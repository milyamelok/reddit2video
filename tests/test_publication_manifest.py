from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parent.parent


def load_manifest_module() -> ModuleType:
    path = ROOT / "scripts/build_publication_manifest.py"
    spec = importlib.util.spec_from_file_location("build_publication_manifest", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_publication_manifest_holds_local_ready_when_oracle_is_pending(tmp_path: Path) -> None:
    module = load_manifest_module()
    run_dir = tmp_path
    _write_readiness(run_dir, oracle_required=False, item_status="publication_ready", verdict="publication_ready")
    _write_readiness(
        run_dir,
        oracle_required=True,
        item_status="ready_for_oracle",
        verdict="local_pass_oracle_pending",
        pending_reasons=["gemini_quality_oracle_report_missing"],
    )
    _write_json(
        run_dir / "gemini-quality-oracle" / "batch-run-summary.json",
        {
            "verdict": "oracle_unavailable",
            "results": [{"post_id": "post1", "status": "unavailable"}],
        },
    )

    manifest = module.build_publication_manifest(run_dir)

    assert manifest["verdict"] == "local_ready_oracle_pending"
    assert manifest["publish_allowed"] is False
    assert manifest["publishable_item_count"] == 0
    assert manifest["items"][0]["publish_allowed"] is False
    assert "gemini_quality_oracle_report_missing" in manifest["items"][0]["hold_reasons"]
    assert "gemini_oracle_unavailable" in manifest["items"][0]["hold_reasons"]
    assert manifest["items"][0]["sha256"] == _sha256_for_fixture()


def test_publication_manifest_allows_oracle_ready_item(tmp_path: Path) -> None:
    module = load_manifest_module()
    run_dir = tmp_path
    _write_readiness(run_dir, oracle_required=False, item_status="publication_ready", verdict="publication_ready")
    _write_readiness(run_dir, oracle_required=True, item_status="publication_ready", verdict="publication_ready")

    manifest = module.build_publication_manifest(run_dir)

    assert manifest["verdict"] == "publication_ready"
    assert manifest["publish_allowed"] is True
    assert manifest["publishable_item_count"] == 1
    assert manifest["items"][0]["publish_allowed"] is True
    assert manifest["items"][0]["hold_reasons"] == []


def test_publication_manifest_item_hold_reasons_include_blocking_and_pending(tmp_path: Path) -> None:
    module = load_manifest_module()
    run_dir = tmp_path
    _write_readiness(
        run_dir,
        oracle_required=False,
        item_status="local_rejected",
        verdict="fail",
        blocking_defects=["publishability:not enough real media"],
    )
    _write_readiness(
        run_dir,
        oracle_required=True,
        item_status="local_rejected",
        verdict="fail",
        blocking_defects=["publishability:not enough real media"],
        pending_reasons=["gemini_quality_oracle_report_missing"],
    )

    manifest = module.build_publication_manifest(run_dir)

    assert manifest["verdict"] == "fail"
    assert manifest["items"][0]["hold_reasons"][:2] == [
        "publishability:not enough real media",
        "gemini_quality_oracle_report_missing",
    ]


def _write_readiness(
    run_dir: Path,
    *,
    oracle_required: bool,
    item_status: str,
    verdict: str,
    pending_reasons: list[str] | None = None,
    blocking_defects: list[str] | None = None,
) -> None:
    post_id = "post1"
    video_path = run_dir / "renders-final" / f"{post_id}-final-sync.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"fixture mp4")
    item = {
        "post_id": post_id,
        "status": item_status,
        "blocking_defects": blocking_defects or [],
        "pending_reasons": pending_reasons or [],
        "warnings": [],
        "video_path": str(video_path),
        "gemini_quality_oracle_report_path": str(run_dir / "gemini-quality-oracle" / f"{post_id}.video-quality.json"),
        "evidence": {
            "render_av_integrity": {
                "format_duration_sec": 42.0,
                "width": 720,
                "height": 1280,
                "fps": 30,
                "audio_codec": "aac",
            }
        },
    }
    report = {
        "verdict": verdict,
        "oracle_required": oracle_required,
        "item_count": 1,
        "publication_ready_count": 1 if item_status == "publication_ready" else 0,
        "local_pass_count": 1,
        "oracle_available_count": 0 if pending_reasons else 1,
        "oracle_missing_count": 1 if pending_reasons else 0,
        "blocking_defects": [f"{post_id}:{defect}" for defect in blocking_defects or []],
        "pending_reasons": [f"{post_id}:{reason}" for reason in pending_reasons or []],
        "items": [item],
    }
    rel = "publication-readiness-oracle-required.json" if oracle_required else "publication-readiness.json"
    _write_json(run_dir / "qa" / rel, report)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sha256_for_fixture() -> str:
    import hashlib

    return hashlib.sha256(b"fixture mp4").hexdigest()
