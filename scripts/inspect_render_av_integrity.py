#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.render_av_integrity import inspect_render_av_integrity  # noqa: E402


def main() -> int:
    args = parse_args()
    video_path = resolve_path(args.video)
    payload_path = resolve_path(args.payload) if args.payload else None
    out_path = resolve_path(args.out) if args.out else default_out_path(video_path)
    payload = json.loads(payload_path.read_text(encoding="utf-8")) if payload_path else {}

    report = inspect_render_av_integrity(video_path=video_path, payload=payload, payload_path=payload_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
    if args.fail_on_defects and report.verdict == "fail":
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect rendered MP4 video/audio integrity for publication blockers.")
    parser.add_argument("--video", required=True, help="Rendered MP4 to inspect.")
    parser.add_argument("--payload", default="", help="Optional Remotion html-layout payload JSON for expected dimensions/duration.")
    parser.add_argument("--out", default="", help="Output JSON report path.")
    parser.add_argument("--fail-on-defects", action=argparse.BooleanOptionalAction, default=False)
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else ROOT / path


def default_out_path(video_path: Path) -> Path:
    return ROOT / "outputs" / "render-av-integrity" / f"{video_path.stem}.render-av-integrity.json"


if __name__ == "__main__":
    raise SystemExit(main())
