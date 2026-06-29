from reddit2video.story_format_cookbook import (
    DEFAULT_REEL_TEMPLATE_FAMILY,
    STORY_FORMAT_COOKBOOK_MARKER,
    STORY_FORMAT_IDS,
    STORY_FORMATS,
    append_story_format_cookbook,
    reel_template_family,
    validate_story_format_payload,
)


def test_story_format_cookbook_declares_all_12_formats() -> None:
    assert len(STORY_FORMAT_IDS) == 12
    assert set(STORY_FORMAT_IDS) == set(STORY_FORMATS)

    for format_id in STORY_FORMAT_IDS:
        spec = STORY_FORMATS[format_id]
        assert spec["opening_scene_pool"]
        assert spec["middle_scene_pool"]
        assert spec["proof_scene_pool"]
        assert spec["final_scene_pool"]
        assert spec["preferred_layout_recipe_hints"]
        assert reel_template_family(format_id) == f"girly_{format_id}"


def test_story_format_prompt_append_is_idempotent_and_forbids_html() -> None:
    prompt = append_story_format_cookbook("BASE")
    prompt_again = append_story_format_cookbook(prompt)

    assert prompt_again.count(STORY_FORMAT_COOKBOOK_MARKER) == 1
    for format_id in STORY_FORMAT_IDS:
        assert format_id in prompt
    assert "Gemini does not write HTML/CSS" in prompt


def test_story_format_validator_requires_canonical_format_and_six_beats() -> None:
    assert validate_story_format_payload({"story_format": "not_real"}) == ["missing_or_invalid_story_format"]
    assert validate_story_format_payload({"story_format": "everyday_math"}) == [
        "story_format_beat_map_must_have_6_beats"
    ]


def test_story_format_validator_rejects_short_storyboards_without_girly_scenes() -> None:
    issues = validate_story_format_payload(
        {
            "story_format": "everyday_math",
            "story_format_beat_map": [
                {
                    "order": index,
                    "beat_name": f"beat {index}",
                    "narrative_job": "math",
                    "target_seconds": "0-3",
                    "required_turn": "operand",
                }
                for index in range(1, 7)
            ],
            "scenes": [{"scene_id": 1, "voiceover_line": "Считаем."}],
        }
    )

    assert "storyboard_scene_count_must_be_18_to_30" in issues
    assert "all_scenes_must_include_girly_scene" in issues
    assert "story_format_scene_pool_not_used" in issues


def test_story_format_family_falls_back_for_legacy_payloads() -> None:
    assert reel_template_family(None) == DEFAULT_REEL_TEMPLATE_FAMILY
    assert reel_template_family("") == DEFAULT_REEL_TEMPLATE_FAMILY
