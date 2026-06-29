from __future__ import annotations

import json
import re


BASE_STAGE1_RECIPE_HINTS = [
    "slam",
    "whisper",
    "object_hero",
    "proof_card",
    "duel",
    "sandwich",
    "material_stack",
    "beat_ladder",
    "orbit",
    "magazine_grid",
    "cascade",
    "evidence_wall",
    "text_image_text",
    "quote_evidence",
    "speaker_broll",
    "final_fork",
]


COUNTED_STAGE1_RECIPE_HINTS = [
    "slam_0_assets",
    "slam_1_asset",
    "whisper_0_assets",
    "whisper_1_asset",
    "object_hero_1_asset",
    "proof_card_1_asset",
    "duel_2_assets",
    "sandwich_2_assets",
    "material_stack_2_assets",
    "material_stack_3_assets",
    "material_stack_4_assets",
    "beat_ladder_2_assets",
    "beat_ladder_3_assets",
    "beat_ladder_4_assets",
    "orbit_3_assets",
    "orbit_4_assets",
    "orbit_5_assets",
    "orbit_6_assets",
    "magazine_grid_4_assets",
    "magazine_grid_5_assets",
    "magazine_grid_6_assets",
    "cascade_5_assets",
    "cascade_6_assets",
    "evidence_wall_5_assets",
    "evidence_wall_6_assets",
    "text_image_text_1_asset",
    "text_image_text_2_assets",
    "text_image_text_3_assets",
    "quote_evidence_1_asset",
    "quote_evidence_2_assets",
    "quote_evidence_3_assets",
    "speaker_broll_0_assets",
    "speaker_broll_1_video",
    "final_fork_0_assets",
    "final_fork_1_asset",
    "final_fork_2_assets",
]


STAGE1_RECIPE_HINTS = COUNTED_STAGE1_RECIPE_HINTS


STAGE1_RECIPE_COOKBOOK_MARKER = "PIPELINE V4 SHARED STAGE1 RECIPE COOKBOOK"
DESIGN_RECIPE_COOKBOOK_MARKER = "PIPELINE V4 SHARED DESIGN TEMPLATE COOKBOOK"
CANONICAL_RECIPE_LOCK_COOKBOOK_MARKER = "PIPELINE V4.4 CANONICAL RECIPE LOCK COOKBOOK"


DESIGN_TEMPLATE_BY_CANONICAL_RECIPE: dict[str, str] = {
    "slam": "poster_slam",
    "whisper": "hero_type",
    "object_hero": "single_image_editorial",
    "proof_card": "single_image_editorial",
    "duel": "split_duel",
    "sandwich": "text_image_text",
    "material_stack": "collage_orbit",
    "beat_ladder": "horizontal_triptych",
    "orbit": "collage_orbit",
    "magazine_grid": "sticker_grid",
    "cascade": "sticker_grid",
    "evidence_wall": "sticker_grid",
    "text_image_text": "text_image_text",
    "quote_evidence": "single_image_editorial",
    "speaker_broll": "avatar_broll",
    "final_fork": "final_question",
}


V4_LAYOUT_BEHAVIOR_BY_CANONICAL_RECIPE: dict[str, str] = {
    "slam": "text_only_punch",
    "whisper": "quiet_negative_space",
    "object_hero": "single_object_hero",
    "proof_card": "single_proof_exhibit",
    "duel": "two_side_duel",
    "sandwich": "text_image_text_sandwich",
    "material_stack": "visible_material_stack",
    "beat_ladder": "ordered_ladder",
    "orbit": "central_orbit",
    "magazine_grid": "editorial_catalog_grid",
    "cascade": "diagonal_overload",
    "evidence_wall": "dense_evidence_wall",
    "text_image_text": "text_image_text_sandwich",
    "quote_evidence": "quote_plus_evidence",
    "speaker_broll": "exclusive_avatar_broll",
    "final_fork": "final_choice_fork",
}


def recipe_hint_base(layout_recipe_hint: str) -> str:
    hint = layout_recipe_hint.strip().lower().replace("-", "_")
    match = re.fullmatch(r"(.+)_([0-6])_(?:assets?|videos?)", hint)
    return match.group(1) if match else hint


def recipe_hint_asset_count(layout_recipe_hint: str) -> int | None:
    hint = layout_recipe_hint.strip().lower().replace("-", "_")
    match = re.fullmatch(r"(.+)_([0-6])_assets?", hint)
    return int(match.group(2)) if match else None


def design_template_for_canonical_recipe(layout_recipe_hint: str) -> str | None:
    return DESIGN_TEMPLATE_BY_CANONICAL_RECIPE.get(recipe_hint_base(layout_recipe_hint))


def v4_layout_behavior_for_canonical_recipe(layout_recipe_hint: str) -> str | None:
    return V4_LAYOUT_BEHAVIOR_BY_CANONICAL_RECIPE.get(recipe_hint_base(layout_recipe_hint))


def append_stage1_recipe_cookbook(prompt: str) -> str:
    if STAGE1_RECIPE_COOKBOOK_MARKER in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{build_stage1_recipe_cookbook()}\n"


def build_stage1_recipe_cookbook() -> str:
    return f"""# {STAGE1_RECIPE_COOKBOOK_MARKER}

This cookbook is part of the cached Stage 1 prompt. It tells you what each
`layout_recipe_hint` means. You are not writing layout code here. You are
choosing the visual job of each scene so the later Remotion renderer can pick a
controlled template.

Core principle:

```text
scene meaning -> recipe hint -> asset count -> later deterministic Remotion layout
```

Do not choose a recipe by aesthetic randomness. Choose it by the use case below.
Do not invent a separate screen headline. `voiceover_line` remains the only text
source.

Allowed `layout_recipe_hint` values are count-specific. Use these exact values:

```json
{STAGE1_RECIPE_HINTS}
```

Legacy base names such as `material_stack` or `cascade` may appear in older
files, but do not output them in new Stage 1 generations. Always output the
count-specific form, for example:

```text
duel_2_assets
material_stack_3_assets
orbit_4_assets
cascade_5_assets
evidence_wall_6_assets
speaker_broll_0_assets
```

Forbidden:

```text
right_rail
generic_card_row
random_collage
speaker_collage_hybrid
```

Decision logic:

1. If this is a human trust / nuance / explanation beat, duration is at least
   2 seconds, and the scene type is AVATAR, choose `speaker_broll_0_assets`.
2. If this is the last scene and it asks viewers to choose a side, prefer
   `final_fork_0_assets` or `final_fork_1_asset` in strict girly-v5. Use
   `final_fork_2_assets` only when the active scene registry/template explicitly
   supports a 2-asset final fork.
3. If there are 0 foreground assets:
   - use `slam_0_assets` for a hard punch, chapter card, outrage, or dramatic stop;
   - use `whisper_0_assets` for an intimate aside, doubt, quiet reflection, or soft
     confessional line.
4. If there is 1 foreground asset:
   - use `object_hero_1_asset` when the asset is a clear symbol or meme/object hero;
   - use `proof_card_1_asset` when the asset is evidence, receipt, report, screen,
     label, chart, or concrete proof;
   - use `quote_evidence_1_asset` when the spoken line feels like a quote/confession
     and the asset is a side note.
5. If there are 2 foreground assets:
   - use `duel_2_assets` when there is real opposition: X vs Y, myth vs fact, shame vs
     body, fear vs ability, two camps, moral fork;
   - use `sandwich_2_assets` when the line needs setup -> visual pause -> aftertaste;
   - use `text_image_text_2_assets` when top text, image, and bottom text should feel
     like expressive reading.
6. If there are 3 foreground assets:
   - use `beat_ladder_3_assets` when there is order: cause -> proof -> punchline,
     setup -> clue -> conclusion, first -> then -> therefore;
   - use `material_stack_3_assets` when all assets should stay visible as physical cards
     in one pile;
   - use `text_image_text_3_assets` when one or two images are central and the text
     splits around them.
7. If there are 4 foreground assets:
   - use `orbit_4_assets` when a central phrase/object has surrounding emotional noise;
   - use `magazine_grid_4_assets` when the assets are same-family items to compare or
     catalog;
   - use `material_stack_4_assets` when physical overlap matters more than grid logic.
8. If there are 5 foreground assets:
   - use `cascade_5_assets` for overload, pile-up, avalanche, too many signals;
   - use `magazine_grid_5_assets` for a controlled catalog.
9. If there are 6 foreground assets:
   - use `evidence_wall_6_assets` for receipts/proof-board/high-density examples;
   - use `cascade_6_assets` for visual overwhelm.

Recipe use cases:

- `slam`: short brutal text-only or nearly text-only line. Use for "ГОРМОНЫ НЕ
  МАГИЯ.", "ТЕЛО НЕ ДЕКОР.", "ЭТО БРЕД." No foreground assets unless one tiny
  symbol is essential.
- `whisper`: quiet reflective line. Serif/italic energy later. Negative space is
  allowed. No filler assets.
- `object_hero`: one instantly readable object carries the scene. Good for
  pink dumbbell, scale, protein cookie, lab report, barbell, calendar.
- `proof_card`: one asset is an exhibit. Good for chart, screenshot, label,
  scale display, medical paper, progress graph, receipt.
- `duel`: two ideas fight. Good for "хрупкость vs сила", "миф vs факт",
  "дефицит vs жизнь", "соберись vs тело сложнее".
- `sandwich`: text/image/text rhythm with a mid-scene turn. Good for "сначала
  смешно, потом неприятно".
- `material_stack`: 2-4 cards remain visible together. This is a collage, not a
  carousel. Use when examples should feel like physical evidence on a table.
- `beat_ladder`: ordered sequence of 2-4 beats. Use when the viewer should read
  the scene as a process or escalation.
- `orbit`: central phrase wins; small assets orbit as pressure/noise/context.
- `magazine_grid`: controlled editorial catalog. Assets align to a system.
- `cascade`: diagonal pile-up/overload. Some occlusion is okay.
- `evidence_wall`: dense proof board. Viewer gets "there is a lot here"; each
  item does not need to be inspected deeply.
- `text_image_text`: the spoken phrase should feel like reading with expression:
  text above, image pause, text below.
- `quote_evidence`: human quote / inner voice / accusation plus evidence asset.
- `speaker_broll`: background video + bottom-right avatar + word-synced Russian
  caption. No foreground collage assets.
- `final_fork`: last question with a real choice. Do not add summary after it.

Asset count contract:

```text
TEXT_ONLY -> usually 0 assets
AVATAR -> 0 foreground assets, background becomes Pinterest/stock video query
COLLAGE -> 1-6 assets by recipe, never by quota
AI_IMAGE -> avoid in v4 unless explicitly necessary
```

Hard recipe/count compatibility:

```text
slam, whisper -> 0-1 assets
object_hero, proof_card -> exactly 1 asset
duel -> exactly 2 assets
sandwich -> exactly 2 assets
material_stack -> 2-4 assets
beat_ladder -> 2-4 ordered assets
orbit -> 3-6 assets
magazine_grid -> 4-6 same-family assets
cascade -> 5-6 overload assets
evidence_wall -> 5-6 proof/receipt assets
text_image_text -> 1-3 assets
quote_evidence -> 1-3 assets
speaker_broll -> 0 foreground assets
final_fork -> 0-2 assets
```

If the asset count does not fit the recipe suffix, change the recipe. Do not
keep a recipe name that contradicts `target_visual_asset_count`.

Duration density planning guide:

```text
Most scenes: 2.2-2.8 words/sec.
Prefer not to exceed 3.2 words/sec for lines with 8+ words.
Avoid exceeding 3.6 words/sec.
```

If a line would exceed the guardrail, either increase `duration_sec` or split the
line into another scene. This is a planning guide for Stage 1, not a hard render
blocker before real TTS/alignment exists.

Search query rule for Google Images:

```text
Do not ask for transparent background, png, icon, screenshot, app screen, or
interface. Ask for a real findable image/object/photo/illustration primitive.
```

Good:

```text
pink dumbbell close up photo
dog food bag photo
female bicep illustration
barbell plates photo
```

Bad:

```text
pink dumbbell transparent background
female bicep icon transparent
app screenshot
```

Good examples:

```json
{{"layout_recipe_hint": "object_hero_1_asset", "target_visual_asset_count": 1,
 "asset_count_reason": "Одна розовая гантелька сама является символом страха веса."}}
{{"layout_recipe_hint": "duel_2_assets", "target_visual_asset_count": 2,
 "asset_count_reason": "Сцена противопоставляет домашнюю силу и страх штанги."}}
{{"layout_recipe_hint": "material_stack_3_assets", "target_visual_asset_count": 3,
 "asset_count_reason": "Три примера должны лежать вместе как физическая стопка карточек."}}
{{"layout_recipe_hint": "speaker_broll_0_assets", "target_visual_asset_count": 0,
 "asset_count_reason": "Это объясняющий trust beat; foreground collage would compete with speaker."}}
```
"""


def build_design_template_cookbook() -> str:
    return f"""# {DESIGN_RECIPE_COOKBOOK_MARKER}

This cookbook is part of the cached DesignPlan primer. You choose controlled
Remotion templates and parameters. You do not write HTML, CSS, React, or new
scene text. The renderer owns the layout implementation.

You receive Stage 1 semantic hints such as `material_stack_3_assets`,
`duel_2_assets`, or `speaker_broll_0_assets`. The suffix is part of the
contract: it must agree with actual foreground asset count.

Stage 1 recipe fidelity is a hard contract. Do not reinterpret a scene into a
neighboring recipe because it feels prettier. The DesignPlan may only choose the
production `template_recipe` explicitly allowed by the mapping below, and then
adjust scale, spacing, line breaks, hierarchy, treatment, and motion within that
locked semantic recipe.

Production `template_recipe` values:

```json
[
  "poster_slam",
  "poster_question",
  "collage_orbit",
  "sticker_grid",
  "split_duel",
  "vertical_split",
  "horizontal_triptych",
  "text_image_text",
  "single_image_editorial",
  "hero_type",
  "fake_ui_card",
  "avatar_broll",
  "final_question"
]
```

Stage 1 base hint -> preferred production template:

```text
slam -> poster_slam
whisper -> hero_type
object_hero -> single_image_editorial
proof_card -> single_image_editorial
duel -> split_duel
sandwich -> text_image_text
material_stack -> collage_orbit, with visible material-stack card behavior
beat_ladder -> horizontal_triptych
orbit -> collage_orbit
magazine_grid -> sticker_grid
cascade -> sticker_grid, with cascade/overwhelm behavior
evidence_wall -> sticker_grid
text_image_text -> text_image_text
quote_evidence -> single_image_editorial
speaker_broll -> avatar_broll only
final_fork -> final_question only
```

If a Stage 1 hint is present, this mapping is locked. Examples:

- `duel_2_assets` must become `split_duel`, not `single_image_editorial`.
- `material_stack_3_assets` must become `collage_orbit` and behave as a visible
  card stack, not as an orbit, grid, carousel, or single image.
- `speaker_broll_0_assets` must become `avatar_broll`, unless it violates the
  hard speaker duration rule; if it violates duration, explain the demotion in
  notes instead of pretending it was a different recipe.
- `final_fork_2_assets`, when explicitly selected by a compatible final
  template, must become `final_question`, not `split_duel`.

Use cases for production templates:

- `poster_slam`: hard typographic punch. 0 assets. Dark or high-contrast card.
- `poster_question`: question or chapter-card, usually 0 assets.
- `hero_type`: expressive text-first scene. Use huge hierarchy for 1-3 words,
  italic/serif for quiet words, and negative space intentionally.
- `single_image_editorial`: exactly 1 strong asset. The asset should be large
  enough to matter; text should wrap around it or anchor against it.
- `split_duel`: 2 assets or two ideas in conflict. Use when comparison is the
  scene's point.
- `vertical_split`: stronger left/right duel. Use for moral fork or two camps.
- `horizontal_triptych`: ordered beats/process/escalation. Previous beats remain
  visible.
- `text_image_text`: phrase above/below one or two media cards. Use for reading
  with expression and visual pause.
- `collage_orbit`: central text/object plus surrounding material cards. Good for
  orbit and material-stack semantics when all cards stay visible.
- `sticker_grid`: controlled 3-6 item grid/evidence wall/catalog. Avoid if the
  scene should feel intimate.
- `fake_ui_card`: rare. Do not use for 2+ normal assets. Use only when the scene
  is literally fake UI/app/screen logic.
- `avatar_broll`: exclusive speaker mode: video background, bottom-right avatar,
  word-synced caption. No foreground collage assets.
- `final_question`: last scene only, slow reveal and pause.

Hard constraints:

- Never choose `right_rail`; it is not a production template.
- Never write or request freeform layout code.
- Never invent new foreground media.
- Never change the semantic recipe from Stage 1. Only use the production mapping
  above and adjust parameters inside that locked recipe.
- Never choose `avatar_broll` under 2 seconds.
- Never choose `avatar_broll` for a scene with necessary foreground visual
  assets.
- Never choose `avatar_broll` for final question.
- If Stage 1 asks for `material_stack`, all cards must remain visible together.
  Do not create carousel/replacement motion.
- If a scene has one asset, do not pad it with imaginary filler assets. Make the
  typography stronger instead.
- Avoid cheap translucent black subtitle boxes. Use typography, shadow, and
  background depth.

Visual language:

```text
sport editorial wellness collage
Ralph Lauren tennis pink / green softness
cream text, deep green/black ink, pink shadow
tall bold condensed display
serif/italic editorial accent
physical paper/card materiality
```

The output should feel like the scene is being read with expression, not like a
generic subtitle renderer.
"""


def build_canonical_recipe_lock_cookbook() -> str:
    recipe_to_template_lines = "\n".join(
        f"{recipe} -> {template}" for recipe, template in DESIGN_TEMPLATE_BY_CANONICAL_RECIPE.items()
    )
    recipe_to_behavior_lines = "\n".join(
        f"{recipe} -> {behavior}" for recipe, behavior in V4_LAYOUT_BEHAVIOR_BY_CANONICAL_RECIPE.items()
    )
    return f"""# {CANONICAL_RECIPE_LOCK_COOKBOOK_MARKER}

This cookbook is part of the Pipeline v4.4 DesignPlan primer. Its job is to
keep Stage 1's `layout_recipe_hint` as the canonical recipe for every scene.
`template_recipe` is only the renderer family selected from the locked mapping;
it is not a broader creative license.

Allowed counted canonical `layout_recipe_hint` values:

```json
{json.dumps(STAGE1_RECIPE_HINTS, ensure_ascii=False, indent=2)}
```

Canonical recipe base -> locked production template:

```text
{recipe_to_template_lines}
```

Canonical recipe base -> v4.4 recipe behavior token:

```text
{recipe_to_behavior_lines}
```

Per-scene recipe lock rule:

- Copy the scene's `layout_recipe_hint` exactly into
  `recipe_lock.locked_recipe_hint`.
- Set `recipe_lock.canonical_recipe` to the base recipe from that hint, for
  example `material_stack_3_assets` -> `material_stack`.
- Copy `target_visual_asset_count` into
  `recipe_lock.target_visual_asset_count`.
- Count only foreground visual media in
  `recipe_lock.resolved_foreground_asset_count`; avatar background video is not
  a foreground asset.
- Set top-level `template_recipe` to the locked production template above.
- Set `layout_controls.recipe_behavior` to the locked behavior token above.
- If there is a collision or poor crop, change only bounded offsets, scale,
  rotation, line breaks, safe-area padding, z-order, or crop focus. Do not
  change the canonical recipe.

Do not broaden a recipe into a neighboring layout:

```text
duel_2_assets -> split_duel, not single_image_editorial
material_stack_3_assets -> collage_orbit + visible_material_stack, not orbit/grid/carousel
beat_ladder_3_assets -> horizontal_triptych + ordered_ladder, not sticker_grid
quote_evidence_2_assets -> single_image_editorial + quote_plus_evidence, not split_duel
speaker_broll_0_assets -> avatar_broll + exclusive_avatar_broll, unless duration demotion is required
final_fork_2_assets -> final_question + final_choice_fork, only when a compatible final template exists
```

Pipeline v4.4 DesignPlan output is structured JSON with bounded numeric knobs.
Never output HTML, CSS, React, Tailwind, class names, inline style objects, pixel
coordinates, or new scene text.
"""
