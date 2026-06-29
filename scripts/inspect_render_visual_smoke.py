#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.render_visual_smoke import inspect_render_visual_smoke  # noqa: E402


def main() -> int:
    args = parse_args()
    payload_path = resolve_path(args.payload)
    video_path = resolve_path(args.video)
    frames_dir = resolve_path(args.frames_dir) if args.frames_dir else default_frames_dir(video_path)
    contact_sheet_path = resolve_path(args.contact_sheet) if args.contact_sheet else frames_dir.parent / "contact-sheet.jpg"
    timeline_frames_dir = (
        resolve_path(args.timeline_frames_dir) if args.timeline_frames_dir else frames_dir.parent / "timeline-frames"
    )
    timeline_contact_sheet_path = (
        resolve_path(args.timeline_contact_sheet)
        if args.timeline_contact_sheet
        else frames_dir.parent / "timeline-contact-sheet.jpg"
    )
    out_path = resolve_path(args.out) if args.out else frames_dir.parent / "render-visual-smoke.json"

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    report = inspect_render_visual_smoke(
        video_path=video_path,
        payload=payload,
        payload_path=payload_path,
        frames_dir=frames_dir,
        contact_sheet_path=contact_sheet_path,
        timeline_frames_dir=timeline_frames_dir,
        timeline_contact_sheet_path=timeline_contact_sheet_path,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
    if args.fail_on_defects and report.verdict == "fail":
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect rendered MP4 midpoint frames for technical visual defects.")
    parser.add_argument("--payload", required=True, help="Remotion html-layout payload JSON.")
    parser.add_argument("--video", required=True, help="Rendered MP4 to inspect.")
    parser.add_argument("--out", default="", help="Output JSON report path.")
    parser.add_argument("--frames-dir", default="", help="Directory for extracted midpoint frames.")
    parser.add_argument("--contact-sheet", default="", help="Output contact sheet JPG path.")
    parser.add_argument("--timeline-frames-dir", default="", help="Directory for extracted early/mid/late frames.")
    parser.add_argument("--timeline-contact-sheet", default="", help="Output early/mid/late contact sheet JPG path.")
    parser.add_argument("--fail-on-defects", action=argparse.BooleanOptionalAction, default=False)
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else ROOT / path


def default_frames_dir(video_path: Path) -> Path:
    return ROOT / "outputs" / "render-visual-smoke" / video_path.stem / "frames"


if __name__ == "__main__":
    raise SystemExit(main())
