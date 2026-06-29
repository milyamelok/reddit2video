from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal


JsonObject = dict[str, Any]


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class NodeSpec:
    step: str
    name: str
    description: str
    mocked: bool = False


@dataclass(frozen=True)
class RedditThreadRequest:
    post_id: str | None = None
    post_url: str | None = None
    subreddit: str | None = None
    comment_limit: int = 100
    comment_depth: int = 8
    comment_sort: Literal["confidence", "top", "new", "controversial", "old", "qa"] = "top"


@dataclass(frozen=True)
class RedditDiscoveryRequest:
    topics: list[str] = field(
        default_factory=lambda: [
            "biohacking",
            "wellness",
            "weight loss",
            "fitness",
            "sports",
        ]
    )
    subreddits: list[str] = field(default_factory=list)
    hours: int = 24
    time_filter: Literal["hour", "day", "week", "month", "year", "all"] = "day"
    post_limit: int = 20
    per_subreddit_limit: int = 30
    sort_modes: list[str] = field(default_factory=lambda: ["top", "hot", "new"])
    include_nsfw: bool = False
    min_score: int = 5
    min_comments: int = 5
    comment_limit: int = 100
    comment_depth: int = 8
    comment_sort: Literal["confidence", "top", "new", "controversial", "old", "qa"] = "top"


@dataclass(frozen=True)
class RedditPostSummary:
    id: str
    fullname: str
    subreddit: str
    title: str
    author: str | None
    permalink: str
    score: int
    num_comments: int
    created_utc: float | None
    over_18: bool
    stickied: bool


@dataclass(frozen=True)
class RedditDiscoveryCandidate:
    post: RedditPostSummary
    interesting_score: float
    relevance_score: float
    age_hours: float | None
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RedditPost:
    id: str
    fullname: str
    subreddit: str
    title: str
    selftext: str
    url: str
    permalink: str
    author: str | None
    score: int
    upvote_ratio: float | None
    num_comments: int
    created_utc: float | None
    over_18: bool
    spoiler: bool
    is_self: bool
    link_flair_text: str | None = None


@dataclass(frozen=True)
class RedditComment:
    id: str
    fullname: str
    parent_id: str
    link_id: str
    author: str | None
    body: str
    score: int
    created_utc: float | None
    permalink: str
    depth: int
    replies: list["RedditComment"] = field(default_factory=list)

    def flatten(self) -> list["RedditComment"]:
        comments = [self]
        for reply in self.replies:
            comments.extend(reply.flatten())
        return comments


@dataclass(frozen=True)
class RedditThread:
    post: RedditPost
    comments: list[RedditComment]
    source_url: str
    fetched_at: str
    metadata: JsonObject = field(default_factory=dict)

    @property
    def flat_comments(self) -> list[RedditComment]:
        flattened: list[RedditComment] = []
        for comment in self.comments:
            flattened.extend(comment.flatten())
        return flattened


@dataclass(frozen=True)
class RedditThreadBatch:
    threads: list[RedditThread]
    candidates: list[RedditDiscoveryCandidate]
    fetched_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceoverScriptNodeRequest:
    thread_batch: RedditThreadBatch
    target_language: str = "Russian"
    target_platform: str = "short-form vertical video"
    target_duration_sec: int = 60
    audience: str = "curious general audience interested in wellness, fitness, and biohacking"
    voice_style: str = "conversational, sharp, slightly informal, not cringe"
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    desired_intensity: str = "high but not clickbait-fake"
    validate_scripts: bool = True
    validation_retries: int = 1
    max_comments: int = 35
    max_comment_chars: int = 1200
    use_cache: bool = True
    cache_dir: str = "outputs/cache"
    period_key: str | None = None
    concurrency: int = 2
    prompt_version: Literal["v1", "storyboard_v2"] = "v1"
    master_prompt_path: str = "prompts/voiceover_storyboard_master_v3.md"
    runtime_prompt_path: str = "prompts/voiceover_storyboard_runtime_single_v3.md"
    use_context_cache: bool = False
    context_cache_ttl: str = "3600s"


@dataclass(frozen=True)
class VoiceoverScriptItem:
    post_id: str
    subreddit: str
    title: str
    script: JsonObject
    validator: JsonObject | None
    attempts: int
    from_cache: bool
    cache_path: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceoverScriptBatch:
    items: list[VoiceoverScriptItem]
    fetched_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class ScenePipelineNodeRequest:
    voiceover_batch: VoiceoverScriptBatch
    voice_id: str = "XrExE9yKIg1WjnnlVkGX"
    voice_name: str = "Matilda - Knowledgable, Professional"
    tts_provider: str = "elevenlabs"
    tts_prep_with_gemini: bool = False
    tts_prep_model: str = "gemini-3.1-pro-preview"
    target_scene_count: int = 22
    repair_retries: int = 1
    target_duration_sec: int = 60
    style_pack_path: str = "assets/style_packs/static_girly"
    style_library_hint: str = (
        "Girly wellness/biohacking blogger style: cream background, pink and sky-blue accents, "
        "bold condensed Russian typography, cute meme energy, casual photos, GIFs, and meme/reaction videos. "
        "No emoji stickers, standalone stickers, or interface screenshots; emoji is allowed only inside text."
    )
    use_cache: bool = True
    cache_dir: str = "outputs/cache"
    audio_dir: str = "outputs/audio"
    period_key: str | None = None
    concurrency: int = 2


@dataclass(frozen=True)
class ScenePipelineItem:
    post_id: str
    subreddit: str
    title: str
    status: Literal["pass", "fail"]
    audio_path: str
    alignment: JsonObject
    semantic_fragments: JsonObject
    timed_fragments: list[JsonObject]
    scene_plan: JsonObject | None
    timed_scenes: list[JsonObject]
    validator_errors: list[str]
    validator_warnings: list[str]
    attempts: int
    from_cache: bool
    cache_path: str
    timed_words: list[JsonObject] = field(default_factory=list)
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class ScenePipelineBatch:
    items: list[ScenePipelineItem]
    fetched_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class MediaResolverNodeRequest:
    scene_batch: ScenePipelineBatch
    providers: list[str] = field(default_factory=lambda: ["giphy", "pinterest"])
    candidates_per_provider: int = 50
    selected_per_slot: int = 1
    max_slots_per_item: int = 100
    contact_sheet_size: int = 10
    pinterest_scroll_steps: int = 3
    selection_mode: Literal["gemini", "heuristic", "first"] = "gemini"
    media_selector_model: str = "gemini-3-flash-preview"
    media_selector_fallback_models: list[str] = field(default_factory=list)
    media_query_rewrite_enabled: bool = True
    media_query_rewrite_model: str = "gemini-3-flash-preview"
    media_query_rewrite_max_slots_per_item: int = 4
    media_query_rewrite_timeout_sec: float = 10.0
    media_provider_search_timeout_sec: float = 15.0
    giphy_connector_mode: Literal["auto", "api", "playwright"] = "auto"
    pinterest_connector_mode: Literal["auto", "api", "playwright"] = "auto"
    pinterest_request_dump_path: str = ""
    pinterest_api_scope: str = "auto"
    pinterest_cache_api_responses: bool = True
    giphy_api_scope: str = "auto"
    giphy_api_key_source: Literal["env", "web", "auto"] = "env"
    giphy_web_key_cache_path: str = "outputs/cache/giphy_web_api_key.json"
    giphy_rating: str = "pg"
    giphy_lang: str = "en"
    giphy_bundle: str = ""
    giphy_download_assets: bool = True
    giphy_download_concurrency: int = 8
    giphy_cache_api_responses: bool = True
    brightdata_zone: str = "serp_api1"
    brightdata_size: Literal["small", "medium", "large"] = "large"
    brightdata_cache_api_responses: bool = True
    serper_gl: str = "us"
    serper_hl: str = "en"
    serper_cache_api_responses: bool = True
    use_cache: bool = True
    cache_dir: str = "outputs/cache"
    out_dir: str = "outputs/media"
    screenshot_dir: str = "outputs/media-screens"
    period_key: str | None = None
    concurrency: int = 1
    ai_image_model: str = "gemini-3.1-flash-image-preview"
    ai_image_generation_enabled: bool = True
    chrome_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    browser_mode: Literal["playwright", "dolphin"] = "playwright"
    dolphin_profile_id: str | None = None
    dolphin_local_api_url: str = "http://127.0.0.1:3001"
    dolphin_fallback_to_playwright: bool = True


@dataclass(frozen=True)
class MediaResolverItem:
    post_id: str
    subreddit: str
    title: str
    status: Literal["pass", "fail"]
    resolved_slots: list[JsonObject]
    provider_errors: list[str]
    validator_warnings: list[str]
    from_cache: bool
    cache_path: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class MediaResolverBatch:
    items: list[MediaResolverItem]
    fetched_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class GoogleImagePlannerNodeRequest:
    scene_batch: ScenePipelineBatch
    model: str = "gemini-3-flash-preview"
    use_cache: bool = True
    cache_dir: str = "outputs/cache"
    out_dir: str = "outputs/google-images-visual-v1"
    period_key: str | None = None
    concurrency: int = 1
    scene_concurrency: int = 20
    max_text_only_scenes: int = 3


@dataclass(frozen=True)
class GoogleImagePlanItem:
    post_id: str
    subreddit: str
    title: str
    status: Literal["pass", "fail"]
    scene_plans: list[JsonObject]
    planner_errors: list[str]
    from_cache: bool
    cache_path: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class GoogleImagePlanBatch:
    items: list[GoogleImagePlanItem]
    fetched_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class GoogleImageResolverNodeRequest:
    plan_batch: GoogleImagePlanBatch
    candidates_per_query: int = 10
    min_image_side_px: int = 720
    selection_mode: Literal["top1", "gemini"] = "top1"
    selector_model: str = "gemini-3-flash-preview"
    use_cache: bool = True
    cache_dir: str = "outputs/cache"
    out_dir: str = "outputs/google-images-visual-v1"
    screenshot_dir: str = "outputs/google-images-visual-v1/screens"
    period_key: str | None = None
    concurrency: int = 4
    serper_gl: str = "us"
    serper_hl: str = "en"
    serper_cache_api_responses: bool = True
    chrome_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@dataclass(frozen=True)
class GoogleImageResolverItem:
    post_id: str
    subreddit: str
    title: str
    status: Literal["pass", "fail"]
    resolved_slots: list[JsonObject]
    provider_errors: list[str]
    from_cache: bool
    cache_path: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class GoogleImageResolverBatch:
    items: list[GoogleImageResolverItem]
    fetched_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class StableGoogleLayoutNodeRequest:
    scene_batch: ScenePipelineBatch
    plan_batch: GoogleImagePlanBatch
    resolver_payload: JsonObject | None = None
    out_dir: str = "outputs/google-images-visual-v1/html"
    period_key: str | None = None
    reuse_existing: bool = False


@dataclass(frozen=True)
class HtmlLayoutNodeRequest:
    scene_batch: ScenePipelineBatch
    media_resolver_payload: JsonObject | None = None
    style_html_path: str = "assets/style_packs/static_girly/index.html"
    reference_screens_dir: str = "outputs/html-experiments/reference-screens"
    out_dir: str = "outputs/html-layouts"
    period_key: str | None = None
    layout_mode: Literal[
        "standard",
        "guardrails",
        "two_pass",
        "guardrails_two_pass",
        "meaning_preserving",
        "meaning_preserving_two_pass",
        "full_text_sexy",
    ] = "standard"
    generation_seed: int | None = None
    with_reference_screens: bool = True
    repair_retries: int = 1
    repair_if_needed: bool = True
    max_issue_screenshots: int = 10
    visual_gate_max_screenshots: int = 4
    min_scene_count: int = 18
    max_scene_count: int = 25
    reuse_existing: bool = False
    skip_html_qa: bool = False
    concurrency: int = 1
    chrome_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@dataclass(frozen=True)
class HtmlLayoutItem:
    post_id: str
    subreddit: str
    title: str
    status: Literal["pass", "fail"]
    html_path: str
    raw_path: str
    prompt_path: str
    preview_path: str
    qa: JsonObject
    repair_attempts: int
    from_existing: bool
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class HtmlLayoutBatch:
    items: list[HtmlLayoutItem]
    fetched_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RenderBundleNodeRequest:
    scene_batch: ScenePipelineBatch
    html_batch: HtmlLayoutBatch
    media_resolver_payload: JsonObject | None = None
    word_timing_payload: JsonObject | None = None
    period_key: str | None = None
    fps: int = 30
    width: int = 1080
    height: int = 1920
    scene_asset_dir: str = "remotion/public/render-assets"
    audio_public_dir: str = "remotion/public/audio"
    remotion_data_path: str = "remotion/src/render-bundle.generated.json"
    reuse_existing_assets: bool = True
    render_mode: Literal["dom", "screenshot"] = "dom"
    subtitle_mode: Literal["off", "auto", "always"] = "off"
    chrome_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@dataclass(frozen=True)
class RenderBundleItem:
    post_id: str
    subreddit: str
    title: str
    composition_id: str
    status: Literal["pass", "fail"]
    duration_sec: float
    duration_frames: int
    fps: int
    width: int
    height: int
    audio_path: str
    audio_public_path: str
    scenes: list[JsonObject]
    word_timings: list[JsonObject]
    html_path: str
    errors: list[str]
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RenderBundleBatch:
    items: list[RenderBundleItem]
    fetched_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RenderVisualAuditNodeRequest:
    render_bundle_payload: JsonObject
    post_id: str | None = None
    include_failed: bool = False
    max_scenes: int = 6
    out_dir: str = "outputs/render-visual-audit"
    period_key: str | None = None
    remotion_project_dir: str = "remotion"
    remotion_entry: str = "src/index.ts"
    use_gemini: bool = True
    concurrency: int = 1


@dataclass(frozen=True)
class RenderVisualAuditItem:
    post_id: str
    title: str
    status: Literal["pass", "fail"]
    screenshots: list[JsonObject]
    audit: JsonObject | None
    errors: list[str]
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RenderVisualAuditBatch:
    items: list[RenderVisualAuditItem]
    fetched_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class DesignKit:
    name: str
    colors: list[str]
    typography: dict[str, str]
    motion: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextBundle:
    thread: RedditThread
    design_kit: DesignKit
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GeneratedScript:
    title: str
    beats: list[str]
    narration: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceoverResult:
    audio_path: str
    duration_seconds: float
    voice_id: str
    transcript: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class HtmlGenerationResult:
    mode: Literal["jinja2_template", "gemini_full_html"]
    html_path: str
    assets: list[str]
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class ImageParseResult:
    query: str
    images: list[JsonObject]
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RemotionProjectResult:
    project_dir: str
    tsx_files: list[str]
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RenderResult:
    video_path: str
    duration_seconds: float
    metadata: JsonObject = field(default_factory=dict)
