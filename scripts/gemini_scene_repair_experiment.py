from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from google.genai import types
from playwright.async_api import async_playwright

from reddit2video.cli import _load_env_file
from reddit2video.gemini import GeminiClient


DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--input-html", default="outputs/html-experiments/gemini_visual_reference.html")
    parser.add_argument("--scene-number", type=int, default=9)
    parser.add_argument("--out-dir", default="outputs/html-experiments/scene-repair")
    parser.add_argument("--chrome", default=DEFAULT_CHROME)
    return asyncio.run(_amain(parser.parse_args()))


async def _amain(args: argparse.Namespace) -> int:
    _load_env_file(Path(args.env_file))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    input_html = Path(args.input_html).resolve()
    scene_number = args.scene_number
    extracted = await _extract_scene(
        input_html=input_html,
        scene_number=scene_number,
        out_dir=out_dir,
        chrome_path=args.chrome,
    )

    prompt = _build_prompt(
        scene_number=scene_number,
        input_html=input_html,
        extracted_html=extracted["standalone_html"],
        outer_html=extracted["outer_html"],
        computed=extracted["computed"],
    )
    prompt_path = out_dir / f"scene_{scene_number:02d}_repair.prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    parts: list[Any] = [
        types.Part.from_text(text=prompt),
        types.Part.from_text(text=f"Current broken screenshot for scene {scene_number}. Fix layout and proportions."),
        types.Part.from_bytes(data=Path(extracted["before_png"]).read_bytes(), mime_type="image/png"),
    ]
    client = GeminiClient.from_env(model="gemini-3.1-pro-preview", vertex=True)
    try:
        response = await client._ensure_client().aio.models.generate_content(
            model=client.model,
            contents=[types.Content(role="user", parts=parts)],
        )
    finally:
        await client.aclose()

    raw_text = getattr(response, "text", "") or ""
    repaired_html = _extract_html(raw_text)
    raw_path = out_dir / f"scene_{scene_number:02d}_repair.raw.txt"
    repaired_path = out_dir / f"scene_{scene_number:02d}_repaired.html"
    raw_path.write_text(raw_text, encoding="utf-8")
    repaired_path.write_text(repaired_html, encoding="utf-8")

    after_png = await _screenshot_repaired(
        html_path=repaired_path,
        scene_number=scene_number,
        out_dir=out_dir,
        chrome_path=args.chrome,
    )

    result = {
        "input_html": str(input_html),
        "scene_number": scene_number,
        "slice_html": extracted["slice_html"],
        "before_png": extracted["before_png"],
        "prompt": str(prompt_path),
        "raw": str(raw_path),
        "repaired_html": str(repaired_path),
        "after_png": after_png,
        "computed": extracted["computed"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def _extract_scene(
    *,
    input_html: Path,
    scene_number: int,
    out_dir: Path,
    chrome_path: str,
) -> dict[str, Any]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=chrome_path)
        page = await browser.new_page(viewport={"width": 900, "height": 1100}, device_scale_factor=2)
        await page.goto(input_html.as_uri(), wait_until="load")
        frame = page.locator(".scene-frame").nth(scene_number - 1)
        outer_html = await frame.evaluate(
            """el => {
              const wrapper = el.closest('.scene-wrapper, .scene-card, article') || el.parentElement || el;
              return wrapper.outerHTML;
            }"""
        )
        styles = await page.evaluate(
            """() => Array.from(document.querySelectorAll('style')).map(style => style.textContent).join('\\n\\n')"""
        )
        computed = await frame.evaluate(
            """el => {
              const canvas = el.querySelector('.scene-canvas') || el.firstElementChild;
              const textNodes = Array.from(el.querySelectorAll('.hero, .sub, .ui-hero, .ui-label, .split-hero, .split-sub'));
              const frameRect = el.getBoundingClientRect();
              const canvasRect = canvas ? canvas.getBoundingClientRect() : null;
              return {
                frame: {width: frameRect.width, height: frameRect.height},
                canvas: canvasRect ? {width: canvasRect.width, height: canvasRect.height} : null,
                text: textNodes.map(node => {
                  const rect = node.getBoundingClientRect();
                  return {
                    text: node.textContent.trim(),
                    className: node.className,
                    rect: {left: rect.left - frameRect.left, top: rect.top - frameRect.top, width: rect.width, height: rect.height},
                    overflowsFrame: rect.left < frameRect.left || rect.right > frameRect.right || rect.top < frameRect.top || rect.bottom > frameRect.bottom
                  };
                })
              };
            }"""
        )
        before_png = out_dir / f"scene_{scene_number:02d}_before.png"
        await frame.screenshot(path=str(before_png))
        await browser.close()

    standalone = _standalone_html(
        title=f"Scene {scene_number} repair slice",
        styles=styles,
        body=outer_html,
    )
    slice_path = out_dir / f"scene_{scene_number:02d}_slice.html"
    slice_path.write_text(standalone, encoding="utf-8")
    return {
        "outer_html": outer_html,
        "standalone_html": standalone,
        "slice_html": str(slice_path),
        "before_png": str(before_png),
        "computed": computed,
    }


async def _screenshot_repaired(
    *,
    html_path: Path,
    scene_number: int,
    out_dir: Path,
    chrome_path: str,
) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=chrome_path)
        page = await browser.new_page(viewport={"width": 900, "height": 1100}, device_scale_factor=2)
        await page.goto(html_path.resolve().as_uri(), wait_until="load")
        frame = page.locator(".scene-frame").first
        if await frame.count() == 0:
            frame = page.locator("body")
        after_png = out_dir / f"scene_{scene_number:02d}_after.png"
        await frame.screenshot(path=str(after_png))
        await browser.close()
    return str(after_png)


def _standalone_html(*, title: str, styles: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
{styles}
    body {{
      min-width: 0;
      display: grid;
      place-items: center;
      min-height: 100vh;
      padding: 32px;
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _build_prompt(
    *,
    scene_number: int,
    input_html: Path,
    extracted_html: str,
    outer_html: str,
    computed: dict[str, Any],
) -> str:
    return f"""You are a strict HTML/CSS layout repair engineer for 9:16 short-form video scenes.

You receive:
1. A screenshot of one broken scene cut out from a larger generated HTML file.
2. The isolated standalone HTML/CSS for the same scene.
3. DOM measurements showing text bounds and overflow.

Your task:
Repair ONLY scene {scene_number}. Fix:
a) layout: no text clipping, no text outside the 9:16 frame, readable Russian text, stable spacing;
b) proportions: keep the static-girly visual language, but make the scene feel intentionally composed, not accidentally oversized.

Hard requirements:
- Return one complete standalone HTML document only. No Markdown.
- Keep one .scene-frame containing one .scene-canvas.
- Preserve all data-asset-id / data-kind / data-role / data-query-* attributes.
- Do not remove media slots unless they are decorative duplicates.
- Do not fetch external assets.
- Keep a 360x640 design canvas scaled to a 260px preview frame or equivalent.
- Prefer CSS fixes: max-width, line breaks, font-size, line-height, transforms, positioning.
- Keep the same content meaning and scene metadata.
- Make Russian text fit professionally. If needed, split long text into 2-3 lines manually.

Source file:
{input_html}

Measured current layout:
```json
{json.dumps(computed, ensure_ascii=False, indent=2)}
```

Current scene wrapper HTML:
```html
{outer_html}
```

Standalone extracted HTML/CSS:
```html
{extracted_html}
```
"""


def _extract_html(text: str) -> str:
    match = re.search(r"```(?:html)?\\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip() + "\n"
    start = text.lower().find("<!doctype html")
    if start < 0:
        start = text.lower().find("<html")
    if start >= 0:
        return text[start:].strip() + "\n"
    return text.strip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
