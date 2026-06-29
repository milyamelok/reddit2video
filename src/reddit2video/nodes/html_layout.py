from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from reddit2video.gemini import GeminiClient
from reddit2video.models import (
    HtmlLayoutBatch,
    HtmlLayoutItem,
    HtmlLayoutNodeRequest,
    NodeSpec,
    ScenePipelineItem,
    to_jsonable,
)
from reddit2video.nodes.base import AsyncBaseNode


DEFAULT_REFERENCE_SCREENSHOTS = [
    "static_girly_scene_01.png",
    "static_girly_scene_02.png",
    "static_girly_scene_03.png",
    "static_girly_scene_05.png",
    "static_girly_scene_06.png",
    "static_girly_scene_08.png",
    "static_girly_scene_10.png",
    "static_girly_scene_12.png",
    "static_girly_scene_14.png",
    "static_girly_scene_17.png",
]


class HtmlRepairDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    needs_repair: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    issues_to_fix: list[str] = Field(default_factory=list)


class HtmlLayoutNode(AsyncBaseNode[HtmlLayoutNodeRequest, HtmlLayoutBatch]):
    spec = NodeSpec(
        step="step-5",
        name="html_layout",
        description="Generate static-girly HTML layouts with visual references, QA, and repair.",
        mocked=False,
    )

    def __init__(self, *, gemini: GeminiClient | None = None) -> None:
        self.gemini = gemini or GeminiClient.from_env(model="gemini-3.1-pro-preview", vertex=True)

    async def run(self, node_input: HtmlLayoutNodeRequest) -> HtmlLayoutBatch:
        period_key = node_input.period_key or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_dir = Path(node_input.out_dir) / period_key
        out_dir.mkdir(parents=True, exist_ok=True)
        semaphore = asyncio.Semaphore(max(1, node_input.concurrency))

        async def process(index: int, item: ScenePipelineItem) -> HtmlLayoutItem:
            async with semaphore:
                return await self._process_item(index, item, node_input, out_dir)

        items = await asyncio.gather(*(process(index, item) for index, item in enumerate(node_input.scene_batch.items, start=1)))
        await self.gemini.aclose()
        return HtmlLayoutBatch(
            items=list(items),
            fetched_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "node": self.spec.name,
                "period_key": period_key,
                "items": len(items),
                "passes": sum(1 for item in items if item.status == "pass"),
                "fails": sum(1 for item in items if item.status == "fail"),
                "repair_retries": node_input.repair_retries,
                "repair_if_needed": node_input.repair_if_needed,
                "with_reference_screens": node_input.with_reference_screens,
                "out_dir": str(out_dir),
            },
        )

    async def _process_item(
        self,
        index: int,
        item: ScenePipelineItem,
        request: HtmlLayoutNodeRequest,
        out_dir: Path,
    ) -> HtmlLayoutItem:
        base = f"{index:02d}_{item.post_id}_{_safe_filename(item.title)}_visual"
        html_path = out_dir / f"{base}.html"
        raw_path = out_dir / f"{base}.raw.txt"
        prompt_path = out_dir / f"{base}.prompt.txt"
        qa_dir = out_dir / "qa" / f"{index:02d}_{item.post_id}"
        qa_dir.mkdir(parents=True, exist_ok=True)

        from_existing = False
        if request.reuse_existing and html_path.exists():
            from_existing = True
        else:
            await self._generate_html(index, item, request, html_path, raw_path, prompt_path)

        qa = await qa_html_layout(
            html_path=html_path,
            out_dir=qa_dir,
            chrome_path=request.chrome_path,
            min_scene_count=request.min_scene_count,
            max_scene_count=request.max_scene_count,
        )

        repair_attempts = 0
        visual_repair_decisions: list[dict[str, Any]] = []
        for attempt in range(max(0, request.repair_retries)):
            if not qa["errors"]:
                break
            if request.repair_if_needed:
                decision = await self._decide_repair(
                    item=item,
                    qa=qa,
                    request=request,
                    attempt=attempt + 1,
                    stage="before_repair",
                )
                visual_repair_decisions.append(decision)
                qa["visual_repair_decisions"] = visual_repair_decisions
                if not decision["needs_repair"]:
                    qa["waived_errors"] = list(qa["errors"])
                    qa["errors"] = []
                    qa["visual_repair_status"] = "waived_before_repair"
                    break

            repair_attempts += 1
            repaired_html = await self._repair_html(
                item=item,
                html_path=html_path,
                qa=qa,
                request=request,
                attempt=attempt + 1,
                raw_path=out_dir / f"{base}.repair{attempt + 1}.raw.txt",
                prompt_path=out_dir / f"{base}.repair{attempt + 1}.prompt.txt",
            )
            html_path.write_text(repaired_html, encoding="utf-8")
            qa = await qa_html_layout(
                html_path=html_path,
                out_dir=qa_dir,
                chrome_path=request.chrome_path,
                min_scene_count=request.min_scene_count,
                max_scene_count=request.max_scene_count,
            )
            qa["visual_repair_decisions"] = visual_repair_decisions

        if qa["errors"] and request.repair_if_needed:
            decision = await self._decide_repair(
                item=item,
                qa=qa,
                request=request,
                attempt=repair_attempts + 1,
                stage="after_retries",
            )
            visual_repair_decisions.append(decision)
            qa["visual_repair_decisions"] = visual_repair_decisions
            if not decision["needs_repair"]:
                qa["waived_errors"] = list(qa["errors"])
                qa["errors"] = []
                qa["visual_repair_status"] = "waived_after_retries"

        return HtmlLayoutItem(
            post_id=item.post_id,
            subreddit=item.subreddit,
            title=item.title,
            status="pass" if not qa["errors"] else "fail",
            html_path=str(html_path),
            raw_path=str(raw_path),
            prompt_path=str(prompt_path),
            preview_path=str(qa.get("page_screenshot", "")),
            qa=qa,
            repair_attempts=repair_attempts,
            from_existing=from_existing,
            metadata={
                "scene_count_detected": qa.get("scene_count"),
                "asset_slots_detected": qa.get("asset_slots"),
                "qa_dir": str(qa_dir),
                "visual_gate_checks": len(visual_repair_decisions),
            },
        )

    async def _generate_html(
        self,
        index: int,
        item: ScenePipelineItem,
        request: HtmlLayoutNodeRequest,
        html_path: Path,
        raw_path: Path,
        prompt_path: Path,
    ) -> None:
        style_html = Path(request.style_html_path).read_text(encoding="utf-8")
        prompt = build_html_generation_prompt(
            scenario_index=index,
            item=item,
            style_html=style_html,
            with_reference_screens=request.with_reference_screens,
        )
        prompt_path.write_text(prompt, encoding="utf-8")
        parts = _gemini_parts(prompt, request)
        response = await self._generate_content_with_retries(parts)
        raw_text = getattr(response, "text", "") or ""
        raw_path.write_text(raw_text, encoding="utf-8")
        html_path.write_text(extract_html(raw_text), encoding="utf-8")

    async def _repair_html(
        self,
        *,
        item: ScenePipelineItem,
        html_path: Path,
        qa: dict[str, Any],
        request: HtmlLayoutNodeRequest,
        attempt: int,
        raw_path: Path,
        prompt_path: Path,
    ) -> str:
        html = html_path.read_text(encoding="utf-8")
        issues = qa["errors"][:50]
        screenshots = [Path(path) for path in qa.get("issue_screenshots", [])[: request.max_issue_screenshots]]
        prompt = build_html_repair_prompt(
            item=item,
            html=html,
            issues=issues,
            attempt=attempt,
            min_scene_count=request.min_scene_count,
            max_scene_count=request.max_scene_count,
        )
        prompt_path.write_text(prompt, encoding="utf-8")
        parts: list[Any] = [types.Part.from_text(text=prompt)]
        for index, screenshot in enumerate(screenshots, start=1):
            parts.append(types.Part.from_text(text=f"Issue screenshot {index}: {screenshot.name}"))
            parts.append(types.Part.from_bytes(data=screenshot.read_bytes(), mime_type="image/png"))
        response = await self._generate_content_with_retries(parts)
        raw_text = getattr(response, "text", "") or ""
        raw_path.write_text(raw_text, encoding="utf-8")
        return extract_html(raw_text)

    async def _decide_repair(
        self,
        *,
        item: ScenePipelineItem,
        qa: dict[str, Any],
        request: HtmlLayoutNodeRequest,
        attempt: int,
        stage: str,
    ) -> dict[str, Any]:
        prompt = build_html_visual_gate_prompt(
            item=item,
            qa=qa,
            attempt=attempt,
            stage=stage,
            min_scene_count=request.min_scene_count,
            max_scene_count=request.max_scene_count,
        )
        screenshot_paths = _visual_gate_screenshots(qa, request.visual_gate_max_screenshots)
        parts: list[Any] = [types.Part.from_text(text=prompt)]
        for index, screenshot in enumerate(screenshot_paths, start=1):
            parts.append(types.Part.from_text(text=f"QA screenshot {index}: {screenshot.name}"))
            parts.append(types.Part.from_bytes(data=screenshot.read_bytes(), mime_type="image/png"))
        try:
            response = await self._generate_content_with_retries(
                parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=HtmlRepairDecision,
                ),
            )
            parsed = getattr(response, "parsed", None)
            if isinstance(parsed, HtmlRepairDecision):
                decision = parsed
            elif parsed is not None:
                decision = HtmlRepairDecision.model_validate(parsed)
            else:
                raw_text = getattr(response, "text", "") or ""
                decision = HtmlRepairDecision.model_validate_json(_extract_json(raw_text))
            payload = decision.model_dump(mode="json")
        except Exception as exc:
            payload = {
                "needs_repair": True,
                "confidence": 0.0,
                "reasons": [f"Visual repair gate failed, falling back to repair: {exc}"],
                "issues_to_fix": [],
            }
        payload["stage"] = stage
        payload["attempt"] = attempt
        payload["screenshots"] = [str(path) for path in screenshot_paths]
        return payload

    async def _generate_content_with_retries(
        self,
        parts: list[Any],
        retries: int = 2,
        config: types.GenerateContentConfig | None = None,
    ) -> Any:
        response = None
        for attempt in range(retries + 1):
            try:
                response = await self.gemini._ensure_client().aio.models.generate_content(
                    model=self.gemini.model,
                    contents=[types.Content(role="user", parts=parts)],
                    config=config,
                )
                break
            except Exception:
                if attempt >= retries:
                    raise
                await asyncio.sleep(5 * (attempt + 1))
        if response is None:
            raise RuntimeError("Gemini returned no response.")
        return response


def build_html_generation_prompt(
    *,
    scenario_index: int,
    item: ScenePipelineItem,
    style_html: str,
    with_reference_screens: bool,
) -> str:
    compact_item = {
        "post_id": item.post_id,
        "title": item.title,
        "status": item.status,
        "audio_path": item.audio_path,
        "timed_fragments": item.timed_fragments,
        "scene_plan": item.scene_plan,
    }
    image_instruction = (
        "You also receive 10 reference screenshots from the style library. Match their visual language closely: "
        "bold condensed typography, pastel pink/sky-blue/cream, hard 9:16 editorial layouts, fake UI, stickers, "
        "dashed image placeholders, simple diagrams, and playful wellness-blogger energy."
        if with_reference_screens
        else "You do not receive images in this run; infer the visual language from the provided reference HTML/CSS."
    )
    return f"""You are a senior motion/HTML scene layout designer for short-form 9:16 videos.

Task:
Create a single self-contained HTML file that lays out all scenes for SCENARIO_INDEX={scenario_index}.

Reference:
1. Use the provided STYLE_LIBRARY_HTML as the main style/pipeline reference.
2. Use SCENARIO_PIPELINE_JSON as the content source: voiceover fragments, timings, scene tags, screen rows, templates, and media_slots.
3. {image_instruction}

Hard requirements:
- Output only one complete HTML document. No Markdown, no explanation.
- Create one visual scene frame per scene in SCENARIO_PIPELINE_JSON.
- Each scene must be 9:16, designed at 360x640 or equivalent.
- Keep the static-girly look: pink + sky-blue + cream, cute wellness/biohacking blogger, meme stickers, fake UI, simple diagrams only.
- Do not download or reference remote images.
- For future asset resolver, create visible placeholders for media_slots with:
  data-asset-id, data-kind, data-role, data-query-ru, data-query-en, and short visual brief text.
- Use the media_slots to decide where images/GIFs/videos/stickers will go.
- The HTML must be renderable by simply opening it from disk.
- Use inline CSS only.
- Avoid long full subtitles. Use screen_rows as the visual text, not every voiceover word.
- Include a tiny per-scene metadata strip outside each 9:16 frame with scene id, fragment ids, duration, template, and media count.

STYLE_LIBRARY_HTML:
```html
{style_html}
```

SCENARIO_PIPELINE_JSON:
```json
{json.dumps(compact_item, ensure_ascii=False, indent=2)}
```
"""


def build_html_repair_prompt(
    *,
    item: ScenePipelineItem,
    html: str,
    issues: list[dict[str, Any]],
    attempt: int,
    min_scene_count: int,
    max_scene_count: int,
) -> str:
    return f"""You are a strict HTML/CSS layout repair engineer for 9:16 short-form video scene boards.

Repair attempt: {attempt}
Post id: {item.post_id}
Title: {item.title}

Your task:
Return a complete repaired HTML document. Fix only layout/proportion problems found by deterministic QA.

Hard requirements:
- Output only one complete HTML document. No Markdown.
- Keep the same scene order and meaning.
- Keep scene-like frame count inside {min_scene_count}-{max_scene_count}.
- Keep all media slot placeholders and their data-asset-id / data-kind / data-role / data-query-* attributes when possible.
- Do not fetch external assets.
- Make Russian text fit professionally: no clipping, no horizontal cut-off, no microscopic text, no text outside 9:16 frames.
- Preserve the static-girly style: pink + sky-blue + cream, bold condensed typography, fake UI, stickers, simple diagrams.
- Prefer surgical CSS/HTML fixes over rewriting the whole design.

QA_ISSUES:
```json
{json.dumps(issues, ensure_ascii=False, indent=2)}
```

CURRENT_HTML:
```html
{html}
```
"""


def build_html_visual_gate_prompt(
    *,
    item: ScenePipelineItem,
    qa: dict[str, Any],
    attempt: int,
    stage: str,
    min_scene_count: int,
    max_scene_count: int,
) -> str:
    compact_qa = {
        "scene_count": qa.get("scene_count"),
        "expected_scene_count_range": [min_scene_count, max_scene_count],
        "asset_slots": qa.get("asset_slots"),
        "errors": qa.get("errors", [])[:80],
        "warnings": qa.get("warnings", [])[:40],
    }
    return f"""You are a strict visual QA gate for 9:16 short-form HTML scene boards.

Post id: {item.post_id}
Title: {item.title}
Gate attempt: {attempt}
Stage: {stage}

You receive deterministic QA findings and screenshots. The deterministic detector can be noisy because DOM scroll metrics sometimes flag text that looks fine in the screenshot.

Decision rule:
- Return needs_repair=false only if the screenshots look publishable and the listed issues are likely false positives or harmless.
- Return needs_repair=true if you can see clipped/cut-off text, text outside a 9:16 frame, unreadably tiny text, broken proportions, media placeholders outside frames, missing placeholders, or if the scene count is outside {min_scene_count}-{max_scene_count}.
- Do not ask for cosmetic style improvements. This gate is only for visible layout/proportion defects.
- Be conservative about scene_count_out_of_range, page errors, and missing asset slots.

Return only JSON with:
{{
  "needs_repair": true|false,
  "confidence": 0.0-1.0,
  "reasons": ["short reason"],
  "issues_to_fix": ["specific visible issue to repair"]
}}

DETERMINISTIC_QA:
```json
{json.dumps(compact_qa, ensure_ascii=False, indent=2)}
```
"""


async def qa_html_layout(
    *,
    html_path: Path,
    out_dir: Path,
    chrome_path: str,
    min_scene_count: int,
    max_scene_count: int,
) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is required for HTML layout QA. Run `pip install -e .`.") from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=chrome_path)
        page = await browser.new_page(viewport={"width": 1440, "height": 1600}, device_scale_factor=1)
        page_errors: list[str] = []
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        await page.goto(html_path.resolve().as_uri(), wait_until="load")
        data = await page.evaluate(_QA_SCRIPT)
        screenshot_path = out_dir / "page.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)

        issue_screenshots: list[str] = []
        issue_scene_indexes = sorted({issue["scene_index"] for issue in data["issues"] if issue.get("scene_index")})[:10]
        selector = data.get("selector") or ".scene-frame"
        for scene_index in issue_scene_indexes:
            locator = page.locator(selector).nth(scene_index - 1)
            if await locator.count() == 0:
                continue
            path = out_dir / f"scene_{scene_index:02d}.png"
            await locator.screenshot(path=str(path))
            issue_screenshots.append(str(path))
        await browser.close()

    errors = list(data["issues"])
    scene_count = int(data["scene_count"])
    if scene_count < min_scene_count or scene_count > max_scene_count:
        errors.insert(
            0,
            {
                "type": "scene_count_out_of_range",
                "scene_index": None,
                "message": f"Detected {scene_count} scene-like frames, expected {min_scene_count}-{max_scene_count}.",
            },
        )
    for error in page_errors:
        errors.append({"type": "page_error", "scene_index": None, "message": error})

    return {
        "html_path": str(html_path),
        "selector": data.get("selector"),
        "scene_count": scene_count,
        "asset_slots": int(data["asset_slots"]),
        "errors": errors,
        "warnings": data.get("warnings", []),
        "page_errors": page_errors,
        "page_screenshot": str(screenshot_path),
        "issue_screenshots": issue_screenshots,
    }


_QA_SCRIPT = r"""
() => {
  const selectors = ['.scene-frame', '.frame', '[data-scene-frame]', '.scene-card', 'article'];
  let selector = selectors.find((sel) => document.querySelectorAll(sel).length >= 1) || '.scene-frame';
  const frames = Array.from(document.querySelectorAll(selector));
  const issues = [];
  const warnings = [];
  const assetSlots = document.querySelectorAll('[data-asset-id]').length;

  function visible(el) {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 1 && rect.height > 1;
  }

  function hasOwnText(el) {
    return Array.from(el.childNodes).some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0);
  }

  frames.forEach((frame, frameIndex) => {
    const sceneIndex = frameIndex + 1;
    const frameRect = frame.getBoundingClientRect();
    const ratio = frameRect.width / Math.max(1, frameRect.height);
    if (Math.abs(ratio - (9 / 16)) > 0.04) {
      issues.push({type: 'bad_aspect_ratio', scene_index: sceneIndex, message: `Frame aspect ratio ${ratio.toFixed(3)} is not close to 9:16.`});
    }

    const textNodes = Array.from(frame.querySelectorAll('*')).filter((el) => {
      if (!visible(el)) return false;
      if (el.closest('[data-asset-id], .media-slot, .scene-meta')) return false;
      if (!hasOwnText(el)) return false;
      return el.textContent.trim().length > 0;
    });

    textNodes.forEach((el) => {
      const rect = el.getBoundingClientRect();
      const text = el.textContent.trim().replace(/\s+/g, ' ').slice(0, 120);
      const style = getComputedStyle(el);
      const fontSize = parseFloat(style.fontSize || '0');
      const widthOverflow = el.scrollWidth - el.clientWidth;
      const heightOverflow = el.scrollHeight - el.clientHeight;
      const clipped = widthOverflow > 8 || heightOverflow > Math.max(8, el.clientHeight * 0.16);
      const outside = rect.left < frameRect.left - 4 || rect.right > frameRect.right + 4 || rect.top < frameRect.top - 4 || rect.bottom > frameRect.bottom + 4;
      if (outside) {
        issues.push({type: 'text_outside_frame', scene_index: sceneIndex, text, message: 'Text bounding box extends outside the scene frame.'});
      }
      if (clipped) {
        issues.push({type: 'text_clipped', scene_index: sceneIndex, text, message: `Text scroll size ${el.scrollWidth}x${el.scrollHeight} exceeds client size ${el.clientWidth}x${el.clientHeight}.`});
      }
      if (fontSize > 0 && fontSize < 11 && text.length > 3) {
        issues.push({type: 'text_too_small', scene_index: sceneIndex, text, message: `Font size ${fontSize.toFixed(1)}px is likely too small.`});
      }
      if (rect.width > frameRect.width * 0.98 && text.length > 12) {
        warnings.push({type: 'text_nearly_full_width', scene_index: sceneIndex, text, message: 'Text nearly spans the full frame width.'});
      }
    });

    Array.from(frame.querySelectorAll('[data-asset-id]')).forEach((slot) => {
      if (!visible(slot)) return;
      const rect = slot.getBoundingClientRect();
      const outside = rect.left < frameRect.left - 2 || rect.right > frameRect.right + 2 || rect.top < frameRect.top - 2 || rect.bottom > frameRect.bottom + 2;
      if (outside) {
        issues.push({type: 'media_slot_outside_frame', scene_index: sceneIndex, asset_id: slot.getAttribute('data-asset-id'), message: 'Media slot extends outside the scene frame.'});
      }
    });
  });

  if (assetSlots === 0) {
    issues.push({type: 'no_asset_slots', scene_index: null, message: 'No data-asset-id media slots were found.'});
  }

  return {selector, scene_count: frames.length, asset_slots: assetSlots, issues, warnings};
}
"""


def _gemini_parts(prompt: str, request: HtmlLayoutNodeRequest) -> list[Any]:
    parts: list[Any] = [types.Part.from_text(text=prompt)]
    if request.with_reference_screens:
        screens_dir = Path(request.reference_screens_dir)
        for index, filename in enumerate(DEFAULT_REFERENCE_SCREENSHOTS, start=1):
            path = screens_dir / filename
            if not path.exists():
                continue
            parts.append(types.Part.from_text(text=f"Reference screenshot {index}: {filename}"))
            parts.append(types.Part.from_bytes(data=path.read_bytes(), mime_type="image/png"))
    return parts


def extract_html(text: str) -> str:
    match = re.search(r"```(?:html)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip() + "\n"
    start = text.lower().find("<!doctype html")
    if start < 0:
        start = text.lower().find("<html")
    if start >= 0:
        return text[start:].strip() + "\n"
    return text.strip() + "\n"


def _extract_json(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        return text[start : end + 1].strip()
    return text.strip()


def _visual_gate_screenshots(qa: dict[str, Any], limit: int) -> list[Path]:
    if limit <= 0:
        return []
    paths: list[Path] = []
    for value in qa.get("issue_screenshots", []):
        if len(paths) >= limit:
            break
        path = Path(str(value))
        if path.exists() and path not in paths:
            paths.append(path)
    error_types = {str(error.get("type", "")) for error in qa.get("errors", []) if isinstance(error, dict)}
    needs_page_context = bool({"scene_count_out_of_range", "no_asset_slots", "page_error"} & error_types)
    page_screenshot = qa.get("page_screenshot")
    if (not paths or needs_page_context) and len(paths) < limit and page_screenshot:
        path = Path(str(page_screenshot))
        if path.exists() and path not in paths:
            paths.append(path)
    return paths[:limit]


def _safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_")[:70] or "untitled"
