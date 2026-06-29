from __future__ import annotations

import importlib.util
from pathlib import Path


def _payload_module():
    path = Path("scripts/girly_static_v5_to_remotion_html_payload.py").resolve()
    spec = importlib.util.spec_from_file_location("girly_static_v5_to_remotion_html_payload", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_payload_sanitizer_removes_rejected_prefilled_local_media_slot_for_render() -> None:
    module = _payload_module()
    html = (
        '<div class="scene-frame">'
        '<div class="s21-photo-01" data-girly-filled-media="true" data-girly-slot="s21-photo-01" '
        'data-girly-role="diary_photo" data-asset-id="s004_storyboard_asset_01" '
        'style="background-image: url(__STATIC_FILE__bad-lions-mane.jpg); background-size: cover;"></div>'
        "</div>"
    )
    scene = {
        "resolved_slots": [
            {
                "asset_id": "s004_storyboard_asset_01",
                "slot": {"asset_id": "s004_storyboard_asset_01", "girly_asset_role": "diary_photo"},
                "selected_candidates": [
                    {
                        "candidate_id": "PF24_P01",
                        "provider": "pinterest",
                        "query": "lion mane mushroom powder spoon",
                        "title": "Your Brain's New Best Friend: Medshrum's Lion's Mane",
                        "public_path": "__STATIC_FILE__bad-lions-mane.jpg",
                    }
                ],
            }
        ]
    }

    cleaned, rejected = module._sanitize_rejected_html_media_slots(html, scene)

    assert rejected == ["s004_storyboard_asset_01"]
    assert "__STATIC_FILE__bad-lions-mane.jpg" not in cleaned
    assert "data-girly-filled-media" not in cleaned
    assert "data-asset-id" not in cleaned


def test_story_format_metadata_preserves_new_reel_family_contract() -> None:
    module = _payload_module()
    beat_map = [
        {
            "order": index,
            "beat_name": f"beat {index}",
            "narrative_job": "build the math",
            "target_seconds": "0-3",
            "required_turn": "new operand",
            "preferred_scene_pool": ["Scene012"],
        }
        for index in range(1, 7)
    ]
    metadata = module._story_format_metadata(
        [
            {
                "story_format": "everyday_math",
                "story_format_reason": "The reel is a small household calculation.",
                "story_format_confidence": 0.88,
                "story_format_beat_map": beat_map,
                "scenes": [
                    {
                        "scene_id": index,
                        "girly_scene": {"scene_id": "Scene012"},
                    }
                    for index in range(1, 19)
                ],
            }
        ]
    )

    assert metadata["story_format"] == "everyday_math"
    assert metadata["reel_template_family"] == "girly_everyday_math"
    assert metadata["template_family_version"] == "story_format_families_v1"
    assert metadata["story_format_beat_map"] == beat_map
    assert metadata["story_format_validation_warnings"] == []


def test_story_format_metadata_keeps_legacy_payload_default_family() -> None:
    module = _payload_module()

    metadata = module._story_format_metadata([{"scenes": []}])

    assert metadata["story_format"] == ""
    assert metadata["reel_template_family"] == "default_girly_b_layout"
    assert metadata["story_format_validation_warnings"] == []


def test_asset_timings_follow_spoken_word_and_resolved_asset_id() -> None:
    module = _payload_module()
    scene = {
        "girly_scene_unit": {
            "slot_plan": [
                {
                    "slot": "s26-image-card",
                    "slot_type": "media",
                    "visual_asset_index": 0,
                    "appears_on_word": "семьсот",
                }
            ],
        },
        "visual_assets": [{"asset_id": "visual_asset_0"}],
        "resolved_media": [
            {
                "asset_id": "s003_storyboard_asset_01",
                "slot": {
                    "asset_id": "s003_storyboard_asset_01",
                    "girly_slot_plan": {"slot": "s26-image-card", "appears_on_word": "семьсот"},
                },
            }
        ],
    }
    words = [
        {"word": "Ведь", "appear_frame": 0},
        {"word": "семьсот", "appear_frame": 50},
        {"word": "калорий.", "appear_frame": 61},
    ]

    timings = module._asset_timings(scene, fps=30, word_timings=words)

    assert timings["s003_storyboard_asset_01"]["appear_frame"] == 50
    assert timings["s003_storyboard_asset_01"]["confidence"] == "girly_static_v5_word_timing"


def test_bridge_media_assets_skip_rejected_publication_sources() -> None:
    module = _payload_module()
    scene = {
        "resolved_media": [
            {
                "asset_id": "s017_storyboard_asset_01",
                "kind": "image",
                "slot": {"asset_id": "s017_storyboard_asset_01", "role": "reaction_cutaway"},
                "selected_candidates": [
                    {
                        "candidate_id": "bad",
                        "provider": "pinterest",
                        "query": "secret eating meme reaction",
                        "title": "funny meme reaction gif",
                        "public_path": "__STATIC_FILE__bad-meme.jpg",
                    }
                ],
            }
        ]
    }

    assets = module._bridge_media_assets(scene, scene_html="<div></div>")

    assert assets == []


def test_bridge_media_assets_keep_local_selected_social_caption_source() -> None:
    module = _payload_module()
    scene = {
        "resolved_media": [
            {
                "asset_id": "s003_storyboard_asset_01",
                "kind": "video",
                "slot": {"asset_id": "s003_storyboard_asset_01", "kind": "video"},
                "selected_candidates": [
                    {
                        "candidate_id": "local-social",
                        "provider": "pinterest",
                        "query": "calorie counting cafe video",
                        "title": "What I eat in a day #fyp #viral",
                        "public_path": "__STATIC_FILE__assets/s003.mp4",
                        "local_content_type": "video/mp4",
                    }
                ],
            }
        ]
    }

    assets = module._bridge_media_assets(scene, scene_html="<div></div>")

    assert assets == [
        {
            "id": "s003_storyboard_asset_01",
            "kind": "video",
            "role": "semantic_bridge",
            "src": "__STATIC_FILE__assets/s003.mp4",
            "fit": "cover",
            "focusX": "50%",
            "focusY": "50%",
        }
    ]


def test_bridge_media_assets_skip_local_playlist_and_avif_publication_sources() -> None:
    module = _payload_module()
    scene = {
        "resolved_media": [
            {
                "asset_id": "s004_avatar_broll_bg",
                "kind": "video",
                "slot": {"asset_id": "s004_avatar_broll_bg", "kind": "video"},
                "selected_candidates": [
                    {
                        "candidate_id": "playlist",
                        "provider": "pinterest",
                        "title": "cafe broll",
                        "public_path": "__STATIC_FILE__assets/s004.m3u8",
                        "local_content_type": "application/x-mpegurl",
                    }
                ],
            },
            {
                "asset_id": "s005_storyboard_asset_01",
                "kind": "image",
                "slot": {"asset_id": "s005_storyboard_asset_01", "kind": "image"},
                "selected_candidates": [
                    {
                        "candidate_id": "avif",
                        "provider": "serper_images",
                        "title": "bathroom",
                        "public_path": "__STATIC_FILE__assets/s005.avif",
                        "local_content_type": "image/avif",
                    }
                ],
            },
        ]
    }

    assets = module._bridge_media_assets(scene, scene_html="<div></div>")

    assert assets == []


def test_sanitizer_removes_local_playlist_media_slot_for_render() -> None:
    module = _payload_module()
    html = (
        '<div class="scene-frame">'
        '<div data-girly-filled-media="true" data-asset-id="s004_avatar_broll_bg">'
        '<video src="__STATIC_FILE__assets/s004.m3u8"></video>'
        "</div>"
        "</div>"
    )
    scene = {
        "resolved_slots": [
            {
                "asset_id": "s004_avatar_broll_bg",
                "slot": {"asset_id": "s004_avatar_broll_bg", "kind": "video"},
                "selected_candidates": [
                    {
                        "candidate_id": "playlist",
                        "provider": "pinterest",
                        "title": "cafe broll",
                        "public_path": "__STATIC_FILE__assets/s004.m3u8",
                        "local_content_type": "application/x-mpegurl",
                    }
                ],
            }
        ]
    }

    cleaned, rejected = module._sanitize_rejected_html_media_slots(html, scene)

    assert rejected == ["s004_avatar_broll_bg"]
    assert "__STATIC_FILE__assets/s004.m3u8" not in cleaned
    assert "data-girly-filled-media" not in cleaned


def test_sanitizer_keeps_local_selected_soft_metadata_media_slot() -> None:
    module = _payload_module()
    html = (
        '<div class="scene-frame">'
        '<div data-girly-filled-media="true" data-asset-id="s003_storyboard_asset_01">'
        '<video src="__STATIC_FILE__assets/s003.mp4"></video>'
        "</div>"
        "</div>"
    )
    scene = {
        "resolved_slots": [
            {
                "asset_id": "s003_storyboard_asset_01",
                "slot": {"asset_id": "s003_storyboard_asset_01", "kind": "video"},
                "selected_candidates": [
                    {
                        "candidate_id": "local-social",
                        "provider": "pinterest",
                        "query": "calorie counting cafe video",
                        "title": "What I eat in a day #fyp #viral",
                        "public_path": "__STATIC_FILE__assets/s003.mp4",
                        "local_content_type": "video/mp4",
                    }
                ],
            }
        ]
    }

    cleaned, rejected = module._sanitize_rejected_html_media_slots(html, scene)

    assert rejected == []
    assert cleaned == html
