from __future__ import annotations

from copy import deepcopy
from html import escape
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from reddit2video.girly_scene_bridge import materialize_girly_scene_unit
from reddit2video.media_asset_hygiene import publication_render_asset_hygiene_rejection_reason

Json = dict[str, Any]

TIMED_WORD_RE = re.compile(
    r'["\'«„“‘]*(?:\d+(?:[.,]\d+)*(?:[-–—]\d+(?:[.,]\d+)*)?(?:[%％])?|'
    r"[A-Za-zА-Яа-яЁё]+(?:[-'’][A-Za-zА-Яа-яЁё]+)*)[\"'»“”‘’.,!?;:…]*",
    flags=re.UNICODE,
)


def render_girly_static_document(
    scenes: list[Json],
    *,
    style_html_path: str | Path = "assets/style_packs/static_girly_2/index.html",
    title: str = "girly static v5",
    allow_rejected_media_for_render: bool = False,
) -> str:
    """Render selected static_girly_2 scenes without Gemini layout generation."""

    style_html = Path(style_html_path).read_text(encoding="utf-8")
    css = _extract_style(style_html)
    rendered_roots = [
        render_girly_static_scene(
            scene,
            style_html=style_html,
            allow_rejected_media_for_render=allow_rejected_media_for_render,
        )
        for scene in scenes
    ]
    body = "\n".join(
        f'<article class="scene-card" data-rendered-index="{index}">\n'
        f'  <p class="scene-label">{escape(_scene_label(scene, index))}</p>\n'
        f"{_indent(root, 2)}\n"
        "</article>"
        for index, (scene, root) in enumerate(zip(scenes, rendered_roots), start=1)
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
{css}

    body {{
      min-height: 100%;
      margin: 0;
      padding: 32px;
      background: var(--page-bg);
    }}

    .scene-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 375px));
      gap: 18px;
      align-items: start;
      justify-content: center;
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
  </style>
</head>
<body data-renderer="girly_static_v5">
  <main class="library-shell">
    <h1 class="library-title">{escape(title)}</h1>
    <section class="scene-grid" data-girly-static-v5-scenes>
{_indent(body, 6)}
    </section>
  </main>
</body>
</html>
"""


def render_girly_static_scene(
    scene: Json,
    *,
    style_html: str,
    allow_rejected_media_for_render: bool = False,
) -> str:
    materialized = scene if isinstance(scene.get("girly_scene_unit"), dict) else materialize_girly_scene_unit(scene)
    unit = materialized.get("girly_scene_unit") or {}
    scene_id = str(unit.get("scene_id") or "").strip()
    if not scene_id:
        raise ValueError("girly_scene_unit.scene_id is required")

    root_html = _extract_scene_root(style_html, scene_id)
    if not root_html:
        raise ValueError(f"Cannot find [data-scene-root={scene_id!r}] in static_girly_2 HTML")

    html = root_html
    assets = list(unit.get("visual_assets") or materialized.get("visual_assets") or [])
    resolved_by_slot = _resolved_media_by_preferred_slot(materialized)
    filled_media_slots: set[str] = set()
    filled_text_slots: set[str] = set()
    filled_text_values: dict[str, str] = {}
    for slot in unit.get("slot_plan") or []:
        if not isinstance(slot, dict):
            continue
        slot_name = str(slot.get("slot") or "").strip()
        if not slot_name:
            continue
        if slot.get("slot_type") == "media":
            media = _media_for_slot(slot, assets=assets, resolved_by_slot=resolved_by_slot)
            if media:
                next_html = _fill_media_slot(
                    html,
                    slot_name=slot_name,
                    media=media,
                    slot=slot,
                    allow_rejected_media_for_render=allow_rejected_media_for_render,
                )
                if next_html != html:
                    filled_media_slots.add(slot_name)
                html = next_html
        elif slot.get("slot_type") == "text":
            text = _text_for_slot(slot=slot, scene=materialized)
            if text:
                next_html = _fill_text_slot(html, slot_name=slot_name, text=text, slot=slot, scene=materialized)
                if next_html != html:
                    filled_text_slots.add(slot_name)
                    filled_text_values[slot_name] = text
                html = next_html
    for slot_name, media in resolved_by_slot.items():
        if slot_name in filled_media_slots:
            continue
        slot_meta = media.get("slot") if isinstance(media.get("slot"), dict) else {}
        synthetic_slot = {
            "slot": slot_name,
            "slot_type": "media",
            "role": slot_meta.get("girly_asset_role") or slot_meta.get("role") or "",
            "kind": slot_meta.get("kind") or media.get("kind") or "",
        }
        html = _fill_media_slot(
            html,
            slot_name=slot_name,
            media=media,
            slot=synthetic_slot,
            allow_rejected_media_for_render=allow_rejected_media_for_render,
        )
    html = _fill_missing_registry_text_slots(
        html,
        scene=materialized,
        unit=unit,
        filled_text_slots=filled_text_slots,
        filled_text_values=filled_text_values,
    )
    return html


def _extract_style(html: str) -> str:
    match = re.search(r"<style\b[^>]*>(?P<style>.*?)</style>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return match.group("style").rstrip()


def _extract_scene_root(html: str, scene_id: str) -> str:
    attr_match = re.search(
        rf"<div\b[^>]*\bdata-scene-root=[\"']{re.escape(scene_id)}[\"'][^>]*>",
        html,
        flags=re.IGNORECASE,
    )
    if not attr_match:
        return ""
    start = attr_match.start()
    depth = 0
    for token in re.finditer(r"</?div\b[^>]*>", html[start:], flags=re.IGNORECASE):
        text = token.group(0)
        if text.startswith("</"):
            depth -= 1
            if depth == 0:
                return html[start : start + token.end()]
        else:
            depth += 1
    return ""


def _media_for_slot(slot: Json, *, assets: list[Any], resolved_by_slot: dict[str, Json]) -> Json:
    slot_name = str(slot.get("slot") or "").strip()
    if slot_name in resolved_by_slot:
        return resolved_by_slot[slot_name]
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            continue
        if str(asset.get("preferred_slot") or "").strip() != slot_name:
            continue
        return {
            "asset_id": asset.get("asset_id") or f"visual_asset_{index}",
            "url": _asset_url(asset),
            "kind": _kind_from_slot(slot, asset),
            "storyboard_asset": asset,
        }
    index = slot.get("visual_asset_index")
    if isinstance(index, int) and 0 <= index < len(assets) and isinstance(assets[index], dict):
        asset = dict(assets[index])
        preferred_slot = str(asset.get("preferred_slot") or "").strip()
        if preferred_slot and preferred_slot != slot_name:
            return {}
        return {
            "asset_id": asset.get("asset_id") or f"visual_asset_{index}",
            "url": _asset_url(asset),
            "kind": _kind_from_slot(slot, asset),
            "storyboard_asset": asset,
        }
    return {}


def _resolved_media_by_preferred_slot(scene: Json) -> dict[str, Json]:
    result: dict[str, Json] = {}
    for candidate in scene.get("resolved_media") or scene.get("resolved_slots") or []:
        if not isinstance(candidate, dict):
            continue
        slot = candidate.get("slot") if isinstance(candidate.get("slot"), dict) else candidate
        merged = dict(candidate)
        merged.setdefault("asset_id", slot.get("asset_id"))
        merged.setdefault("kind", slot.get("kind"))
        merged.setdefault("slot", slot)
        girly_slot_plan = slot.get("girly_slot_plan") if isinstance(slot.get("girly_slot_plan"), dict) else {}
        slot_name = (
            girly_slot_plan.get("slot")
            or slot.get("slot")
            or slot.get("preferred_slot")
        )
        slot_names = [slot_name]
        for slot_name in slot_names:
            key = str(slot_name or "").strip()
            if key:
                result[key] = merged
    return result


def _asset_url(asset: Json) -> str:
    return _asset_url_with_preference(asset, prefer_video=True)


def _asset_url_with_preference(asset: Json, *, prefer_video: bool, allow_remote: bool = True) -> str:
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
    for key in keys:
        value = asset.get(key)
        if key == "thumbnail_url" and _is_low_quality_thumbnail_url(str(value or "")):
            continue
        if isinstance(value, str) and value.strip() and (allow_remote or _is_local_render_url(value)):
            return value.strip()
    return ""


def _media_url(
    media: Json,
    *,
    prefer_video: bool = True,
    allow_rejected_media_for_render: bool = False,
) -> str:
    slot = media.get("slot") if isinstance(media.get("slot"), dict) else media
    candidate_sources = _media_candidate_sources(media)
    for source in candidate_sources:
        if (
            not allow_rejected_media_for_render
            and publication_render_asset_hygiene_rejection_reason(source, slot=slot)
        ):
            continue
        url = _asset_url_with_preference(
            source,
            prefer_video=prefer_video,
            allow_remote=source.get("_renderer_allow_remote") is not False,
        )
        if url:
            return url
    if not candidate_sources:
        if (
            not allow_rejected_media_for_render
            and publication_render_asset_hygiene_rejection_reason(media, slot=slot) is not None
        ):
            return ""
        return _asset_url_with_preference(media, prefer_video=prefer_video)
    return ""


def _media_candidate_sources(media: Json) -> list[Json]:
    sources: list[Json] = []
    for key in ("selected", "selection", "candidate"):
        value = media.get(key)
        if isinstance(value, dict):
            sources.append(value)
    value = media.get("storyboard_asset")
    if isinstance(value, dict):
        sources.append(value)
    value = media.get("selected_candidates")
    if isinstance(value, list):
        sources.extend(candidate for candidate in value if isinstance(candidate, dict))
    value = media.get("candidate_pool")
    if isinstance(value, list):
        for candidate in value:
            if isinstance(candidate, dict):
                marked = dict(candidate)
                marked["_renderer_allow_remote"] = False
                sources.append(marked)
    return sources


def _kind_from_slot(slot: Json, asset: Json) -> str:
    raw = " ".join(str(value or "").lower() for value in (slot.get("kind"), asset.get("source"), asset.get("kind")))
    if "video" in raw or "footage" in raw:
        return "video"
    if "gif" in raw:
        return "gif"
    return "image"


def _fill_media_slot(
    html: str,
    *,
    slot_name: str,
    media: Json,
    slot: Json,
    allow_rejected_media_for_render: bool = False,
) -> str:
    slot_meta = media.get("slot") if isinstance(media.get("slot"), dict) else {}
    asset_id = str(media.get("asset_id") or slot_meta.get("asset_id") or "").strip()
    kind = str(media.get("kind") or slot_meta.get("kind") or slot.get("kind") or "").lower()
    role = str(slot.get("role") or slot_meta.get("girly_asset_role") or "").strip()
    wants_video = _slot_wants_video(slot_name=slot_name, role=role, kind=kind)
    media_url = _media_url(
        media,
        prefer_video=wants_video,
        allow_rejected_media_for_render=allow_rejected_media_for_render,
    )
    if wants_video and not _is_direct_video_url(media_url):
        fallback_image_url = _media_url(
            media,
            prefer_video=False,
            allow_rejected_media_for_render=allow_rejected_media_for_render,
        )
        if fallback_image_url:
            media_url = fallback_image_url
            wants_video = False
    if not wants_video and _is_direct_video_url(media_url):
        wants_video = True
    if not media_url:
        return html

    def replace(match: re.Match[str]) -> str:
        tag = match.group("tag")
        attrs = match.group("attrs")
        inner = match.group("inner")
        if "data-girly-filled-media" in attrs:
            return match.group(0)
        common_attrs = (
            f'{attrs} data-girly-filled-media="true" data-girly-slot="{escape(slot_name, quote=True)}"'
            f' data-girly-role="{escape(role, quote=True)}"'
        )
        if asset_id:
            common_attrs += f' data-asset-id="{escape(asset_id, quote=True)}"'
        url = _css_url(media_url)
        if wants_video:
            content = (
                f'<video class="girly-media-fill" src="{escape(_url_for_html(media_url), quote=True)}" '
                "autoplay muted loop playsinline></video>"
            )
            return f"<{tag}{common_attrs}>{content}</{tag}>"
        style = f"background-image: url({url}); background-size: cover; background-position: center;"
        common_attrs = _merge_style_attr(common_attrs, style)
        return f"<{tag}{common_attrs}>{inner}</{tag}>"

    return _replace_first_class_tag(html, slot_name, replace)


def _slot_wants_video(*, slot_name: str, role: str, kind: str) -> bool:
    slot_lower = slot_name.lower()
    if any(token in slot_lower for token in ("photo", "image", "item", "mail", "science")):
        return False
    text = f"{slot_lower} {role} {kind}".lower()
    return "video" in text or "broll" in text or "background" in role.lower()


def _is_direct_video_url(value: str) -> bool:
    return bool(re.search(r"\.(mp4|webm|mov)(?:[?#].*)?$", str(value or ""), flags=re.IGNORECASE))


def _fill_text_slot(html: str, *, slot_name: str, text: str, slot: Json, scene: Json) -> str:
    formatted = format_timed_text_html(
        text,
        scene=scene,
        max_words=int(slot.get("max_words") or 7),
        line_break=True,
    )

    def replace(match: re.Match[str]) -> str:
        tag = match.group("tag")
        attrs = match.group("attrs")
        attrs = f'{attrs} data-girly-filled-text="true" data-girly-slot="{escape(slot_name, quote=True)}"'
        return f"<{tag}{attrs}>{formatted}</{tag}>"

    return _replace_first_class_tag(html, slot_name, replace)


def format_timed_text_html(
    text: str,
    *,
    scene: Json | None = None,
    max_words: int = 7,
    line_break: bool = True,
) -> str:
    """Render exact visible text and add timing hooks when scene word timings exist."""

    raw_text = str(text or "").strip()
    if not raw_text:
        return ""
    lines = _line_break_text(raw_text, max_words=max_words) if line_break else [raw_text]
    timings = _timed_words_for_scene(scene or {})
    cursor = {"index": 0}
    return "<br>".join(_wrap_line_with_timed_word_spans(line, timings=timings, cursor=cursor) for line in lines)


def _timed_words_for_scene(scene: Json) -> list[Json]:
    for key in ("timed_words_for_render", "word_timings"):
        words = scene.get(key)
        if isinstance(words, list) and words:
            return [word for word in words if isinstance(word, dict)]
    return []


def _wrap_line_with_timed_word_spans(line: str, *, timings: list[Json], cursor: dict[str, int]) -> str:
    if not timings:
        return escape(line)
    result: list[str] = []
    position = 0
    for match in TIMED_WORD_RE.finditer(line):
        start, end = match.span()
        if start > position:
            result.append(escape(line[position:start]))
        token = match.group(0)
        timing = _next_timing_for_token(token, timings=timings, cursor=cursor)
        if timing:
            word_index = str(timing.get("index") or timing.get("word_index") or "").strip()
            if word_index:
                voice_word = str(timing.get("word") or timing.get("text") or token).strip()
                start_sec = timing.get("start_sec", timing.get("appear_sec"))
                attrs = [
                    'class="sync-word"',
                    f'data-word-index="{escape(word_index, quote=True)}"',
                    f'data-voice-word-index="{escape(word_index, quote=True)}"',
                    f'data-voice-word="{escape(voice_word, quote=True)}"',
                ]
                if start_sec is not None:
                    attrs.append(f'data-voice-start-sec="{escape(str(start_sec), quote=True)}"')
                result.append(
                    f"<span {' '.join(attrs)}>{escape(token)}</span>"
                )
            else:
                result.append(escape(token))
        else:
            result.append(escape(token))
        position = end
    if position < len(line):
        result.append(escape(line[position:]))
    return "".join(result)


def _next_timing_for_token(token: str, *, timings: list[Json], cursor: dict[str, int]) -> Json | None:
    wanted = _normalize_timing_token(token)
    if not wanted:
        return None
    start = max(0, int(cursor.get("index") or 0))
    for index in range(start, len(timings)):
        candidate = timings[index]
        candidate_text = str(candidate.get("word") or candidate.get("text") or "").strip()
        if _normalize_timing_token(candidate_text) == wanted:
            cursor["index"] = index + 1
            return candidate
    return None


def _normalize_timing_token(value: str) -> str:
    lowered = str(value or "").casefold().replace("ё", "е")
    return re.sub(r"^[^\wА-Яа-яЁё0-9]+|[^\wА-Яа-яЁё0-9]+$", "", lowered, flags=re.UNICODE)


def _fill_missing_registry_text_slots(
    html: str,
    *,
    scene: Json,
    unit: Json,
    filled_text_slots: set[str],
    filled_text_values: dict[str, str],
) -> str:
    voiceover = str(scene.get("voiceover_line") or unit.get("voiceover_line") or "").strip()
    words = voiceover.split()
    spoken_slots = [
        slot
        for slot in unit.get("registry_text_slots") or []
        if isinstance(slot, dict) and "spoken_fragment" in str(slot.get("source") or "")
    ]
    has_spoken_text = any(str(slot.get("slot") or "").strip() in filled_text_slots for slot in spoken_slots)
    fallback_filled = False
    for slot in unit.get("registry_text_slots") or []:
        if not isinstance(slot, dict):
            continue
        slot_name = str(slot.get("slot") or "").strip()
        if not slot_name or "spoken_fragment" not in str(slot.get("source") or ""):
            continue
        max_words = max(1, int(slot.get("max_words") or 3))
        if slot_name in filled_text_slots:
            continue
        if not has_spoken_text and not fallback_filled:
            text = " ".join(words[:max_words]).strip()
            if text:
                synthetic_slot = {
                    "slot": slot_name,
                    "slot_type": "text",
                    "text_source": "spoken_fragment",
                    "max_words": max_words,
                }
                next_html = _fill_text_slot(html, slot_name=slot_name, text=text, slot=synthetic_slot, scene=scene)
                if next_html != html:
                    filled_text_slots.add(slot_name)
                    filled_text_values[slot_name] = text
                    fallback_filled = True
                    html = next_html
                    continue
        html = _hide_text_slot(html, slot_name=slot_name)
    return html


def _hide_text_slot(html: str, *, slot_name: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group("tag")
        attrs = match.group("attrs")
        attrs = f'{attrs} data-girly-hidden-text="true"'
        attrs = _merge_style_attr(attrs, "visibility: hidden;")
        return f"<{tag}{attrs}></{tag}>"

    return _replace_first_class_tag(html, slot_name, replace)


def _replace_first_class_tag(html: str, class_name: str, replace: Any) -> str:
    pattern = re.compile(
        rf"<(?P<tag>[a-z0-9]+)\b(?P<attrs>[^>]*\bclass=[\"'][^\"']*\b{re.escape(class_name)}\b[^\"']*[\"'][^>]*)>"
        r"(?P<inner>.*?)</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub(replace, html, count=1)


def _text_for_slot(*, slot: Json, scene: Json) -> str:
    text = str(slot.get("text") or "").strip()
    source = str(slot.get("text_source") or "").strip()
    voiceover = str(scene.get("voiceover_line") or (scene.get("girly_scene_unit") or {}).get("voiceover_line") or "").strip()
    if text and (source != "spoken_fragment" or text in voiceover):
        return text
    if source in {"ui_label", "metadata_or_ui_label", "metadata_or_short_label", "metadata_or_proof_numbers"}:
        return text
    return _spoken_fragment_fallback(voiceover, max_words=int(slot.get("max_words") or 7))


def _spoken_fragment_fallback(text: str, *, max_words: int) -> str:
    words = text.split()
    if not words:
        return ""
    return " ".join(words[:max(1, max_words)])


def _line_break_text(text: str, *, max_words: int) -> list[str]:
    words = text.split()
    if not words:
        return [text]
    max_chars = 11 if max_words <= 4 else 15
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and (len(candidate) > max_chars or len(current) >= max(1, min(max_words, 3))):
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _merge_style_attr(attrs: str, style: str) -> str:
    match = re.search(r"\sstyle=([\"'])(?P<style>.*?)\1", attrs, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return f'{attrs} style="{escape(style, quote=True)}"'
    quote_char = match.group(1)
    merged = f"{match.group('style').rstrip(';')}; {style}"
    return attrs[: match.start()] + f' style={quote_char}{escape(merged, quote=True)}{quote_char}' + attrs[match.end() :]


def _css_url(value: str) -> str:
    return escape(_url_for_html(value), quote=True)


def _is_low_quality_thumbnail_url(value: str) -> bool:
    return "encrypted-tbn" in str(value or "").lower()


def _is_local_render_url(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text.startswith("__STATIC_FILE__") or text.startswith("file://") or Path(text).expanduser().is_absolute())


def _url_for_html(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("__STATIC_FILE__"):
        return text
    if re.match(r"^[a-z][a-z0-9+.-]*://", text, flags=re.IGNORECASE) or text.startswith("data:"):
        return text
    path = Path(text).expanduser()
    if not path.is_absolute():
        return text
    return path.as_uri() if path.exists() else "file://" + quote(str(path))


def _scene_label(scene: Json, index: int) -> str:
    unit = scene.get("girly_scene_unit") if isinstance(scene.get("girly_scene_unit"), dict) else {}
    girly = scene.get("girly_scene") if isinstance(scene.get("girly_scene"), dict) else {}
    return str(unit.get("scene_id") or girly.get("scene_id") or f"Scene {index}")


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else line for line in str(text).splitlines())


def materialize_scenes_for_girly_static(storyboard_payload: Json) -> list[Json]:
    payload = deepcopy(storyboard_payload)
    if isinstance(payload.get("girly_scene"), dict) and payload.get("voiceover_line"):
        return [materialize_girly_scene_unit(payload)]
    storyboard = payload.get("storyboard_v2") if isinstance(payload.get("storyboard_v2"), dict) else payload
    scenes = storyboard.get("scenes") if isinstance(storyboard.get("scenes"), list) else []
    return [materialize_girly_scene_unit(scene) for scene in scenes if isinstance(scene, dict)]
