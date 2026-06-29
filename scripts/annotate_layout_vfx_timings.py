from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit2video.gemini import GeminiClient  # noqa: E402


DEFAULT_INPUT = (
    ROOT
    / "outputs/girly-static-v5/e2e-4-pronunciation-design-fixpass/"
    / "html-layouts-final/1ttwsvc.html-layout.generated.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "outputs/quality-oracle/layout-b-staged-vfx/"
    / "1ttwsvc.b-layout-staged-vfx.html-layout.generated.json"
)
DEFAULT_COMPOSITION_ID = "girly-static-v5-b-layout-staged-vfx-1ttwsvc"


class VfxTimingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(description="Exact CSS selector from the input element list.")
    appear_frame: int = Field(description="Frame inside the scene where reveal starts.")
    cue_word: Optional[str] = Field(default=None, description="Transcript word or phrase used as cue, if any.")
    role: str = Field(description="media | card | label | decoration | non_caption_text")
    confidence: str = Field(default="gemini", description="gemini | deterministic_fallback")


class SceneVfxTimingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: int
    timings: list[VfxTimingItem]


class VfxTimingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenes: list[SceneVfxTimingPlan]


@dataclass(frozen=True)
class VisualCandidate:
    target: str
    role: str
    tag: str
    classes: list[str]
    text: str
    asset_id: str | None = None
    slot: str | None = None
    existing_appear_frame: int | None = None
    existing_cue_word: str | None = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Annotate an existing B html-layout payload with layout-only staged VFX timings."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--composition-id", default=DEFAULT_COMPOSITION_ID)
    parser.add_argument("--model", default="gemini-3-flash-preview")
    parser.add_argument("--env-file", action="append", default=[".env.iac", ".env"])
    parser.add_argument("--no-gemini", action="store_true")
    parser.add_argument("--force", action="store_true", help="Ignore cached Gemini timing plan.")
    parser.add_argument("--cache", type=Path, default=None, help="Cached Gemini JSON timing plan path.")
    args = parser.parse_args()

    for env_file in args.env_file:
        load_env_file(ROOT / env_file)

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    candidates_by_scene = extract_visual_candidates_by_scene(payload)
    cache_path = args.cache or args.output.with_name(args.output.name.replace(".json", ".gemini-plan.json"))

    if args.no_gemini:
        plan = deterministic_timing_plan(payload, candidates_by_scene)
        method = "deterministic_fallback"
    else:
        plan, method = asyncio.run(load_or_request_gemini_plan(payload, candidates_by_scene, cache_path, args))

    annotated = annotate_payload(
        payload,
        candidates_by_scene=candidates_by_scene,
        timing_plan=plan,
        method=method,
        model=args.model,
        composition_id=args.composition_id,
        source_payload=args.input,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(annotated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    total_timings = sum(len(scene.get("vfx_timings") or []) for scene in annotated["scenes"])
    print(f"wrote {args.output}")
    print(f"method={method} scenes={len(annotated['scenes'])} vfx_timings={total_timings}")
    if not args.no_gemini:
        print(f"gemini_plan_cache={cache_path}")


async def load_or_request_gemini_plan(
    payload: dict[str, Any],
    candidates_by_scene: dict[int, list[VisualCandidate]],
    cache_path: Path,
    args: argparse.Namespace,
) -> tuple[VfxTimingPlan, str]:
    if cache_path.exists() and not args.force:
        try:
            return VfxTimingPlan.model_validate_json(cache_path.read_text(encoding="utf-8")), "gemini_cached"
        except (ValidationError, json.JSONDecodeError) as exc:
            print(f"warning: ignoring invalid cached Gemini plan {cache_path}: {exc}", file=sys.stderr)

    prompt = build_gemini_prompt(payload, candidates_by_scene)
    client = GeminiClient.from_env(model=str(args.model), vertex=True)
    try:
        plan = await client.generate_structured(prompt=prompt, response_model=VfxTimingPlan)
    except Exception as exc:  # noqa: BLE001 - this script must fail soft to preserve renderability.
        print(f"warning: Gemini timing annotation failed, using deterministic fallback: {exc}", file=sys.stderr)
        return deterministic_timing_plan(payload, candidates_by_scene), "deterministic_fallback"
    finally:
        await client.aclose()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    return plan, "gemini"


def annotate_payload(
    payload: dict[str, Any],
    *,
    candidates_by_scene: dict[int, list[VisualCandidate]],
    timing_plan: VfxTimingPlan,
    method: str,
    model: str,
    composition_id: str,
    source_payload: Path | None = None,
) -> dict[str, Any]:
    annotated = copy.deepcopy(payload)
    annotated["composition_id"] = composition_id
    annotated["layout_mode"] = "b_layout_staged_vfx"
    metadata = dict(annotated.get("metadata") or {})
    metadata["vfx_timing_annotation"] = {
        "kind": "layout_only_non_caption_reveal",
        "method": method,
        "model": model,
        "source_payload": stable_path(source_payload) if source_payload else None,
        "preserves_asset_paths": True,
    }
    annotated["metadata"] = metadata

    plan_by_scene = {scene.scene_id: scene for scene in timing_plan.scenes}
    for scene in annotated.get("scenes") or []:
        scene_id = int(scene.get("scene_id") or 0)
        candidates = candidates_by_scene.get(scene_id, [])
        planned = plan_by_scene.get(scene_id)
        scene["vfx_timings"] = normalized_scene_timings(scene, candidates, planned)
    return annotated


def normalized_scene_timings(
    scene: dict[str, Any],
    candidates: list[VisualCandidate],
    planned: SceneVfxTimingPlan | None,
) -> list[dict[str, Any]]:
    duration = int(scene.get("duration_frames") or 1)
    candidate_by_target = {candidate.target: candidate for candidate in candidates}
    result: list[VfxTimingItem] = []
    seen: set[str] = set()

    if planned:
        for item in planned.timings:
            candidate = candidate_by_target.get(item.target)
            if not candidate or item.target in seen:
                continue
            result.append(
                VfxTimingItem(
                    target=item.target,
                    appear_frame=clamp_int(item.appear_frame, 0, max(0, duration - 1)),
                    cue_word=item.cue_word or None,
                    role=candidate.role,
                    confidence=item.confidence or "gemini",
                )
            )
            seen.add(item.target)

    fallback_plan = deterministic_timing_plan({"scenes": [scene]}, {int(scene.get("scene_id") or 0): candidates})
    fallback_by_target = {
        item.target: item
        for scene_plan in fallback_plan.scenes
        for item in scene_plan.timings
    }
    for candidate in candidates:
        if candidate.target in seen:
            continue
        fallback = fallback_by_target[candidate.target]
        result.append(fallback)
        seen.add(candidate.target)

    result.sort(key=lambda item: (item.appear_frame, item.target))
    return [item.model_dump(exclude_none=True) for item in result]


def extract_visual_candidates_by_scene(payload: dict[str, Any]) -> dict[int, list[VisualCandidate]]:
    return {
        int(scene.get("scene_id") or 0): extract_scene_visual_candidates(scene)
        for scene in payload.get("scenes") or []
    }


def extract_scene_visual_candidates(scene: dict[str, Any]) -> list[VisualCandidate]:
    html = str(scene.get("html") or "")
    asset_timings = scene.get("asset_timings") or {}
    candidates: list[VisualCandidate] = []
    seen: set[str] = set()

    for match in re.finditer(r"<([a-z0-9]+)\b([^>]*)>", html, flags=re.IGNORECASE):
        tag = (match.group(1) or "").lower()
        attrs = match.group(2) or ""
        classes = class_tokens(attrs)
        if should_skip_element(tag, attrs, classes):
            continue
        if not attr_value(attrs, "data-asset-id") and inner_contains_sync_caption(html, match.end(), tag):
            continue
        asset_id = attr_value(attrs, "data-asset-id") or None
        slot = attr_value(attrs, "data-girly-slot") or None
        role = role_for_element(attrs, classes, bool(asset_id))
        target = target_selector(asset_id, slot, classes)
        if not target or target in seen:
            continue
        text = visible_text_snippet(html, match.end(), tag)
        timing = asset_timings.get(asset_id or "") if asset_id else None
        existing_appear_frame = safe_int((timing or {}).get("appear_frame")) if isinstance(timing, dict) else None
        existing_cue_word = str((timing or {}).get("appears_on_word") or "") or None if isinstance(timing, dict) else None
        seen.add(target)
        candidates.append(
            VisualCandidate(
                target=target,
                role=role,
                tag=tag,
                classes=classes,
                text=text,
                asset_id=asset_id,
                slot=slot,
                existing_appear_frame=existing_appear_frame,
                existing_cue_word=existing_cue_word,
            )
        )

    return candidates[:24]


def should_skip_element(tag: str, attrs: str, classes: list[str]) -> bool:
    class_text = " ".join(classes)
    if tag in {"script", "style", "source"}:
        return True
    if "girly-sync-caption" in class_text or "sync-word" in class_text or "voiceoverSyncText" in class_text:
        return True
    if attr_value(attrs, "data-girly-sync-caption").lower() == "true":
        return True
    if "girly-media-fill" in class_text and not attr_value(attrs, "data-asset-id"):
        return True
    if set(classes).issubset({"scene", "scene-frame", "textonly", "avatar"}):
        return True
    if not visual_enough(attrs, classes):
        return True
    return False


def inner_contains_sync_caption(html: str, start: int, tag: str) -> bool:
    close = re.search(rf"</{re.escape(tag)}>", html[start:], flags=re.IGNORECASE)
    if not close:
        return False
    inner = html[start : start + close.start()]
    return bool(re.search(r"(girly-sync-caption|sync-word|data-girly-sync-caption)", inner, flags=re.IGNORECASE))


def visual_enough(attrs: str, classes: list[str]) -> bool:
    if attr_value(attrs, "data-asset-id"):
        return True
    if attr_value(attrs, "data-girly-slot") or attr_value(attrs, "data-girly-role"):
        return True
    if attr_value(attrs, "data-girly-filled-text").lower() == "true":
        return True
    class_text = " ".join(classes)
    return bool(
        re.search(
            r"(card|note|label|badge|tag|frame|tape|star|bar|panel|poster|headline|kicker|source|accent|line|shape|photo|video|image|thumb)",
            class_text,
            flags=re.IGNORECASE,
        )
    )


def role_for_element(attrs: str, classes: list[str], has_asset: bool) -> str:
    if has_asset:
        return "media"
    class_text = " ".join(classes)
    if attr_value(attrs, "data-girly-filled-text").lower() == "true":
        return "non_caption_text"
    if re.search(r"(label|badge|tag|kicker|source)", class_text, flags=re.IGNORECASE):
        return "label"
    if re.search(r"(card|note|panel|poster|headline)", class_text, flags=re.IGNORECASE):
        return "card"
    return "decoration"


def target_selector(asset_id: str | None, slot: str | None, classes: list[str]) -> str | None:
    if asset_id:
        return f'[data-asset-id="{css_attr(asset_id)}"]'
    if slot:
        return f'[data-girly-slot="{css_attr(slot)}"]'
    specific = [cls for cls in classes if re.match(r"^s\d+[-_]", cls)]
    useful = specific or [
        cls for cls in classes if not re.match(r"^(scene|scene-frame|sync-text|sync-word|girly-)", cls)
    ]
    if not useful:
        return None
    return "." + ".".join(css_class(cls) for cls in useful[:2])


def deterministic_timing_plan(
    payload: dict[str, Any],
    candidates_by_scene: dict[int, list[VisualCandidate]],
) -> VfxTimingPlan:
    scenes: list[SceneVfxTimingPlan] = []
    for scene in payload.get("scenes") or []:
        scene_id = int(scene.get("scene_id") or 0)
        duration = int(scene.get("duration_frames") or 1)
        words = scene_words(scene)
        timings: list[VfxTimingItem] = []
        for index, candidate in enumerate(candidates_by_scene.get(scene_id, [])):
            cue_word = candidate.existing_cue_word
            appear_frame = candidate.existing_appear_frame
            matched = semantic_word_frame(candidate, words)
            if matched:
                cue_word, appear_frame = matched
            if appear_frame is None:
                appear_frame = staged_fallback_frame(index, candidate.role, duration)
            timings.append(
                VfxTimingItem(
                    target=candidate.target,
                    appear_frame=clamp_int(appear_frame, 0, max(0, duration - 1)),
                    cue_word=cue_word,
                    role=candidate.role,
                    confidence="deterministic_fallback",
                )
            )
        scenes.append(SceneVfxTimingPlan(scene_id=scene_id, timings=timings))
    return VfxTimingPlan(scenes=scenes)


def semantic_word_frame(candidate: VisualCandidate, words: list[dict[str, Any]]) -> tuple[str, int] | None:
    haystack = normalize_text(" ".join([candidate.text, candidate.slot or "", candidate.asset_id or "", " ".join(candidate.classes)]))
    terms = [term for term in re.split(r"\s+", haystack) if len(term) >= 4]
    if not terms:
        return None
    for word in words:
        raw = str(word.get("text") or word.get("word") or "")
        normalized = normalize_text(raw)
        if not normalized:
            continue
        if any(term.startswith(normalized) or normalized.startswith(term) for term in terms):
            frame = safe_int(word.get("appear_frame"))
            if frame is not None:
                return raw, frame
    return None


def staged_fallback_frame(index: int, role: str, duration: int) -> int:
    step = max(4, min(9, int(round(duration * 0.045))))
    role_offset = {
        "card": 0,
        "non_caption_text": 2,
        "label": 5,
        "media": 8,
        "decoration": -2,
    }.get(role, 4)
    frame = 4 + index * step + role_offset
    return clamp_int(frame, 0, max(0, int(duration * 0.55)))


def build_gemini_prompt(payload: dict[str, Any], candidates_by_scene: dict[int, list[VisualCandidate]]) -> str:
    scenes = []
    for scene in payload.get("scenes") or []:
        scene_id = int(scene.get("scene_id") or 0)
        candidates = candidates_by_scene.get(scene_id, [])
        scenes.append(
            {
                "scene_id": scene_id,
                "duration_frames": scene.get("duration_frames"),
                "transcript_words": scene_words(scene),
                "elements": [candidate_for_prompt(candidate) for candidate in candidates],
            }
        )
    compact = json.dumps(
        {"fps": payload.get("fps"), "scenes": scenes},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "You are a layout-only motion timing annotator for a short vertical Remotion video.\n"
        "Do not judge media quality. Do not rewrite any text. Do not add or remove elements.\n"
        "Choose appear_frame timings only for the provided non-caption visual elements.\n"
        "Never include .girly-sync-caption or .sync-word targets. Subtitles are controlled elsewhere.\n"
        "Rhythm: at frames 0-10 the scene should be incomplete, by 50% mostly assembled, by 90% fully assembled.\n"
        "Tie important media/cards/text to meaningful transcript cue words when possible. Decorative elements may appear 4-10 frames around nearby main elements.\n"
        "Return exactly one timing for every input element target. target must exactly match input. "
        "confidence must be gemini. role must keep the input role. appear_frame must be an integer inside the scene.\n"
        "Return JSON only matching this schema: {\"scenes\":[{\"scene_id\":1,\"timings\":[{\"target\":\"...\",\"appear_frame\":0,\"cue_word\":\"...\",\"role\":\"media\",\"confidence\":\"gemini\"}]}]}.\n"
        f"Input:\n{compact}"
    )


def candidate_for_prompt(candidate: VisualCandidate) -> dict[str, Any]:
    return {
        "target": candidate.target,
        "role": candidate.role,
        "tag": candidate.tag,
        "classes": candidate.classes[:5],
        "text": candidate.text,
        "asset_id": candidate.asset_id,
        "slot": candidate.slot,
        "existing_appear_frame": candidate.existing_appear_frame,
        "existing_cue_word": candidate.existing_cue_word,
    }


def scene_words(scene: dict[str, Any]) -> list[dict[str, Any]]:
    words = []
    for word in scene.get("word_timings") or []:
        text = str(word.get("word") or word.get("text") or "").strip()
        frame = safe_int(word.get("appear_frame"))
        if not text or frame is None:
            continue
        words.append({"text": text, "appear_frame": frame})
    return words


def visible_text_snippet(html: str, start: int, tag: str) -> str:
    close = re.search(rf"</{re.escape(tag)}>", html[start:], flags=re.IGNORECASE)
    if not close:
        return ""
    inner = html[start : start + close.start()]
    text = re.sub(r"<[^>]+>", " ", inner)
    text = decode_html_entities(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120]


def attr_value(attrs: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*(['\"])(.*?)\1", attrs, flags=re.IGNORECASE | re.DOTALL)
    return decode_html_entities(match.group(2)) if match else ""


def class_tokens(attrs: str) -> list[str]:
    return [token for token in re.split(r"\s+", attr_value(attrs, "class").strip()) if token]


def decode_html_entities(text: str) -> str:
    return (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def normalize_text(text: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", " ", text.lower().replace("ё", "е")).strip()


def css_attr(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def css_class(value: str) -> str:
    return re.sub(r"([^a-zA-Z0-9_-])", lambda match: "\\" + match.group(1), value)


def safe_int(value: Any) -> int | None:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return number


def clamp_int(value: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, int(value)))


def stable_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    main()
