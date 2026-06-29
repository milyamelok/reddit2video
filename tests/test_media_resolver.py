import asyncio
import json

from reddit2video.gemini import GeminiClientError
from reddit2video.media_connectors import (
    BrightDataGoogleImagesConnector,
    GiphyApiConnector,
    GiphyPlaywrightConnector,
    MediaCandidate,
    MediaSearchResult,
    PinterestApiConnector,
    PinterestPlaywrightConnector,
    SerperDevImagesConnector,
    WikimediaCommonsImagesConnector,
    _brightdata_authorization_header,
    _brightdata_google_candidate_from_raw,
    _giphy_api_scopes,
    _giphy_candidate_from_raw,
    _contact_sheet_html,
    _extract_giphy_api_key_from_url,
    _giphy_query,
    _read_giphy_web_api_key_cache,
    _pinterest_api_scopes,
    _pinterest_candidate_from_raw,
    _serper_image_candidate_from_raw,
    _wikimedia_commons_candidate_from_raw,
    _wikimedia_search_query,
    build_slot_query,
    connector_for_provider,
    provider_hint_for_slot,
)
from reddit2video.models import MediaResolverItem, MediaResolverNodeRequest, ScenePipelineBatch, ScenePipelineItem
from reddit2video.media_schema import MediaCandidateModel, MediaQueryRewriteDecision, MediaSelectorDecision
from reddit2video.nodes.media_resolver import (
    MediaResolverNode,
    _build_selector_prompt,
    _candidate_media_file_rejection_reason,
    _candidate_media_dedupe_key,
    _candidate_pool_for_slot,
    _candidate_quality_rejection_reason,
    _decision_candidate_ids,
    _fallback_ranked_decision,
    _fallback_query_for_slot,
    _first_publishable_candidate,
    _gemini_rewrite_query_for_slot,
    _giphy_fallback_query_for_image_slot,
    _giphy_api_scope_for_slot,
    _iter_media_slots,
    _media_policy_error,
    _media_slot_truncation_summary,
    _normalized_slot_for_resolution,
    _pinterest_api_scope_for_slot,
    _provider_query_for_provider,
    _selected_candidates_with_media_files,
    _selected_candidates,
    _selector_fallback_models,
    _sanitize_rewritten_provider_query,
    _slot_allows_gemini_query_rewrite,
    _slot_search_query,
    _slot_status_for_selection,
    _reserve_cached_item_media_keys,
    _reserve_unique_selected_candidates,
)


def test_media_selector_schema_ignores_extra_fields() -> None:
    decision = MediaSelectorDecision.model_validate(
        {
            "selected_candidate_ids": ["I01"],
            "confidence": 0.91,
            "unexpected": "ignored",
        }
    )

    assert decision.selected_candidate_ids == ["I01"]
    assert decision.confidence == 0.91


def test_selector_prompt_includes_exact_slot_spoken_context() -> None:
    item = ScenePipelineItem(
        post_id="p1",
        subreddit="biohackers",
        title="Morning routine",
        status="pass",
        audio_path="audio.wav",
        alignment={},
        semantic_fragments={},
        timed_fragments=[
            {"fragment_id": 1, "text": "I tried magnesium at night.", "start_sec": 0.0, "end_sec": 2.0},
            {"fragment_id": 2, "text": "Then my sleep got weird.", "start_sec": 2.0, "end_sec": 4.5},
        ],
        scene_plan={},
        timed_scenes=[{"scene_id": 7, "start_sec": 0.0, "end_sec": 4.5, "duration_sec": 4.5, "fragment_ids": [1, 2]}],
        validator_errors=[],
        validator_warnings=[],
        attempts=1,
        from_cache=False,
        cache_path="",
    )

    prompt = _build_selector_prompt(
        item=item,
        scene={"scene_id": 7, "fragment_ids": [1, 2], "scene_tag": "setup"},
        slot={"asset_id": "gif_1", "kind": "gif", "role": "reaction", "source_fragment_ids": [2]},
        query="sleep got weird reaction gif",
        candidates=[MediaCandidate(candidate_id="G01", provider="giphy", query="q", media_url="https://x.test/a.gif")],
        selected_per_slot=1,
    )
    payload = json.loads(prompt.split("INPUT_JSON:\n", 1)[1])

    assert payload["scene"]["voiceover_fragment"] == "I tried magnesium at night. Then my sleep got weird."
    assert payload["scene"]["start_sec"] == 0.0
    assert payload["scene"]["duration_sec"] == 4.5
    assert payload["scene"]["spoken_context"]["slot_spoken_text"] == "Then my sleep got weird."
    assert payload["scene"]["spoken_context"]["slot_start_sec"] == 2.0
    assert payload["scene"]["spoken_context"]["slot_duration_sec"] == 2.5


def test_media_candidate_schema_accepts_optional_dimensions() -> None:
    candidate = MediaCandidateModel.model_validate(
        {
            "candidate_id": "P03",
            "provider": "pinterest",
            "query": "pink wellness habit tracker",
        }
    )

    assert candidate.width is None
    assert candidate.height is None


def test_provider_hint_promotes_giphy_for_memes() -> None:
    providers = provider_hint_for_slot(
        {"kind": "gif", "role": "reaction meme"},
        ["google_images", "giphy", "pinterest"],
    )

    assert providers == ["giphy"]


def test_provider_hint_promotes_giphy_for_funny_object_queries() -> None:
    providers = provider_hint_for_slot(
        {"kind": "image", "role": "subject", "search_query_en": "funny bodybuilder workout"},
        ["serper_images", "giphy", "pinterest"],
    )

    assert providers == ["giphy"]


def test_provider_hint_promotes_pinterest_for_normal_media() -> None:
    providers = provider_hint_for_slot(
        {"kind": "image", "role": "subject", "search_query_en": "woman stretching at home casual photo"},
        ["giphy", "pinterest"],
    )

    assert providers == ["pinterest"]


def test_provider_hint_promotes_pinterest_for_background_footage() -> None:
    providers = provider_hint_for_slot(
        {"kind": "video", "role": "background_texture", "search_query_en": "morning routine footage"},
        ["giphy", "pinterest", "serper_images", "brightdata_google_images"],
    )

    assert providers == ["pinterest"]


def test_provider_hint_promotes_pinterest_for_action_video() -> None:
    providers = provider_hint_for_slot(
        {"kind": "video", "role": "subject", "search_query_en": "doctor visit waiting room video"},
        ["giphy", "pinterest", "serper_images", "brightdata_google_images"],
    )

    assert providers == ["pinterest", "serper_images", "brightdata_google_images"]


def test_provider_hint_keeps_still_image_fallback_for_subject_video_slots() -> None:
    providers = provider_hint_for_slot(
        {"kind": "video", "role": "subject", "search_query_en": "sauna interior video"},
        ["serper_images", "wikimedia_commons", "pinterest"],
    )

    assert providers == ["pinterest", "serper_images", "wikimedia_commons"]


def test_provider_hint_drops_still_image_providers_for_background_motion_slots() -> None:
    providers = provider_hint_for_slot(
        {"kind": "video", "role": "background_texture", "search_query_en": "sauna interior video"},
        ["serper_images", "wikimedia_commons", "pinterest"],
    )

    assert providers == ["pinterest"]


def test_provider_hint_promotes_serper_for_exact_image_slots() -> None:
    providers = provider_hint_for_slot(
        {
            "kind": "image",
            "role": "evidence_prop",
            "source_strategy": "stock_search",
            "search_query_en": "bathroom scale close up photo",
        },
        ["giphy", "pinterest", "serper_images", "brightdata_google_images"],
    )

    assert providers == ["serper_images", "brightdata_google_images", "pinterest"]


def test_provider_hint_uses_wikimedia_after_serper_for_exact_image_slots() -> None:
    providers = provider_hint_for_slot(
        {
            "kind": "image",
            "role": "evidence_prop",
            "source_strategy": "stock_search",
            "search_query_en": "dry sauna interior photo",
        },
        ["pinterest", "wikimedia_commons", "serper_images"],
    )

    assert providers == ["serper_images", "wikimedia_commons", "pinterest"]


def test_provider_hint_blocks_giphy_for_evidence_and_medical_photo_slots() -> None:
    providers = provider_hint_for_slot(
        {
            "kind": "image",
            "role": "foreground",
            "search_query_en": "medical evidence casual lifestyle photo",
        },
        ["giphy", "pinterest", "google_images"],
    )

    assert providers == ["google_images", "pinterest"]


def test_provider_hint_allows_giphy_only_for_explicit_reaction_slots() -> None:
    casual = provider_hint_for_slot(
        {"kind": "image", "role": "foreground", "search_query_en": "emotional lifestyle photo"},
        ["giphy", "pinterest"],
    )
    reaction = provider_hint_for_slot(
        {"kind": "image", "role": "emotional_reaction", "search_query_en": "funny reaction"},
        ["giphy", "pinterest"],
    )

    assert casual == ["pinterest"]
    assert reaction == ["giphy"]


def test_media_resolver_defaults_exclude_google_images() -> None:
    request = MediaResolverNodeRequest(scene_batch=ScenePipelineBatch(items=[], fetched_at="now"))

    assert request.providers == ["giphy", "pinterest"]
    assert request.candidates_per_provider == 50
    assert request.contact_sheet_size == 10
    assert request.pinterest_scroll_steps == 3
    assert request.selection_mode == "gemini"
    assert request.media_selector_model == "gemini-3-flash-preview"
    assert request.media_selector_fallback_models == []
    assert request.media_query_rewrite_enabled is True
    assert request.media_query_rewrite_model == "gemini-3-flash-preview"
    assert request.media_query_rewrite_max_slots_per_item == 4
    assert request.media_query_rewrite_timeout_sec == 10.0
    assert request.media_provider_search_timeout_sec == 15.0
    assert request.pinterest_connector_mode == "auto"
    assert request.pinterest_request_dump_path == ""
    assert request.pinterest_api_scope == "auto"
    assert request.pinterest_cache_api_responses is True
    assert request.giphy_api_scope == "auto"
    assert request.giphy_api_key_source == "env"
    assert request.giphy_web_key_cache_path == "outputs/cache/giphy_web_api_key.json"
    assert request.giphy_download_assets is True
    assert request.giphy_download_concurrency == 8
    assert request.giphy_cache_api_responses is True
    assert request.brightdata_zone == "serp_api1"
    assert request.brightdata_size == "large"
    assert request.brightdata_cache_api_responses is True
    assert request.serper_gl == "us"
    assert request.serper_hl == "en"
    assert request.serper_cache_api_responses is True


def test_selector_fallback_models_default_for_gpt_oss_120b() -> None:
    assert _selector_fallback_models("gpt-oss-120b", []) == ["gemini-3-flash-preview"]
    assert _selector_fallback_models("openai/gpt-oss-120b", ["gemini-3.1-pro-preview"]) == [
        "gemini-3.1-pro-preview"
    ]
    assert _selector_fallback_models("gemini-3-flash-preview", []) == []


def test_media_selector_uses_model_fallback_on_gpt_oss_rate_limit() -> None:
    class StubGemini:
        def __init__(self) -> None:
            self.models: list[str] = []

        async def generate_structured_multimodal(self, **kwargs):
            model = kwargs["model"]
            self.models.append(model)
            if model == "gpt-oss-120b":
                raise GeminiClientError("429 rate limit exceeded for gpt-oss-120b")
            return MediaSelectorDecision(
                selected_candidate_ids=["P02"],
                confidence=0.82,
                rationale="Fallback selector picked the clearer asset.",
            )

    item = ScenePipelineItem(
        post_id="p1",
        subreddit="biohackers",
        title="Morning routine",
        status="pass",
        audio_path="audio.wav",
        alignment={},
        semantic_fragments={},
        timed_fragments=[{"fragment_id": 1, "text": "I tried magnesium at night.", "start_sec": 0.0, "end_sec": 2.0}],
        scene_plan={},
        timed_scenes=[{"scene_id": 1, "start_sec": 0.0, "end_sec": 2.0, "duration_sec": 2.0, "fragment_ids": [1]}],
        validator_errors=[],
        validator_warnings=[],
        attempts=1,
        from_cache=False,
        cache_path="",
    )
    candidates = [
        MediaCandidate(candidate_id="P01", provider="pinterest", query="q", media_url="https://example.com/a.jpg"),
        MediaCandidate(candidate_id="P02", provider="pinterest", query="q", media_url="https://example.com/b.jpg"),
    ]
    gemini = StubGemini()

    decision = asyncio.run(
        MediaResolverNode()._select_candidates(
            item=item,
            scene={"scene_id": 1, "fragment_ids": [1], "scene_tag": "setup"},
            slot={"asset_id": "photo_1", "kind": "image", "role": "reference"},
            query="sleep routine",
            candidates=candidates,
            screenshots=[],
            gemini=gemini,  # type: ignore[arg-type]
            selected_per_slot=1,
            selector_model="gpt-oss-120b",
        )
    )

    assert gemini.models == ["gpt-oss-120b", "gemini-3-flash-preview"]
    assert decision.selected_candidate_ids == ["P02"]
    assert decision.warnings == ["Selector model fallback used: gpt-oss-120b -> gemini-3-flash-preview"]


def test_reserve_unique_selected_candidates_replaces_duplicate_media_url() -> None:
    duplicate = MediaCandidate(
        candidate_id="P01",
        provider="pinterest",
        query="q",
        media_url="https://v1.pinimg.com/videos/a.m3u8",
    )
    replacement = MediaCandidate(
        candidate_id="P02",
        provider="pinterest",
        query="q",
        media_url="https://v1.pinimg.com/videos/b.m3u8",
    )
    used = {"https://v1.pinimg.com/videos/a.m3u8"}
    errors: list[str] = []

    selected = _reserve_unique_selected_candidates(
        [duplicate],
        candidates=[duplicate, replacement],
        used_media_keys=used,
        limit=1,
        errors=errors,
    )

    assert [candidate.candidate_id for candidate in selected] == ["P02"]
    assert "https://v1.pinimg.com/videos/b.m3u8" in used
    assert any("duplicate" in error for error in errors)


def test_reserve_cached_item_media_keys_tracks_selected_urls() -> None:
    item = MediaResolverItem(
        post_id="p1",
        subreddit="biohackers",
        title="Title",
        status="pass",
        resolved_slots=[
            {
                "selected_candidates": [
                    {
                        "candidate_id": "P01",
                        "provider": "pinterest",
                        "query": "q",
                        "media_url": "https://v1.pinimg.com/videos/a.m3u8?x=1",
                    }
                ]
            }
        ],
        provider_errors=[],
        validator_warnings=[],
        from_cache=True,
        cache_path="",
    )
    used: set[str] = set()

    _reserve_cached_item_media_keys(item, used)

    assert used == {"https://v1.pinimg.com/videos/a.m3u8"}


def test_candidate_media_dedupe_key_prefers_actual_media_url() -> None:
    candidate = MediaCandidate(
        candidate_id="P02",
        provider="pinterest",
        query="q",
        media_url="https://v1.pinimg.com/videos/new.m3u8?x=1",
        metadata={"video_hls_url": "https://v1.pinimg.com/videos/stale.m3u8"},
    )

    assert _candidate_media_dedupe_key(candidate) == "https://v1.pinimg.com/videos/new.m3u8"


def test_fallback_query_for_video_slot_preserves_slot_specific_context() -> None:
    fallback = _fallback_query_for_slot(
        {"kind": "video", "role": "main_video", "search_query_en": "sauna cabin steam"},
        "sauna cabin steam",
    )

    assert fallback == "sauna cabin steam"
    assert fallback != "wellness girl casual lifestyle"


def test_giphy_auto_connector_uses_playwright_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("GIPHY_API_KEY", raising=False)

    connector = connector_for_provider("giphy", giphy_mode="auto")

    assert isinstance(connector, GiphyPlaywrightConnector)


def test_giphy_api_connector_can_be_forced_without_key(monkeypatch) -> None:
    monkeypatch.delenv("GIPHY_API_KEY", raising=False)

    connector = connector_for_provider("giphy", giphy_mode="api")

    assert isinstance(connector, GiphyApiConnector)


def test_giphy_api_connector_can_use_cached_web_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GIPHY_API_KEY", raising=False)
    cache_path = tmp_path / "giphy_web_key.json"
    cache_path.write_text(json.dumps({"api_key": "Gc7131jiJuvI7IdN0HZ1D7nh0ow5BU6g"}), encoding="utf-8")

    connector = connector_for_provider(
        "giphy",
        giphy_mode="api",
        giphy_api_key_source="web",
        giphy_web_key_cache_path=cache_path,
    )

    assert isinstance(connector, GiphyApiConnector)
    assert connector.requires_browser is False
    assert _read_giphy_web_api_key_cache(cache_path) == "Gc7131jiJuvI7IdN0HZ1D7nh0ow5BU6g"


def test_giphy_api_connector_requires_browser_for_missing_web_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GIPHY_API_KEY", raising=False)

    connector = connector_for_provider(
        "giphy",
        giphy_mode="api",
        giphy_api_key_source="web",
        giphy_web_key_cache_path=tmp_path / "missing.json",
    )

    assert isinstance(connector, GiphyApiConnector)
    assert connector.requires_browser is True


def test_pinterest_auto_connector_uses_playwright_without_dump(monkeypatch) -> None:
    monkeypatch.delenv("PINTEREST_REQUEST_DUMP_PATH", raising=False)

    connector = connector_for_provider("pinterest", pinterest_mode="auto", pinterest_api_scope="videos")

    assert isinstance(connector, PinterestPlaywrightConnector)
    assert connector.scope == "videos"


def test_pinterest_api_connector_can_be_forced_without_dump(monkeypatch) -> None:
    monkeypatch.delenv("PINTEREST_REQUEST_DUMP_PATH", raising=False)

    connector = connector_for_provider("pinterest", pinterest_mode="api")

    assert isinstance(connector, PinterestApiConnector)


def test_brightdata_google_images_connector_is_api_connector(monkeypatch) -> None:
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)

    connector = connector_for_provider("brightdata_google_images", brightdata_zone="custom_zone")

    assert isinstance(connector, BrightDataGoogleImagesConnector)
    assert connector.requires_browser is False
    assert connector.zone == "custom_zone"


def test_serper_images_connector_is_api_connector(monkeypatch) -> None:
    monkeypatch.delenv("SERPER_API_KEY", raising=False)

    connector = connector_for_provider("serper_images", serper_gl="gb", serper_hl="en")

    assert isinstance(connector, SerperDevImagesConnector)
    assert connector.requires_browser is False
    assert connector.gl == "gb"
    assert connector.hl == "en"


def test_brightdata_auth_header_uses_bearer_for_plain_api_key() -> None:
    assert _brightdata_authorization_header("abc-123") == "Bearer abc-123"
    assert _brightdata_authorization_header("Bearer abc-123") == "Bearer abc-123"


def test_brightdata_google_candidate_maps_original_image_fields() -> None:
    candidate = _brightdata_google_candidate_from_raw(
        index=1,
        query="bathroom scale close up photo",
        item={
            "original_image": "https://example.com/scale.jpg",
            "original_width": "1600",
            "original_height": "900",
            "global_rank": 4,
            "link": "https://example.com/article",
            "title": "Bathroom scale",
        },
    )

    assert candidate is not None
    assert candidate.candidate_id == "B01"
    assert candidate.provider == "brightdata_google_images"
    assert candidate.media_url == "https://example.com/scale.jpg"
    assert candidate.width == 1600
    assert candidate.height == 900
    assert candidate.position == 4
    assert candidate.metadata["transport"] == "brightdata_request"


def test_serper_image_candidate_maps_image_fields() -> None:
    candidate = _serper_image_candidate_from_raw(
        index=1,
        query="bathroom scale close up photo",
        item={
            "title": "Scale photo",
            "imageUrl": "https://example.com/scale.jpg",
            "imageWidth": 1300,
            "imageHeight": 956,
            "thumbnailUrl": "https://example.com/thumb.jpg",
            "source": "Example",
            "domain": "example.com",
            "link": "https://example.com/page",
            "position": 2,
        },
    )

    assert candidate is not None
    assert candidate.candidate_id == "S01"
    assert candidate.provider == "serper_images"
    assert candidate.media_url == "https://example.com/scale.jpg"
    assert candidate.thumbnail_url == "https://example.com/thumb.jpg"
    assert candidate.width == 1300
    assert candidate.height == 956
    assert candidate.position == 2
    assert candidate.metadata["transport"] == "serper_dev"


def test_wikimedia_commons_connector_is_no_key_api_connector() -> None:
    connector = connector_for_provider("wikimedia_commons")

    assert isinstance(connector, WikimediaCommonsImagesConnector)
    assert connector.requires_browser is False


def test_wikimedia_commons_candidate_maps_imageinfo_fields() -> None:
    candidate = _wikimedia_commons_candidate_from_raw(
        index=1,
        query="dry sauna interior photo",
        item={
            "title": "File:Dry sauna interior.jpg",
            "imageinfo": [
                {
                    "thumburl": "https://upload.wikimedia.org/thumb/sauna.jpg",
                    "url": "https://upload.wikimedia.org/sauna.jpg",
                    "thumbwidth": 1400,
                    "thumbheight": 933,
                    "width": 2400,
                    "height": 1600,
                    "mime": "image/jpeg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Dry_sauna_interior.jpg",
                    "extmetadata": {
                        "ObjectName": {"value": "Dry sauna interior"},
                        "ImageDescription": {"value": "<p>Wooden sauna room</p>"},
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    },
                }
            ],
        },
    )

    assert candidate is not None
    assert candidate.candidate_id == "W01"
    assert candidate.provider == "wikimedia_commons"
    assert candidate.title == "Dry sauna interior"
    assert candidate.media_url == "https://upload.wikimedia.org/thumb/sauna.jpg"
    assert candidate.width == 1400
    assert candidate.height == 933
    assert candidate.metadata["license"] == "CC BY-SA 4.0"
    assert candidate.metadata["description"] == "Wooden sauna room"


def test_wikimedia_commons_candidate_rejects_svg_results() -> None:
    candidate = _wikimedia_commons_candidate_from_raw(
        index=1,
        query="orange slice photo",
        item={"title": "File:Orange icon.svg", "imageinfo": [{"mime": "image/svg+xml", "url": "https://x/icon.svg"}]},
    )

    assert candidate is None


def test_wikimedia_search_query_simplifies_pinterest_style_prompts() -> None:
    assert _wikimedia_search_query("huge latte and croissant on aesthetic cafe table photo video footage").startswith(
        "latte croissant cafe table "
    )
    assert _wikimedia_search_query("dry finnish sauna interior vertical video").startswith("dry finnish sauna interior ")


def test_pinterest_api_scope_for_slot_uses_video_only_for_video_slots() -> None:
    assert _pinterest_api_scope_for_slot({"kind": "video", "source_strategy": "stock_search"}, "auto") == "videos"
    assert _pinterest_api_scope_for_slot({"kind": "image", "role": "background_texture"}, "auto") == "videos"
    assert _pinterest_api_scope_for_slot({"kind": "image", "source_strategy": "stock_search"}, "auto") == "pins"
    assert _pinterest_api_scope_for_slot({"kind": "image"}, "all") == "all"


def test_pinterest_api_scopes_supports_images_and_mixed_search() -> None:
    assert _pinterest_api_scopes("pins") == ["pins"]
    assert _pinterest_api_scopes("images") == ["pins"]
    assert _pinterest_api_scopes("videos") == ["videos"]
    assert _pinterest_api_scopes("all") == ["videos", "pins"]


def test_giphy_query_is_limited_to_api_max() -> None:
    query = _giphy_query("pink wellness morning routine soft girl biohacking habit tracker dashboard")

    assert len(query) <= 50


def test_giphy_api_scope_for_slot_stays_on_gifs_by_default() -> None:
    assert _giphy_api_scope_for_slot({"kind": "video", "source_strategy": "gif_search"}, "auto") == "clips,gifs"
    assert _giphy_api_scope_for_slot({"kind": "video", "role": "background_texture"}, "auto") == "clips"
    assert _giphy_api_scope_for_slot({"kind": "image", "role": "reaction meme"}, "auto") == "clips,gifs"
    assert _giphy_api_scope_for_slot({"kind": "image"}, "clips") == "clips"


def test_giphy_api_scopes_supports_site_tabs() -> None:
    assert _giphy_api_scopes("gifs") == ["gifs"]
    assert _giphy_api_scopes("stickers") == ["gifs"]
    assert _giphy_api_scopes("video") == ["clips"]
    assert _giphy_api_scopes("clips,gifs") == ["clips", "gifs"]
    assert _giphy_api_scopes("all") == ["gifs", "clips"]


def test_media_policy_blocks_mock_ui_and_sticker_assets() -> None:
    assert _media_policy_error({"kind": "sticker", "role": "warning_sticker", "source_strategy": "generated"})
    assert _media_policy_error({"kind": "image", "role": "ui_card", "source_strategy": "stock_search"})
    assert _media_policy_error(
        {"kind": "image", "role": "subject", "source_strategy": "stock_search", "visual_prompt": "reddit screenshot"}
    )
    assert (
        _media_policy_error(
            {
                "kind": "image",
                "role": "subject",
                "source_strategy": "stock_search",
                "visual_prompt": "casual photo of woman stretching in bedroom",
            }
        )
        is None
    )
    assert _media_policy_error({"kind": "image", "role": "background_texture", "source_strategy": "stock_search"})
    assert (
        _media_policy_error(
            {
                "kind": "image",
                "role": "metaphor",
                "source_strategy": "generated",
                "visual_prompt": "Surreal editorial collage of a yogurt tub, vertical 9:16, no text.",
            }
        )
        is None
    )


def test_background_image_slot_is_normalized_to_video_query() -> None:
    slot = {
        "asset_id": "bg",
        "kind": "image",
        "role": "background_texture",
        "source_strategy": "stock_search",
        "search_query_en": "pastel clinic waiting room",
    }

    normalized = _normalized_slot_for_resolution(slot)

    assert normalized["kind"] == "video"
    assert normalized["source_strategy"] == "pinterest_search"
    assert _media_policy_error(normalized) is None
    assert _slot_search_query(normalized) == "clinic waiting room"


def test_motion_slot_search_query_removes_photo_intent() -> None:
    assert (
        _slot_search_query(
            {
                "kind": "video",
                "role": "subject",
                "search_query_en": "thin fitness girl holding coffee walking photo",
            }
        )
        == "fitness coffee walking"
    )


def test_slot_search_query_drops_product_and_diet_modifiers() -> None:
    assert (
        _slot_search_query({"kind": "video", "role": "subject", "search_query_en": "iced latte plastic cup photo"})
        == "iced latte cup"
    )
    assert (
        _slot_search_query(
            {"kind": "video", "role": "subject", "search_query_en": "sugar free vanilla syrup bottle photo"}
        )
        == "vanilla syrup bottle"
    )
    assert (
        _slot_search_query({"kind": "video", "role": "subject", "search_query_en": "big healthy salad bowl photo"})
        == "salad bowl"
    )
    assert (
        _slot_search_query(
            {"kind": "video", "role": "subject", "search_query_en": "calorie counter nutrition label photo"}
        )
        == "nutrition label"
    )


def test_serper_subject_food_query_uses_source_quality_token_without_length_bloat() -> None:
    assert (
        _provider_query_for_provider(
            "latte croissant cafe",
            provider="serper_images",
            slot={"kind": "video", "role": "subject"},
        )
        == "latte croissant unsplash"
    )
    assert (
        _provider_query_for_provider(
            "iced latte cup",
            provider="serper_images",
            slot={"kind": "video", "role": "subject"},
        )
        == "iced latte pexels"
    )
    assert (
        _provider_query_for_provider(
            "cafe receipt",
            provider="serper_images",
            slot={"kind": "video", "role": "subject"},
        )
        == "cafe receipt"
    )
    assert (
        _provider_query_for_provider(
            "latte croissant cafe",
            provider="pinterest",
            slot={"kind": "video", "role": "subject"},
        )
        == "latte croissant cafe"
    )
    assert (
        _provider_query_for_provider(
            "half eaten pastry",
            provider="serper_images",
            slot={"kind": "image", "role": "subject"},
        )
        == "pastry plate pexels"
    )


def test_gemini_query_rewrite_is_allowed_for_still_and_subject_video_slots() -> None:
    assert _slot_allows_gemini_query_rewrite({"kind": "image", "role": "subject"})
    assert _slot_allows_gemini_query_rewrite({"kind": "video", "role": "subject"})
    assert not _slot_allows_gemini_query_rewrite({"kind": "gif", "role": "reaction"})
    assert not _slot_allows_gemini_query_rewrite({"kind": "video", "role": "background_texture"})
    assert not _slot_allows_gemini_query_rewrite({"kind": "image", "role": "warning_sticker"})


def test_sanitize_rewritten_provider_query_keeps_broad_two_or_three_word_broll() -> None:
    assert _sanitize_rewritten_provider_query("Beautiful aesthetic vertical video of coffee pour in cafe") == (
        "coffee pour cafe"
    )
    assert _sanitize_rewritten_provider_query("AI brain animation") == ""
    assert _sanitize_rewritten_provider_query("coffee") == ""


def test_gemini_query_rewrite_returns_sanitized_broad_query() -> None:
    class FakeGemini:
        async def generate_structured(self, *, prompt, response_model, model):  # noqa: ANN001
            assert response_model is MediaQueryRewriteDecision
            assert model == "gemini-test"
            assert "Return exactly one broad concrete b-roll query" in prompt
            assert "How Do People Drink Lattes" in prompt
            return MediaQueryRewriteDecision(rewritten_query="coffee pour cafe")

    item = ScenePipelineItem(
        post_id="post1",
        subreddit="loseit",
        title="How Do People Drink Lattes and Eat Pastries Regularly",
        status="pass",
        audio_path="",
        alignment={},
        semantic_fragments={},
        timed_fragments=[],
        scene_plan=None,
        timed_scenes=[],
        validator_errors=[],
        validator_warnings=[],
        attempts=1,
        from_cache=False,
        cache_path="",
    )
    errors: list[str] = []

    query = asyncio.run(
        _gemini_rewrite_query_for_slot(
            gemini=FakeGemini(),
            item=item,
            scene={"scene_id": 7, "voiceover_fragment": "latte and pastry scene"},
            slot={"kind": "video", "role": "subject", "search_query_en": "almond milk carton"},
            current_query="almond milk carton",
            candidates=[
                MediaCandidate(
                    candidate_id="P01",
                    provider="pinterest",
                    query="almond milk carton",
                    title="How to Make Almond Milk",
                    media_url="https://v1.pinimg.com/videos/iht/hls/milk.m3u8",
                    metadata={"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/milk.m3u8"},
                )
            ],
            model="gemini-test",
            errors=errors,
        )
    )

    assert query == "coffee pour cafe"
    assert errors == []


def test_resolve_slot_rewrites_once_when_candidates_are_all_bad(monkeypatch, tmp_path) -> None:
    class FakeConnector:
        requires_browser = False
        scope = "test"

        def __init__(self) -> None:
            self.queries: list[str] = []

        async def search(self, *, context, query, limit, screenshot_path, scroll_steps):  # noqa: ANN001
            self.queries.append(query)
            if query == "pastry plate pexels":
                candidate = MediaCandidate(
                    candidate_id="S02",
                    provider="serper_images",
                    query=query,
                    title="Pastry plate on cafe table",
                    page_url="https://www.pexels.com/photo/pastry-plate-123/",
                    thumbnail_url="https://images.pexels.com/photos/pastry-thumb.jpg",
                    media_url="https://images.pexels.com/photos/pastry.jpg",
                    width=1400,
                    height=1000,
                    position=1,
                    metadata={"domain": "pexels.com"},
                )
            else:
                candidate = MediaCandidate(
                    candidate_id="S01",
                    provider="serper_images",
                    query=query,
                    title="Amazon pastry product listing",
                    page_url="https://www.amazon.com/pastry-product",
                    thumbnail_url="https://example.com/pastry-thumb.jpg",
                    media_url="https://example.com/pastry.jpg",
                    width=1400,
                    height=1000,
                    position=1,
                    metadata={"domain": "amazon.com"},
                )
            return MediaSearchResult(
                provider="serper_images",
                query=query,
                candidates=[candidate],
                screenshot_path=str(screenshot_path),
                errors=[],
                metadata={},
            )

    class FakeGemini:
        async def generate_structured(self, *, prompt, response_model, model):  # noqa: ANN001
            assert response_model is MediaQueryRewriteDecision
            assert "commerce_or_low_trust_asset" in prompt
            return MediaQueryRewriteDecision(rewritten_query="pastry plate")

    fake_connector = FakeConnector()
    monkeypatch.setattr(
        "reddit2video.nodes.media_resolver.connector_for_provider",
        lambda *args, **kwargs: fake_connector,
    )

    item = ScenePipelineItem(
        post_id="post1",
        subreddit="loseit",
        title="How Do People Drink Lattes and Eat Pastries Regularly",
        status="pass",
        audio_path="",
        alignment={},
        semantic_fragments={},
        timed_fragments=[],
        scene_plan={},
        timed_scenes=[],
        validator_errors=[],
        validator_warnings=[],
        attempts=1,
        from_cache=False,
        cache_path="",
    )
    request = MediaResolverNodeRequest(
        scene_batch=ScenePipelineBatch(items=[], fetched_at="now"),
        providers=["serper_images"],
        candidates_per_provider=2,
        selection_mode="heuristic",
        selected_per_slot=1,
    )

    result = asyncio.run(
        MediaResolverNode()._resolve_slot(
            item=item,
            scene={"scene_id": 1, "voiceover_fragment": "pastry scene"},
            slot={
                "asset_id": "storyboard_asset_01",
                "kind": "image",
                "role": "subject",
                "source_strategy": "stock_search",
                "search_query_en": "bad pastry",
                "is_required": True,
            },
            slot_index=1,
            context=None,
            gemini=FakeGemini(),  # type: ignore[arg-type]
            request=request,
            screenshot_root=tmp_path,
            search_cache={},
        )
    )

    assert result["status"] == "pass"
    assert result["gemini_rewrite_attempted"] is True
    assert result["gemini_rewrite_query"] == "pastry plate"
    assert result["query"] == "pastry plate"
    assert fake_connector.queries == ["bad pastry unsplash", "pastry plate pexels"]
    assert result["selected_candidates"][0]["candidate_id"] == "S02"


def test_fallback_query_stays_compact_for_provider_search() -> None:
    assert _fallback_query_for_slot({"kind": "video", "role": "background_texture"}, "too specific") == "too specific"
    assert _fallback_query_for_slot({"kind": "video", "role": "subject"}, "too specific") == "too specific"
    assert _fallback_query_for_slot({"kind": "image", "role": "subject"}, "too specific") == "too specific"


def test_giphy_image_fallback_marks_reaction_intent() -> None:
    assert (
        _giphy_fallback_query_for_image_slot({"kind": "image", "role": "subject"}, "feet on scale")
        == "feet scale reaction"
    )
    assert _giphy_fallback_query_for_image_slot({"kind": "image"}, "funny reaction gif") == "funny reaction gif"


def test_extract_giphy_web_api_key_from_url() -> None:
    url = "https://api.giphy.com/v1/gifs/search?q=cat&api_key=Gc7131jiJuvI7IdN0HZ1D7nh0ow5BU6g"

    assert _extract_giphy_api_key_from_url(url) == "Gc7131jiJuvI7IdN0HZ1D7nh0ow5BU6g"
    assert _extract_giphy_api_key_from_url("https://example.com/?api_key=Gc7131jiJuvI7IdN0HZ1D7nh0ow5BU6g") == ""


def test_giphy_clip_candidate_prefers_source_mp4() -> None:
    candidate = _giphy_candidate_from_raw(
        index=1,
        query="funny cat",
        api_scope="clips",
        item={
            "id": "clip123",
            "type": "video",
            "title": "Funny Cat",
            "url": "https://giphy.com/clips/funny-cat",
            "video": {
                "duration": 8.0,
                "assets": {
                    "360p": {"url": "https://media.giphy.com/clip360.mp4", "width": "640", "height": "360"},
                    "source": {"url": "https://media.giphy.com/source.mp4", "width": "1280", "height": "720"},
                },
            },
            "images": {
                "fixed_width_small": {
                    "url": "https://media.giphy.com/thumb.gif",
                    "width": "200",
                    "height": "113",
                }
            },
        },
    )

    assert candidate.media_url == "https://media.giphy.com/source.mp4"
    assert candidate.thumbnail_url == "https://media.giphy.com/thumb.gif"
    assert candidate.width == 1280
    assert candidate.height == 720
    assert candidate.metadata["api_scope"] == "clips"


def test_giphy_gif_candidate_prefers_original_mp4_with_gif_fallback_metadata() -> None:
    candidate = _giphy_candidate_from_raw(
        index=1,
        query="funny reaction",
        api_scope="gifs",
        item={
            "id": "gif123",
            "type": "gif",
            "title": "Funny Reaction",
            "url": "https://giphy.com/gifs/funny-reaction",
            "images": {
                "original": {
                    "url": "https://media.giphy.com/media/gif123/giphy.gif",
                    "mp4": "https://media.giphy.com/media/gif123/giphy.mp4",
                    "width": "480",
                    "height": "360",
                },
                "preview_gif": {
                    "url": "https://media.giphy.com/media/gif123/preview.gif",
                    "width": "200",
                    "height": "150",
                },
            },
        },
    )

    assert candidate.media_url == "https://media.giphy.com/media/gif123/giphy.mp4"
    assert candidate.thumbnail_url == "https://media.giphy.com/media/gif123/preview.gif"
    assert candidate.metadata["media_rendition_format"] == "mp4"
    assert candidate.metadata["fallback_gif_url"] == "https://media.giphy.com/media/gif123/giphy.gif"


def test_contact_sheet_renders_video_candidates_with_motion_metadata() -> None:
    html = _contact_sheet_html(
        provider="media_pool",
        candidates=[
            MediaCandidate(
                candidate_id="G01",
                provider="giphy",
                query="q",
                title="reaction clip",
                media_url="https://media.giphy.com/media/gif123/giphy.mp4",
                thumbnail_url="https://media.giphy.com/media/gif123/preview.gif",
                metadata={"media_rendition_format": "mp4", "api_scope": "gifs"},
            ),
            MediaCandidate(
                candidate_id="P01",
                provider="pinterest",
                query="q",
                title="still image",
                media_url="https://i.pinimg.com/originals/a/b/c.jpg",
                width=1080,
                height=1920,
            ),
        ],
    )

    assert '<video src="https://media.giphy.com/media/gif123/giphy.mp4"' in html
    assert "autoplay muted loop playsinline" in html
    assert "motion media:mp4" in html
    assert '<img src="https://i.pinimg.com/originals/a/b/c.jpg"' in html


def test_build_slot_query_prefers_english_search_query() -> None:
    query = build_slot_query(
        {
            "search_query_en": "  wellness morning routine   pink   ",
            "visual_prompt": "fallback",
        }
    )

    assert query == "wellness morning routine pink"


def test_iter_media_slots_reports_required_truncation_without_changing_iterator_contract() -> None:
    scene_plan = {
        "scenes": [
            {
                "scene_id": 1,
                "media_slots": [
                    {"asset_id": "hero", "kind": "image", "required": True},
                    {"asset_id": "optional", "kind": "image", "required": False},
                ],
            },
            {
                "scene_id": 2,
                "media_slots": [
                    {"asset_id": "late_required", "kind": "gif", "required": True},
                ],
            },
        ]
    }

    slots = _iter_media_slots(scene_plan, max_slots=1)
    summary = _media_slot_truncation_summary(scene_plan, max_slots=1)

    assert len(slots) == 1
    assert slots[0][0] == 1
    assert slots[0][2]["asset_id"] == "hero"
    assert summary["skipped_slot_count"] == 2
    assert summary["skipped_required_slot_count"] == 1
    assert summary["skipped_required_slots"] == [
        {"slot_index": 3, "scene_id": 2, "asset_id": "late_required", "kind": "gif", "role": None}
    ]


def test_selected_candidates_preserves_requested_order_and_limit() -> None:
    candidates = [
        MediaCandidate(candidate_id="I01", provider="google_images", query="q"),
        MediaCandidate(candidate_id="I02", provider="google_images", query="q"),
        MediaCandidate(candidate_id="I03", provider="google_images", query="q"),
    ]

    selected = _selected_candidates(candidates, ["I03", "missing", "I01"], 2)

    assert [candidate.candidate_id for candidate in selected] == ["I03", "I01"]


def test_decision_candidate_ids_prefers_ranked_publishable_order() -> None:
    decision = MediaSelectorDecision.model_validate(
        {
            "selected_candidate_ids": ["P09"],
            "ranked_candidates": [
                {"candidate_id": "P02", "rank": 2, "publishability_tier": "usable", "total_score_40": 30},
                {"candidate_id": "P01", "rank": 1, "publishability_tier": "reject", "total_score_40": 38},
                {"candidate_id": "G04", "rank": 3, "publishability_tier": "weak", "total_score_40": 24},
            ],
        }
    )

    assert _decision_candidate_ids(decision) == ["P02", "G04"]


def test_fallback_ranked_decision_selects_first_candidate() -> None:
    candidates = [
        MediaCandidate(candidate_id="G01", provider="giphy", query="q", media_url="https://example.com/a.gif"),
        MediaCandidate(candidate_id="P01", provider="pinterest", query="q", media_url="https://example.com/b.jpg"),
    ]

    decision = _fallback_ranked_decision(candidates, reason="boom")

    assert decision.selected_candidate_ids == ["G01"]
    assert decision.ranked_candidates[0].candidate_id == "G01"
    assert decision.warnings == ["boom"]


def test_first_publishable_candidate_skips_lowres_pinterest_thumbnail() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="q",
            title="tiny original",
            media_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=288,
            height=512,
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="q",
            title="original lifestyle photo",
            media_url="https://i.pinimg.com/originals/a/b/d.jpg",
            width=720,
            height=1280,
        ),
    ]

    assert _first_publishable_candidate(candidates).candidate_id == "P02"


def test_first_publishable_candidate_skips_pinterest_heic() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="q",
            title="high-res but unsupported",
            media_url="https://i.pinimg.com/originals/a/b/c.heic",
            width=3000,
            height=3000,
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="q",
            title="vertical jpg",
            media_url="https://i.pinimg.com/originals/a/b/d.jpg",
            width=1080,
            height=1920,
        ),
    ]

    assert _first_publishable_candidate(candidates).candidate_id == "P02"


def test_first_publishable_candidate_skips_pinterest_social_video_titles() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="q",
            title="ASMR camera covering video - YouTube",
            media_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=1080,
            height=1920,
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="q",
            title="coffee table morning scene",
            media_url="https://i.pinimg.com/originals/a/b/d.jpg",
            width=1080,
            height=1920,
        ),
    ]

    assert _first_publishable_candidate(candidates).candidate_id == "P02"


def test_pinterest_motion_video_rejects_creator_social_reels() -> None:
    candidate = MediaCandidate(
        candidate_id="P01",
        provider="pinterest",
        query="q",
        title="Casual wellness reel from creator",
        page_url="https://www.pinterest.com/pin/123/",
        media_url="https://v1.pinimg.com/videos/iht/hls/a/b/c.m3u8",
        thumbnail_url="https://i.pinimg.com/originals/a/b/c.jpg",
        width=720,
        height=1280,
        metadata={
            "api_scope": "videos",
            "video_hls_url": "https://v1.pinimg.com/videos/iht/hls/a/b/c.m3u8",
            "video_width": 720,
            "video_height": 1280,
            "domain": "instagram.com",
            "link": "https://www.instagram.com/example/reel/abc/",
        },
    )

    assert _candidate_quality_rejection_reason(candidate) == "commerce_or_low_trust_asset"


def test_candidate_pool_rejects_social_campaign_video_and_reaction_provider() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="wellness girl casual lifestyle",
            title="Choose yourself #motivation #wellness #fyp",
            media_url="https://v1.pinimg.com/videos/iht/hls/a/b/c.m3u8",
            thumbnail_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=720,
            height=1280,
            metadata={"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/a/b/c.m3u8"},
        ),
        MediaCandidate(
            candidate_id="G01",
            provider="giphy",
            query="confused math lady meme",
            title="Confused Thinking GIF",
            media_url="https://media.giphy.com/media/source.mp4",
            metadata={"media_rendition_format": "mp4"},
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="wellness girl casual lifestyle",
            title="quiet morning walk",
            media_url="https://v1.pinimg.com/videos/iht/hls/d/e/f.m3u8",
            thumbnail_url="https://i.pinimg.com/originals/d/e/f.jpg",
            width=720,
            height=1280,
            metadata={"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/d/e/f.m3u8"},
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "video", "role": "background_texture"}, candidates)

    assert [candidate.candidate_id for candidate in filtered] == ["P02"]
    assert _candidate_quality_rejection_reason(candidates[0]) == "social_caption_campaign_asset"
    assert _candidate_quality_rejection_reason(candidates[1]) == "reaction_gif_provider"


def test_exact_image_candidate_rejects_commerce_and_clipart_sources() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="S01",
            provider="serper_images",
            query="orange slice photo",
            title="Orange Slice PNG Clip Art",
            page_url="https://gallery.yopriceville.com/Free-Clipart-Pictures/Fruit-PNG/Orange_Slice_PNG_Clip_Art",
            media_url="https://gallery.yopriceville.com/orange-slice.png",
            width=1200,
            height=1200,
        ),
        MediaCandidate(
            candidate_id="S02",
            provider="serper_images",
            query="orange slice photo",
            title="orange slice on cutting board",
            page_url="https://images.test/orange",
            media_url="https://images.test/orange.jpg",
            width=1200,
            height=1200,
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "image", "role": "foreground"}, candidates)

    assert [candidate.candidate_id for candidate in filtered] == ["S02"]
    assert _candidate_quality_rejection_reason(candidates[0]) == "clipart_or_stock_graphic_asset"


def test_exact_image_candidate_rejects_watermarked_stock_domains() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="S01",
            provider="serper_images",
            query="woman coffee lifestyle photo",
            title="Young woman with coffee Stock Photo - Alamy",
            page_url="https://www.alamy.com/young-woman-with-coffee-image123.html",
            media_url="https://c8.alamy.com/comp/ABC123/young-woman-with-coffee-ABC123.jpg",
            width=1200,
            height=900,
        ),
        MediaCandidate(
            candidate_id="S03",
            provider="serper_images",
            query="woman coffee lifestyle photo",
            title="Nice Slim Lady Strolling in Park with Coffee in Her Hands",
            page_url="https://elements.envato.com/nice-slim-lady-strolling-in-park-with-coffee-2MAGLVS",
            media_url="https://elements-resized.envatousercontent.com/elements-video-cover-images/preview.jpg",
            width=1200,
            height=900,
            metadata={"source": "Envato", "domain": "elements.envato.com"},
        ),
        MediaCandidate(
            candidate_id="S02",
            provider="serper_images",
            query="woman coffee lifestyle photo",
            title="woman with coffee on cafe street",
            page_url="https://editorial.example/coffee",
            media_url="https://editorial.example/coffee.jpg",
            width=1200,
            height=900,
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "image", "role": "foreground"}, candidates)

    assert [candidate.candidate_id for candidate in filtered] == ["S02"]
    assert _candidate_quality_rejection_reason(candidates[0]) == "commerce_or_low_trust_asset"
    assert _candidate_quality_rejection_reason(candidates[1]) == "commerce_or_low_trust_asset"


def test_exact_image_candidate_rejects_avif_publication_assets() -> None:
    candidate = MediaCandidate(
        candidate_id="S01",
        provider="serper_images",
        query="organic bathroom photo",
        title="organic bathroom photo",
        page_url="https://assets.example/bathroom",
        media_url="https://assets.example/bathroom.png?enc_avif",
        thumbnail_url="https://assets.example/bathroom.avif",
        width=1200,
        height=1600,
    )

    assert _candidate_quality_rejection_reason(candidate) == "unsupported_image_format"


def test_publication_hygiene_rejects_product_and_medical_explainer_assets() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="cheap biohack morning routine",
            title="Add to Cart Stop Motion BetterVits",
            media_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=1080,
            height=1920,
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="sauna heart health data",
            title="ANATOMY of the HEART",
            media_url="https://i.pinimg.com/originals/d/e/f.jpg",
            width=1080,
            height=1920,
        ),
        MediaCandidate(
            candidate_id="P03",
            provider="pinterest",
            query="cold plunge friend sauna",
            title="tag your ice bath buddy",
            media_url="https://i.pinimg.com/originals/g/h/i.jpg",
            width=1080,
            height=1920,
        ),
    ]

    assert [_candidate_quality_rejection_reason(candidate) for candidate in candidates] == [
        "commerce_or_low_trust_asset",
        "render_creator_or_social_asset",
        "render_creator_or_social_asset",
    ]


def test_candidate_pool_rejects_query_title_mismatch_replacement() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="huge latte and croissant on aesthetic cafe table",
            title="Sunroom Ideas with Built In Home Office",
            media_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=1080,
            height=1920,
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="huge latte and croissant on aesthetic cafe table",
            title="coffee and croissant on cafe table",
            media_url="https://i.pinimg.com/originals/a/b/d.jpg",
            width=1080,
            height=1920,
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "image", "role": "foreground"}, candidates)

    assert [candidate.candidate_id for candidate in filtered] == ["P02"]
    assert _candidate_quality_rejection_reason(candidates[0]) == "query_title_mismatch_asset"


def test_candidate_pool_rejects_lowres_quote_card_and_thumbnail_only_pinterest() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="q",
            title="tiny original",
            media_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=540,
            height=960,
            metadata={"image_key": "orig", "available_image_keys": ["orig"]},
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="q",
            title="Inspirational quote poster template",
            media_url="https://i.pinimg.com/originals/a/b/d.jpg",
            width=1080,
            height=1920,
            metadata={"image_key": "orig", "available_image_keys": ["orig"]},
        ),
        MediaCandidate(
            candidate_id="P03",
            provider="pinterest",
            query="q",
            title="doctor-card thumbnail",
            media_url="https://i.pinimg.com/236x/a/b/e.jpg",
            width=236,
            height=419,
            metadata={"image_key": "236x", "available_image_keys": ["236x"]},
        ),
        MediaCandidate(
            candidate_id="P05",
            provider="pinterest",
            query="q",
            title="casual thumbnail only",
            media_url="https://i.pinimg.com/236x/a/b/g.jpg",
            width=236,
            height=419,
            metadata={"image_key": "236x", "available_image_keys": ["236x"]},
        ),
        MediaCandidate(
            candidate_id="P04",
            provider="pinterest",
            query="q",
            title="coffee table morning scene",
            media_url="https://i.pinimg.com/originals/a/b/f.jpg",
            width=1080,
            height=1920,
            metadata={"image_key": "orig", "available_image_keys": ["orig"]},
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "image", "role": "foreground"}, candidates)

    assert [candidate.candidate_id for candidate in filtered] == ["P04"]
    assert _candidate_quality_rejection_reason(candidates[0]).startswith("low_res_pinterest_asset")
    assert _candidate_quality_rejection_reason(candidates[1]) == "text_heavy_or_card_candidate"
    assert _candidate_quality_rejection_reason(candidates[2]) == "doctor_card_candidate"
    assert _candidate_quality_rejection_reason(candidates[3]) == "thumbnail_only_pinterest_asset"


def test_required_selected_candidate_without_media_file_is_rejected() -> None:
    errors: list[str] = []
    selected = _selected_candidates_with_media_files(
        {"required": True},
        [
            MediaCandidate(
                candidate_id="P01",
                provider="pinterest",
                query="q",
                thumbnail_url="https://i.pinimg.com/236x/a/b/c.jpg",
                media_url="",
                width=236,
                height=419,
            )
        ],
        errors,
    )

    assert selected == []
    assert _candidate_media_file_rejection_reason(
        MediaCandidate(candidate_id="P02", provider="pinterest", query="q", media_url="")
    ) == "missing_downloadable_media_file"
    assert _slot_status_for_selection({"required": True}, selected) == "fail"
    assert "Required media slot has no downloadable/local media file." in errors


def test_candidate_pool_for_background_uses_only_motion_video_candidates() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="q",
            title="ambient apartment room photo",
            media_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=1080,
            height=1920,
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="q",
            title="quiet hallway apartment walk",
            media_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=1080,
            height=1920,
            metadata={"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/a/b/c.m3u8"},
        ),
        MediaCandidate(
            candidate_id="G01",
            provider="giphy",
            query="q",
            media_url="https://media.giphy.com/source.mp4",
            metadata={"api_scope": "clips"},
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "video", "role": "background_texture"}, candidates)

    assert [candidate.candidate_id for candidate in filtered] == ["P02"]


def test_candidate_pool_for_subject_video_falls_back_to_clean_stills_when_motion_missing() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="S01",
            provider="serper_images",
            query="coffee croissant cafe table",
            title="coffee croissant cafe table",
            page_url="https://images.test/cafe-table",
            media_url="https://images.test/cafe-table.jpg",
            width=1080,
            height=1620,
        ),
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="coffee croissant cafe table",
            title="good vibes cafe morning",
            media_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=1080,
            height=1920,
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "video", "role": "subject"}, candidates)

    assert [candidate.candidate_id for candidate in filtered] == ["S01"]
    assert _candidate_quality_rejection_reason(candidates[1]) == "render_creator_or_social_asset"


def test_candidate_pool_for_background_rejects_stills_when_motion_missing() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="S01",
            provider="serper_images",
            query="warm sauna room",
            title="warm sauna room bench",
            page_url="https://images.test/sauna-square",
            media_url="https://images.test/sauna-square.jpg",
            width=1200,
            height=900,
        ),
        MediaCandidate(
            candidate_id="S02",
            provider="serper_images",
            query="warm sauna room",
            title="vertical warm sauna room",
            page_url="https://images.test/sauna-vertical",
            media_url="https://images.test/sauna-vertical.jpg",
            width=900,
            height=1400,
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "video", "role": "background_texture"}, candidates)

    assert filtered == []


def test_candidate_pool_for_background_prefers_vertical_motion_video() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="q",
            title="square kitchen video",
            media_url="https://v.test/square.m3u8",
            width=826,
            height=724,
            metadata={"video_hls_url": "https://v.test/square.m3u8", "video_width": 826, "video_height": 724},
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="q",
            title="vertical kitchen window motion",
            media_url="https://v.test/vertical.m3u8",
            width=720,
            height=1280,
            metadata={"video_hls_url": "https://v.test/vertical.m3u8", "video_width": 720, "video_height": 1280},
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "video", "role": "background_texture"}, candidates)

    assert [candidate.candidate_id for candidate in filtered] == ["P02"]


def test_candidate_pool_for_gif_rejects_static_image_candidates() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="q",
            title="static jpg",
            media_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=1080,
            height=1920,
            metadata={"image_key": "orig", "available_image_keys": ["orig"]},
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="q",
            title="looping cafe table motion",
            media_url="https://i.pinimg.com/originals/a/b/d.jpg",
            width=1080,
            height=1920,
            metadata={"image_key": "orig", "available_image_keys": ["orig"], "video_hls_url": "https://v.test/a.m3u8"},
        ),
        MediaCandidate(
            candidate_id="G01",
            provider="giphy",
            query="q",
            title="reaction",
            media_url="https://media.giphy.com/media/giphy.mp4",
            thumbnail_url="https://media.giphy.com/media/preview.gif",
            metadata={"media_rendition_format": "mp4"},
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "gif", "role": "reaction meme"}, candidates)

    assert [candidate.candidate_id for candidate in filtered] == ["P02"]


def test_candidate_pool_rejects_render_only_creator_pinterest_assets() -> None:
    candidates = [
        MediaCandidate(
            candidate_id="P01",
            provider="pinterest",
            query="lion mane mushroom photo",
            title="Your Brain's New Best Friend: Medshrum's Lion's Mane",
            media_url="https://i.pinimg.com/originals/a/b/c.jpg",
            width=1080,
            height=1920,
        ),
        MediaCandidate(
            candidate_id="P02",
            provider="pinterest",
            query="lion mane mushroom kitchen photo",
            title="lion mane mushrooms cooking in skillet",
            media_url="https://i.pinimg.com/originals/a/b/d.jpg",
            width=1080,
            height=1920,
        ),
    ]

    filtered = _candidate_pool_for_slot({"kind": "image", "role": "foreground"}, candidates)

    assert [candidate.candidate_id for candidate in filtered] == ["P02"]
    assert _candidate_quality_rejection_reason(candidates[0]) == "render_creator_or_social_asset"


def test_pinterest_api_candidate_prefers_original_image_and_keeps_hls_metadata() -> None:
    candidate = _pinterest_candidate_from_raw(
        index=1,
        query="woman doing crunches",
        item={
            "type": "pin",
            "id": "123",
            "grid_title": "Workout crunches",
            "images": {
                "236x": {"url": "https://i.pinimg.com/236x/a/b/c.jpg", "width": 236, "height": 419},
                "orig": {"url": "https://i.pinimg.com/originals/a/b/c.jpg", "width": 720, "height": 1280},
            },
            "videos": {
                "video_list": {
                    "V_HLSV4": {
                        "url": "https://v1.pinimg.com/videos/iht/hls/a/b/c.m3u8",
                        "width": 720,
                        "height": 1280,
                    }
                }
            },
        },
    )

    assert candidate is not None
    assert candidate.candidate_id == "P01"
    assert candidate.media_url == "https://i.pinimg.com/originals/a/b/c.jpg"
    assert candidate.metadata["video_hls_url"] == "https://v1.pinimg.com/videos/iht/hls/a/b/c.m3u8"


def test_pinterest_api_video_scope_prefers_hls_and_video_dimensions() -> None:
    candidate = _pinterest_candidate_from_raw(
        index=1,
        query="woman doing crunches",
        api_scope="videos",
        item={
            "type": "pin",
            "id": "123",
            "grid_title": "Workout crunches",
            "images": {
                "236x": {"url": "https://i.pinimg.com/236x/a/b/c.jpg", "width": 236, "height": 419},
            },
            "videos": {
                "video_list": {
                    "V_HLSV4": {
                        "url": "https://v1.pinimg.com/videos/iht/hls/a/b/c.m3u8",
                        "width": 720,
                        "height": 1280,
                    }
                }
            },
        },
    )

    assert candidate is not None
    assert candidate.media_url == "https://v1.pinimg.com/videos/iht/hls/a/b/c.m3u8"
    assert candidate.thumbnail_url == "https://i.pinimg.com/236x/a/b/c.jpg"
    assert candidate.width == 720
    assert candidate.height == 1280
    assert _candidate_quality_rejection_reason(candidate) is None
