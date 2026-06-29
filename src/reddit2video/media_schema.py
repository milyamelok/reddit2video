from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class MediaCandidateModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidate_id: str
    provider: Literal["giphy", "google_images", "serper_images", "brightdata_google_images", "pinterest"]
    query: str
    title: str = ""
    page_url: str = ""
    thumbnail_url: str = ""
    media_url: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    position: int = 0
    metadata: Dict[str, object] = Field(default_factory=dict)


class MediaCandidateScores(BaseModel):
    model_config = ConfigDict(extra="ignore")

    readability: int = 0
    scene_relevance: int = 0
    stance_clarity: int = 0
    emotional_charge: int = 0
    meme_or_cultural_value: int = 0
    cropability: int = 0
    motion_potential: int = 0
    platform_safety: int = 0


class RankedMediaCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidate_id: str
    rank: int
    use_case: Literal["primary", "backup", "collage_element", "reference_only"] = "backup"
    publishability_tier: Literal["strong", "usable", "weak", "reject"] = "usable"
    total_score_40: int = 0
    why_selected: str = ""
    scores: MediaCandidateScores = Field(default_factory=MediaCandidateScores)
    crop_instruction: str = ""
    animation_instruction: str = ""
    risk_note: str = ""


class RejectedMediaCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidate_id: str
    reason: str = ""


class MediaSelectorDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot_id: str = ""
    verdict: Literal["select", "no_good_candidate"] = "select"
    selected_candidate_ids: List[str] = Field(default_factory=list)
    rejected_candidate_ids: List[str] = Field(default_factory=list)
    ranked_candidates: List[RankedMediaCandidate] = Field(default_factory=list)
    rejected_reasons: List[RejectedMediaCandidate] = Field(default_factory=list)
    better_search_queries: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""
    visual_fit_notes: List[str] = Field(default_factory=list)
    safety_notes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    notes_for_editor: str = ""


class MediaQueryRewriteDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rewritten_query: str = ""
    rationale: str = ""
    warnings: List[str] = Field(default_factory=list)
