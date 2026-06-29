from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from reddit2video.render_visual_smoke import (
    RegionVisualMetrics,
    SceneRenderVisualInspection,
    _blocking_defects,
    _media_binary_path,
    image_region_metrics,
    lower_media_region_metrics,
    sample_frame_for_scene,
    scene_expected_media,
    timeline_sample_frames_for_scene,
    visual_smoke_flags,
    visual_substance_defects,
    visual_substance_flags,
)


def test_visual_smoke_binary_lookup_prefers_env(monkeypatch, tmp_path: Path) -> None:
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("FFMPEG_PATH", str(ffmpeg))

    assert _media_binary_path("ffmpeg") == ffmpeg


def test_visual_smoke_flags_dark_media_region_under_title_card() -> None:
    image = Image.new("RGB", (720, 1280), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 430, 720, 1210], fill=(10, 10, 10))
    draw.text((80, 120), "TITLE CARD", fill=(20, 20, 20))

    flags = visual_smoke_flags(
        full_frame=image_region_metrics(image),
        lower_media_region=lower_media_region_metrics(image),
        expected_media=True,
    )

    assert "media_region_dark" in flags


def test_visual_smoke_allows_intentional_dark_poster_without_media() -> None:
    image = Image.new("RGB", (720, 1280), (24, 24, 28))
    draw = ImageDraw.Draw(image)
    draw.text((120, 500), "POSTER BEAT", fill=(245, 245, 245))

    flags = visual_smoke_flags(
        full_frame=image_region_metrics(image),
        lower_media_region=lower_media_region_metrics(image),
        expected_media=False,
    )

    assert "media_region_dark" not in flags


def test_visual_smoke_allows_saturated_dark_media() -> None:
    image = Image.new("RGB", (720, 1280), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 430, 720, 1210], fill=(8, 8, 8))
    for y in range(520, 1110, 70):
        draw.line([(40, y), (680, y + 30)], fill=(255, 32, 45), width=24)
    draw.ellipse([360, 650, 690, 1060], outline=(255, 45, 20), width=40)

    flags = visual_smoke_flags(
        full_frame=image_region_metrics(image),
        lower_media_region=lower_media_region_metrics(image),
        expected_media=True,
    )

    assert "media_region_dark" not in flags


def test_visual_smoke_allows_readable_dark_media_with_frame_detail() -> None:
    flags = visual_smoke_flags(
        full_frame=RegionVisualMetrics(
            luma_mean=118.9,
            luma_std=87.9,
            saturation_mean=24.5,
            edge_mean=8.3,
            dark_pixel_ratio=0.33,
            bright_pixel_ratio=0.02,
        ),
        lower_media_region=RegionVisualMetrics(
            luma_mean=64.4,
            luma_std=69.8,
            saturation_mean=33.8,
            edge_mean=12.3,
            dark_pixel_ratio=0.56,
            bright_pixel_ratio=0.02,
        ),
        expected_media=True,
    )

    assert "media_region_dark" not in flags


def test_scene_expected_media_counts_html_and_bridge_assets() -> None:
    assert scene_expected_media({"html": '<div data-asset-id="a1"></div>'})
    assert scene_expected_media({"html": "", "bridge_media_assets": [{"src": "__STATIC_FILE__x.mp4"}]})
    assert not scene_expected_media(
        {
            "html": "",
            "semantic_visual": {
                "id": "semantic-1",
                "kind": "semantic_motion",
                "quality": "publishable_visual",
                "motifs": ["evidence_cards", "signal_line"],
            },
        }
    )
    assert not scene_expected_media({"html": "<div></div>", "bridge_media_assets": []})
    assert not scene_expected_media(
        {
            "html": "",
            "semantic_visual": {
                "id": "semantic-1",
                "kind": "semantic_motion",
                "quality": "placeholder",
                "motifs": ["one"],
            },
        }
    )


def test_timeline_blocking_defects_allow_early_staged_blank() -> None:
    early = _inspection(scene_id=1, weak=False)
    early.sample_label = "early"
    early.flags = ["pale_blank_frame"]
    late = _inspection(scene_id=1, weak=False)
    late.sample_label = "late"
    late.flags = ["media_region_dark"]

    defects = _blocking_defects([early, late], allow_early_staged_blank=True)

    assert defects == ["scene 1 late: media_region_dark"]


def test_sample_frame_stays_inside_scene() -> None:
    assert sample_frame_for_scene(start_frame=100, duration_frames=90) in range(100, 190)
    assert sample_frame_for_scene(start_frame=100, duration_frames=4) in range(100, 104)


def test_timeline_sample_frames_cover_early_mid_late_without_edges() -> None:
    samples = timeline_sample_frames_for_scene(start_frame=100, duration_frames=90)

    assert [label for label, _, _ in samples] == ["early", "mid", "late"]
    assert [frame for _, _, frame in samples] == sorted(frame for _, _, frame in samples)
    assert all(frame in range(108, 182) for _, _, frame in samples)


def test_timeline_sample_frames_handles_short_scenes() -> None:
    samples = timeline_sample_frames_for_scene(start_frame=100, duration_frames=4)

    assert samples == [("mid", 0.52, 102)]


def test_visual_substance_flags_flat_claimed_media() -> None:
    flags = visual_substance_flags(
        full_frame=_metrics(edge=7.0, saturation=12.0, luma_std=32.0),
        lower_media_region=_metrics(edge=5.0, saturation=12.0, luma_std=30.0),
        expected_media=True,
    )

    assert flags == ["weak_media_substance"]


def test_visual_substance_ignores_intentional_text_card_without_media() -> None:
    flags = visual_substance_flags(
        full_frame=_metrics(edge=7.0, saturation=12.0, luma_std=32.0),
        lower_media_region=_metrics(edge=5.0, saturation=12.0, luma_std=30.0),
        expected_media=False,
    )

    assert flags == []


def test_visual_substance_allows_isolated_weak_media_sample() -> None:
    inspections = [_inspection(scene_id=index, weak=index == 3) for index in range(1, 9)]

    assert visual_substance_defects(inspections) == []


def test_visual_substance_defects_ignore_early_staged_samples() -> None:
    inspections = []
    for index in range(1, 9):
        early = _inspection(scene_id=index, weak=True)
        early.sample_label = "early"
        mid = _inspection(scene_id=index, weak=False)
        mid.sample_label = "mid"
        late = _inspection(scene_id=index, weak=False)
        late.sample_label = "late"
        inspections.extend([early, mid, late])

    assert visual_substance_defects(inspections) == []


def test_visual_substance_blocks_systemically_weak_media() -> None:
    inspections = [_inspection(scene_id=index, weak=index <= 5) for index in range(1, 13)]

    defects = visual_substance_defects(inspections)

    assert any(defect.startswith("media_visual_substance_too_weak=") for defect in defects)
    assert any(defect.startswith("media_scene_substance_too_weak=") for defect in defects)


def test_visual_substance_blocks_long_weak_media_run() -> None:
    inspections = [_inspection(scene_id=index, weak=index <= 4) for index in range(1, 9)]

    defects = visual_substance_defects(inspections, max_weak_media_sample_ratio=1.0, max_weak_media_scene_ratio=1.0)

    assert "weak_media_substance_run=4 consecutive media scenes flagged weak_media_substance" in defects


def _inspection(scene_id: int, *, weak: bool) -> SceneRenderVisualInspection:
    lower = _metrics(edge=5.0, saturation=12.0, luma_std=30.0) if weak else _metrics(
        edge=9.0,
        saturation=62.0,
        luma_std=58.0,
    )
    full = _metrics(edge=7.0 if weak else 11.0, saturation=lower.saturation_mean, luma_std=lower.luma_std)
    return SceneRenderVisualInspection(
        scene_id=scene_id,
        start_frame=scene_id * 30,
        duration_frames=30,
        sample_frame=scene_id * 30 + 15,
        sample_sec=scene_id + 0.5,
        expected_media=True,
        full_frame=full,
        lower_media_region=lower,
        flags=[],
        substance_flags=visual_substance_flags(
            full_frame=full,
            lower_media_region=lower,
            expected_media=True,
        ),
    )


def _metrics(*, edge: float, saturation: float, luma_std: float) -> RegionVisualMetrics:
    return RegionVisualMetrics(
        luma_mean=140.0,
        luma_std=luma_std,
        saturation_mean=saturation,
        edge_mean=edge,
        dark_pixel_ratio=0.01,
        bright_pixel_ratio=0.02,
    )
