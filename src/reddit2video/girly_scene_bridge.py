from __future__ import annotations

from copy import deepcopy
from typing import Any

from reddit2video.girly_scene_cookbook import GIRLY_SCENE_REGISTRY, get_girly_scene

Json = dict[str, Any]


def normalize_scene_id(scene_id: str | None) -> str | None:
    if not scene_id:
        return None
    token = str(scene_id).strip()
    if token.lower().startswith("scene") and len(token) == 8:
        return "Scene" + token[-3:]
    if token.isdigit():
        return f"Scene{int(token):03d}"
    return token


def get_visual_asset_count(scene: Json) -> int:
    assets = scene.get("visual_assets") or []
    return len(assets) if isinstance(assets, list) else 0


def validate_girly_scene_selection(scene: Json) -> list[str]:
    """Return human-readable warnings/errors for one storyboard scene."""
    warnings: list[str] = []
    girly = scene.get("girly_scene") or {}
    scene_id = normalize_scene_id(girly.get("scene_id"))
    if not scene_id:
        return ["missing girly_scene.scene_id"]

    registry = get_girly_scene(scene_id)
    if registry is None:
        return [f"unknown girly_scene.scene_id: {scene_id}"]

    group = girly.get("scene_group")
    if group and group != registry.get("group"):
        warnings.append(f"scene_group mismatch: got {group}, registry says {registry.get('group')}")

    count = get_visual_asset_count(scene)
    min_assets, max_assets = registry.get("asset_range", [0, 999])
    if count < min_assets:
        warnings.append(f"asset count too low for {scene_id}: got {count}, expected >= {min_assets}")
    if count > max_assets:
        warnings.append(f"asset count too high for {scene_id}: got {count}, expected <= {max_assets}")

    recipe = scene.get("layout_recipe_hint")
    compatible = set(registry.get("compatible_recipe_hints", []))
    if recipe and compatible and recipe not in compatible:
        warnings.append(f"recipe {recipe} is not ideal for {scene_id}; compatible: {sorted(compatible)}")

    slot_plan = girly.get("slot_plan") or []
    planned_slots = {slot.get("slot") for slot in slot_plan if isinstance(slot, dict)}
    registry_slots = {
        slot.get("slot")
        for slot in list(registry.get("media_slots", [])) + list(registry.get("text_slots", []))
        if isinstance(slot, dict)
    }
    unknown_slots = sorted(slot for slot in planned_slots if slot and slot not in registry_slots)
    if unknown_slots:
        warnings.append(f"unknown slots for {scene_id}: {unknown_slots}")

    for slot in slot_plan:
        if not isinstance(slot, dict):
            continue
        if slot.get("slot_type") == "media":
            index = slot.get("visual_asset_index")
            if index is not None and (not isinstance(index, int) or index < 0 or index >= count):
                warnings.append(f"slot {slot.get('slot')} references visual_asset_index={index}, but asset count is {count}")
        if slot.get("slot_type") == "text" and slot.get("text_source") == "spoken_fragment":
            text = (slot.get("text") or "").strip()
            voiceover = (scene.get("voiceover_line") or "").strip()
            if text and text not in voiceover:
                warnings.append(f"text slot {slot.get('slot')} is not an exact spoken_fragment: {text!r}")

    return warnings


def fallback_girly_scene_id(scene: Json) -> str:
    """Best-effort deterministic fallback when Gemini omitted or overfit girly_scene."""
    line = (scene.get("voiceover_line") or "").lower()
    recipe = (scene.get("layout_recipe_hint") or "").lower()
    count = get_visual_asset_count(scene)
    retention = (scene.get("retention_function") or "").lower()
    visual = (scene.get("visual_direction") or "").lower()
    text = " ".join([line, recipe, retention, visual])

    if any(w in text for w in ["тренд", "образ", "инфлюенсер", "очки", "пальто", "style", "fashion", "look"]):
        if any(w in text for w in ["облож", "3 трен", "три трен"]):
            return "Scene013"
        if count <= 1:
            return "Scene015"
        if count >= 5:
            return "Scene017"
        if any(w in text for w in ["пальто", "сумк", "предмет", "вещь"]):
            return "Scene018"
        return "Scene014"

    if any(w in text for w in ["дней", "трениров", "коврик", "привыч", "мозг", "нейро", "импульс", "дождь", "зачем мне"]):
        if any(w in text for w in ["нейро", "мозг", "дофамин", "психолог"]):
            return "Scene026"
        if any(w in text for w in ["зачем", "смысл", "нужно?", "почему я"]):
            return "Scene023"
        if any(w in text for w in ["расстил", "коврик", "надел", "пошла"]):
            return "Scene024"
        if any(w in text for w in ["дожд", "утром", "вечером"]):
            return "Scene022"
        if any(w in text for w in ["дней", "не пропуст", "streak", "серия"]):
            return "Scene020"
        if count == 0:
            return "Scene025"
        return "Scene021"

    if any(w in text for w in ["наук", "математ", "логик", "исслед", "факт", "объясним"]):
        if "математ" in text or "циф" in text:
            return "Scene012"
        return "Scene011"

    if any(w in text for w in ["контракт", "евро", "бренд", "деньг", "письм", "receipt", "доход"]):
        return "Scene008"
    if any(w in text for w in ["подпис", "профил", "аккаунт", "блог", "аудитор"]):
        if any(w in text for w in ["нач", "перв", "вести блог"]):
            return "Scene001"
        if any(w in text for w in ["профил", "подпис", "аккаунт", "followers"]):
            return "Scene003"
        return "Scene005" if count <= 2 else "Scene004"

    if any(w in text for w in ["скуч", "не нравится", "будни", "стиль", "до ", "before"]):
        return "Scene027"

    if count == 0:
        return "Scene025"
    if count == 1:
        return "Scene009"
    if count >= 4:
        return "Scene004"
    return "Scene027"


def materialize_girly_scene_unit(scene: Json) -> Json:
    """Convert one Stage 1 scene to a renderer-friendly unit.

    This function does not touch HTML. It produces a stable payload that a later
    node can use to clone `[data-scene-root="SceneXXX"]` from index.html and fill
    media/text slots.
    """
    result = deepcopy(scene)
    girly = result.get("girly_scene") or {}
    scene_id = normalize_scene_id(girly.get("scene_id")) or fallback_girly_scene_id(result)
    registry = get_girly_scene(scene_id)
    warnings = validate_girly_scene_selection(result) if result.get("girly_scene") else ["girly_scene missing; used deterministic fallback"]
    if registry is None:
        fallback_id = normalize_scene_id(girly.get("fallback_scene_id"))
        if fallback_id and get_girly_scene(fallback_id) is not None:
            scene_id = fallback_id
        else:
            scene_id = fallback_girly_scene_id(result)
        registry = get_girly_scene(scene_id)
        warnings.append(f"girly_scene broken; used fallback {scene_id}")

    result["girly_scene_unit"] = {
        "scene_id": scene_id,
        "root_selector": registry.get("root_selector") if registry else None,
        "scene_class": registry.get("scene_class") if registry else None,
        "group": registry.get("group") if registry else None,
        "function": registry.get("function") if registry else None,
        "voiceover_line": result.get("voiceover_line"),
        "duration_sec": result.get("duration_sec"),
        "layout_recipe_hint": result.get("layout_recipe_hint"),
        "slot_plan": girly.get("slot_plan", []),
        "registry_media_slots": registry.get("media_slots", []) if registry else [],
        "registry_text_slots": registry.get("text_slots", []) if registry else [],
        "visual_assets": result.get("visual_assets", []),
        "warnings": warnings,
    }
    return result


def materialize_girly_storyboard(storyboard_payload: Json) -> Json:
    payload = deepcopy(storyboard_payload)
    storyboard = payload.get("storyboard_v2") if isinstance(payload.get("storyboard_v2"), dict) else payload
    scenes = storyboard.get("scenes") or []
    storyboard["scenes"] = [materialize_girly_scene_unit(scene) for scene in scenes]
    payload["storyboard_v2"] = storyboard
    return payload
