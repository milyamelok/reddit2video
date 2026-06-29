#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.publication_readiness import (  # noqa: E402
    build_publication_readiness_report,
    discover_standard_publication_readiness_inputs,
)


def main() -> int:
    args = parse_args()
    run_dir = resolve_path(args.run_dir)
    inputs = discover_standard_publication_readiness_inputs(run_dir)
    post_ids = [str(post_id) for post_id in inputs["post_ids"]]
    if args.post_id:
        requested = {str(post_id).strip() for post_id in args.post_id if str(post_id).strip()}
        post_ids = [post_id for post_id in post_ids if post_id in requested]
        missing = sorted(requested - set(post_ids))
        if missing:
            raise SystemExit(f"post ids not found in run dir: {', '.join(missing)}")
    if not post_ids:
        raise SystemExit(f"no standard render outputs found in run dir: {run_dir}")

    report = build_publication_readiness_report(
        post_ids=post_ids,
        video_paths=inputs["video_paths"],
        html_payload_paths=inputs["html_payload_paths"],
        publishability_report_paths=inputs["publishability_report_paths"],
        render_visual_smoke_report_paths=inputs["render_visual_smoke_report_paths"],
        render_av_integrity_report_paths=inputs["render_av_integrity_report_paths"],
        gemini_quality_oracle_report_paths=inputs["gemini_quality_oracle_report_paths"],
        oracle_required=bool(args.oracle_required),
    )
    text = json.dumps(report.model_dump(), ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        out_path = resolve_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    if args.fail_on_not_ready and report.verdict != "publication_ready":
        return 2
    return 2 if report.verdict == "fail" and args.fail_on_blockers else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a publication-readiness report for a static girly v5 run.")
    parser.add_argument("--run-dir", required=True, help="Run directory with renders-final and QA reports.")
    parser.add_argument("--out", default="", help="Optional JSON output path.")
    parser.add_argument("--post-id", action="append", default=[], help="Limit report to one post id. Repeatable.")
    parser.add_argument("--oracle-required", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fail-on-blockers", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--fail-on-not-ready",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Exit non-zero unless the combined verdict is publication_ready.",
    )
    return parser.parse_args()


def resolve_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else ROOT / candidate


if __name__ == "__main__":
    raise SystemExit(main())
