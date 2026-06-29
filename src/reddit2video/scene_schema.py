from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SceneModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FragmentTag(str, Enum):
    HOOK = "hook"
    HOOK_INVERSION = "hook_inversion"
    CONTEXT = "context"
    RECOGNIZABLE_PATTERN = "recognizable_pattern"
    EXAMPLE = "example"
    ESCALATION = "escalation"
    CONTRAST = "contrast"
    TWIST = "twist"
    MECHANISM = "mechanism"
    METAPHOR = "metaphor"
    LABEL = "label"
    RULE = "rule"
    SAVE_OBJECT = "save_object"
    SHARE_PROMPT = "share_prompt"
    COMMENT_BAIT = "comment_bait"
    PUNCH = "punch"
    BRIDGE = "bridge"


class BoundaryStrength(str, Enum):
    NONE = "none"
    WEAK = "weak"
    PREFERRED = "preferred"
    FORCED = "forced"


class LabeledFragment(SceneModel):
    fragment_id: int = Field(..., ge=1)
    text: str = Field(..., min_length=1)
    tag: FragmentTag
    boundary_after: BoundaryStrength
    is_anchor: bool = False


class SemanticFragmentOutput(SceneModel):
    original_voiceover: str = Field(..., min_length=1)
    fragments: list[LabeledFragment] = Field(..., min_length=1)
    segmentation_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_fragment_ids(self):
        expected = list(range(1, len(self.fragments) + 1))
        actual = [fragment.fragment_id for fragment in self.fragments]
        if actual != expected:
            raise ValueError("fragment_id must be sequential starting from 1.")
        return self


class TimedFragment(LabeledFragment):
    start_sec: float = Field(..., ge=0)
    end_sec: float = Field(..., ge=0)
    duration_sec: float = Field(..., ge=0)
    asr_confidence: Optional[float] = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_timing(self):
        if self.end_sec < self.start_sec:
            raise ValueError("end_sec must be >= start_sec.")
        measured = self.end_sec - self.start_sec
        if abs(measured - self.duration_sec) > 0.075:
            raise ValueError("duration_sec should approximately equal end_sec - start_sec.")
        return self


class SceneTag(str, Enum):
    COLD_HOOK = "cold_hook"
    HOOK_INVERSION = "hook_inversion"
    CONTEXT = "context"
    RECOGNIZABLE_PATTERN = "recognizable_pattern"
    ESCALATION = "escalation"
    CONTRAST = "contrast"
    TWIST = "twist"
    MECHANISM = "mechanism"
    METAPHOR = "metaphor"
    LABEL = "label"
    RULE = "rule"
    SAVE_ARTIFACT = "save_artifact"
    SHARE_PROMPT = "share_prompt"
    DEBATE_CARD = "debate_card"
    PUNCH = "punch"
    BRIDGE = "bridge"


class VisualDensity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class VisualMode(str, Enum):
    BACKGROUND_VIDEO = "background_video"
    FOREGROUND_MEDIA = "foreground_media"
    TEXT_ONLY = "text_only"
    DEFINITION = "definition"
    CHECKLIST = "checklist"


class TextUnitPolicy(str, Enum):
    SPOKEN_WORDS = "spoken_words"
    FULL_DEFINITION = "full_definition"
    FULL_LIST = "full_list"
    FULL_TERM = "full_term"


class TemplateHint(str, Enum):
    HERO_TEXT = "hero_text"
    IMAGE_PLUS_CAPTION = "image_plus_caption"
    VIDEO_PLUS_CAPTION = "video_plus_caption"
    GIF_REACTION = "gif_reaction"
    SPLIT_COMPARISON = "split_comparison"
    COLLAGE = "collage"
    FAKE_UI = "fake_ui"
    CHECKLIST = "checklist"
    DEBATE_CARD = "debate_card"
    ONE_WORD_PUNCH = "one_word_punch"
    QUOTE_CARD = "quote_card"
    REEL_CARD = "reel_card"
    WHEEL_OR_DIAGRAM = "wheel_or_diagram"
    MINIMAL_BRIDGE = "minimal_bridge"


class RowRole(str, Enum):
    HERO = "hero"
    SUB = "sub"
    STICKER = "sticker"
    LABEL = "label"
    TINY = "tiny"


class MediaKind(str, Enum):
    IMAGE = "image"
    GIF = "gif"
    VIDEO = "video"
    ICON = "icon"
    STICKER = "sticker"
    FAKE_UI = "fake_ui"
    DIAGRAM = "diagram"
    TEXT_SHAPE = "text_shape"


class AssetRole(str, Enum):
    BACKGROUND_TEXTURE = "background_texture"
    SUBJECT = "subject"
    EMOTIONAL_TEXTURE = "emotional_texture"
    METAPHOR = "metaphor"
    CONTRAST_SIDE_A = "contrast_side_a"
    CONTRAST_SIDE_B = "contrast_side_b"
    EVIDENCE_PROP = "evidence_prop"
    WARNING_STICKER = "warning_sticker"
    UI_CARD = "ui_card"
    SAVE_ARTIFACT = "save_artifact"
    DEBATE_OPTION = "debate_option"
    DECORATIVE_ACCENT = "decorative_accent"


class AssetSourceStrategy(str, Enum):
    STOCK_SEARCH = "stock_search"
    GENERATED = "generated"
    EXISTING_LIBRARY = "existing_library"
    TEMPLATE_NATIVE = "template_native"
    MANUAL_CLIP = "manual_clip"
    NONE = "none"


class MotionHint(str, Enum):
    STATIC = "static"
    KEN_BURNS = "ken_burns"
    POP_IN = "pop_in"
    LOOP = "loop"
    GLITCH = "glitch"
    SHAKE = "shake"
    SLIDE_IN = "slide_in"
    STACK_BUILD = "stack_build"
    ZOOM_PUNCH = "zoom_punch"
    HARD_CUT = "hard_cut"
    SLOW_MOTION = "slow_motion"


class SceneTextRow(SceneModel):
    text: str = Field(..., min_length=1)
    role: RowRole
    source_fragment_ids: list[int] = Field(..., min_length=1)


class MediaAssetSlot(SceneModel):
    asset_id: str = Field(..., min_length=1)
    kind: MediaKind
    role: AssetRole
    source_strategy: AssetSourceStrategy
    source_fragment_ids: list[int] = Field(..., min_length=1)
    required: bool = True
    search_query_ru: Optional[str] = None
    search_query_en: Optional[str] = None
    visual_prompt: str = Field(..., min_length=1)
    avoid: list[str] = Field(default_factory=list)
    crop_hint: str = "9:16 safe, subject centered"
    motion_hint: MotionHint = MotionHint.STATIC
    girly_asset_role: Optional[str] = None
    preferred_slot: Optional[str] = None


class SceneGroup(SceneModel):
    scene_id: int = Field(..., ge=1)
    fragment_ids: list[int] = Field(..., min_length=1)
    scene_tag: SceneTag
    visual_density: VisualDensity
    visual_mode: VisualMode = VisualMode.TEXT_ONLY
    text_unit_policy: TextUnitPolicy = TextUnitPolicy.SPOKEN_WORDS
    template_hint: TemplateHint
    attention_job: str = Field(..., min_length=1)
    screen_rows: list[SceneTextRow] = Field(..., min_length=1, max_length=4)
    media_slots: list[MediaAssetSlot] = Field(default_factory=list, max_length=7)
    build_order: list[str] = Field(default_factory=list)
    exit_energy: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_fragment_ids_are_contiguous(self):
        if self.fragment_ids != list(range(self.fragment_ids[0], self.fragment_ids[-1] + 1)):
            raise ValueError("fragment_ids inside a scene must be contiguous.")
        return self


class ScenePlanOutput(SceneModel):
    target_scene_count: int = Field(..., ge=1)
    scenes: list[SceneGroup] = Field(..., min_length=1)
    asset_budget_notes: list[str] = Field(default_factory=list)
    grouping_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scene_ids(self):
        expected = list(range(1, len(self.scenes) + 1))
        actual = [scene.scene_id for scene in self.scenes]
        if actual != expected:
            raise ValueError("scene_id must be sequential starting from 1.")
        return self


@dataclass(frozen=True)
class TimedScene:
    scene_id: int
    start_sec: float
    end_sec: float
    duration_sec: float
    fragment_ids: list[int]
