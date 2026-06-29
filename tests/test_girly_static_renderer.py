from reddit2video.girly_static_renderer import format_timed_text_html, render_girly_static_document


def test_girly_static_renderer_fills_scene027_slots_without_freeform_layout() -> None:
    scene = {
        "scene_id": 27,
        "duration_sec": 3,
        "scene_type": "COLLAGE",
        "voiceover_line": "вам не нравится ваш стиль и будни",
        "visual_assets": [
            {
                "asset": "before-state video",
                "source": "Stock/Footage",
                "search_query": "boring routine vertical video",
                "url": "https://assets.test/main.mp4",
                "girly_asset_role": "main_video",
                "preferred_slot": "s27-video",
            },
            {
                "asset": "pain closet photo",
                "source": "Google Images",
                "search_query": "messy closet aesthetic photo",
                "url": "https://assets.test/pain.jpg",
                "girly_asset_role": "pain_photo",
                "preferred_slot": "s27-photo-top",
            },
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
                    "text": "вам не нравится ваш стиль и будни",
                    "text_source": "spoken_fragment",
                },
            ],
        },
    }

    html = render_girly_static_document([scene], title="Scene027 smoke")

    assert 'data-scene-root="Scene027"' in html
    assert "scene-frame scene-27" in html
    assert "s27-video" in html
    assert "s27-photo-top" in html
    assert "s27-copy-right" in html
    assert 'data-girly-slot="s27-video"' in html
    assert 'data-girly-slot="s27-photo-top"' in html
    assert 'data-girly-slot="s27-copy-right"' in html
    assert 'data-girly-slot="s27-photo-bottom"' not in html
    assert "https://assets.test/main.mp4" in html
    assert "https://assets.test/pain.jpg" in html
    assert "вам не нравится<br>ваш стиль и<br>будни" in html
    assert "SCENARIO_PIPELINE_JSON" not in html
    assert "scene-new" not in html


def test_girly_static_renderer_uses_resolved_media_for_girly_slot_plan_slot() -> None:
    scene = {
        "scene_id": 27,
        "duration_sec": 3,
        "voiceover_line": "локальный клип должен победить",
        "visual_assets": [
            {
                "asset": "remote fallback",
                "source": "Stock/Footage",
                "url": "https://assets.test/remote.mp4",
                "girly_asset_role": "main_video",
                "preferred_slot": "s27-photo-top",
            }
        ],
        "resolved_slots": [
            {
                "scene_id": 27,
                "asset_id": "a1",
                "slot": {
                    "asset_id": "a1",
                    "kind": "video",
                    "preferred_slot": "s27-photo-top",
                    "girly_slot_plan": {"slot": "s27-video"},
                },
                "selected_candidates": [
                    {
                        "candidate_id": "P01",
                        "provider": "pinterest",
                        "query": "quiet morning walk video",
                        "title": "Quiet morning walk in soft light",
                        "public_path": "__STATIC_FILE__girly-static-v5/assets/local.mp4",
                        "media_url": "https://assets.test/remote-selected.m3u8",
                    }
                ],
            }
        ],
        "girly_scene": {
            "scene_id": "Scene027",
            "scene_group": "blog_opener_transformation",
            "storytelling_function": "image url regression",
            "semantic_reason": "supporting photo slot",
            "asset_semantics": ["supporting_photo"],
            "slot_plan": [
                {"slot": "s27-video", "slot_type": "media", "role": "main_video", "visual_asset_index": 0}
            ],
        },
    }

    html = render_girly_static_document([scene], title="Scene027 resolved")

    assert "__STATIC_FILE__girly-static-v5/assets/local.mp4" in html
    assert "https://assets.test/remote.mp4" not in html
    assert "https://assets.test/remote-selected.m3u8" not in html


def test_girly_static_renderer_skips_dirty_selected_media_for_clean_pool_candidate() -> None:
    scene = {
        "scene_id": 27,
        "duration_sec": 3,
        "voiceover_line": "локальный клип должен быть чистым",
        "resolved_slots": [
            {
                "scene_id": 27,
                "asset_id": "a1",
                "slot": {
                    "asset_id": "a1",
                    "kind": "video",
                    "girly_slot_plan": {"slot": "s27-video"},
                },
                "selected_candidates": [
                    {
                        "candidate_id": "G01",
                        "provider": "giphy",
                        "query": "reaction meme",
                        "title": "Confused Thinking GIF",
                        "public_path": "__STATIC_FILE__girly-static-v5/assets/dirty.mp4",
                        "media_url": "https://media.giphy.com/media/dirty.mp4",
                    }
                ],
                "candidate_pool": [
                    {
                        "candidate_id": "P01",
                        "provider": "pinterest",
                        "query": "quiet morning walk",
                        "title": "quiet morning walk",
                        "public_path": "__STATIC_FILE__girly-static-v5/assets/clean.mp4",
                        "media_url": "https://assets.test/clean.mp4",
                        "width": 720,
                        "height": 1280,
                    }
                ],
            }
        ],
        "girly_scene": {
            "scene_id": "Scene027",
            "slot_plan": [{"slot": "s27-video", "slot_type": "media", "role": "main_video"}],
        },
    }

    html = render_girly_static_document([scene], title="Scene027 hygiene")

    assert "__STATIC_FILE__girly-static-v5/assets/clean.mp4" in html
    assert "__STATIC_FILE__girly-static-v5/assets/dirty.mp4" not in html


def test_girly_static_renderer_prefers_full_image_url_without_escaped_css_quotes() -> None:
    scene = {
        "scene_id": 27,
        "duration_sec": 3,
        "scene_type": "COLLAGE",
        "voiceover_line": "полная картинка важнее превью",
        "visual_assets": [
            {
                "asset": "remote fallback",
                "source": "Stock/Footage",
                "url": "https://assets.test/photo.jpg",
                "girly_asset_role": "supporting_photo",
                "preferred_slot": "s27-photo-top",
            }
        ],
        "resolved_slots": [
            {
                "scene_id": 27,
                "asset_id": "a1",
                "slot": {
                    "asset_id": "a1",
                    "kind": "image",
                    "preferred_slot": "s27-photo-top",
                    "girly_slot_plan": {"slot": "s27-photo-top"},
                },
                "selected_candidates": [
                    {
                        "candidate_id": "S01",
                        "provider": "serper_images",
                        "query": "orange slice photo",
                        "title": "orange slice on plate",
                        "media_url": "https://images.test/full-orange.jpg",
                        "thumbnail_url": "https://encrypted-tbn0.gstatic.com/thumb.jpg",
                        "width": 1200,
                        "height": 1200,
                    }
                ],
            }
        ],
        "girly_scene": {
            "scene_id": "Scene027",
            "scene_group": "blog_opener_transformation",
            "storytelling_function": "image url regression",
            "semantic_reason": "supporting photo slot",
            "asset_semantics": ["supporting_photo"],
            "slot_plan": [
                {"slot": "s27-photo-top", "slot_type": "media", "role": "supporting_photo", "visual_asset_index": 0},
                {"slot": "s27-copy-right", "slot_type": "text", "role": "spoken", "text_source": "spoken_fragment"},
            ],
        },
    }

    html = render_girly_static_document([scene], title="Scene027 image")

    assert "https://images.test/full-orange.jpg" in html
    assert "encrypted-tbn0" not in html
    assert "&quot;https://images.test/full-orange.jpg" not in html


def test_girly_static_renderer_skips_social_pinterest_selected_media() -> None:
    scene = {
        "scene_id": 27,
        "duration_sec": 3,
        "voiceover_line": "соц нарезка не должна попадать в финал",
        "resolved_slots": [
            {
                "scene_id": 27,
                "asset_id": "a1",
                "slot": {
                    "asset_id": "a1",
                    "kind": "video",
                    "girly_slot_plan": {"slot": "s27-video"},
                },
                "selected_candidates": [
                    {
                        "candidate_id": "P01",
                        "provider": "pinterest",
                        "query": "aesthetic coffee video",
                        "title": "Tap in and get yours from @creator asap",
                        "public_path": "__STATIC_FILE__girly-static-v5/assets/social.mp4",
                        "media_url": "https://v1.pinimg.com/videos/iht/hls/social.m3u8",
                    }
                ],
            }
        ],
        "girly_scene": {
            "scene_id": "Scene027",
            "slot_plan": [{"slot": "s27-video", "slot_type": "media", "role": "main_video"}],
        },
    }

    html = render_girly_static_document([scene], title="Scene027 social reject")

    assert "__STATIC_FILE__girly-static-v5/assets/social.mp4" not in html


def test_girly_static_renderer_skips_motivational_pinterest_clip() -> None:
    scene = {
        "scene_id": 21,
        "duration_sec": 3,
        "voiceover_line": "исследования показывают реальную пользу тепла",
        "resolved_slots": [
            {
                "scene_id": 21,
                "asset_id": "s021_storyboard_asset_01",
                "slot": {
                    "asset_id": "s021_storyboard_asset_01",
                    "kind": "video",
                    "girly_slot_plan": {"slot": "s21-photo-02"},
                },
                "selected_candidates": [
                    {
                        "candidate_id": "P01",
                        "provider": "pinterest",
                        "query": "healthy happy older woman",
                        "title": "Have Fun and Be Happy",
                        "page_url": "https://www.pinterest.com/pin/82542605659321509/",
                        "public_path": "__STATIC_FILE__girly-static-v5/assets/happy.mp4",
                    }
                ],
            }
        ],
        "girly_scene": {
            "scene_id": "Scene021",
            "slot_plan": [{"slot": "s21-photo-02", "slot_type": "media", "role": "habit_action_photo"}],
        },
    }

    html = render_girly_static_document([scene], title="Scene021 motivational reject")

    assert "__STATIC_FILE__girly-static-v5/assets/happy.mp4" not in html


def test_girly_static_renderer_skips_product_landing_page_clip() -> None:
    scene = {
        "scene_id": 10,
        "duration_sec": 3,
        "voiceover_line": "наука о тепле сильнее модного льда",
        "resolved_slots": [
            {
                "scene_id": 10,
                "asset_id": "s010_storyboard_asset_01",
                "slot": {
                    "asset_id": "s010_storyboard_asset_01",
                    "kind": "video",
                    "girly_slot_plan": {"slot": "s10-video-main"},
                },
                "selected_candidates": [
                    {
                        "candidate_id": "P01",
                        "provider": "pinterest",
                        "query": "dry finnish sauna interior",
                        "title": "Building a Barrel Sauna with Thermory - Intro",
                        "page_url": "https://www.pinterest.com/pin/317855686221368031/",
                        "metadata": {
                            "domain": "sauna.thermoryusa.com",
                            "link": "https://sauna.thermoryusa.com/products/natural-barrel-saunas/?utm_source=pinterest",
                        },
                        "public_path": "__STATIC_FILE__girly-static-v5/assets/thermory.mp4",
                    }
                ],
            }
        ],
        "girly_scene": {
            "scene_id": "Scene010",
            "slot_plan": [{"slot": "s10-video-main", "slot_type": "media", "role": "main_video"}],
        },
    }

    html = render_girly_static_document([scene], title="Scene010 product reject")

    assert "__STATIC_FILE__girly-static-v5/assets/thermory.mp4" not in html


def test_girly_static_renderer_skips_supplement_marketing_pin() -> None:
    scene = {
        "scene_id": 21,
        "duration_sec": 3,
        "voiceover_line": "это не ежовик и не пептиды",
        "resolved_slots": [
            {
                "scene_id": 21,
                "asset_id": "s021_storyboard_asset_01",
                "slot": {
                    "asset_id": "s021_storyboard_asset_01",
                    "kind": "image",
                    "girly_slot_plan": {"slot": "s21-photo-01"},
                },
                "selected_candidates": [
                    {
                        "candidate_id": "PF24_P01",
                        "provider": "pinterest",
                        "query": "lion mane mushroom powder spoon",
                        "title": "Your Brain's New Best Friend: Medshrum's Lion's Mane",
                        "page_url": "https://www.pinterest.com/pin/627970741834834490/",
                        "metadata": {"link": "https://www.instagram.com/p/DFN4Gu3tGAM/"},
                        "public_path": "__STATIC_FILE__girly-static-v5/assets/lions-mane.jpg",
                    }
                ],
            }
        ],
        "girly_scene": {
            "scene_id": "Scene021",
            "slot_plan": [{"slot": "s21-photo-01", "slot_type": "media", "role": "diary_photo"}],
        },
    }

    html = render_girly_static_document([scene], title="Scene021 supplement reject")

    assert "__STATIC_FILE__girly-static-v5/assets/lions-mane.jpg" not in html


def test_girly_static_renderer_checks_wrapped_storyboard_asset_hygiene() -> None:
    scene = {
        "scene_id": 27,
        "duration_sec": 3,
        "voiceover_line": "короткий случайный title не должен пройти",
        "visual_assets": [
            {
                "asset_id": "story-a1",
                "asset": "random lifestyle clip",
                "source": "Pinterest",
                "provider": "pinterest",
                "query": "wellness girl casual lifestyle",
                "title": "From Now On",
                "url": "__STATIC_FILE__girly-static-v5/assets/random.mp4",
                "girly_asset_role": "main_video",
                "preferred_slot": "s27-video",
            }
        ],
        "girly_scene": {
            "scene_id": "Scene027",
            "slot_plan": [{"slot": "s27-video", "slot_type": "media", "role": "main_video"}],
        },
    }

    html = render_girly_static_document([scene], title="Scene027 wrapped hygiene")

    assert "__STATIC_FILE__girly-static-v5/assets/random.mp4" not in html


def test_format_timed_text_html_adds_word_indexes_for_exact_spoken_words() -> None:
    scene = {
        "timed_words_for_render": [
            {"index": 1, "word": "Ты", "appear_frame": 0, "start_sec": 0.0},
            {"index": 2, "word": "скупаешь", "appear_frame": 4, "start_sec": 0.13},
            {"index": 3, "word": "аптеки", "appear_frame": 9, "start_sec": 0.31},
        ]
    }

    html = format_timed_text_html("Ты скупаешь аптеки", scene=scene, max_words=6)

    assert 'data-word-index="1"' in html
    assert 'data-word-index="2"' in html
    assert 'data-word-index="3"' in html
    assert 'data-voice-word-index="2"' in html
    assert 'data-voice-word="скупаешь"' in html
    assert 'data-voice-start-sec="0.13"' in html
    assert "Ты" in html
