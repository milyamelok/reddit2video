from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from reddit2video.dolphin_anty import DolphinAntyError, start_dolphin_browser, stop_dolphin_profile
from reddit2video.gemini import GeminiClient, GeminiClientError
from reddit2video.media_asset_hygiene import (
    publication_asset_hygiene_rejection_reason,
    publication_render_asset_hygiene_rejection_reason,
)
from reddit2video.media_connectors import (
    MediaCandidate,
    MediaSearchResult,
    build_slot_query,
    connector_for_provider,
    provider_hint_for_slot,
    render_candidate_contact_sheets,
)
from reddit2video.media_schema import (
    MediaCandidateScores,
    MediaQueryRewriteDecision,
    MediaSelectorDecision,
    RankedMediaCandidate,
    RejectedMediaCandidate,
)
from reddit2video.models import (
    MediaResolverBatch,
    MediaResolverItem,
    MediaResolverNodeRequest,
    NodeSpec,
    ScenePipelineItem,
    to_jsonable,
)
from reddit2video.nodes.base import AsyncBaseNode
from reddit2video.vertex_image import VertexImageGenerationError, generate_vertex_express_image


ALLOWED_RESOLVER_MEDIA_KINDS = {"image", "gif", "video"}
DISALLOWED_RESOLVER_ROLES = {"warning_sticker", "ui_card", "decorative_accent"}
DISALLOWED_RESOLVER_SOURCE_STRATEGIES = {"existing_library", "template_native"}
PINTEREST_LOWRES_IMAGE_KEYS = {"60x60", "136x136", "136x", "170x", "236x"}
PINTEREST_HIGHRES_IMAGE_KEYS = {"orig", "originals", "736x"}


class MediaResolverNode(AsyncBaseNode[MediaResolverNodeRequest, MediaResolverBatch]):
    spec = NodeSpec(
        step="step-6",
        name="media_resolver",
        description="Resolve scene media slots with Playwright search connectors and Gemini visual selection.",
        mocked=False,
    )

    async def run(self, node_input: MediaResolverNodeRequest) -> MediaResolverBatch:
        period_key = node_input.period_key or _period_from_scene_batch(node_input.scene_batch.metadata)
        cache_root = Path(node_input.cache_dir) / self.spec.name / period_key
        out_root = Path(node_input.out_dir) / period_key
        screenshot_root = Path(node_input.screenshot_dir) / period_key
        cache_root.mkdir(parents=True, exist_ok=True)
        out_root.mkdir(parents=True, exist_ok=True)
        screenshot_root.mkdir(parents=True, exist_ok=True)

        launch_metadata: dict[str, Any] = {}
        browser = None
        playwright = None
        dolphin_profile_id = node_input.dolphin_profile_id
        dolphin_started = False

        try:
            if node_input.browser_mode == "dolphin":
                if not dolphin_profile_id:
                    raise DolphinAntyError("browser_mode=dolphin requires dolphin_profile_id.")
                try:
                    started = await start_dolphin_browser(
                        profile_id=dolphin_profile_id,
                        local_api_url=node_input.dolphin_local_api_url,
                    )
                    browser = started.browser
                    playwright = started.playwright
                    dolphin_started = True
                    launch_metadata = {
                        "browser_mode": "dolphin",
                        "dolphin_profile_id": dolphin_profile_id,
                        "port": started.port,
                    }
                except DolphinAntyError as exc:
                    if not node_input.dolphin_fallback_to_playwright:
                        raise
                    launch_metadata = {
                        "browser_mode": "playwright",
                        "dolphin_requested": True,
                        "dolphin_error": str(exc),
                    }

            if browser is None:
                from playwright.async_api import async_playwright

                playwright = await async_playwright().start()
                browser = await playwright.chromium.launch(
                    headless=True,
                    executable_path=node_input.chrome_path,
                )
                launch_metadata.setdefault("browser_mode", "playwright")

            context = await _new_browser_context(browser, dolphin=launch_metadata.get("browser_mode") == "dolphin")
            gemini = GeminiClient.from_env()
            semaphore = asyncio.Semaphore(max(1, node_input.concurrency))
            used_media_keys: set[str] = set()
            used_media_lock = asyncio.Lock()

            async def guarded(index: int, item: ScenePipelineItem) -> MediaResolverItem:
                async with semaphore:
                    return await self._process_item(
                        index=index,
                        item=item,
                        context=context,
                        gemini=gemini,
                        request=node_input,
                        period_key=period_key,
                        cache_root=cache_root,
                        screenshot_root=screenshot_root,
                        used_media_keys=used_media_keys,
                        used_media_lock=used_media_lock,
                    )

            items = await asyncio.gather(
                *[guarded(index, item) for index, item in enumerate(node_input.scene_batch.items, start=1)]
            )
            await gemini.aclose()
            await context.close()
        finally:
            if browser is not None:
                await browser.close()
            if playwright is not None:
                await playwright.stop()
            if dolphin_started and dolphin_profile_id:
                await stop_dolphin_profile(
                    profile_id=dolphin_profile_id,
                    local_api_url=node_input.dolphin_local_api_url,
                )

        return MediaResolverBatch(
            items=items,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "node": self.spec.name,
                "period_key": period_key,
                "providers": node_input.providers,
                "media_selector_model": node_input.media_selector_model,
                "items": len(items),
                "passes": sum(1 for item in items if item.status == "pass"),
                "fails": sum(1 for item in items if item.status == "fail"),
                **launch_metadata,
            },
        )

    async def _process_item(
        self,
        *,
        index: int,
        item: ScenePipelineItem,
        context: Any,
        gemini: GeminiClient,
        request: MediaResolverNodeRequest,
        period_key: str,
        cache_root: Path,
        screenshot_root: Path,
        used_media_keys: set[str] | None = None,
        used_media_lock: asyncio.Lock | None = None,
    ) -> MediaResolverItem:
        cache_path = cache_root / f"{item.post_id}.json"
        if request.use_cache and cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached["from_cache"] = True
            if used_media_keys is not None:
                cached_item = _media_item_from_dict(cached)
                if used_media_lock is not None:
                    async with used_media_lock:
                        _reserve_cached_item_media_keys(cached_item, used_media_keys)
                else:
                    _reserve_cached_item_media_keys(cached_item, used_media_keys)
                return cached_item
            return _media_item_from_dict(cached)

        provider_errors: list[str] = []
        warnings: list[str] = []
        resolved_slots: list[dict[str, Any]] = []
        truncation_summary: dict[str, Any] = {}
        search_cache: dict[tuple[str, str, str, int, int], MediaSearchResult] = {}

        if item.status != "pass" or not item.scene_plan:
            provider_errors.append(f"Scene item is not resolvable: status={item.status}.")
        else:
            slots = _iter_media_slots(item.scene_plan, max_slots=request.max_slots_per_item)
            truncation_summary = _media_slot_truncation_summary(
                item.scene_plan,
                max_slots=request.max_slots_per_item,
            )
            if truncation_summary:
                warning = _media_slot_truncation_message(truncation_summary)
                warnings.append(warning)
                if truncation_summary["skipped_required_slot_count"]:
                    provider_errors.append(warning)
            query_rewrites_used = 0
            query_rewrite_limit = max(0, int(request.media_query_rewrite_max_slots_per_item))
            for slot_index, scene, slot in slots:
                resolved_slot = await self._resolve_slot(
                    item=item,
                    scene=scene,
                    slot=slot,
                    slot_index=slot_index,
                    context=context,
                    gemini=gemini,
                    request=request,
                    screenshot_root=screenshot_root / item.post_id,
                    search_cache=search_cache,
                    allow_query_rewrite=query_rewrites_used < query_rewrite_limit,
                    used_media_keys=used_media_keys,
                    used_media_lock=used_media_lock,
                )
                if resolved_slot.get("gemini_rewrite_attempted"):
                    query_rewrites_used += 1
                resolved_slots.append(resolved_slot)
            failed_slots = [
                f"scene={slot.get('scene_id')} asset={slot.get('asset_id')}"
                for slot in resolved_slots
                if slot.get("status") == "fail"
            ]
            if failed_slots:
                provider_errors.append(f"Failed media slots: {', '.join(failed_slots[:10])}")
                if len(failed_slots) > 10:
                    provider_errors.append(f"...and {len(failed_slots) - 10} more failed media slots.")
            gemini_query_rewrite_attempted_count = query_rewrites_used
        if item.status != "pass" or not item.scene_plan:
            gemini_query_rewrite_attempted_count = 0

        status = "fail" if provider_errors else "pass"
        result = MediaResolverItem(
            post_id=item.post_id,
            subreddit=item.subreddit,
            title=item.title,
            status=status,
            resolved_slots=resolved_slots,
            provider_errors=provider_errors,
            validator_warnings=warnings,
            from_cache=False,
            cache_path=str(cache_path),
            metadata={
                "index": index,
                "period_key": period_key,
                "resolved_slot_count": len(resolved_slots),
                "selected_asset_count": sum(len(slot.get("selected_candidates", [])) for slot in resolved_slots),
                "gemini_query_rewrite_attempted_count": gemini_query_rewrite_attempted_count,
                **({"slot_truncation": truncation_summary} if item.scene_plan and truncation_summary else {}),
            },
        )
        cache_path.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    async def _resolve_slot(
        self,
        *,
        item: ScenePipelineItem,
        scene: dict[str, Any],
        slot: dict[str, Any],
        slot_index: int,
        context: Any,
        gemini: GeminiClient,
        request: MediaResolverNodeRequest,
        screenshot_root: Path,
        search_cache: dict[tuple[str, str, str, int, int], MediaSearchResult],
        allow_query_rewrite: bool = True,
        used_media_keys: set[str] | None = None,
        used_media_lock: asyncio.Lock | None = None,
    ) -> dict[str, Any]:
        original_slot = dict(slot)
        slot = _normalized_slot_for_resolution(slot)
        query = _slot_search_query(slot)
        scene_id = int(scene.get("scene_id") or 0)
        asset_id = str(slot.get("asset_id") or f"slot_{slot_index:03d}")
        slot_key = f"s{scene_id:03d}_{slot_index:03d}_{_safe_slug(asset_id)}"
        errors: list[str] = []
        search_results: list[MediaSearchResult] = []
        policy_error = _media_policy_error(slot)
        if policy_error:
            return {
                "scene_id": scene_id,
                "asset_id": asset_id,
                "status": "fail",
                "skip_reason": "media_policy_disallowed",
                "query": query,
                "slot": slot,
                **({"original_slot": original_slot} if original_slot != slot else {}),
                "search_results": [],
                "selected_candidates": [],
                "selection": None,
                "errors": [policy_error],
            }

        if _slot_requires_generated_image(slot):
            return await self._resolve_generated_image_slot(
                item=item,
                scene_id=scene_id,
                asset_id=asset_id,
                slot=slot,
                original_slot=original_slot,
                slot_key=slot_key,
                request=request,
                query=query,
            )

        if not _should_resolve_slot(slot, query):
            return {
                "scene_id": scene_id,
                "asset_id": asset_id,
                "status": "skipped",
                "skip_reason": "source_strategy_not_searchable",
                "query": query,
                "slot": slot,
                **({"original_slot": original_slot} if original_slot != slot else {}),
                "search_results": [],
                "selected_candidates": [],
                "selection": None,
                "errors": [],
            }

        providers = _dedupe_providers(provider_hint_for_slot(slot, request.providers))

        async def search_provider_query(
            active_query: str,
            *,
            suffix: str = "",
            provider_list: list[str] | None = None,
        ) -> list[MediaSearchResult]:
            results: list[MediaSearchResult] = []
            for provider in provider_list or providers:
                provider_query = _provider_query_for_provider(active_query, provider=provider, slot=slot)
                try:
                    connector = connector_for_provider(
                        provider,
                        giphy_mode=request.giphy_connector_mode,
                        pinterest_mode=request.pinterest_connector_mode,
                        pinterest_request_dump_path=request.pinterest_request_dump_path,
                        pinterest_api_scope=_pinterest_api_scope_for_slot(slot, request.pinterest_api_scope),
                        pinterest_cache_api_responses=request.pinterest_cache_api_responses,
                        pinterest_cache_dir=Path(request.out_dir) / item.post_id / "pinterest_api",
                        giphy_api_scope=_giphy_api_scope_for_slot(slot, request.giphy_api_scope),
                        giphy_api_key_source=request.giphy_api_key_source,
                        giphy_web_key_cache_path=Path(request.giphy_web_key_cache_path),
                        giphy_rating=request.giphy_rating,
                        giphy_lang=request.giphy_lang,
                        giphy_bundle=request.giphy_bundle,
                        giphy_download_assets=request.giphy_download_assets,
                        giphy_download_concurrency=request.giphy_download_concurrency,
                        giphy_cache_api_responses=request.giphy_cache_api_responses,
                        giphy_asset_dir=Path(request.out_dir) / item.post_id / "giphy_assets",
                        brightdata_zone=request.brightdata_zone,
                        brightdata_size=request.brightdata_size,
                        brightdata_cache_api_responses=request.brightdata_cache_api_responses,
                        brightdata_cache_dir=Path(request.out_dir) / item.post_id / "brightdata_google_images",
                        serper_gl=request.serper_gl,
                        serper_hl=request.serper_hl,
                        serper_cache_api_responses=request.serper_cache_api_responses,
                        serper_cache_dir=Path(request.out_dir) / item.post_id / "serper_images",
                    )
                except ValueError as exc:
                    errors.append(str(exc))
                    continue
                screenshot_path = screenshot_root / f"{slot_key}{suffix}_{provider}.png"
                scroll_steps = request.pinterest_scroll_steps if provider == "pinterest" else 2
                connector_scope = str(getattr(connector, "scope", ""))
                cache_key = (
                    provider,
                    connector_scope,
                    provider_query,
                    int(request.candidates_per_provider),
                    int(scroll_steps),
                )
                result = search_cache.get(cache_key)
                if result is None:
                    search_context = (
                        None
                        if request.selection_mode in {"first", "heuristic"}
                        and not getattr(connector, "requires_browser", True)
                        else context
                    )
                    try:
                        result = await asyncio.wait_for(
                            connector.search(
                                context=search_context,
                                query=provider_query,
                                limit=request.candidates_per_provider,
                                screenshot_path=screenshot_path,
                                scroll_steps=scroll_steps,
                            ),
                            timeout=max(1.0, float(request.media_provider_search_timeout_sec)),
                        )
                    except (asyncio.TimeoutError, TimeoutError):
                        result = MediaSearchResult(
                            provider=provider,
                            query=provider_query,
                            candidates=[],
                            screenshot_path=str(screenshot_path),
                            errors=[
                                f"provider_search_timeout_after_{request.media_provider_search_timeout_sec:g}s"
                            ],
                            metadata={"timeout_sec": request.media_provider_search_timeout_sec},
                        )
                    search_cache[cache_key] = result
                results.append(result)
                errors.extend([f"{provider}: {error}" for error in result.errors])
                if (
                    provider in {"pinterest", "pinterest_api"}
                    and not result.candidates
                    and not _slot_requires_motion_video(slot)
                    and not _slot_requires_animated_media(slot)
                    and not getattr(connector, "requires_browser", True)
                    and provider != "pinterest_api"
                    and str(request.pinterest_connector_mode or "auto").lower() != "api"
                    and context is not None
                ):
                    browser_connector = connector_for_provider(
                        "pinterest_playwright",
                        pinterest_api_scope="pins",
                    )
                    browser_screenshot_path = screenshot_root / f"{slot_key}{suffix}_{provider}_browser.png"
                    browser_cache_key = (
                        "pinterest_playwright",
                        "pins",
                        provider_query,
                        int(request.candidates_per_provider),
                        int(request.pinterest_scroll_steps),
                    )
                    browser_result = search_cache.get(browser_cache_key)
                    if browser_result is None:
                        try:
                            browser_result = await asyncio.wait_for(
                                browser_connector.search(
                                    context=context,
                                    query=provider_query,
                                    limit=request.candidates_per_provider,
                                    screenshot_path=browser_screenshot_path,
                                    scroll_steps=request.pinterest_scroll_steps,
                                ),
                                timeout=max(1.0, float(request.media_provider_search_timeout_sec)),
                            )
                        except (asyncio.TimeoutError, TimeoutError):
                            browser_result = MediaSearchResult(
                                provider="pinterest_playwright",
                                query=provider_query,
                                candidates=[],
                                screenshot_path=str(browser_screenshot_path),
                                errors=[
                                    f"provider_search_timeout_after_{request.media_provider_search_timeout_sec:g}s"
                                ],
                                metadata={"timeout_sec": request.media_provider_search_timeout_sec},
                            )
                        search_cache[browser_cache_key] = browser_result
                    results.append(browser_result)
                    errors.extend([f"pinterest_playwright: {error}" for error in browser_result.errors])
            return results

        search_results.extend(await search_provider_query(query))
        all_candidates = [candidate for result in search_results for candidate in result.candidates]
        fallback_query = ""
        gemini_rewrite_query = ""
        if not all_candidates and _slot_is_required(slot):
            fallback_query = _fallback_query_for_slot(slot, query)
            if fallback_query and fallback_query != query:
                errors.append(f"Primary query returned no candidates; retried fallback query: {fallback_query}.")
                fallback_results = await search_provider_query(fallback_query, suffix="_fallback")
                search_results.extend(fallback_results)
                fallback_candidates = [candidate for result in fallback_results for candidate in result.candidates]
                if fallback_candidates:
                    query = fallback_query
                    all_candidates = [candidate for result in search_results for candidate in result.candidates]
        candidate_pool = _candidate_pool_for_slot(slot, all_candidates)
        gemini_rewrite_attempted = False
        gemini_rewrite_skipped_reason = ""
        if (
            not candidate_pool
            and _slot_is_required(slot)
            and request.media_query_rewrite_enabled
            and _slot_allows_gemini_query_rewrite(slot)
        ):
            if not allow_query_rewrite:
                gemini_rewrite_skipped_reason = "per_item_limit"
                errors.append(
                    f"Gemini query rewrite skipped after "
                    f"{request.media_query_rewrite_max_slots_per_item} attempts for this item."
                )
            else:
                gemini_rewrite_attempted = True
                gemini_rewrite_query = await _gemini_rewrite_query_for_slot(
                    gemini=gemini,
                    item=item,
                    scene=scene,
                    slot=slot,
                    current_query=query,
                    candidates=all_candidates,
                    model=request.media_query_rewrite_model,
                    timeout_sec=request.media_query_rewrite_timeout_sec,
                    errors=errors,
                )
                tried_queries = {query, fallback_query}
                if gemini_rewrite_query and gemini_rewrite_query not in tried_queries:
                    errors.append(f"Gemini rewrote bad media query once: {query} -> {gemini_rewrite_query}.")
                    rewrite_results = await search_provider_query(gemini_rewrite_query, suffix="_gemini_rewrite")
                    search_results.extend(rewrite_results)
                    rewrite_candidates = [candidate for result in rewrite_results for candidate in result.candidates]
                    if rewrite_candidates:
                        query = gemini_rewrite_query
                        all_candidates = [candidate for result in search_results for candidate in result.candidates]
                        candidate_pool = _candidate_pool_for_slot(slot, all_candidates)
        if all_candidates and not candidate_pool and _slot_is_required(slot) and not fallback_query:
            fallback_query = _fallback_query_for_slot(slot, query)
            if fallback_query and fallback_query != query:
                errors.append(
                    f"Primary candidates failed quality gates; retried fallback query: {fallback_query}."
                )
                fallback_results = await search_provider_query(fallback_query, suffix="_fallback")
                search_results.extend(fallback_results)
                fallback_candidates = [candidate for result in fallback_results for candidate in result.candidates]
                if fallback_candidates:
                    query = fallback_query
                    all_candidates = [candidate for result in search_results for candidate in result.candidates]
                    candidate_pool = _candidate_pool_for_slot(slot, all_candidates)
        if (
            not candidate_pool
            and _slot_is_required(slot)
            and not _slot_requires_motion_video(slot)
            and not _slot_requires_animated_media(slot)
            and any(provider.startswith("giphy") for provider in request.providers)
        ):
            giphy_fallback_query = _giphy_fallback_query_for_image_slot(slot, query)
            errors.append(f"Pinterest image fallback produced no usable media; tried Giphy fallback: {giphy_fallback_query}.")
            giphy_results = await search_provider_query(
                giphy_fallback_query,
                suffix="_giphy_fallback",
                provider_list=["giphy"],
            )
            search_results.extend(giphy_results)
            giphy_candidates = [candidate for result in giphy_results for candidate in result.candidates]
            if giphy_candidates:
                query = giphy_fallback_query
                all_candidates = [candidate for result in search_results for candidate in result.candidates]
                candidate_pool = _candidate_pool_for_slot(slot, all_candidates)
        if all_candidates and len(candidate_pool) < len(all_candidates):
            errors.append(
                f"Quality gates rejected {len(all_candidates) - len(candidate_pool)} of "
                f"{len(all_candidates)} media candidates."
            )
        if all_candidates and not candidate_pool:
            if _slot_requires_animated_media(slot):
                qualifier = "required " if _slot_is_required(slot) else ""
                errors.append(f"No animated GIF/video candidates passed quality gates for {qualifier}gif slot.")
            elif _slot_requires_motion_video(slot):
                errors.append("No motion/video candidates passed quality gates for video-only slot.")
            else:
                errors.append("No media candidates passed quality gates.")
        if candidate_pool and used_media_keys is not None:
            if used_media_lock is not None:
                async with used_media_lock:
                    filtered_pool = _unused_candidate_pool(candidate_pool, used_media_keys)
            else:
                filtered_pool = _unused_candidate_pool(candidate_pool, used_media_keys)
            if len(filtered_pool) < len(candidate_pool):
                errors.append(
                    f"Removed {len(candidate_pool) - len(filtered_pool)} already-used media candidates before selection."
                )
                candidate_pool = filtered_pool
        analysis_screenshots: list[str] = []
        if candidate_pool and request.selection_mode == "gemini":
            try:
                analysis_screenshots = await render_candidate_contact_sheets(
                    context=context,
                    provider="media_pool",
                    candidates=candidate_pool,
                    screenshot_root=screenshot_root,
                    stem=f"{slot_key}_rank",
                    sheet_size=request.contact_sheet_size,
                )
            except Exception as exc:
                errors.append(f"contact_sheets_failed:{type(exc).__name__}: {exc}")
        decision = await self._select_candidates(
            item=item,
            scene=scene,
            slot=slot,
            query=query,
            candidates=candidate_pool,
            screenshots=analysis_screenshots or _existing_screenshots(search_results),
            gemini=gemini,
            selected_per_slot=request.selected_per_slot,
            selection_mode=request.selection_mode,
            selector_model=request.media_selector_model,
            selector_fallback_models=request.media_selector_fallback_models,
        )
        selected = _selected_candidates(candidate_pool, _decision_candidate_ids(decision), request.selected_per_slot)
        if not selected and candidate_pool:
            selected = candidate_pool[: request.selected_per_slot]
            decision.warnings.append("Gemini selected no valid candidate ids; used first candidates as fallback.")
        selected = _selected_candidates_with_media_files(slot, selected, errors)
        if used_media_keys is not None and selected:
            if used_media_lock is not None:
                async with used_media_lock:
                    selected = _reserve_unique_selected_candidates(
                        selected,
                        candidates=candidate_pool,
                        used_media_keys=used_media_keys,
                        limit=request.selected_per_slot,
                        errors=errors,
                    )
            else:
                selected = _reserve_unique_selected_candidates(
                    selected,
                    candidates=candidate_pool,
                    used_media_keys=used_media_keys,
                    limit=request.selected_per_slot,
                    errors=errors,
                )
        status = _slot_status_for_selection(slot, selected)

        return {
            "scene_id": scene_id,
            "asset_id": asset_id,
            "status": status,
            "query": query,
            "slot": slot,
            **({"original_slot": original_slot} if original_slot != slot else {}),
            "provider_order": providers,
            "fallback_query": fallback_query,
            "gemini_rewrite_query": gemini_rewrite_query,
            "gemini_rewrite_attempted": gemini_rewrite_attempted,
            "gemini_rewrite_skipped_reason": gemini_rewrite_skipped_reason,
            "raw_candidate_count": len(all_candidates),
            "candidate_pool_count": len(candidate_pool),
            "candidate_pool": [_candidate_to_json(candidate) for candidate in candidate_pool],
            "analysis_screenshots": analysis_screenshots,
            "search_results": [_search_result_to_json(result) for result in search_results],
            "selection": decision.model_dump(mode="json"),
            "selected_candidates": [_candidate_to_json(candidate) for candidate in selected],
            "errors": errors,
        }

    async def _resolve_generated_image_slot(
        self,
        *,
        item: ScenePipelineItem,
        scene_id: int,
        asset_id: str,
        slot: dict[str, Any],
        original_slot: dict[str, Any],
        slot_key: str,
        request: MediaResolverNodeRequest,
        query: str,
    ) -> dict[str, Any]:
        prompt = _generated_image_prompt_for_slot(slot)
        errors: list[str] = []
        selected: list[MediaCandidate] = []
        search_results: list[MediaSearchResult] = []
        status = "skipped"
        if not prompt:
            errors.append("Generated image slot has no prompt.")
        elif not request.ai_image_generation_enabled:
            errors.append("AI image generation is disabled for this resolver run.")
        else:
            output_path = (
                Path(request.out_dir)
                / item.post_id
                / "generated_assets"
                / f"{slot_key}_{_safe_slug(prompt)[:32]}.png"
            )
            try:
                metadata = await generate_vertex_express_image(
                    prompt=prompt,
                    output_path=output_path,
                    model=request.ai_image_model,
                    aspect_ratio=_generated_image_aspect_ratio_for_slot(slot),
                )
                local_path = str(metadata.get("output_path") or output_path.with_suffix(".png"))
                candidate = MediaCandidate(
                    candidate_id="AI01",
                    provider="ai_generated",
                    query=prompt,
                    title=str(slot.get("storyboard_asset", {}).get("asset") or asset_id),
                    page_url="",
                    thumbnail_url=local_path,
                    media_url=local_path,
                    width=None,
                    height=None,
                    position=1,
                    metadata={
                        "local_media_path": local_path,
                        "generated": True,
                        "model": request.ai_image_model,
                        "aspect_ratio": metadata.get("aspect_ratio") or _generated_image_aspect_ratio_for_slot(slot),
                        "endpoint": metadata.get("endpoint"),
                        "mime_type": metadata.get("mime_type"),
                        "usage_metadata": metadata.get("usage_metadata") or {},
                        "response_text": metadata.get("text") or "",
                    },
                )
                selected = [candidate]
                search_results = [
                    MediaSearchResult(
                        provider="ai_generated",
                        query=prompt,
                        candidates=[candidate],
                        screenshot_path="",
                        errors=[],
                        metadata={"source": "vertex_express_image_generation"},
                    )
                ]
            except VertexImageGenerationError as exc:
                errors.append(f"ai_generation_failed:{exc}")
            except Exception as exc:
                errors.append(f"ai_generation_failed:{type(exc).__name__}: {exc}")
        if selected:
            status = "pass"
        elif _slot_is_required(slot):
            status = "fail"
        return {
            "scene_id": scene_id,
            "asset_id": asset_id,
            "status": status,
            "query": prompt or query,
            "slot": slot,
            **({"original_slot": original_slot} if original_slot != slot else {}),
            "provider_order": ["ai_generated"],
            "fallback_query": "",
            "raw_candidate_count": len(selected),
            "candidate_pool_count": len(selected),
            "candidate_pool": [_candidate_to_json(candidate) for candidate in selected],
            "analysis_screenshots": [],
            "search_results": [_search_result_to_json(result) for result in search_results],
            "selection": {
                "selected_candidate_ids": ["AI01"] if selected else [],
                "confidence": 1.0 if selected else 0.0,
                "rationale": "Generated via Vertex Express image model." if selected else "No image generated.",
                "warnings": [],
            },
            "selected_candidates": [_candidate_to_json(candidate) for candidate in selected],
            "errors": errors,
        }

    async def _select_candidates(
        self,
        *,
        item: ScenePipelineItem,
        scene: dict[str, Any],
        slot: dict[str, Any],
        query: str,
        candidates: list[MediaCandidate],
        screenshots: list[str],
        gemini: GeminiClient,
        selected_per_slot: int,
        selection_mode: str = "gemini",
        selector_model: str = "gemini-3-flash-preview",
        selector_fallback_models: list[str] | None = None,
    ) -> MediaSelectorDecision:
        if not candidates:
            return MediaSelectorDecision(
                selected_candidate_ids=[],
                confidence=0.0,
                rationale="No candidates found.",
                warnings=["No candidates were available for visual selection."],
            )
        if selection_mode == "first":
            return _first_candidate_decision(candidates)
        if selection_mode == "heuristic":
            return _fallback_ranked_decision(candidates, reason="selection_mode=heuristic")
        prompt = _build_selector_prompt(
            item=item,
            scene=scene,
            slot=slot,
            query=query,
            candidates=candidates,
            selected_per_slot=selected_per_slot,
        )
        models = [selector_model] + _selector_fallback_models(selector_model, selector_fallback_models)
        tried_rate_limit_fallback = False
        last_exc: Exception | None = None
        for index, active_model in enumerate(models):
            try:
                decision = await gemini.generate_structured_multimodal(
                    prompt=prompt,
                    image_paths=screenshots[:10],
                    response_model=MediaSelectorDecision,
                    model=active_model,
                )
                if tried_rate_limit_fallback:
                    decision.warnings.append(f"Selector model fallback used: {selector_model} -> {active_model}")
                return decision
            except (GeminiClientError, ValidationError, Exception) as exc:
                last_exc = exc
                if _looks_like_rate_limit_error(exc) and index + 1 < len(models):
                    tried_rate_limit_fallback = True
                    continue
                break
        assert last_exc is not None
        return _fallback_ranked_decision(candidates, reason=f"{type(last_exc).__name__}: {last_exc}")


def _selector_fallback_models(primary_model: str, configured_models: list[str] | None = None) -> list[str]:
    env_models = _split_model_list(os.getenv("REDDIT2VIDEO_MEDIA_SELECTOR_FALLBACK_MODELS", ""))
    models = [*(configured_models or []), *env_models]
    if not models and _is_gpt_oss_120b_model(primary_model):
        models = [_default_gpt_oss_120b_fallback_model()]
    return _dedupe_model_list([model for model in models if model and model != primary_model])


async def _gemini_rewrite_query_for_slot(
    *,
    gemini: GeminiClient,
    item: ScenePipelineItem,
    scene: dict[str, Any],
    slot: dict[str, Any],
    current_query: str,
    candidates: list[MediaCandidate],
    model: str,
    errors: list[str],
    timeout_sec: float = 20.0,
) -> str:
    prompt = _build_query_rewrite_prompt(item=item, scene=scene, slot=slot, current_query=current_query, candidates=candidates)
    try:
        decision = await asyncio.wait_for(
            gemini.generate_structured(
                prompt=prompt,
                response_model=MediaQueryRewriteDecision,
                model=model,
            ),
            timeout=max(1.0, float(timeout_sec)),
        )
    except TimeoutError as exc:
        errors.append(f"gemini_query_rewrite_failed:TimeoutError after {timeout_sec:g}s")
        return ""
    except (GeminiClientError, ValidationError, Exception) as exc:
        errors.append(f"gemini_query_rewrite_failed:{type(exc).__name__}: {exc}")
        return ""
    query = _sanitize_rewritten_provider_query(decision.rewritten_query)
    if not query:
        errors.append("Gemini query rewrite returned no usable provider query.")
        return ""
    if query == _compact_provider_query(current_query):
        errors.append(f"Gemini query rewrite repeated the current query: {query}.")
        return ""
    return query


def _build_query_rewrite_prompt(
    *,
    item: ScenePipelineItem,
    scene: dict[str, Any],
    slot: dict[str, Any],
    current_query: str,
    candidates: list[MediaCandidate],
) -> str:
    rejected_examples = []
    for candidate in candidates[:18]:
        metadata = candidate.metadata or {}
        rejected_examples.append(
            {
                "title": candidate.title,
                "domain": metadata.get("domain") or "",
                "page_url": candidate.page_url,
                "rejection_reason": _candidate_quality_rejection_reason(candidate, slot=slot) or "not_rejected",
            }
        )
    payload = {
        "video_title": item.title,
        "subreddit": item.subreddit,
        "scene": {
            "scene_id": scene.get("scene_id"),
            "voiceover_fragment": scene.get("voiceover_fragment"),
            "screen_rows": scene.get("screen_rows"),
        },
        "slot": {
            "kind": slot.get("kind"),
            "role": slot.get("role"),
            "visual_prompt": slot.get("visual_prompt"),
            "search_query_en": slot.get("search_query_en"),
        },
        "current_provider_query": current_query,
        "bad_or_rejected_examples": rejected_examples,
    }
    return "\n".join(
        [
            "Rewrite a failed media provider search query for a short-form vertical video.",
            "Return exactly one broad concrete b-roll query in 2 or 3 lowercase English words.",
            "Use common visual nouns/actions only. Prefer real-life b-roll: coffee pour, cafe table, pastry plate, sauna stones, cold plunge, office desk.",
            "Avoid brands, products, affiliate/ecommerce terms, app/listicle intent, recipes/tutorials, memes, podcasts, AI art, anatomy/3D science models, social-media overlays, and the words photo/video/vertical/aesthetic.",
            "Do not preserve a bad overly-specific query if the examples show product, recipe, social, or template results.",
            "Return JSON only.",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


def _sanitize_rewritten_provider_query(query: str) -> str:
    compact = _compact_provider_query(query, max_words=3)
    if not compact or len(compact.split()) < 2:
        return ""
    if _matches_bad_rewrite_query(compact):
        return ""
    return compact


def _matches_bad_rewrite_query(query: str) -> bool:
    return bool(
        re.search(
            r"\b(?:app|apps|recipe|tutorial|podcast|meme|ai|art|brain|heart|anatomy|3d|model|brand|product|wrench|crystal)\b",
            query,
            flags=re.IGNORECASE,
        )
    )


def _default_gpt_oss_120b_fallback_model() -> str:
    return os.getenv("REDDIT2VIDEO_GPT_OSS_120B_FALLBACK_MODEL", "").strip() or "gemini-3-flash-preview"


def _is_gpt_oss_120b_model(model: str) -> bool:
    normalized = model.lower().replace("_", "-")
    return "gpt-oss-120b" in normalized or normalized.endswith("oss-120b")


def _looks_like_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "429",
            "rate limit",
            "ratelimit",
            "too many requests",
            "resource exhausted",
            "quota exceeded",
        )
    )


def _split_model_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _dedupe_model_list(models: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for model in models:
        key = model.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


async def _new_browser_context(browser: Any, *, dolphin: bool) -> Any:
    if dolphin and getattr(browser, "contexts", None):
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
            for page in context.pages:
                await page.set_viewport_size({"width": 1365, "height": 1600})
            return context
    return await browser.new_context(
        viewport={"width": 1365, "height": 1600},
        device_scale_factor=1,
        ignore_https_errors=True,
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        ),
    )


def _iter_media_slots(scene_plan: dict[str, Any], *, max_slots: int) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    return _collect_media_slots(scene_plan)[: max(0, max_slots)]


def _collect_media_slots(scene_plan: dict[str, Any]) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    result: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for scene in scene_plan.get("scenes", []):
        for slot in scene.get("media_slots", []) or []:
            result.append((len(result) + 1, dict(scene), dict(slot)))
    return result


def _media_slot_truncation_summary(scene_plan: dict[str, Any], *, max_slots: int) -> dict[str, Any]:
    all_slots = _collect_media_slots(scene_plan)
    skipped = all_slots[max(0, max_slots) :]
    if not skipped:
        return {}
    skipped_required = [(slot_index, scene, slot) for slot_index, scene, slot in skipped if _slot_is_required(slot)]
    return {
        "max_slots": max_slots,
        "total_slot_count": len(all_slots),
        "resolved_slot_count": min(len(all_slots), max(0, max_slots)),
        "skipped_slot_count": len(skipped),
        "skipped_required_slot_count": len(skipped_required),
        "skipped_optional_slot_count": len(skipped) - len(skipped_required),
        "skipped_required_slots": [
            {
                "slot_index": slot_index,
                "scene_id": scene.get("scene_id"),
                "asset_id": slot.get("asset_id"),
                "kind": slot.get("kind"),
                "role": slot.get("role"),
            }
            for slot_index, scene, slot in skipped_required[:20]
        ],
    }


def _media_slot_truncation_message(summary: dict[str, Any]) -> str:
    required_count = int(summary.get("skipped_required_slot_count") or 0)
    prefix = (
        f"max_slots_per_item={summary.get('max_slots')} truncated media slots: "
        f"resolved {summary.get('resolved_slot_count')} of {summary.get('total_slot_count')}; "
        f"skipped {summary.get('skipped_slot_count')}."
    )
    if not required_count:
        return prefix
    details = ", ".join(
        f"scene={slot.get('scene_id')} asset={slot.get('asset_id')}"
        for slot in list(summary.get("skipped_required_slots") or [])[:10]
    )
    if required_count > 10:
        details = f"{details}, ...and {required_count - 10} more"
    return f"{prefix} Skipped {required_count} required slots: {details}."


def _should_resolve_slot(slot: dict[str, Any], query: str) -> bool:
    if not query:
        return False
    strategy = str(slot.get("source_strategy") or "").lower()
    if strategy in {"stock_search", "web_search", "gif_search", "pinterest_search", "google_images", "giphy"}:
        return True
    return bool(slot.get("search_query_en") or slot.get("search_query_ru"))


def _slot_requires_generated_image(slot: dict[str, Any]) -> bool:
    return str(slot.get("source_strategy") or "").lower() == "generated"


def _generated_image_prompt_for_slot(slot: dict[str, Any]) -> str:
    storyboard_asset = slot.get("storyboard_asset") if isinstance(slot.get("storyboard_asset"), dict) else {}
    for value in (
        slot.get("visual_prompt"),
        storyboard_asset.get("ai_image_prompt"),
        storyboard_asset.get("search_query"),
        slot.get("search_query_en"),
        slot.get("search_query_ru"),
        storyboard_asset.get("asset"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _generated_image_aspect_ratio_for_slot(slot: dict[str, Any]) -> str:
    value = str(slot.get("generation_aspect_ratio") or "").strip()
    return value if value in {"1:1", "3:4", "4:3", "9:16", "16:9"} else "4:3"


def _normalized_slot_for_resolution(slot: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(slot)
    role = str(normalized.get("role") or "").lower()
    if role == "background_texture" and str(normalized.get("kind") or "").lower() != "video":
        normalized["kind"] = "video"
        normalized["source_strategy"] = "pinterest_search"
        normalized["normalization_note"] = "background_texture coerced to video for render policy"
    return normalized


def _slot_search_query(slot: dict[str, Any]) -> str:
    query = build_slot_query(slot)
    if not query:
        return query
    if _slot_requires_motion_video(slot):
        query = _clean_pinterest_motion_query(query)
    return _compact_provider_query(query)


def _slot_allows_gemini_query_rewrite(slot: dict[str, Any]) -> bool:
    if _slot_requires_generated_image(slot) or _slot_requires_animated_media(slot):
        return False
    kind = str(slot.get("kind") or "").lower()
    role = str(slot.get("role") or "").lower()
    if kind not in {"image", "video"}:
        return False
    if role == "background_texture":
        return False
    if role in DISALLOWED_RESOLVER_ROLES:
        return False
    return True


def _provider_query_for_provider(query: str, *, provider: str, slot: dict[str, Any]) -> str:
    if _provider_uses_source_quality_still_search(provider) and _slot_allows_source_quality_still_search(slot, query):
        return _source_quality_still_query(query)
    return query


def _provider_uses_source_quality_still_search(provider: str) -> bool:
    normalized = str(provider or "").strip().lower()
    return normalized in {"serper_images", "serper", "serper_dev_images", "serp_dev_images"}


def _slot_allows_source_quality_still_search(slot: dict[str, Any], query: str) -> bool:
    role = str(slot.get("role") or "").lower()
    if role == "background_texture":
        return False
    if str(slot.get("kind") or "").lower() not in {"image", "video"}:
        return False
    lowered = str(query or "").lower()
    positive = {
        "latte",
        "coffee",
        "croissant",
        "pastry",
        "cafe",
        "almond",
        "milk",
        "salad",
        "plate",
        "crumb",
        "cake",
    }
    excluded = {
        "receipt",
        "label",
        "nutrition",
        "syrup",
        "bottle",
        "pilates",
        "fitness",
        "office",
    }
    return any(term in lowered for term in positive) and not any(term in lowered for term in excluded)


def _source_quality_still_query(query: str) -> str:
    lowered = str(query or "").lower()
    if re.search(r"\b(?:pastry|croissant)\b", lowered) and re.search(
        r"\b(?:half|eaten|empty|crumb|crumbs)\b", lowered
    ):
        return "pastry plate pexels"
    provider_token = "pexels" if re.search(r"\b(?:iced|milk|salad|plate|crumb|cake)\b", query, flags=re.I) else "unsplash"
    base = _compact_provider_query(query, max_words=2)
    words = [word for word in base.split() if word != provider_token]
    words = words[:2] or ["cafe"]
    return " ".join([*words, provider_token])


def _clean_pinterest_motion_query(query: str) -> str:
    cleaned = str(query or "").replace("_", " ")
    cleaned = re.sub(r"(?i)\b(?:9:16|portrait|vertical|horizontal)\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:stock\s+)?(?:video\s+)?footage\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:b-roll|broll|clip|loop)\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\b(?:stock\s+)?(?:photo|photos|image|images|picture|pictures)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,:-")
    return cleaned or "wellness lifestyle"


def _fallback_query_for_slot(slot: dict[str, Any], query: str) -> str:
    kind = str(slot.get("kind") or "").lower()
    base = _fallback_query_base(slot, query)
    if kind == "gif":
        return _compact_provider_query(_append_query_terms(base, "reaction"))
    return _compact_provider_query(base)


def _fallback_query_base(slot: dict[str, Any], query: str) -> str:
    storyboard_asset = slot.get("storyboard_asset") if isinstance(slot.get("storyboard_asset"), dict) else {}
    for value in (
        query,
        slot.get("search_query_en"),
        storyboard_asset.get("search_query"),
        slot.get("visual_prompt"),
        storyboard_asset.get("asset"),
        slot.get("role"),
    ):
        text = _clean_pinterest_motion_query(str(value or ""))
        if text and text.lower() not in {"wellness girl casual lifestyle", "wellness girl casual lifestyle photo"}:
            return text
    role = str(slot.get("role") or "").replace("_", " ").strip()
    kind = str(slot.get("kind") or "").replace("_", " ").strip()
    return " ".join(part for part in (role, kind, "lifestyle") if part).strip() or "casual lifestyle"


_PROVIDER_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "aesthetic",
    "at",
    "background",
    "beautiful",
    "big",
    "block",
    "broll",
    "calorie",
    "casual",
    "carton",
    "clean",
    "clip",
    "clips",
    "close",
    "closeup",
    "completely",
    "counter",
    "counting",
    "footage",
    "for",
    "free",
    "full",
    "girl",
    "girls",
    "healthy",
    "holding",
    "horizontal",
    "huge",
    "image",
    "images",
    "in",
    "lifestyle",
    "loop",
    "motion",
    "of",
    "on",
    "person",
    "pastel",
    "plastic",
    "photo",
    "photos",
    "picture",
    "pictures",
    "portrait",
    "small",
    "soft",
    "stock",
    "subject",
    "sugar",
    "texture",
    "the",
    "thin",
    "to",
    "up",
    "vertical",
    "video",
    "videos",
    "wellness",
    "with",
    "woman",
    "women",
}


def _compact_provider_query(query: str, *, max_words: int = 3) -> str:
    text = re.sub(r"[_/|+]+", " ", str(query or "").lower())
    text = re.sub(r"(?i)\b(?:9:16|b-roll|broll|stock|vertical|horizontal|portrait)\b", " ", text)
    tokens = re.findall(r"[a-zа-яё0-9]+", text, flags=re.IGNORECASE)
    compact: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        token = token.lower()
        if token in _PROVIDER_QUERY_STOPWORDS or len(token) < 3 or token.isdigit():
            continue
        if token in seen:
            continue
        seen.add(token)
        compact.append(token)
        if len(compact) >= max(1, max_words):
            break
    if compact:
        return " ".join(compact)
    fallback = [token.lower() for token in tokens if len(token) >= 3 and not token.isdigit()]
    return " ".join(fallback[: max(1, max_words)]) or "lifestyle"


def _append_query_terms(base: str, terms: str) -> str:
    base = re.sub(r"\s+", " ", str(base or "")).strip()
    terms = re.sub(r"\s+", " ", str(terms or "")).strip()
    lowered = base.lower()
    suffix = " ".join(term for term in terms.split() if term.lower() not in lowered)
    return " ".join(part for part in (base, suffix) if part).strip()


def _giphy_fallback_query_for_image_slot(slot: dict[str, Any], query: str) -> str:
    base = query.strip() or build_slot_query(slot) or "wellness reaction"
    lowered = base.lower()
    if any(marker in lowered for marker in ("gif", "reaction", "meme")):
        return _compact_provider_query(base)
    return _compact_provider_query(_append_query_terms(base, "reaction"))


def _pinterest_api_scope_for_slot(slot: dict[str, Any], configured_scope: str) -> str:
    scope = (configured_scope or "auto").strip().lower()
    if scope and scope != "auto":
        return scope
    haystack = " ".join(
        str(slot.get(key) or "").lower()
        for key in ("kind", "role", "source_strategy", "search_query_en", "search_query_ru")
    )
    if "background_texture" in haystack:
        return "videos"
    if any(marker in haystack for marker in ("video", "clip", "gif", "motion")):
        return "videos"
    return "pins"


def _giphy_api_scope_for_slot(slot: dict[str, Any], configured_scope: str) -> str:
    scope = (configured_scope or "auto").strip().lower()
    if scope and scope != "auto":
        return scope
    haystack = " ".join(
        str(slot.get(key) or "").lower()
        for key in ("kind", "role", "source_strategy", "search_query_en", "search_query_ru", "asset_id")
    )
    if "background_texture" in haystack:
        return "clips"
    if any(marker in haystack for marker in ("video", "clip", "reaction", "meme")):
        return "clips,gifs"
    return "gifs"


def _media_policy_error(slot: dict[str, Any]) -> str | None:
    kind = str(slot.get("kind") or "").lower()
    role = str(slot.get("role") or "").lower()
    strategy = str(slot.get("source_strategy") or "").lower()
    if kind and kind not in ALLOWED_RESOLVER_MEDIA_KINDS:
        return f"Disallowed media kind {kind!r}; only image/gif/video slots are allowed."
    if role in DISALLOWED_RESOLVER_ROLES:
        return f"Disallowed media role {role!r}; use casual photos, GIFs, or meme/reaction videos instead."
    if role == "background_texture" and kind != "video":
        return "Background media must use kind='video'; still images are allowed only as foreground media."
    if strategy in DISALLOWED_RESOLVER_SOURCE_STRATEGIES:
        return (
            f"Disallowed source_strategy {strategy!r}; mock UI, standalone stickers, emoji assets, "
            "and non-searchable decorative media are banned."
        )
    haystack = " ".join(
        str(slot.get(key) or "").lower()
        for key in ("visual_prompt", "search_query_en", "search_query_ru", "crop_hint")
    )
    policy_term = _find_policy_term(haystack)
    if policy_term:
        return (
            f"Disallowed media brief term {policy_term!r}; emoji may be text-only "
            "and interface screenshots are banned."
        )
    return None


def _candidate_pool_for_slot(slot: dict[str, Any], candidates: list[MediaCandidate]) -> list[MediaCandidate]:
    quality_candidates = [candidate for candidate in candidates if _candidate_meets_basic_quality(candidate, slot=slot)]
    if _slot_requires_animated_media(slot):
        return [candidate for candidate in quality_candidates if _candidate_has_animated_media(candidate)]
    if not _slot_requires_motion_video(slot):
        return quality_candidates
    motion_candidates = [candidate for candidate in quality_candidates if _candidate_has_video_motion(candidate)]
    if str(slot.get("role") or "").lower() == "background_texture":
        vertical = [candidate for candidate in motion_candidates if _candidate_vertical_score(candidate) > 0]
        return sorted(vertical, key=_candidate_vertical_score, reverse=True) or motion_candidates
    return motion_candidates or quality_candidates


def _candidate_vertical_score(candidate: MediaCandidate) -> int:
    width, height = _candidate_effective_dimensions(candidate)
    if not width or not height:
        return 0
    if height < width:
        return 0
    ratio = height / max(width, 1)
    if ratio >= 1.55:
        return 3
    if ratio >= 1.25:
        return 2
    return 1


def _slot_requires_animated_media(slot: dict[str, Any]) -> bool:
    return str(slot.get("kind") or "").lower() == "gif"


def _slot_requires_motion_video(slot: dict[str, Any]) -> bool:
    role = str(slot.get("role") or "").lower()
    kind = str(slot.get("kind") or "").lower()
    return role == "background_texture" or kind == "video"


def _candidate_has_video_motion(candidate: MediaCandidate) -> bool:
    metadata = candidate.metadata or {}
    if metadata.get("video_hls_url"):
        return True
    if str(metadata.get("api_scope") or "").lower() == "clips":
        return True
    suffix = _candidate_media_extension(candidate)
    return suffix in {".mp4", ".webm", ".mov"}


def _candidate_has_animated_media(candidate: MediaCandidate) -> bool:
    metadata = candidate.metadata or {}
    if _candidate_has_video_motion(candidate):
        return True
    if str(metadata.get("media_rendition_format") or "").lower() in {"gif", "mp4", "webm", "mov"}:
        return True
    if str(metadata.get("source_tag") or "").lower() == "video":
        return True
    suffix = _candidate_media_extension(candidate)
    if suffix in {".gif", ".mp4", ".webm", ".mov", ".m3u8"}:
        return True
    # Pinterest and some CDNs serve animated loops as WebP. Treat WebP as motion only
    # when provider metadata already indicates a GIF/motion search context.
    if suffix == ".webp":
        haystack = " ".join(
            str(value or "").lower()
            for value in (
                candidate.provider,
                candidate.title,
                candidate.page_url,
                candidate.media_url,
                candidate.thumbnail_url,
                metadata.get("api_scope"),
                metadata.get("source_tag"),
            )
        )
        return any(marker in haystack for marker in ("gif", "giphy", "clip", "video", "motion"))
    return False


def _slot_is_required(slot: dict[str, Any]) -> bool:
    value = slot.get("required", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "optional"}
    return bool(value)


def _slot_status_for_selection(slot: dict[str, Any], selected: list[MediaCandidate]) -> str:
    if selected:
        return "pass"
    return "fail" if _slot_is_required(slot) else "skipped"


def _find_policy_term(text: str) -> str | None:
    for term in (
        "emoji",
        "sticker",
        "икон",
        "icon",
        "fake ui",
        "fake_ui",
        "ui card",
        "interface",
        "интерфейс",
        "dashboard",
        "дашборд",
        "screenshot",
        "screen recording",
        "app screen",
        "app screenshot",
        "social screenshot",
        "reddit screenshot",
        "tiktok screenshot",
        "instagram screenshot",
    ):
        pattern = rf"(?<![a-zа-яё0-9]){re.escape(term)}(?![a-zа-яё0-9])"
        if re.search(pattern, text, flags=re.IGNORECASE):
            return term
    return None


def _search_result_to_json(result: MediaSearchResult) -> dict[str, Any]:
    return {
        "provider": result.provider,
        "query": result.query,
        "screenshot_path": result.screenshot_path,
        "candidate_count": len(result.candidates),
        "candidates": [_candidate_to_json(candidate) for candidate in result.candidates],
        "errors": result.errors,
        "metadata": result.metadata,
    }


def _existing_screenshots(search_results: list[MediaSearchResult]) -> list[str]:
    paths: list[str] = []
    for result in search_results:
        if not result.candidates or not result.screenshot_path:
            continue
        path = Path(result.screenshot_path)
        if path.is_file():
            paths.append(str(path))
    return paths


def _candidate_to_json(candidate: MediaCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "provider": candidate.provider,
        "query": candidate.query,
        "title": candidate.title,
        "page_url": candidate.page_url,
        "thumbnail_url": candidate.thumbnail_url,
        "media_url": candidate.media_url,
        "width": candidate.width,
        "height": candidate.height,
        "position": candidate.position,
        "metadata": candidate.metadata,
    }


def _selected_candidates(
    candidates: list[MediaCandidate],
    selected_ids: list[str],
    limit: int,
) -> list[MediaCandidate]:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    selected: list[MediaCandidate] = []
    for candidate_id in selected_ids:
        candidate = by_id.get(candidate_id)
        if candidate and candidate not in selected:
            selected.append(candidate)
        if len(selected) >= limit:
            return selected
    return selected


def _selected_candidates_with_media_files(
    slot: dict[str, Any],
    candidates: list[MediaCandidate],
    errors: list[str],
) -> list[MediaCandidate]:
    selected: list[MediaCandidate] = []
    for candidate in candidates:
        reason = _candidate_media_file_rejection_reason(candidate)
        if reason:
            errors.append(f"Selected candidate {candidate.candidate_id} rejected: {reason}.")
            continue
        selected.append(candidate)
    if candidates and not selected and _slot_is_required(slot):
        errors.append("Required media slot has no downloadable/local media file.")
    return selected


def _unused_candidate_pool(candidates: list[MediaCandidate], used_media_keys: set[str]) -> list[MediaCandidate]:
    unused = [candidate for candidate in candidates if _candidate_media_dedupe_key(candidate) not in used_media_keys]
    return unused or candidates


def _reserve_unique_selected_candidates(
    selected: list[MediaCandidate],
    *,
    candidates: list[MediaCandidate],
    used_media_keys: set[str],
    limit: int,
    errors: list[str],
) -> list[MediaCandidate]:
    result: list[MediaCandidate] = []
    rejected_duplicate_count = 0
    for candidate in [*selected, *candidates]:
        if len(result) >= limit:
            break
        if candidate in result:
            continue
        key = _candidate_media_dedupe_key(candidate)
        if not key:
            result.append(candidate)
            continue
        if key in used_media_keys:
            rejected_duplicate_count += 1
            continue
        used_media_keys.add(key)
        if candidate not in result:
            result.append(candidate)
    if not result and selected:
        fallback = selected[0]
        key = _candidate_media_dedupe_key(fallback)
        if key:
            used_media_keys.add(key)
        result = [fallback]
        errors.append("All selected media candidates were already used; allowed one duplicate as last resort.")
    elif rejected_duplicate_count:
        errors.append(f"Skipped {rejected_duplicate_count} duplicate selected media candidates.")
    return result


def _reserve_cached_item_media_keys(item: MediaResolverItem, used_media_keys: set[str]) -> None:
    for slot in item.resolved_slots:
        for raw_candidate in slot.get("selected_candidates") or []:
            if not isinstance(raw_candidate, dict):
                continue
            try:
                candidate = MediaCandidate(**raw_candidate)
            except Exception:
                continue
            key = _candidate_media_dedupe_key(candidate)
            if key:
                used_media_keys.add(key)


def _candidate_media_dedupe_key(candidate: MediaCandidate) -> str:
    metadata = candidate.metadata or {}
    for value in (
        candidate.media_url,
        metadata.get("video_hls_url"),
        candidate.thumbnail_url,
        candidate.page_url,
        metadata.get("pin_id"),
        metadata.get("giphy_id"),
    ):
        if isinstance(value, str) and value.strip():
            return _canonical_media_url(value)
    return ""


def _canonical_media_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path}".rstrip("/")
    return str(value or "").strip().lower()


def _decision_candidate_ids(decision: MediaSelectorDecision) -> list[str]:
    if decision.ranked_candidates:
        ranked = sorted(
            decision.ranked_candidates,
            key=lambda item: (
                item.rank if item.rank > 0 else 9999,
                -item.total_score_40,
            ),
        )
        ids = [
            item.candidate_id
            for item in ranked
            if item.candidate_id and item.publishability_tier in {"strong", "usable", "weak"}
        ]
        if ids:
            return ids
    return list(decision.selected_candidate_ids)


def _fallback_ranked_decision(candidates: list[MediaCandidate], *, reason: str) -> MediaSelectorDecision:
    ranked: list[RankedMediaCandidate] = []
    rejected: list[RejectedMediaCandidate] = []
    for rank, candidate in enumerate(candidates[:20], start=1):
        score = _heuristic_candidate_score(candidate)
        tier = "usable" if rank <= 3 else "weak"
        ranked.append(
            RankedMediaCandidate(
                candidate_id=candidate.candidate_id,
                rank=rank,
                use_case="primary" if rank == 1 else "backup",
                publishability_tier=tier,
                total_score_40=score,
                why_selected="Fallback ranking by provider position because Gemini selection failed.",
                scores=MediaCandidateScores(
                    readability=4 if candidate.thumbnail_url or candidate.media_url else 2,
                    scene_relevance=3,
                    stance_clarity=2,
                    emotional_charge=3 if candidate.provider == "giphy" else 2,
                    meme_or_cultural_value=4 if candidate.provider == "giphy" else 2,
                    cropability=3,
                    motion_potential=4 if candidate.provider == "giphy" else 1,
                    platform_safety=3,
                ),
                crop_instruction="Use as a centered crop; verify readability manually before publishing.",
                animation_instruction="Simple zoom-in or pop-in.",
                risk_note="Gemini visual ranking was unavailable; this is a mechanical fallback.",
            )
        )
    for candidate in candidates[20:]:
        rejected.append(
            RejectedMediaCandidate(
                candidate_id=candidate.candidate_id,
                reason="Not evaluated in fallback ranking because candidate pool exceeded 20 items.",
            )
        )
    selected_ids = [ranked[0].candidate_id] if ranked else []
    return MediaSelectorDecision(
        verdict="select" if selected_ids else "no_good_candidate",
        selected_candidate_ids=selected_ids,
        ranked_candidates=ranked,
        rejected_reasons=rejected,
        confidence=0.15 if selected_ids else 0.0,
        rationale="Gemini ranking failed; used deterministic provider-order fallback.",
        warnings=[reason],
        notes_for_editor="Manual review recommended because fallback did not inspect visual screenshots semantically.",
    )


def _first_candidate_decision(candidates: list[MediaCandidate]) -> MediaSelectorDecision:
    first = _first_publishable_candidate(candidates)
    return MediaSelectorDecision(
        verdict="select",
        selected_candidate_ids=[first.candidate_id],
        ranked_candidates=[
            RankedMediaCandidate(
                candidate_id=first.candidate_id,
                rank=1,
                use_case="primary",
                publishability_tier="usable",
                total_score_40=_heuristic_candidate_score(first),
                why_selected="First-result mode: trusting provider search ranking, no Gemini validation.",
                scores=MediaCandidateScores(
                    readability=3 if first.thumbnail_url or first.media_url else 2,
                    scene_relevance=3,
                    stance_clarity=2,
                    emotional_charge=3 if first.provider == "giphy" else 2,
                    meme_or_cultural_value=4 if first.provider == "giphy" else 2,
                    cropability=3,
                    motion_potential=4 if first.provider == "giphy" else 1,
                    platform_safety=3,
                ),
                crop_instruction="Use the first provider-ranked candidate that passes basic quality checks.",
                animation_instruction="Simple pop-in or slow zoom.",
                risk_note="No visual semantic validation was performed.",
            )
        ],
        confidence=0.2,
        rationale="Selected the first provider-ranked candidate that passed deterministic quality checks.",
        warnings=["selection_mode=first_quality"],
        notes_for_editor="Fast mode: quality depends on provider query/ranking; obvious thumbnails and UI screenshots are skipped.",
    )


def _first_publishable_candidate(candidates: list[MediaCandidate]) -> MediaCandidate:
    for candidate in candidates:
        if _candidate_meets_basic_quality(candidate):
            return candidate
    return max(candidates, key=_candidate_quality_score)


def _candidate_meets_basic_quality(candidate: MediaCandidate, *, slot: dict[str, Any] | None = None) -> bool:
    return _candidate_quality_rejection_reason(candidate, slot=slot) is None


def _candidate_quality_rejection_reason(
    candidate: MediaCandidate,
    *,
    slot: dict[str, Any] | None = None,
) -> str | None:
    media_reason = _candidate_media_file_rejection_reason(candidate)
    if media_reason:
        return media_reason
    if _candidate_media_extension(candidate) in {".avif", ".heic", ".heif"}:
        return "unsupported_image_format"
    text_reason = _candidate_text_rejection_reason(candidate)
    if text_reason:
        return text_reason
    hygiene_reason = publication_render_asset_hygiene_rejection_reason(candidate, slot=slot)
    if hygiene_reason:
        return hygiene_reason
    if candidate.provider in {"brightdata_google_images", "serper_images", "wikimedia_commons"}:
        return _exact_image_candidate_quality_rejection_reason(candidate)
    if candidate.provider == "pinterest":
        return _pinterest_candidate_quality_rejection_reason(candidate)
    return None


def _candidate_media_file_rejection_reason(candidate: MediaCandidate) -> str | None:
    if _candidate_existing_local_media_path(candidate):
        return None
    metadata = candidate.metadata or {}
    hls_url = str(metadata.get("video_hls_url") or "")
    if hls_url.endswith(".m3u8"):
        return None
    if (
        candidate.provider in {"brightdata_google_images", "serper_images"}
        and urlparse(candidate.media_url).scheme.lower() in {"http", "https"}
    ):
        return None
    if _media_url_looks_downloadable(candidate.media_url):
        return None
    return "missing_downloadable_media_file"


def _candidate_existing_local_media_path(candidate: MediaCandidate) -> str:
    metadata = candidate.metadata or {}
    asset_cache = metadata.get("asset_cache") if isinstance(metadata.get("asset_cache"), dict) else {}
    for value in (
        metadata.get("local_media_path"),
        asset_cache.get("highres_path"),
        metadata.get("local_thumbnail_path"),
        asset_cache.get("lowres_path"),
    ):
        if isinstance(value, str) and value:
            path = Path(value)
            if path.is_file() and path.stat().st_size > 0:
                return str(path)
    return ""


def _media_url_looks_downloadable(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme.lower() in {"http", "https"}:
        return _media_url_suffix(url) in {".gif", ".mp4", ".webm", ".mov", ".jpg", ".jpeg", ".png", ".webp", ".m3u8"}
    path = Path(url)
    return path.is_file() and path.stat().st_size > 0


def _pinterest_candidate_quality_rejection_reason(candidate: MediaCandidate) -> str | None:
    width, height = _candidate_effective_dimensions(candidate)
    if not width or not height:
        return "missing_pinterest_dimensions"
    if (
        not _candidate_has_video_motion(candidate)
        and _is_lowres_pinterest_thumbnail(candidate)
        and not _pinterest_has_highres_source(candidate)
    ):
        return "thumbnail_only_pinterest_asset"
    min_side = min(width, height)
    required_min_side = _pinterest_min_side_px()
    if min_side < required_min_side:
        return f"low_res_pinterest_asset_min_side_{min_side}_below_{required_min_side}"
    return None


def _exact_image_candidate_quality_rejection_reason(candidate: MediaCandidate) -> str | None:
    width, height = _candidate_effective_dimensions(candidate)
    if not width or not height:
        return "missing_exact_image_dimensions"
    min_side = min(width, height)
    required_min_side = _exact_image_min_side_px()
    if min_side < required_min_side:
        return f"low_res_exact_image_min_side_{min_side}_below_{required_min_side}"
    return None


def _exact_image_min_side_px() -> int:
    try:
        return max(1, int(os.getenv("MEDIA_RESOLVER_EXACT_IMAGE_MIN_SIDE_PX", "720")))
    except ValueError:
        return 720


def _candidate_effective_dimensions(candidate: MediaCandidate) -> tuple[int | None, int | None]:
    metadata = candidate.metadata or {}
    if _candidate_has_video_motion(candidate):
        video_width = _int_or_none(metadata.get("video_width"))
        video_height = _int_or_none(metadata.get("video_height"))
        if video_width and video_height:
            return video_width, video_height
    return candidate.width, candidate.height


def _candidate_text_rejection_reason(candidate: MediaCandidate) -> str | None:
    text = _candidate_text_haystack(candidate)
    checks = (
        (
            "doctor_card_candidate",
            r"\b(?:doctor|physician|medical|clinic|healthcare|hospital)[\s_-]*(?:business\s*)?card\b",
        ),
        (
            "interface_or_screenshot_candidate",
            r"\b(?:screenshot|screen\s*shot|app\s*screen|phone\s*screen|iphone\s*screen|"
            r"interface|dashboard|ui\s*kit|user\s*interface|reddit|tweet|twitter|threads\s*post|"
            r"facebook\s*post)\b",
        ),
        (
            "text_heavy_or_card_candidate",
            r"\b(?:quote|quotes|text\s*post|infographic|worksheet|template|poster|flyer|"
            r"business\s*card|id\s*card|flashcard|doctor\s*card|medical\s*card)\b",
        ),
    )
    for reason, pattern in checks:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return reason
    if not _candidate_has_video_motion(candidate) and re.search(
        r"\b(?:instagram|tiktok|youtube|reels?)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return "interface_or_screenshot_candidate"
    return None


def _candidate_text_haystack(candidate: MediaCandidate) -> str:
    metadata = candidate.metadata or {}
    metadata_values: list[str] = []
    for key in ("source_tag", "image_key", "domain", "link", "api_scope"):
        value = metadata.get(key)
        if isinstance(value, (str, int, float)):
            metadata_values.append(str(value))
    available = metadata.get("available_image_keys")
    if isinstance(available, list):
        metadata_values.extend(str(item) for item in available if isinstance(item, (str, int, float)))
    return " ".join(
        str(value or "").lower().replace("_", " ")
        for value in (
            candidate.title,
            candidate.page_url,
            candidate.media_url,
            candidate.thumbnail_url,
            *metadata_values,
        )
    )


def _is_lowres_pinterest_thumbnail(candidate: MediaCandidate) -> bool:
    metadata = candidate.metadata or {}
    image_key = str(metadata.get("image_key") or "").lower()
    if image_key in PINTEREST_LOWRES_IMAGE_KEYS:
        return True
    lowered_urls = " ".join([candidate.media_url.lower(), candidate.thumbnail_url.lower()])
    return any(f"/{key}/" in lowered_urls for key in PINTEREST_LOWRES_IMAGE_KEYS)


def _pinterest_has_highres_source(candidate: MediaCandidate) -> bool:
    metadata = candidate.metadata or {}
    image_key = str(metadata.get("image_key") or "").lower()
    if image_key in PINTEREST_HIGHRES_IMAGE_KEYS:
        return True
    available = metadata.get("available_image_keys")
    if isinstance(available, list):
        return any(str(key).lower() in PINTEREST_HIGHRES_IMAGE_KEYS for key in available)
    lowered_urls = " ".join([candidate.media_url.lower(), candidate.thumbnail_url.lower()])
    return any(f"/{key}/" in lowered_urls for key in PINTEREST_HIGHRES_IMAGE_KEYS)


def _pinterest_min_side_px() -> int:
    try:
        return max(1, int(os.getenv("MEDIA_RESOLVER_PINTEREST_MIN_SIDE_PX", "720")))
    except ValueError:
        return 720


def _media_url_suffix(url: str) -> str:
    return Path(urlparse(url).path).suffix.lower()


def _heuristic_candidate_score(candidate: MediaCandidate) -> int:
    return _candidate_quality_score(candidate)


def _candidate_media_extension(candidate: MediaCandidate) -> str:
    value = str(candidate.media_url or candidate.thumbnail_url or "").lower().split("?", 1)[0]
    raw_value = str(candidate.media_url or candidate.thumbnail_url or "").lower()
    if "enc_avif" in raw_value or "format=avif" in raw_value:
        return ".avif"
    for suffix in (
        ".heic",
        ".heif",
        ".avif",
        ".webp",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".mp4",
        ".webm",
        ".mov",
        ".m3u8",
    ):
        if value.endswith(suffix):
            return suffix
    return ""


def _candidate_quality_score(candidate: MediaCandidate) -> int:
    score = 18
    if _candidate_media_extension(candidate) in {".heic", ".heif"}:
        score -= 30
    if candidate.provider == "giphy":
        score += 5
    if candidate.provider == "pinterest":
        score += 2
    width, height = _candidate_effective_dimensions(candidate)
    if width and height:
        ratio = width / max(height, 1)
        area = width * height
        if area >= 900_000:
            score += 8
        elif area >= 500_000:
            score += 5
        elif area >= 250_000:
            score += 2
        else:
            score -= 8
        if 0.45 <= ratio <= 1.35:
            score += 5
        elif 0.35 <= ratio <= 1.8:
            score += 2
        else:
            score -= 5
    else:
        score -= 3
    url = str(candidate.media_url or candidate.thumbnail_url or "").lower()
    if "/originals/" in url:
        score += 10
    elif "/736x/" in url:
        score += 6
    elif "/564x/" in url:
        score += 3
    elif any(part in url for part in ("/236x/", "/170x/", "/136x/", "/60x60/")):
        score -= 10
    metadata = candidate.metadata or {}
    if metadata.get("video_hls_url") or str(metadata.get("api_scope") or "") == "clips":
        score += 6
    if candidate.title:
        score += 2
    lowered = " ".join(
        str(value or "").lower()
        for value in (
            candidate.title,
            candidate.page_url,
            candidate.media_url,
            candidate.thumbnail_url,
        )
    )
    if any(
        term in lowered
        for term in ("screenshot", "dashboard", "interface", "reddit", "instagram", "tiktok", "youtube", "reels")
    ):
        score -= 12
    if any(term in lowered for term in ("watermark", "logo")):
        score -= 5
    return min(score, 30)


def _candidate_quality_flags(candidate: MediaCandidate) -> list[str]:
    flags: list[str] = []
    width, height = _candidate_effective_dimensions(candidate)
    if width and height:
        min_side = min(width, height)
        if candidate.provider == "pinterest" and min_side < _pinterest_min_side_px():
            flags.append(f"short_side_below_{_pinterest_min_side_px()}px")
        if width * height < 500_000:
            flags.append("small_pixel_area")
    else:
        flags.append("missing_dimensions")
    url = str(candidate.media_url or candidate.thumbnail_url or "").lower()
    if any(part in url for part in ("/236x/", "/170x/", "/136x/", "/60x60/")):
        flags.append("thumbnail_url")
    if "/736x/" in url and candidate.provider == "pinterest":
        flags.append("pinterest_736x_resized_candidate_verify_not_upscaled")
    if _candidate_has_video_motion(candidate):
        flags.append("motion_candidate")
    text_reason = _candidate_text_rejection_reason(candidate)
    if text_reason:
        flags.append(text_reason)
    hygiene_reason = publication_render_asset_hygiene_rejection_reason(candidate)
    if hygiene_reason and hygiene_reason not in flags:
        flags.append(hygiene_reason)
    return flags


def _build_selector_prompt(
    *,
    item: ScenePipelineItem,
    scene: dict[str, Any],
    slot: dict[str, Any],
    query: str,
    candidates: list[MediaCandidate],
    selected_per_slot: int,
) -> str:
    candidate_brief = [
        {
            "candidate_id": candidate.candidate_id,
            "provider": candidate.provider,
            "title": candidate.title,
            "page_url": candidate.page_url,
            "media_url": candidate.media_url,
            "width": candidate.width,
            "height": candidate.height,
            "position": candidate.position,
            "effective_width": _candidate_effective_dimensions(candidate)[0],
            "effective_height": _candidate_effective_dimensions(candidate)[1],
            "quality_flags": _candidate_quality_flags(candidate),
        }
        for candidate in candidates
    ]
    spoken_context = _selector_spoken_context(item=item, scene=scene, slot=slot)
    payload = {
        "video_title": item.title,
        "subreddit": item.subreddit,
        "scene": {
            "scene_id": scene.get("scene_id"),
            "scene_tag": scene.get("scene_tag"),
            "attention_job": scene.get("attention_job"),
            "voiceover_fragment": scene.get("voiceover_fragment") or spoken_context.get("scene_spoken_text"),
            "start_sec": scene.get("start_sec") if scene.get("start_sec") is not None else spoken_context.get("scene_start_sec"),
            "end_sec": scene.get("end_sec") if scene.get("end_sec") is not None else spoken_context.get("scene_end_sec"),
            "duration_sec": (
                scene.get("duration_sec")
                if scene.get("duration_sec") is not None
                else spoken_context.get("scene_duration_sec")
            ),
            "screen_rows": scene.get("screen_rows"),
            "visual_density": scene.get("visual_density"),
            "template_hint": scene.get("template_hint"),
            "spoken_context": spoken_context,
        },
        "media_slot": slot,
        "query": query,
        "selected_per_slot": selected_per_slot,
        "candidates": candidate_brief,
    }
    return (
        "You are a visual creative director and ranking editor for short-form vertical wellness/biohacking videos.\n"
        "You receive one or more 3x3 contact-sheet screenshots. Each candidate is labeled by ID, like G01 or P07, "
        "and metadata for the same IDs is provided below.\n\n"
        "Your job is NOT to merely approve or reject one image. Build a ranked media pool for the slot. "
        "Prefer visuals that improve retention, emotion, meme value, shareability, phone readability, and the scene stance. "
        "Literal relevance is useful only when it makes the scene clearer or more watchable.\n\n"
        "Use scene.spoken_context as ground truth for the exact voiceover text and timing of this slot. "
        "The slot_spoken_text is the precise spoken fragment the selected media must support; scene_spoken_text is the broader scene context.\n\n"
        "Style target: girly wellness/biohacking blogger, pink + sky-blue accents, meme-aware, clean enough for vertical video. "
        "Prefer casual lifestyle photos, expressive GIFs, meme/reaction clips, and assets that can survive a 9:16 crop. "
        "Do not select emoji stickers, standalone stickers, fake UI cards, app/interface screenshots, dashboards, or social screenshots. "
        "Emoji is allowed only as part of rendered text, not as a media asset.\n\n"
        "Pinterest quality rule: choose assets that look genuinely high quality on the screenshot, not merely metadata-highres. "
        "Reject or downrank images/videos that are visibly blurry, overcompressed, posterized, pixelated, upscaled from a tiny source, "
        "watermarked, text-card-like, or semantically random. Minimum acceptable Pinterest effective resolution is 720px on the short side, "
        "but a nominal 720p asset should still be rejected if the contact sheet shows compression/upscale artifacts. For videos, judge the "
        "shown mid-frame/poster as the representative visual.\n\n"
        "Scoring rubric: score each ranked candidate from 0 to 5 on readability, scene_relevance, stance_clarity, "
        "emotional_charge, meme_or_cultural_value, cropability, motion_potential, and platform_safety. "
        "Set total_score_40 to the sum. Use publishability_tier: strong, usable, weak, or reject.\n\n"
        "Rank at least the best 10 candidates if that many are visible and usable. If there are many candidates, focus on "
        "the most promising 20 and reject obvious bad fits with short reasons. Do not mark no_good_candidate unless every "
        "candidate is unsafe, unreadable, or useless for the slot. Weak but potentially useful candidates should be ranked as weak, "
        "not omitted.\n\n"
        "selected_candidate_ids must contain the top selected_per_slot IDs from ranked_candidates whose tier is strong or usable. "
        "If only weak candidates exist, you may select the best weak candidate and explain the risk. Do not invent IDs.\n\n"
        "Avoid gore, hateful symbols, sexually explicit content, minors in sensitive contexts, graphic medical scenes, "
        "misleading medical authority vibes, random body before/after imagery, cluttered screenshots, UI/interface screenshots, heavy watermarks, and "
        "celebrity reactions that do not clearly serve the stance.\n\n"
        "Return JSON only matching the provided schema. Use rejected_reasons for bad candidates, better_search_queries for "
        "queries that would likely find stronger assets, and notes_for_editor for crop/motion caveats.\n\n"
        f"INPUT_JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _selector_spoken_context(
    *,
    item: ScenePipelineItem,
    scene: dict[str, Any],
    slot: dict[str, Any],
) -> dict[str, Any]:
    scene_id = _int_or_none(scene.get("scene_id"))
    timed_scene = _timed_scene_for_scene(item, scene_id)
    scene_fragment_ids = _normalize_fragment_ids(scene.get("fragment_ids")) or _normalize_fragment_ids(
        timed_scene.get("fragment_ids")
    )
    slot_fragment_ids = _normalize_fragment_ids(slot.get("source_fragment_ids")) or scene_fragment_ids
    fragments_by_id = {
        fragment_id: fragment
        for fragment in item.timed_fragments
        if isinstance(fragment, dict) and (fragment_id := _int_or_none(fragment.get("fragment_id"))) is not None
    }
    scene_timing = _timing_from_scene_or_fragments(
        scene=scene,
        timed_scene=timed_scene,
        fragment_ids=scene_fragment_ids,
        fragments_by_id=fragments_by_id,
    )
    slot_timing = _timing_from_fragments(slot_fragment_ids, fragments_by_id)
    scene_text = str(scene.get("voiceover_fragment") or "").strip() or _spoken_text(scene_fragment_ids, fragments_by_id)
    slot_text = _spoken_text(slot_fragment_ids, fragments_by_id) or scene_text
    return {
        "slot_fragment_ids": slot_fragment_ids,
        "slot_spoken_text": slot_text,
        "slot_start_sec": slot_timing.get("start_sec"),
        "slot_end_sec": slot_timing.get("end_sec"),
        "slot_duration_sec": slot_timing.get("duration_sec"),
        "scene_fragment_ids": scene_fragment_ids,
        "scene_spoken_text": scene_text,
        "scene_start_sec": scene_timing.get("start_sec"),
        "scene_end_sec": scene_timing.get("end_sec"),
        "scene_duration_sec": scene_timing.get("duration_sec"),
    }


def _timed_scene_for_scene(item: ScenePipelineItem, scene_id: int | None) -> dict[str, Any]:
    if scene_id is None:
        return {}
    for timed_scene in item.timed_scenes:
        if isinstance(timed_scene, dict) and _int_or_none(timed_scene.get("scene_id")) == scene_id:
            return timed_scene
    return {}


def _normalize_fragment_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        parsed = _int_or_none(item)
        if parsed is not None:
            result.append(parsed)
    return result


def _spoken_text(fragment_ids: list[int], fragments_by_id: dict[int, dict[str, Any]]) -> str:
    return " ".join(
        str(fragments_by_id[fragment_id].get("text") or "").strip()
        for fragment_id in fragment_ids
        if fragment_id in fragments_by_id and str(fragments_by_id[fragment_id].get("text") or "").strip()
    ).strip()


def _timing_from_scene_or_fragments(
    *,
    scene: dict[str, Any],
    timed_scene: dict[str, Any],
    fragment_ids: list[int],
    fragments_by_id: dict[int, dict[str, Any]],
) -> dict[str, float | None]:
    start = _float_or_none(scene.get("start_sec"))
    end = _float_or_none(scene.get("end_sec"))
    duration = _float_or_none(scene.get("duration_sec"))
    if start is None:
        start = _float_or_none(timed_scene.get("start_sec"))
    if end is None:
        end = _float_or_none(timed_scene.get("end_sec"))
    if duration is None:
        duration = _float_or_none(timed_scene.get("duration_sec"))
    if start is not None and end is not None and duration is None:
        duration = max(0.0, end - start)
    if start is not None or end is not None or duration is not None:
        return {"start_sec": start, "end_sec": end, "duration_sec": duration}
    return _timing_from_fragments(fragment_ids, fragments_by_id)


def _timing_from_fragments(
    fragment_ids: list[int],
    fragments_by_id: dict[int, dict[str, Any]],
) -> dict[str, float | None]:
    fragments = [fragments_by_id[fragment_id] for fragment_id in fragment_ids if fragment_id in fragments_by_id]
    if not fragments:
        return {"start_sec": None, "end_sec": None, "duration_sec": None}
    start = _float_or_none(fragments[0].get("start_sec"))
    end = _float_or_none(fragments[-1].get("end_sec"))
    duration = max(0.0, end - start) if start is not None and end is not None else None
    return {"start_sec": start, "end_sec": end, "duration_sec": duration}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _media_item_from_dict(data: dict[str, Any]) -> MediaResolverItem:
    status = data.get("status") if data.get("status") in {"pass", "fail"} else "fail"
    return MediaResolverItem(
        post_id=str(data.get("post_id", "")),
        subreddit=str(data.get("subreddit", "")),
        title=str(data.get("title", "")),
        status=status,
        resolved_slots=list(data.get("resolved_slots", [])),
        provider_errors=[str(error) for error in data.get("provider_errors", [])],
        validator_warnings=[str(warning) for warning in data.get("validator_warnings", [])],
        from_cache=bool(data.get("from_cache")),
        cache_path=str(data.get("cache_path", "")),
        metadata=dict(data.get("metadata", {})),
    )


def _dedupe_providers(providers: list[str]) -> list[str]:
    result: list[str] = []
    for provider in providers:
        if provider and provider not in result:
            result.append(provider)
    return result


def _safe_slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    slug = "_".join(part for part in slug.split("_") if part)
    return slug[:60] or "slot"


def _period_from_scene_batch(metadata: dict[str, Any]) -> str:
    value = metadata.get("period_key")
    if isinstance(value, str) and value:
        return value
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
