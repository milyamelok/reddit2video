from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType


ROOT = Path(__file__).resolve().parent.parent


def load_batch_module() -> ModuleType:
    path = ROOT / "scripts/run_gemini_quality_oracle_batch.py"
    spec = importlib.util.spec_from_file_location("run_gemini_quality_oracle_batch", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_oracle_batch_skips_existing_well_formed_report(tmp_path: Path) -> None:
    module = load_batch_module()
    video_path = tmp_path / "post1-final-sync.mp4"
    report_path = tmp_path / "post1.video-quality.json"
    video_path.write_bytes(b"mp4")
    report_path.write_text('{"verdict":"pass"}\n', encoding="utf-8")

    summary = module.run_oracle_batch(
        [module.OracleBatchItem("post1", video_path, report_path)],
        model="gemini-test",
        env_files=[],
    )

    assert summary["verdict"] == "complete"
    assert summary["skipped_existing_count"] == 1
    assert summary["results"][0]["status"] == "skipped_existing"


def test_oracle_batch_rejects_existing_failed_oracle_report(tmp_path: Path) -> None:
    module = load_batch_module()
    video_path = tmp_path / "post1-final-sync.mp4"
    report_path = tmp_path / "post1.video-quality.json"
    video_path.write_bytes(b"mp4")
    report_path.write_text(
        json.dumps(
            {
                "verdict": "pass",
                "blocking_defects": [],
                "must_fix_before_publish": [],
                "anti_degradation_flags": ["weak_scene_variety"],
                "calibration_risk_flags": [],
                "editorial_observations": [],
            }
        ),
        encoding="utf-8",
    )

    summary = module.run_oracle_batch(
        [module.OracleBatchItem("post1", video_path, report_path)],
        model="gemini-test",
        env_files=[],
    )

    assert summary["verdict"] == "oracle_rejected"
    assert summary["oracle_rejected_count"] == 1
    assert summary["results"][0]["status"] == "skipped_existing"
    assert summary["results"][0]["oracle_defects"] == ["anti_degradation_flags=weak_scene_variety"]


def test_oracle_batch_stops_after_unavailable_without_grinding(monkeypatch, tmp_path: Path) -> None:
    module = load_batch_module()
    calls: list[str] = []

    def fake_run_single_oracle(item, *, model: str, env_files: list[str]):
        calls.append(item.post_id)
        return module._result(item, "unavailable", returncode=1, message="Gemini quality oracle unavailable: auth")

    monkeypatch.setattr(module, "_run_single_oracle", fake_run_single_oracle)
    items = [
        module.OracleBatchItem("post1", tmp_path / "post1.mp4", tmp_path / "post1.json"),
        module.OracleBatchItem("post2", tmp_path / "post2.mp4", tmp_path / "post2.json"),
    ]

    summary = module.run_oracle_batch(items, model="gemini-test", env_files=[])

    assert calls == ["post1"]
    assert summary["verdict"] == "oracle_unavailable"
    assert summary["unavailable_count"] == 1
    assert summary["skipped_after_unavailable_count"] == 1
    assert summary["results"][1]["status"] == "skipped_after_unavailable"


def test_oracle_batch_dry_run_lists_missing_reports(tmp_path: Path) -> None:
    module = load_batch_module()
    items = [
        module.OracleBatchItem("post1", tmp_path / "post1.mp4", tmp_path / "post1.json"),
        module.OracleBatchItem("post2", tmp_path / "post2.mp4", tmp_path / "post2.json"),
    ]

    summary = module.run_oracle_batch(items, model="gemini-test", env_files=[], dry_run=True)

    assert summary["verdict"] == "dry_run"
    assert summary["would_run_count"] == 2


def test_run_single_oracle_passes_payload_path(monkeypatch, tmp_path: Path) -> None:
    module = load_batch_module()
    video_path = tmp_path / "post1.mp4"
    report_path = tmp_path / "post1.json"
    payload_path = tmp_path / "post1.payload.json"
    video_path.write_bytes(b"mp4")
    payload_path.write_text('{"scenes":[]}', encoding="utf-8")
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = cmd
        report_path.write_text('{"verdict":"pass"}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module._run_single_oracle(
        module.OracleBatchItem("post1", video_path, report_path, payload_path),
        model="gemini-test",
        env_files=[],
    )

    assert result["status"] == "completed"
    assert "--payload" in captured["cmd"]
    assert str(payload_path) in captured["cmd"]


def test_oracle_batch_writes_readiness_report(tmp_path: Path) -> None:
    module = load_batch_module()
    run_dir = tmp_path
    post_id = "post1"
    _write_standard_local_evidence(run_dir, post_id)
    out_path = run_dir / "qa" / "publication-readiness-oracle-required.json"

    report = module.write_readiness_report(
        run_dir,
        post_ids=[],
        out_path=out_path,
        oracle_required=True,
    )

    assert out_path.exists()
    assert report["verdict"] == "local_pass_oracle_pending"
    assert report["oracle_missing_count"] == 1
    assert json.loads(out_path.read_text(encoding="utf-8"))["items"][0]["post_id"] == post_id


def _write_standard_local_evidence(run_dir: Path, post_id: str) -> None:
    video_path = run_dir / "renders-final" / f"{post_id}-final-sync.mp4"
    html_path = run_dir / "html-layouts-final" / f"{post_id}.html-layout.generated.json"
    publishability_path = run_dir / "publishability" / f"{post_id}.publishability.json"
    visual_path = run_dir / "qa" / "visual-smoke" / f"{post_id}.visual-smoke.json"
    av_path = run_dir / "qa" / "av-integrity" / f"{post_id}.av-integrity.json"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"mp4")
    _write_json(html_path, {"scenes": []})
    _write_json(
        publishability_path,
        {
            "verdict": "pass",
            "blocking_defects": [],
            "warnings": [],
            "scene_count": 18,
            "duration_sec": 52.0,
            "media_scene_ratio": 1.0,
            "text_only_scene_count": 0,
            "max_text_only_run": 0,
            "unique_asset_count": 18,
            "video_asset_count": 1,
            "image_asset_count": 2,
            "generated_visual_count": 15,
            "visual_archetype_count": 12,
            "dominant_visual_archetype_ratio": 0.2,
        },
    )
    _write_json(
        visual_path,
        {
            "verdict": "pass",
            "blocking_defects": [],
            "scene_count": 18,
            "flagged_scene_count": 0,
            "timeline_sample_count": 54,
            "timeline_flagged_sample_count": 0,
        },
    )
    _write_json(
        av_path,
        {
            "verdict": "pass",
            "blocking_defects": [],
            "warnings": [],
            "width": 720,
            "height": 1280,
            "fps": 30,
            "format_duration_sec": 52.0,
            "audio_codec": "aac",
            "silence_segments": [],
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
