from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, Field


Json = dict[str, Any]

PublicationReadinessStatus = Literal[
    "missing_evidence",
    "local_rejected",
    "ready_for_oracle",
    "oracle_rejected",
    "publication_ready",
]
PublicationReadinessVerdict = Literal["publication_ready", "local_pass_oracle_pending", "fail"]


class PublicationReadinessItem(BaseModel):
    post_id: str
    status: PublicationReadinessStatus
    blocking_defects: list[str] = Field(default_factory=list)
    pending_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    video_path: str = ""
    html_payload_path: str = ""
    publishability_report_path: str = ""
    render_visual_smoke_report_path: str = ""
    render_av_integrity_report_path: str = ""
    gemini_quality_oracle_report_path: str = ""
    evidence: Json = Field(default_factory=dict)


class PublicationReadinessRunReport(BaseModel):
    verdict: PublicationReadinessVerdict
    oracle_required: bool = True
    item_count: int
    publication_ready_count: int = 0
    local_pass_count: int = 0
    oracle_available_count: int = 0
    oracle_missing_count: int = 0
    blocking_defects: list[str] = Field(default_factory=list)
    pending_reasons: list[str] = Field(default_factory=list)
    items: list[PublicationReadinessItem] = Field(default_factory=list)


def build_publication_readiness_report(
    *,
    post_ids: Iterable[str],
    video_paths: Mapping[str, Path | str],
    html_payload_paths: Mapping[str, Path | str],
    publishability_report_paths: Mapping[str, Path | str],
    render_visual_smoke_report_paths: Mapping[str, Path | str],
    render_av_integrity_report_paths: Mapping[str, Path | str],
    gemini_quality_oracle_report_paths: Mapping[str, Path | str] | None = None,
    oracle_required: bool = True,
) -> PublicationReadinessRunReport:
    oracle_paths = gemini_quality_oracle_report_paths or {}
    items = [
        build_publication_readiness_item(
            post_id=str(post_id),
            video_path=_path_for(video_paths, str(post_id)),
            html_payload_path=_path_for(html_payload_paths, str(post_id)),
            publishability_report_path=_path_for(publishability_report_paths, str(post_id)),
            render_visual_smoke_report_path=_path_for(render_visual_smoke_report_paths, str(post_id)),
            render_av_integrity_report_path=_path_for(render_av_integrity_report_paths, str(post_id)),
            gemini_quality_oracle_report_path=_path_for(oracle_paths, str(post_id)),
            oracle_required=oracle_required,
        )
        for post_id in post_ids
    ]
    return publication_readiness_run_report(items, oracle_required=oracle_required)


def build_publication_readiness_item(
    *,
    post_id: str,
    video_path: Path | None,
    html_payload_path: Path | None,
    publishability_report_path: Path | None,
    render_visual_smoke_report_path: Path | None,
    render_av_integrity_report_path: Path | None,
    gemini_quality_oracle_report_path: Path | None,
    oracle_required: bool = True,
) -> PublicationReadinessItem:
    blocking_defects: list[str] = []
    pending_reasons: list[str] = []
    warnings: list[str] = []
    evidence: Json = {}

    _require_existing_path(blocking_defects, "rendered_video", video_path)
    _require_existing_path(blocking_defects, "html_payload", html_payload_path)

    publishability = _read_report(
        blocking_defects,
        "publishability",
        publishability_report_path,
    )
    visual_smoke = _read_report(
        blocking_defects,
        "render_visual_smoke",
        render_visual_smoke_report_path,
    )
    av_integrity = _read_report(
        blocking_defects,
        "render_av_integrity",
        render_av_integrity_report_path,
    )

    if publishability is not None:
        evidence["publishability"] = summarize_publishability_report(publishability)
        blocking_defects.extend(_report_defects("publishability", publishability))
        warnings.extend(_prefixed_warnings("publishability", publishability.get("warnings")))
    if visual_smoke is not None:
        evidence["render_visual_smoke"] = summarize_render_visual_smoke_report(visual_smoke)
        blocking_defects.extend(_report_defects("render_visual_smoke", visual_smoke))
    if av_integrity is not None:
        evidence["render_av_integrity"] = summarize_render_av_integrity_report(av_integrity)
        blocking_defects.extend(_report_defects("render_av_integrity", av_integrity))
        warnings.extend(_prefixed_warnings("render_av_integrity", av_integrity.get("warnings")))

    oracle_report = _read_optional_report(
        blocking_defects,
        "gemini_quality_oracle",
        gemini_quality_oracle_report_path,
    )
    if oracle_report is not None:
        oracle_defects = gemini_quality_oracle_defects(oracle_report)
        evidence["gemini_quality_oracle"] = summarize_gemini_quality_oracle_report(
            oracle_report,
            oracle_defects=oracle_defects,
        )
        blocking_defects.extend(f"gemini_quality_oracle:{defect}" for defect in oracle_defects)
    elif oracle_required:
        pending_reasons.append("gemini_quality_oracle_report_missing")

    local_defects = [defect for defect in blocking_defects if not defect.startswith("gemini_quality_oracle:")]
    oracle_defects = [defect for defect in blocking_defects if defect.startswith("gemini_quality_oracle:")]
    if local_defects:
        status: PublicationReadinessStatus = "missing_evidence" if _has_missing_evidence(local_defects) else "local_rejected"
    elif oracle_defects:
        status = "oracle_rejected"
    elif pending_reasons:
        status = "ready_for_oracle"
    else:
        status = "publication_ready"

    return PublicationReadinessItem(
        post_id=post_id,
        status=status,
        blocking_defects=blocking_defects,
        pending_reasons=pending_reasons,
        warnings=warnings,
        video_path=_path_str(video_path),
        html_payload_path=_path_str(html_payload_path),
        publishability_report_path=_path_str(publishability_report_path),
        render_visual_smoke_report_path=_path_str(render_visual_smoke_report_path),
        render_av_integrity_report_path=_path_str(render_av_integrity_report_path),
        gemini_quality_oracle_report_path=_path_str(gemini_quality_oracle_report_path),
        evidence=evidence,
    )


def publication_readiness_run_report(
    items: list[PublicationReadinessItem],
    *,
    oracle_required: bool = True,
) -> PublicationReadinessRunReport:
    blocking_defects = [
        f"{item.post_id}:{defect}"
        for item in items
        for defect in item.blocking_defects
    ]
    pending_reasons = [
        f"{item.post_id}:{reason}"
        for item in items
        for reason in item.pending_reasons
    ]
    if blocking_defects:
        verdict: PublicationReadinessVerdict = "fail"
    elif pending_reasons:
        verdict = "local_pass_oracle_pending"
    else:
        verdict = "publication_ready"
    return PublicationReadinessRunReport(
        verdict=verdict,
        oracle_required=oracle_required,
        item_count=len(items),
        publication_ready_count=sum(1 for item in items if item.status == "publication_ready"),
        local_pass_count=sum(
            1 for item in items if item.status in {"ready_for_oracle", "oracle_rejected", "publication_ready"}
        ),
        oracle_available_count=sum(1 for item in items if "gemini_quality_oracle" in item.evidence),
        oracle_missing_count=sum(1 for item in items if "gemini_quality_oracle_report_missing" in item.pending_reasons),
        blocking_defects=blocking_defects,
        pending_reasons=pending_reasons,
        items=items,
    )


def discover_standard_publication_readiness_inputs(run_dir: Path) -> Json:
    post_ids = _discover_standard_post_ids(run_dir)
    return {
        "post_ids": post_ids,
        "video_paths": {post_id: run_dir / "renders-final" / f"{post_id}-final-sync.mp4" for post_id in post_ids},
        "html_payload_paths": {
            post_id: run_dir / "html-layouts-final" / f"{post_id}.html-layout.generated.json"
            for post_id in post_ids
        },
        "publishability_report_paths": {
            post_id: run_dir / "publishability" / f"{post_id}.publishability.json"
            for post_id in post_ids
        },
        "render_visual_smoke_report_paths": {
            post_id: _prefer_existing_path(
                run_dir / "qa" / "visual-smoke" / f"{post_id}.visual-smoke.json",
                run_dir / "render-visual-smoke" / post_id / f"{post_id}.render-visual-smoke.json",
            )
            for post_id in post_ids
        },
        "render_av_integrity_report_paths": {
            post_id: _prefer_existing_path(
                run_dir / "qa" / "av-integrity" / f"{post_id}.av-integrity.json",
                run_dir / "render-av-integrity" / f"{post_id}.render-av-integrity.json",
            )
            for post_id in post_ids
        },
        "gemini_quality_oracle_report_paths": {
            post_id: run_dir / "gemini-quality-oracle" / f"{post_id}.video-quality.json"
            for post_id in post_ids
        },
    }


def gemini_quality_oracle_defects(report: Json) -> list[str]:
    defects = _string_list(report.get("blocking_defects"))
    verdict = str(report.get("verdict") or "").strip().lower()
    must_fix = _string_list(report.get("must_fix_before_publish"))
    defects.extend(f"must_fix={fix}" for fix in must_fix)
    serious_anti_degradation_flags = {
        "mostly_text_cards",
        "media_is_decorative_not_semantic",
        "generic_template_feel",
        "weak_scene_variety",
        "caption_carries_the_video",
        "unreadable_or_crowded_text",
        "broken_or_blank_visuals",
    }
    oracle_reliability_flags = {
        "evidence_too_generic",
        "audio_not_confidently_checked",
    }
    anti_flags = {str(flag).strip() for flag in report.get("anti_degradation_flags") or [] if str(flag).strip()}
    calibration_flags = {str(flag).strip() for flag in report.get("calibration_risk_flags") or [] if str(flag).strip()}
    if verdict != "pass":
        defects.append(f"verdict={verdict or 'missing'}")
    flagged = sorted(anti_flags & serious_anti_degradation_flags)
    if flagged:
        defects.append(f"anti_degradation_flags={','.join(flagged)}")
    unreliable = sorted(calibration_flags & oracle_reliability_flags)
    if unreliable:
        defects.append(f"oracle_reliability_flags={','.join(unreliable)}")
    for observation in report.get("editorial_observations") or []:
        if not isinstance(observation, dict):
            continue
        assessment = str(observation.get("assessment") or "").strip().lower()
        if assessment not in {"major_issue", "blocker"}:
            continue
        area = str(observation.get("area") or "unknown_area").strip() or "unknown_area"
        evidence = str(observation.get("visible_evidence") or "").strip()
        defects.append(f"{assessment}:{area}" + (f" ({evidence})" if evidence else ""))
    return defects


def summarize_publishability_report(report: Json) -> Json:
    return {
        "verdict": report.get("verdict"),
        "scene_count": report.get("scene_count"),
        "duration_sec": report.get("duration_sec"),
        "media_scene_ratio": report.get("media_scene_ratio"),
        "real_media_scene_ratio": report.get("real_media_scene_ratio"),
        "generated_visual_scene_ratio": report.get("generated_visual_scene_ratio"),
        "text_only_scene_count": report.get("text_only_scene_count"),
        "max_text_only_run": report.get("max_text_only_run"),
        "unique_asset_count": report.get("unique_asset_count"),
        "video_asset_count": report.get("video_asset_count"),
        "image_asset_count": report.get("image_asset_count"),
        "real_media_scene_count": report.get("real_media_scene_count"),
        "generated_visual_count": report.get("generated_visual_count"),
        "generated_visual_scene_count": report.get("generated_visual_scene_count"),
        "visual_archetype_count": report.get("visual_archetype_count"),
        "dominant_visual_archetype_ratio": report.get("dominant_visual_archetype_ratio"),
        "blocking_defects": _string_list(report.get("blocking_defects")),
        "warning_count": len(_string_list(report.get("warnings"))),
    }


def summarize_render_visual_smoke_report(report: Json) -> Json:
    return {
        "verdict": report.get("verdict"),
        "scene_count": report.get("scene_count"),
        "flagged_scene_count": report.get("flagged_scene_count"),
        "media_sample_count": report.get("media_sample_count"),
        "weak_media_sample_count": report.get("weak_media_sample_count"),
        "weak_media_scene_count": report.get("weak_media_scene_count"),
        "timeline_sample_count": report.get("timeline_sample_count"),
        "timeline_flagged_sample_count": report.get("timeline_flagged_sample_count"),
        "timeline_media_sample_count": report.get("timeline_media_sample_count"),
        "timeline_weak_media_sample_count": report.get("timeline_weak_media_sample_count"),
        "timeline_weak_media_scene_count": report.get("timeline_weak_media_scene_count"),
        "contact_sheet_path": report.get("contact_sheet_path"),
        "timeline_contact_sheet_path": report.get("timeline_contact_sheet_path"),
        "blocking_defects": _string_list(report.get("blocking_defects")),
    }


def summarize_render_av_integrity_report(report: Json) -> Json:
    silence_segments = report.get("silence_segments")
    return {
        "verdict": report.get("verdict"),
        "width": report.get("width"),
        "height": report.get("height"),
        "fps": report.get("fps"),
        "format_duration_sec": report.get("format_duration_sec"),
        "audio_codec": report.get("audio_codec"),
        "mean_volume_db": report.get("mean_volume_db"),
        "max_volume_db": report.get("max_volume_db"),
        "silence_segment_count": len(silence_segments) if isinstance(silence_segments, list) else 0,
        "blocking_defects": _string_list(report.get("blocking_defects")),
        "warning_count": len(_string_list(report.get("warnings"))),
    }


def summarize_gemini_quality_oracle_report(report: Json, *, oracle_defects: list[str]) -> Json:
    return {
        "verdict": report.get("verdict"),
        "publication_summary": report.get("publication_summary"),
        "assessment_counts": _assessment_counts(report.get("editorial_observations")),
        "blocking_defects": _string_list(report.get("blocking_defects")),
        "must_fix_before_publish": _string_list(report.get("must_fix_before_publish")),
        "anti_degradation_flags": _string_list(report.get("anti_degradation_flags")),
        "calibration_risk_flags": _string_list(report.get("calibration_risk_flags")),
        "derived_defects": oracle_defects,
    }


def _discover_standard_post_ids(run_dir: Path) -> list[str]:
    post_ids: set[str] = set()
    for path in (run_dir / "html-layouts-final").glob("*.html-layout.generated.json"):
        post_ids.add(path.name.removesuffix(".html-layout.generated.json"))
    for path in (run_dir / "renders-final").glob("*-final-sync.mp4"):
        post_ids.add(path.name.removesuffix("-final-sync.mp4"))
    for path in (run_dir / "publishability").glob("*.publishability.json"):
        post_ids.add(path.name.removesuffix(".publishability.json"))
    for path in (run_dir / "render-av-integrity").glob("*.render-av-integrity.json"):
        post_ids.add(path.name.removesuffix(".render-av-integrity.json"))
    for path in (run_dir / "qa" / "av-integrity").glob("*.av-integrity.json"):
        post_ids.add(path.name.removesuffix(".av-integrity.json"))
    for path in (run_dir / "qa" / "visual-smoke").glob("*.visual-smoke.json"):
        post_ids.add(path.name.removesuffix(".visual-smoke.json"))
    for path in (run_dir / "gemini-quality-oracle").glob("*.video-quality.json"):
        post_ids.add(path.name.removesuffix(".video-quality.json"))
    visual_dir = run_dir / "render-visual-smoke"
    if visual_dir.exists():
        for path in visual_dir.glob("*/*.render-visual-smoke.json"):
            post_ids.add(path.name.removesuffix(".render-visual-smoke.json"))
    return sorted(post_ids)


def _prefer_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def _require_existing_path(blocking_defects: list[str], label: str, path: Path | None) -> None:
    if path is None:
        blocking_defects.append(f"missing_evidence:{label}")
    elif not path.exists():
        blocking_defects.append(f"missing_evidence:{label}:{path}")


def _read_report(blocking_defects: list[str], label: str, path: Path | None) -> Json | None:
    if path is None:
        blocking_defects.append(f"missing_evidence:{label}_report")
        return None
    if not path.exists():
        blocking_defects.append(f"missing_evidence:{label}_report:{path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        blocking_defects.append(f"invalid_evidence:{label}_report:{exc}")
        return None


def _read_optional_report(blocking_defects: list[str], label: str, path: Path | None) -> Json | None:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        blocking_defects.append(f"invalid_evidence:{label}_report:{exc}")
        return None


def _report_defects(label: str, report: Json) -> list[str]:
    defects = _string_list(report.get("blocking_defects"))
    verdict = str(report.get("verdict") or "").strip().lower()
    if verdict != "pass":
        if defects:
            return [f"{label}:{defect}" for defect in defects]
        return [f"{label}:verdict={verdict or 'missing'}"]
    return []


def _prefixed_warnings(label: str, value: Any) -> list[str]:
    return [f"{label}:{warning}" for warning in _string_list(value)]


def _assessment_counts(value: Any) -> Json:
    counts: Json = {}
    if not isinstance(value, list):
        return counts
    for observation in value:
        if not isinstance(observation, dict):
            continue
        assessment = str(observation.get("assessment") or "missing").strip() or "missing"
        counts[assessment] = int(counts.get(assessment) or 0) + 1
    return counts


def _path_for(paths: Mapping[str, Path | str], post_id: str) -> Path | None:
    value = paths.get(post_id)
    if value is None:
        return None
    return value if isinstance(value, Path) else Path(value)


def _path_str(path: Path | None) -> str:
    return str(path) if path is not None else ""


def _has_missing_evidence(defects: list[str]) -> bool:
    return any(defect.startswith("missing_evidence:") or defect.startswith("invalid_evidence:") for defect in defects)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
