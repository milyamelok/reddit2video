from __future__ import annotations

from reddit2video.scene_schema import (
    ScenePlanOutput,
    SceneTag,
    TemplateHint,
    TimedFragment,
    TimedScene,
    VisualDensity,
)


SHORT_SCENE_OK_TAGS = {
    SceneTag.COLD_HOOK,
    SceneTag.HOOK_INVERSION,
    SceneTag.PUNCH,
    SceneTag.TWIST,
    SceneTag.LABEL,
}

LONG_SCENE_OK_TAGS = {
    SceneTag.MECHANISM,
    SceneTag.METAPHOR,
    SceneTag.RULE,
    SceneTag.SAVE_ARTIFACT,
    SceneTag.DEBATE_CARD,
}

DENSE_TEMPLATE_HINTS = {
    TemplateHint.COLLAGE,
    TemplateHint.CHECKLIST,
    TemplateHint.WHEEL_OR_DIAGRAM,
    TemplateHint.DEBATE_CARD,
}

GENERIC_ASSET_PHRASES = {
    "cool visual",
    "dramatic image",
    "something dramatic",
    "interesting picture",
    "viral meme",
    "random gif",
    "generic background",
}


def compute_scene_times(scene_plan: ScenePlanOutput, timed_fragments: list[TimedFragment]) -> list[TimedScene]:
    by_id = {fragment.fragment_id: fragment for fragment in timed_fragments}
    result: list[TimedScene] = []
    for scene in scene_plan.scenes:
        first = by_id[scene.fragment_ids[0]]
        last = by_id[scene.fragment_ids[-1]]
        result.append(
            TimedScene(
                scene_id=scene.scene_id,
                start_sec=first.start_sec,
                end_sec=last.end_sec,
                duration_sec=last.end_sec - first.start_sec,
                fragment_ids=scene.fragment_ids,
            )
        )
    return result


def validate_scene_plan(
    scene_plan: ScenePlanOutput,
    timed_fragments: list[TimedFragment],
    min_scenes: int = 18,
    max_scenes: int = 25,
) -> tuple[list[str], list[str], list[TimedScene]]:
    errors: list[str] = []
    warnings: list[str] = []
    timed_scenes: list[TimedScene] = []

    expected_ids = [fragment.fragment_id for fragment in timed_fragments]
    if expected_ids != list(range(1, len(expected_ids) + 1)):
        errors.append("Timed fragments must have sequential fragment_id values starting from 1.")

    used_ids = [fragment_id for scene in scene_plan.scenes for fragment_id in scene.fragment_ids]
    if used_ids != expected_ids:
        errors.append(
            "Scene plan must use every fragment exactly once in original order. "
            f"Expected {expected_ids}, got {used_ids}."
        )

    scene_count = len(scene_plan.scenes)
    if scene_count < min_scenes or scene_count > max_scenes:
        errors.append(f"Scene count {scene_count} is outside allowed range {min_scenes}-{max_scenes}.")

    try:
        timed_scenes = compute_scene_times(scene_plan, timed_fragments)
    except KeyError as exc:
        errors.append(f"Scene references unknown fragment_id: {exc}.")
        return errors, warnings, timed_scenes

    for scene, timed in zip(scene_plan.scenes, timed_scenes):
        if timed.duration_sec < 1.2 and scene.scene_tag not in SHORT_SCENE_OK_TAGS:
            warnings.append(
                f"Scene {scene.scene_id} is very short ({timed.duration_sec:.2f}s) "
                f"but tag {scene.scene_tag.value} is not usually a short punch tag."
            )
        if timed.duration_sec > 6.0 and scene.scene_tag not in LONG_SCENE_OK_TAGS:
            errors.append(f"Scene {scene.scene_id} is too long ({timed.duration_sec:.2f}s) for tag {scene.scene_tag.value}.")
        if timed.duration_sec <= 2.0 and scene.visual_density == VisualDensity.HIGH:
            errors.append(f"Scene {scene.scene_id} is {timed.duration_sec:.2f}s but has HIGH density.")
        if timed.duration_sec <= 2.2 and len(scene.screen_rows) > 2:
            warnings.append(f"Scene {scene.scene_id} is short ({timed.duration_sec:.2f}s) but has {len(scene.screen_rows)} text rows.")

    for scene in scene_plan.scenes[:3]:
        if scene.visual_density == VisualDensity.HIGH:
            errors.append(f"Scene {scene.scene_id} is in first three scenes and should not be HIGH density.")
        if scene.template_hint in DENSE_TEMPLATE_HINTS:
            warnings.append(f"Scene {scene.scene_id} uses dense template {scene.template_hint.value} too early.")

    template_run = 1
    density_run = 1
    for index in range(1, len(scene_plan.scenes)):
        previous = scene_plan.scenes[index - 1]
        current = scene_plan.scenes[index]
        if current.template_hint == previous.template_hint:
            template_run += 1
            if template_run >= 3:
                warnings.append(
                    f"Scenes {index - 1}-{index + 1} repeat template {current.template_hint.value} three times in a row."
                )
        else:
            template_run = 1
        if current.visual_density == previous.visual_density:
            density_run += 1
            if density_run >= 4:
                warnings.append(
                    f"Scenes {index - 2}-{index + 1} repeat density {current.visual_density.value} four times in a row."
                )
        else:
            density_run = 1

    last_high_index = None
    for index, scene in enumerate(scene_plan.scenes):
        if scene.visual_density == VisualDensity.HIGH:
            if last_high_index is not None and index - last_high_index < 4:
                warnings.append(f"HIGH density scenes are close together: scene {last_high_index + 1} and scene {index + 1}.")
            last_high_index = index

    dense_text_tags = {SceneTag.SAVE_ARTIFACT, SceneTag.RULE, SceneTag.DEBATE_CARD, SceneTag.MECHANISM}
    for scene in scene_plan.scenes:
        total_words = sum(len(row.text.split()) for row in scene.screen_rows)
        if total_words > 12 and scene.scene_tag not in dense_text_tags:
            warnings.append(f"Scene {scene.scene_id} has {total_words} on-screen words; likely too much for a normal scene.")
        for slot in scene.media_slots:
            visual_prompt = slot.visual_prompt.strip().lower()
            if visual_prompt in GENERIC_ASSET_PHRASES:
                errors.append(f"Scene {scene.scene_id}, asset {slot.asset_id} has generic visual_prompt: {slot.visual_prompt!r}.")
            if not slot.search_query_ru and not slot.search_query_en and slot.source_strategy.value == "stock_search":
                warnings.append(f"Scene {scene.scene_id}, asset {slot.asset_id} uses stock_search but has no query.")

    final_tags = {scene.scene_tag for scene in scene_plan.scenes[-5:]}
    if not (
        SceneTag.SAVE_ARTIFACT in final_tags
        or SceneTag.SHARE_PROMPT in final_tags
        or SceneTag.DEBATE_CARD in final_tags
        or SceneTag.PUNCH in final_tags
    ):
        warnings.append("Last 5 scenes do not contain save/share/debate/punch energy.")

    return errors, warnings, timed_scenes
