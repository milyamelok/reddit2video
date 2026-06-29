#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


Json = dict[str, Any]


def main() -> int:
    args = parse_args()
    run_dir = resolve_path(args.run_dir)
    manifest = build_publication_manifest(run_dir)
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    print(text)
    out_path = resolve_path(args.out) if args.out else run_dir / "publication-manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8")
    if args.fail_on_not_publishable and not manifest["publish_allowed"]:
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a release manifest for final MP4s and publication gates.")
    parser.add_argument("--run-dir", required=True, help="Run directory with renders-final and QA reports.")
    parser.add_argument("--out", default="", help="Optional manifest JSON path.")
    parser.add_argument(
        "--fail-on-not-publishable",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Exit non-zero unless the oracle-required readiness gate allows publication.",
    )
    return parser.parse_args()


def build_publication_manifest(run_dir: Path) -> Json:
    local_readiness = _read_json(run_dir / "qa" / "publication-readiness.json")
    oracle_readiness = _read_json(run_dir / "qa" / "publication-readiness-oracle-required.json")
    batch_summary = _read_json_optional(run_dir / "gemini-quality-oracle" / "batch-run-summary.json")

    local_verdict = str(local_readiness.get("verdict") or "missing")
    oracle_verdict = str(oracle_readiness.get("verdict") or "missing")
    manifest_verdict = _manifest_verdict(local_verdict=local_verdict, oracle_verdict=oracle_verdict)
    local_items = {str(item.get("post_id") or ""): item for item in local_readiness.get("items") or [] if isinstance(item, dict)}

    items = [
        _manifest_item(
            item,
            local_item=local_items.get(str(item.get("post_id") or ""), {}),
            batch_summary=batch_summary,
        )
        for item in oracle_readiness.get("items") or []
        if isinstance(item, dict)
    ]

    return {
        "schema": "reddit2video.publication_manifest.v1",
        "run_dir": str(run_dir),
        "verdict": manifest_verdict,
        "publish_allowed": manifest_verdict == "publication_ready",
        "release_policy": "requires_local_quality_gates_and_gemini_oracle_pass",
        "local_readiness_verdict": local_verdict,
        "oracle_required_readiness_verdict": oracle_verdict,
        "gemini_oracle_batch_verdict": batch_summary.get("verdict") if batch_summary else "missing",
        "blocking_defects": oracle_readiness.get("blocking_defects") or [],
        "pending_reasons": oracle_readiness.get("pending_reasons") or [],
        "item_count": len(items),
        "publishable_item_count": sum(1 for item in items if item["publish_allowed"]),
        "items": items,
    }


def _manifest_item(item: Json, *, local_item: Json, batch_summary: Json) -> Json:
    video_path = Path(str(item.get("video_path") or ""))
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    av = evidence.get("render_av_integrity") if isinstance(evidence.get("render_av_integrity"), dict) else {}
    pending = [str(reason) for reason in item.get("pending_reasons") or [] if str(reason)]
    blocking = [str(defect) for defect in item.get("blocking_defects") or [] if str(defect)]
    status = str(item.get("status") or "missing_evidence")
    publish_allowed = status == "publication_ready" and not pending and not blocking
    hold_reasons = [*blocking, *pending]
    if not publish_allowed and not hold_reasons:
        hold_reasons.append(f"status={status}")
    batch_status = _batch_status_for_post(batch_summary, str(item.get("post_id") or ""))
    if batch_status in {"unavailable", "skipped_after_unavailable"} and "gemini_oracle_unavailable" not in hold_reasons:
        hold_reasons.append("gemini_oracle_unavailable")

    return {
        "post_id": str(item.get("post_id") or ""),
        "publish_allowed": publish_allowed,
        "status": status,
        "local_status": str(local_item.get("status") or ""),
        "hold_reasons": hold_reasons,
        "video_path": str(video_path),
        "sha256": _sha256(video_path) if video_path.exists() else "",
        "size_bytes": video_path.stat().st_size if video_path.exists() else 0,
        "duration_sec": av.get("format_duration_sec"),
        "width": av.get("width"),
        "height": av.get("height"),
        "fps": av.get("fps"),
        "audio_codec": av.get("audio_codec"),
        "gemini_oracle_batch_status": batch_status,
        "gemini_quality_oracle_report_path": str(item.get("gemini_quality_oracle_report_path") or ""),
    }


def _manifest_verdict(*, local_verdict: str, oracle_verdict: str) -> str:
    if oracle_verdict == "publication_ready":
        return "publication_ready"
    if local_verdict == "publication_ready" and oracle_verdict == "local_pass_oracle_pending":
        return "local_ready_oracle_pending"
    return "fail"


def _batch_status_for_post(batch_summary: Json, post_id: str) -> str:
    for result in batch_summary.get("results") or []:
        if isinstance(result, dict) and str(result.get("post_id") or "") == post_id:
            return str(result.get("status") or "")
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Json:
    if not path.exists():
        raise SystemExit(f"required manifest input missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"manifest input is not a JSON object: {path}")
    return data


def _read_json_optional(path: Path) -> Json:
    if not path.exists():
        return {}
    return _read_json(path)


def resolve_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else ROOT / candidate


if __name__ == "__main__":
    raise SystemExit(main())
