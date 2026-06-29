from reddit2video.girly_scene_bridge import materialize_girly_scene_unit, validate_girly_scene_selection
from reddit2video.scene_schema import MediaAssetSlot
from reddit2video.voiceover_schema import StoryboardVisualAsset


def test_storyboard_visual_asset_schema_keeps_girly_fields() -> None:
    asset = StoryboardVisualAsset.model_validate(
        {
            "asset": "pain opener video",
            "source": "Stock/Footage",
            "search_query": "boring morning routine video",
            "appears_on_word": "будни",
            "why": "Main before-state visual.",
            "girly_asset_role": "main_video",
            "preferred_slot": "s27-video",
        }
    )

    dumped = asset.model_dump(mode="json")

    assert dumped["girly_asset_role"] == "main_video"
    assert dumped["preferred_slot"] == "s27-video"


def test_media_asset_slot_schema_keeps_girly_slot_metadata() -> None:
    slot = MediaAssetSlot.model_validate(
        {
            "asset_id": "s027_storyboard_asset_01",
            "kind": "video",
            "role": "subject",
            "source_strategy": "stock_search",
            "source_fragment_ids": [27],
            "visual_prompt": "boring morning routine",
            "girly_asset_role": "main_video",
            "preferred_slot": "s27-video",
        }
    )

    dumped = slot.model_dump(mode="json")

    assert dumped["girly_asset_role"] == "main_video"
    assert dumped["preferred_slot"] == "s27-video"


def test_validate_girly_scene_selection_reports_broken_selection() -> None:
    scene = _scene027()
    scene["girly_scene"]["scene_id"] = "Scene999"

    warnings = validate_girly_scene_selection(scene)

    assert warnings == ["unknown girly_scene.scene_id: Scene999"]


def test_validate_girly_scene_selection_reports_slot_index_and_text_errors() -> None:
    scene = _scene027()
    scene["girly_scene"]["slot_plan"] = [
        {"slot": "s27-unknown", "slot_type": "media", "role": "main_video", "visual_asset_index": 0},
        {"slot": "s27-video", "slot_type": "media", "role": "main_video", "visual_asset_index": 9},
        {
            "slot": "s27-copy-right",
            "slot_type": "text",
            "role": "pain_phrase_1",
            "text": "этой фразы нет",
            "text_source": "spoken_fragment",
        },
    ]

    warnings = validate_girly_scene_selection(scene)

    assert any("unknown slots for Scene027" in warning for warning in warnings)
    assert any("visual_asset_index=9" in warning for warning in warnings)
    assert any("not an exact spoken_fragment" in warning for warning in warnings)


def test_materialize_girly_scene_unit_falls_back_when_missing_or_unknown() -> None:
    missing = materialize_girly_scene_unit(
        {
            "scene_id": 1,
            "duration_sec": 3,
            "voiceover_line": "вам не нравится ваш стиль и будни",
            "visual_assets": [],
        }
    )
    unknown = _scene027()
    unknown["girly_scene"]["scene_id"] = "Scene999"
    materialized_unknown = materialize_girly_scene_unit(unknown)

    assert missing["girly_scene_unit"]["scene_id"] == "Scene027"
    assert "girly_scene missing" in missing["girly_scene_unit"]["warnings"][0]
    assert materialized_unknown["girly_scene_unit"]["scene_id"] == "Scene027"
    assert any("girly_scene broken" in warning for warning in materialized_unknown["girly_scene_unit"]["warnings"])


def _scene027() -> dict:
    return {
        "scene_id": 27,
        "duration_sec": 3,
        "scene_type": "COLLAGE",
        "voiceover_line": "вам не нравится ваш стиль и будни",
        "layout_recipe_hint": "duel_2_assets",
        "visual_assets": [
            {"asset": "main", "source": "Stock/Footage", "search_query": "boring routine video"},
            {"asset": "pain", "source": "Google Images", "search_query": "messy closet photo"},
        ],
        "girly_scene": {
            "scene_id": "Scene027",
            "scene_group": "blog_opener_transformation",
            "storytelling_function": "pain opener",
            "semantic_reason": "before-state pain",
            "asset_semantics": ["main_video", "pain_photo"],
            "slot_plan": [
                {"slot": "s27-video", "slot_type": "media", "role": "main_video", "visual_asset_index": 0},
                {"slot": "s27-photo-top", "slot_type": "media", "role": "pain_photo", "visual_asset_index": 1},
                {
                    "slot": "s27-copy-right",
                    "slot_type": "text",
                    "role": "pain_phrase_1",
                    "text": "вам не нравится ваш стиль",
                    "text_source": "spoken_fragment",
                },
            ],
        },
    }
