from __future__ import annotations

import os
from pathlib import Path
import math
import re
import shutil
import subprocess
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat
from pydantic import BaseModel, Field


Json = dict[str, Any]


class RegionVisualMetrics(BaseModel):
    luma_mean: float
    luma_std: float
    saturation_mean: float
    edge_mean: float
    dark_pixel_ratio: float
    bright_pixel_ratio: float


class SceneRenderVisualInspection(BaseModel):
    scene_id: int
    start_frame: int
    duration_frames: int
    sample_label: Literal["early", "mid", "late"] = "mid"
    sample_position: float = 0.52
    sample_frame: int
    sample_sec: float
    expected_media: bool
    frame_path: str = ""
    full_frame: RegionVisualMetrics
    lower_media_region: RegionVisualMetrics
    flags: list[str] = Field(default_factory=list)
    substance_flags: list[str] = Field(default_factory=list)


class RenderVisualSmokeReport(BaseModel):
    verdict: Literal["pass", "fail"]
    blocking_defects: list[str] = Field(default_factory=list)
    video_path: str
    payload_path: str = ""
    fps: float
    scene_count: int
    flagged_scene_count: int
    media_sample_count: int = 0
    weak_media_sample_count: int = 0
    weak_media_scene_count: int = 0
    contact_sheet_path: str = ""
    frames_dir: str = ""
    timeline_sample_count: int = 0
    timeline_flagged_sample_count: int = 0
    timeline_media_sample_count: int = 0
    timeline_weak_media_sample_count: int = 0
    timeline_weak_media_scene_count: int = 0
    timeline_contact_sheet_path: str = ""
    timeline_frames_dir: str = ""
    scenes: list[SceneRenderVisualInspection] = Field(default_factory=list)
    timeline_samples: list[SceneRenderVisualInspection] = Field(default_factory=list)


def inspect_render_visual_smoke(
    *,
    video_path: Path,
    payload: Json,
    frames_dir: Path,
    contact_sheet_path: Path | None = None,
    timeline_frames_dir: Path | None = None,
    timeline_contact_sheet_path: Path | None = None,
    payload_path: Path | None = None,
) -> RenderVisualSmokeReport:
    scenes = payload.get("scenes") if isinstance(payload.get("scenes"), list) else []
    fps = _positive_float(payload.get("fps")) or 30.0
    frames_dir.mkdir(parents=True, exist_ok=True)

    inspections: list[SceneRenderVisualInspection] = []
    timeline_inspections: list[SceneRenderVisualInspection] = []
    for fallback, raw_scene in enumerate(scenes, start=1):
        scene = raw_scene if isinstance(raw_scene, dict) else {}
        scene_id = _scene_id(scene, fallback=fallback)
        start_frame = int(_positive_float(scene.get("start_frame")) or 0)
        duration_frames = int(_positive_float(scene.get("duration_frames")) or 1)
        sample_frame = sample_frame_for_scene(start_frame=start_frame, duration_frames=duration_frames)
        expected_media = scene_expected_media(scene)
        inspections.append(
            inspect_scene_render_frame(
                video_path=video_path,
                fps=fps,
                scene_id=scene_id,
                start_frame=start_frame,
                duration_frames=duration_frames,
                sample_frame=sample_frame,
                sample_label="mid",
                sample_position=0.52,
                expected_media=expected_media,
                frame_path=frames_dir / f"scene-{scene_id:03d}-{sample_frame:06d}.jpg",
            )
        )
        if timeline_frames_dir:
            for sample_label, sample_position, timeline_frame in timeline_sample_frames_for_scene(
                start_frame=start_frame,
                duration_frames=duration_frames,
            ):
                timeline_inspections.append(
                    inspect_scene_render_frame(
                        video_path=video_path,
                        fps=fps,
                        scene_id=scene_id,
                        start_frame=start_frame,
                        duration_frames=duration_frames,
                        sample_frame=timeline_frame,
                        sample_label=sample_label,
                        sample_position=sample_position,
                        expected_media=expected_media,
                        frame_path=timeline_frames_dir
                        / f"scene-{scene_id:03d}-{sample_label}-{timeline_frame:06d}.jpg",
                    )
                )

    if contact_sheet_path:
        write_contact_sheet(inspections, out_path=contact_sheet_path)
    if timeline_contact_sheet_path:
        write_contact_sheet(timeline_inspections, out_path=timeline_contact_sheet_path, columns=6)

    defects = _blocking_defects(inspections)
    defects.extend(
        _blocking_defects(
            [sample for sample in timeline_inspections if sample.sample_label != "mid"],
            allow_early_staged_blank=True,
        )
    )
    substance_source = timeline_inspections or inspections
    defects.extend(visual_substance_defects(substance_source))
    weak_mid_samples = [scene for scene in inspections if scene.expected_media and scene.substance_flags]
    weak_timeline_samples = [scene for scene in timeline_inspections if scene.expected_media and scene.substance_flags]
    return RenderVisualSmokeReport(
        verdict="fail" if defects else "pass",
        blocking_defects=defects,
        video_path=str(video_path),
        payload_path=str(payload_path or ""),
        fps=fps,
        scene_count=len(inspections),
        flagged_scene_count=sum(1 for scene in inspections if scene.flags),
        media_sample_count=sum(1 for scene in inspections if scene.expected_media),
        weak_media_sample_count=len(weak_mid_samples),
        weak_media_scene_count=len({scene.scene_id for scene in weak_mid_samples}),
        contact_sheet_path=str(contact_sheet_path or ""),
        frames_dir=str(frames_dir),
        timeline_sample_count=len(timeline_inspections),
        timeline_flagged_sample_count=sum(1 for scene in timeline_inspections if scene.flags),
        timeline_media_sample_count=sum(1 for scene in timeline_inspections if scene.expected_media),
        timeline_weak_media_sample_count=len(weak_timeline_samples),
        timeline_weak_media_scene_count=len({scene.scene_id for scene in weak_timeline_samples}),
        timeline_contact_sheet_path=str(timeline_contact_sheet_path or ""),
        timeline_frames_dir=str(timeline_frames_dir or ""),
        scenes=inspections,
        timeline_samples=timeline_inspections,
    )


def inspect_scene_render_frame(
    *,
    video_path: Path,
    fps: float,
    scene_id: int,
    start_frame: int,
    duration_frames: int,
    sample_frame: int,
    sample_label: Literal["early", "mid", "late"],
    sample_position: float,
    expected_media: bool,
    frame_path: Path,
) -> SceneRenderVisualInspection:
    sample_sec = round(sample_frame / fps, 3)
    extract_video_frame(video_path=video_path, timestamp_sec=sample_sec, out_path=frame_path)

    image = Image.open(frame_path).convert("RGB")
    full = image_region_metrics(image)
    lower = lower_media_region_metrics(image)
    flags = visual_smoke_flags(full_frame=full, lower_media_region=lower, expected_media=expected_media)
    substance_flags = visual_substance_flags(
        full_frame=full,
        lower_media_region=lower,
        expected_media=expected_media,
    )
    return SceneRenderVisualInspection(
        scene_id=scene_id,
        start_frame=start_frame,
        duration_frames=duration_frames,
        sample_label=sample_label,
        sample_position=sample_position,
        sample_frame=sample_frame,
        sample_sec=sample_sec,
        expected_media=expected_media,
        frame_path=str(frame_path),
        full_frame=full,
        lower_media_region=lower,
        flags=flags,
        substance_flags=substance_flags,
    )


def sample_frame_for_scene(*, start_frame: int, duration_frames: int) -> int:
    duration = max(1, int(duration_frames))
    if duration <= 4:
        return start_frame + max(0, duration // 2)
    margin = min(8, max(1, duration // 4))
    target = int(round(duration * 0.52))
    offset = max(margin, min(duration - margin, target))
    return start_frame + offset


def timeline_sample_frames_for_scene(
    *,
    start_frame: int,
    duration_frames: int,
) -> list[tuple[Literal["early", "mid", "late"], float, int]]:
    duration = max(1, int(duration_frames))
    if duration <= 4:
        return [("mid", 0.52, start_frame + max(0, duration // 2))]
    margin = min(8, max(1, duration // 6))
    samples: list[tuple[Literal["early", "mid", "late"], float, int]] = []
    used_frames: set[int] = set()
    for label, position in (("early", 0.18), ("mid", 0.52), ("late", 0.84)):
        target = int(round(duration * position))
        offset = max(margin, min(duration - margin, target))
        frame = start_frame + offset
        if frame in used_frames:
            continue
        used_frames.add(frame)
        samples.append((label, position, frame))
    return samples


def scene_expected_media(scene: Json) -> bool:
    html = str(scene.get("html") or "")
    if re.search(r"\bdata-asset-id=(['\"])(?P<id>.+?)(\1)", html, flags=re.I | re.S):
        return True
    assets = scene.get("bridge_media_assets")
    if isinstance(assets, list):
        if any(isinstance(asset, dict) and str(asset.get("src") or "").strip() for asset in assets):
            return True
    return False


def image_region_metrics(image: Image.Image) -> RegionVisualMetrics:
    rgb = image.convert("RGB")
    gray = rgb.convert("L")
    gray_stat = ImageStat.Stat(gray)
    saturation = ImageStat.Stat(rgb.convert("HSV").getchannel("S")).mean[0]
    edge = gray.filter(ImageFilter.FIND_EDGES)
    edge_mean = ImageStat.Stat(edge).mean[0]
    histogram = gray.histogram()
    total = max(1, sum(histogram))
    dark_ratio = sum(histogram[:45]) / total
    bright_ratio = sum(histogram[235:]) / total
    return RegionVisualMetrics(
        luma_mean=round(gray_stat.mean[0], 3),
        luma_std=round(gray_stat.stddev[0], 3),
        saturation_mean=round(saturation, 3),
        edge_mean=round(edge_mean, 3),
        dark_pixel_ratio=round(dark_ratio, 4),
        bright_pixel_ratio=round(bright_ratio, 4),
    )


def lower_media_region_metrics(image: Image.Image) -> RegionVisualMetrics:
    width, height = image.size
    top = int(height * 0.34)
    bottom = int(height * 0.94)
    return image_region_metrics(image.crop((0, top, width, bottom)))


def visual_smoke_flags(
    *,
    full_frame: RegionVisualMetrics,
    lower_media_region: RegionVisualMetrics,
    expected_media: bool,
) -> list[str]:
    flags: list[str] = []
    if full_frame.luma_mean < 35 and full_frame.edge_mean < 18:
        flags.append("dark_frame")
    if full_frame.luma_std < 14 and full_frame.edge_mean < 10:
        flags.append("flat_frame")
    if full_frame.luma_mean > 226 and full_frame.saturation_mean < 30 and full_frame.edge_mean < 18:
        flags.append("pale_blank_frame")
    if expected_media:
        readable_dark_media = (
            full_frame.luma_mean >= 108
            and full_frame.luma_std >= 42
            and full_frame.edge_mean >= 6.0
            and lower_media_region.edge_mean >= 8.0
        )
        if (
            lower_media_region.dark_pixel_ratio >= 0.55
            and lower_media_region.luma_mean < 86
            and lower_media_region.saturation_mean < 45
            and lower_media_region.edge_mean < 34
            and not readable_dark_media
        ):
            flags.append("media_region_dark")
        if (
            lower_media_region.luma_std < 12
            and lower_media_region.edge_mean < 11
            and (lower_media_region.dark_pixel_ratio > 0.45 or lower_media_region.bright_pixel_ratio > 0.75)
        ):
            flags.append("media_region_flat")
    return flags


def visual_substance_flags(
    *,
    full_frame: RegionVisualMetrics,
    lower_media_region: RegionVisualMetrics,
    expected_media: bool,
) -> list[str]:
    if not expected_media:
        return []
    if (
        lower_media_region.edge_mean < 5.8
        and lower_media_region.saturation_mean < 24
        and lower_media_region.luma_std < 36
    ):
        return ["weak_media_substance"]
    if (
        lower_media_region.edge_mean < 7.5
        and lower_media_region.saturation_mean < 20
        and lower_media_region.luma_std < 42
        and full_frame.edge_mean < 10
    ):
        return ["weak_media_substance"]
    return []


def visual_substance_defects(
    inspections: list[SceneRenderVisualInspection],
    *,
    max_weak_media_sample_ratio: float = 0.28,
    max_weak_media_scene_ratio: float = 0.28,
    max_weak_media_scene_run: int = 3,
) -> list[str]:
    media_samples = [
        scene
        for scene in inspections
        if scene.expected_media and scene.sample_label != "early"
    ]
    if not media_samples:
        return []
    weak_samples = [scene for scene in media_samples if scene.substance_flags]
    sample_ratio = len(weak_samples) / len(media_samples)

    scene_sample_counts: dict[int, int] = {}
    scene_weak_counts: dict[int, int] = {}
    for scene in media_samples:
        scene_sample_counts[scene.scene_id] = scene_sample_counts.get(scene.scene_id, 0) + 1
        if scene.substance_flags:
            scene_weak_counts[scene.scene_id] = scene_weak_counts.get(scene.scene_id, 0) + 1
    weak_scene_ids = {
        scene_id
        for scene_id, total in scene_sample_counts.items()
        if total > 0 and scene_weak_counts.get(scene_id, 0) / total >= 0.67
    }
    scene_ratio = len(weak_scene_ids) / len(scene_sample_counts)
    max_run = _max_consecutive_weak_media_scenes(media_samples, weak_scene_ids)

    defects: list[str] = []
    if len(media_samples) >= 8 and sample_ratio > max_weak_media_sample_ratio:
        defects.append(
            "media_visual_substance_too_weak="
            f"{len(weak_samples)}/{len(media_samples)} samples flagged weak_media_substance"
        )
    if len(scene_sample_counts) >= 6 and scene_ratio > max_weak_media_scene_ratio:
        defects.append(
            "media_scene_substance_too_weak="
            f"{len(weak_scene_ids)}/{len(scene_sample_counts)} media scenes flagged weak_media_substance"
        )
    if max_run > max_weak_media_scene_run:
        defects.append(
            "weak_media_substance_run="
            f"{max_run} consecutive media scenes flagged weak_media_substance"
        )
    return defects


def extract_video_frame(*, video_path: Path, timestamp_sec: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _media_binary_path("ffmpeg")
    subprocess.run(
        [
            str(ffmpeg),
            "-y",
            "-ss",
            f"{timestamp_sec:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_media_binary_env(ffmpeg),
        check=True,
    )


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


def write_contact_sheet(
    inspections: list[SceneRenderVisualInspection],
    *,
    out_path: Path,
    columns: int = 4,
    tile_width: int = 180,
    tile_height: int = 320,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not inspections:
        Image.new("RGB", (tile_width, tile_height), (18, 18, 18)).save(out_path, quality=92)
        return
    font, font_bold = _load_fonts()
    label_height = 28
    tiles: list[Image.Image] = []
    for scene in inspections:
        source = Image.open(scene.frame_path).convert("RGB")
        thumb = source.resize((tile_width, tile_height), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (tile_width, tile_height + label_height), "white")
        tile.paste(thumb, (0, 0))
        draw = ImageDraw.Draw(tile)
        has_substance_warning = bool(scene.substance_flags)
        label_bg = (20, 20, 20) if scene.flags else (255, 244, 202) if has_substance_warning else (255, 255, 255)
        label_fg = (255, 255, 255) if scene.flags else (20, 20, 20)
        draw.rectangle([0, tile_height, tile_width, tile_height + label_height], fill=label_bg)
        sample_label = "" if scene.sample_label == "mid" else f" {scene.sample_label}"
        draw.text(
            (6, tile_height + 2),
            f"s{scene.scene_id:02d}{sample_label} {scene.sample_sec:04.1f}s",
            fill=label_fg,
            font=font_bold,
        )
        finding_labels = scene.flags or scene.substance_flags
        if finding_labels:
            draw.text((96, tile_height + 6), ",".join(finding_labels)[:12], fill=(140, 84, 20), font=font)
        tiles.append(tile)

    rows = math.ceil(len(tiles) / columns)
    sheet = Image.new("RGB", (columns * tile_width, rows * (tile_height + label_height)), (18, 18, 18))
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % columns) * tile_width, (index // columns) * (tile_height + label_height)))
    sheet.save(out_path, quality=92)


def _blocking_defects(
    inspections: list[SceneRenderVisualInspection],
    *,
    allow_early_staged_blank: bool = False,
) -> list[str]:
    defects: list[str] = []
    for scene in inspections:
        for flag in scene.flags:
            if allow_early_staged_blank and scene.sample_label == "early" and flag == "pale_blank_frame":
                continue
            label = "" if scene.sample_label == "mid" else f" {scene.sample_label}"
            defects.append(f"scene {scene.scene_id}{label}: {flag}")
    return defects


def _max_consecutive_weak_media_scenes(
    inspections: list[SceneRenderVisualInspection],
    weak_scene_ids: set[int],
) -> int:
    ordered_scene_ids: list[int] = []
    seen: set[int] = set()
    for scene in inspections:
        if not scene.expected_media or scene.scene_id in seen:
            continue
        ordered_scene_ids.append(scene.scene_id)
        seen.add(scene.scene_id)
    best = 0
    current = 0
    for scene_id in ordered_scene_ids:
        if scene_id in weak_scene_ids:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _scene_id(scene: Json, *, fallback: int) -> int:
    value = scene.get("scene_id") or fallback
    try:
        return int(float(value))
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value or ""))
        return int(match.group(0)) if match else fallback


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _load_fonts() -> tuple[ImageFont.ImageFont, ImageFont.ImageFont]:
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 15)
        font_bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 18)
        return font, font_bold
    except Exception:
        fallback = ImageFont.load_default()
        return fallback, fallback
