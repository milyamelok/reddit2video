from __future__ import annotations

from pathlib import Path

from reddit2video.render_av_integrity import (
    RenderAVIntegrityReport,
    _media_binary_path,
    av_integrity_findings,
    expected_duration_from_payload,
    parse_silencedetect,
    parse_volumedetect,
    summarize_probe,
)


def test_av_integrity_binary_lookup_prefers_env(monkeypatch, tmp_path: Path) -> None:
    ffprobe = tmp_path / "ffprobe"
    ffprobe.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("FFPROBE_PATH", str(ffprobe))

    assert _media_binary_path("ffprobe") == ffprobe


def test_expected_duration_from_payload_uses_duration_frames() -> None:
    assert expected_duration_from_payload({"fps": 30, "duration_frames": 1575}) == 52.5


def test_expected_duration_from_payload_falls_back_to_scene_end() -> None:
    assert expected_duration_from_payload(
        {
            "fps": 30,
            "scenes": [
                {"start_frame": 0, "duration_frames": 45},
                {"start_frame": 45, "duration_frames": 75},
            ],
        }
    ) == 4.0


def test_summarize_probe_extracts_av_fields() -> None:
    probe = {
        "format": {"duration": "12.500"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 720,
                "height": 1280,
                "avg_frame_rate": "30/1",
                "duration": "12.500",
                "bit_rate": "4000000",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "duration": "12.480",
                "sample_rate": "48000",
                "channels": 2,
                "bit_rate": "317000",
            },
        ],
    }

    summary = summarize_probe(probe)

    assert summary["video_codec"] == "h264"
    assert summary["audio_codec"] == "aac"
    assert summary["width"] == 720
    assert summary["height"] == 1280
    assert summary["fps"] == 30.0
    assert summary["audio_sample_rate"] == 48000


def test_parse_volumedetect() -> None:
    output = """
    [Parsed_volumedetect_0] mean_volume: -23.6 dB
    [Parsed_volumedetect_0] max_volume: -7.2 dB
    """

    assert parse_volumedetect(output) == (-23.6, -7.2)


def test_parse_silencedetect() -> None:
    output = """
    [silencedetect @ 0x1] silence_start: 10.22
    [silencedetect @ 0x1] silence_end: 11.18 | silence_duration: 0.96
    """

    assert parse_silencedetect(output)[0].model_dump() == {
        "start_sec": 10.22,
        "end_sec": 11.18,
        "duration_sec": 0.96,
    }


def test_av_integrity_blocks_missing_audio_and_wrong_shape() -> None:
    report = RenderAVIntegrityReport(
        verdict="pass",
        video_path="video.mp4",
        expected_width=720,
        expected_height=1280,
        expected_fps=30,
        expected_duration_sec=10,
        format_duration_sec=10,
        video_duration_sec=10,
        width=1080,
        height=1920,
        fps=24,
        video_codec="h264",
        audio_codec="",
    )

    defects, _ = av_integrity_findings(report)

    assert "missing_audio_stream" in defects
    assert "width=1080, expected=720" in defects
    assert "height=1920, expected=1280" in defects
    assert "fps=24, expected=30" in defects


def test_av_integrity_blocks_quiet_audio_and_long_silence() -> None:
    report = RenderAVIntegrityReport(
        verdict="pass",
        video_path="video.mp4",
        expected_width=720,
        expected_height=1280,
        expected_fps=30,
        expected_duration_sec=10,
        format_duration_sec=10,
        video_duration_sec=10,
        audio_duration_sec=10,
        width=720,
        height=1280,
        fps=30,
        video_codec="h264",
        audio_codec="aac",
        mean_volume_db=-45,
        max_volume_db=-30,
        silence_segments=[{"start_sec": 4, "end_sec": 7, "duration_sec": 3}],
    )

    defects, _ = av_integrity_findings(report)

    assert any(defect.startswith("audio_too_quiet=") for defect in defects)
    assert any(defect.startswith("long_audio_silence=") for defect in defects)


def test_av_integrity_allows_current_publication_shape() -> None:
    report = RenderAVIntegrityReport(
        verdict="pass",
        video_path="video.mp4",
        expected_width=720,
        expected_height=1280,
        expected_fps=30,
        expected_duration_sec=52.5,
        format_duration_sec=52.501,
        video_duration_sec=52.467,
        audio_duration_sec=52.501,
        width=720,
        height=1280,
        fps=30,
        video_codec="h264",
        audio_codec="aac",
        audio_bit_rate=317375,
        video_bit_rate=4053927,
        mean_volume_db=-23.6,
        max_volume_db=-7.2,
    )

    defects, warnings = av_integrity_findings(report)

    assert defects == []
    assert warnings == []
