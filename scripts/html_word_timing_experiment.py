from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+(?:[-'][A-Za-zА-Яа-яЁё0-9]+)?")
FRAME_SELECTORS = [".scene-frame", ".frame", "[data-scene-frame]", ".scene-card", "article"]
DEFAULT_CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@dataclass(frozen=True)
class SourceWord:
    fragment_id: int
    text: str
    norm: str
    index: int
    start_sec: float
    end_sec: float


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate word timings for visible HTML text without extra markup.")
    parser.add_argument("--scene-pipeline", default="outputs/scene-pipeline.json")
    parser.add_argument("--html-layouts", default="outputs/html-layouts.json")
    parser.add_argument("--out", default="outputs/html-word-timing-experiment.json")
    parser.add_argument("--chrome-path", default=DEFAULT_CHROME_PATH)
    args = parser.parse_args()
    asyncio.run(run(args))
    return 0


async def run(args: argparse.Namespace) -> None:
    scene_batch = json.loads(Path(args.scene_pipeline).read_text(encoding="utf-8"))
    html_batch = json.loads(Path(args.html_layouts).read_text(encoding="utf-8"))
    scene_by_post_id = {item["post_id"]: item for item in scene_batch["items"]}

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is required. Run `pip install -e .`.") from exc

    results: list[dict[str, Any]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=args.chrome_path)
        page = await browser.new_page(viewport={"width": 1440, "height": 1600}, device_scale_factor=1)
        for html_item in html_batch["items"]:
            scene_item = scene_by_post_id.get(html_item["post_id"])
            if not scene_item:
                continue
            html_path = Path(html_item["html_path"])
            await page.goto(html_path.resolve().as_uri(), wait_until="load")
            visible_nodes = await page.evaluate(_EXTRACT_TEXT_SCRIPT, FRAME_SELECTORS)
            results.append(analyze_item(scene_item, html_item, visible_nodes))
        await browser.close()

    summary = build_summary(results)
    payload = {"summary": summary, "items": results}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Wrote {out_path}")


def analyze_item(scene_item: dict[str, Any], html_item: dict[str, Any], visible_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    source_words_by_fragment = build_source_words(scene_item)
    scenes = scene_item.get("scene_plan", {}).get("scenes", [])
    timed_fragments = {int(fragment["fragment_id"]): fragment for fragment in scene_item.get("timed_fragments", [])}

    words: list[dict[str, Any]] = []
    row_match_scores: list[float] = []
    text_nodes: list[dict[str, Any]] = []

    for node_index, node in enumerate(visible_nodes, start=1):
        scene_index = int(node["scene_index"])
        scene = scenes[scene_index - 1] if 0 < scene_index <= len(scenes) else {}
        row_match = match_screen_row(str(node["text"]), scene)
        row_fragment_ids = [int(fragment_id) for fragment_id in row_match["source_fragment_ids"] if _is_intish(fragment_id)]
        scene_fragment_ids = [int(fragment_id) for fragment_id in scene.get("fragment_ids", []) if _is_intish(fragment_id)]
        fragment_ids = row_fragment_ids if row_match["score"] >= 0.45 and row_fragment_ids else scene_fragment_ids
        fallback_fragment_ids = scene_fragment_ids if scene_fragment_ids != fragment_ids else []
        if not fragment_ids:
            fragment_ids = sorted({word.fragment_id for words_ in source_words_by_fragment.values() for word in words_})

        row_match_scores.append(float(row_match["score"]))
        text_node_words = assign_node_words(
            node_id=f"{html_item['post_id']}:s{scene_index}:n{node_index}",
            text=str(node["text"]),
            scene_index=scene_index,
            source_fragment_ids=fragment_ids,
            fallback_fragment_ids=fallback_fragment_ids,
            source_words_by_fragment=source_words_by_fragment,
            timed_fragments=timed_fragments,
            row_match=row_match,
        )
        words.extend(text_node_words)
        text_nodes.append(
            {
                "scene_index": scene_index,
                "node_index": node_index,
                "text": node["text"],
                "tag": node.get("tag"),
                "class_name": node.get("class_name"),
                "row_match": row_match,
                "word_count": len(text_node_words),
            }
        )

    strategy_counts = Counter(word["timing_strategy"] for word in words)
    hard_errors = sum(1 for word in words if word["timing_strategy"] == "failed")
    low_confidence = sum(1 for word in words if float(word["confidence"]) < 0.7)
    row_matches = sum(1 for score in row_match_scores if score >= 0.45)
    interpolated = sum(1 for word in words if str(word["timing_strategy"]).startswith("interpolated_"))

    return {
        "post_id": scene_item["post_id"],
        "title": scene_item["title"],
        "html_path": html_item["html_path"],
        "visible_text_nodes": len(text_nodes),
        "visible_words": len(words),
        "row_match_rate": _rate(row_matches, len(row_match_scores)),
        "direct_word_match_rate": _rate(strategy_counts["exact_word"] + strategy_counts["fuzzy_word"], len(words)),
        "interpolation_rate": _rate(interpolated, len(words)),
        "fallback_rate": _rate(strategy_counts["distributed"], len(words)),
        "hard_error_rate": _rate(hard_errors, len(words)),
        "low_confidence_rate": _rate(low_confidence, len(words)),
        "strategy_counts": dict(strategy_counts),
        "text_nodes": text_nodes,
        "words": words,
    }


def build_source_words(scene_item: dict[str, Any]) -> dict[int, list[SourceWord]]:
    alignment = scene_item.get("alignment", {}).get("alignment", {})
    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    alignment_text = "".join(str(character) for character in characters)
    words_by_fragment: dict[int, list[SourceWord]] = {}
    cursor = 0
    source_index = 0

    for fragment in scene_item.get("timed_fragments", []):
        fragment_id = int(fragment["fragment_id"])
        fragment_text = str(fragment["text"])
        fragment_start = alignment_text.find(fragment_text, cursor)
        if fragment_start < 0:
            fragment_start = cursor
            fragment_end = min(len(alignment_text), fragment_start + len(fragment_text))
        else:
            fragment_end = fragment_start + len(fragment_text)
        cursor = fragment_end
        fragment_words: list[SourceWord] = []
        local_matches = list(WORD_RE.finditer(fragment_text))
        for local_index, match in enumerate(local_matches):
            start_index = fragment_start + match.start()
            end_index = fragment_start + match.end() - 1
            start_sec = _time_at(starts, start_index, fallback=float(fragment.get("start_sec", 0.0)))
            end_sec = _time_at(ends, end_index, fallback=float(fragment.get("end_sec", start_sec + 0.05)))
            if end_sec <= start_sec:
                end_sec = start_sec + 0.05
            fragment_words.append(
                SourceWord(
                    fragment_id=fragment_id,
                    text=match.group(0),
                    norm=normalize_word(match.group(0)),
                    index=source_index,
                    start_sec=round(start_sec, 3),
                    end_sec=round(end_sec, 3),
                )
            )
            source_index += 1
        words_by_fragment[fragment_id] = fragment_words
    return words_by_fragment


def match_screen_row(text: str, scene: dict[str, Any]) -> dict[str, Any]:
    rows = scene.get("screen_rows") or []
    if not rows:
        return {"score": 0.0, "row_text": "", "source_fragment_ids": []}
    best_score = -1.0
    best_row: dict[str, Any] = {}
    for row in rows:
        score = text_similarity(text, str(row.get("text", "")))
        if score > best_score:
            best_score = score
            best_row = row
    return {
        "score": round(max(0.0, best_score), 3),
        "row_text": best_row.get("text", ""),
        "source_fragment_ids": best_row.get("source_fragment_ids", []),
    }


def assign_node_words(
    *,
    node_id: str,
    text: str,
    scene_index: int,
    source_fragment_ids: list[int],
    fallback_fragment_ids: list[int],
    source_words_by_fragment: dict[int, list[SourceWord]],
    timed_fragments: dict[int, dict[str, Any]],
    row_match: dict[str, Any],
) -> list[dict[str, Any]]:
    html_words = list(WORD_RE.finditer(text))
    candidates: list[SourceWord] = []
    for fragment_id in source_fragment_ids:
        candidates.extend(source_words_by_fragment.get(fragment_id, []))
    candidates.sort(key=lambda word: word.index)
    fallback_candidates: list[SourceWord] = []
    for fragment_id in fallback_fragment_ids:
        fallback_candidates.extend(source_words_by_fragment.get(fragment_id, []))
    fallback_candidates.sort(key=lambda word: word.index)

    window_start, window_end = timing_window(source_fragment_ids, timed_fragments)
    last_candidate_index = -1
    assigned: list[dict[str, Any]] = []

    for word_index, match in enumerate(html_words):
        raw_word = match.group(0)
        norm_word = normalize_word(raw_word)
        best: tuple[float, str, SourceWord | None] = (0.0, "failed", None)
        for candidate in candidates:
            if candidate.index <= last_candidate_index:
                continue
            score, strategy = word_match_score(norm_word, candidate.norm)
            if score > best[0]:
                best = (score, strategy, candidate)
        if best[2] is None or best[0] < threshold_for_word(norm_word, best[1]):
            for candidate in fallback_candidates:
                if candidate.index <= last_candidate_index:
                    continue
                score, strategy = word_match_score(norm_word, candidate.norm)
                if score > best[0]:
                    best = (score, strategy, candidate)

        score, strategy, candidate = best
        if candidate is not None and score >= threshold_for_word(norm_word, strategy):
            last_candidate_index = candidate.index
            start_sec = candidate.start_sec
            end_sec = candidate.end_sec
            confidence = 1.0 if strategy == "exact_word" else round(score * 0.82, 3)
            matched_source_word = candidate.text
            matched_fragment_id = candidate.fragment_id
        else:
            start_sec = None
            end_sec = None
            confidence = 0.0
            strategy = "pending_interpolation"
            matched_source_word = None
            matched_fragment_id = None

        assigned.append(
            {
                "word_id": f"{node_id}:w{word_index + 1}",
                "scene_index": scene_index,
                "node_text": text,
                "word": raw_word,
                "source_fragment_ids": source_fragment_ids,
                "matched_fragment_id": matched_fragment_id,
                "matched_source_word": matched_source_word,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "appear_sec": start_sec,
                "timing_strategy": strategy,
                "confidence": confidence,
                "row_match_score": row_match["score"],
                "row_match_text": row_match["row_text"],
            }
        )
    return interpolate_missing_word_timings(
        assigned,
        window_start=window_start,
        window_end=window_end,
        row_match_score=float(row_match["score"]),
    )


def interpolate_missing_word_timings(
    words: list[dict[str, Any]],
    *,
    window_start: float | None,
    window_end: float | None,
    row_match_score: float,
) -> list[dict[str, Any]]:
    if not words:
        return words
    timed_indexes = [index for index, word in enumerate(words) if isinstance(word.get("start_sec"), (int, float))]
    if not timed_indexes:
        return distribute_missing_run(
            words,
            indexes=list(range(len(words))),
            start_sec=window_start,
            end_sec=window_end,
            strategy="distributed",
            confidence=0.45 if row_match_score >= 0.45 else 0.32,
        )

    pending_indexes = [index for index, word in enumerate(words) if word["timing_strategy"] == "pending_interpolation"]
    for index in pending_indexes:
        previous_timed = max((candidate for candidate in timed_indexes if candidate < index), default=None)
        next_timed = min((candidate for candidate in timed_indexes if candidate > index), default=None)
        if previous_timed is not None and next_timed is not None:
            run = list(range(previous_timed + 1, next_timed))
            start = float(words[previous_timed]["start_sec"])
            end = float(words[next_timed]["start_sec"])
            distribute_missing_run(
                words,
                indexes=run,
                start_sec=start,
                end_sec=end,
                strategy="interpolated_between_words",
                confidence=0.66,
            )
        elif previous_timed is not None:
            run = list(range(previous_timed + 1, len(words)))
            start = float(words[previous_timed]["end_sec"] or words[previous_timed]["start_sec"])
            end = window_end
            distribute_missing_run(
                words,
                indexes=run,
                start_sec=start,
                end_sec=end,
                strategy="interpolated_after_word",
                confidence=0.58,
            )
        elif next_timed is not None:
            run = list(range(0, next_timed))
            start = window_start
            end = float(words[next_timed]["start_sec"])
            distribute_missing_run(
                words,
                indexes=run,
                start_sec=start,
                end_sec=end,
                strategy="interpolated_before_word",
                confidence=0.58,
            )

    for word in words:
        if word["timing_strategy"] == "pending_interpolation":
            word["timing_strategy"] = "failed"
    return words


def distribute_missing_run(
    words: list[dict[str, Any]],
    *,
    indexes: list[int],
    start_sec: float | None,
    end_sec: float | None,
    strategy: str,
    confidence: float,
) -> list[dict[str, Any]]:
    missing_indexes = [index for index in indexes if words[index]["timing_strategy"] == "pending_interpolation"]
    if not missing_indexes:
        return words
    if start_sec is None or end_sec is None or end_sec <= start_sec:
        for index in missing_indexes:
            words[index]["timing_strategy"] = "failed"
        return words
    step = (end_sec - start_sec) / (len(missing_indexes) + 1)
    for offset, index in enumerate(missing_indexes, start=1):
        appear_sec = round(start_sec + (step * offset), 3)
        words[index]["start_sec"] = appear_sec
        words[index]["end_sec"] = round(min(end_sec, appear_sec + max(0.05, step * 0.72)), 3)
        words[index]["appear_sec"] = appear_sec
        words[index]["timing_strategy"] = strategy
        words[index]["confidence"] = confidence
    return words


def timing_window(fragment_ids: list[int], timed_fragments: dict[int, dict[str, Any]]) -> tuple[float | None, float | None]:
    fragments = [timed_fragments[fragment_id] for fragment_id in fragment_ids if fragment_id in timed_fragments]
    if not fragments:
        return None, None
    return min(float(fragment["start_sec"]) for fragment in fragments), max(float(fragment["end_sec"]) for fragment in fragments)


def word_match_score(html_norm: str, source_norm: str) -> tuple[float, str]:
    if not html_norm or not source_norm:
        return 0.0, "failed"
    if html_norm == source_norm:
        return 1.0, "exact_word"
    if len(html_norm) < 4 or len(source_norm) < 4:
        return 0.0, "failed"
    ratio = SequenceMatcher(None, html_norm, source_norm).ratio()
    prefix_bonus = 0.08 if html_norm[:4] == source_norm[:4] else 0.0
    return min(0.99, ratio + prefix_bonus), "fuzzy_word"


def threshold_for_word(norm_word: str, strategy: str) -> float:
    if strategy == "exact_word":
        return 1.0
    if len(norm_word) <= 4:
        return 0.88
    return 0.74


def text_similarity(left: str, right: str) -> float:
    left_tokens = normalize_tokens(left)
    right_tokens = normalize_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    left_text = " ".join(left_tokens)
    right_text = " ".join(right_tokens)
    char_ratio = SequenceMatcher(None, left_text, right_text).ratio()
    intersection = len(set(left_tokens) & set(right_tokens))
    union = max(1, len(set(left_tokens) | set(right_tokens)))
    jaccard = intersection / union
    return round((char_ratio * 0.65) + (jaccard * 0.35), 3)


def normalize_tokens(text: str) -> list[str]:
    return [normalize_word(match.group(0)) for match in WORD_RE.finditer(text) if normalize_word(match.group(0))]


def normalize_word(word: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", "", word.lower().replace("ё", "е"))


def build_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total_words = sum(item["visible_words"] for item in items)
    total_nodes = sum(item["visible_text_nodes"] for item in items)
    strategy_counts: Counter[str] = Counter()
    low_confidence = 0
    row_match_weighted = 0.0
    direct_weighted = 0.0
    fallback_weighted = 0.0
    interpolation_weighted = 0.0
    hard_error_weighted = 0.0
    for item in items:
        strategy_counts.update(item["strategy_counts"])
        low_confidence += round(item["low_confidence_rate"] * item["visible_words"])
        row_match_weighted += item["row_match_rate"] * item["visible_text_nodes"]
        direct_weighted += item["direct_word_match_rate"] * item["visible_words"]
        interpolation_weighted += item.get("interpolation_rate", 0.0) * item["visible_words"]
        fallback_weighted += item["fallback_rate"] * item["visible_words"]
        hard_error_weighted += item["hard_error_rate"] * item["visible_words"]

    return {
        "items": len(items),
        "visible_text_nodes": total_nodes,
        "visible_words": total_words,
        "row_match_rate": _rate(row_match_weighted, total_nodes),
        "direct_word_match_rate": _rate(direct_weighted, total_words),
        "interpolation_rate": _rate(interpolation_weighted, total_words),
        "fallback_rate": _rate(fallback_weighted, total_words),
        "hard_error_rate": _rate(hard_error_weighted, total_words),
        "low_confidence_rate": _rate(low_confidence, total_words),
        "strategy_counts": dict(strategy_counts),
        "worst_items_by_low_confidence": [
            {
                "post_id": item["post_id"],
                "title": item["title"],
                "visible_words": item["visible_words"],
                "low_confidence_rate": item["low_confidence_rate"],
                "direct_word_match_rate": item["direct_word_match_rate"],
            }
            for item in sorted(items, key=lambda value: value["low_confidence_rate"], reverse=True)[:5]
        ],
    }


def _time_at(values: list[Any], index: int, *, fallback: float) -> float:
    if not values:
        return fallback
    index = max(0, min(index, len(values) - 1))
    value = values[index]
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else fallback


def _rate(numerator: float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


def _is_intish(value: Any) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


_EXTRACT_TEXT_SCRIPT = r"""
(selectors) => {
  const selector = selectors.find((sel) => document.querySelectorAll(sel).length >= 1) || '.scene-frame';
  const frames = Array.from(document.querySelectorAll(selector));
  const nodes = [];

  function visible(el) {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 1 && rect.height > 1;
  }

  function skipElement(el) {
    if (!el) return true;
    if (el.closest('script, style, noscript, [data-asset-id], .media-ph, .media-slot, .scene-meta, .meta, .metadata')) return true;
    return !visible(el);
  }

  frames.forEach((frame, frameIndex) => {
    const walker = document.createTreeWalker(frame, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const textNode = walker.currentNode;
      const text = (textNode.textContent || '').replace(/\s+/g, ' ').trim();
      if (!text) continue;
      const parent = textNode.parentElement;
      if (skipElement(parent)) continue;
      if (!/[A-Za-zА-Яа-яЁё0-9]/.test(text)) continue;
      const rect = parent.getBoundingClientRect();
      nodes.push({
        scene_index: frameIndex + 1,
        text,
        tag: parent.tagName.toLowerCase(),
        class_name: parent.className ? String(parent.className) : '',
        rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
      });
    }
  });

  return nodes;
}
"""


if __name__ == "__main__":
    raise SystemExit(main())
