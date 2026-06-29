#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.publication_readiness import (  # noqa: E402
    build_publication_readiness_report,
    discover_standard_publication_readiness_inputs,
    gemini_quality_oracle_defects,
)


Json = dict[str, Any]


@dataclass(frozen=True)
class OracleBatchItem:
    post_id: str
    video_path: Path
    report_path: Path
    payload_path: Path | None = None


def main() -> int:
    args = parse_args()
    run_dir = resolve_path(args.run_dir)
    items = discover_oracle_batch_items(run_dir, post_ids=args.post_id)
    if not items:
        raise SystemExit(f"no standard render outputs found in run dir: {run_dir}")

    summary = run_oracle_batch(
        items,
        model=str(args.model),
        env_files=[str(path) for path in args.env_file],
        force=bool(args.force),
        dry_run=bool(args.dry_run),
        stop_on_unavailable=bool(args.stop_on_unavailable),
    )
    summary["run_dir"] = str(run_dir)
    summary["model"] = str(args.model)

    if args.update_readiness and not args.dry_run:
        readiness_out_path = _default_readiness_out_path(run_dir, post_ids=args.post_id, explicit=args.readiness_out)
        readiness_report = write_readiness_report(
            run_dir,
            post_ids=args.post_id,
            out_path=readiness_out_path,
            oracle_required=bool(args.readiness_oracle_required),
        )
        summary["publication_readiness_report_path"] = str(readiness_out_path)
        summary["publication_readiness"] = _readiness_summary(readiness_report)

    out_path = resolve_path(args.out) if args.out else run_dir / "gemini-quality-oracle" / "batch-run-summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    out_path.write_text(text + "\n", encoding="utf-8")

    if (summary["failed_count"] or summary["oracle_rejected_count"]) and args.fail_on_rejected:
        return 2
    if summary["unavailable_count"] and args.fail_on_unavailable:
        return 3
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Gemini video-quality oracle once per final render without overwriting existing reports."
    )
    parser.add_argument("--run-dir", required=True, help="Run directory with renders-final outputs.")
    parser.add_argument("--post-id", action="append", default=[], help="Limit to one post id. Repeatable.")
    parser.add_argument("--out", default="", help="Optional batch summary path.")
    parser.add_argument("--model", default="gemini-3.1-pro-preview")
    parser.add_argument("--env-file", action="append", default=[".env.iac", ".env"])
    parser.add_argument("--force", action="store_true", help="Re-run even when a well-formed oracle report exists.")
    parser.add_argument("--dry-run", action="store_true", help="List what would run without calling Gemini.")
    parser.add_argument("--stop-on-unavailable", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fail-on-rejected", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fail-on-unavailable", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--update-readiness", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--readiness-out", default="", help="Optional readiness report path after the oracle batch.")
    parser.add_argument("--readiness-oracle-required", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def discover_oracle_batch_items(run_dir: Path, *, post_ids: list[str] | None = None) -> list[OracleBatchItem]:
    inputs = discover_standard_publication_readiness_inputs(run_dir)
    discovered = [str(post_id) for post_id in inputs["post_ids"]]
    if post_ids:
        requested = {str(post_id).strip() for post_id in post_ids if str(post_id).strip()}
        missing = sorted(requested - set(discovered))
        if missing:
            raise SystemExit(f"post ids not found in run dir: {', '.join(missing)}")
        discovered = [post_id for post_id in discovered if post_id in requested]
    return [
        OracleBatchItem(
            post_id=post_id,
            video_path=Path(inputs["video_paths"][post_id]),
            report_path=Path(inputs["gemini_quality_oracle_report_paths"][post_id]),
            payload_path=Path(inputs["html_payload_paths"][post_id]),
        )
        for post_id in discovered
    ]


def run_oracle_batch(
    items: list[OracleBatchItem],
    *,
    model: str,
    env_files: list[str],
    force: bool = False,
    dry_run: bool = False,
    stop_on_unavailable: bool = True,
) -> Json:
    results: list[Json] = []
    unavailable = False
    for item in items:
        if not force and _has_well_formed_report(item.report_path):
            results.append(_result_from_report(item, "skipped_existing"))
            continue
        if unavailable and stop_on_unavailable:
            results.append(_result(item, "skipped_after_unavailable"))
            continue
        if dry_run:
            results.append(_result(item, "would_run"))
            continue
        run_result = _run_single_oracle(item, model=model, env_files=env_files)
        results.append(run_result)
        if run_result["status"] == "unavailable":
            unavailable = True

    return {
        "verdict": _batch_verdict(results),
        "item_count": len(items),
        "completed_count": sum(1 for result in results if result["status"] == "completed"),
        "skipped_existing_count": sum(1 for result in results if result["status"] == "skipped_existing"),
        "would_run_count": sum(1 for result in results if result["status"] == "would_run"),
        "unavailable_count": sum(1 for result in results if result["status"] == "unavailable"),
        "failed_count": sum(1 for result in results if result["status"] == "failed"),
        "oracle_rejected_count": sum(1 for result in results if result.get("oracle_defects")),
        "skipped_after_unavailable_count": sum(
            1 for result in results if result["status"] == "skipped_after_unavailable"
        ),
        "results": results,
    }


def _run_single_oracle(item: OracleBatchItem, *, model: str, env_files: list[str]) -> Json:
    item.report_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "scripts/evaluate_video_quality_gemini.py",
        "--video",
        str(item.video_path),
        "--out",
        str(item.report_path),
        "--model",
        model,
    ]
    if item.payload_path:
        cmd.extend(["--payload", str(item.payload_path)])
    for env_file in env_files:
        cmd.extend(["--env-file", env_file])
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    output = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
    if proc.returncode == 0:
        result = _result_from_report(item, "completed", returncode=proc.returncode)
        if "oracle_verdict" not in result:
            return _result(
                item,
                "failed",
                returncode=proc.returncode,
                message="Gemini oracle command completed but did not write a well-formed report.",
            )
        return result
    if "Gemini quality oracle unavailable" in output:
        return _result(item, "unavailable", returncode=proc.returncode, message=output)
    return _result(item, "failed", returncode=proc.returncode, message=output)


def _has_well_formed_report(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and str(data.get("verdict") or "").strip() in {"pass", "fail"}


def _result(
    item: OracleBatchItem,
    status: str,
    *,
    returncode: int | None = None,
    message: str = "",
) -> Json:
    result: Json = {
        "post_id": item.post_id,
        "status": status,
        "video_path": str(item.video_path),
        "report_path": str(item.report_path),
    }
    if returncode is not None:
        result["returncode"] = returncode
    if message:
        result["message"] = message
    return result


def _result_from_report(item: OracleBatchItem, status: str, *, returncode: int | None = None) -> Json:
    result = _result(item, status, returncode=returncode)
    try:
        report = json.loads(item.report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return result
    if not isinstance(report, dict):
        return result
    oracle_verdict = str(report.get("verdict") or "").strip()
    if oracle_verdict:
        result["oracle_verdict"] = oracle_verdict
    defects = gemini_quality_oracle_defects(report)
    if defects:
        result["oracle_defects"] = defects
    return result


def _batch_verdict(results: list[Json]) -> str:
    statuses = {str(result.get("status") or "") for result in results}
    if "failed" in statuses:
        return "failed"
    if any(result.get("oracle_defects") for result in results):
        return "oracle_rejected"
    if "unavailable" in statuses:
        return "oracle_unavailable"
    if "would_run" in statuses:
        return "dry_run"
    if statuses <= {"completed", "skipped_existing"}:
        return "complete"
    return "partial"


def write_readiness_report(
    run_dir: Path,
    *,
    post_ids: list[str] | None,
    out_path: Path,
    oracle_required: bool,
) -> Json:
    inputs = discover_standard_publication_readiness_inputs(run_dir)
    selected_post_ids = _selected_post_ids(inputs["post_ids"], post_ids=post_ids)
    report = build_publication_readiness_report(
        post_ids=selected_post_ids,
        video_paths=inputs["video_paths"],
        html_payload_paths=inputs["html_payload_paths"],
        publishability_report_paths=inputs["publishability_report_paths"],
        render_visual_smoke_report_paths=inputs["render_visual_smoke_report_paths"],
        render_av_integrity_report_paths=inputs["render_av_integrity_report_paths"],
        gemini_quality_oracle_report_paths=inputs["gemini_quality_oracle_report_paths"],
        oracle_required=oracle_required,
    ).model_dump()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _selected_post_ids(discovered: list[str], *, post_ids: list[str] | None) -> list[str]:
    selected = [str(post_id) for post_id in discovered]
    if not post_ids:
        return selected
    requested = {str(post_id).strip() for post_id in post_ids if str(post_id).strip()}
    missing = sorted(requested - set(selected))
    if missing:
        raise SystemExit(f"post ids not found in run dir: {', '.join(missing)}")
    return [post_id for post_id in selected if post_id in requested]


def _default_readiness_out_path(run_dir: Path, *, post_ids: list[str], explicit: str) -> Path:
    if explicit:
        return resolve_path(explicit)
    suffix = ".selected" if post_ids else ""
    return run_dir / "qa" / f"publication-readiness-oracle-required{suffix}.json"


def _readiness_summary(report: Json) -> Json:
    return {
        "verdict": report.get("verdict"),
        "item_count": report.get("item_count"),
        "publication_ready_count": report.get("publication_ready_count"),
        "local_pass_count": report.get("local_pass_count"),
        "oracle_available_count": report.get("oracle_available_count"),
        "oracle_missing_count": report.get("oracle_missing_count"),
        "blocking_defects": report.get("blocking_defects") or [],
        "pending_reasons": report.get("pending_reasons") or [],
    }


def resolve_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else ROOT / candidate


if __name__ == "__main__":
    raise SystemExit(main())
