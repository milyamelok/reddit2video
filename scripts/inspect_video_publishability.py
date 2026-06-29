#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.video_publishability import inspect_html_payload  # noqa: E402


def main() -> int:
    args = parse_args()
    reports: dict[str, Any] = {}
    failed = False
    for payload_path in args.payload:
        path = Path(payload_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        report = inspect_html_payload(
            payload,
            min_scenes=args.min_scenes,
            min_duration_sec=args.min_duration_sec,
            min_media_scene_ratio=args.min_media_scene_ratio,
            min_unique_assets=args.min_unique_assets,
            min_video_assets=args.min_video_assets,
            min_visual_archetypes=args.min_visual_archetypes,
            max_dominant_visual_archetype_ratio=args.max_dominant_visual_archetype_ratio,
            min_real_media_scene_ratio=args.min_real_media_scene_ratio,
            max_generated_visual_scene_ratio=args.max_generated_visual_scene_ratio,
            max_text_only_run=args.max_text_only_run,
            require_audio=not args.no_require_audio,
        )
        reports[str(path)] = report.model_dump()
        failed = failed or report.verdict == "fail"

    output: Any = reports
    if len(reports) == 1 and not args.keep_mapping:
        output = next(iter(reports.values()))
    text = json.dumps(output, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    return 2 if failed and args.fail_on_blockers else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Remotion HTML payloads for publishable video structure.")
    parser.add_argument("--payload", action="append", required=True, help="Path to an html-layout.generated.json payload.")
    parser.add_argument("--out", default="", help="Optional JSON output path.")
    parser.add_argument("--keep-mapping", action="store_true", help="Always return a path-to-report mapping.")
    parser.add_argument("--fail-on-blockers", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-scenes", type=int, default=8)
    parser.add_argument("--min-duration-sec", type=float, default=20.0)
    parser.add_argument("--min-media-scene-ratio", type=float, default=0.45)
    parser.add_argument("--min-unique-assets", type=int, default=6)
    parser.add_argument("--min-video-assets", type=int, default=0)
    parser.add_argument("--min-visual-archetypes", type=int, default=4)
    parser.add_argument("--max-dominant-visual-archetype-ratio", type=float, default=0.55)
    parser.add_argument("--min-real-media-scene-ratio", type=float, default=0.35)
    parser.add_argument("--max-generated-visual-scene-ratio", type=float, default=0.65)
    parser.add_argument("--max-text-only-run", type=int, default=3)
    parser.add_argument("--no-require-audio", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
