from __future__ import annotations

import json
from typing import Any

GIRLY_SCENE_COOKBOOK_MARKER = "PIPELINE V5 GIRLY STATIC SCENE COOKBOOK"

# This registry is intentionally semantic, not visual-only.
# The renderer should instantiate the scene root from static_girly/index.html
# and fill the declared class slots instead of generating freeform HTML/CSS.
GIRLY_SCENE_REGISTRY: list[dict[str, Any]] = [
    {
        "scene_id": "Scene001",
        "root_selector": '[data-scene-root="Scene001"]',
        "scene_class": "scene-01",
        "group": "blog_opener_transformation",
        "function": "blog_start_cta_or_threshold",
        "use_when": "Порог входа: начать блог, сделать первый шаг, из before перейти к решению.",
        "avoid_when": "Нужно доказательство, трендовая подборка, научный разбор или плотный текст.",
        "compatible_recipe_hints": ["slam_0_assets", "whisper_0_assets", "speaker_broll_0_assets", "object_hero_1_asset"],
        "asset_range": [1, 1],
        "asset_roles": ["main_video"],
        "media_slots": [
            {"slot": "s1-video", "kind": "video_or_photo", "required": True, "role": "main_video", "notes": "Героиня/lifestyle b-roll, можно speaking clip."}
        ],
        "text_slots": [
            {"slot": "s1-title-left", "role": "hero_word_left", "max_words": 1, "source": "spoken_fragment_or_short_label"},
            {"slot": "s1-title-right", "role": "hero_word_right", "max_words": 1, "source": "spoken_fragment_or_short_label"},
            {"slot": "s1-start", "role": "cta_micro_label", "max_words": 2, "source": "spoken_fragment_or_ui_label"},
            {"slot": "s1-label", "role": "state_badge", "max_words": 1, "source": "ui_label"}
        ],
        "fallback_scene_ids": ["Scene027", "Scene009", "Scene006"]
    },
    {
        "scene_id": "Scene002",
        "root_selector": '[data-scene-root="Scene002"]',
        "scene_class": "scene-02",
        "group": "blog_opener_transformation",
        "function": "current_state_after_lifestyle_collage",
        "use_when": "Состояние сейчас/после: новая жизнь, новая версия себя, результат после решения.",
        "avoid_when": "Начальная боль, доказательство профиля, коммерческие receipts или fashion trend по номерам.",
        "compatible_recipe_hints": ["orbit_5_assets", "orbit_6_assets", "material_stack_4_assets", "magazine_grid_5_assets"],
        "asset_range": [3, 6],
        "asset_roles": ["main_video", "lifestyle_photo", "result_photo", "detail_photo"],
        "media_slots": [
            {"slot": "s2-video", "kind": "video_or_photo", "required": True, "role": "main_video"},
            {"slot": "s2-photo-01", "kind": "photo", "required": False, "role": "lifestyle_photo"},
            {"slot": "s2-photo-02", "kind": "photo", "required": False, "role": "lifestyle_photo"},
            {"slot": "s2-photo-03", "kind": "photo", "required": False, "role": "detail_photo"},
            {"slot": "s2-photo-04", "kind": "photo", "required": False, "role": "result_photo"},
            {"slot": "s2-photo-05", "kind": "photo", "required": False, "role": "lifestyle_photo"}
        ],
        "text_slots": [
            {"slot": "s2-label", "role": "state_badge", "max_words": 1, "source": "ui_label_or_spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene004", "Scene027", "Scene021"]
    },
    {
        "scene_id": "Scene003",
        "root_selector": '[data-scene-root="Scene003"]',
        "scene_class": "scene-03",
        "group": "blog_proof_profile",
        "function": "profile_social_proof",
        "use_when": "Пруф через профиль, подписчиков, автора, bio, аккаунт, доверие, рост аудитории.",
        "avoid_when": "Нет профиля/цифр/интерфейсного proof. Для денег/контрактов лучше Scene008.",
        "compatible_recipe_hints": ["proof_card_1_asset", "evidence_wall_5_assets", "evidence_wall_6_assets", "speaker_broll_0_assets"],
        "asset_range": [1, 3],
        "asset_roles": ["main_video", "profile_avatar", "profile_screenshot"],
        "media_slots": [
            {"slot": "s3-video", "kind": "video_or_photo", "required": True, "role": "main_video"},
            {"slot": "s3-avatar", "kind": "avatar_or_photo", "required": False, "role": "profile_avatar"},
            {"slot": "s3-profile-card", "kind": "synthetic_ui_card", "required": True, "role": "profile_card"}
        ],
        "text_slots": [
            {"slot": "s3-handle", "role": "profile_handle", "max_words": 2, "source": "metadata_or_ui_label"},
            {"slot": "s3-bio", "role": "profile_bio", "max_words": 12, "source": "metadata_or_short_label"},
            {"slot": "s3-stat", "role": "profile_stats", "max_words": 6, "source": "metadata_or_proof_numbers"},
            {"slot": "s3-blogu", "role": "hero_keyword", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s3-thanks", "role": "cause_keyword", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s3-label", "role": "connector_word", "max_words": 1, "source": "spoken_fragment_or_ui_label"}
        ],
        "fallback_scene_ids": ["Scene019", "Scene008", "Scene005"]
    },
    {
        "scene_id": "Scene004",
        "root_selector": '[data-scene-root="Scene004"]',
        "scene_class": "scene-04",
        "group": "blog_opener_transformation",
        "function": "lifestyle_result_moodboard",
        "use_when": "Эмоциональный payoff: жизнь стала наполненнее, ярче, социальнее, эстетичнее.",
        "avoid_when": "Нужен точный proof/статистика или одна конкретная вещь.",
        "compatible_recipe_hints": ["orbit_6_assets", "magazine_grid_6_assets", "material_stack_4_assets", "cascade_6_assets"],
        "asset_range": [4, 7],
        "asset_roles": ["main_video", "lifestyle_photo", "travel_photo", "social_photo", "detail_photo"],
        "media_slots": [
            {"slot": "s4-video", "kind": "video_or_photo", "required": True, "role": "main_video"},
            {"slot": "s4-photo-01", "kind": "photo", "required": False, "role": "lifestyle_photo"},
            {"slot": "s4-photo-02", "kind": "photo", "required": False, "role": "travel_photo"},
            {"slot": "s4-photo-03", "kind": "photo", "required": False, "role": "detail_photo"},
            {"slot": "s4-photo-04", "kind": "photo", "required": False, "role": "social_photo"},
            {"slot": "s4-photo-05", "kind": "photo", "required": False, "role": "lifestyle_photo"},
            {"slot": "s4-photo-06", "kind": "photo", "required": False, "role": "detail_photo"}
        ],
        "text_slots": [
            {"slot": "s4-life", "role": "hero_word_1", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s4-real", "role": "hero_word_2", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s4-becomes", "role": "hero_word_3", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s4-full", "role": "payoff_phrase", "max_words": 3, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene002", "Scene005", "Scene027"]
    },
    {
        "scene_id": "Scene005",
        "root_selector": '[data-scene-root="Scene005"]',
        "scene_class": "scene-05",
        "group": "blog_proof_profile",
        "function": "personal_blog_transformation_confession",
        "use_when": "Личный монолог/трансформация: я начала/поняла/изменила, spoken trust beat с красивым hero video.",
        "avoid_when": "Нужен коллаж множества предметов или fashion trend catalog.",
        "compatible_recipe_hints": ["speaker_broll_0_assets", "whisper_0_assets", "slam_0_assets", "proof_card_1_asset"],
        "asset_range": [1, 2],
        "asset_roles": ["main_video", "profile_card"],
        "media_slots": [
            {"slot": "s5-video", "kind": "video_or_photo", "required": True, "role": "main_video"},
            {"slot": "s5-profile-card", "kind": "profile_or_proof_card", "required": False, "role": "profile_card"}
        ],
        "text_slots": [
            {"slot": "s5-started", "role": "setup_phrase", "max_words": 3, "source": "spoken_fragment"},
            {"slot": "s5-blog", "role": "hero_action", "max_words": 3, "source": "spoken_fragment"},
            {"slot": "s5-english", "role": "modifier", "max_words": 3, "source": "spoken_fragment"},
            {"slot": "s5-and-my", "role": "connector", "max_words": 2, "source": "spoken_fragment"},
            {"slot": "s5-life", "role": "hero_object", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s5-180", "role": "metric_phrase", "max_words": 3, "source": "spoken_fragment"},
            {"slot": "s5-changed", "role": "payoff_word", "max_words": 1, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene006", "Scene003", "Scene009"]
    },
    {
        "scene_id": "Scene006",
        "root_selector": '[data-scene-root="Scene006"]',
        "scene_class": "scene-06",
        "group": "blog_proof_profile",
        "function": "big_claim_chapter_title",
        "use_when": "Крупный claim/название главы: как я становлюсь, почему это работает, обещание результата.",
        "avoid_when": "Нужны много фото или реальные receipts.",
        "compatible_recipe_hints": ["slam_0_assets", "whisper_0_assets", "speaker_broll_0_assets"],
        "asset_range": [1, 1],
        "asset_roles": ["main_video"],
        "media_slots": [{"slot": "s6-video", "kind": "video_or_photo", "required": True, "role": "main_video"}],
        "text_slots": [
            {"slot": "s6-how", "role": "setup_phrase", "max_words": 5, "source": "spoken_fragment"},
            {"slot": "s6-popular", "role": "hero_word_1", "max_words": 2, "source": "spoken_fragment"},
            {"slot": "s6-foreign", "role": "hero_word_2", "max_words": 2, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene005", "Scene009", "Scene001"]
    },
    {
        "scene_id": "Scene007",
        "root_selector": '[data-scene-root="Scene007"]',
        "scene_class": "scene-07",
        "group": "blog_proof_profile",
        "function": "series_or_step_ladder",
        "use_when": "Путь по сериям/этапам: 1 серия, 2 серия, 3 серия, постепенное раскрытие.",
        "avoid_when": "Нет последовательности или шагов.",
        "compatible_recipe_hints": ["beat_ladder_3_assets", "beat_ladder_4_assets", "speaker_broll_0_assets"],
        "asset_range": [1, 1],
        "asset_roles": ["main_video"],
        "media_slots": [{"slot": "s7-video", "kind": "video_or_photo", "required": True, "role": "main_video"}],
        "text_slots": [
            {"slot": "s7-number", "role": "step_number", "max_words": 1, "source": "ui_label_or_spoken_fragment"},
            {"slot": "s7-guess", "role": "setup_phrase", "max_words": 6, "source": "spoken_fragment"},
            {"slot": "s7-label-01", "role": "series_label_1", "max_words": 2, "source": "ui_label"},
            {"slot": "s7-label-02", "role": "series_label_2", "max_words": 2, "source": "ui_label"},
            {"slot": "s7-label-03", "role": "series_label_3", "max_words": 2, "source": "ui_label"}
        ],
        "fallback_scene_ids": ["Scene012", "Scene021", "Scene005"]
    },
    {
        "scene_id": "Scene008",
        "root_selector": '[data-scene-root="Scene008"]',
        "scene_class": "scene-08",
        "group": "blog_proof_profile",
        "function": "commercial_proof_receipts",
        "use_when": "Деньги, контракты, бренды, письма, сделки, коммерческий результат.",
        "avoid_when": "Нет evidence/receipts или речь не про результат/деньги.",
        "compatible_recipe_hints": ["evidence_wall_5_assets", "proof_card_1_asset", "material_stack_3_assets", "cascade_5_assets"],
        "asset_range": [2, 4],
        "asset_roles": ["main_video", "email_receipt", "contract_card", "brand_card"],
        "media_slots": [
            {"slot": "s8-video", "kind": "video_or_photo", "required": True, "role": "main_video"},
            {"slot": "s8-mail-01", "kind": "proof_card", "required": False, "role": "email_receipt"},
            {"slot": "s8-mail-02", "kind": "proof_card", "required": False, "role": "contract_card"},
            {"slot": "s8-mail-03", "kind": "proof_card", "required": False, "role": "brand_card"}
        ],
        "text_slots": [
            {"slot": "s8-contracts", "role": "proof_object", "max_words": 2, "source": "spoken_fragment"},
            {"slot": "s8-euro", "role": "amount_setup", "max_words": 3, "source": "spoken_fragment"},
            {"slot": "s8-thousands", "role": "amount", "max_words": 3, "source": "spoken_fragment"},
            {"slot": "s8-foreign", "role": "modifier", "max_words": 3, "source": "spoken_fragment"},
            {"slot": "s8-brands", "role": "proof_source", "max_words": 2, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene003", "Scene019", "Scene005"]
    },
    {
        "scene_id": "Scene009",
        "root_selector": '[data-scene-root="Scene009"]',
        "scene_class": "scene-09",
        "group": "blog_proof_profile",
        "function": "simple_bridge_or_definition",
        "use_when": "Короткий мостик/определение/связка между блоками, один спокойный смысл.",
        "avoid_when": "Нужен сильный hook, proof или плотный коллаж.",
        "compatible_recipe_hints": ["whisper_0_assets", "slam_0_assets", "speaker_broll_0_assets"],
        "asset_range": [1, 1],
        "asset_roles": ["main_video"],
        "media_slots": [{"slot": "s9-video", "kind": "video_or_photo", "required": True, "role": "main_video"}],
        "text_slots": [{"slot": "s9-caption", "role": "bridge_caption", "max_words": 6, "source": "spoken_fragment"}],
        "fallback_scene_ids": ["Scene006", "Scene025", "Scene001"]
    },
    {
        "scene_id": "Scene010",
        "root_selector": '[data-scene-root="Scene010"]',
        "scene_class": "scene-10",
        "group": "raw_explainer_meme",
        "function": "dirty_meme_logic_or_anti_gloss",
        "use_when": "Жесткая ирония, грубая метафора, антиглянцевый вывод, мемная логика.",
        "avoid_when": "Бренд-safe блог, fashion эстетика или мягкий wellness trust beat.",
        "compatible_recipe_hints": ["duel_2_assets", "sandwich_2_assets", "material_stack_2_assets", "slam_0_assets"],
        "asset_range": [2, 2],
        "asset_roles": ["main_video", "supporting_video_or_photo"],
        "media_slots": [
            {"slot": "s10-video-main", "kind": "video_or_photo", "required": True, "role": "main_video"},
            {"slot": "s10-video-small", "kind": "video_or_photo", "required": False, "role": "supporting_video_or_photo"}
        ],
        "text_slots": [
            {"slot": "s10-from", "role": "top_phrase_1", "max_words": 3, "source": "spoken_fragment"},
            {"slot": "s10-sticks", "role": "top_phrase_2", "max_words": 3, "source": "spoken_fragment"},
            {"slot": "s10-video-text", "role": "middle_phrase", "max_words": 4, "source": "spoken_fragment"},
            {"slot": "s10-bad-01", "role": "bottom_word_1", "max_words": 2, "source": "spoken_fragment"},
            {"slot": "s10-bad-02", "role": "bottom_word_2", "max_words": 2, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene012", "Scene011", "Scene025"]
    },
    {
        "scene_id": "Scene011",
        "root_selector": '[data-scene-root="Scene011"]',
        "scene_class": "scene-11",
        "group": "raw_explainer_meme",
        "function": "science_explainer_with_human_video",
        "use_when": "Научное/логическое объяснение с говорящей героиней и 1–2 science references.",
        "avoid_when": "Нет science/logic context или нужен fashion/blog proof.",
        "compatible_recipe_hints": ["quote_evidence_2_assets", "text_image_text_2_assets", "speaker_broll_0_assets", "proof_card_1_asset"],
        "asset_range": [2, 3],
        "asset_roles": ["main_video", "science_image", "science_image"],
        "media_slots": [
            {"slot": "s11-video-main", "kind": "video_or_photo", "required": True, "role": "main_video"},
            {"slot": "s11-science-left", "kind": "image", "required": False, "role": "science_image"},
            {"slot": "s11-science-right", "kind": "image", "required": False, "role": "science_image"}
        ],
        "text_slots": [
            {"slot": "s11-pink-chip", "role": "category_chip", "max_words": 1, "source": "ui_label_or_spoken_fragment"},
            {"slot": "s11-caption-text", "role": "explanation_caption", "max_words": 14, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene026", "Scene012", "Scene021"]
    },
    {
        "scene_id": "Scene012",
        "root_selector": '[data-scene-root="Scene012"]',
        "scene_class": "scene-12",
        "group": "raw_explainer_meme",
        "function": "math_or_structure_emphasis",
        "use_when": "Математика, расчет, структура, логика, повторяющееся ключевое слово.",
        "avoid_when": "Эмоциональный lifestyle payoff или proof-card.",
        "compatible_recipe_hints": ["slam_0_assets", "whisper_0_assets", "speaker_broll_0_assets", "object_hero_1_asset"],
        "asset_range": [1, 1],
        "asset_roles": ["main_video"],
        "media_slots": [{"slot": "s12-video-main", "kind": "video_or_photo", "required": True, "role": "main_video"}],
        "text_slots": [
            {"slot": "s12-side-left", "role": "repeated_keyword", "max_words": 1, "source": "spoken_fragment_or_ui_label"},
            {"slot": "s12-side-right", "role": "repeated_keyword", "max_words": 1, "source": "spoken_fragment_or_ui_label"},
            {"slot": "s12-pink-chip", "role": "keyword_chip", "max_words": 1, "source": "spoken_fragment_or_ui_label"},
            {"slot": "s12-caption", "role": "caption", "max_words": 8, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene011", "Scene025", "Scene006"]
    },
    {
        "scene_id": "Scene013",
        "root_selector": '[data-scene-root="Scene013"]',
        "scene_class": "scene-13",
        "group": "fashion_trend_moodboard",
        "function": "fashion_trend_cover",
        "use_when": "Обложка трендового блока: 3 тренда, подборка, что будет у инфлюенсеров.",
        "avoid_when": "Не fashion/style/trend topic.",
        "compatible_recipe_hints": ["magazine_grid_4_assets", "orbit_4_assets", "cascade_5_assets"],
        "asset_range": [4, 5],
        "asset_roles": ["fashion_reference", "fashion_reference", "fashion_reference", "fashion_reference", "style_avatar"],
        "media_slots": [
            {"slot": "s13-photo-01", "kind": "photo", "required": True, "role": "fashion_reference"},
            {"slot": "s13-photo-02", "kind": "photo", "required": True, "role": "fashion_reference"},
            {"slot": "s13-photo-03", "kind": "photo", "required": True, "role": "fashion_reference"},
            {"slot": "s13-photo-04", "kind": "photo", "required": True, "role": "fashion_reference"},
            {"slot": "s13-ai-avatar", "kind": "avatar_or_cutout", "required": False, "role": "style_avatar"}
        ],
        "text_slots": [
            {"slot": "s13-number", "role": "trend_count", "max_words": 1, "source": "ui_label_or_spoken_fragment"},
            {"slot": "s13-caption", "role": "cover_caption", "max_words": 8, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene017", "Scene014", "Scene018"]
    },
    {
        "scene_id": "Scene014",
        "root_selector": '[data-scene-root="Scene014"]',
        "scene_class": "scene-14",
        "group": "fashion_trend_moodboard",
        "function": "fashion_trend_numbered_moodboard",
        "use_when": "Тренд #1/#2/#3 с 3–4 визуальными примерами и style avatar.",
        "avoid_when": "Один конкретный look лучше Scene015; плотный glasses wall лучше Scene017.",
        "compatible_recipe_hints": ["magazine_grid_4_assets", "orbit_4_assets", "material_stack_4_assets"],
        "asset_range": [4, 5],
        "asset_roles": ["fashion_reference", "fashion_reference", "fashion_reference", "fashion_reference", "style_avatar"],
        "media_slots": [
            {"slot": "s14-photo-01", "kind": "photo", "required": True, "role": "fashion_reference"},
            {"slot": "s14-photo-02", "kind": "photo", "required": True, "role": "fashion_reference"},
            {"slot": "s14-photo-03", "kind": "photo", "required": True, "role": "fashion_reference"},
            {"slot": "s14-photo-04", "kind": "photo", "required": True, "role": "fashion_reference"},
            {"slot": "s14-ai-avatar", "kind": "avatar_or_cutout", "required": False, "role": "style_avatar"}
        ],
        "text_slots": [
            {"slot": "s14-pink-chip", "role": "english_tag", "max_words": 2, "source": "ui_label_or_search_keyword"},
            {"slot": "s14-hash", "role": "trend_number", "max_words": 1, "source": "ui_label"},
            {"slot": "s14-title", "role": "trend_title", "max_words": 8, "source": "spoken_fragment"},
            {"slot": "s14-avatar-label", "role": "avatar_tag", "max_words": 1, "source": "ui_label"}
        ],
        "fallback_scene_ids": ["Scene017", "Scene018", "Scene016"]
    },
    {
        "scene_id": "Scene015",
        "root_selector": '[data-scene-root="Scene015"]',
        "scene_class": "scene-15",
        "group": "fashion_trend_moodboard",
        "function": "single_fashion_look_example",
        "use_when": "Один конкретный пример образа, один dominant look/background.",
        "avoid_when": "Нужна подборка из многих примеров.",
        "compatible_recipe_hints": ["object_hero_1_asset", "proof_card_1_asset", "single_image_editorial", "text_image_text_1_asset"],
        "asset_range": [1, 2],
        "asset_roles": ["fashion_look", "style_avatar"],
        "media_slots": [
            {"slot": "s15-bg", "kind": "photo", "required": True, "role": "fashion_look"},
            {"slot": "s15-ai-avatar", "kind": "avatar_or_cutout", "required": False, "role": "style_avatar"}
        ],
        "text_slots": [
            {"slot": "s15-hash", "role": "trend_number", "max_words": 1, "source": "ui_label"},
            {"slot": "s15-caption", "role": "look_caption", "max_words": 4, "source": "spoken_fragment_or_ui_label"},
            {"slot": "s15-avatar-label", "role": "avatar_tag", "max_words": 1, "source": "ui_label"}
        ],
        "fallback_scene_ids": ["Scene016", "Scene014", "Scene018"]
    },
    {
        "scene_id": "Scene016",
        "root_selector": '[data-scene-root="Scene016"]',
        "scene_class": "scene-16",
        "group": "fashion_trend_moodboard",
        "function": "fashion_look_collage_or_breakdown",
        "use_when": "Разбор образа: один main look + 2–3 детали/варианта вокруг.",
        "avoid_when": "Обложка трендов или proof-profile.",
        "compatible_recipe_hints": ["material_stack_4_assets", "orbit_4_assets", "magazine_grid_4_assets"],
        "asset_range": [4, 5],
        "asset_roles": ["fashion_look", "fashion_detail", "fashion_detail", "fashion_detail", "style_avatar"],
        "media_slots": [
            {"slot": "s16-look-main", "kind": "photo", "required": True, "role": "fashion_look"},
            {"slot": "s16-look-top", "kind": "photo", "required": False, "role": "fashion_detail"},
            {"slot": "s16-look-right", "kind": "photo", "required": False, "role": "fashion_detail"},
            {"slot": "s16-look-bottom", "kind": "photo", "required": False, "role": "fashion_detail"},
            {"slot": "s16-ai-avatar", "kind": "avatar_or_cutout", "required": False, "role": "style_avatar"}
        ],
        "text_slots": [
            {"slot": "s16-keyword", "role": "single_keyword", "max_words": 1, "source": "spoken_fragment_or_ui_label"},
            {"slot": "s16-avatar-label", "role": "avatar_tag", "max_words": 1, "source": "ui_label"}
        ],
        "fallback_scene_ids": ["Scene015", "Scene014", "Scene017"]
    },
    {
        "scene_id": "Scene017",
        "root_selector": '[data-scene-root="Scene017"]',
        "scene_class": "scene-17",
        "group": "fashion_trend_moodboard",
        "function": "dense_fashion_trend_wall",
        "use_when": "Тренд с большим количеством визуальных примеров: очки, сумки, обувь, repeated same-family items.",
        "avoid_when": "Один look или один предмет hero.",
        "compatible_recipe_hints": ["magazine_grid_6_assets", "evidence_wall_6_assets", "cascade_6_assets", "orbit_6_assets"],
        "asset_range": [5, 8],
        "asset_roles": ["fashion_reference"],
        "media_slots": [
            {"slot": f"s17-photo-0{i}", "kind": "photo", "required": i <= 5, "role": "fashion_reference"} for i in range(1, 8)
        ] + [{"slot": "s17-ai-avatar", "kind": "avatar_or_cutout", "required": False, "role": "style_avatar"}],
        "text_slots": [
            {"slot": "s17-hash", "role": "trend_number", "max_words": 1, "source": "ui_label"},
            {"slot": "s17-title", "role": "trend_title", "max_words": 7, "source": "spoken_fragment"},
            {"slot": "s17-avatar-label", "role": "avatar_tag", "max_words": 1, "source": "ui_label"}
        ],
        "fallback_scene_ids": ["Scene014", "Scene016", "Scene018"]
    },
    {
        "scene_id": "Scene018",
        "root_selector": '[data-scene-root="Scene018"]',
        "scene_class": "scene-18",
        "group": "fashion_trend_moodboard",
        "function": "fashion_item_hero_with_supporting_examples",
        "use_when": "Тренд с одним главным предметом/category hero: пальто, сумка, балетки, шарф.",
        "avoid_when": "Нужен dense wall или один full look.",
        "compatible_recipe_hints": ["object_hero_1_asset", "material_stack_3_assets", "orbit_3_assets", "magazine_grid_4_assets"],
        "asset_range": [3, 5],
        "asset_roles": ["fashion_reference", "fashion_reference", "fashion_cutout", "fashion_reference", "style_avatar"],
        "media_slots": [
            {"slot": "s18-photo-01", "kind": "photo", "required": True, "role": "fashion_reference"},
            {"slot": "s18-photo-02", "kind": "photo", "required": True, "role": "fashion_reference"},
            {"slot": "s18-yellow-cutout", "kind": "cutout_or_photo", "required": True, "role": "fashion_cutout"},
            {"slot": "s18-photo-03", "kind": "photo", "required": False, "role": "fashion_reference"},
            {"slot": "s18-ai-avatar", "kind": "avatar_or_cutout", "required": False, "role": "style_avatar"}
        ],
        "text_slots": [
            {"slot": "s18-hash", "role": "trend_number", "max_words": 1, "source": "ui_label"},
            {"slot": "s18-title", "role": "trend_title", "max_words": 5, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene015", "Scene014", "Scene017"]
    },
    {
        "scene_id": "Scene019",
        "root_selector": '[data-scene-root="Scene019"]',
        "scene_class": "scene-19",
        "group": "fashion_trend_moodboard",
        "function": "blog_or_profile_proof_after_fashion",
        "use_when": "После трендов показать, что у автора есть блог/аудитория/профиль/контентная база.",
        "avoid_when": "Нет blog/profile proof, не fashion/blog context.",
        "compatible_recipe_hints": ["proof_card_1_asset", "evidence_wall_6_assets", "magazine_grid_6_assets"],
        "asset_range": [1, 3],
        "asset_roles": ["profile_card", "style_avatar", "stats_grid"],
        "media_slots": [
            {"slot": "s19-profile-card", "kind": "profile_or_proof_card", "required": True, "role": "profile_card"},
            {"slot": "s19-grid-bg", "kind": "synthetic_stats_grid", "required": False, "role": "stats_grid"},
            {"slot": "s19-ai-avatar", "kind": "avatar_or_cutout", "required": False, "role": "style_avatar"}
        ],
        "text_slots": [{"slot": "s19-headline", "role": "proof_headline", "max_words": 10, "source": "spoken_fragment"}],
        "fallback_scene_ids": ["Scene003", "Scene008", "Scene013"]
    },
    {
        "scene_id": "Scene020",
        "root_selector": '[data-scene-root="Scene020"]',
        "scene_class": "scene-20",
        "group": "habit_fitness_diary",
        "function": "habit_result_streak_metric",
        "use_when": "Результат привычки/streak: дни, тренировки, ни одного пропуска, прогресс, дисциплина.",
        "avoid_when": "Нет цифры/результата/серии; для вопроса-сомнения лучше Scene023.",
        "compatible_recipe_hints": ["proof_card_1_asset", "evidence_wall_5_assets", "beat_ladder_4_assets", "magazine_grid_4_assets"],
        "asset_range": [1, 5],
        "asset_roles": ["background_video", "habit_proof_card", "fitness_action_photo", "calendar_or_metric_card"],
        "media_slots": [
            {"slot": "s20-background", "kind": "video_or_photo", "required": True, "role": "background_video"},
            {"slot": "s20-card-01", "kind": "photo_or_card", "required": False, "role": "habit_proof_card"},
            {"slot": "s20-card-02", "kind": "photo_or_card", "required": False, "role": "fitness_action_photo"},
            {"slot": "s20-card-03", "kind": "photo_or_card", "required": False, "role": "calendar_or_metric_card"},
            {"slot": "s20-card-04", "kind": "photo_or_card", "required": False, "role": "habit_proof_card"}
        ],
        "text_slots": [
            {"slot": "s20-note", "role": "series_note", "max_words": 4, "source": "ui_label"},
            {"slot": "s20-last", "role": "setup_phrase", "max_words": 3, "source": "spoken_fragment"},
            {"slot": "s20-metric", "role": "metric_phrase", "max_words": 6, "source": "spoken_fragment"},
            {"slot": "s20-none", "role": "emphasis_word", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s20-training", "role": "object_word", "max_words": 2, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene021", "Scene024", "Scene025"]
    },
    {
        "scene_id": "Scene021",
        "root_selector": '[data-scene-root="Scene021"]',
        "scene_class": "scene-21",
        "group": "habit_fitness_diary",
        "function": "habit_explanation_collage",
        "use_when": "Разбор причины/мифа: это не потому что..., почему привычка держится, 4–5 diary visuals.",
        "avoid_when": "Одна цитата/сомнение или чистая нейробиология.",
        "compatible_recipe_hints": ["material_stack_4_assets", "orbit_5_assets", "beat_ladder_4_assets", "cascade_5_assets"],
        "asset_range": [3, 5],
        "asset_roles": ["diary_photo", "habit_action_photo", "main_video", "fitness_detail_photo"],
        "media_slots": [
            {"slot": "s21-photo-01", "kind": "photo", "required": False, "role": "diary_photo"},
            {"slot": "s21-photo-02", "kind": "photo", "required": False, "role": "habit_action_photo"},
            {"slot": "s21-photo-03", "kind": "video_or_photo", "required": True, "role": "main_video"},
            {"slot": "s21-photo-04", "kind": "photo", "required": False, "role": "fitness_detail_photo"},
            {"slot": "s21-photo-05", "kind": "photo", "required": False, "role": "diary_photo"}
        ],
        "text_slots": [
            {"slot": "s21-note-left", "role": "series_note", "max_words": 4, "source": "ui_label"},
            {"slot": "s21-note-right", "role": "handle", "max_words": 1, "source": "ui_label"},
            {"slot": "s21-this", "role": "word_1", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s21-not", "role": "word_2", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s21-because", "role": "word_3", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s21-that", "role": "word_4", "max_words": 1, "source": "spoken_fragment"},
            {"slot": "s21-sharp", "role": "punch_word", "max_words": 1, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene020", "Scene024", "Scene026"]
    },
    {
        "scene_id": "Scene022",
        "root_selector": '[data-scene-root="Scene022"]',
        "scene_class": "scene-22",
        "group": "habit_fitness_diary",
        "function": "single_action_context_clip",
        "use_when": "Конкретное действие/обстоятельство одним клипом: в дождь, утром, после работы, без сил.",
        "avoid_when": "Нужна длинная мысль или proof metric.",
        "compatible_recipe_hints": ["object_hero_1_asset", "speaker_broll_0_assets", "text_image_text_1_asset"],
        "asset_range": [1, 1],
        "asset_roles": ["action_video"],
        "media_slots": [{"slot": "s22-video-card", "kind": "video_or_photo", "required": True, "role": "action_video"}],
        "text_slots": [
            {"slot": "s22-note-left", "role": "series_note", "max_words": 4, "source": "ui_label"},
            {"slot": "s22-note-right", "role": "handle", "max_words": 1, "source": "ui_label"},
            {"slot": "s22-video-caption", "role": "action_caption", "max_words": 3, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene024", "Scene021", "Scene025"]
    },
    {
        "scene_id": "Scene023",
        "root_selector": '[data-scene-root="Scene023"]',
        "scene_class": "scene-23",
        "group": "habit_fitness_diary",
        "function": "inner_question_or_resistance_quote",
        "use_when": "Внутреннее сомнение/вопрос/сопротивление: зачем мне это, я не хочу, а смысл.",
        "avoid_when": "Нужно объяснение, статистика или действие.",
        "compatible_recipe_hints": ["quote_evidence_1_asset", "whisper_0_assets", "final_fork_0_assets", "final_fork_1_asset"],
        "asset_range": [0, 3],
        "asset_roles": ["creator_card", "reaction_photo", "pet_or_meme_photo"],
        "media_slots": [
            {"slot": "s23-creator", "kind": "photo_or_card", "required": False, "role": "creator_card"},
            {"slot": "s23-cat-top", "kind": "photo", "required": False, "role": "reaction_photo"},
            {"slot": "s23-cat-bottom", "kind": "photo", "required": False, "role": "pet_or_meme_photo"}
        ],
        "text_slots": [
            {"slot": "s23-note-left", "role": "series_note", "max_words": 4, "source": "ui_label"},
            {"slot": "s23-note-right", "role": "handle", "max_words": 1, "source": "ui_label"},
            {"slot": "s23-quote", "role": "quote", "max_words": 8, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene025", "Scene022", "Scene026"]
    },
    {
        "scene_id": "Scene024",
        "root_selector": '[data-scene-root="Scene024"]',
        "scene_class": "scene-24",
        "group": "habit_fitness_diary",
        "function": "specific_habit_action",
        "use_when": "Конкретный ритуал/действие: расстилала коврик, надевала кроссовки, шла в зал.",
        "avoid_when": "Абстрактное объяснение или сложная статистика.",
        "compatible_recipe_hints": ["duel_2_assets", "text_image_text_2_assets", "material_stack_2_assets", "speaker_broll_0_assets"],
        "asset_range": [2, 2],
        "asset_roles": ["action_video", "supporting_photo"],
        "media_slots": [
            {"slot": "s24-video", "kind": "video_or_photo", "required": True, "role": "action_video"},
            {"slot": "s24-photo", "kind": "photo", "required": False, "role": "supporting_photo"}
        ],
        "text_slots": [
            {"slot": "s24-note-left", "role": "series_note", "max_words": 4, "source": "ui_label"},
            {"slot": "s24-note-right", "role": "handle", "max_words": 1, "source": "ui_label"},
            {"slot": "s24-statement", "role": "action_statement", "max_words": 4, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene022", "Scene021", "Scene025"]
    },
    {
        "scene_id": "Scene025",
        "root_selector": '[data-scene-root="Scene025"]',
        "scene_class": "scene-25",
        "group": "habit_fitness_diary",
        "function": "large_text_takeaway",
        "use_when": "Финальный/серединный вывод с длинной фразой, без необходимости медиа.",
        "avoid_when": "Можно показать конкретный предмет, proof, действие или fashion moodboard.",
        "compatible_recipe_hints": ["slam_0_assets", "whisper_0_assets", "final_fork_0_assets"],
        "asset_range": [0, 0],
        "asset_roles": [],
        "media_slots": [],
        "text_slots": [
            {"slot": "s25-note-left", "role": "series_note", "max_words": 4, "source": "ui_label"},
            {"slot": "s25-note-right", "role": "handle", "max_words": 1, "source": "ui_label"},
            {"slot": "s25-statement", "role": "takeaway_statement", "max_words": 12, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene023", "Scene012", "Scene009"]
    },
    {
        "scene_id": "Scene026",
        "root_selector": '[data-scene-root="Scene026"]',
        "scene_class": "scene-26",
        "group": "habit_fitness_diary",
        "function": "neuro_science_explainer",
        "use_when": "Нейробиология/психология привычек/мозг/импульсы, одна scientific card.",
        "avoid_when": "Нет science explanation; для raw math лучше Scene012/011.",
        "compatible_recipe_hints": ["proof_card_1_asset", "object_hero_1_asset", "quote_evidence_1_asset", "text_image_text_1_asset"],
        "asset_range": [1, 1],
        "asset_roles": ["science_image"],
        "media_slots": [{"slot": "s26-image-card", "kind": "image", "required": True, "role": "science_image"}],
        "text_slots": [
            {"slot": "s26-note-left", "role": "series_note", "max_words": 4, "source": "ui_label"},
            {"slot": "s26-note-right", "role": "handle", "max_words": 1, "source": "ui_label"},
            {"slot": "s26-statement", "role": "science_statement", "max_words": 10, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene011", "Scene012", "Scene025"]
    },
    {
        "scene_id": "Scene027",
        "root_selector": '[data-scene-root="Scene027"]',
        "scene_class": "scene-27",
        "group": "blog_opener_transformation",
        "function": "pain_opener_before_life_style",
        "use_when": "Боль/хук: скучные будни, не нравится стиль, ощущение что жизнь не такая, before-state.",
        "avoid_when": "Результат/после, social proof, fashion trend catalog, habit streak.",
        "compatible_recipe_hints": ["duel_2_assets", "material_stack_2_assets", "speaker_broll_0_assets", "quote_evidence_2_assets"],
        "asset_range": [2, 3],
        "asset_roles": ["main_video", "pain_photo", "pain_photo"],
        "media_slots": [
            {"slot": "s27-video", "kind": "video_or_photo", "required": True, "role": "main_video"},
            {"slot": "s27-photo-top", "kind": "photo", "required": False, "role": "pain_photo"},
            {"slot": "s27-photo-bottom", "kind": "photo", "required": False, "role": "pain_photo"}
        ],
        "text_slots": [
            {"slot": "s27-copy-right", "role": "pain_phrase_1", "max_words": 7, "source": "spoken_fragment"},
            {"slot": "s27-copy-left", "role": "pain_phrase_2", "max_words": 5, "source": "spoken_fragment"}
        ],
        "fallback_scene_ids": ["Scene001", "Scene002", "Scene023"]
    }
]

GIRLY_SCENE_IDS = [scene["scene_id"] for scene in GIRLY_SCENE_REGISTRY]

GIRLY_ASSET_ROLES = sorted({role for scene in GIRLY_SCENE_REGISTRY for role in scene.get("asset_roles", [])})

GIRLY_GROUPS = sorted({scene["group"] for scene in GIRLY_SCENE_REGISTRY})


def get_girly_scene(scene_id: str) -> dict[str, Any] | None:
    for scene in GIRLY_SCENE_REGISTRY:
        if scene["scene_id"] == scene_id:
            return scene
    return None


def build_girly_scene_registry_json() -> str:
    return json.dumps(
        {
            "version": "girly_static_scene_registry_v1",
            "scene_ids": GIRLY_SCENE_IDS,
            "groups": GIRLY_GROUPS,
            "asset_roles": GIRLY_ASSET_ROLES,
            "scenes": GIRLY_SCENE_REGISTRY,
        },
        ensure_ascii=False,
        indent=2,
    )


def append_girly_scene_cookbook(prompt: str) -> str:
    if GIRLY_SCENE_COOKBOOK_MARKER in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{build_girly_scene_cookbook()}\n"


def build_girly_scene_cookbook() -> str:
    registry_compact = []
    for scene in GIRLY_SCENE_REGISTRY:
        registry_compact.append(
            {
                "scene_id": scene["scene_id"],
                "group": scene["group"],
                "function": scene["function"],
                "use_when": scene["use_when"],
                "avoid_when": scene["avoid_when"],
                "compatible_recipe_hints": scene["compatible_recipe_hints"],
                "asset_range": scene["asset_range"],
                "asset_roles": scene["asset_roles"],
                "media_slots": scene["media_slots"],
                "text_slots": scene["text_slots"],
                "fallback_scene_ids": scene["fallback_scene_ids"],
            }
        )

    return f"""# {GIRLY_SCENE_COOKBOOK_MARKER}

You are no longer choosing generic/poor VFX layouts. You are choosing from the
existing `static_girly/index.html` scene library. Every Stage 1 storyboard scene
must be executable by cloning one of the ready girly scene roots `Scene001` to
`Scene027`, then filling its media and text slots.

Core contract:

```text
story meaning -> girly scene group -> concrete SceneXXX -> slot plan -> asset queries
```

Do not choose the scene by visual coincidence. Choose by storytelling function,
then asset type/count, then text density. The existing scene composition is the
layout. Gemini must not invent a new layout family for these videos.

The old `layout_recipe_hint` stays as a secondary geometry/asset-count hint for
validators and fallbacks. The primary style decision is `girly_scene.scene_id`.

Required additional object for every `scenes[]` item:

```json
{{
  "girly_scene": {{
    "scene_id": "Scene027",
    "scene_group": "blog_opener_transformation",
    "storytelling_function": "pain_opener_before_life_style",
    "semantic_reason": "This is a before-state pain hook about boring life/style, so it must use the pain opener template.",
    "asset_semantics": ["main_video", "pain_photo", "pain_photo"],
    "slot_plan": [
      {{
        "slot": "s27-video",
        "slot_type": "media",
        "role": "main_video",
        "required": true,
        "visual_asset_index": 0,
        "text": null,
        "text_source": null,
        "appears_on_word": "..."
      }},
      {{
        "slot": "s27-copy-right",
        "slot_type": "text",
        "role": "pain_phrase_1",
        "required": true,
        "visual_asset_index": null,
        "text": "вам не нравится ваш стиль",
        "text_source": "spoken_fragment",
        "appears_on_word": "стиль"
      }}
    ],
    "fallback_scene_id": "Scene001",
    "do_not_use_scene_ids": ["Scene003", "Scene020"]
  }}
}}
```

Slot text rules:
- `voiceover_line` remains the primary spoken/visible text source.
- Text slots with `text_source: "spoken_fragment"` must copy an exact substring
  or clean phrase from `voiceover_line`; do not invent a separate headline.
- Tiny template UI labels are allowed only with `text_source: "ui_label"`, for
  example `#1`, `style`, `до`, `сейчас`, `@anti_lili`. They are decorative labels,
  not alternate narration.
- If the phrase cannot fit the scene's max text slots, split the voiceover into
  two scenes instead of shrinking the template or generating new CSS.

Asset rules:
- Every `visual_assets[]` item should be written for a girly slot, not as a
  generic VFX idea.
- Add `girly_asset_role` and `preferred_slot` to each visual asset when useful.
  If the strict schema does not expose those fields, include the role in `asset`
  and `why` clearly; later bridge code can map it.
- Do not search for transparent PNGs/icons unless the slot explicitly says
  `cutout_or_photo`. Prefer real photos, fashion references, diary photos,
  profile/proof cards, science images, or main b-roll video.
- Do not pad asset count. Pick a simpler scene in the same group when assets are
  missing. Pick a collage scene in the same group when assets are abundant.

Domain lock:
- Blog/style transformation: use Scene027, Scene001, Scene002, Scene004.
- Blog/profile/commercial proof: use Scene003, Scene005, Scene006, Scene007,
  Scene008, Scene009.
- Raw explainer/meme/math/science: use Scene010, Scene011, Scene012.
- Fashion trends/style moodboard: use Scene013, Scene014, Scene015, Scene016,
  Scene017, Scene018, Scene019.
- Habit/fitness/anti_lili diary: use Scene020, Scene021, Scene022, Scene023,
  Scene024, Scene025, Scene026.

Do not mix groups casually. A video can move between groups only if the story
moves there: e.g. habit diary -> neuro explainer is okay; fashion trend -> blog
proof is okay. Fashion scenes are not generic collages. Habit scenes are not
blog scenes. Blog profile scenes are not proof for medical/science claims.

Allowed girly scene registry:

```json
{json.dumps(registry_compact, ensure_ascii=False, indent=2)}
```

Selection examples:

```json
{{
  "scene_type": "COLLAGE",
  "voiceover_line": "вам не нравится ваш стиль и будни",
  "layout_recipe_hint": "duel_2_assets",
  "target_visual_asset_count": 2,
  "girly_scene": {{
    "scene_id": "Scene027",
    "scene_group": "blog_opener_transformation",
    "storytelling_function": "pain_opener_before_life_style",
    "semantic_reason": "Pain opener about style and boring daily life; Scene027 is the dedicated before-state hook.",
    "asset_semantics": ["main_video", "pain_photo", "pain_photo"],
    "slot_plan": [
      {{"slot": "s27-video", "slot_type": "media", "role": "main_video", "required": true, "visual_asset_index": 0, "text": null, "text_source": null, "appears_on_word": "стиль"}},
      {{"slot": "s27-photo-top", "slot_type": "media", "role": "pain_photo", "required": false, "visual_asset_index": 1, "text": null, "text_source": null, "appears_on_word": "будни"}},
      {{"slot": "s27-copy-right", "slot_type": "text", "role": "pain_phrase_1", "required": true, "visual_asset_index": null, "text": "вам не нравится ваш стиль и будни", "text_source": "spoken_fragment", "appears_on_word": "стиль"}}
    ],
    "fallback_scene_id": "Scene001",
    "do_not_use_scene_ids": ["Scene003", "Scene020"]
  }}
}}
```

```json
{{
  "scene_type": "COLLAGE",
  "voiceover_line": "первый тренд — головные уборы и мягкие фактуры",
  "layout_recipe_hint": "magazine_grid_4_assets",
  "target_visual_asset_count": 4,
  "girly_scene": {{
    "scene_id": "Scene014",
    "scene_group": "fashion_trend_moodboard",
    "storytelling_function": "fashion_trend_numbered_moodboard",
    "semantic_reason": "Numbered fashion trend with 4 references; Scene014 is the trend moodboard template.",
    "asset_semantics": ["fashion_reference", "fashion_reference", "fashion_reference", "fashion_reference"],
    "slot_plan": [
      {{"slot": "s14-photo-01", "slot_type": "media", "role": "fashion_reference", "required": true, "visual_asset_index": 0, "text": null, "text_source": null, "appears_on_word": "головные"}},
      {{"slot": "s14-photo-02", "slot_type": "media", "role": "fashion_reference", "required": true, "visual_asset_index": 1, "text": null, "text_source": null, "appears_on_word": "уборы"}},
      {{"slot": "s14-pink-chip", "slot_type": "text", "role": "english_tag", "required": false, "visual_asset_index": null, "text": "headwear", "text_source": "ui_label", "appears_on_word": "головные"}},
      {{"slot": "s14-title", "slot_type": "text", "role": "trend_title", "required": true, "visual_asset_index": null, "text": "тренд #1 головные уборы", "text_source": "spoken_fragment", "appears_on_word": "тренд"}}
    ],
    "fallback_scene_id": "Scene017",
    "do_not_use_scene_ids": ["Scene020", "Scene003"]
  }}
}}
```
"""
