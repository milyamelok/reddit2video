from __future__ import annotations

from collections import Counter
from html import unescape
import re
from typing import Any, Literal

from pydantic import BaseModel, Field


Json = dict[str, Any]


class ScenePublishabilityInspection(BaseModel):
    scene_id: int
    duration_frames: int
    has_media: bool
    has_real_media: bool
    has_generated_visual: bool
    media_asset_ids: list[str] = Field(default_factory=list)
    video_asset_ids: list[str] = Field(default_factory=list)
    image_asset_ids: list[str] = Field(default_factory=list)
    generated_visual_asset_ids: list[str] = Field(default_factory=list)
    has_sync_caption: bool
    sync_caption_mode: str
    sync_caption_chars: int
    visual_archetype: str = ""
    warnings: list[str] = Field(default_factory=list)


class HtmlPayloadPublishabilityReport(BaseModel):
    verdict: Literal["pass", "fail"]
    blocking_defects: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    scene_count: int
    duration_frames: int
    duration_sec: float
    media_scene_count: int
    media_scene_ratio: float
    real_media_scene_count: int
    real_media_scene_ratio: float
    generated_visual_scene_count: int
    generated_visual_scene_ratio: float
    text_only_scene_count: int
    max_text_only_run: int
    unique_asset_count: int
    video_asset_count: int
    image_asset_count: int
    generated_visual_count: int
    visual_archetype_count: int
    dominant_visual_archetype_ratio: float
    sync_caption_replace_scene_count: int
    scenes: list[ScenePublishabilityInspection] = Field(default_factory=list)


def inspect_html_payload(
    payload: Json,
    *,
    min_scenes: int = 8,
    min_duration_sec: float = 20.0,
    min_media_scene_ratio: float = 0.45,
    min_unique_assets: int = 6,
    min_video_assets: int = 0,
    min_visual_archetypes: int = 4,
    max_dominant_visual_archetype_ratio: float = 0.55,
    min_real_media_scene_ratio: float = 0.35,
    max_generated_visual_scene_ratio: float = 0.65,
    max_text_only_run: int = 3,
    require_audio: bool = True,
) -> HtmlPayloadPublishabilityReport:
    """Detect "one text over a slideshow" failure before a render is published.

    This is deliberately a structural gate, not a taste score. Gemini can still
    act as a post-render oracle, but this check prevents easy metric grinding:
    hiding weak media or collapsing into mostly text-only scenes is a release
    blocker regardless of a flattering model score.
    """

    scenes = payload.get("scenes") if isinstance(payload.get("scenes"), list) else []
    fps = _positive_float(payload.get("fps")) or 30.0
    duration_frames = int(_positive_float(payload.get("duration_frames")) or 0)
    inspections = [_inspect_scene(scene, fallback=index) for index, scene in enumerate(scenes, start=1)]

    media_scene_count = sum(1 for scene in inspections if scene.has_media)
    real_media_scene_count = sum(1 for scene in inspections if scene.has_real_media)
    generated_visual_scene_count = sum(1 for scene in inspections if scene.has_generated_visual)
    text_only_scene_count = len(inspections) - media_scene_count
    unique_asset_ids = {
        asset_id
        for scene in inspections
        for asset_id in scene.media_asset_ids
        if asset_id
    }
    video_asset_ids = {
        asset_id
        for scene in inspections
        for asset_id in scene.video_asset_ids
        if asset_id
    }
    image_asset_ids = {
        asset_id
        for scene in inspections
        for asset_id in scene.image_asset_ids
        if asset_id
    }
    generated_visual_ids = {
        asset_id
        for scene in inspections
        for asset_id in scene.generated_visual_asset_ids
        if asset_id
    }
    media_scene_ratio = round(media_scene_count / len(inspections), 4) if inspections else 0.0
    real_media_scene_ratio = round(real_media_scene_count / len(inspections), 4) if inspections else 0.0
    generated_visual_scene_ratio = round(generated_visual_scene_count / len(inspections), 4) if inspections else 0.0
    max_text_run = _max_text_only_run(inspections)
    replace_count = sum(1 for scene in inspections if scene.sync_caption_mode == "replace")
    archetype_counts = Counter(scene.visual_archetype or "text_only" for scene in inspections)
    visual_archetype_count = len(archetype_counts)
    dominant_visual_archetype_ratio = (
        round(max(archetype_counts.values()) / len(inspections), 4)
        if inspections and archetype_counts
        else 0.0
    )

    blocking_defects: list[str] = []
    warnings: list[str] = []
    duration_sec = round(duration_frames / fps, 3) if fps else 0.0
    required_visual_archetypes = min(min_visual_archetypes, len(inspections))
    if len(inspections) < min_scenes:
        blocking_defects.append(f"Only {len(inspections)} scenes; expected at least {min_scenes}.")
    if duration_sec < min_duration_sec:
        blocking_defects.append(f"Duration is {duration_sec:.1f}s; expected at least {min_duration_sec:.1f}s.")
    if require_audio and not str(payload.get("audio_public_path") or "").strip():
        blocking_defects.append("No audio_public_path is attached to the render payload.")
    if media_scene_ratio < min_media_scene_ratio:
        blocking_defects.append(
            f"Only {media_scene_ratio:.0%} of scenes have resolved media; expected at least {min_media_scene_ratio:.0%}."
        )
    if len(unique_asset_ids) < min_unique_assets:
        blocking_defects.append(f"Only {len(unique_asset_ids)} unique media assets; expected at least {min_unique_assets}.")
    if len(video_asset_ids) < min_video_assets:
        blocking_defects.append(
            f"Only {len(video_asset_ids)} video assets; expected at least {min_video_assets} "
            "for a motion-rich publication render."
        )
    if real_media_scene_ratio < min_real_media_scene_ratio:
        blocking_defects.append(
            f"Only {real_media_scene_ratio:.0%} of scenes use real media; expected at least "
            f"{min_real_media_scene_ratio:.0%}. Generated fallback visuals cannot carry a publication render alone."
        )
    if generated_visual_scene_ratio > max_generated_visual_scene_ratio:
        blocking_defects.append(
            f"Generated fallback visuals appear in {generated_visual_scene_ratio:.0%} of scenes; maximum allowed is "
            f"{max_generated_visual_scene_ratio:.0%} for a publication render."
        )
    if visual_archetype_count < required_visual_archetypes:
        blocking_defects.append(
            f"Only {visual_archetype_count} visual archetypes; expected at least {required_visual_archetypes}."
        )
    if inspections and dominant_visual_archetype_ratio > max_dominant_visual_archetype_ratio:
        blocking_defects.append(
            "Dominant visual archetype appears in "
            f"{dominant_visual_archetype_ratio:.0%} of scenes; maximum allowed is "
            f"{max_dominant_visual_archetype_ratio:.0%}."
        )
    if max_text_run > max_text_only_run:
        blocking_defects.append(
            f"{max_text_run} text-only scenes appear in a row; maximum allowed run is {max_text_only_run}."
        )
    if inspections and text_only_scene_count == len(inspections):
        blocking_defects.append("Every scene is text-only; this is not a publishable video.")
    if (
        inspections
        and replace_count == len(inspections)
        and (
            visual_archetype_count < required_visual_archetypes
            or dominant_visual_archetype_ratio > max_dominant_visual_archetype_ratio
        )
    ):
        warnings.append(
            "Every scene uses sync_caption_mode=replace; keep this only when the visual layer still carries scene meaning."
        )
    warnings.extend(_scene_warnings(inspections))

    return HtmlPayloadPublishabilityReport(
        verdict="fail" if blocking_defects else "pass",
        blocking_defects=blocking_defects,
        warnings=warnings,
        scene_count=len(inspections),
        duration_frames=duration_frames,
        duration_sec=duration_sec,
        media_scene_count=media_scene_count,
        media_scene_ratio=media_scene_ratio,
        real_media_scene_count=real_media_scene_count,
        real_media_scene_ratio=real_media_scene_ratio,
        generated_visual_scene_count=generated_visual_scene_count,
        generated_visual_scene_ratio=generated_visual_scene_ratio,
        text_only_scene_count=text_only_scene_count,
        max_text_only_run=max_text_run,
        unique_asset_count=len(unique_asset_ids),
        video_asset_count=len(video_asset_ids),
        image_asset_count=len(image_asset_ids),
        generated_visual_count=len(generated_visual_ids),
        visual_archetype_count=visual_archetype_count,
        dominant_visual_archetype_ratio=dominant_visual_archetype_ratio,
        sync_caption_replace_scene_count=replace_count,
        scenes=inspections,
    )


def _inspect_scene(scene: Any, *, fallback: int) -> ScenePublishabilityInspection:
    payload = scene if isinstance(scene, dict) else {}
    html = str(payload.get("html") or "")
    assets = _asset_sources_by_id(html)
    assets.update(_bridge_asset_sources_by_id(payload))
    assets.update(_semantic_visual_sources_by_id(payload))
    asset_ids = sorted(assets)
    video_ids = sorted(asset_id for asset_id, source in assets.items() if source == "video")
    generated_visual_ids = sorted(asset_id for asset_id, source in assets.items() if source == "generated_visual")
    image_ids = sorted(asset_id for asset_id, source in assets.items() if source not in {"video", "generated_visual"})
    real_media_ids = sorted(asset_id for asset_id, source in assets.items() if source != "generated_visual")
    sync_caption = _sync_caption_text(html)
    sync_mode = _sync_caption_mode(html)
    visual_archetype = _visual_archetype(payload, assets=assets)
    warnings: list[str] = []
    if sync_mode == "replace" and not asset_ids:
        warnings.append("replace_caption_without_media")
    if len(sync_caption) > 170:
        warnings.append("long_scene_caption")
    return ScenePublishabilityInspection(
        scene_id=_scene_id(payload, fallback=fallback),
        duration_frames=int(_positive_float(payload.get("duration_frames")) or 0),
        has_media=bool(asset_ids),
        has_real_media=bool(real_media_ids),
        has_generated_visual=bool(generated_visual_ids),
        media_asset_ids=asset_ids,
        video_asset_ids=video_ids,
        image_asset_ids=image_ids,
        generated_visual_asset_ids=generated_visual_ids,
        has_sync_caption=bool(sync_caption),
        sync_caption_mode=sync_mode,
        sync_caption_chars=len(sync_caption),
        visual_archetype=visual_archetype,
        warnings=warnings,
    )


def _asset_sources_by_id(html: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in re.finditer(r"\bdata-asset-id=(?P<quote>['\"])(?P<id>.*?)(?P=quote)", html, flags=re.I | re.S):
        asset_id = unescape(match.group("id")).strip()
        if not asset_id:
            continue
        tag_start = html.rfind("<", 0, match.start())
        tag_end = html.find(">", match.end())
        opening_tag = html[tag_start : tag_end + 1] if tag_start >= 0 and tag_end >= 0 else match.group(0)
        close_tag = html.find("</div>", tag_end + 1) if tag_end >= 0 else -1
        inner_html = html[tag_end + 1 : close_tag] if tag_end >= 0 and close_tag >= 0 else ""
        haystack = f"{opening_tag} {inner_html[:600]}"
        result[asset_id] = "video" if _looks_like_video_asset(haystack) else "image"
    return result


def _bridge_asset_sources_by_id(scene: Json) -> dict[str, str]:
    result: dict[str, str] = {}
    assets = scene.get("bridge_media_assets")
    if not isinstance(assets, list):
        return result
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("id") or "").strip()
        src = str(asset.get("src") or "").strip()
        if not asset_id or not src:
            continue
        kind = str(asset.get("kind") or "").strip().lower()
        result[asset_id] = "video" if kind == "video" or _looks_like_video_asset(src) else "image"
    return result


def _semantic_visual_sources_by_id(scene: Json) -> dict[str, str]:
    visual = scene.get("semantic_visual")
    if not isinstance(visual, dict):
        return {}
    visual_id = str(visual.get("id") or "").strip()
    if not visual_id or not _valid_semantic_visual(visual):
        return {}
    return {visual_id: "generated_visual"}


def _visual_archetype(scene: Json, *, assets: dict[str, str]) -> str:
    visual = scene.get("semantic_visual")
    if isinstance(visual, dict) and _valid_semantic_visual(visual):
        topic = _archetype_token(visual.get("topic")) or "general"
        layout = _archetype_token(visual.get("layout")) or "default"
        motifs = visual.get("motifs")
        motif_tokens = sorted(
            token
            for token in (_archetype_token(motif) for motif in (motifs if isinstance(motifs, list) else []))
            if token
        )
        return f"semantic:{topic}:{layout}:{','.join(motif_tokens[:4])}"

    if assets:
        asset_id, source = sorted(assets.items())[0]
        return f"{source}:{_archetype_token(asset_id)}"

    return "text_only"


def _valid_semantic_visual(visual: Json) -> bool:
    motifs = visual.get("motifs")
    return (
        str(visual.get("kind") or "") == "semantic_motion"
        and str(visual.get("quality") or "") == "publishable_visual"
        and isinstance(motifs, list)
        and len([motif for motif in motifs if str(motif or "").strip()]) >= 2
    )


def _archetype_token(value: Any) -> str:
    token = re.sub(r"[^a-z0-9_-]+", "_", str(value or "").strip().casefold())
    return token.strip("_")


def _looks_like_video_asset(snippet: str) -> bool:
    return bool(
        re.search(r"<video\b", snippet, flags=re.I)
        or re.search(r"\.(?:mp4|webm|mov|m3u8)(?:[?#\"')\s<>]|$)", snippet, flags=re.I)
    )


def _sync_caption_text(html: str) -> str:
    match = re.search(r"<div\b[^>]*\bdata-girly-sync-caption=['\"]true['\"][^>]*>(.*?)</div>", html, flags=re.I | re.S)
    if not match:
        return ""
    text = re.sub(r"<br\s*/?>", " ", match.group(1), flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _sync_caption_mode(html: str) -> str:
    match = re.search(r"\bdata-sync-caption-mode=(?P<quote>['\"])(?P<mode>.*?)(?P=quote)", html, flags=re.I | re.S)
    return match.group("mode").strip() if match else ""


def _max_text_only_run(scenes: list[ScenePublishabilityInspection]) -> int:
    longest = 0
    current = 0
    for scene in scenes:
        if scene.has_media:
            longest = max(longest, current)
            current = 0
        else:
            current += 1
    return max(longest, current)


def _scene_warnings(scenes: list[ScenePublishabilityInspection]) -> list[str]:
    warnings: list[str] = []
    for scene in scenes:
        for warning in scene.warnings:
            warnings.append(f"scene {scene.scene_id}: {warning}")
    return warnings


def _scene_id(scene: Json, *, fallback: int) -> int:
    value = scene.get("scene_id") or fallback
    try:
        return int(float(value))
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value or ""))
        return int(match.group(0)) if match else fallback


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
