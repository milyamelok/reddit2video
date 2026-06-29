from __future__ import annotations

import json
from pathlib import Path

from reddit2video.publication_readiness import (
    build_publication_readiness_report,
    discover_standard_publication_readiness_inputs,
)


POST_ID = "post1"


def test_publication_readiness_waits_for_required_oracle(tmp_path: Path) -> None:
    paths = _write_local_pass_evidence(tmp_path)

    report = build_publication_readiness_report(
        post_ids=[POST_ID],
        video_paths={POST_ID: paths["video"]},
        html_payload_paths={POST_ID: paths["html"]},
        publishability_report_paths={POST_ID: paths["publishability"]},
        render_visual_smoke_report_paths={POST_ID: paths["visual"]},
        render_av_integrity_report_paths={POST_ID: paths["av"]},
        gemini_quality_oracle_report_paths={},
        oracle_required=True,
    )

    assert report.verdict == "local_pass_oracle_pending"
    assert report.local_pass_count == 1
    assert report.oracle_missing_count == 1
    assert report.items[0].status == "ready_for_oracle"
    assert report.items[0].blocking_defects == []
    assert report.items[0].pending_reasons == ["gemini_quality_oracle_report_missing"]


def test_publication_readiness_blocks_local_failures(tmp_path: Path) -> None:
    paths = _write_local_pass_evidence(tmp_path)
    _write_json(
        paths["publishability"],
        {
            **_pass_publishability(),
            "verdict": "fail",
            "blocking_defects": ["Every scene is text-only."],
        },
    )

    report = build_publication_readiness_report(
        post_ids=[POST_ID],
        video_paths={POST_ID: paths["video"]},
        html_payload_paths={POST_ID: paths["html"]},
        publishability_report_paths={POST_ID: paths["publishability"]},
        render_visual_smoke_report_paths={POST_ID: paths["visual"]},
        render_av_integrity_report_paths={POST_ID: paths["av"]},
        gemini_quality_oracle_report_paths={},
        oracle_required=False,
    )

    assert report.verdict == "fail"
    assert report.items[0].status == "local_rejected"
    assert "post1:publishability:Every scene is text-only." in report.blocking_defects


def test_publication_readiness_blocks_oracle_major_issue(tmp_path: Path) -> None:
    paths = _write_local_pass_evidence(tmp_path)
    oracle_path = tmp_path / "post1.video-quality.json"
    _write_json(
        oracle_path,
        {
            "verdict": "pass",
            "publication_summary": "Technically clean but visually weak.",
            "editorial_observations": [
                {
                    "area": "visual variety",
                    "assessment": "major_issue",
                    "visible_evidence": "Most scenes repeat a text card.",
                }
            ],
            "blocking_defects": [],
            "must_fix_before_publish": [],
            "anti_degradation_flags": [],
            "calibration_risk_flags": [],
        },
    )

    report = build_publication_readiness_report(
        post_ids=[POST_ID],
        video_paths={POST_ID: paths["video"]},
        html_payload_paths={POST_ID: paths["html"]},
        publishability_report_paths={POST_ID: paths["publishability"]},
        render_visual_smoke_report_paths={POST_ID: paths["visual"]},
        render_av_integrity_report_paths={POST_ID: paths["av"]},
        gemini_quality_oracle_report_paths={POST_ID: oracle_path},
        oracle_required=True,
    )

    assert report.verdict == "fail"
    assert report.local_pass_count == 1
    assert report.oracle_available_count == 1
    assert report.items[0].status == "oracle_rejected"
    assert any("gemini_quality_oracle:major_issue:visual variety" in defect for defect in report.blocking_defects)


def test_publication_readiness_accepts_local_and_oracle_pass(tmp_path: Path) -> None:
    paths = _write_local_pass_evidence(tmp_path)
    oracle_path = tmp_path / "post1.video-quality.json"
    _write_json(
        oracle_path,
        {
            "verdict": "pass",
            "publication_summary": "Ready to publish.",
            "editorial_observations": [
                {
                    "area": "visual variety",
                    "assessment": "publication_ready",
                    "visible_evidence": "Distinct scene media appears throughout.",
                }
            ],
            "blocking_defects": [],
            "must_fix_before_publish": [],
            "anti_degradation_flags": [],
            "calibration_risk_flags": [],
        },
    )

    report = build_publication_readiness_report(
        post_ids=[POST_ID],
        video_paths={POST_ID: paths["video"]},
        html_payload_paths={POST_ID: paths["html"]},
        publishability_report_paths={POST_ID: paths["publishability"]},
        render_visual_smoke_report_paths={POST_ID: paths["visual"]},
        render_av_integrity_report_paths={POST_ID: paths["av"]},
        gemini_quality_oracle_report_paths={POST_ID: oracle_path},
        oracle_required=True,
    )

    assert report.verdict == "publication_ready"
    assert report.publication_ready_count == 1
    assert report.items[0].status == "publication_ready"


def test_publication_readiness_does_not_count_missing_optional_oracle(tmp_path: Path) -> None:
    paths = _write_local_pass_evidence(tmp_path)

    report = build_publication_readiness_report(
        post_ids=[POST_ID],
        video_paths={POST_ID: paths["video"]},
        html_payload_paths={POST_ID: paths["html"]},
        publishability_report_paths={POST_ID: paths["publishability"]},
        render_visual_smoke_report_paths={POST_ID: paths["visual"]},
        render_av_integrity_report_paths={POST_ID: paths["av"]},
        gemini_quality_oracle_report_paths={POST_ID: tmp_path / "missing.video-quality.json"},
        oracle_required=False,
    )

    assert report.verdict == "publication_ready"
    assert report.oracle_available_count == 0
    assert report.oracle_missing_count == 0


def test_discover_standard_inputs_prefer_current_qa_paths(tmp_path: Path) -> None:
    run_dir = tmp_path
    html_path = run_dir / "html-layouts-final" / f"{POST_ID}.html-layout.generated.json"
    video_path = run_dir / "renders-final" / f"{POST_ID}-final-sync.mp4"
    publishability_path = run_dir / "publishability" / f"{POST_ID}.publishability.json"
    visual_path = run_dir / "qa" / "visual-smoke" / f"{POST_ID}.visual-smoke.json"
    av_path = run_dir / "qa" / "av-integrity" / f"{POST_ID}.av-integrity.json"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"mp4")
    _write_json(html_path, {"scenes": []})
    _write_json(publishability_path, _pass_publishability())
    _write_json(visual_path, _pass_visual_smoke())
    _write_json(av_path, _pass_av_integrity())

    inputs = discover_standard_publication_readiness_inputs(run_dir)
    assert inputs["post_ids"] == [POST_ID]
    assert inputs["render_visual_smoke_report_paths"][POST_ID] == visual_path
    assert inputs["render_av_integrity_report_paths"][POST_ID] == av_path

    report = build_publication_readiness_report(
        post_ids=inputs["post_ids"],
        video_paths=inputs["video_paths"],
        html_payload_paths=inputs["html_payload_paths"],
        publishability_report_paths=inputs["publishability_report_paths"],
        render_visual_smoke_report_paths=inputs["render_visual_smoke_report_paths"],
        render_av_integrity_report_paths=inputs["render_av_integrity_report_paths"],
        gemini_quality_oracle_report_paths=inputs["gemini_quality_oracle_report_paths"],
        oracle_required=False,
    )
    assert report.verdict == "publication_ready"


def test_publication_readiness_reports_missing_evidence(tmp_path: Path) -> None:
    paths = _write_local_pass_evidence(tmp_path)
    paths["visual"].unlink()

    report = build_publication_readiness_report(
        post_ids=[POST_ID],
        video_paths={POST_ID: paths["video"]},
        html_payload_paths={POST_ID: paths["html"]},
        publishability_report_paths={POST_ID: paths["publishability"]},
        render_visual_smoke_report_paths={POST_ID: paths["visual"]},
        render_av_integrity_report_paths={POST_ID: paths["av"]},
        gemini_quality_oracle_report_paths={},
        oracle_required=False,
    )

    assert report.verdict == "fail"
    assert report.items[0].status == "missing_evidence"
    assert any("missing_evidence:render_visual_smoke_report" in defect for defect in report.blocking_defects)


def _write_local_pass_evidence(tmp_path: Path) -> dict[str, Path]:
    video_path = tmp_path / "post1-final-sync.mp4"
    html_path = tmp_path / "post1.html-layout.generated.json"
    publishability_path = tmp_path / "post1.publishability.json"
    visual_path = tmp_path / "post1.render-visual-smoke.json"
    av_path = tmp_path / "post1.render-av-integrity.json"
    video_path.write_bytes(b"mp4")
    _write_json(html_path, {"scenes": []})
    _write_json(publishability_path, _pass_publishability())
    _write_json(visual_path, _pass_visual_smoke())
    _write_json(av_path, _pass_av_integrity())
    return {
        "video": video_path,
        "html": html_path,
        "publishability": publishability_path,
        "visual": visual_path,
        "av": av_path,
    }


def _pass_publishability() -> dict[str, object]:
    return {
        "verdict": "pass",
        "blocking_defects": [],
        "warnings": [],
        "scene_count": 18,
        "duration_sec": 52.0,
        "media_scene_ratio": 0.9,
        "text_only_scene_count": 2,
        "max_text_only_run": 1,
        "unique_asset_count": 20,
        "video_asset_count": 12,
        "image_asset_count": 8,
    }


def _pass_visual_smoke() -> dict[str, object]:
    return {
        "verdict": "pass",
        "blocking_defects": [],
        "scene_count": 18,
        "flagged_scene_count": 0,
        "timeline_sample_count": 54,
        "timeline_flagged_sample_count": 0,
    }


def _pass_av_integrity() -> dict[str, object]:
    return {
        "verdict": "pass",
        "blocking_defects": [],
        "warnings": [],
        "width": 720,
        "height": 1280,
        "fps": 30.0,
        "format_duration_sec": 52.0,
        "audio_codec": "aac",
        "mean_volume_db": -23.0,
        "max_volume_db": -4.0,
        "silence_segments": [],
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
