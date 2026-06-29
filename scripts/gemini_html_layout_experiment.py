from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from google.genai import types

from reddit2video.cli import _load_env_file
from reddit2video.gemini import GeminiClient


DEFAULT_SCREENSHOTS = [
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--scene-pipeline", default="outputs/scene-pipeline.json")
    parser.add_argument("--style-html", default="assets/style_packs/static_girly/index.html")
    parser.add_argument("--screens-dir", default="outputs/html-experiments/reference-screens")
    parser.add_argument("--scene-index", type=int, default=10)
    parser.add_argument("--out-dir", default="outputs/html-experiments")
    parser.add_argument("--out-name", default="gemini_text_reference")
    parser.add_argument("--with-screens", action="store_true")
    parser.add_argument("--retries", type=int, default=2)
    return asyncio.run(_amain(parser.parse_args()))


async def _amain(args: argparse.Namespace) -> int:
    _load_env_file(Path(args.env_file))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scene_payload = json.loads(Path(args.scene_pipeline).read_text(encoding="utf-8"))
    item = scene_payload["items"][args.scene_index - 1]
    style_html = Path(args.style_html).read_text(encoding="utf-8")
    prompt = _build_prompt(
        scenario_index=args.scene_index,
        item=item,
        style_html=style_html,
        with_screens=args.with_screens,
    )
    (out_dir / f"{args.out_name}.prompt.txt").write_text(prompt, encoding="utf-8")

    parts: list[Any] = [types.Part.from_text(text=prompt)]
    if args.with_screens:
        screens_dir = Path(args.screens_dir)
        for index, filename in enumerate(DEFAULT_SCREENSHOTS, start=1):
            path = screens_dir / filename
            parts.append(types.Part.from_text(text=f"Reference screenshot {index}: {filename}"))
            parts.append(types.Part.from_bytes(data=path.read_bytes(), mime_type="image/png"))

    client = GeminiClient.from_env(model="gemini-3.1-pro-preview", vertex=True)
    try:
        response = None
        for attempt in range(args.retries + 1):
            try:
                response = await client._ensure_client().aio.models.generate_content(
                    model=client.model,
                    contents=[types.Content(role="user", parts=parts)],
                )
                break
            except Exception as exc:
                if attempt >= args.retries:
                    raise
                wait_seconds = 5 * (attempt + 1)
                print(
                    f"Gemini layout attempt {attempt + 1} failed: {type(exc).__name__}: {exc}. "
                    f"Retrying in {wait_seconds}s...",
                    file=sys.stderr,
                )
                await asyncio.sleep(wait_seconds)
    finally:
        await client.aclose()

    if response is None:
        raise RuntimeError("Gemini did not return a response.")

    raw_text = getattr(response, "text", "") or ""
    html = _extract_html(raw_text)
    raw_path = out_dir / f"{args.out_name}.raw.txt"
    html_path = out_dir / f"{args.out_name}.html"
    raw_path.write_text(raw_text, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    print(json.dumps({"raw": str(raw_path), "html": str(html_path), "chars": len(html)}, ensure_ascii=False))
    return 0


def _build_prompt(*, scenario_index: int, item: dict[str, Any], style_html: str, with_screens: bool) -> str:
    compact_item = {
        "post_id": item["post_id"],
        "title": item["title"],
        "status": item["status"],
        "audio_path": item["audio_path"],
        "timed_fragments": item["timed_fragments"],
        "scene_plan": item["scene_plan"],
    }
    image_instruction = (
        "You also receive 10 reference screenshots from the style library. Match their visual language closely: "
        "bold condensed typography, pastel pink/sky-blue/cream, hard 9:16 editorial layouts, fake UI, stickers, "
        "dashed image placeholders, simple diagrams, and playful wellness-blogger energy."
        if with_screens
        else "You do not receive images in this run; infer the visual language from the provided reference HTML/CSS."
    )
    return f"""You are a senior motion/HTML scene layout designer for short-form 9:16 videos.

Task:
Create a single self-contained HTML file that lays out all scenes for SCENARIO_INDEX={scenario_index}.

Reference:
1. Use the provided STYLE_LIBRARY_HTML as the main style/pipeline reference.
2. Use SCENARIO_10_PIPELINE_JSON as the content source: voiceover fragments, timings, scene tags, screen rows, templates, and media_slots.
3. {image_instruction}

Hard requirements:
- Output only one complete HTML document. No Markdown, no explanation.
- Create 22 scene frames in order.
- Each scene must be 9:16, designed at 360x640 or equivalent.
- Keep the static-girly look: pink + sky-blue + cream, cute wellness/biohacking blogger, meme stickers, fake UI, simple diagrams only.
- Do not download or reference remote images.
- For future asset resolver, create visible placeholders for media_slots with:
  data-asset-id, data-kind, data-role, data-query-ru, data-query-en, and short visual brief text.
- Use the media_slots to decide where images/GIFs/videos/stickers will go.
- The HTML must be renderable by simply opening it from disk.
- Use inline CSS only.
- Include CSS comments that label reusable scene/template patterns.
- Avoid long full subtitles. Use screen_rows as the visual text, not every voiceover word.
- Include a tiny per-scene metadata strip outside each 9:16 frame with scene id, fragment ids, duration, template, and media count.

STYLE_LIBRARY_HTML:
```html
{style_html}
```

SCENARIO_10_PIPELINE_JSON:
```json
{json.dumps(compact_item, ensure_ascii=False, indent=2)}
```
"""


def _extract_html(text: str) -> str:
    match = re.search(r"```(?:html)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
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
