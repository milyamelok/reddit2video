from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class SchemaModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ConfigAssumptions(SchemaModel):
    target_language: str
    target_platform: str
    target_duration_sec: int
    audience: str
    voice_style: str
    risk_tolerance: Literal["low", "medium", "high"]
    reading_speed_wpm: int


class ContentDna(SchemaModel):
    surface_story: str
    deeper_conflict: str
    core_tension: str
    weirdest_detail: str
    strongest_comment_insight: str
    most_human_comment_insight: str
    main_disagreement: str
    knowns_from_input: list[str]
    unknowns_or_uncertain_claims: list[str]
    details_to_avoid_or_soften: list[str]
    topic_risk_level: Literal["low", "medium", "high"]


class DecisionLogItem(SchemaModel):
    step: str
    choice: str
    concise_reason: str


class AngleScores(SchemaModel):
    novelty: int
    clarity: int
    emotional_activation: int
    source_relevance: int
    save_share_potential: int
    safety: int


class AngleCandidate(SchemaModel):
    angle_type: Literal[
        "direct_story",
        "contrarian",
        "hidden_mechanism",
        "human_psychology",
        "lateral_analogy",
        "save_share_utility",
        "other",
    ]
    angle_name: str
    one_liner: str
    lateral_move: str
    scores: AngleScores
    main_risk: str


class SelectedAngle(SchemaModel):
    angle_name: str
    why_selected: str
    viewer_promise: str
    emotional_engine: str
    save_share_engine: str


class HookCandidate(SchemaModel):
    hook_text: str
    hook_type: Literal[
        "expectation_violation",
        "not_x_actually_y",
        "stakes_inversion",
        "hidden_mechanism",
        "social_conflict",
        "lateral_analogy",
        "practical_utility",
        "uncomfortable_truth",
        "other",
    ]
    open_loop: str
    payoff_implied: str
    risk: str


class SelectedHook(SchemaModel):
    hook_text: str
    why_it_wins: str
    information_gap: str
    first_payoff: str


class PayoffStep(SchemaModel):
    order: int
    reveal: str
    question_answered: str
    next_question_created: str


class ScriptBeat(SchemaModel):
    beat_index: int
    start_sec: int
    end_sec: int
    voiceover_line: str
    on_screen_text: str
    retention_function: Literal[
        "hook",
        "context",
        "contrast",
        "stakes",
        "reveal",
        "payoff",
        "bridge",
        "save_share",
        "final_reframe",
    ]
    micro_question: str
    payoff: str


class ScriptBody(SchemaModel):
    internal_title: str
    estimated_duration_sec: int
    estimated_word_count: int
    voiceover_full_text: str
    beats: list[ScriptBeat]


class RetentionTimelineItem(SchemaModel):
    second: int
    attention_driver: str
    loop_status: Literal["opens_loop", "partial_payoff", "full_payoff", "stakes_raise", "bridge"]
    linked_beat_index: int


class SaveSharePayload(SchemaModel):
    payload_type: Literal[
        "checklist",
        "rule_of_thumb",
        "send_to_someone_frame",
        "one_sentence_argument",
        "red_flag_list",
        "decision_tree",
        "recipe_or_process",
        "ranking_or_order",
        "vocabulary_label",
        "question_to_ask",
        "other",
    ]
    save_reason: str
    share_reason: str
    exact_script_line: str
    use_case: str
    trigger_phrase: str


class RiskAndFactHandling(SchemaModel):
    risk_level: Literal["low", "medium", "high"]
    unverified_claims: list[str]
    claims_softened_in_script: list[str]
    safety_notes: list[str]
    source_limitations: str


class QualityValidation(SchemaModel):
    total_score_100: int
    hook_score_10: int
    retention_score_10: int
    clarity_score_10: int
    novelty_score_10: int
    source_fidelity_score_10: int
    save_share_score_10: int
    voice_naturalness_score_10: int
    safety_score_10: int
    dead_zones_found: list[str]
    failed_checks: list[str]
    revision_performed: bool
    pass_: bool = Field(alias="pass")


class RedditVoiceoverScriptOutput(SchemaModel):
    config_assumptions: ConfigAssumptions
    content_dna: ContentDna
    decision_log: list[DecisionLogItem]
    angle_candidates: list[AngleCandidate]
    selected_angle: SelectedAngle
    hook_candidates: list[HookCandidate]
    selected_hook: SelectedHook
    payoff_ladder: list[PayoffStep]
    script: ScriptBody
    retention_timeline: list[RetentionTimelineItem]
    save_share_payload: SaveSharePayload
    risk_and_fact_handling: RiskAndFactHandling
    quality_validation: QualityValidation
    rewrite_notes: list[str]


class SurgicalRewriteSuggestion(SchemaModel):
    location: str
    problem: str
    replacement: str


class VoiceoverValidatorOutput(SchemaModel):
    verdict: Literal["pass", "fail"]
    score_100: int
    top_issues: list[str]
    dead_zones: list[str]
    unsafe_or_unsupported_claims: list[str]
    hook_diagnosis: str
    retention_diagnosis: str
    save_share_diagnosis: str
    voiceover_diagnosis: str
    required_rewrites: list[str]
    surgical_rewrite_suggestions: list[SurgicalRewriteSuggestion]


class StoryboardSourceDigest(SchemaModel):
    raw_topic: str
    what_happened: str
    comment_conflict: str
    do_not_reference_source_in_voiceover: bool


class StoryboardTwoCamps(SchemaModel):
    camp_a: str
    camp_b: str


class StoryboardStrategy(SchemaModel):
    core_conflict: str
    two_camps: StoryboardTwoCamps
    emotional_wound: str
    hidden_third_insight: str
    chosen_angle: str
    story_engine: str
    narrator_mask: str
    hook_type: str
    ending_type: str
    why_this_will_retain: str


class StoryboardVoiceover(SchemaModel):
    full_text: str
    estimated_duration_sec: int
    bait_question: str


class StoryboardSceneMix(SchemaModel):
    total_scenes: int
    text_only_scenes: int
    avatar_scenes: int
    collage_scenes: int
    ai_generated_image_scenes: int


StoryFormatId = Literal[
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


class StoryFormatBeat(SchemaModel):
    order: int = Field(ge=1, le=6)
    beat_name: str
    narrative_job: str
    target_seconds: str
    required_turn: str
    preferred_scene_pool: list[str] = []


# BEGIN GIRLY STATIC SCENE SCHEMA

GirlySceneId = Literal[
    "Scene001",
    "Scene002",
    "Scene003",
    "Scene004",
    "Scene005",
    "Scene006",
    "Scene007",
    "Scene008",
    "Scene009",
    "Scene010",
    "Scene011",
    "Scene012",
    "Scene013",
    "Scene014",
    "Scene015",
    "Scene016",
    "Scene017",
    "Scene018",
    "Scene019",
    "Scene020",
    "Scene021",
    "Scene022",
    "Scene023",
    "Scene024",
    "Scene025",
    "Scene026",
    "Scene027",
]

GirlySceneGroup = Literal[
    "blog_opener_transformation",
    "blog_proof_profile",
    "raw_explainer_meme",
    "fashion_trend_moodboard",
    "habit_fitness_diary",
]

GirlySlotType = Literal["media", "text"]

GirlyTextSource = Literal[
    "spoken_fragment",
    "ui_label",
    "metadata_or_ui_label",
    "metadata_or_short_label",
    "metadata_or_proof_numbers",
    "spoken_fragment_or_ui_label",
    "spoken_fragment_or_short_label",
    "spoken_fragment_or_search_keyword",
    "ui_label_or_spoken_fragment",
    "ui_label_or_search_keyword",
]

GirlyAssetRole = Literal[
    "action_video",
    "background_video",
    "brand_card",
    "calendar_or_metric_card",
    "contract_card",
    "creator_card",
    "detail_photo",
    "diary_photo",
    "email_receipt",
    "fashion_cutout",
    "fashion_detail",
    "fashion_look",
    "fashion_reference",
    "fitness_action_photo",
    "fitness_detail_photo",
    "habit_action_photo",
    "habit_proof_card",
    "lifestyle_photo",
    "main_video",
    "pain_photo",
    "pet_or_meme_photo",
    "profile_avatar",
    "profile_card",
    "profile_screenshot",
    "reaction_photo",
    "result_photo",
    "science_image",
    "social_photo",
    "stats_grid",
    "style_avatar",
    "supporting_photo",
    "supporting_video_or_photo",
    "travel_photo",
]


class GirlySceneSlotPlan(SchemaModel):
    slot: str = Field(description="CSS class slot from static_girly_2/index.html, e.g. s27-video or s14-title.")
    slot_type: GirlySlotType
    role: str
    required: bool = True
    visual_asset_index: Optional[int] = Field(default=None, ge=0)
    text: Optional[str] = None
    text_source: Optional[GirlyTextSource] = None
    appears_on_word: Optional[str] = None


class GirlySceneSelection(SchemaModel):
    scene_id: GirlySceneId
    scene_group: GirlySceneGroup
    storytelling_function: str
    semantic_reason: str
    asset_semantics: list[GirlyAssetRole]
    slot_plan: list[GirlySceneSlotPlan]
    fallback_scene_id: Optional[GirlySceneId] = None
    do_not_use_scene_ids: list[GirlySceneId] = []


# END GIRLY STATIC SCENE SCHEMA


class StoryboardVisualAsset(SchemaModel):
    asset: str
    girly_asset_role: Optional[GirlyAssetRole] = None
    preferred_slot: Optional[str] = None
    source: Literal["Google Images", "Giphy", "Telegram stickers", "AI-generated", "Stock/Footage"]
    search_query: str
    appears_on_word: str
    why: str


StoryboardLayoutRecipeHint = Literal[
    "slam",
    "slam_0_assets",
    "slam_1_asset",
    "whisper",
    "whisper_0_assets",
    "whisper_1_asset",
    "object_hero",
    "object_hero_1_asset",
    "proof_card",
    "proof_card_1_asset",
    "duel",
    "duel_2_assets",
    "sandwich",
    "sandwich_2_assets",
    "material_stack",
    "material_stack_2_assets",
    "material_stack_3_assets",
    "material_stack_4_assets",
    "beat_ladder",
    "beat_ladder_2_assets",
    "beat_ladder_3_assets",
    "beat_ladder_4_assets",
    "orbit",
    "orbit_3_assets",
    "orbit_4_assets",
    "orbit_5_assets",
    "orbit_6_assets",
    "magazine_grid",
    "magazine_grid_4_assets",
    "magazine_grid_5_assets",
    "magazine_grid_6_assets",
    "cascade",
    "cascade_5_assets",
    "cascade_6_assets",
    "evidence_wall",
    "evidence_wall_5_assets",
    "evidence_wall_6_assets",
    "text_image_text",
    "text_image_text_1_asset",
    "text_image_text_2_assets",
    "text_image_text_3_assets",
    "quote_evidence",
    "quote_evidence_1_asset",
    "quote_evidence_2_assets",
    "quote_evidence_3_assets",
    "speaker_broll",
    "speaker_broll_0_assets",
    "final_fork",
    "final_fork_0_assets",
    "final_fork_1_asset",
    "final_fork_2_assets",
]


class StoryboardScene(SchemaModel):
    scene_id: int
    duration_sec: float
    scene_type: Literal["TEXT_ONLY", "AVATAR", "COLLAGE", "AI_IMAGE"]
    voiceover_line: str
    layout_recipe_hint: Optional[StoryboardLayoutRecipeHint] = None
    target_visual_asset_count: Optional[int] = Field(default=None, ge=0, le=6)
    asset_count_reason: Optional[str] = None
    retention_function: str
    visual_direction: str
    background: str
    visual_assets: list[StoryboardVisualAsset]
    animation: str
    typography_notes: str
    ai_image_prompt: Optional[str] = None
    girly_scene: Optional[GirlySceneSelection] = None


class StoryboardQualityControl(SchemaModel):
    does_not_reference_reddit: bool
    has_hook_in_first_2_seconds: bool
    has_retention_shift_every_2_to_5_sec: bool
    has_clear_visuals_for_each_scene: bool
    uses_voiceover_line_as_only_text: bool = True
    uses_recipe_aware_asset_counts: bool = True
    has_no_forced_text_only_quota: bool = True
    has_no_forced_avatar_quota: bool = True
    has_no_avatar_scene_under_2_sec: bool = True
    has_scene_duration_word_density_ok: bool = True
    has_speaker_share_by_duration_not_count: bool = True
    has_4_to_6_text_only_scenes: bool = False
    has_4_to_6_avatar_scenes: bool = False
    has_collage_visuals_with_3_to_4_assets: bool = False
    has_final_bait_question: bool
    avoids_medical_overclaiming: bool
    anti_brainrot_pass: bool


class RedditVoiceoverStoryboardOutput(SchemaModel):
    title: str
    story_format: Optional[StoryFormatId] = None
    story_format_reason: Optional[str] = None
    story_format_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    story_format_beat_map: list[StoryFormatBeat] = []
    source_digest: StoryboardSourceDigest
    story_strategy: StoryboardStrategy
    voiceover: StoryboardVoiceover
    scene_mix: StoryboardSceneMix
    scenes: list[StoryboardScene]
    asset_checklist: list[str]
    quality_control: StoryboardQualityControl
