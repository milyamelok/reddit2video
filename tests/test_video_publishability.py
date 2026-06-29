from __future__ import annotations

from reddit2video.video_publishability import inspect_html_payload


def test_publishability_passes_media_rich_payload() -> None:
    payload = {
        "fps": 30,
        "duration_frames": 900,
        "audio_public_path": "audio/story.mp3",
        "scenes": [
            _scene(1, "a", with_media=True),
            _scene(2, "b", with_media=True),
            _scene(3, "c", with_media=False),
            _scene(4, "d", with_media=True, video=True),
            _scene(5, "e", with_media=True),
            _scene(6, "f", with_media=False),
            _scene(7, "g", with_media=True),
            _scene(8, "h", with_media=True),
        ],
    }

    report = inspect_html_payload(
        payload,
        min_scenes=8,
        min_duration_sec=20,
        min_media_scene_ratio=0.5,
        min_unique_assets=5,
        max_text_only_run=2,
    )

    assert report.verdict == "pass"
    assert report.media_scene_count == 6
    assert report.unique_asset_count == 6
    assert report.video_asset_count == 1
    assert report.visual_archetype_count >= 4
    assert not any("Every scene uses sync_caption_mode=replace" in warning for warning in report.warnings)


def test_publishability_fails_single_text_collapse() -> None:
    payload = {
        "fps": 30,
        "duration_frames": 900,
        "audio_public_path": "audio/story.mp3",
        "scenes": [_scene(index, f"text {index}", with_media=False) for index in range(1, 9)],
    }

    report = inspect_html_payload(
        payload,
        min_scenes=8,
        min_duration_sec=20,
        min_media_scene_ratio=0.5,
        min_unique_assets=5,
        max_text_only_run=2,
    )

    assert report.verdict == "fail"
    assert "Every scene is text-only" in " ".join(report.blocking_defects)
    assert report.max_text_only_run == 8


def test_publishability_blocks_all_static_assets_when_motion_required() -> None:
    payload = {
        "fps": 30,
        "duration_frames": 900,
        "audio_public_path": "audio/story.mp3",
        "scenes": [
            _scene(index, f"text {index}", with_media=True)
            for index in range(1, 9)
        ],
    }

    report = inspect_html_payload(
        payload,
        min_scenes=8,
        min_duration_sec=20,
        min_media_scene_ratio=1.0,
        min_unique_assets=8,
        min_video_assets=1,
        max_text_only_run=1,
    )

    assert report.verdict == "fail"
    assert report.video_asset_count == 0
    assert "Only 0 video assets" in " ".join(report.blocking_defects)


def test_publishability_counts_rendered_bridge_media_assets() -> None:
    payload = {
        "fps": 30,
        "duration_frames": 900,
        "audio_public_path": "audio/story.mp3",
        "scenes": [
            _scene(1, "a", with_media=True),
            _scene(2, "b", with_media=False, bridge_kind="video"),
            _scene(3, "c", with_media=False, bridge_kind="image"),
            _scene(4, "d", with_media=True),
            _scene(5, "e", with_media=True),
            _scene(6, "f", with_media=False, bridge_kind="video"),
            _scene(7, "g", with_media=True),
            _scene(8, "h", with_media=True),
        ],
    }

    report = inspect_html_payload(
        payload,
        min_scenes=8,
        min_duration_sec=20,
        min_media_scene_ratio=0.8,
        min_unique_assets=8,
        max_text_only_run=1,
    )

    assert report.verdict == "pass"
    assert report.media_scene_count == 8
    assert report.text_only_scene_count == 0
    assert report.video_asset_count == 2
    assert report.image_asset_count == 6


def test_publishability_counts_valid_semantic_visuals_without_accepting_empty_markers() -> None:
    payload = {
        "fps": 30,
        "duration_frames": 900,
        "audio_public_path": "audio/story.mp3",
        "scenes": [
            _scene(1, "a", with_media=True),
            _scene(2, "b", with_media=False, semantic_visual=True),
            _scene(3, "c", with_media=False, semantic_visual=True),
            _scene(4, "d", with_media=True),
            _scene(5, "e", with_media=True),
            _scene(6, "f", with_media=False, semantic_visual=True),
            _scene(7, "g", with_media=True),
            _scene(8, "h", with_media=False, semantic_visual=False, malformed_semantic_visual=True),
        ],
    }

    report = inspect_html_payload(
        payload,
        min_scenes=8,
        min_duration_sec=20,
        min_media_scene_ratio=1.0,
        min_unique_assets=7,
        max_text_only_run=1,
    )

    assert report.verdict == "fail"
    assert report.media_scene_count == 7
    assert report.generated_visual_count == 3
    assert report.scenes[1].generated_visual_asset_ids == ["semantic-2"]
    assert report.scenes[7].generated_visual_asset_ids == []
    assert "Only 88% of scenes" in " ".join(report.blocking_defects)
    assert "1 text-only scenes" not in " ".join(report.blocking_defects)


def test_publishability_blocks_repeated_semantic_visual_archetype_despite_unique_ids() -> None:
    payload = {
        "fps": 30,
        "duration_frames": 900,
        "audio_public_path": "audio/story.mp3",
        "scenes": [
            _scene(index, f"text {index}", with_media=False, semantic_visual=True)
            for index in range(1, 9)
        ],
    }

    report = inspect_html_payload(
        payload,
        min_scenes=8,
        min_duration_sec=20,
        min_media_scene_ratio=1.0,
        min_unique_assets=8,
        min_visual_archetypes=4,
        max_dominant_visual_archetype_ratio=0.55,
        max_text_only_run=1,
    )

    assert report.verdict == "fail"
    assert report.media_scene_count == 8
    assert report.unique_asset_count == 8
    assert report.generated_visual_count == 8
    assert report.visual_archetype_count == 1
    assert report.dominant_visual_archetype_ratio == 1.0
    assert "Only 1 visual archetypes" in " ".join(report.blocking_defects)
    assert "Dominant visual archetype appears in 100%" in " ".join(report.blocking_defects)


def test_publishability_blocks_generated_fallback_from_carrying_release() -> None:
    payload = {
        "fps": 30,
        "duration_frames": 900,
        "audio_public_path": "audio/story.mp3",
        "scenes": [
            _scene(1, "a", with_media=True),
            _scene(2, "b", with_media=True),
            *[
                _scene(
                    index,
                    f"text {index}",
                    with_media=False,
                    semantic_visual=True,
                    semantic_topic=f"topic-{index}",
                    semantic_layout=f"layout-{index}",
                )
                for index in range(3, 11)
            ],
        ],
    }

    report = inspect_html_payload(
        payload,
        min_scenes=8,
        min_duration_sec=20,
        min_media_scene_ratio=1.0,
        min_unique_assets=8,
        min_visual_archetypes=4,
        max_dominant_visual_archetype_ratio=0.55,
        min_real_media_scene_ratio=0.35,
        max_generated_visual_scene_ratio=0.65,
        max_text_only_run=1,
    )

    assert report.verdict == "fail"
    assert report.media_scene_count == 10
    assert report.real_media_scene_count == 2
    assert report.generated_visual_scene_count == 8
    assert report.generated_visual_scene_ratio == 0.8
    assert "Only 20% of scenes use real media" in " ".join(report.blocking_defects)
    assert "Generated fallback visuals appear in 80%" in " ".join(report.blocking_defects)


def _scene(
    scene_id: int,
    text: str,
    *,
    with_media: bool,
    video: bool = False,
    bridge_kind: str = "",
    semantic_visual: bool = False,
    semantic_topic: str = "",
    semantic_layout: str = "",
    malformed_semantic_visual: bool = False,
) -> dict:
    media = ""
    if with_media:
        extension = "mp4" if video else "jpg"
        tag = "video" if video else "div"
        src = f"__STATIC_FILE__assets/{scene_id}.{extension}"
        if video:
            media = f'<div data-asset-id="asset-{scene_id}"><{tag} src="{src}"></{tag}></div>'
        else:
            media = (
                f'<div data-asset-id="asset-{scene_id}" '
                f'style="background-image: url({src});"></div>'
            )
    scene = {
        "scene_id": scene_id,
        "duration_frames": 90,
        "html": (
            '<div data-scene-root="Scene001" data-sync-caption-mode="replace">'
            f"{media}"
            f'<div data-girly-sync-caption="true">{text}</div>'
            "</div>"
        ),
    }
    if bridge_kind:
        extension = "mp4" if bridge_kind == "video" else "jpg"
        scene["bridge_media_assets"] = [
            {
                "id": f"bridge-{scene_id}",
                "kind": bridge_kind,
                "src": f"__STATIC_FILE__assets/bridge-{scene_id}.{extension}",
                "role": "semantic_bridge",
            }
        ]
    if semantic_visual:
        scene["semantic_visual"] = {
            "id": f"semantic-{scene_id}",
            "kind": "semantic_motion",
            "quality": "publishable_visual",
            "topic": semantic_topic,
            "layout": semantic_layout,
            "motifs": ["evidence_cards", "signal_line"],
        }
    if malformed_semantic_visual:
        scene["semantic_visual"] = {
            "id": f"semantic-{scene_id}",
            "kind": "semantic_motion",
            "quality": "placeholder",
            "motifs": ["one"],
        }
    return scene
