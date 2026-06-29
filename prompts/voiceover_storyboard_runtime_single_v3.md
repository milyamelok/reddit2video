Сгенерируй сценарий по MASTER PROMPT.

MASTER PROMPT включает cached Pipeline v4 recipe cookbook. Используй его как
словарь сцен: сначала смысл сцены, потом layout_recipe_hint, потом количество
foreground assets. Не выбирай recipe по случайной эстетике.
MASTER PROMPT также включает cached Story Format Cookbook. Сначала выбери ровно
один `story_format`, затем пиши историю и scenes внутри его 6-beat skeleton.

Дополнительные требования к этому ролику:
- Весь production-facing output пиши на русском: title, source_digest, story_strategy,
  voiceover, scene directions, visual asset labels, why, animation, typography notes.
- Английский разрешен только в search_query, ai_image_prompt и реальных названиях мемов.
- Не упоминай Reddit, тред, пост, комментарии.
- Voiceover должен звучать как личное наблюдение от лица девушки.
- Сделай 18-26 сцен.
- Не фиксируй TEXT_ONLY/AVATAR по количеству. Выбирай тип сцены по смыслу.
- TEXT_ONLY используй как редкий акцент: обычно 3-5 сцен и не больше 12-15%
  длительности. Не ставь две TEXT_ONLY сцены подряд.
- Не делай финальную треть ролика длинным хвостом из TEXT_ONLY сцен; после
  каждого текстового панча возвращайся в COLLAGE или AVATAR.
- Сцены с числами, доказательствами, сравнением, действием, предметом, бытовой
  ситуацией или визуальной метафорой не должны быть TEXT_ONLY.
- Финальный bait-question с выбором между двумя лагерями обычно делай
  `final_fork_0_assets` или `final_fork_1_asset`, а не голым текстом.
- AVATAR-сцены нужны для доверия/эмоции/объяснения; каждая не короче 2 секунд.
- Speaker share считай по длительности: обычно 25-40% видео, часто это 2-4
  длинных AVATAR-сегмента, а не 5 коротких.
- COLLAGE-сцены могут иметь 1-6 визуальных ассетов в зависимости от
  layout_recipe_hint и смысла сцены.
- Не добавляй ассеты ради квоты. Одна сильная картинка лучше трех filler cards.
- Каждый visual asset описывай 2-3 словами.
- Все `search_query` для Google Images, Pinterest, Giphy, Stock/Footage и
  background должны быть на английском. Не используй русские поисковые запросы.
- В Google Images/Pinterest image search_query не проси `transparent background`, `png`, `icon`,
  `screenshot`, `app screen` или `interface`. Ищи реальную картинку/объект:
  `pink dumbbell close up photo`, `dog food bag photo`, `female bicep
  illustration`, а не `transparent background`.
- Для AVATAR `background` не добавляй префикс `Avatar background:` и не используй
  слово `blurred`; пиши коротко: `aesthetic supplement shelf`, `doctor office hallway`.
- Для каждой сцены, где это полезно, заполни:
  layout_recipe_hint, target_visual_asset_count, asset_count_reason.
- Используй count-specific layout_recipe_hint из cached cookbook. Не пиши
  legacy base names вроде `duel` или `cascade`. Пиши так:
  `duel_2_assets`, `material_stack_3_assets`, `orbit_4_assets`,
  `cascade_5_assets`, `evidence_wall_6_assets`, `speaker_broll_0_assets`,
  `final_fork_0_assets`, `final_fork_1_asset`.
- У каждой сцены обязательно должен быть непустой voiceover_line.
- Не добавляй отдельное поле для экранного текста. В pipeline v3 видимый текст сцены всегда
  берется из voiceover_line, чтобы ElevenLabs word timings точно управляли
  typewriter-текстом и появлением assets.
- Если видимая фраза кажется слишком длинной, разбей ее на несколько сцен;
  не делай отдельный сокращенный заголовок.
- В AVATAR сценах не добавляй collage visual_assets специально для фона:
  поле background будет автоматически резолвиться как Pinterest/stock footage,
  avatar будет маленьким overlay внизу справа, примерно 1/5 площади кадра.
- В TEXT_ONLY сценах visual_assets обычно пустой.
- В COLLAGE:
  1 asset = single object/proof,
  2 assets = contrast/choice,
  3-4 assets = normal collage,
  5-6 assets = evidence wall/orbit/grid/list only.
- Жестко соблюдай совместимость recipe-суффикса и количества ассетов:
  `object_hero_1_asset` = ровно 1,
  `duel_2_assets` / `sandwich_2_assets` = ровно 2,
  `material_stack_3_assets` = ровно 3,
  `orbit_4_assets` = ровно 4,
  `cascade_5_assets` = ровно 5,
  `speaker_broll_0_assets` = ровно 0 foreground assets.
- Планируй плотность речи разумно: обычно 2.2-2.8 слов/сек, желательно не выше
  3.2 слов/сек для строк от 8 слов. Если не помещается, увеличь duration_sec
  или разбей сцену. Это ориентир до реальной TTS/alignment, а не повод ломать
  хороший hook.
- Финал - bait-question с выбором лагеря.
- Избегай медицинской уверенности.
- Сделай язык максимально визуальным: чтобы к каждой фразе было понятно, что показывать.
- Верни только JSON по structured schema.

Вот материал:
{{PASTE_POST_AND_COMMENTS_HERE}}
