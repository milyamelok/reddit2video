from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from reddit2video.models import ScenePipelineBatch, ScenePipelineItem, VoiceoverScriptBatch


GOOGLE_IMAGE_SOURCE = "Google Images"
GIPHY_SOURCE = "Giphy"
TELEGRAM_STICKERS_SOURCE = "Telegram stickers"
AI_GENERATED_SOURCE = "AI-generated"
STOCK_FOOTAGE_SOURCE = "Stock/Footage"

SUPPORTED_STORYBOARD_ASSET_SOURCES = {
    GOOGLE_IMAGE_SOURCE,
    GIPHY_SOURCE,
    TELEGRAM_STICKERS_SOURCE,
    AI_GENERATED_SOURCE,
    STOCK_FOOTAGE_SOURCE,
}

UNAVAILABLE_STORYBOARD_ASSET_SOURCES: set[str] = set()


def storyboard_assets_to_scene_batch(
    voiceover_batch: VoiceoverScriptBatch,
    *,
    period_key: str | None = None,
) -> ScenePipelineBatch:
    """Build a resolver-compatible scene batch from storyboard_v2 visual assets.

    This deliberately does not ask Gemini to invent media slots. It only projects
    the assets already requested by the voiceover storyboard prompt into the
    existing MediaResolverNode contract.
    """

    items = [_storyboard_item_to_scene_item(item) for item in voiceover_batch.items]
    source_counts: dict[str, int] = {}
    unavailable_counts: dict[str, int] = {}
    skipped_counts: dict[str, int] = {}
    slot_count = 0
    for item in items:
        for scene in (item.scene_plan or {}).get("scenes", []):
            for slot in scene.get("media_slots", []) or []:
                slot_count += 1
                source = str(slot.get("storyboard_source") or "")
                source_counts[source] = source_counts.get(source, 0) + 1
                if str(slot.get("source_strategy") or "") == "none":
                    skipped_counts[source] = skipped_counts.get(source, 0) + 1
                    if source in UNAVAILABLE_STORYBOARD_ASSET_SOURCES:
                        unavailable_counts[source] = unavailable_counts.get(source, 0) + 1

    return ScenePipelineBatch(
        items=items,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        metadata={
            "node": "storyboard_asset_plan",
            "period_key": period_key,
            "items": len(items),
            "media_slots": slot_count,
            "source_counts": source_counts,
            "skipped_source_counts": skipped_counts,
            "unavailable_source_counts": unavailable_counts,
            "supported_sources": sorted(SUPPORTED_STORYBOARD_ASSET_SOURCES),
            "unavailable_sources": sorted(UNAVAILABLE_STORYBOARD_ASSET_SOURCES),
        },
    )


def _storyboard_item_to_scene_item(item: Any) -> ScenePipelineItem:
    storyboard = _storyboard_payload(item)
    scenes = list(storyboard.get("scenes") or [])
    scene_plan = {
        "target_scene_count": len(scenes),
        "scenes": [_scene_payload(scene, index) for index, scene in enumerate(scenes, start=1)],
        "asset_budget_notes": [
            "Media slots are projected from storyboard_v2.scenes[].visual_assets[].",
            "No new visual ideas were generated after voiceover planning.",
        ],
        "grouping_notes": [],
    }
    timed_scenes = _timed_scenes_from_storyboard(scenes)
    unavailable = _unavailable_source_summary(scene_plan)
    skipped_reasons = _skip_reason_summary(scene_plan)
    validator_warnings = [
        f"Storyboard asset source {source!r} is not implemented; {count} slots marked optional/skipped."
        for source, count in sorted(unavailable.items())
    ]
    validator_warnings.extend(
        f"Storyboard asset skipped by policy bridge: {reason} ({count} slots)."
        for reason, count in sorted(skipped_reasons.items())
        if not reason.startswith("storyboard_asset_source_not_implemented")
    )
    return ScenePipelineItem(
        post_id=item.post_id,
        subreddit=item.subreddit,
        title=item.title,
        status="pass",
        audio_path="",
        alignment={},
        semantic_fragments={},
        timed_fragments=[],
        scene_plan=scene_plan,
        timed_scenes=timed_scenes,
        validator_errors=[],
        validator_warnings=validator_warnings,
        attempts=0,
        from_cache=False,
        cache_path="",
        timed_words=[],
        metadata={
            "source_node": "voiceover_script.storyboard_v2",
            "voiceover_prompt_version": (item.metadata or {}).get("prompt_version"),
            "storyboard_title": storyboard.get("title"),
            "storyboard_scene_mix": storyboard.get("scene_mix", {}),
            "unavailable_asset_sources": unavailable,
            "skipped_asset_reasons": skipped_reasons,
        },
    )


def _storyboard_payload(item: Any) -> dict[str, Any]:
    script = dict(getattr(item, "script", {}) or {})
    storyboard = script.get("storyboard_v2")
    if isinstance(storyboard, dict):
        return storyboard
    if all(key in script for key in ("source_digest", "story_strategy", "voiceover", "scenes")):
        return script
    return {}


def _scene_payload(scene: dict[str, Any], index: int) -> dict[str, Any]:
    scene_id = int(scene.get("scene_id") or index)
    scene_type = str(scene.get("scene_type") or "COLLAGE")
    visual_assets = list(scene.get("visual_assets") or [])
    avatar_broll_slot = (
        _avatar_background_slot(scene_id=scene_id, scene=scene)
        if scene_type.strip().upper() == "AVATAR" and not _has_stock_footage_asset(visual_assets)
        else None
    )
    media_slots = [
        _asset_to_media_slot(scene_id=scene_id, asset_index=asset_index, asset=asset, scene=scene)
        for asset_index, asset in enumerate(visual_assets, start=1)
    ]
    if avatar_broll_slot:
        media_slots.insert(0, avatar_broll_slot)
    screen_text = str(scene.get("voiceover_line") or "").strip() or " "
    screen_role = "marquee" if scene_type.strip().upper() == "AVATAR" else "hero"
    return {
        "scene_id": scene_id,
        "fragment_ids": [scene_id],
        "scene_tag": _scene_tag(scene_type, scene_id),
        "visual_density": "high" if media_slots else "low",
        "visual_mode": _visual_mode(scene_type, media_slots),
        "text_unit_policy": "spoken_words",
        "template_hint": _template_hint(scene_type, media_slots),
        "attention_job": str(scene.get("retention_function") or scene.get("visual_direction") or "Storyboard scene."),
        "screen_rows": [{"text": screen_text, "role": screen_role, "source_fragment_ids": [scene_id]}],
        "media_slots": media_slots,
        "build_order": [slot["asset_id"] for slot in media_slots],
        "exit_energy": str(scene.get("animation") or "Cut."),
        "avatar_overlay": _avatar_overlay_spec(scene) if scene_type.strip().upper() == "AVATAR" else None,
        "storyboard_scene": scene,
    }


def _avatar_background_slot(*, scene_id: int, scene: dict[str, Any]) -> dict[str, Any]:
    background = str(scene.get("background") or "").strip()
    visual_direction = str(scene.get("visual_direction") or "").strip()
    query_seed = _clean_avatar_background_seed(background or visual_direction or "wellness lifestyle vertical background")
    query = query_seed
    asset = {
        "asset": query_seed,
        "source": STOCK_FOOTAGE_SOURCE,
        "search_query": query,
        "appears_on_word": "",
        "why": "Background footage for small bottom-right AI avatar overlay.",
    }
    return {
        "asset_id": f"s{scene_id:03d}_avatar_broll_bg",
        "source_fragment_ids": [scene_id],
        "required": True,
        "kind": "video",
        "role": "background_texture",
        "source_strategy": "pinterest_search",
        "search_query_ru": None,
        "search_query_en": query,
        "visual_prompt": f"Soft vertical background video for avatar scene: {query_seed}",
        "avoid": ["text-heavy", "screenshot", "watermark", "low resolution", "busy foreground face"],
        "crop_hint": "vertical 9:16 center-crop safe background video with room for text and bottom-right avatar",
        "motion_hint": "ambient motion loop",
        "storyboard_source": STOCK_FOOTAGE_SOURCE,
        "storyboard_asset": asset,
        "normalization_note": "AVATAR scenes synthesize a Pinterest/Stock background video from scene.background.",
    }


def _clean_avatar_background_seed(value: str) -> str:
    cleaned = " ".join(str(value or "").replace("_", " ").split())
    cleaned = re.sub(r"(?i)\bavatar\s+background\s*:\s*", "", cleaned)
    cleaned = re.sub(r"(?i)\bblurred\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,:-")
    return cleaned or "wellness lifestyle vertical background"


def _has_stock_footage_asset(visual_assets: list[Any]) -> bool:
    for asset in visual_assets:
        if not isinstance(asset, dict):
            continue
        source = str(asset.get("source") or "").lower()
        if "stock" in source or "footage" in source:
            return True
    return False


def _avatar_overlay_spec(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": True,
        "position": "bottom_right",
        "area_fraction": 0.2,
        "max_width_fraction": 0.34,
        "max_height_fraction": 0.34,
        "safe_margin_fraction": 0.045,
        "text_behavior": "center_marquee_or_kinetic_line",
        "background_video_source": "pinterest_search",
        "notes": str(scene.get("visual_direction") or ""),
    }


def _asset_to_media_slot(
    *,
    scene_id: int,
    asset_index: int,
    asset: dict[str, Any],
    scene: dict[str, Any],
) -> dict[str, Any]:
    source = str(asset.get("source") or "").strip()
    asset_name = str(asset.get("asset") or f"asset_{asset_index}").strip()
    query = _query_for_source(source=source, asset=asset, scene=scene, asset_name=asset_name)
    scene_asset_count = len(scene.get("visual_assets") or [])
    asset_id = f"s{scene_id:03d}_storyboard_asset_{asset_index:02d}"
    source_fragment_ids = [scene_id]
    policy_skip_reason = _query_policy_skip_reason(source=source, query=query, asset_name=asset_name)
    girly_slot_plan = _girly_slot_plan_for_asset(scene=scene, asset_index=asset_index)
    girly_asset_role = str(asset.get("girly_asset_role") or girly_slot_plan.get("role") or "").strip() or None
    preferred_slot = str(asset.get("preferred_slot") or girly_slot_plan.get("slot") or "").strip() or None
    base = {
        "asset_id": asset_id,
        "source_fragment_ids": source_fragment_ids,
        "required": source in SUPPORTED_STORYBOARD_ASSET_SOURCES and bool(query) and not policy_skip_reason,
        "search_query_ru": None,
        "search_query_en": query if source in SUPPORTED_STORYBOARD_ASSET_SOURCES and not policy_skip_reason else None,
        "visual_prompt": (
            _visual_prompt_for_source(source=source, asset=asset, scene=scene, asset_name=asset_name)
            if source in SUPPORTED_STORYBOARD_ASSET_SOURCES and not policy_skip_reason
            else "Unavailable storyboard asset source."
        ),
        "avoid": [],
        "crop_hint": "9:16 safe, subject readable on phone",
        "motion_hint": _motion_hint(source, asset),
        "storyboard_source": source,
        "storyboard_asset": asset,
        "storyboard_asset_index": asset_index - 1,
        "girly_asset_role": girly_asset_role,
        "preferred_slot": preferred_slot,
        "girly_slot_plan": girly_slot_plan or None,
    }
    if policy_skip_reason:
        return {
            **base,
            "kind": "image",
            "role": "subject",
            "source_strategy": "none",
            "required": False,
            "skip_reason": policy_skip_reason,
        }
    if source == GOOGLE_IMAGE_SOURCE:
        return {
            **base,
            "kind": "image",
            "role": _role_from_asset(asset),
            "source_strategy": "google_images",
        }
    if source == GIPHY_SOURCE:
        return {
            **base,
            "kind": "gif",
            "role": "emotional_texture",
            "source_strategy": "giphy",
        }
    if source == TELEGRAM_STICKERS_SOURCE:
        return {
            **base,
            "kind": "gif",
            "role": "emotional_texture",
            "source_strategy": "giphy",
            "normalization_note": "Telegram stickers temporarily routed to Giphy.",
        }
    if source == AI_GENERATED_SOURCE:
        return {
            **base,
            "kind": "image",
            "role": _role_from_asset(asset),
            "source_strategy": "generated",
            "generation_aspect_ratio": _generated_asset_aspect_ratio(scene=scene, scene_asset_count=scene_asset_count),
            "normalization_note": "AI-generated storyboard asset should be materialized by Vertex image generation.",
        }
    if source == STOCK_FOOTAGE_SOURCE:
        return {
            **base,
            "kind": "video",
            "role": "subject",
            "source_strategy": "pinterest_search",
            "crop_hint": "vertical 9:16 or center-crop safe video footage",
        }
    return {
        **base,
        "kind": "image",
        "role": "subject",
        "source_strategy": "none",
        "required": False,
        "skip_reason": f"storyboard_asset_source_not_implemented:{source or 'unknown'}",
    }


def _girly_slot_plan_for_asset(*, scene: dict[str, Any], asset_index: int) -> dict[str, Any]:
    girly_scene = scene.get("girly_scene") if isinstance(scene.get("girly_scene"), dict) else {}
    slot_plan = girly_scene.get("slot_plan") if isinstance(girly_scene.get("slot_plan"), list) else []
    zero_based_index = asset_index - 1
    for slot in slot_plan:
        if not isinstance(slot, dict) or slot.get("slot_type") != "media":
            continue
        if slot.get("visual_asset_index") == zero_based_index:
            return dict(slot)
    return {}


def _query_policy_skip_reason(*, source: str, query: str, asset_name: str) -> str:
    if source not in SUPPORTED_STORYBOARD_ASSET_SOURCES or source in {
        GIPHY_SOURCE,
        TELEGRAM_STICKERS_SOURCE,
        AI_GENERATED_SOURCE,
    }:
        return ""
    haystack = f"{query} {asset_name}".lower()
    for term in (
        "sticker",
        "app screen",
        "app display",
        "screenshot",
        "interface",
        "transparent background",
    ):
        if term in haystack:
            return f"storyboard_asset_query_disallowed_by_media_policy:{term}"
    return ""


def _query_for_source(*, source: str, asset: dict[str, Any], scene: dict[str, Any], asset_name: str) -> str:
    raw = str(asset.get("search_query") or asset_name or "").strip()
    if source == GOOGLE_IMAGE_SOURCE:
        return _clean_google_images_query(raw or asset_name)
    if source == TELEGRAM_STICKERS_SOURCE:
        return _giphy_query_from_sticker(raw or asset_name)
    if source == GIPHY_SOURCE:
        return _clean_giphy_query(raw or asset_name)
    if source == AI_GENERATED_SOURCE:
        return str(scene.get("ai_image_prompt") or asset.get("search_query") or asset_name or "").strip()
    return raw


def _clean_google_images_query(query: str) -> str:
    cleaned = " ".join(str(query or "").replace("_", " ").split())
    replacements = {
        "transparent background": "",
        "transparent": "",
        "png": "",
        "cutout": "",
        "isolated": "",
        "icon": "illustration",
        "icons": "illustrations",
        "иконка": "иллюстрация",
        "иконки": "иллюстрации",
    }
    lowered = cleaned
    for term, replacement in replacements.items():
        lowered = re.sub(rf"(?i)\b{re.escape(term)}\b", replacement, lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip(" ,")
    return lowered or "editorial object photo"


def _generated_asset_aspect_ratio(*, scene: dict[str, Any], scene_asset_count: int) -> str:
    scene_type = str(scene.get("scene_type") or "").strip().upper()
    if scene_asset_count <= 1 and scene_type == "AI_IMAGE":
        return "3:4"
    return "4:3"


def _visual_prompt_for_source(
    *,
    source: str,
    asset: dict[str, Any],
    scene: dict[str, Any],
    asset_name: str,
) -> str:
    if source == AI_GENERATED_SOURCE:
        return str(scene.get("ai_image_prompt") or asset.get("search_query") or asset_name).strip()
    if source in {GIPHY_SOURCE, TELEGRAM_STICKERS_SOURCE}:
        return _clean_giphy_query(asset_name)
    return asset_name


def _giphy_query_from_sticker(query: str) -> str:
    cleaned = _clean_giphy_query(query)
    lowered = cleaned.lower()
    if any(marker in lowered for marker in ("gif", "reaction", "meme")):
        return cleaned
    return f"{cleaned} reaction gif".strip()


def _clean_giphy_query(query: str) -> str:
    cleaned = " ".join(str(query or "").replace("_", " ").split())
    for term in ("telegram", "stickers", "sticker", "transparent background", "icon"):
        cleaned = cleaned.replace(term, " ")
        cleaned = cleaned.replace(term.title(), " ")
    return " ".join(cleaned.split()) or "funny reaction gif"


def _role_from_asset(asset: dict[str, Any]) -> str:
    haystack = " ".join(str(asset.get(key) or "").lower() for key in ("asset", "search_query", "why"))
    if any(marker in haystack for marker in ("scale", "receipt", "lab", "report", "chart", "bottle", "jar")):
        return "evidence_prop"
    if any(marker in haystack for marker in ("bridge", "monster", "demon", "excel", "metaphor")):
        return "metaphor"
    if any(marker in haystack for marker in ("cat", "meme", "side eye", "panic", "reaction")):
        return "emotional_texture"
    return "subject"


def _motion_hint(source: str, asset: dict[str, Any]) -> str:
    haystack = " ".join(str(asset.get(key) or "").lower() for key in ("asset", "search_query", "why"))
    if source in {GIPHY_SOURCE, TELEGRAM_STICKERS_SOURCE, STOCK_FOOTAGE_SOURCE}:
        return "loop"
    if any(marker in haystack for marker in ("punch", "panic", "shock", "meme", "cat")):
        return "pop_in"
    return "ken_burns"


def _scene_tag(scene_type: str, scene_id: int) -> str:
    if scene_id == 1:
        return "cold_hook"
    normalized = scene_type.strip().upper()
    if normalized == "TEXT_ONLY":
        return "punch"
    if normalized == "AVATAR":
        return "explain"
    if normalized == "AI_IMAGE":
        return "metaphor"
    return "context"


def _template_hint(scene_type: str, media_slots: list[dict[str, Any]]) -> str:
    normalized = scene_type.strip().upper()
    if normalized == "AVATAR":
        return "avatar_broll_marquee"
    if not media_slots:
        return "hero_text"
    if len(media_slots) >= 3:
        return "collage"
    if len(media_slots) == 2:
        return "split_comparison"
    return "text_with_media"


def _visual_mode(scene_type: str, media_slots: list[dict[str, Any]]) -> str:
    normalized = scene_type.strip().upper()
    if normalized == "AVATAR":
        return "avatar_overlay_with_broll"
    if media_slots:
        return "text_with_media"
    return "text_only"


def _timed_scenes_from_storyboard(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timed: list[dict[str, Any]] = []
    cursor = 0.0
    for index, scene in enumerate(scenes, start=1):
        duration = max(0.5, float(scene.get("duration_sec") or 0))
        start = cursor
        cursor += duration
        timed.append(
            {
                "scene_id": int(scene.get("scene_id") or index),
                "start_sec": round(start, 3),
                "end_sec": round(cursor, 3),
                "duration_sec": round(duration, 3),
                "timing_source": "storyboard_declared_duration",
            }
        )
    return timed


def _unavailable_source_summary(scene_plan: dict[str, Any]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for scene in scene_plan.get("scenes", []):
        for slot in scene.get("media_slots", []) or []:
            if str(slot.get("source_strategy") or "") != "none":
                continue
            source = str(slot.get("storyboard_source") or "unknown")
            if source not in UNAVAILABLE_STORYBOARD_ASSET_SOURCES:
                continue
            summary[source] = summary.get(source, 0) + 1
    return summary


def _skip_reason_summary(scene_plan: dict[str, Any]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for scene in scene_plan.get("scenes", []):
        for slot in scene.get("media_slots", []) or []:
            if str(slot.get("source_strategy") or "") != "none":
                continue
            reason = str(slot.get("skip_reason") or "unknown")
            summary[reason] = summary.get(reason, 0) + 1
    return summary
