#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.append(str(ROOT_DIR / "src"))

from reddit2video.girly_static_renderer import (  # noqa: E402
    format_timed_text_html,
    materialize_scenes_for_girly_static,
    render_girly_static_scene,
)
from reddit2video.media_asset_hygiene import publication_render_asset_hygiene_rejection_reason  # noqa: E402
from reddit2video.story_format_cookbook import (  # noqa: E402
    DEFAULT_REEL_TEMPLATE_FAMILY,
    TEMPLATE_FAMILY_VERSION,
    extract_story_format,
    reel_template_family,
    story_format_spec,
    validate_story_format_payload,
)
from reddit2video.word_timing import (  # noqa: E402
    align_words_to_character_alignment,
    normalize_timed_word_tokens,
    normalize_token_core,
)

DEFAULT_STYLE_HTML = "assets/style_packs/static_girly_2/index.html"
DEFAULT_OUT = "remotion/src/html-layout.generated.json"
LOCAL_RENDER_SOFT_HYGIENE_REASONS = {
    "low_information_title_asset",
    "render_long_creator_caption_asset",
    "render_low_information_pinterest_asset",
    "social_caption_campaign_asset",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert storyboard_v2/static_girly_2 input into Remotion html-layout.generated.json payload."
    )
    parser.add_argument("--input", required=True, help="Storyboard item, storyboard_v2 payload, or batch JSON.")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output Remotion HtmlLayout payload JSON path.")
    parser.add_argument("--item-index", type=int, default=0, help="Batch item index to render when --all-items is not set.")
    parser.add_argument("--all-items", action="store_true", help="Render every batch item into one composition.")
    parser.add_argument(
        "--media-resolver",
        default="",
        help="Optional media resolver JSON; selected slots are merged into storyboard scenes by post_id/scene_id.",
    )
    parser.add_argument("--audio-public-path", default="", help="Optional Remotion public audio path, e.g. audio/post.mp3.")
    parser.add_argument("--alignment", default="", help="Optional Inworld/ElevenLabs timestamp alignment JSON.")
    parser.add_argument("--scene-lines", default="", help="Optional TTS scene-lines JSON with exact voiceover_line text.")
    parser.add_argument(
        "--sync-caption-mode",
        choices=["off", "overlay", "replace"],
        default="overlay",
        help="Add full voiceover timed caption overlay; replace hides template spoken-fragment text.",
    )
    parser.add_argument("--composition-id", default="", help="Optional Remotion composition id.")
    parser.add_argument("--style-html", default=DEFAULT_STYLE_HTML, help="static_girly_2 index.html template path.")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--default-scene-sec", type=float, default=3.0)
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    storyboard_payloads = _select_storyboard_payloads(payload, item_index=args.item_index, all_items=args.all_items)
    if not storyboard_payloads:
        raise SystemExit("No storyboard_v2-compatible payloads found.")
    story_format_metadata = _story_format_metadata(storyboard_payloads)
    post_ids = _selected_post_ids(payload, item_index=args.item_index, all_items=args.all_items)
    resolver_items = _resolver_items(args.media_resolver)
    scene_line_overrides = _load_scene_lines(args.scene_lines)
    alignment_payload = _load_json_optional(args.alignment)

    style_html = Path(args.style_html).read_text(encoding="utf-8")
    scenes: list[dict[str, Any]] = []
    source_scenes: list[dict[str, Any]] = []
    for index, storyboard_payload in enumerate(storyboard_payloads):
        storyboard_payload = _merge_resolved_slots(
            storyboard_payload,
            resolver_items=resolver_items,
            post_id=post_ids[index] if index < len(post_ids) else "",
            item_index=index,
        )
        materialized = materialize_scenes_for_girly_static(storyboard_payload)
        scenes.extend(materialized)
        source_scenes.extend(_storyboard_scenes(storyboard_payload) or materialized)
    if not scenes:
        raise SystemExit("No scenes found in selected storyboard payload.")

    voiceover_by_scene, scene_spans, full_voiceover_text = _voiceover_scene_spans(
        source_scenes=source_scenes,
        scene_line_overrides=scene_line_overrides,
    )
    timed_words, word_warnings = _timed_words_from_alignment(
        voiceover_text=full_voiceover_text,
        alignment_payload=alignment_payload,
    )
    words_by_scene = _words_by_scene(timed_words, scene_spans=scene_spans)
    timings = _scene_timings_from_words(
        source_scenes=source_scenes,
        words_by_scene=words_by_scene,
        voiceover_by_scene=voiceover_by_scene,
        fps=args.fps,
    ) or _scene_timings(
        source_scenes=source_scenes,
        payloads=storyboard_payloads,
        fps=args.fps,
        default_scene_sec=args.default_scene_sec,
    )
    remotion_scenes: list[dict[str, Any]] = []
    for index, (scene, timing) in enumerate(zip(scenes, timings), start=1):
        scene_id = _scene_id(scene, fallback=index)
        voiceover_line = voiceover_by_scene.get(scene_id) or str(scene.get("voiceover_line") or "").strip()
        if voiceover_line:
            scene["voiceover_line"] = voiceover_line
            if isinstance(scene.get("girly_scene_unit"), dict):
                scene["girly_scene_unit"]["voiceover_line"] = voiceover_line
        scene_words = _word_timings_for_scene(
            words_by_scene.get(scene_id) or [],
            scene_start_sec=float(timing.get("start_sec") or timing["start_frame"] / args.fps),
            fps=args.fps,
        )
        if scene_id == 1:
            _suppress_design_text_slots(scene)
        scene["timed_words_for_render"] = scene_words
        scene_html = render_girly_static_scene(
            scene,
            style_html=style_html,
            allow_rejected_media_for_render=True,
        )
        if args.sync_caption_mode != "off" and voiceover_line:
            scene_html = _inject_sync_caption(
                scene_html,
                voiceover_line=voiceover_line,
                scene=scene,
                mode=args.sync_caption_mode,
            )
        if scene_id == 1:
            scene_html = _strip_design_text_slots(scene_html)
        scene_html, rejected_media_asset_ids = _sanitize_rejected_html_media_slots(scene_html, scene)
        bridge_assets = _bridge_media_assets(scene, scene_html=scene_html)
        remotion_scene = {
            "scene_id": scene_id,
            "start_frame": timing["start_frame"],
            "duration_frames": timing["duration_frames"],
            "asset_timings": _asset_timings(scene, fps=args.fps, word_timings=scene_words),
            "word_timings": scene_words,
            "bridge_media_assets": bridge_assets,
            "html": scene_html,
        }
        if rejected_media_asset_ids:
            remotion_scene["rejected_media_asset_ids"] = rejected_media_asset_ids
        semantic_visual = _semantic_visual(scene, scene_html=scene_html, bridge_assets=bridge_assets)
        if semantic_visual:
            remotion_scene["semantic_visual"] = semantic_visual
        remotion_scenes.append(remotion_scene)

    payload_out = {
        "composition_id": args.composition_id or _composition_id(args.input, payload, storyboard_payloads),
        "fps": args.fps,
        "width": args.width,
        "height": args.height,
        "duration_frames": max(
            scene["start_frame"] + scene["duration_frames"] for scene in remotion_scenes
        ),
        "audio_public_path": args.audio_public_path,
        "post_id": post_ids[0] if post_ids else str(payload.get("post_id") or ""),
        "subreddit": _selected_subreddit(payload, item_index=args.item_index, all_items=args.all_items),
        "story_title": _selected_title(payload, item_index=args.item_index, all_items=args.all_items),
        **story_format_metadata,
        "css": _extract_css(style_html) + _remotion_css_patch(args.width, args.height),
        "scenes": remotion_scenes,
        "word_timing_warnings": word_warnings,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out_path),
                "composition_id": payload_out["composition_id"],
                "duration_frames": payload_out["duration_frames"],
                "duration_sec": round(payload_out["duration_frames"] / args.fps, 3),
                "scenes": len(remotion_scenes),
                "audio_public_path": payload_out["audio_public_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _select_storyboard_payloads(payload: Any, *, item_index: int, all_items: bool) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if _is_storyboard_like(payload):
        return [payload]
    item_payload = _storyboard_payload_from_item(payload)
    if item_payload is not payload or _is_storyboard_like(item_payload):
        return [item_payload]

    items = payload.get("items")
    if not isinstance(items, list):
        return []
    selected = items if all_items else items[item_index : item_index + 1]
    return [_storyboard_payload_from_item(item) for item in selected if isinstance(item, dict)]


def _selected_post_ids(payload: Any, *, item_index: int, all_items: bool) -> list[str]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if isinstance(items, list):
        selected = items if all_items else items[item_index : item_index + 1]
        return [str(item.get("post_id") or "") for item in selected if isinstance(item, dict)]
    return [str(payload.get("post_id") or "")]


def _selected_title(payload: Any, *, item_index: int, all_items: bool) -> str:
    if not isinstance(payload, dict):
        return ""
    items = payload.get("items")
    if isinstance(items, list):
        selected = items if all_items else items[item_index : item_index + 1]
        for item in selected:
            if isinstance(item, dict) and str(item.get("title") or "").strip():
                return str(item.get("title") or "").strip()
    return str(payload.get("title") or "").strip()


def _selected_subreddit(payload: Any, *, item_index: int, all_items: bool) -> str:
    if not isinstance(payload, dict):
        return ""
    items = payload.get("items")
    if isinstance(items, list):
        selected = items if all_items else items[item_index : item_index + 1]
        for item in selected:
            if isinstance(item, dict) and str(item.get("subreddit") or "").strip():
                return str(item.get("subreddit") or "").strip()
    return str(payload.get("subreddit") or "").strip()


def _storyboard_payload_from_item(item: dict[str, Any]) -> dict[str, Any]:
    script = item.get("script") if isinstance(item.get("script"), dict) else None
    if script and _is_storyboard_like(script):
        return script
    if script and isinstance(script.get("storyboard_v2"), dict):
        return script["storyboard_v2"]
    if isinstance(item.get("storyboard_v2"), dict):
        return item["storyboard_v2"]
    return item


def _is_storyboard_like(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("storyboard_v2"), dict) or isinstance(payload.get("scenes"), list) or (
        isinstance(payload.get("girly_scene"), dict) and bool(payload.get("voiceover_line"))
    )


def _storyboard_scenes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    storyboard = payload.get("storyboard_v2") if isinstance(payload.get("storyboard_v2"), dict) else payload
    scenes = storyboard.get("scenes") if isinstance(storyboard.get("scenes"), list) else []
    return [scene for scene in scenes if isinstance(scene, dict)]


def _storyboard_root(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("storyboard_v2") if isinstance(payload.get("storyboard_v2"), dict) else payload


def _story_format_metadata(storyboard_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, payload in enumerate(storyboard_payloads):
        storyboard = _storyboard_root(payload)
        format_id = extract_story_format(storyboard)
        family = reel_template_family(format_id)
        entry = {
            "item_index": index,
            "story_format": format_id or "",
            "reel_template_family": family,
            "template_family_version": TEMPLATE_FAMILY_VERSION,
        }
        spec = story_format_spec(format_id)
        if spec:
            entry["opening_scene_pool"] = spec.get("opening_scene_pool") or []
            entry["final_scene_pool"] = spec.get("final_scene_pool") or []
        entries.append(entry)
        if _has_story_format_contract(storyboard):
            warnings.extend(
                f"item_{index}:{issue}"
                for issue in validate_story_format_payload(storyboard)
            )

    selected_formats = [entry["story_format"] for entry in entries if entry["story_format"]]
    selected_families = [entry["reel_template_family"] for entry in entries if entry["reel_template_family"]]
    unique_formats = sorted(set(selected_formats))
    unique_families = sorted(set(selected_families))

    if len(unique_formats) == 1:
        story_format = unique_formats[0]
    elif len(unique_formats) > 1:
        story_format = "multiple"
    else:
        story_format = ""

    if len(unique_families) == 1:
        family = unique_families[0]
    elif len(unique_families) > 1:
        family = "multiple_girly_families"
    else:
        family = DEFAULT_REEL_TEMPLATE_FAMILY

    return {
        "story_format": story_format,
        "reel_template_family": family,
        "template_family_version": TEMPLATE_FAMILY_VERSION,
        "story_format_beat_map": _story_format_beat_map(storyboard_payloads),
        "story_format_entries": entries,
        "story_format_validation_warnings": warnings,
    }


def _has_story_format_contract(storyboard: dict[str, Any]) -> bool:
    return any(
        key in storyboard
        for key in (
            "story_format",
            "story_format_reason",
            "story_format_confidence",
            "story_format_beat_map",
        )
    )


def _story_format_beat_map(storyboard_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(storyboard_payloads) != 1:
        return []
    storyboard = _storyboard_root(storyboard_payloads[0])
    beat_map = storyboard.get("story_format_beat_map")
    return [beat for beat in beat_map if isinstance(beat, dict)] if isinstance(beat_map, list) else []


def _resolver_items(path: str) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else None
    return [item for item in items or [] if isinstance(item, dict)]


def _load_json_optional(path: str) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_scene_lines(path: str) -> dict[int, str]:
    payload = _load_json_optional(path)
    scenes = payload.get("scenes") if isinstance(payload, dict) else []
    result: dict[int, str] = {}
    for scene in scenes or []:
        if not isinstance(scene, dict):
            continue
        scene_id = _int(scene.get("scene_id"))
        line = str(scene.get("voiceover_line") or "").strip()
        if scene_id and line:
            result[scene_id] = line
    return result


def _voiceover_scene_spans(
    *,
    source_scenes: list[dict[str, Any]],
    scene_line_overrides: dict[int, str],
) -> tuple[dict[int, str], dict[int, tuple[int, int]], str]:
    voiceover_by_scene: dict[int, str] = {}
    scene_spans: dict[int, tuple[int, int]] = {}
    parts: list[str] = []
    cursor = 0
    for index, scene in enumerate(source_scenes, start=1):
        scene_id = _scene_id(scene, fallback=index)
        line = scene_line_overrides.get(scene_id) or str(scene.get("voiceover_line") or "").strip()
        if parts:
            parts.append(" ")
            cursor += 1
        start = cursor
        parts.append(line)
        cursor += len(line)
        voiceover_by_scene[scene_id] = line
        scene_spans[scene_id] = (start, cursor)
    return voiceover_by_scene, scene_spans, "".join(parts)


def _timed_words_from_alignment(
    *,
    voiceover_text: str,
    alignment_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    alignment = _extract_alignment(alignment_payload)
    if not voiceover_text or not alignment:
        return [], []
    timed_words, warnings = align_words_to_character_alignment(voiceover_text, alignment)
    return normalize_timed_word_tokens(timed_words), warnings


def _extract_alignment(payload: dict[str, Any]) -> dict[str, Any]:
    alignment = payload.get("alignment") if isinstance(payload, dict) else {}
    if isinstance(alignment, dict) and alignment.get("characters"):
        return alignment
    timestamp_info = payload.get("timestamp_info") if isinstance(payload, dict) else {}
    character_alignment = timestamp_info.get("characterAlignment") if isinstance(timestamp_info, dict) else {}
    if isinstance(character_alignment, dict):
        return {
            "characters": character_alignment.get("characters") or [],
            "character_start_times_seconds": (
                character_alignment.get("characterStartTimeSeconds")
                or character_alignment.get("characterStartTimesSeconds")
                or []
            ),
            "character_end_times_seconds": (
                character_alignment.get("characterEndTimeSeconds")
                or character_alignment.get("characterEndTimesSeconds")
                or []
            ),
        }
    return {}


def _words_by_scene(
    timed_words: list[dict[str, Any]],
    *,
    scene_spans: dict[int, tuple[int, int]],
) -> dict[int, list[dict[str, Any]]]:
    result = {scene_id: [] for scene_id in scene_spans}
    for word in timed_words:
        start = int(word.get("source_start_char") or 0)
        for scene_id, (scene_start, scene_end) in scene_spans.items():
            if scene_start <= start < scene_end:
                result.setdefault(scene_id, []).append(word)
                break
    return result


def _merge_resolved_slots(
    storyboard_payload: dict[str, Any],
    *,
    resolver_items: list[dict[str, Any]],
    post_id: str,
    item_index: int,
) -> dict[str, Any]:
    if not resolver_items:
        return storyboard_payload
    resolver_item = _resolver_item_for_post(resolver_items, post_id=post_id, item_index=item_index)
    if not resolver_item:
        return storyboard_payload
    storyboard = storyboard_payload.get("storyboard_v2") if isinstance(storyboard_payload.get("storyboard_v2"), dict) else storyboard_payload
    scenes = storyboard.get("scenes") if isinstance(storyboard.get("scenes"), list) else []
    slots_by_scene: dict[int, list[dict[str, Any]]] = {}
    for slot in resolver_item.get("resolved_slots") or []:
        if not isinstance(slot, dict):
            continue
        scene_id = _int(slot.get("scene_id"))
        if scene_id is None:
            continue
        slots_by_scene.setdefault(scene_id, []).append(slot)
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            continue
        scene_id = _int(scene.get("scene_id")) or index
        resolved = slots_by_scene.get(scene_id) or []
        if resolved:
            scene["resolved_slots"] = resolved
            scene["resolved_media"] = resolved
    return storyboard_payload


def _bridge_media_assets(scene: dict[str, Any], *, scene_html: str) -> list[dict[str, Any]]:
    """Expose scene-owned resolved media when the selected template has no media slot.

    The Remotion composition renders these assets in its visual layer. This is
    not a hidden score marker: only selected resolver assets attached to the
    same scene are eligible, and scenes that already render media through the
    template are left untouched.
    """

    if _html_has_media_asset(scene_html):
        return []

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for media in scene.get("resolved_media") or scene.get("resolved_slots") or []:
        if not isinstance(media, dict):
            continue
        slot = media.get("slot") if isinstance(media.get("slot"), dict) else {}
        asset_id = str(media.get("asset_id") or slot.get("asset_id") or "").strip()
        if not asset_id or asset_id in seen:
            continue
        if _resolved_media_rejected_for_publication(media, slot=slot):
            continue

        wants_video = _bridge_wants_video(media=media, slot=slot)
        src = _bridge_media_url(media, prefer_video=wants_video)
        kind = "video" if wants_video else "image"
        if wants_video and not _is_direct_video_url(src):
            fallback = _bridge_media_url(media, prefer_video=False)
            if fallback:
                src = fallback
                kind = "image"
        if not wants_video and _is_direct_video_url(src):
            kind = "video"
        if not src:
            continue

        result.append(
            {
                "id": asset_id,
                "kind": kind,
                "role": str(slot.get("role") or slot.get("girly_asset_role") or media.get("role") or "semantic_bridge"),
                "src": _url_for_html(src),
                "fit": "cover",
                "focusX": "50%",
                "focusY": "50%",
            }
        )
        seen.add(asset_id)
    return result[:2]


def _suppress_design_text_slots(scene: dict[str, Any]) -> None:
    unit = scene.get("girly_scene_unit") if isinstance(scene.get("girly_scene_unit"), dict) else {}
    slots = unit.get("slot_plan")
    if not isinstance(slots, list):
        return
    unit["slot_plan"] = [
        slot
        for slot in slots
        if not (isinstance(slot, dict) and slot.get("slot_type") == "text")
    ]


def _strip_design_text_slots(html: str) -> str:
    def replace(match: re.Match[str]) -> str:
        attrs = re.sub(r"\sdata-girly-filled-text=(['\"]).*?\1", "", match.group("attrs"), flags=re.I | re.S)
        attrs = re.sub(r"\sdata-girly-hidden-text=(['\"]).*?\1", "", attrs, flags=re.I | re.S)
        attrs = re.sub(r"\sstyle=(['\"]).*?\1", "", attrs, flags=re.I | re.S)
        return f'<{match.group("tag")}{attrs} data-girly-hidden-text="true" style="visibility: hidden;"></{match.group("tag")}>'

    return re.sub(
        r"<(?P<tag>[a-z0-9]+)\b(?P<attrs>[^>]*\bdata-girly-filled-text=(['\"]).*?\3[^>]*)>"
        r".*?</(?P=tag)>",
        replace,
        html,
        flags=re.I | re.S,
    )


def _sanitize_rejected_html_media_slots(html: str, scene: dict[str, Any]) -> tuple[str, list[str]]:
    """Remove prefilled template media whose selected source fails final hygiene."""

    rejected_asset_ids = _rejected_resolved_media_asset_ids(scene)
    if not rejected_asset_ids:
        return html, []

    removed: list[str] = []

    def replace(match: re.Match[str]) -> str:
        asset_id = str(match.group("asset_id") or "").strip()
        if asset_id not in rejected_asset_ids:
            return match.group(0)
        removed.append(asset_id)
        attrs = _strip_media_fill_attrs(match.group("attrs"))
        inner = _strip_media_fill_inner(match.group("inner"))
        return f"<{match.group('tag')}{attrs}>{inner}</{match.group('tag')}>"

    cleaned = re.sub(
        r"<(?P<tag>[a-z0-9]+)\b(?P<attrs>[^>]*\bdata-asset-id=(?P<quote>['\"])(?P<asset_id>.*?)(?P=quote)[^>]*)>"
        r"(?P<inner>.*?)</(?P=tag)>",
        replace,
        html,
        flags=re.I | re.S,
    )
    return cleaned, sorted(set(removed), key=removed.index)


def _rejected_resolved_media_asset_ids(scene: dict[str, Any]) -> set[str]:
    rejected: set[str] = set()
    for media in scene.get("resolved_media") or scene.get("resolved_slots") or []:
        if not isinstance(media, dict):
            continue
        slot = media.get("slot") if isinstance(media.get("slot"), dict) else {}
        asset_id = str(media.get("asset_id") or slot.get("asset_id") or "").strip()
        if asset_id and _resolved_media_rejected_for_publication(media, slot=slot):
            rejected.add(asset_id)
    return rejected


def _resolved_media_rejected_for_publication(media: dict[str, Any], *, slot: dict[str, Any]) -> bool:
    sources = _selected_publication_sources(media)
    if not sources:
        return False
    for source in sources:
        reason = publication_render_asset_hygiene_rejection_reason(source, slot=slot)
        if not reason:
            return False
        if reason in LOCAL_RENDER_SOFT_HYGIENE_REASONS and _has_local_render_asset(source):
            return False
    return True


def _has_local_render_asset(source: dict[str, Any]) -> bool:
    content_type = str(source.get("local_content_type") or source.get("content_type") or "").lower()
    if content_type.startswith(("image/", "video/")):
        return True
    for key in (
        "public_path",
        "media_public_path",
        "local_path",
        "path",
        "downloaded_path",
        "file_path",
        "thumbnail_local_path",
        "thumbnail_path",
    ):
        if _is_local_render_media_path(str(source.get(key) or "")):
            return True
    return False


def _is_local_render_media_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if not (
        text.startswith("__STATIC_FILE__")
        or text.startswith("file://")
        or Path(text).expanduser().is_absolute()
        or "/" in text
    ):
        return False
    return bool(re.search(r"\.(?:mp4|webm|mov|jpe?g|png|webp|avif)(?:[?#].*)?$", text, flags=re.I))


def _selected_publication_sources(media: dict[str, Any]) -> list[dict[str, Any]]:
    selected = media.get("selected_candidates")
    if isinstance(selected, list):
        sources = [candidate for candidate in selected if isinstance(candidate, dict)]
        if sources:
            return sources

    selected_ids = _selection_candidate_ids(media.get("selection"))
    pool = media.get("candidate_pool")
    if selected_ids and isinstance(pool, list):
        sources = [
            candidate
            for candidate in pool
            if isinstance(candidate, dict) and str(candidate.get("candidate_id") or "") in selected_ids
        ]
        if sources:
            return sources

    sources = _bridge_media_sources(media)
    return [source for source in sources if _source_has_publication_identity(source)]


def _selection_candidate_ids(selection: Any) -> set[str]:
    if not isinstance(selection, dict):
        return set()
    values = selection.get("selected_candidate_ids")
    if not isinstance(values, list):
        return set()
    return {str(value).strip() for value in values if str(value or "").strip()}


def _source_has_publication_identity(source: dict[str, Any]) -> bool:
    for key in (
        "provider",
        "title",
        "query",
        "page_url",
        "media_url",
        "thumbnail_url",
        "public_path",
        "local_path",
    ):
        if str(source.get(key) or "").strip():
            return True
    metadata = source.get("metadata")
    return isinstance(metadata, dict) and bool(metadata)


def _strip_media_fill_attrs(attrs: str) -> str:
    attrs = re.sub(r"\sdata-girly-filled-media=(['\"]).*?\1", "", attrs, flags=re.I | re.S)
    attrs = re.sub(r"\sdata-girly-role=(['\"]).*?\1", "", attrs, flags=re.I | re.S)
    attrs = re.sub(r"\sdata-girly-slot=(['\"]).*?\1", "", attrs, flags=re.I | re.S)
    attrs = re.sub(r"\sdata-asset-id=(['\"]).*?\1", "", attrs, flags=re.I | re.S)

    def strip_style(match: re.Match[str]) -> str:
        style = match.group("value")
        if re.search(r"background-image\s*:", style, flags=re.I):
            return ""
        return match.group(0)

    return re.sub(
        r"\sstyle=(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
        strip_style,
        attrs,
        flags=re.I | re.S,
    )


def _strip_media_fill_inner(inner: str) -> str:
    inner = re.sub(r"<video\b[^>]*>.*?</video>", "", inner, flags=re.I | re.S)
    inner = re.sub(r"<img\b[^>]*>", "", inner, flags=re.I | re.S)
    return inner


def _html_has_media_asset(html: str) -> bool:
    for match in re.finditer(r"\bdata-asset-id=(?P<quote>['\"])(?P<id>.*?)(?P=quote)", html, flags=re.I | re.S):
        tag_start = html.rfind("<", 0, match.start())
        tag_end = html.find(">", match.end())
        opening_tag = html[tag_start : tag_end + 1] if tag_start >= 0 and tag_end >= 0 else match.group(0)
        close_tag = html.find("</div>", tag_end + 1) if tag_end >= 0 else -1
        inner_html = html[tag_end + 1 : close_tag] if tag_end >= 0 and close_tag >= 0 else ""
        if _looks_like_media_asset(f"{opening_tag} {inner_html[:600]}"):
            return True
    return False


def _looks_like_media_asset(snippet: str) -> bool:
    return bool(
        re.search(r"<(?:video|img)\b", snippet, flags=re.I)
        or re.search(r"background-image\s*:\s*url\(", snippet, flags=re.I)
        or re.search(r"\.(?:mp4|webm|mov|m3u8|jpe?g|png|webp|gif)(?:[?#\"')\s<>]|$)", snippet, flags=re.I)
    )


def _bridge_wants_video(*, media: dict[str, Any], slot: dict[str, Any]) -> bool:
    text = " ".join(
        str(value or "").lower()
        for value in (
            media.get("kind"),
            media.get("role"),
            slot.get("kind"),
            slot.get("role"),
            slot.get("source_strategy"),
            slot.get("asset_id"),
        )
    )
    return any(token in text for token in ("video", "footage", "broll", "background"))


def _bridge_media_url(media: dict[str, Any], *, prefer_video: bool) -> str:
    common_keys = (
        "public_path",
        "media_public_path",
        "local_path",
        "path",
        "downloaded_path",
        "file_path",
        "preview_url",
        "url",
        "source_url",
    )
    thumbnail_keys = ("thumbnail_local_path", "thumbnail_path")
    media_keys = ("media_url", "thumbnail_url")
    keys = common_keys + media_keys if prefer_video else thumbnail_keys + common_keys + media_keys
    slot = media.get("slot") if isinstance(media.get("slot"), dict) else media
    for source in _bridge_media_sources(media):
        for key in keys:
            value = source.get(key)
            if key == "thumbnail_url" and _is_low_quality_thumbnail_url(str(value or "")):
                continue
            if (
                isinstance(value, str)
                and value.strip()
                and (source.get("_renderer_allow_remote") is not False or _is_local_render_url(value))
            ):
                return value.strip()
    return ""


def _bridge_media_sources(media: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for key in ("selected", "selection", "candidate"):
        value = media.get(key)
        if isinstance(value, dict):
            sources.append(value)
    value = media.get("storyboard_asset")
    if isinstance(value, dict):
        sources.append(value)
    for key in ("selected_candidates", "candidate_pool"):
        candidates = media.get(key)
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                if key == "candidate_pool":
                    marked = dict(candidate)
                    marked["_renderer_allow_remote"] = False
                    sources.append(marked)
                else:
                    sources.append(candidate)
    return sources or [media]


def _is_direct_video_url(value: str) -> bool:
    return bool(re.search(r"\.(?:mp4|webm|mov)(?:[?#].*)?$", str(value or ""), flags=re.I))


def _is_low_quality_thumbnail_url(value: str) -> bool:
    return "encrypted-tbn" in str(value or "").lower()


def _is_local_render_url(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text.startswith("__STATIC_FILE__") or text.startswith("file://") or Path(text).expanduser().is_absolute())


def _url_for_html(value: str) -> str:
    text = str(value or "").strip()
    if not text or text.startswith("__STATIC_FILE__"):
        return text
    if re.match(r"^[a-z][a-z0-9+.-]*://", text, flags=re.I) or text.startswith("data:"):
        return text
    path = Path(text).expanduser()
    if not path.is_absolute():
        return text
    return path.as_uri() if path.exists() else "file://" + quote(str(path))


def _semantic_visual(
    scene: dict[str, Any],
    *,
    scene_html: str,
    bridge_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    if _html_has_media_asset(scene_html) or bridge_assets:
        return {}
    scene_id = _scene_id(scene, fallback=0)
    text = _scene_semantic_text(scene)
    topic = _semantic_visual_topic(text)
    motifs = _semantic_visual_motifs(topic, text)
    return {
        "id": f"semantic-visual-{scene_id:03d}",
        "kind": "semantic_motion",
        "quality": "publishable_visual",
        "source": "offline_editorial_renderer",
        "topic": topic,
        "layout": ["tableau", "meter", "split", "stack"][scene_id % 4],
        "motifs": motifs,
    }


def _scene_semantic_text(scene: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("voiceover_line", "title", "description", "visual_prompt"):
        value = scene.get(key)
        if isinstance(value, str):
            values.append(value)
    girly_scene = scene.get("girly_scene") if isinstance(scene.get("girly_scene"), dict) else {}
    for key in ("storytelling_function", "semantic_reason"):
        value = girly_scene.get(key)
        if isinstance(value, str):
            values.append(value)
    assets = girly_scene.get("asset_semantics")
    if isinstance(assets, list):
        values.extend(str(item) for item in assets if isinstance(item, (str, int, float)))
    for media in scene.get("resolved_media") or scene.get("resolved_slots") or []:
        if not isinstance(media, dict):
            continue
        for key in ("query", "fallback_query", "asset_id"):
            value = media.get(key)
            if isinstance(value, str):
                values.append(value)
        slot = media.get("slot") if isinstance(media.get("slot"), dict) else {}
        for key in ("search_query_en", "search_query_ru", "visual_prompt", "role", "girly_asset_role"):
            value = slot.get(key)
            if isinstance(value, str):
                values.append(value)
    return " ".join(values).casefold()


def _semantic_visual_topic(text: str) -> str:
    checks = (
        (
            "food",
            (
                "latte",
                "coffee",
                "pastry",
                "croissant",
                "calorie",
                "plate",
                "portion",
                "milk",
                "syrup",
                "кофе",
                "латте",
                "круас",
                "выпеч",
                "калори",
                "тарел",
                "порци",
            ),
        ),
        (
            "thermal",
            (
                "sauna",
                "cold",
                "plunge",
                "ice",
                "bath",
                "heat",
                "thermal",
                "blood pressure",
                "саун",
                "холод",
                "лед",
                "баня",
                "тепл",
                "сосуд",
                "давлен",
            ),
        ),
        (
            "supplements",
            (
                "supplement",
                "pill",
                "vitamin",
                "iron",
                "omega",
                "stack",
                "bottle",
                "capsule",
                "добав",
                "витамин",
                "желез",
                "таблет",
                "капсул",
                "банка",
                "стек",
            ),
        ),
        (
            "recovery",
            (
                "sleep",
                "walk",
                "stress",
                "energy",
                "treadmill",
                "steps",
                "bedroom",
                "tea",
                "сон",
                "шаг",
                "прогул",
                "стресс",
                "энерг",
                "чай",
            ),
        ),
    )
    for topic, terms in checks:
        if any(term in text for term in terms):
            return topic
    return "general"


def _semantic_visual_motifs(topic: str, text: str) -> list[str]:
    defaults = {
        "food": ["cup", "plate", "receipt", "portion_grid"],
        "thermal": ["heat_panel", "cold_panel", "pulse_line", "timer"],
        "supplements": ["bottle_stack", "dose_grid", "checklist", "risk_badge"],
        "recovery": ["sleep_arc", "step_meter", "energy_bar", "pause_card"],
        "general": ["evidence_cards", "signal_line", "decision_axis", "note_stack"],
    }
    motifs = list(defaults.get(topic, defaults["general"]))
    if "not" in text or "не " in text:
        motifs.append("contrast_mark")
    return motifs[:5]


def _resolver_item_for_post(
    resolver_items: list[dict[str, Any]],
    *,
    post_id: str,
    item_index: int,
) -> dict[str, Any] | None:
    if post_id:
        for item in resolver_items:
            if str(item.get("post_id") or "") == post_id:
                return item
    if 0 <= item_index < len(resolver_items):
        return resolver_items[item_index]
    return resolver_items[0] if len(resolver_items) == 1 else None


def _scene_timings(
    *,
    source_scenes: list[dict[str, Any]],
    payloads: list[dict[str, Any]],
    fps: int,
    default_scene_sec: float,
) -> list[dict[str, int]]:
    count = len(source_scenes)
    explicit = [_scene_duration_sec(scene) for scene in source_scenes]
    total_sec = _execution_duration_sec(payloads)
    if count == 0:
        return []
    if all(value and value > 0 for value in explicit):
        seconds = [float(value) for value in explicit]
    elif total_sec and total_sec > 0:
        known = sum(float(value) for value in explicit if value and value > 0)
        missing = sum(1 for value in explicit if not value or value <= 0)
        fallback = max(1.0 / fps, (total_sec - known) / missing) if missing else 0
        seconds = [float(value) if value and value > 0 else fallback for value in explicit]
    else:
        seconds = [float(value) if value and value > 0 else default_scene_sec for value in explicit]

    starts = [0]
    for value in seconds[:-1]:
        starts.append(starts[-1] + max(1, int(round(value * fps))))
    result = []
    for index, value in enumerate(seconds):
        duration = max(1, int(round(value * fps)))
        result.append({"start_frame": starts[index], "duration_frames": duration})
    return result


def _scene_timings_from_words(
    *,
    source_scenes: list[dict[str, Any]],
    words_by_scene: dict[int, list[dict[str, Any]]],
    voiceover_by_scene: dict[int, str],
    fps: int,
) -> list[dict[str, Any]]:
    if not any(words_by_scene.values()):
        return []
    ordered_ids = [_scene_id(scene, fallback=index) for index, scene in enumerate(source_scenes, start=1)]
    starts: dict[int, float] = {}
    cursor = 0.0
    for scene_id in ordered_ids:
        words = words_by_scene.get(scene_id) or []
        if words:
            starts[scene_id] = max(0.0, _word_start_sec(words[0], fallback=cursor))
            cursor = starts[scene_id]
        else:
            starts[scene_id] = cursor
            cursor += _estimate_scene_duration_sec(voiceover_by_scene.get(scene_id, ""))

    result: list[dict[str, Any]] = []
    for index, scene_id in enumerate(ordered_ids):
        start_sec = starts[scene_id] if index else 0.0
        if index + 1 < len(ordered_ids):
            end_sec = starts[ordered_ids[index + 1]]
        else:
            words = words_by_scene.get(scene_id) or []
            end_sec = _word_end_sec(words[-1], fallback=start_sec + 0.25) + 0.25 if words else start_sec + 0.25
        end_sec = max(start_sec + 1.0 / max(1, fps), end_sec)
        start_frame = int(round(start_sec * fps))
        duration_frames = max(1, int(round(end_sec * fps)) - start_frame)
        result.append(
            {
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
                "start_frame": start_frame,
                "duration_frames": duration_frames,
            }
        )
    return result


def _word_timings_for_scene(
    words: list[dict[str, Any]],
    *,
    scene_start_sec: float,
    fps: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, word in enumerate(words, start=1):
        start_sec = _word_start_sec(word, fallback=scene_start_sec)
        end_sec = _word_end_sec(word, fallback=start_sec)
        appear_frame = max(0, int(round((start_sec - scene_start_sec) * fps)))
        result.append(
            {
                "index": index,
                "word_index": index,
                "word": str(word.get("word") or ""),
                "text": str(word.get("word") or ""),
                "appear_sec": round(start_sec, 3),
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
                "appear_frame": appear_frame,
                "confidence": word.get("confidence", 1.0),
                "timing_strategy": word.get("timing_strategy") or "character_alignment",
            }
        )
    return result


def _inject_sync_caption(html: str, *, voiceover_line: str, scene: dict[str, Any], mode: str) -> str:
    caption = format_timed_text_html(
        voiceover_line,
        scene=scene,
        max_words=7,
        line_break=True,
    )
    if not caption:
        return html
    html = re.sub(
        r'(<div\b[^>]*\bdata-scene-root=["\'][^"\']+["\'][^>]*)(>)',
        rf'\1 data-sync-caption-mode="{mode}"\2',
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    insert_at = html.rfind("</div>")
    if insert_at < 0:
        return html
    caption_html = f'\n          <div class="girly-sync-caption" data-girly-sync-caption="true">{caption}</div>'
    return html[:insert_at] + caption_html + html[insert_at:]


def _word_start_sec(word: dict[str, Any], *, fallback: float) -> float:
    value = _float(word.get("start_sec"))
    if value is not None:
        return value
    value = _float(word.get("appear_sec"))
    return value if value is not None else fallback


def _word_end_sec(word: dict[str, Any], *, fallback: float) -> float:
    value = _float(word.get("end_sec"))
    if value is not None:
        return value
    value = _float(word.get("appear_sec"))
    return value if value is not None else fallback


def _estimate_scene_duration_sec(text: str) -> float:
    words = max(1, len(str(text or "").split()))
    return max(0.8, words / 2.8)


def _scene_duration_sec(scene: dict[str, Any]) -> float | None:
    direct = _float(scene.get("duration_sec"))
    if direct and direct > 0:
        return direct
    execution = scene.get("execution") if isinstance(scene.get("execution"), dict) else {}
    return _float(execution.get("duration_sec"))


def _execution_duration_sec(payloads: list[dict[str, Any]]) -> float | None:
    total = 0.0
    found = False
    for payload in payloads:
        storyboard = payload.get("storyboard_v2") if isinstance(payload.get("storyboard_v2"), dict) else payload
        execution = storyboard.get("execution") if isinstance(storyboard.get("execution"), dict) else {}
        value = _float(execution.get("duration_sec")) or _float(storyboard.get("duration_sec"))
        if value and value > 0:
            total += value
            found = True
    return total if found else None


def _asset_timings(
    scene: dict[str, Any],
    *,
    fps: int,
    word_timings: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    unit = scene.get("girly_scene_unit") if isinstance(scene.get("girly_scene_unit"), dict) else {}
    result: dict[str, dict[str, Any]] = {}
    media_slots = [slot for slot in unit.get("slot_plan") or [] if isinstance(slot, dict) and slot.get("slot_type") == "media"]
    for media_index, slot in enumerate(media_slots):
        if not isinstance(slot, dict) or slot.get("slot_type") != "media":
            continue
        asset_ids = _asset_ids_for_slot(scene, slot, index=media_index)
        if not asset_ids:
            continue
        appears_on_word = _slot_appears_on_word(scene, slot, index=media_index)
        appear_frame, timing_confidence = _asset_appear_frame(
            appears_on_word,
            word_timings=word_timings or [],
            media_index=media_index,
            media_count=len(media_slots),
            fps=fps,
        )
        for asset_id in asset_ids:
            result[asset_id] = {
                "appear_frame": appear_frame,
                "appears_on_word": appears_on_word,
                "confidence": timing_confidence,
            }
    for media_index, media in enumerate(scene.get("resolved_media") or scene.get("resolved_slots") or []):
        if not isinstance(media, dict):
            continue
        slot = media.get("slot") if isinstance(media.get("slot"), dict) else media
        asset_id = str(media.get("asset_id") or slot.get("asset_id") or "").strip()
        if not asset_id or asset_id in result:
            continue
        appears_on_word = _media_appears_on_word(media)
        appear_frame, timing_confidence = _asset_appear_frame(
            appears_on_word,
            word_timings=word_timings or [],
            media_index=media_index,
            media_count=max(1, len(scene.get("resolved_media") or scene.get("resolved_slots") or [])),
            fps=fps,
        )
        result[asset_id] = {
            "appear_frame": appear_frame,
            "appears_on_word": appears_on_word,
            "confidence": timing_confidence,
        }
    return result


def _asset_ids_for_slot(scene: dict[str, Any], slot: dict[str, Any], *, index: int) -> list[str]:
    ids: list[str] = []
    for asset_id in (
        _resolved_asset_id_for_slot(scene, slot),
        _visual_asset_id_for_slot(scene, slot),
        str(slot.get("asset_id") or "").strip(),
        str(slot.get("slot") or "").strip() or f"slot_{index}",
    ):
        if asset_id and asset_id not in ids:
            ids.append(asset_id)
    return ids


def _resolved_asset_id_for_slot(scene: dict[str, Any], slot: dict[str, Any]) -> str:
    slot_name = str(slot.get("slot") or "").strip()
    visual_asset_index = slot.get("visual_asset_index")
    for media in scene.get("resolved_media") or scene.get("resolved_slots") or []:
        if not isinstance(media, dict):
            continue
        media_slot = media.get("slot") if isinstance(media.get("slot"), dict) else media
        storyboard_asset_index = media_slot.get("storyboard_asset_index")
        if slot_name and _resolved_media_slot_name(media_slot) == slot_name:
            return str(media.get("asset_id") or media_slot.get("asset_id") or "").strip()
        if isinstance(visual_asset_index, int) and storyboard_asset_index == visual_asset_index:
            return str(media.get("asset_id") or media_slot.get("asset_id") or "").strip()
    return ""


def _resolved_media_slot_name(media_slot: dict[str, Any]) -> str:
    girly_slot_plan = media_slot.get("girly_slot_plan") if isinstance(media_slot.get("girly_slot_plan"), dict) else {}
    return str(
        girly_slot_plan.get("slot")
        or media_slot.get("slot")
        or media_slot.get("preferred_slot")
        or ""
    ).strip()


def _visual_asset_id_for_slot(scene: dict[str, Any], slot: dict[str, Any]) -> str:
    assets = scene.get("visual_assets") if isinstance(scene.get("visual_assets"), list) else []
    asset_index = slot.get("visual_asset_index")
    if isinstance(asset_index, int) and 0 <= asset_index < len(assets) and isinstance(assets[asset_index], dict):
        return str(assets[asset_index].get("asset_id") or f"visual_asset_{asset_index}")
    return ""


def _slot_appears_on_word(scene: dict[str, Any], slot: dict[str, Any], *, index: int) -> str:
    for value in (
        slot.get("appears_on_word"),
        _visual_asset_appears_on_word(scene, slot),
        _resolved_asset_appears_on_word(scene, slot),
    ):
        cue = str(value or "").strip()
        if cue:
            return cue
    return ""


def _visual_asset_appears_on_word(scene: dict[str, Any], slot: dict[str, Any]) -> str:
    assets = scene.get("visual_assets") if isinstance(scene.get("visual_assets"), list) else []
    asset_index = slot.get("visual_asset_index")
    if isinstance(asset_index, int) and 0 <= asset_index < len(assets) and isinstance(assets[asset_index], dict):
        return str(assets[asset_index].get("appears_on_word") or "")
    return ""


def _resolved_asset_appears_on_word(scene: dict[str, Any], slot: dict[str, Any]) -> str:
    slot_name = str(slot.get("slot") or "").strip()
    for media in scene.get("resolved_media") or scene.get("resolved_slots") or []:
        if not isinstance(media, dict):
            continue
        media_slot = media.get("slot") if isinstance(media.get("slot"), dict) else media
        girly_slot_plan = media_slot.get("girly_slot_plan") if isinstance(media_slot.get("girly_slot_plan"), dict) else {}
        storyboard_asset = media_slot.get("storyboard_asset") if isinstance(media_slot.get("storyboard_asset"), dict) else {}
        if str(girly_slot_plan.get("slot") or "").strip() == slot_name:
            return str(girly_slot_plan.get("appears_on_word") or storyboard_asset.get("appears_on_word") or "")
    return ""


def _media_appears_on_word(media: dict[str, Any]) -> str:
    slot = media.get("slot") if isinstance(media.get("slot"), dict) else {}
    girly_slot_plan = slot.get("girly_slot_plan") if isinstance(slot.get("girly_slot_plan"), dict) else {}
    storyboard_asset = slot.get("storyboard_asset") if isinstance(slot.get("storyboard_asset"), dict) else {}
    return str(girly_slot_plan.get("appears_on_word") or storyboard_asset.get("appears_on_word") or "").strip()


def _asset_appear_frame(
    appears_on_word: str,
    *,
    word_timings: list[dict[str, Any]],
    media_index: int,
    media_count: int,
    fps: int,
) -> tuple[int, str]:
    cue_frame = _appear_frame_for_word_cue(appears_on_word, word_timings=word_timings)
    if cue_frame is not None:
        return max(0, cue_frame), "girly_static_v5_word_timing"
    if word_timings:
        if media_count <= 1:
            fallback_word_index = 0
        else:
            fallback_word_index = round((media_index + 1) * (len(word_timings) - 1) / (media_count + 1))
        word = word_timings[max(0, min(len(word_timings) - 1, fallback_word_index))]
        return max(0, int(word.get("appear_frame") or 0)), "girly_static_v5_even_word_fallback"
    return media_index * max(4, int(round(fps * 0.15))), "girly_static_v5_slot_index_fallback"


def _appear_frame_for_word_cue(
    appears_on_word: str,
    *,
    word_timings: list[dict[str, Any]],
) -> int | None:
    cue_tokens = _normalized_word_tokens(appears_on_word)
    if not cue_tokens:
        return None
    timed_tokens = [_normalized_word_tokens(str(word.get("word") or word.get("text") or "")) for word in word_timings]
    for index, tokens in enumerate(timed_tokens):
        if _tokens_match(cue_tokens, tokens):
            return int(word_timings[index].get("appear_frame") or 0)
        if _phrase_matches_at(cue_tokens, timed_tokens, index):
            return int(word_timings[index].get("appear_frame") or 0)
    return None


def _phrase_matches_at(cue_tokens: list[str], timed_tokens: list[list[str]], index: int) -> bool:
    if len(cue_tokens) < 2 or index + len(cue_tokens) > len(timed_tokens):
        return False
    return all(_tokens_match([cue_token], timed_tokens[index + offset]) for offset, cue_token in enumerate(cue_tokens))


def _tokens_match(cue_tokens: list[str], timed_tokens: list[str]) -> bool:
    if not cue_tokens or not timed_tokens:
        return False
    cue = cue_tokens[0]
    for token in timed_tokens:
        if cue == token:
            return True
        if len(cue) >= 5 and len(token) >= 5 and (cue.startswith(token) or token.startswith(cue)):
            return True
    return False


def _normalized_word_tokens(value: str) -> list[str]:
    return [
        token
        for token in (normalize_token_core(match.group(0)) for match in re.finditer(r"[\wА-Яа-яЁё0-9%％'-]+", value, re.U))
        if token
    ]


def _scene_id(scene: dict[str, Any], *, fallback: int) -> int:
    unit = scene.get("girly_scene_unit") if isinstance(scene.get("girly_scene_unit"), dict) else {}
    value = scene.get("scene_id") or unit.get("storyboard_scene_id") or unit.get("scene_index") or fallback
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else fallback


def _composition_id(input_path: str, payload: dict[str, Any], storyboard_payloads: list[dict[str, Any]]) -> str:
    for candidate in (payload, *storyboard_payloads):
        for key in ("post_id", "id", "video_id"):
            value = candidate.get(key)
            if value:
                return _slug(f"girly-static-v5-{value}")
    return _slug(f"girly-static-v5-{Path(input_path).stem}")


def _extract_css(html: str) -> str:
    css = "\n\n".join(match.rstrip() for match in re.findall(r"<style\b[^>]*>(.*?)</style>", html, flags=re.I | re.S))
    return _rewrite_font_urls_for_remotion(css)


def _rewrite_font_urls_for_remotion(css: str) -> str:
    """Remotion serves public assets under /public; raw CSS relative URLs resolve at /."""

    return re.sub(
        r"url\((?P<quote>['\"]?)Fonts/",
        lambda match: f"url({match.group('quote')}/public/Fonts/",
        css,
        flags=re.I,
    )


def _remotion_css_patch(width: int, height: int) -> str:
    return f"""

html, body {{
  margin: 0 !important;
  overflow: hidden !important;
  background: var(--page-bg, #fff7fb) !important;
}}
#remotion-html-stage > div:first-child {{
  position: absolute !important;
  inset: 0 !important;
  width: 100% !important;
  height: 100% !important;
}}
[data-scene-root] {{
  width: {width}px !important;
  height: {height}px !important;
  transform-origin: top left !important;
}}
.girly-media-fill {{
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center;
  display: block;
}}
[data-girly-filled-media]::before {{
  content: none !important;
}}
[data-girly-filled-text] {{
  overflow-wrap: anywhere !important;
  word-break: normal !important;
  white-space: normal !important;
  text-wrap: balance;
}}
[data-sync-caption-mode="replace"] [data-girly-filled-text] {{
  visibility: hidden !important;
}}
[data-sync-caption-mode="replace"] [class*="top-note"],
[data-sync-caption-mode="replace"] [class*="note-left"],
[data-sync-caption-mode="replace"] [class*="note-right"],
[data-sync-caption-mode="replace"] [class*="-note"],
[data-sync-caption-mode="replace"] [class*="pink-chip"],
[data-sync-caption-mode="replace"] [class*="avatar-label"],
[data-sync-caption-mode="replace"] [class*="-hash"],
[data-sync-caption-mode="replace"] [class*="side-word"],
[data-sync-caption-mode="replace"] [class*="label"] {{
  visibility: hidden !important;
}}
.girly-sync-caption {{
  position: absolute !important;
  left: 5.5% !important;
  right: 5.5% !important;
  bottom: 7% !important;
  z-index: 90 !important;
  color: #ffffff !important;
  font-family: "Neo Sans Pro Cyrillic", "Helvetica Bold CY", Arial, sans-serif !important;
  font-size: 46px !important;
  font-weight: 700 !important;
  line-height: 1.04 !important;
  letter-spacing: 0 !important;
  text-align: center !important;
  padding: 18px 22px 20px !important;
  background: rgba(20, 15, 13, 0.80) !important;
  border: 1px solid rgba(255, 255, 255, 0.28) !important;
  box-shadow: 0 18px 52px rgba(20, 15, 13, 0.34) !important;
  text-shadow:
    0 2px 0 rgba(0, 0, 0, 0.55),
    0 5px 18px rgba(0, 0, 0, 0.42) !important;
  pointer-events: none !important;
}}
.girly-sync-caption .sync-word {{
  display: inline-block !important;
  opacity: 0 !important;
  will-change: opacity, translate, filter !important;
}}
.scene-05 .s5-started[data-girly-filled-text] {{
  left: 12% !important;
  width: 76% !important;
  text-align: center !important;
  line-height: 0.92 !important;
}}
.scene-placeholder:not([data-girly-filled-media]) {{
  border-color: transparent !important;
  color: transparent !important;
}}
.scene-placeholder:not([data-girly-filled-media])::before {{
  content: none !important;
}}
[data-scene-root] [class*="photo"]:not([data-girly-filled-media]) {{
  background: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
  color: transparent !important;
}}
[data-scene-root] [class*="photo"]:not([data-girly-filled-media])::before,
[data-scene-root] [class*="video"]:not([data-girly-filled-media])::before,
[data-scene-root] [class*="image"]:not([data-girly-filled-media])::before {{
  content: none !important;
}}
[data-scene-root] .s5-profile-card:not([data-girly-filled-media]),
[data-scene-root] .s8-mail:not([data-girly-filled-media]),
[data-scene-root] .s10-video-main:not([data-girly-filled-media]),
[data-scene-root] .s10-video-small:not([data-girly-filled-media]),
[data-scene-root] .s11-science:not([data-girly-filled-media]),
[data-scene-root] .s11-video-main:not([data-girly-filled-media]),
[data-scene-root] .s12-video-main:not([data-girly-filled-media]),
[data-scene-root] .s13-photo:not([data-girly-filled-media]),
[data-scene-root] .s14-photo:not([data-girly-filled-media]),
[data-scene-root] .s15-bg:not([data-girly-filled-media]),
[data-scene-root] .s16-photo:not([data-girly-filled-media]),
[data-scene-root] .s17-photo:not([data-girly-filled-media]),
[data-scene-root] .s18-photo:not([data-girly-filled-media]),
[data-scene-root] .s20-card:not([data-girly-filled-media]),
[data-scene-root] .s21-photo:not([data-girly-filled-media]),
[data-scene-root] .s21-video:not([data-girly-filled-media]),
[data-scene-root] .s22-video-card:not([data-girly-filled-media]),
[data-scene-root] .s23-creator:not([data-girly-filled-media]),
[data-scene-root] .s23-cat-top:not([data-girly-filled-media]),
[data-scene-root] .s23-cat-bottom:not([data-girly-filled-media]),
[data-scene-root] .s24-media:not([data-girly-filled-media]),
[data-scene-root] .s24-photo:not([data-girly-filled-media]),
[data-scene-root] .s26-image-card:not([data-girly-filled-media]),
[data-scene-root] .s27-photo:not([data-girly-filled-media]),
[data-scene-root] .s27-video:not([data-girly-filled-media]) {{
  visibility: hidden !important;
}}
"""


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value or ""))
        return int(match.group(0)) if match else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or "girly-static-v5-html"


if __name__ == "__main__":
    raise SystemExit(main())
