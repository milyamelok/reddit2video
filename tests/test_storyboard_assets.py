from reddit2video.models import VoiceoverScriptBatch, VoiceoverScriptItem
from reddit2video.storyboard_assets import storyboard_assets_to_scene_batch


def test_storyboard_visual_assets_project_to_media_slots_without_new_ideas() -> None:
    batch = VoiceoverScriptBatch(
        items=[
            VoiceoverScriptItem(
                post_id="p1",
                subreddit="test",
                title="Storyboard",
                script={
                    "storyboard_v2": {
                        "title": "Storyboard",
                        "scene_mix": {"total_scenes": 1},
                        "scenes": [
                            {
                                "scene_id": 1,
                                "duration_sec": 2.5,
                                "scene_type": "COLLAGE",
                                "voiceover_line": "Йогурт притворяется чизкейком.",
                                "on_screen_text": "ЙОГУРТ НЕ ТОРТ",
                                "retention_function": "visual punchline",
                                "visual_direction": "Collage of exact assets from prompt.",
                                "animation": "pop in",
                                "visual_assets": [
                                    {
                                        "asset": "Greek yogurt tub",
                                        "source": "Google Images",
                                        "search_query": "Greek yogurt tub",
                                        "appears_on_word": "Йогурт",
                                        "why": "literal object",
                                    },
                                    {
                                        "asset": "side eye",
                                        "source": "Giphy",
                                        "search_query": "side eye reaction gif",
                                        "appears_on_word": "притворяется",
                                        "why": "reaction",
                                    },
                                    {
                                        "asset": "crying cat sticker",
                                        "source": "Telegram stickers",
                                        "search_query": "crying cat sticker",
                                        "appears_on_word": "не торт",
                                        "why": "temporary sticker bridge",
                                    },
                                    {
                                        "asset": "Greek yogurt as cheesecake monster",
                                        "source": "AI-generated",
                                        "search_query": "",
                                        "appears_on_word": "торт",
                                        "why": "custom metaphor",
                                    },
                                ],
                                "ai_image_prompt": "Greek yogurt tub wearing a cheesecake costume, vertical 9:16, no text",
                            }
                        ],
                    }
                },
                validator=None,
                attempts=1,
                from_cache=False,
                cache_path="",
            )
        ],
        fetched_at="now",
        metadata={},
    )

    result = storyboard_assets_to_scene_batch(batch, period_key="test")
    scene = result.items[0].scene_plan["scenes"][0]
    slots = scene["media_slots"]

    assert [slot["storyboard_asset"]["asset"] for slot in slots] == [
        "Greek yogurt tub",
        "side eye",
        "crying cat sticker",
        "Greek yogurt as cheesecake monster",
    ]
    assert slots[0]["source_strategy"] == "google_images"
    assert slots[0]["kind"] == "image"
    assert slots[0]["search_query_en"] == "Greek yogurt tub"
    assert slots[1]["source_strategy"] == "giphy"
    assert slots[1]["kind"] == "gif"
    assert slots[2]["source_strategy"] == "giphy"
    assert slots[2]["kind"] == "gif"
    assert slots[2]["required"] is True
    assert "sticker" not in slots[2]["search_query_en"].lower()
    assert "reaction gif" in slots[2]["search_query_en"].lower()
    assert slots[3]["source_strategy"] == "generated"
    assert slots[3]["kind"] == "image"
    assert slots[3]["required"] is True
    assert slots[3]["generation_aspect_ratio"] == "4:3"
    assert slots[3]["visual_prompt"] == "Greek yogurt tub wearing a cheesecake costume, vertical 9:16, no text"
    assert result.metadata["unavailable_source_counts"] == {}


def test_storyboard_stock_footage_maps_to_video_slot() -> None:
    batch = VoiceoverScriptBatch(
        items=[
            VoiceoverScriptItem(
                post_id="p2",
                subreddit="test",
                title="Footage",
                script={
                    "storyboard_v2": {
                        "title": "Footage",
                        "scenes": [
                            {
                                "scene_id": 1,
                                "duration_sec": 3,
                                "scene_type": "AVATAR",
                                "voiceover_line": "Ночной холодильник зовет.",
                                "on_screen_text": "ЕДА ШУМИТ",
                                "visual_assets": [
                                    {
                                        "asset": "night kitchen",
                                        "source": "Stock/Footage",
                                        "search_query": "night kitchen fridge footage",
                                        "appears_on_word": "холодильник",
                                        "why": "mood footage",
                                    }
                                ],
                            }
                        ],
                    }
                },
                validator=None,
                attempts=1,
                from_cache=False,
                cache_path="",
            )
        ],
        fetched_at="now",
        metadata={},
    )

    slot = storyboard_assets_to_scene_batch(batch).items[0].scene_plan["scenes"][0]["media_slots"][0]

    assert slot["kind"] == "video"
    assert slot["source_strategy"] == "pinterest_search"
    assert slot["motion_hint"] == "loop"


def test_storyboard_assets_project_girly_slot_metadata() -> None:
    batch = VoiceoverScriptBatch(
        items=[
            VoiceoverScriptItem(
                post_id="p27",
                subreddit="test",
                title="Scene027",
                script={
                    "storyboard_v2": {
                        "title": "Scene027",
                        "scenes": [
                            {
                                "scene_id": 27,
                                "duration_sec": 3,
                                "scene_type": "COLLAGE",
                                "voiceover_line": "вам не нравится ваш стиль и будни",
                                "visual_assets": [
                                    {
                                        "asset": "before-state video",
                                        "source": "Stock/Footage",
                                        "search_query": "boring routine vertical video",
                                        "appears_on_word": "будни",
                                        "why": "main before-state visual",
                                        "girly_asset_role": "main_video",
                                        "preferred_slot": "s27-video",
                                    },
                                    {
                                        "asset": "pain closet photo",
                                        "source": "Google Images",
                                        "search_query": "messy closet aesthetic photo",
                                        "appears_on_word": "стиль",
                                        "why": "pain detail",
                                    },
                                ],
                                "girly_scene": {
                                    "scene_id": "Scene027",
                                    "scene_group": "blog_opener_transformation",
                                    "storytelling_function": "pain opener",
                                    "semantic_reason": "before-state pain",
                                    "asset_semantics": ["main_video", "pain_photo"],
                                    "slot_plan": [
                                        {
                                            "slot": "s27-video",
                                            "slot_type": "media",
                                            "role": "main_video",
                                            "visual_asset_index": 0,
                                        },
                                        {
                                            "slot": "s27-photo-top",
                                            "slot_type": "media",
                                            "role": "pain_photo",
                                            "visual_asset_index": 1,
                                        },
                                    ],
                                },
                            }
                        ],
                    }
                },
                validator=None,
                attempts=1,
                from_cache=False,
                cache_path="",
            )
        ],
        fetched_at="now",
        metadata={},
    )

    scene = storyboard_assets_to_scene_batch(batch).items[0].scene_plan["scenes"][0]
    slots = {slot["preferred_slot"]: slot for slot in scene["media_slots"]}

    assert scene["storyboard_scene"]["girly_scene"]["scene_id"] == "Scene027"
    assert slots["s27-video"]["girly_asset_role"] == "main_video"
    assert slots["s27-video"]["kind"] == "video"
    assert slots["s27-video"]["source_strategy"] == "pinterest_search"
    assert slots["s27-video"]["storyboard_asset"]["preferred_slot"] == "s27-video"
    assert slots["s27-video"]["girly_slot_plan"]["role"] == "main_video"
    assert slots["s27-photo-top"]["girly_asset_role"] == "pain_photo"
    assert slots["s27-photo-top"]["kind"] == "image"
    assert slots["s27-photo-top"]["source_strategy"] == "google_images"
    assert slots["s27-photo-top"]["girly_slot_plan"]["role"] == "pain_photo"


def test_avatar_scene_synthesizes_pinterest_broll_background() -> None:
    batch = VoiceoverScriptBatch(
        items=[
            VoiceoverScriptItem(
                post_id="p3",
                subreddit="test",
                title="Avatar",
                script={
                    "storyboard_v2": {
                        "title": "Avatar",
                        "scenes": [
                            {
                                "scene_id": 1,
                                "duration_sec": 3,
                                "scene_type": "AVATAR",
                                "voiceover_line": "Я бы тоже так думала.",
                                "on_screen_text": "Я тоже так думала",
                                "background": "blurred gym rack with warm light",
                                "visual_direction": "Small avatar in the lower-right corner over soft gym b-roll.",
                                "visual_assets": [],
                            }
                        ],
                    }
                },
                validator=None,
                attempts=1,
                from_cache=False,
                cache_path="",
            )
        ],
        fetched_at="now",
        metadata={},
    )

    scene = storyboard_assets_to_scene_batch(batch).items[0].scene_plan["scenes"][0]
    slot = scene["media_slots"][0]

    assert scene["template_hint"] == "avatar_broll_marquee"
    assert scene["visual_mode"] == "avatar_overlay_with_broll"
    assert scene["screen_rows"][0]["role"] == "marquee"
    assert scene["avatar_overlay"]["position"] == "bottom_right"
    assert scene["avatar_overlay"]["area_fraction"] == 0.2
    assert slot["asset_id"] == "s001_avatar_broll_bg"
    assert slot["kind"] == "video"
    assert slot["role"] == "background_texture"
    assert slot["source_strategy"] == "pinterest_search"
    assert slot["storyboard_source"] == "Stock/Footage"
    assert slot["search_query_en"] == "gym rack with warm light"
