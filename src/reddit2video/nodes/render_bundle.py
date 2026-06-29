from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from reddit2video.models import (
    HtmlLayoutBatch,
    HtmlLayoutItem,
    NodeSpec,
    RenderBundleBatch,
    RenderBundleItem,
    RenderBundleNodeRequest,
    ScenePipelineBatch,
    ScenePipelineItem,
    to_jsonable,
)
from reddit2video.nodes.base import AsyncBaseNode


class RenderBundleNode(AsyncBaseNode[RenderBundleNodeRequest, RenderBundleBatch]):
    spec = NodeSpec(
        step="step-7a",
        name="render_bundle",
        description="Prepare gapless scene timings, DOM render trees, media assets, audio paths, and Remotion data.",
        mocked=False,
    )

    async def run(self, node_input: RenderBundleNodeRequest) -> RenderBundleBatch:
        period_key = node_input.period_key or _period_from_scene_batch(node_input.scene_batch)
        html_by_post_id = {item.post_id: item for item in node_input.html_batch.items}
        media_by_post_id = _media_items_by_post_id(node_input.media_resolver_payload or {})
        word_timings_by_post_id = _word_timings_by_post_id(node_input.word_timing_payload or {})
        scene_asset_root = Path(node_input.scene_asset_dir) / period_key
        audio_public_root = Path(node_input.audio_public_dir) / period_key
        scene_asset_root.mkdir(parents=True, exist_ok=True)
        audio_public_root.mkdir(parents=True, exist_ok=True)
        _copy_static_girly_fonts_to_public()

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("playwright is required for render bundle screenshots. Run `pip install -e .`.") from exc

        items: list[RenderBundleItem] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, executable_path=node_input.chrome_path)
            page = await browser.new_page(viewport={"width": 1400, "height": 2200}, device_scale_factor=3)
            for index, scene_item in enumerate(node_input.scene_batch.items, start=1):
                html_item = html_by_post_id.get(scene_item.post_id)
                items.append(
                    await self._process_item(
                        index=index,
                        scene_item=scene_item,
                        html_item=html_item,
                        media_item=media_by_post_id.get(scene_item.post_id),
                        word_timings=word_timings_by_post_id.get(scene_item.post_id, []),
                        period_key=period_key,
                        scene_asset_root=scene_asset_root,
                        audio_public_root=audio_public_root,
                        request=node_input,
                        page=page,
                    )
                )
            await browser.close()

        batch = RenderBundleBatch(
            items=items,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "node": self.spec.name,
                "period_key": period_key,
                "items": len(items),
                "passes": sum(1 for item in items if item.status == "pass"),
                "fails": sum(1 for item in items if item.status == "fail"),
                "fps": node_input.fps,
                "width": node_input.width,
                "height": node_input.height,
                "render_mode": node_input.render_mode,
                "visual_timing_policy": "gapless_extend_previous_scene_until_next_scene_start",
            },
        )
        _write_remotion_data(batch, Path(node_input.remotion_data_path))
        return batch

    async def _process_item(
        self,
        *,
        index: int,
        scene_item: ScenePipelineItem,
        html_item: HtmlLayoutItem | None,
        media_item: dict[str, Any] | None,
        word_timings: list[dict[str, Any]],
        period_key: str,
        scene_asset_root: Path,
        audio_public_root: Path,
        request: RenderBundleNodeRequest,
        page: Any,
    ) -> RenderBundleItem:
        errors: list[str] = []
        if scene_item.status != "pass":
            errors.append(f"Scene pipeline item status is {scene_item.status}.")
        if html_item is None:
            errors.append("Missing matching HTML layout item.")
        elif html_item.status != "pass":
            errors.append(f"HTML layout item status is {html_item.status}.")

        audio_path = Path(scene_item.audio_path)
        audio_public_path = audio_public_root / f"{scene_item.post_id}.mp3"
        if audio_path.exists():
            if not audio_public_path.exists() or audio_public_path.stat().st_size != audio_path.stat().st_size:
                shutil.copy2(audio_path, audio_public_path)
        else:
            errors.append(f"Missing audio file: {audio_path}")

        raw_scenes = list(scene_item.timed_scenes)
        duration_sec = round(max(_audio_duration_sec(scene_item), _last_scene_end(raw_scenes), 0.05), 3)
        visual_scenes = _build_gapless_scenes(raw_scenes, duration_sec, request.fps)
        html_path = Path(html_item.html_path) if html_item else Path("")
        scene_assets: list[dict[str, Any]] = []
        if html_item and html_path.exists():
            if request.render_mode == "screenshot":
                scene_assets = await _screenshot_scenes(
                    page=page,
                    html_path=html_path,
                    post_id=scene_item.post_id,
                    visual_scenes=visual_scenes,
                    word_timings=word_timings,
                    scene_asset_root=scene_asset_root,
                    reuse_existing=request.reuse_existing_assets,
                    fps=request.fps,
                )
            else:
                scene_assets = await _extract_scene_dom_assets(
                    page=page,
                    html_path=html_path,
                    post_id=scene_item.post_id,
                    visual_scenes=visual_scenes,
                    word_timings=word_timings,
                    scene_asset_root=scene_asset_root,
                    fps=request.fps,
                    width=request.width,
                    height=request.height,
                )
        elif html_item:
            errors.append(f"Missing HTML file: {html_path}")

        if len(scene_assets) != len(visual_scenes):
            errors.append(f"Captured {len(scene_assets)} scene assets for {len(visual_scenes)} timed scenes.")

        scenes: list[dict[str, Any]] = []
        resolved_media = _resolved_media_by_scene_asset(media_item or {})
        proxy = os.getenv("OUTBOUND_PROXY") or None
        async with httpx.AsyncClient(timeout=45, proxy=proxy, follow_redirects=True) as client:
            for visual_scene, asset in zip(visual_scenes, scene_assets):
                scene_payload = {**visual_scene, **asset}
                scene_payload["media_layers"] = await _media_layers_for_scene(
                    placeholders=list(asset.get("media_placeholders", [])),
                    resolved_media=resolved_media,
                    media_asset_dir=scene_asset_root / scene_item.post_id / "media",
                    client=client,
                )
                scene_payload["media_by_asset_id"] = {
                    str(layer.get("asset_id")): layer for layer in scene_payload["media_layers"] if layer.get("asset_id")
                }
                scenes.append(scene_payload)

        return RenderBundleItem(
            post_id=scene_item.post_id,
            subreddit=scene_item.subreddit,
            title=scene_item.title,
            composition_id=f"video-{scene_item.post_id}",
            status="fail" if errors else "pass",
            duration_sec=duration_sec,
            duration_frames=max(1, math.ceil(duration_sec * request.fps)),
            fps=request.fps,
            width=request.width,
            height=request.height,
            audio_path=str(audio_path),
            audio_public_path=_public_path(audio_public_path),
            scenes=scenes,
            word_timings=word_timings,
            html_path=str(html_path),
            errors=errors,
            metadata={
                "index": index,
                "scene_count": len(scenes),
                "word_count": len(word_timings),
                "render_mode": request.render_mode,
            },
        )


async def _extract_scene_dom_assets(
    *,
    page: Any,
    html_path: Path,
    post_id: str,
    visual_scenes: list[dict[str, Any]],
    word_timings: list[dict[str, Any]],
    scene_asset_root: Path,
    fps: int,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    item_dir = scene_asset_root / post_id
    item_dir.mkdir(parents=True, exist_ok=True)
    await page.goto(html_path.resolve().as_uri(), wait_until="load")
    await page.add_style_tag(content=_REMOTION_EXTRACTION_CSS)
    await page.evaluate(_WRAP_WORDS_SCRIPT, word_timings)
    selector = await page.evaluate(
        """() => {
          const selectors = ['.scene-frame', '.frame', '[data-scene-frame]', '.scene-card', 'article'];
          return selectors.find((sel) => document.querySelectorAll(sel).length >= 1) || '.scene-frame';
        }"""
    )
    count = await page.locator(selector).count()
    assets: list[dict[str, Any]] = []
    previous_background = "#d99caf"
    previous_dom_layers: list[dict[str, Any]] = []
    previous_placeholders: list[dict[str, Any]] = []
    words_by_scene = _word_timings_by_scene(word_timings)
    for index, scene in enumerate(visual_scenes, start=1):
        asset_status = "pass"
        background_color = previous_background
        media_placeholders: list[dict[str, Any]] = []
        dom_layers: list[dict[str, Any]] = []
        if index <= count:
            locator = page.locator(selector).nth(index - 1)
            background_color = await locator.evaluate("(el) => getComputedStyle(el).backgroundColor || '#d99caf'")
            previous_background = background_color
            media_placeholders = await _extract_media_placeholders(locator)
            for placeholder in media_placeholders:
                placeholder["scene_id"] = int(scene.get("scene_id") or index)
            dom_layers = await _extract_dom_layers(
                frame_locator=locator,
                scene=scene,
                words=words_by_scene.get(index, []),
                fps=fps,
                width=width,
                height=height,
            )
            previous_dom_layers = dom_layers
            previous_placeholders = media_placeholders
        elif previous_dom_layers:
            asset_status = "fallback_previous_scene"
            dom_layers = [dict(layer) for layer in previous_dom_layers]
            media_placeholders = [dict(placeholder) for placeholder in previous_placeholders]
            for placeholder in media_placeholders:
                placeholder["scene_id"] = int(scene.get("scene_id") or index)
        else:
            asset_status = "missing"

        assets.append(
            {
                "scene_image_path": "",
                "scene_image_public_path": "",
                "base_scene_image_path": "",
                "base_scene_image_public_path": "",
                "background_color": _css_color_to_hex(background_color),
                "asset_status": asset_status,
                "source_scene_id": scene.get("scene_id"),
                "media_placeholders": media_placeholders,
                "media_layers": [],
                "word_layers": [],
                "dom_layers": dom_layers,
            }
        )
    return assets


async def _extract_dom_layers(
    *,
    frame_locator: Any,
    scene: dict[str, Any],
    words: list[dict[str, Any]],
    fps: int,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    word_map: dict[str, dict[str, Any]] = {}
    visual_start = float(scene.get("visual_start_sec") or 0.0)
    visual_end = float(scene.get("visual_end_sec") or visual_start + 0.1)
    visual_start_frame = int(scene.get("visual_start_frame") or round(visual_start * fps))
    visual_end_frame = int(scene.get("visual_end_frame") or round(visual_end * fps))
    for order, word in enumerate(words, start=1):
        word_id = str(word.get("word_id") or "")
        if not word_id:
            continue
        appear_sec = _float_or_none(word.get("appear_sec"))
        if appear_sec is None:
            appear_sec = visual_start + min(max(0.0, visual_end - visual_start), order * 0.09)
        appear_sec = max(visual_start, min(appear_sec, max(visual_start, visual_end - (1 / fps))))
        word_map[word_id] = {
            "appear_sec": round(appear_sec, 3),
            "appear_frame": max(
                visual_start_frame,
                min(round(appear_sec * fps), max(visual_start_frame, visual_end_frame - 1)),
            ),
            "confidence": word.get("confidence"),
            "timing_strategy": str(word.get("timing_strategy", "")),
        }

    return await frame_locator.evaluate(
        _EXTRACT_DOM_LAYERS_SCRIPT,
        {
            "width": width,
            "height": height,
            "wordMap": word_map,
        },
    )


async def _screenshot_scenes(
    *,
    page: Any,
    html_path: Path,
    post_id: str,
    visual_scenes: list[dict[str, Any]],
    word_timings: list[dict[str, Any]],
    scene_asset_root: Path,
    reuse_existing: bool,
    fps: int,
) -> list[dict[str, Any]]:
    item_dir = scene_asset_root / post_id
    item_dir.mkdir(parents=True, exist_ok=True)
    await page.goto(html_path.resolve().as_uri(), wait_until="load")
    await page.add_style_tag(
        content="""
        :root {
          --scene-width: 360px !important;
          --scene-scale: 1 !important;
          --scene-design-width: 360px !important;
          --scene-design-height: 640px !important;
        }
        body { background: #000 !important; }
        .library { width: 420px !important; padding: 0 !important; }
        .library-header, .meta-strip { display: none !important; }
        .scene-grid { display: block !important; }
        .scene-card { width: 360px !important; margin: 0 0 40px 0 !important; }
        .scene-frame { width: 360px !important; height: 640px !important; aspect-ratio: auto !important; box-shadow: none !important; }
        body.rt-base .rt-word, body.rt-base .rt-sep { visibility: hidden !important; }
        body.rt-layer, body.rt-layer .scene-frame, body.rt-layer .scene-canvas { background: transparent !important; }
        body.rt-layer * {
          background: transparent !important;
          border-color: transparent !important;
          box-shadow: none !important;
        }
        body.rt-layer [data-asset-id], body.rt-layer .media-ph, body.rt-layer .media-slot, body.rt-layer img, body.rt-layer svg {
          visibility: hidden !important;
        }
        body.rt-layer .rt-word, body.rt-layer .rt-sep { visibility: hidden !important; }
        body.rt-layer .rt-active-word { visibility: visible !important; }
        """
    )
    await page.evaluate(_WRAP_WORDS_SCRIPT, word_timings)
    selector = await page.evaluate(
        """() => {
          const selectors = ['.scene-frame', '.frame', '[data-scene-frame]', '.scene-card', 'article'];
          return selectors.find((sel) => document.querySelectorAll(sel).length >= 1) || '.scene-frame';
        }"""
    )
    count = await page.locator(selector).count()
    assets: list[dict[str, Any]] = []
    previous_path: Path | None = None
    previous_background = "#d99caf"
    words_by_scene = _word_timings_by_scene(word_timings)
    for index, scene in enumerate(visual_scenes, start=1):
        path = item_dir / f"scene_{index:03d}.png"
        base_path = item_dir / f"scene_{index:03d}_base.png"
        locator = page.locator(selector).nth(index - 1)
        asset_status = "pass"
        if index <= count and (not reuse_existing or not path.exists()):
            await locator.screenshot(path=str(path))
        elif index > count and previous_path and previous_path.exists() and not path.exists():
            shutil.copy2(previous_path, path)
            asset_status = "fallback_previous_scene"
        elif index > count:
            asset_status = "missing"
        background_color = previous_background
        media_placeholders: list[dict[str, Any]] = []
        if index <= count:
            background_color = await locator.evaluate("(el) => getComputedStyle(el).backgroundColor || '#d99caf'")
            previous_background = background_color
            media_placeholders = await _extract_media_placeholders(locator)
        if path.exists():
            previous_path = path
        scene_words = words_by_scene.get(index, [])
        word_layers: list[dict[str, Any]] = []
        if index <= count and scene_words:
            if not reuse_existing or not base_path.exists():
                await page.evaluate("document.body.classList.add('rt-base')")
                await locator.screenshot(path=str(base_path))
                await page.evaluate("document.body.classList.remove('rt-base')")
            word_layers = await _capture_word_layers(
                page=page,
                frame_locator=locator,
                item_dir=item_dir,
                scene_index=index,
                scene=scene,
                words=scene_words,
                reuse_existing=reuse_existing,
                fps=fps,
            )
        elif path.exists() and not base_path.exists():
            base_path = path
        assets.append(
            {
                "scene_image_path": str(path),
                "scene_image_public_path": _public_path(path),
                "base_scene_image_path": str(base_path),
                "base_scene_image_public_path": _public_path(base_path),
                "background_color": _css_color_to_hex(background_color),
                "asset_status": asset_status if path.exists() else "missing",
                "source_scene_id": scene.get("scene_id"),
                "media_placeholders": media_placeholders,
                "word_layers": word_layers,
            }
        )
    return assets


async def _extract_media_placeholders(frame_locator: Any) -> list[dict[str, Any]]:
    return await frame_locator.evaluate(
        """(frame) => {
          const frameRect = frame.getBoundingClientRect();
          const nodes = Array.from(frame.querySelectorAll('[data-asset-id], .media-ph, .media-slot'));
          const seen = new Set();
          const result = [];
          for (const node of nodes) {
            const rect = node.getBoundingClientRect();
            if (rect.width < 6 || rect.height < 6) continue;
            const style = getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const assetId =
              node.getAttribute('data-asset-id') ||
              node.getAttribute('data-slot-id') ||
              node.id ||
              '';
            if (!assetId || seen.has(assetId)) continue;
            seen.add(assetId);
            result.push({
              asset_id: assetId,
              kind: node.getAttribute('data-kind') || node.dataset.kind || '',
              role: node.getAttribute('data-role') || node.dataset.role || '',
              query_en: node.getAttribute('data-query-en') || node.dataset.queryEn || '',
              query_ru: node.getAttribute('data-query-ru') || node.dataset.queryRu || '',
              x: Math.max(0, Math.round((rect.left - frameRect.left) * 3)),
              y: Math.max(0, Math.round((rect.top - frameRect.top) * 3)),
              width: Math.max(1, Math.round(rect.width * 3)),
              height: Math.max(1, Math.round(rect.height * 3)),
            });
          }
          return result;
        }"""
    )


async def _capture_word_layers(
    *,
    page: Any,
    frame_locator: Any,
    item_dir: Path,
    scene_index: int,
    scene: dict[str, Any],
    words: list[dict[str, Any]],
    reuse_existing: bool,
    fps: int,
) -> list[dict[str, Any]]:
    word_dir = item_dir / "words" / f"scene_{scene_index:03d}"
    word_dir.mkdir(parents=True, exist_ok=True)
    frame_box = await frame_locator.bounding_box()
    if not frame_box:
        return []
    visual_start = float(scene.get("visual_start_sec") or 0.0)
    visual_end = float(scene.get("visual_end_sec") or visual_start + 0.1)
    visual_start_frame = int(scene.get("visual_start_frame") or round(visual_start * fps))
    visual_end_frame = int(scene.get("visual_end_frame") or round(visual_end * fps))
    scale = 3
    layers: list[dict[str, Any]] = []
    await page.evaluate("document.body.classList.add('rt-layer')")
    try:
        for order, word in enumerate(words, start=1):
            word_id = str(word.get("word_id", ""))
            if not word_id:
                continue
            layer_path = word_dir / f"word_{order:03d}.png"
            selector = f'[data-word-id="{_css_attr(word_id)}"]'
            if await page.locator(selector).count() == 0:
                continue
            span = page.locator(selector).nth(0)
            if not reuse_existing or not layer_path.exists():
                await page.evaluate(
                    """(wordId) => {
                      document.querySelectorAll('.rt-active-word').forEach((node) => node.classList.remove('rt-active-word'));
                      const node = document.querySelector(`[data-word-id="${CSS.escape(wordId)}"]`);
                      if (node) node.classList.add('rt-active-word');
                    }""",
                    word_id,
                )
                box = await span.bounding_box()
                if not box:
                    continue
                pad = 10
                clip_x = max(frame_box["x"], box["x"] - pad)
                clip_y = max(frame_box["y"], box["y"] - pad)
                clip_right = min(frame_box["x"] + frame_box["width"], box["x"] + box["width"] + pad)
                clip_bottom = min(frame_box["y"] + frame_box["height"], box["y"] + box["height"] + pad)
                if clip_right <= clip_x or clip_bottom <= clip_y:
                    continue
                await page.screenshot(
                    path=str(layer_path),
                    clip={
                        "x": clip_x,
                        "y": clip_y,
                        "width": clip_right - clip_x,
                        "height": clip_bottom - clip_y,
                    },
                    omit_background=True,
                )
            else:
                box = await span.bounding_box()
                if not box:
                    continue
                pad = 10
                clip_x = max(frame_box["x"], box["x"] - pad)
                clip_y = max(frame_box["y"], box["y"] - pad)
                clip_right = min(frame_box["x"] + frame_box["width"], box["x"] + box["width"] + pad)
                clip_bottom = min(frame_box["y"] + frame_box["height"], box["y"] + box["height"] + pad)

            appear_sec = _float_or_none(word.get("appear_sec"))
            if appear_sec is None:
                appear_sec = visual_start + min(visual_end - visual_start, order * 0.09)
            appear_sec = max(visual_start, min(appear_sec, max(visual_start, visual_end - (1 / fps))))
            appear_frame = max(visual_start_frame, min(round(appear_sec * fps), max(visual_start_frame, visual_end_frame - 1)))
            layers.append(
                {
                    "word_id": word_id,
                    "word": str(word.get("word", "")),
                    "image_path": str(layer_path),
                    "image_public_path": _public_path(layer_path),
                    "x": round((clip_x - frame_box["x"]) * scale),
                    "y": round((clip_y - frame_box["y"]) * scale),
                    "width": round((clip_right - clip_x) * scale),
                    "height": round((clip_bottom - clip_y) * scale),
                    "appear_sec": round(appear_sec, 3),
                    "appear_frame": appear_frame,
                    "timing_strategy": str(word.get("timing_strategy", "")),
                    "confidence": word.get("confidence"),
                }
            )
    finally:
        await page.evaluate(
            """() => {
              document.body.classList.remove('rt-layer');
              document.querySelectorAll('.rt-active-word').forEach((node) => node.classList.remove('rt-active-word'));
            }"""
        )
    return layers


async def _media_layers_for_scene(
    *,
    placeholders: list[dict[str, Any]],
    resolved_media: dict[tuple[int, str], dict[str, Any]],
    media_asset_dir: Path,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    for placeholder in placeholders:
        scene_id = _int_or_none(placeholder.get("scene_id")) or 0
        # Placeholders usually do not carry scene_id, so match by asset_id inside the current scene map below.
        asset_id = str(placeholder.get("asset_id") or "")
        if not asset_id:
            continue
        slot = None
        if scene_id:
            slot = resolved_media.get((int(scene_id), asset_id))
        if slot is None:
            matches = [value for key, value in resolved_media.items() if key[1] == asset_id]
            if len(matches) == 1:
                slot = matches[0]
        if not slot:
            continue
        selected = list(slot.get("selected_candidates") or [])
        if not selected:
            continue
        candidate = dict(selected[0])
        materialized = await _materialize_media_candidate(
            candidate,
            media_asset_dir,
            client,
            asset_id=asset_id,
        )
        if not materialized:
            continue
        layers.append(
            {
                "asset_id": asset_id,
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "provider": str(candidate.get("provider") or ""),
                "kind": str(slot.get("slot", {}).get("kind") or placeholder.get("kind") or ""),
                "role": str(slot.get("slot", {}).get("role") or placeholder.get("role") or ""),
                "title": str(candidate.get("title") or ""),
                "media_path": materialized["path"],
                "media_public_path": materialized["public_path"],
                "media_type": materialized["media_type"],
                "x": int(placeholder.get("x") or 0),
                "y": int(placeholder.get("y") or 0),
                "width": int(placeholder.get("width") or 1),
                "height": int(placeholder.get("height") or 1),
            }
        )
    return layers


async def _materialize_media_candidate(
    candidate: dict[str, Any],
    media_asset_dir: Path,
    client: httpx.AsyncClient,
    *,
    asset_id: str = "",
) -> dict[str, str] | None:
    source_path = _candidate_local_media_path(candidate)
    source_url = str(candidate.get("media_url") or "")
    provider = str(candidate.get("provider") or "media")
    candidate_id = str(candidate.get("candidate_id") or "candidate")
    media_asset_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = _short_media_fingerprint(source_path or source_url)
    stem = "_".join(
        part
        for part in (
            _safe_file_token(provider),
            _safe_file_token(asset_id),
            _safe_file_token(candidate_id),
            fingerprint,
        )
        if part
    )
    suffix = _media_suffix(source_path or source_url)
    output = media_asset_dir / f"{stem}{suffix}"
    hls_url = _candidate_hls_url(candidate)
    if hls_url:
        mp4_output = media_asset_dir / f"{stem}.mp4"
        if mp4_output.exists() and mp4_output.stat().st_size > 0:
            return {"path": str(mp4_output), "public_path": _public_path(mp4_output), "media_type": "video"}
        if await _download_hls_to_mp4(hls_url, mp4_output):
            return {"path": str(mp4_output), "public_path": _public_path(mp4_output), "media_type": "video"}
    if output.exists() and output.stat().st_size > 0:
        return {"path": str(output), "public_path": _public_path(output), "media_type": _media_type(output)}
    if source_path:
        path = Path(source_path)
        if path.exists():
            shutil.copy2(path, output)
            return {"path": str(output), "public_path": _public_path(output), "media_type": _media_type(output)}
    for download_url in _candidate_download_urls(candidate):
        try:
            response = await client.get(download_url)
            if response.status_code >= 400:
                continue
            content_type = response.headers.get("content-type", "")
            download_suffix = _media_suffix(download_url)
            output = media_asset_dir / f"{stem}{download_suffix}"
            if download_suffix == ".bin":
                suffix = _suffix_from_content_type(content_type)
                output = media_asset_dir / f"{stem}{suffix}"
            output.write_bytes(response.content)
            return {"path": str(output), "public_path": _public_path(output), "media_type": _media_type(output)}
        except Exception:
            continue
    return None


def _candidate_hls_url(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    value = metadata.get("video_hls_url")
    return value if isinstance(value, str) and value.endswith(".m3u8") else ""


async def _download_hls_to_mp4(hls_url: str, output: Path) -> bool:
    ffmpeg_path = _find_ffmpeg_path()
    if not ffmpeg_path:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.with_suffix(".tmp.mp4")
    if tmp_output.exists():
        tmp_output.unlink()
    headers = (
        "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36\r\n"
        "Referer: https://ru.pinterest.com/\r\n"
        "Origin: https://ru.pinterest.com\r\n"
    )
    cmd = [
        str(ffmpeg_path),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-headers",
        headers,
        "-i",
        hls_url,
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-an",
        "-movflags",
        "+faststart",
        str(tmp_output),
    ]
    env = _ffmpeg_env(ffmpeg_path)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            if tmp_output.exists():
                tmp_output.unlink()
            return False
        if not tmp_output.exists() or tmp_output.stat().st_size < 1024:
            if tmp_output.exists():
                tmp_output.unlink()
            return False
        tmp_output.replace(output)
        return True
    except Exception:
        if tmp_output.exists():
            tmp_output.unlink()
        return False


def _find_ffmpeg_path() -> Path | None:
    configured = os.getenv("FFMPEG_PATH")
    if configured and Path(configured).exists():
        return Path(configured)
    system = shutil.which("ffmpeg")
    if system:
        return Path(system)
    remotion_candidates = [
        Path("remotion/node_modules/@remotion/compositor-darwin-arm64/ffmpeg"),
        Path("remotion/node_modules/@remotion/compositor-linux-x64-gnu/ffmpeg"),
        Path("remotion/node_modules/@remotion/compositor-linux-arm64-gnu/ffmpeg"),
    ]
    for candidate in remotion_candidates:
        if candidate.exists():
            return candidate
    return None


def _ffmpeg_env(ffmpeg_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    ffmpeg_dir = str(ffmpeg_path.parent.resolve())
    existing_dyld = env.get("DYLD_LIBRARY_PATH")
    env["DYLD_LIBRARY_PATH"] = f"{ffmpeg_dir}:{existing_dyld}" if existing_dyld else ffmpeg_dir
    existing_ld = env.get("LD_LIBRARY_PATH")
    env["LD_LIBRARY_PATH"] = f"{ffmpeg_dir}:{existing_ld}" if existing_ld else ffmpeg_dir
    return env


def _candidate_local_media_path(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    asset_cache = metadata.get("asset_cache") if isinstance(metadata.get("asset_cache"), dict) else {}
    for value in (
        metadata.get("local_media_path"),
        asset_cache.get("highres_path"),
        metadata.get("local_thumbnail_path"),
        asset_cache.get("lowres_path"),
    ):
        if isinstance(value, str) and value:
            return value
    return ""


def _candidate_download_urls(candidate: dict[str, Any]) -> list[str]:
    source_url = str(candidate.get("media_url") or "")
    thumbnail_url = str(candidate.get("thumbnail_url") or "")
    urls: list[str] = []
    for url in _pinterest_highres_urls(source_url):
        if url and url not in urls:
            urls.append(url)
    for url in (source_url, thumbnail_url):
        if url and url not in urls:
            urls.append(url)
    return urls


def _pinterest_highres_urls(url: str) -> list[str]:
    if not url or "pinimg.com" not in url:
        return [url] if url else []
    parsed = urlparse(url)
    parts = parsed.path.lstrip("/").split("/")
    if len(parts) < 4:
        return [url]
    size_segment = parts[0].lower()
    if size_segment not in {"60x60", "136x136", "170x", "236x", "474x", "564x", "736x", "originals"}:
        return [url]
    variants: list[str] = []
    for replacement in ("originals", "736x", "564x"):
        variant_parts = [replacement, *parts[1:]]
        variant = parsed._replace(path="/" + "/".join(variant_parts)).geturl()
        if variant not in variants:
            variants.append(variant)
    if url not in variants:
        variants.append(url)
    return variants


def _media_items_by_post_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("post_id")): dict(item) for item in payload.get("items", []) if item.get("post_id")}


def _resolved_media_by_scene_asset(media_item: dict[str, Any]) -> dict[tuple[int, str], dict[str, Any]]:
    result: dict[tuple[int, str], dict[str, Any]] = {}
    for slot in media_item.get("resolved_slots", []) or []:
        try:
            scene_id = int(slot.get("scene_id") or 0)
        except (TypeError, ValueError):
            scene_id = 0
        asset_id = str(slot.get("asset_id") or "")
        if scene_id and asset_id and slot.get("selected_candidates"):
            result[(scene_id, asset_id)] = dict(slot)
    return result


def _media_suffix(value: str) -> str:
    if not value:
        return ".bin"
    parsed_path = urlparse(value).path if "://" in value else value
    suffix = Path(parsed_path).suffix.lower()
    return suffix if suffix in {".gif", ".mp4", ".webm", ".mov", ".jpg", ".jpeg", ".png", ".webp"} else ".bin"


def _suffix_from_content_type(content_type: str) -> str:
    lowered = content_type.lower()
    if "gif" in lowered:
        return ".gif"
    if "png" in lowered:
        return ".png"
    if "webp" in lowered:
        return ".webp"
    if "mp4" in lowered:
        return ".mp4"
    if "webm" in lowered:
        return ".webm"
    return ".jpg"


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".webm", ".mov"}:
        return "video"
    if suffix == ".gif":
        return "gif"
    return "image"


def _safe_file_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return token[:80] or "asset"


def _short_media_fingerprint(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _build_gapless_scenes(raw_scenes: list[dict[str, Any]], duration_sec: float, fps: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous_end = 0.0
    for index, scene in enumerate(raw_scenes):
        next_scene = raw_scenes[index + 1] if index + 1 < len(raw_scenes) else None
        raw_start = float(scene.get("start_sec") or previous_end)
        raw_end = float(scene.get("end_sec") or raw_start)
        visual_start = 0.0 if index == 0 else previous_end
        visual_end = float(next_scene.get("start_sec")) if next_scene else duration_sec
        if visual_end <= visual_start:
            visual_end = max(raw_end, visual_start + (1 / fps))
        visual_end = min(max(visual_end, visual_start + (1 / fps)), duration_sec)
        result.append(
            {
                "scene_id": int(scene.get("scene_id") or index + 1),
                "fragment_ids": list(scene.get("fragment_ids", [])),
                "raw_start_sec": round(raw_start, 3),
                "raw_end_sec": round(raw_end, 3),
                "raw_duration_sec": round(max(0.0, raw_end - raw_start), 3),
                "visual_start_sec": round(visual_start, 3),
                "visual_end_sec": round(visual_end, 3),
                "visual_duration_sec": round(max(0.0, visual_end - visual_start), 3),
                "visual_start_frame": max(0, round(visual_start * fps)),
                "visual_end_frame": max(1, round(visual_end * fps)),
            }
        )
        previous_end = visual_end
    return result


def _audio_duration_sec(item: ScenePipelineItem) -> float:
    for key in ("alignment", "normalized_alignment"):
        ends = item.alignment.get(key, {}).get("character_end_times_seconds") or []
        for value in reversed(ends):
            if isinstance(value, (int, float)):
                return float(value)
    return 0.0


def _last_scene_end(scenes: list[dict[str, Any]]) -> float:
    for scene in reversed(scenes):
        value = scene.get("end_sec")
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _period_from_scene_batch(batch: ScenePipelineBatch) -> str:
    value = batch.metadata.get("period_key")
    if isinstance(value, str) and value:
        return value
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _word_timings_by_post_id(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {str(item.get("post_id")): list(item.get("words", [])) for item in payload.get("items", [])}


def _word_timings_by_scene(word_timings: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for index, word in enumerate(word_timings):
        scene_index = word.get("scene_index")
        try:
            scene_number = int(scene_index)
        except (TypeError, ValueError):
            word_id = str(word.get("word_id", ""))
            match = re.search(r":s(\d+):n\d+:w\d+$", word_id)
            if not match:
                continue
            scene_number = int(match.group(1))
        result.setdefault(scene_number, []).append({**word, "_order": index})

    for words in result.values():
        words.sort(
            key=lambda value: (
                int(value.get("scene_index") or 0),
                _word_id_part(str(value.get("word_id", "")), "n"),
                _word_id_part(str(value.get("word_id", "")), "w"),
                int(value.get("_order") or 0),
            )
        )
        for word in words:
            word.pop("_order", None)
    return result


def _word_id_part(word_id: str, part: str) -> int:
    match = re.search(rf":{part}(\d+)", word_id)
    return int(match.group(1)) if match else 0


def _css_attr(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_remotion_data(batch: RenderBundleBatch, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = to_jsonable(batch)
    # Keep the generated import reasonably small; detailed word timing remains in outputs/render-bundle.json.
    for item in data["items"]:
        item["word_timings"] = []
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _public_path(path: Path) -> str:
    parts = path.parts
    if "public" in parts:
        index = parts.index("public")
        return "/".join(parts[index + 1 :])
    return str(path)


def _css_color_to_hex(value: str) -> str:
    match = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", value)
    if not match:
        return value if value.startswith("#") else "#d99caf"
    red, green, blue = [int(part) for part in match.groups()]
    return f"#{red:02x}{green:02x}{blue:02x}"


def _copy_static_girly_fonts_to_public() -> None:
    source = Path("assets/style_packs/static_girly/Fonts")
    target = Path("remotion/public/style_packs/static_girly/Fonts")
    if not source.exists():
        return
    if target.exists():
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


_REMOTION_EXTRACTION_CSS = """
:root {
  --scene-width: 360px !important;
  --scene-scale: 1 !important;
  --scene-design-width: 360px !important;
  --scene-design-height: 640px !important;
}
body { background: #000 !important; }
.library { width: 420px !important; padding: 0 !important; }
.library-header, .meta-strip { display: none !important; }
.scene-grid { display: block !important; }
.scene-card { width: 360px !important; margin: 0 0 40px 0 !important; }
.scene-frame {
  width: 360px !important;
  height: 640px !important;
  aspect-ratio: auto !important;
  box-shadow: none !important;
}
"""


_EXTRACT_DOM_LAYERS_SCRIPT = r"""
(frame, payload) => {
  const frameRect = frame.getBoundingClientRect();
  const scaleX = Number(payload.width || 1080) / Math.max(1, frameRect.width);
  const scaleY = Number(payload.height || 1920) / Math.max(1, frameRect.height);
  const wordMap = payload.wordMap || {};
  const layers = [];

  function isTransparent(value) {
    return !value || value === 'transparent' || value === 'rgba(0, 0, 0, 0)';
  }

  function px(value) {
    const parsed = Number.parseFloat(value || '0');
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function scaleCssLengths(value, scale) {
    if (!value || value === 'normal' || value === 'auto' || value === 'none') return value;
    return String(value).replace(/(-?\d+(?:\.\d+)?)px/g, (_, number) => `${Number.parseFloat(number) * scale}px`);
  }

  function visible(el) {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (Number.parseFloat(style.opacity || '1') <= 0.01) return false;
    return rect.width > 0.5 && rect.height > 0.5;
  }

  function skipElement(el) {
    if (!el || !visible(el)) return true;
    if (el.matches('script, style, noscript')) return true;
    if (el.closest('.scene-meta, .meta, .metadata')) return true;
    if (el.parentElement && el.parentElement.closest('[data-asset-id], .media-ph, .media-slot')) return true;
    return false;
  }

  function directText(el) {
    let text = '';
    for (const node of Array.from(el.childNodes)) {
      if (node.nodeType === Node.TEXT_NODE) text += node.textContent || '';
    }
    return text.replace(/\s+/g, ' ').trim();
  }

  function hasVisibleElementChildren(el) {
    return Array.from(el.children).some((child) => visible(child));
  }

  function styleFor(el, rect, order, isWord, hasText, assetId) {
    const style = getComputedStyle(el);
    const padX = isWord ? 2 : 0;
    const padY = isWord ? 1 : 0;
    const left = Math.round((rect.left - frameRect.left - padX) * scaleX);
    const top = Math.round((rect.top - frameRect.top - padY) * scaleY);
    const width = Math.max(1, Math.round((rect.width + padX * 2) * scaleX));
    const height = Math.max(1, Math.round((rect.height + padY * 2) * scaleY));
    const result = {
      position: 'absolute',
      left,
      top,
      width,
      height,
      zIndex: order,
      boxSizing: 'border-box',
      overflow: assetId ? 'hidden' : style.overflow,
      opacity: Number.parseFloat(style.opacity || '1'),
    };
    if (!isTransparent(style.backgroundColor)) result.backgroundColor = style.backgroundColor;
    if (px(style.borderTopWidth) || px(style.borderRightWidth) || px(style.borderBottomWidth) || px(style.borderLeftWidth)) {
      result.borderStyle = style.borderStyle;
      result.borderColor = style.borderColor;
      result.borderWidth = scaleCssLengths(style.borderWidth, scaleX);
    }
    if (style.borderRadius && style.borderRadius !== '0px') result.borderRadius = scaleCssLengths(style.borderRadius, scaleX);
    if (style.boxShadow && style.boxShadow !== 'none') result.boxShadow = scaleCssLengths(style.boxShadow, scaleX);
    if (hasText || isWord) {
      result.color = style.color;
      result.fontFamily = style.fontFamily;
      result.fontWeight = style.fontWeight;
      result.fontStyle = style.fontStyle;
      result.fontSize = `${Math.max(1, px(style.fontSize) * scaleY)}px`;
      result.lineHeight = style.lineHeight === 'normal' ? 'normal' : `${Math.max(1, px(style.lineHeight) * scaleY)}px`;
      result.letterSpacing = style.letterSpacing === 'normal' ? 'normal' : `${px(style.letterSpacing) * scaleX}px`;
      result.textAlign = style.textAlign;
      result.textTransform = style.textTransform;
      result.textDecorationLine = style.textDecorationLine;
      result.whiteSpace = isWord ? 'pre' : style.whiteSpace;
      result.display = isWord ? 'block' : style.display;
      result.alignItems = style.alignItems;
      result.justifyContent = style.justifyContent;
      result.padding = isWord ? 0 : scaleCssLengths(style.padding, scaleX);
    }
    return result;
  }

  const elements = Array.from(frame.querySelectorAll('*'));
  let order = 0;
  for (const el of elements) {
    if (skipElement(el)) continue;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const assetId =
      el.getAttribute('data-asset-id') ||
      el.getAttribute('data-slot-id') ||
      el.id ||
      '';
    const isWord = el.classList.contains('rt-word');
    const isSep = el.classList.contains('rt-sep');
    if (isSep) continue;

    const hasChildWords = Boolean(el.querySelector('.rt-word'));
    const childrenVisible = hasVisibleElementChildren(el);
    let text = '';
    if (isWord) {
      text = el.textContent || '';
    } else if (!assetId && !hasChildWords) {
      text = directText(el);
      if (!text && !childrenVisible) text = (el.textContent || '').replace(/\s+/g, ' ').trim();
    }

    const hasPaint =
      !isTransparent(style.backgroundColor) ||
      px(style.borderTopWidth) > 0 ||
      px(style.borderRightWidth) > 0 ||
      px(style.borderBottomWidth) > 0 ||
      px(style.borderLeftWidth) > 0 ||
      (style.boxShadow && style.boxShadow !== 'none');
    if (!assetId && !isWord && !text && !hasPaint) continue;

    order += 1;
    const wordTiming = isWord && el.dataset.wordId ? wordMap[el.dataset.wordId] || null : null;
    layers.push({
      id: `dom_${order}`,
      tag: el.tagName.toLowerCase(),
      class_name: el.className || '',
      asset_id: assetId || null,
      word_id: isWord ? (el.dataset.wordId || null) : null,
      text,
      style: styleFor(el, rect, order, isWord, Boolean(text), assetId),
      appear_sec: wordTiming ? wordTiming.appear_sec : null,
      appear_frame: wordTiming ? wordTiming.appear_frame : null,
      timing_strategy: wordTiming ? wordTiming.timing_strategy : '',
      confidence: wordTiming ? wordTiming.confidence : null,
    });
  }
  return layers;
}
"""


_WRAP_WORDS_SCRIPT = r"""
(wordTimings) => {
  const frameSelectors = ['.scene-frame', '.frame', '[data-scene-frame]', '.scene-card', 'article'];
  const selector = frameSelectors.find((sel) => document.querySelectorAll(sel).length >= 1) || '.scene-frame';
  const frames = Array.from(document.querySelectorAll(selector));
  const wordPattern = /[A-Za-zА-Яа-яЁё0-9]+(?:[-'][A-Za-zА-Яа-яЁё0-9]+)?/gu;
  const alnumPattern = /[A-Za-zА-Яа-яЁё0-9]/u;
  const wordGroups = new Map();

  for (const word of wordTimings || []) {
    const wordId = String(word.word_id || '');
    const match = wordId.match(/:s(\d+):n(\d+):w(\d+)$/);
    if (!match) continue;
    const key = `${Number(match[1])}:${Number(match[2])}`;
    if (!wordGroups.has(key)) wordGroups.set(key, []);
    wordGroups.get(key).push({...word, __wordOrder: Number(match[3])});
  }

  for (const words of wordGroups.values()) {
    words.sort((left, right) => left.__wordOrder - right.__wordOrder);
  }

  function visible(el) {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 1 && rect.height > 1;
  }

  function skipElement(el) {
    if (!el) return true;
    if (el.closest('script, style, noscript, [data-asset-id], .media-ph, .media-slot, .scene-meta, .meta, .metadata')) return true;
    return !visible(el);
  }

  function appendSep(fragment, text) {
    if (!text) return;
    const sep = document.createElement('span');
    sep.className = 'rt-sep';
    sep.textContent = text;
    fragment.appendChild(sep);
  }

  function appendWord(fragment, text, timing) {
    const span = document.createElement('span');
    span.className = 'rt-word';
    span.textContent = text;
    if (timing && timing.word_id) {
      span.dataset.wordId = String(timing.word_id);
    }
    fragment.appendChild(span);
  }

  function trailingPunctuationEnd(text, start, limit) {
    let cursor = start;
    while (cursor < limit) {
      const char = text[cursor];
      if (/\s/u.test(char) || alnumPattern.test(char)) break;
      cursor += 1;
    }
    return cursor;
  }

  let nodeIndex = 0;
  let wrapped = 0;

  frames.forEach((frame, frameIndex) => {
    const walker = document.createTreeWalker(frame, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    for (const textNode of nodes) {
      const rawText = textNode.textContent || '';
      const normalizedText = rawText.replace(/\s+/g, ' ').trim();
      if (!normalizedText) continue;
      const parent = textNode.parentElement;
      if (skipElement(parent)) continue;
      if (!alnumPattern.test(normalizedText)) continue;

      nodeIndex += 1;
      const sceneIndex = frameIndex + 1;
      const key = `${sceneIndex}:${nodeIndex}`;
      const timings = wordGroups.get(key) || [];
      const matches = Array.from(rawText.matchAll(wordPattern));
      const fragment = document.createDocumentFragment();

      if (!matches.length || !timings.length) {
        appendSep(fragment, rawText);
        textNode.replaceWith(fragment);
        continue;
      }

      let cursor = 0;
      matches.forEach((match, matchIndex) => {
        const wordStart = match.index || 0;
        const wordEnd = wordStart + match[0].length;
        const nextStart = matchIndex + 1 < matches.length ? (matches[matchIndex + 1].index || rawText.length) : rawText.length;
        const visualEnd = trailingPunctuationEnd(rawText, wordEnd, nextStart);
        appendSep(fragment, rawText.slice(cursor, wordStart));
        appendWord(fragment, rawText.slice(wordStart, visualEnd), timings[matchIndex]);
        cursor = visualEnd;
      });

      appendSep(fragment, rawText.slice(cursor));
      textNode.replaceWith(fragment);
      wrapped += 1;
    }
  });

  return {wrapped};
}
"""
