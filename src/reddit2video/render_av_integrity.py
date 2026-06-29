from __future__ import annotations

import os
from pathlib import Path
import json
import re
import shutil
import subprocess
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


Json = dict[str, Any]


class SilenceSegment(BaseModel):
    start_sec: float
    end_sec: float
    duration_sec: float


class RenderAVIntegrityReport(BaseModel):
    verdict: Literal["pass", "fail"]
    blocking_defects: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    video_path: str
    payload_path: str = ""
    expected_width: Optional[int] = None
    expected_height: Optional[int] = None
    expected_fps: Optional[float] = None
    expected_duration_sec: Optional[float] = None
    format_duration_sec: Optional[float] = None
    video_duration_sec: Optional[float] = None
    audio_duration_sec: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    video_codec: str = ""
    audio_codec: str = ""
    audio_sample_rate: Optional[int] = None
    audio_channels: Optional[int] = None
    video_bit_rate: Optional[int] = None
    audio_bit_rate: Optional[int] = None
    mean_volume_db: Optional[float] = None
    max_volume_db: Optional[float] = None
    silence_segments: list[SilenceSegment] = Field(default_factory=list)


def inspect_render_av_integrity(
    *,
    video_path: Path,
    payload: Json | None = None,
    payload_path: Path | None = None,
) -> RenderAVIntegrityReport:
    payload = payload or {}
    probe = ffprobe_json(video_path)
    summary = summarize_probe(probe)
    expected_width = _positive_int(payload.get("width"))
    expected_height = _positive_int(payload.get("height"))
    expected_fps = _positive_float(payload.get("fps"))
    expected_duration_sec = expected_duration_from_payload(payload)
    mean_volume_db: float | None = None
    max_volume_db: float | None = None
    silence_segments: list[SilenceSegment] = []

    if summary.get("audio_codec"):
        volume_text = ffmpeg_audio_filter_output(video_path, ["volumedetect"])
        mean_volume_db, max_volume_db = parse_volumedetect(volume_text)
        silence_text = ffmpeg_audio_filter_output(video_path, ["silencedetect=noise=-45dB:d=0.8"])
        silence_segments = parse_silencedetect(silence_text)

    report = RenderAVIntegrityReport(
        verdict="pass",
        video_path=str(video_path),
        payload_path=str(payload_path or ""),
        expected_width=expected_width,
        expected_height=expected_height,
        expected_fps=expected_fps,
        expected_duration_sec=expected_duration_sec,
        format_duration_sec=summary.get("format_duration_sec"),
        video_duration_sec=summary.get("video_duration_sec"),
        audio_duration_sec=summary.get("audio_duration_sec"),
        width=summary.get("width"),
        height=summary.get("height"),
        fps=summary.get("fps"),
        video_codec=str(summary.get("video_codec") or ""),
        audio_codec=str(summary.get("audio_codec") or ""),
        audio_sample_rate=summary.get("audio_sample_rate"),
        audio_channels=summary.get("audio_channels"),
        video_bit_rate=summary.get("video_bit_rate"),
        audio_bit_rate=summary.get("audio_bit_rate"),
        mean_volume_db=mean_volume_db,
        max_volume_db=max_volume_db,
        silence_segments=silence_segments,
    )
    defects, warnings = av_integrity_findings(report)
    report.blocking_defects = defects
    report.warnings = warnings
    report.verdict = "fail" if defects else "pass"
    return report


def summarize_probe(probe: Json) -> Json:
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
    video_stream = _first_stream(streams, "video")
    audio_stream = _first_stream(streams, "audio")
    format_info = probe.get("format") if isinstance(probe.get("format"), dict) else {}
    return {
        "format_duration_sec": _positive_float(format_info.get("duration")),
        "video_duration_sec": _positive_float(video_stream.get("duration")) if video_stream else None,
        "audio_duration_sec": _positive_float(audio_stream.get("duration")) if audio_stream else None,
        "width": _positive_int(video_stream.get("width")) if video_stream else None,
        "height": _positive_int(video_stream.get("height")) if video_stream else None,
        "fps": _ratio_to_float(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate")) if video_stream else None,
        "video_codec": str(video_stream.get("codec_name") or "") if video_stream else "",
        "audio_codec": str(audio_stream.get("codec_name") or "") if audio_stream else "",
        "audio_sample_rate": _positive_int(audio_stream.get("sample_rate")) if audio_stream else None,
        "audio_channels": _positive_int(audio_stream.get("channels")) if audio_stream else None,
        "video_bit_rate": _positive_int(video_stream.get("bit_rate")) if video_stream else None,
        "audio_bit_rate": _positive_int(audio_stream.get("bit_rate")) if audio_stream else None,
    }


def expected_duration_from_payload(payload: Json) -> float | None:
    fps = _positive_float(payload.get("fps"))
    frames = _positive_float(payload.get("duration_frames"))
    if fps and frames:
        return round(frames / fps, 3)
    scenes = payload.get("scenes")
    if fps and isinstance(scenes, list):
        end_frame = 0.0
        for raw_scene in scenes:
            scene = raw_scene if isinstance(raw_scene, dict) else {}
            start_frame = _positive_float(scene.get("start_frame")) or 0.0
            duration_frames = _positive_float(scene.get("duration_frames")) or 0.0
            end_frame = max(end_frame, start_frame + duration_frames)
        if end_frame > 0:
            return round(end_frame / fps, 3)
    return None


def av_integrity_findings(
    report: RenderAVIntegrityReport,
    *,
    duration_tolerance_sec: float = 0.75,
    av_duration_tolerance_sec: float = 0.4,
    fps_tolerance: float = 0.2,
    min_mean_volume_db: float = -38.0,
    min_peak_volume_db: float = -24.0,
    max_peak_volume_db: float = -0.1,
    max_silence_segment_sec: float = 2.25,
) -> tuple[list[str], list[str]]:
    defects: list[str] = []
    warnings: list[str] = []
    if not report.video_codec:
        defects.append("missing_video_stream")
    if not report.audio_codec:
        defects.append("missing_audio_stream")
    if report.expected_width and report.width != report.expected_width:
        defects.append(f"width={report.width}, expected={report.expected_width}")
    if report.expected_height and report.height != report.expected_height:
        defects.append(f"height={report.height}, expected={report.expected_height}")
    if report.expected_fps and (report.fps is None or abs(report.fps - report.expected_fps) > fps_tolerance):
        defects.append(f"fps={_display_number(report.fps)}, expected={_display_number(report.expected_fps)}")
    actual_duration = report.format_duration_sec or report.video_duration_sec
    if (
        report.expected_duration_sec is not None
        and actual_duration is not None
        and abs(actual_duration - report.expected_duration_sec) > duration_tolerance_sec
    ):
        defects.append(
            "duration_mismatch="
            f"{_display_number(actual_duration)}s, expected={_display_number(report.expected_duration_sec)}s"
        )
    if (
        report.video_duration_sec is not None
        and report.audio_duration_sec is not None
        and abs(report.video_duration_sec - report.audio_duration_sec) > av_duration_tolerance_sec
    ):
        defects.append(
            "audio_video_duration_mismatch="
            f"video={_display_number(report.video_duration_sec)}s,"
            f" audio={_display_number(report.audio_duration_sec)}s"
        )
    if report.audio_codec:
        if report.mean_volume_db is None or report.max_volume_db is None:
            defects.append("audio_volume_unavailable")
        else:
            if report.mean_volume_db < min_mean_volume_db or report.max_volume_db < min_peak_volume_db:
                defects.append(
                    "audio_too_quiet="
                    f"mean={_display_number(report.mean_volume_db)}dB,"
                    f" max={_display_number(report.max_volume_db)}dB"
                )
            if report.max_volume_db > max_peak_volume_db:
                defects.append(f"audio_peak_clipping_risk=max={_display_number(report.max_volume_db)}dB")
    for segment in report.silence_segments:
        if segment.duration_sec > max_silence_segment_sec:
            defects.append(
                "long_audio_silence="
                f"{_display_number(segment.start_sec)}-{_display_number(segment.end_sec)}s"
                f" ({_display_number(segment.duration_sec)}s)"
            )
    if report.audio_bit_rate is not None and report.audio_bit_rate < 96000:
        warnings.append(f"low_audio_bitrate={report.audio_bit_rate}")
    if report.video_bit_rate is not None and report.video_bit_rate < 1800000:
        warnings.append(f"low_video_bitrate={report.video_bit_rate}")
    return defects, warnings


def parse_volumedetect(output: str) -> tuple[float | None, float | None]:
    mean_match = re.search(r"\bmean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", output)
    max_match = re.search(r"\bmax_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", output)
    mean_volume = float(mean_match.group(1)) if mean_match else None
    max_volume = float(max_match.group(1)) if max_match else None
    return mean_volume, max_volume


def parse_silencedetect(output: str) -> list[SilenceSegment]:
    segments: list[SilenceSegment] = []
    pending_start: float | None = None
    for line in output.splitlines():
        start_match = re.search(r"\bsilence_start:\s*(-?\d+(?:\.\d+)?)", line)
        if start_match:
            pending_start = float(start_match.group(1))
            continue
        end_match = re.search(r"\bsilence_end:\s*(-?\d+(?:\.\d+)?)", line)
        if not end_match:
            continue
        duration_match = re.search(r"\bsilence_duration:\s*(-?\d+(?:\.\d+)?)", line)
        end = float(end_match.group(1))
        duration = float(duration_match.group(1)) if duration_match else 0.0
        start = pending_start if pending_start is not None else max(0.0, end - duration)
        segments.append(
            SilenceSegment(
                start_sec=round(start, 3),
                end_sec=round(end, 3),
                duration_sec=round(max(0.0, duration), 3),
            )
        )
        pending_start = None
    return segments


def ffprobe_json(video_path: Path) -> Json:
    ffprobe = _media_binary_path("ffprobe")
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_media_binary_env(ffprobe),
        check=True,
    )
    return json.loads(completed.stdout)


def ffmpeg_audio_filter_output(video_path: Path, filters: list[str]) -> str:
    ffmpeg = _media_binary_path("ffmpeg")
    completed = subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-i",
            str(video_path),
            "-af",
            ",".join(filters),
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_media_binary_env(ffmpeg),
        check=True,
    )
    return f"{completed.stdout}\n{completed.stderr}"


def _media_binary_path(name: str) -> Path:
    env_key = f"{name.upper()}_PATH"
    configured = os.getenv(env_key)
    if configured and Path(configured).exists():
        return Path(configured)
    system = shutil.which(name)
    if system:
        return Path(system)
    root = Path(__file__).resolve().parents[2]
    candidates = [
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
        root / "remotion" / "node_modules" / "@remotion" / "compositor-darwin-arm64" / name,
        root / "remotion" / "node_modules" / "@remotion" / "compositor-linux-x64-gnu" / name,
        root / "remotion" / "node_modules" / "@remotion" / "compositor-linux-arm64-gnu" / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(name)


def _media_binary_env(binary: Path) -> dict[str, str]:
    env = dict(os.environ)
    if binary.is_absolute():
        binary_dir = str(binary.parent.resolve())
        existing_dyld = env.get("DYLD_LIBRARY_PATH", "")
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        env["DYLD_LIBRARY_PATH"] = f"{binary_dir}:{existing_dyld}" if existing_dyld else binary_dir
        env["LD_LIBRARY_PATH"] = f"{binary_dir}:{existing_ld}" if existing_ld else binary_dir
    return env


def _first_stream(streams: list[Any], codec_type: str) -> Json:
    for raw_stream in streams:
        stream = raw_stream if isinstance(raw_stream, dict) else {}
        if stream.get("codec_type") == codec_type:
            return stream
    return {}


def _ratio_to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text == "0/0":
        return None
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        num = _positive_float(numerator)
        den = _positive_float(denominator)
        if num is not None and den:
            return round(num / den, 4)
        return None
    parsed = _positive_float(text)
    return round(parsed, 4) if parsed is not None else None


def _positive_int(value: Any) -> int | None:
    parsed = _positive_float(value)
    return int(parsed) if parsed is not None else None


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _display_number(value: float | None) -> str:
    if value is None:
        return "missing"
    return f"{value:.3f}".rstrip("0").rstrip(".")
