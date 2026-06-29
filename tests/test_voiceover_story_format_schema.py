from reddit2video.voiceover_schema import RedditVoiceoverStoryboardOutput


def _storyboard_payload() -> dict:
    return {
        "title": "Тест",
        "source_digest": {
            "raw_topic": "еда",
            "what_happened": "спорят про порции",
            "comment_conflict": "одни считают, другие угадывают",
            "do_not_reference_source_in_voiceover": True,
        },
        "story_strategy": {
            "core_conflict": "сладкое против контроля",
            "two_camps": {"camp_a": "запрещать", "camp_b": "считать"},
            "emotional_wound": "страх сорваться",
            "hidden_third_insight": "порция решает",
            "chosen_angle": "бытовая математика",
            "story_engine": "math reveal",
            "narrator_mask": "умная подруга",
            "hook_type": "uncomfortable_truth",
            "ending_type": "choice",
            "why_this_will_retain": "каждая сцена добавляет расчет",
        },
        "voiceover": {
            "full_text": "Ты не сорвалась. Ты просто не посчитала порцию.",
            "estimated_duration_sec": 20,
            "bait_question": "Ты считаешь порцию или настроение?",
        },
        "scene_mix": {
            "total_scenes": 1,
            "text_only_scenes": 0,
            "avatar_scenes": 0,
            "collage_scenes": 1,
            "ai_generated_image_scenes": 0,
        },
        "scenes": [],
        "asset_checklist": [],
        "quality_control": {
            "does_not_reference_reddit": True,
            "has_hook_in_first_2_seconds": True,
            "has_retention_shift_every_2_to_5_sec": True,
            "has_clear_visuals_for_each_scene": True,
            "has_final_bait_question": True,
            "avoids_medical_overclaiming": True,
            "anti_brainrot_pass": True,
        },
    }


def test_storyboard_schema_accepts_story_format_contract() -> None:
    payload = _storyboard_payload()
    payload.update(
        {
            "story_format": "everyday_math",
            "story_format_reason": "Тема держится на маленьком бытовом расчете.",
            "story_format_confidence": 0.91,
            "story_format_beat_map": [
                {
                    "order": index,
                    "beat_name": f"beat {index}",
                    "narrative_job": "держит расчет",
                    "target_seconds": "0-3",
                    "required_turn": "новый операнд",
                    "preferred_scene_pool": ["Scene012"],
                }
                for index in range(1, 7)
            ],
        }
    )

    storyboard = RedditVoiceoverStoryboardOutput.model_validate(payload)

    assert storyboard.story_format == "everyday_math"
    assert len(storyboard.story_format_beat_map) == 6


def test_storyboard_schema_keeps_legacy_payloads_backwards_compatible() -> None:
    storyboard = RedditVoiceoverStoryboardOutput.model_validate(_storyboard_payload())

    assert storyboard.story_format is None
    assert storyboard.story_format_beat_map == []
