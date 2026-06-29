from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from reddit2video.models import (
    HtmlLayoutNodeRequest,
    MediaResolverNodeRequest,
    RedditDiscoveryRequest,
    RedditThreadRequest,
    RenderBundleNodeRequest,
    ScenePipelineNodeRequest,
    to_jsonable,
)
from reddit2video.models import VoiceoverScriptNodeRequest
from reddit2video.nodes.base import NodeError
from reddit2video.nodes.html_layout import HtmlLayoutNode
from reddit2video.nodes.media_resolver import MediaResolverNode
from reddit2video.nodes.render_bundle import RenderBundleNode
from reddit2video.nodes.reddit import RedditDiscoveryNode, RedditThreadNode
from reddit2video.nodes.scene_pipeline import ScenePipelineNode
from reddit2video.nodes.voiceover_script import VoiceoverScriptNode
from reddit2video.serialization import (
    html_layout_batch_from_dict,
    reddit_batch_from_dict,
    scene_pipeline_batch_from_dict,
    voiceover_batch_from_dict,
)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv))


async def _amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reddit2video")
    parser.add_argument("--env-file", default=".env", help="Optional dotenv-style file to load.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch-reddit", help="Fetch a Reddit thread as JSON.")
    fetch.add_argument("--url", dest="post_url", help="Reddit post URL.")
    fetch.add_argument("--id", dest="post_id", help="Reddit post id, with or without t3_ prefix.")
    fetch.add_argument("--subreddit", help="Optional subreddit hint.")
    fetch.add_argument("--limit", type=int, default=100, help="Comment limit.")
    fetch.add_argument("--depth", type=int, default=8, help="Comment nesting depth.")
    fetch.add_argument("--sort", default="top", help="Comment sort.")
    fetch.add_argument("--out", default="outputs/thread.json", help="Output JSON path.")

    collect = subparsers.add_parser(
        "collect-reddit",
        help="Discover recent interesting Reddit posts and fetch their comments.",
    )
    collect.add_argument("--posts", type=int, default=20, help="How many threads to return.")
    collect.add_argument("--hours", type=int, default=24, help="Lookback window in hours.")
    collect.add_argument(
        "--topics",
        default="biohacking,wellness,weight loss,fitness,sports",
        help="Comma-separated topic hints for ranking.",
    )
    collect.add_argument(
        "--subreddits",
        default="",
        help="Comma-separated subreddit override. Default uses health/wellness/fitness list.",
    )
    collect.add_argument(
        "--sort-modes",
        default="top,hot,new",
        help="Comma-separated listing sorts to inspect per subreddit.",
    )
    collect.add_argument("--per-subreddit", type=int, default=30, help="Posts to inspect per subreddit/sort.")
    collect.add_argument("--min-score", type=int, default=5)
    collect.add_argument("--min-comments", type=int, default=5)
    collect.add_argument("--comment-limit", type=int, default=100)
    collect.add_argument("--comment-depth", type=int, default=8)
    collect.add_argument("--comment-sort", default="top")
    collect.add_argument("--include-nsfw", action="store_true")
    collect.add_argument("--out", default="outputs/reddit-wellness-24h.json", help="Output JSON path.")

    voiceover = subparsers.add_parser(
        "generate-voiceover",
        help="Generate structured Gemini voiceover scripts for a Reddit batch.",
    )
    voiceover.add_argument("--config", default="generation_config.yaml")
    voiceover.add_argument("--input", default=None, help="Reddit batch JSON path.")
    voiceover.add_argument("--out", default=None, help="Output JSON path.")
    voiceover.add_argument("--period-key", default=None)
    voiceover.add_argument("--validation-retries", type=int, default=None)
    voiceover.add_argument("--concurrency", type=int, default=None)
    voiceover.add_argument("--no-cache", action="store_true")

    scenes = subparsers.add_parser(
        "generate-scenes",
        help="Generate ElevenLabs audio, semantic fragments, and scene/media-slot plans.",
    )
    scenes.add_argument("--config", default="generation_config.yaml")
    scenes.add_argument("--input", default=None, help="Voiceover batch JSON path.")
    scenes.add_argument("--out", default=None, help="Output JSON path.")
    scenes.add_argument("--period-key", default=None)
    scenes.add_argument("--target-scene-count", type=int, default=None)
    scenes.add_argument("--repair-retries", type=int, default=None)
    scenes.add_argument("--concurrency", type=int, default=None)
    scenes.add_argument("--no-cache", action="store_true")

    html_layouts = subparsers.add_parser(
        "generate-html-layouts",
        help="Generate static-girly HTML layouts, QA them with Playwright, and repair layout issues.",
    )
    html_layouts.add_argument("--config", default="generation_config.yaml")
    html_layouts.add_argument("--input", default=None, help="Scene pipeline batch JSON path.")
    html_layouts.add_argument("--out", default=None, help="Output JSON path.")
    html_layouts.add_argument("--out-dir", default=None)
    html_layouts.add_argument("--period-key", default=None)
    html_layouts.add_argument("--repair-retries", type=int, default=None)
    html_layouts.add_argument("--concurrency", type=int, default=None)
    html_layouts.add_argument("--reuse-existing", action="store_true")
    html_layouts.add_argument(
        "--no-repair-if-needed",
        action="store_true",
        help="Skip the visual repair gate and repair whenever deterministic QA reports errors.",
    )
    html_layouts.add_argument("--visual-gate-screenshots", type=int, default=None)
    html_layouts.add_argument("--no-reference-screens", action="store_true")
    html_layouts.add_argument("--min-scenes", type=int, default=None)
    html_layouts.add_argument("--max-scenes", type=int, default=None)
    html_layouts.add_argument("--chrome-path", default=None)

    render_bundle = subparsers.add_parser(
        "prepare-render-bundle",
        help="Prepare gapless visual scene timings, scene screenshots, audio paths, and Remotion data.",
    )
    render_bundle.add_argument("--config", default="generation_config.yaml")
    render_bundle.add_argument("--scene-input", default=None)
    render_bundle.add_argument("--html-input", default=None)
    render_bundle.add_argument("--media-input", default=None)
    render_bundle.add_argument("--word-timing-input", default=None)
    render_bundle.add_argument("--out", default=None)
    render_bundle.add_argument("--period-key", default=None)
    render_bundle.add_argument("--fps", type=int, default=None)
    render_bundle.add_argument("--width", type=int, default=None)
    render_bundle.add_argument("--height", type=int, default=None)
    render_bundle.add_argument("--scene-asset-dir", default=None)
    render_bundle.add_argument("--audio-public-dir", default=None)
    render_bundle.add_argument("--remotion-data-path", default=None)
    render_bundle.add_argument("--no-reuse-existing-assets", action="store_true")
    render_bundle.add_argument("--render-mode", choices=["dom", "screenshot"], default=None)
    render_bundle.add_argument("--chrome-path", default=None)

    media = subparsers.add_parser(
        "resolve-media",
        help="Resolve scene media slots through Playwright search connectors and Gemini visual selection.",
    )
    media.add_argument("--config", default="generation_config.yaml")
    media.add_argument("--input", default=None, help="Scene pipeline batch JSON path.")
    media.add_argument("--out", default=None, help="Output media resolver JSON path.")
    media.add_argument("--period-key", default=None)
    media.add_argument("--providers", default=None, help="Comma-separated providers: giphy,pinterest.")
    media.add_argument("--candidates-per-provider", type=int, default=None)
    media.add_argument("--contact-sheet-size", type=int, default=None)
    media.add_argument("--pinterest-scroll-steps", type=int, default=None)
    media.add_argument("--selection-mode", choices=["gemini", "heuristic", "first"], default=None)
    media.add_argument(
        "--media-selector-fallback-models",
        default=None,
        help="Comma-separated selector models to try on rate-limit errors, before heuristic ranking.",
    )
    media.add_argument("--selected-per-slot", type=int, default=None)
    media.add_argument("--max-slots-per-item", type=int, default=None)
    media.add_argument("--giphy-mode", choices=["auto", "api", "playwright"], default=None)
    media.add_argument("--pinterest-mode", choices=["auto", "api", "playwright"], default=None)
    media.add_argument("--pinterest-request-dump-path", default=None)
    media.add_argument("--pinterest-api-scope", default=None)
    media.add_argument("--no-pinterest-cache-api", action="store_true")
    media.add_argument("--giphy-rating", default=None)
    media.add_argument("--giphy-lang", default=None)
    media.add_argument("--giphy-bundle", default=None)
    media.add_argument("--no-giphy-download-assets", action="store_true")
    media.add_argument("--giphy-download-concurrency", type=int, default=None)
    media.add_argument("--no-giphy-cache-api", action="store_true")
    media.add_argument("--concurrency", type=int, default=None)
    media.add_argument("--no-cache", action="store_true")
    media.add_argument("--out-dir", default=None)
    media.add_argument("--screenshot-dir", default=None)
    media.add_argument("--browser-mode", choices=["playwright", "dolphin"], default=None)
    media.add_argument("--dolphin-profile-id", default=None)
    media.add_argument("--dolphin-local-api-url", default=None)
    media.add_argument("--no-dolphin-fallback", action="store_true")
    media.add_argument("--chrome-path", default=None)

    args = parser.parse_args(argv)
    _load_env_file(Path(args.env_file))

    try:
        if args.command == "fetch-reddit":
            thread = await RedditThreadNode().run(
                RedditThreadRequest(
                    post_id=args.post_id,
                    post_url=args.post_url,
                    subreddit=args.subreddit,
                    comment_limit=args.limit,
                    comment_depth=args.depth,
                    comment_sort=args.sort,
                )
            )
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(to_jsonable(thread), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Fetched {thread.post.id}: {thread.post.title}")
            print(f"Wrote {out_path}")
            return 0

        if args.command == "collect-reddit":
            batch = await RedditDiscoveryNode().run(
                RedditDiscoveryRequest(
                    topics=_split_csv(args.topics),
                    subreddits=_split_csv(args.subreddits),
                    hours=args.hours,
                    post_limit=args.posts,
                    per_subreddit_limit=args.per_subreddit,
                    sort_modes=_split_csv(args.sort_modes),
                    include_nsfw=args.include_nsfw,
                    min_score=args.min_score,
                    min_comments=args.min_comments,
                    comment_limit=args.comment_limit,
                    comment_depth=args.comment_depth,
                    comment_sort=args.comment_sort,
                )
            )
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(to_jsonable(batch), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Collected {len(batch.threads)} Reddit threads from {batch.metadata['candidate_count']} candidates")
            print(f"Wrote {out_path}")
            return 0

        if args.command == "generate-voiceover":
            generation_config = _load_generation_config(Path(args.config))
            node_config = generation_config.get("nodes", {}).get("voiceover_script", {})
            params = node_config.get("params", {})
            input_path = Path(args.input or node_config.get("input_path", "outputs/reddit-wellness-24h.json"))
            output_path = Path(args.out or node_config.get("output_path", "outputs/voiceover-scripts.json"))
            batch_payload = json.loads(input_path.read_text(encoding="utf-8"))
            reddit_batch = reddit_batch_from_dict(batch_payload)
            result = await VoiceoverScriptNode().run(
                VoiceoverScriptNodeRequest(
                    thread_batch=reddit_batch,
                    target_language=params.get("target_language", "Russian"),
                    target_platform=params.get("target_platform", "short-form vertical video"),
                    target_duration_sec=int(params.get("target_duration_sec", 60)),
                    risk_tolerance=params.get("risk_tolerance", "medium"),
                    validation_retries=(
                        args.validation_retries
                        if args.validation_retries is not None
                        else int(node_config.get("validation_retries", 1))
                    ),
                    use_cache=bool(generation_config.get("use_cache", True))
                    and bool(node_config.get("cache", True))
                    and not args.no_cache,
                    cache_dir=str(generation_config.get("cache_dir", "outputs/cache")),
                    period_key=args.period_key,
                    concurrency=(
                        args.concurrency
                        if args.concurrency is not None
                        else int(node_config.get("concurrency", 2))
                    ),
                )
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"Generated {len(result.items)} voiceover scripts "
                f"({result.metadata['cache_hits']} cache hits)"
            )
            print(f"Wrote {output_path}")
            return 0

        if args.command == "generate-scenes":
            generation_config = _load_generation_config(Path(args.config))
            node_config = generation_config.get("nodes", {}).get("scene_pipeline", {})
            params = node_config.get("params", {})
            input_path = Path(args.input or node_config.get("input_path", "outputs/voiceover-scripts.json"))
            output_path = Path(args.out or node_config.get("output_path", "outputs/scene-pipeline.json"))
            batch_payload = json.loads(input_path.read_text(encoding="utf-8"))
            voiceover_batch = voiceover_batch_from_dict(batch_payload)
            result = await ScenePipelineNode().run(
                ScenePipelineNodeRequest(
                    voiceover_batch=voiceover_batch,
                    voice_id=str(node_config.get("voice_id", "XrExE9yKIg1WjnnlVkGX")),
                    voice_name=str(node_config.get("voice_name", "Matilda - Knowledgable, Professional")),
                    target_scene_count=(
                        args.target_scene_count
                        if args.target_scene_count is not None
                        else int(node_config.get("target_scene_count", 22))
                    ),
                    repair_retries=(
                        args.repair_retries
                        if args.repair_retries is not None
                        else int(node_config.get("repair_retries", 1))
                    ),
                    target_duration_sec=int(params.get("target_duration_sec", 60)),
                    style_pack_path=str(node_config.get("style_pack_path", "assets/style_packs/static_girly")),
                    style_library_hint=str(
                        params.get(
                            "style_library_hint",
                            "Girly wellness/biohacking blogger style with pink and sky-blue accents.",
                        )
                    ),
                    use_cache=bool(generation_config.get("use_cache", True))
                    and bool(node_config.get("cache", True))
                    and not args.no_cache,
                    cache_dir=str(generation_config.get("cache_dir", "outputs/cache")),
                    period_key=args.period_key,
                    concurrency=(
                        args.concurrency
                        if args.concurrency is not None
                        else int(node_config.get("concurrency", 2))
                    ),
                )
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"Generated {len(result.items)} scene pipeline items "
                f"({result.metadata['passes']} pass, {result.metadata['fails']} fail, "
                f"{result.metadata['cache_hits']} cache hits)"
            )
            print(f"Wrote {output_path}")
            return 0

        if args.command == "generate-html-layouts":
            generation_config = _load_generation_config(Path(args.config))
            node_config = generation_config.get("nodes", {}).get("html_layout", {})
            input_path = Path(args.input or node_config.get("input_path", "outputs/scene-pipeline.json"))
            output_path = Path(args.out or node_config.get("output_path", "outputs/html-layouts.json"))
            batch_payload = json.loads(input_path.read_text(encoding="utf-8"))
            scene_batch = scene_pipeline_batch_from_dict(batch_payload)
            result = await HtmlLayoutNode().run(
                HtmlLayoutNodeRequest(
                    scene_batch=scene_batch,
                    style_html_path=str(node_config.get("style_html_path", "assets/style_packs/static_girly/index.html")),
                    reference_screens_dir=str(
                        node_config.get("reference_screens_dir", "outputs/html-experiments/reference-screens")
                    ),
                    out_dir=str(args.out_dir or node_config.get("out_dir", "outputs/html-layouts")),
                    period_key=args.period_key,
                    with_reference_screens=bool(node_config.get("with_reference_screens", True))
                    and not args.no_reference_screens,
                    repair_retries=(
                        args.repair_retries
                        if args.repair_retries is not None
                        else int(node_config.get("repair_retries", 1))
                    ),
                    repair_if_needed=bool(node_config.get("repair_if_needed", True))
                    and not args.no_repair_if_needed,
                    visual_gate_max_screenshots=(
                        args.visual_gate_screenshots
                        if args.visual_gate_screenshots is not None
                        else int(node_config.get("visual_gate_max_screenshots", 4))
                    ),
                    min_scene_count=(
                        args.min_scenes if args.min_scenes is not None else int(node_config.get("min_scene_count", 18))
                    ),
                    max_scene_count=(
                        args.max_scenes if args.max_scenes is not None else int(node_config.get("max_scene_count", 23))
                    ),
                    reuse_existing=args.reuse_existing,
                    concurrency=(
                        args.concurrency
                        if args.concurrency is not None
                        else int(node_config.get("concurrency", 1))
                    ),
                    chrome_path=str(
                        args.chrome_path
                        or node_config.get("chrome_path", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                    ),
                )
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"Generated {len(result.items)} HTML layout items "
                f"({result.metadata['passes']} pass, {result.metadata['fails']} fail)"
            )
            print(f"Wrote {output_path}")
            return 0

        if args.command == "prepare-render-bundle":
            generation_config = _load_generation_config(Path(args.config))
            node_config = generation_config.get("nodes", {}).get("render_bundle", {})
            scene_input = Path(args.scene_input or node_config.get("scene_input_path", "outputs/scene-pipeline.json"))
            html_input = Path(args.html_input or node_config.get("html_input_path", "outputs/html-layouts.json"))
            media_input = Path(args.media_input or node_config.get("media_input_path", "outputs/media-resolver.json"))
            word_timing_input = Path(
                args.word_timing_input or node_config.get("word_timing_input_path", "outputs/html-word-timing-experiment.json")
            )
            output_path = Path(args.out or node_config.get("output_path", "outputs/render-bundle.json"))
            scene_batch = scene_pipeline_batch_from_dict(json.loads(scene_input.read_text(encoding="utf-8")))
            html_batch = html_layout_batch_from_dict(json.loads(html_input.read_text(encoding="utf-8")))
            word_timing_payload = (
                json.loads(word_timing_input.read_text(encoding="utf-8")) if word_timing_input.exists() else None
            )
            media_resolver_payload = json.loads(media_input.read_text(encoding="utf-8")) if media_input.exists() else None
            result = await RenderBundleNode().run(
                RenderBundleNodeRequest(
                    scene_batch=scene_batch,
                    html_batch=html_batch,
                    media_resolver_payload=media_resolver_payload,
                    word_timing_payload=word_timing_payload,
                    period_key=args.period_key,
                    fps=args.fps if args.fps is not None else int(node_config.get("fps", 30)),
                    width=args.width if args.width is not None else int(node_config.get("width", 1080)),
                    height=args.height if args.height is not None else int(node_config.get("height", 1920)),
                    scene_asset_dir=str(args.scene_asset_dir or node_config.get("scene_asset_dir", "remotion/public/render-assets")),
                    audio_public_dir=str(args.audio_public_dir or node_config.get("audio_public_dir", "remotion/public/audio")),
                    remotion_data_path=str(
                        args.remotion_data_path or node_config.get("remotion_data_path", "remotion/src/render-bundle.generated.json")
                    ),
                    reuse_existing_assets=not args.no_reuse_existing_assets,
                    render_mode=str(args.render_mode or node_config.get("render_mode", "dom")),
                    chrome_path=str(
                        args.chrome_path
                        or node_config.get("chrome_path", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                    ),
                )
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
            remotion_data_path = str(
                args.remotion_data_path or node_config.get("remotion_data_path", "remotion/src/render-bundle.generated.json")
            )
            print(
                f"Prepared {len(result.items)} render bundle items "
                f"({result.metadata['passes']} pass, {result.metadata['fails']} fail)"
            )
            print(f"Wrote {output_path}")
            print(f"Wrote {remotion_data_path}")
            return 0

        if args.command == "resolve-media":
            generation_config = _load_generation_config(Path(args.config))
            node_config = generation_config.get("nodes", {}).get("media_resolver", {})
            input_path = Path(args.input or node_config.get("input_path", "outputs/scene-pipeline.json"))
            output_path = Path(args.out or node_config.get("output_path", "outputs/media-resolver.json"))
            scene_batch = scene_pipeline_batch_from_dict(json.loads(input_path.read_text(encoding="utf-8")))
            providers = (
                _split_csv(args.providers)
                if args.providers
                else list(node_config.get("providers", ["giphy", "pinterest"]))
            )
            result = await MediaResolverNode().run(
                MediaResolverNodeRequest(
                    scene_batch=scene_batch,
                    providers=providers,
                    candidates_per_provider=(
                        args.candidates_per_provider
                        if args.candidates_per_provider is not None
                        else int(node_config.get("candidates_per_provider", 50))
                    ),
                    contact_sheet_size=(
                        args.contact_sheet_size
                        if args.contact_sheet_size is not None
                        else int(node_config.get("contact_sheet_size", 10))
                    ),
                    pinterest_scroll_steps=(
                        args.pinterest_scroll_steps
                        if args.pinterest_scroll_steps is not None
                        else int(node_config.get("pinterest_scroll_steps", 3))
                    ),
                    selection_mode=str(args.selection_mode or node_config.get("selection_mode", "gemini")),
                    media_selector_fallback_models=(
                        _split_csv(args.media_selector_fallback_models)
                        if args.media_selector_fallback_models
                        else [
                            str(model)
                            for model in node_config.get("media_selector_fallback_models", [])
                            if str(model).strip()
                        ]
                    ),
                    selected_per_slot=(
                        args.selected_per_slot
                        if args.selected_per_slot is not None
                        else int(node_config.get("selected_per_slot", 1))
                    ),
                    max_slots_per_item=(
                        args.max_slots_per_item
                        if args.max_slots_per_item is not None
                        else int(node_config.get("max_slots_per_item", 100))
                    ),
                    giphy_connector_mode=str(args.giphy_mode or node_config.get("giphy_connector_mode", "auto")),
                    pinterest_connector_mode=str(
                        args.pinterest_mode or node_config.get("pinterest_connector_mode", "auto")
                    ),
                    pinterest_request_dump_path=str(
                        args.pinterest_request_dump_path
                        or os.getenv("PINTEREST_REQUEST_DUMP_PATH", "")
                        or node_config.get("pinterest_request_dump_path", "")
                        or ""
                    ),
                    pinterest_api_scope=str(args.pinterest_api_scope or node_config.get("pinterest_api_scope", "auto")),
                    pinterest_cache_api_responses=bool(node_config.get("pinterest_cache_api_responses", True))
                    and not args.no_pinterest_cache_api,
                    giphy_rating=str(args.giphy_rating or node_config.get("giphy_rating", "pg")),
                    giphy_lang=str(args.giphy_lang or node_config.get("giphy_lang", "en")),
                    giphy_bundle=str(args.giphy_bundle or node_config.get("giphy_bundle", "")),
                    giphy_download_assets=bool(node_config.get("giphy_download_assets", True))
                    and not args.no_giphy_download_assets,
                    giphy_download_concurrency=(
                        args.giphy_download_concurrency
                        if args.giphy_download_concurrency is not None
                        else int(node_config.get("giphy_download_concurrency", 8))
                    ),
                    giphy_cache_api_responses=bool(node_config.get("giphy_cache_api_responses", True))
                    and not args.no_giphy_cache_api,
                    use_cache=bool(generation_config.get("use_cache", True))
                    and bool(node_config.get("cache", True))
                    and not args.no_cache,
                    cache_dir=str(generation_config.get("cache_dir", "outputs/cache")),
                    out_dir=str(args.out_dir or node_config.get("out_dir", "outputs/media")),
                    screenshot_dir=str(args.screenshot_dir or node_config.get("screenshot_dir", "outputs/media-screens")),
                    period_key=args.period_key,
                    concurrency=args.concurrency if args.concurrency is not None else int(node_config.get("concurrency", 1)),
                    chrome_path=str(
                        args.chrome_path
                        or node_config.get("chrome_path", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                    ),
                    browser_mode=str(args.browser_mode or node_config.get("browser_mode", "playwright")),
                    dolphin_profile_id=str(
                        args.dolphin_profile_id
                        or os.getenv("DOLPHIN_ANTY_PROFILE_ID", "")
                        or node_config.get("dolphin_profile_id", "")
                        or ""
                    )
                    or None,
                    dolphin_local_api_url=str(
                        args.dolphin_local_api_url
                        or os.getenv("DOLPHIN_ANTY_LOCAL_API_URL", "")
                        or node_config.get("dolphin_local_api_url", "http://127.0.0.1:3001")
                    ),
                    dolphin_fallback_to_playwright=not args.no_dolphin_fallback
                    and bool(node_config.get("dolphin_fallback_to_playwright", True)),
                )
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"Resolved media for {len(result.items)} items "
                f"({result.metadata['passes']} pass, {result.metadata['fails']} fail)"
            )
            print(f"Wrote {output_path}")
            return 0
    except NodeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_generation_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
