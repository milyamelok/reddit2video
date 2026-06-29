from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


TEMPLATE_FAMILY_VERSION = "story_format_families_v1"
DEFAULT_REEL_TEMPLATE_FAMILY = "default_girly_b_layout"
STORY_FORMAT_COOKBOOK_MARKER = "STORY_FORMAT_COOKBOOK_V1"

STORY_FORMAT_IDS = [
    "unpleasant_simplicity",
    "wrong_target",
    "why_she_can_you_cant",
    "myth_vs_mechanics",
    "price_of_the_picture",
    "everyday_math",
    "reddit_confession",
    "boring_thing_that_works",
    "two_roads",
    "forbidden_answer",
    "trend_sober_take",
    "pretty_word_decode",
]


def _fmt(
    *,
    label: str,
    hook_grammar: str,
    six_beat_skeleton: list[str],
    opening_scene_pool: list[str],
    middle_scene_pool: list[str],
    proof_scene_pool: list[str],
    final_scene_pool: list[str],
    layout_recipe_hints: list[str],
    asset_count_profile: str,
    text_density: str,
    vfx_rhythm: str,
    final_beat: str,
    forbidden_moves: list[str],
) -> dict[str, Any]:
    return {
        "label": label,
        "template_family": f"girly_{label}",
        "hook_grammar": hook_grammar,
        "six_beat_skeleton": six_beat_skeleton,
        "opening_scene_pool": opening_scene_pool,
        "middle_scene_pool": middle_scene_pool,
        "proof_scene_pool": proof_scene_pool,
        "final_scene_pool": final_scene_pool,
        "preferred_layout_recipe_hints": layout_recipe_hints,
        "asset_count_profile": asset_count_profile,
        "text_density": text_density,
        "vfx_rhythm": vfx_rhythm,
        "final_beat": final_beat,
        "forbidden_moves": forbidden_moves,
    }


STORY_FORMATS: dict[str, dict[str, Any]] = {
    "unpleasant_simplicity": _fmt(
        label="unpleasant_simplicity",
        hook_grammar="Name the simple rule nobody wants to accept.",
        six_beat_skeleton=[
            "unpleasant claim",
            "why people dodge it",
            "one concrete object or number",
            "brutal everyday example",
            "saveable rule",
            "final price or choice",
        ],
        opening_scene_pool=["Scene006", "Scene010", "Scene012", "Scene025"],
        middle_scene_pool=["Scene009", "Scene011", "Scene021", "Scene024"],
        proof_scene_pool=["Scene011", "Scene020", "Scene026"],
        final_scene_pool=["Scene023", "Scene025"],
        layout_recipe_hints=[
            "slam_0_assets",
            "whisper_0_assets",
            "object_hero_1_asset",
            "proof_card_1_asset",
            "quote_evidence_1_asset",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="0-2 foreground assets most scenes; one concrete object/proof/action beats filler.",
        text_density="Low to medium. Normal scenes <=12 on-screen words; split complex claims.",
        vfx_rhythm="Hard typographic stop, quiet explanation, single proof land, final pause.",
        final_beat="Ask whether the viewer accepts the boring price of the simple rule.",
        forbidden_moves=["Do not turn the rule into motivation.", "Do not add a summary after the final fork."],
    ),
    "wrong_target": _fmt(
        label="wrong_target",
        hook_grammar="Start with the thing she blames, then reveal the hidden mechanism.",
        six_beat_skeleton=[
            "visible target",
            "why it feels obvious",
            "hidden target",
            "mechanism proof",
            "new way to look",
            "re-aimed final question",
        ],
        opening_scene_pool=["Scene010", "Scene012", "Scene023", "Scene027"],
        middle_scene_pool=["Scene009", "Scene011", "Scene021", "Scene024"],
        proof_scene_pool=["Scene008", "Scene011", "Scene020", "Scene026"],
        final_scene_pool=["Scene023", "Scene025"],
        layout_recipe_hints=[
            "duel_2_assets",
            "text_image_text_2_assets",
            "sandwich_2_assets",
            "quote_evidence_1_asset",
            "proof_card_1_asset",
            "material_stack_2_assets",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="Usually two-sided assets: blamed target versus actual mechanism, plus one proof card when earned.",
        text_density="Medium contrast labels. One false target and one real target per scene.",
        vfx_rhythm="False target appears first; real target reveals on the correction word.",
        final_beat="Final beat must re-aim attention, not introduce a new explanation.",
        forbidden_moves=["Do not keep arguing the visible target after the reveal.", "Avoid generic moralizing."],
    ),
    "why_she_can_you_cant": _fmt(
        label="why_she_can_you_cant",
        hook_grammar="Open on envy, then reveal the unseen condition that makes it work.",
        six_beat_skeleton=[
            "envy setup",
            "what she seems to get away with",
            "unseen day or condition",
            "portion/math/mechanism",
            "why comparison lies",
            "choice without shame",
        ],
        opening_scene_pool=["Scene006", "Scene010", "Scene023", "Scene027"],
        middle_scene_pool=["Scene007", "Scene011", "Scene021", "Scene022", "Scene024"],
        proof_scene_pool=["Scene003", "Scene008", "Scene020", "Scene026"],
        final_scene_pool=["Scene023", "Scene025"],
        layout_recipe_hints=[
            "duel_2_assets",
            "beat_ladder_3_assets",
            "beat_ladder_4_assets",
            "material_stack_4_assets",
            "proof_card_1_asset",
            "quote_evidence_1_asset",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="Comparison pair plus hidden habit/portion/proof asset. Avoid generic aspirational filler.",
        text_density="Opening low/medium; proof scenes can be denser only after the setup.",
        vfx_rhythm="She/you contrast, hidden condition reveal, ordered proof, calmer reframe.",
        final_beat="End on compare-versus-build-conditions, never on shame.",
        forbidden_moves=["Do not insult the viewer.", "Do not imply the other woman is fake without evidence."],
    ),
    "myth_vs_mechanics": _fmt(
        label="myth_vs_mechanics",
        hook_grammar="A clean myth card collides with the mechanism card underneath.",
        six_beat_skeleton=[
            "myth card",
            "why myth is tempting",
            "mechanism card",
            "proof/example",
            "sober punch",
            "mechanism-based final question",
        ],
        opening_scene_pool=["Scene010", "Scene011", "Scene012"],
        middle_scene_pool=["Scene011", "Scene012", "Scene021", "Scene022", "Scene024"],
        proof_scene_pool=["Scene011", "Scene012", "Scene020", "Scene026"],
        final_scene_pool=["Scene012", "Scene023", "Scene025"],
        layout_recipe_hints=[
            "duel_2_assets",
            "slam_0_assets",
            "speaker_broll_0_assets",
            "quote_evidence_1_asset",
            "quote_evidence_2_assets",
            "proof_card_1_asset",
            "object_hero_1_asset",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="Main video plus science/proof/object card. 0-3 foreground assets normally.",
        text_density="Medium; myth/fact phrases short, mechanism split across scenes.",
        vfx_rhythm="Myth pops hard, mechanism assembles by cue words, proof lands early enough to read.",
        final_beat="End on mechanism reframe or real choice; no new evidence in the final beat.",
        forbidden_moves=["Do not overclaim health/science.", "Do not make the myth straw-man vague."],
    ),
    "price_of_the_picture": _fmt(
        label="price_of_the_picture",
        hook_grammar="Show the desired picture, then name the hidden cost.",
        six_beat_skeleton=[
            "desired aesthetic",
            "why it looks easy",
            "hidden cost",
            "tradeoff example",
            "who pays the price",
            "is the picture worth it",
        ],
        opening_scene_pool=["Scene001", "Scene002", "Scene004", "Scene027"],
        middle_scene_pool=["Scene012", "Scene014", "Scene016", "Scene018", "Scene021"],
        proof_scene_pool=["Scene008", "Scene011", "Scene019", "Scene020", "Scene026"],
        final_scene_pool=["Scene009", "Scene023", "Scene025"],
        layout_recipe_hints=[
            "orbit_5_assets",
            "orbit_6_assets",
            "magazine_grid_4_assets",
            "magazine_grid_5_assets",
            "material_stack_4_assets",
            "proof_card_1_asset",
            "evidence_wall_5_assets",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="3-6 assets for the picture, then 1-5 assets for the hidden price/proof.",
        text_density="Low to medium; let images carry status, use short price labels.",
        vfx_rhythm="Picture assembles first; cost/receipt elements reveal on number or cost words.",
        final_beat="Ask whether the image is worth the hidden price.",
        forbidden_moves=["Do not become shopping advice.", "Do not invent costs or receipts."],
    ),
    "everyday_math": _fmt(
        label="everyday_math",
        hook_grammar="Turn a messy habit into one readable household calculation.",
        six_beat_skeleton=[
            "small object/math hook",
            "what people miscount",
            "operands in order",
            "result",
            "rule of thumb",
            "saveable final choice",
        ],
        opening_scene_pool=["Scene010", "Scene012", "Scene020"],
        middle_scene_pool=["Scene011", "Scene012", "Scene020", "Scene021", "Scene022", "Scene024"],
        proof_scene_pool=["Scene008", "Scene011", "Scene020", "Scene026"],
        final_scene_pool=["Scene012", "Scene023", "Scene025"],
        layout_recipe_hints=[
            "slam_0_assets",
            "object_hero_1_asset",
            "proof_card_1_asset",
            "beat_ladder_3_assets",
            "beat_ladder_4_assets",
            "text_image_text_1_asset",
            "text_image_text_2_assets",
            "final_fork_0_assets",
        ],
        asset_count_profile="One readable object/card per calculation beat; avoid filler collage.",
        text_density="Number-forward; one equation/rule per scene, max 8-12 visible words.",
        vfx_rhythm="Reveal operands in order, then result; ordered ladders stay visible.",
        final_beat="End on a saveable rule-of-thumb or real choice.",
        forbidden_moves=["Do not do dense math after the final takeaway.", "Do not invent exact calories/statistics."],
    ),
    "reddit_confession": _fmt(
        label="reddit_confession",
        hook_grammar="A personal admission opens the door, but the source is never named in voiceover.",
        six_beat_skeleton=[
            "confession",
            "why it sounds embarrassing",
            "the pattern inside it",
            "comments/mechanism without saying Reddit",
            "viewer mirror",
            "vulnerable final fork",
        ],
        opening_scene_pool=["Scene005", "Scene006", "Scene009", "Scene027"],
        middle_scene_pool=["Scene005", "Scene009", "Scene010", "Scene011", "Scene023", "Scene025"],
        proof_scene_pool=["Scene003", "Scene008", "Scene011", "Scene020", "Scene026"],
        final_scene_pool=["Scene023", "Scene025"],
        layout_recipe_hints=[
            "speaker_broll_0_assets",
            "whisper_0_assets",
            "quote_evidence_1_asset",
            "text_image_text_1_asset",
            "text_image_text_2_assets",
            "duel_2_assets",
            "proof_card_1_asset",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="Low-medium density: main video, pain/reaction photo, creator/proof/science card only when earned.",
        text_density="Intimate. 4-10 spoken words per scene; split confession paragraphs.",
        vfx_rhythm="Slow confession b-roll, word-synced quote reveal, proof stamp only when receipts appear.",
        final_beat="End on a vulnerable moral fork, not a generic 'what do you think'.",
        forbidden_moves=["Do not mention Reddit/thread unless explicitly asked.", "Avoid two TEXT_ONLY confession scenes in a row."],
    ),
    "boring_thing_that_works": _fmt(
        label="boring_thing_that_works",
        hook_grammar="Contrast trend overload with the boring lever that actually works.",
        six_beat_skeleton=[
            "trend overload",
            "boring lever",
            "why people skip it",
            "why it works",
            "saveable rule",
            "boring baseline versus shiny hack",
        ],
        opening_scene_pool=["Scene012", "Scene020", "Scene022", "Scene024", "Scene025"],
        middle_scene_pool=["Scene011", "Scene012", "Scene021", "Scene022", "Scene024", "Scene026"],
        proof_scene_pool=["Scene011", "Scene012", "Scene020", "Scene021", "Scene026"],
        final_scene_pool=["Scene023", "Scene025"],
        layout_recipe_hints=[
            "object_hero_1_asset",
            "text_image_text_1_asset",
            "text_image_text_2_assets",
            "material_stack_2_assets",
            "material_stack_4_assets",
            "beat_ladder_3_assets",
            "proof_card_1_asset",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="Concrete routine assets: action video, diary/card metric, science image where earned.",
        text_density="Short practical claims. Action scenes 3-6 words; proof scenes 8-10 words.",
        vfx_rhythm="Repetitive but satisfying: action clip, small proof card, ordered ladder.",
        final_beat="Force a choice between boring baseline and shiny hack.",
        forbidden_moves=["Do not add motivational outro after the fork.", "Avoid meme chaos."],
    ),
    "two_roads": _fmt(
        label="two_roads",
        hook_grammar="Make the whole reel a split choice, not just the final scene.",
        six_beat_skeleton=[
            "road A/road B",
            "what each road promises",
            "what each road costs",
            "proof or example",
            "where the viewer stands",
            "strong final fork",
        ],
        opening_scene_pool=["Scene001", "Scene006", "Scene010", "Scene023", "Scene027"],
        middle_scene_pool=["Scene010", "Scene011", "Scene012", "Scene021", "Scene024", "Scene027"],
        proof_scene_pool=["Scene003", "Scene008", "Scene011", "Scene020", "Scene026"],
        final_scene_pool=["Scene023", "Scene025"],
        layout_recipe_hints=[
            "duel_2_assets",
            "text_image_text_2_assets",
            "quote_evidence_2_assets",
            "sandwich_2_assets",
            "beat_ladder_2_assets",
            "beat_ladder_3_assets",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="Paired visual camps plus occasional single proof card. Avoid 5-6 assets unless proving pile-up.",
        text_density="Binary phrasing; one clean contrast per scene, usually 4-9 words.",
        vfx_rhythm="Left/right alternation; assets appear on 'or/but/against' words; final slows down.",
        final_beat="Must be a real two-road choice. In strict girly-v5 use final_fork_0/1, not unsupported 2-asset finals.",
        forbidden_moves=["Do not reveal the fork only at the end.", "Do not add a summary after the final fork."],
    ),
    "forbidden_answer": _fmt(
        label="forbidden_answer",
        hook_grammar="Say the taboo answer, soften the certainty, then earn the hard close.",
        six_beat_skeleton=[
            "taboo claim",
            "why it feels rude",
            "softening caveat",
            "evidence/example",
            "hard useful answer",
            "polite answer versus forbidden answer",
        ],
        opening_scene_pool=["Scene006", "Scene010", "Scene012", "Scene025"],
        middle_scene_pool=["Scene009", "Scene010", "Scene011", "Scene012", "Scene026"],
        proof_scene_pool=["Scene003", "Scene008", "Scene011", "Scene026"],
        final_scene_pool=["Scene012", "Scene023", "Scene025"],
        layout_recipe_hints=[
            "duel_2_assets",
            "sandwich_2_assets",
            "quote_evidence_2_assets",
            "proof_card_1_asset",
            "slam_0_assets",
            "whisper_0_assets",
            "speaker_broll_0_assets",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="0-2 assets most scenes: main video, support photo/video, science/proof card, one meme/object symbol.",
        text_density="Punchy-medium. Prefer 4-10 spoken words per scene.",
        vfx_rhythm="Hard claim, two-side contradiction, logic/proof card, quiet human nuance.",
        final_beat="End between the polite answer and the forbidden answer.",
        forbidden_moves=["No generic 'agree?' CTA.", "Do not introduce new proof after final question."],
    ),
    "trend_sober_take": _fmt(
        label="trend_sober_take",
        hook_grammar="Open with the trend visual, then soberly decode the desire behind it.",
        six_beat_skeleton=[
            "trend visual",
            "why it seduces",
            "desire behind trend",
            "safe caveat",
            "boring baseline",
            "wearable versus pressure",
        ],
        opening_scene_pool=["Scene013", "Scene014", "Scene015", "Scene017"],
        middle_scene_pool=["Scene011", "Scene012", "Scene014", "Scene015", "Scene016", "Scene017", "Scene018"],
        proof_scene_pool=["Scene003", "Scene008", "Scene017", "Scene019"],
        final_scene_pool=["Scene015", "Scene023", "Scene025"],
        layout_recipe_hints=[
            "magazine_grid_4_assets",
            "magazine_grid_5_assets",
            "magazine_grid_6_assets",
            "orbit_4_assets",
            "material_stack_3_assets",
            "material_stack_4_assets",
            "object_hero_1_asset",
            "cascade_5_assets",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="4-6 real same-family fashion references for trend beats; proof only when explicit.",
        text_density="Visual-heavy, low text. Trend titles 5-8 words max; tags 1-2 words.",
        vfx_rhythm="Editorial catalog reveal, numbered trend beats, sober critique as pause.",
        final_beat="Choice like wearable versus costume, taste versus algorithm.",
        forbidden_moves=["Do not end as shopping advice.", "No hype CTA after the sober take."],
    ),
    "pretty_word_decode": _fmt(
        label="pretty_word_decode",
        hook_grammar="A pretty word appears, then the reel translates what it actually demands.",
        six_beat_skeleton=[
            "pretty word",
            "rough translation",
            "mechanism underneath",
            "example/proof",
            "price of the word",
            "useful language versus prettier pressure",
        ],
        opening_scene_pool=["Scene006", "Scene009", "Scene012", "Scene015"],
        middle_scene_pool=["Scene010", "Scene011", "Scene012", "Scene016", "Scene018", "Scene026"],
        proof_scene_pool=["Scene003", "Scene008", "Scene011", "Scene019", "Scene026"],
        final_scene_pool=["Scene012", "Scene023", "Scene025"],
        layout_recipe_hints=[
            "whisper_0_assets",
            "slam_0_assets",
            "object_hero_1_asset",
            "proof_card_1_asset",
            "duel_2_assets",
            "quote_evidence_1_asset",
            "quote_evidence_2_assets",
            "text_image_text_1_asset",
            "text_image_text_2_assets",
            "material_stack_2_assets",
            "final_fork_0_assets",
            "final_fork_1_asset",
        ],
        asset_count_profile="0-3 assets: the word, one concrete object/proof, optional science/fashion reference.",
        text_density="Definition-like but split. One repeated keyword where possible.",
        vfx_rhythm="Pretty word quietly appears, meaning decodes, proof card lands, human question.",
        final_beat="Ask whether the word is useful language or prettier pressure.",
        forbidden_moves=["Do not introduce another definition in the final beat.", "Avoid generic dictionary UI."],
    ),
}


def normalized_story_format(value: object) -> str | None:
    text = str(value or "").strip().lower().replace("-", "_")
    return text if text in STORY_FORMATS else None


def story_format_spec(format_id: str | None) -> dict[str, Any] | None:
    normalized = normalized_story_format(format_id)
    if not normalized:
        return None
    return STORY_FORMATS[normalized]


def reel_template_family(format_id: str | None) -> str:
    spec = story_format_spec(format_id)
    if not spec:
        return DEFAULT_REEL_TEMPLATE_FAMILY
    return str(spec["template_family"])


def story_format_ids() -> list[str]:
    return list(STORY_FORMAT_IDS)


def allowed_scene_ids_for_format(format_id: str | None) -> set[str]:
    spec = story_format_spec(format_id)
    if not spec:
        return set()
    allowed: set[str] = set()
    for key in ("opening_scene_pool", "middle_scene_pool", "proof_scene_pool", "final_scene_pool"):
        allowed.update(str(scene_id) for scene_id in spec.get(key) or [])
    return allowed


def story_format_prompt_json() -> str:
    prompt_specs = [
        {
            "story_format": format_id,
            **STORY_FORMATS[format_id],
        }
        for format_id in STORY_FORMAT_IDS
    ]
    return json.dumps(prompt_specs, ensure_ascii=False, indent=2)


def build_story_format_cookbook() -> str:
    return f"""

<!-- {STORY_FORMAT_COOKBOOK_MARKER} -->

STAGE 1 STORY FORMAT CONTRACT

Before writing scenes, choose exactly one `story_format` from the canonical list
below. This is not a loose tag. It is the reel's narrative grammar and template
family. The script, scene rhythm, final beat, and `girly_scene` choices must all
follow the selected format.

Required top-level JSON fields:
- `story_format`: exactly one canonical id from the list.
- `story_format_reason`: short Russian explanation of why this format fits the
  source conflict.
- `story_format_confidence`: number from 0.0 to 1.0.
- `story_format_beat_map`: six objects that map the chosen skeleton to this
  concrete reel. Each object should include `order`, `beat_name`,
  `narrative_job`, `target_seconds`, `required_turn`, and
  `preferred_scene_pool`.

Gemini does not write HTML/CSS. The existing controlled scene library renders
`Scene001`-`Scene027`; the format only routes which existing scenes and counted
`layout_recipe_hint` values are preferred.

Strict compatibility note: in the current girly-v5 registry, final questions
should use `final_fork_0_assets` or `final_fork_1_asset` unless a future registry
explicitly supports a 2-asset final fork. Do not force unsupported
`final_fork_2_assets`.

Canonical story formats:

{story_format_prompt_json()}

Validation rules:
- Missing or invalid `story_format` requires a rewrite.
- `story_format_beat_map` must contain six beats matching the chosen skeleton.
- Storyboards should contain 18-30 scenes.
- Every scene must choose a concrete `girly_scene.scene_id` from `Scene001`-`Scene027`.
- Every scene should use `Scene001`-`Scene027`; prefer the selected format's
  pools unless there is a clear story reason.
- Preserve the usual pipeline contract: `voiceover_line` remains the only main
  visible text source; assets come only from `visual_assets`; no freeform HTML.
""".strip()


def append_story_format_cookbook(prompt: str) -> str:
    if STORY_FORMAT_COOKBOOK_MARKER in prompt:
        return prompt
    return "\n\n".join([prompt.rstrip(), build_story_format_cookbook()])


def extract_story_format(payload: Mapping[str, Any]) -> str | None:
    storyboard = payload.get("storyboard_v2") if isinstance(payload.get("storyboard_v2"), Mapping) else payload
    return normalized_story_format(storyboard.get("story_format") if isinstance(storyboard, Mapping) else None)


def validate_story_format_payload(payload: Mapping[str, Any]) -> list[str]:
    storyboard = payload.get("storyboard_v2") if isinstance(payload.get("storyboard_v2"), Mapping) else payload
    if not isinstance(storyboard, Mapping):
        return ["storyboard_payload_is_not_an_object"]

    format_id = normalized_story_format(storyboard.get("story_format"))
    if not format_id:
        return ["missing_or_invalid_story_format"]

    issues: list[str] = []
    beat_map = storyboard.get("story_format_beat_map")
    if not isinstance(beat_map, list) or len(beat_map) != 6:
        issues.append("story_format_beat_map_must_have_6_beats")
    else:
        for index, beat in enumerate(beat_map, start=1):
            if not isinstance(beat, Mapping):
                issues.append(f"story_format_beat_{index}_is_not_object")
                continue
            if int(beat.get("order") or index) != index:
                issues.append(f"story_format_beat_{index}_order_mismatch")
            for key in ("beat_name", "narrative_job", "required_turn"):
                if not str(beat.get(key) or "").strip():
                    issues.append(f"story_format_beat_{index}_missing_{key}")

    allowed_scene_ids = allowed_scene_ids_for_format(format_id)
    scenes = storyboard.get("scenes")
    if isinstance(scenes, list):
        if not 18 <= len(scenes) <= 30:
            issues.append("storyboard_scene_count_must_be_18_to_30")
        selected_scene_ids: list[str] = []
        missing_girly_scene = 0
        for scene in scenes:
            if not isinstance(scene, Mapping):
                continue
            girly_scene = scene.get("girly_scene")
            if isinstance(girly_scene, Mapping):
                scene_id = str(girly_scene.get("scene_id") or "").strip()
                if scene_id:
                    selected_scene_ids.append(scene_id)
                else:
                    missing_girly_scene += 1
            else:
                missing_girly_scene += 1
        if missing_girly_scene:
            issues.append("all_scenes_must_include_girly_scene")
        if allowed_scene_ids and selected_scene_ids and not any(scene_id in allowed_scene_ids for scene_id in selected_scene_ids):
            issues.append("story_format_scene_pool_not_used")
        if allowed_scene_ids and scenes and not selected_scene_ids:
            issues.append("story_format_scene_pool_not_used")

    return issues
