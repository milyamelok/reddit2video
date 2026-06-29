#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reddit2video.girly_static_renderer import materialize_scenes_for_girly_static, render_girly_static_document


def main() -> None:
    parser = argparse.ArgumentParser(description="Render storyboard_v2 scenes into static_girly_2 filled HTML.")
    parser.add_argument("--input", required=True, help="Path to one storyboard item or storyboard_v2 JSON payload.")
    parser.add_argument("--out", required=True, help="Output HTML path.")
    parser.add_argument(
        "--style-html",
        default="assets/style_packs/static_girly_2/index.html",
        help="Path to the static_girly_2 index.html template.",
    )
    parser.add_argument("--title", default="girly static v5", help="Rendered HTML title.")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    scenes = materialize_scenes_for_girly_static(_first_storyboard_payload(payload))
    html = render_girly_static_document(scenes, style_html_path=args.style_html, title=args.title)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path} with {len(scenes)} scenes")


def _first_storyboard_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("storyboard_v2"), dict) or isinstance(payload.get("scenes"), list):
        return payload
    items = payload.get("items")
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            script = first.get("script")
            if isinstance(script, dict):
                return script
            return first
    return payload


if __name__ == "__main__":
    main()
