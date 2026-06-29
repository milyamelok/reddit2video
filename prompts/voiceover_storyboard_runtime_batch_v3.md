Сгенерируй сценарии по MASTER PROMPT для каждого материала ниже.

Для каждого поста:
- весь production-facing output пиши на русском: title, source_digest, story_strategy,
  voiceover, scene directions, visual asset labels, why, animation, typography notes;
- английский разрешен только в search_query, ai_image_prompt и реальных названиях мемов;
- выбери ровно один `story_format` из cached Story Format Cookbook и строй
  историю внутри его 6-beat skeleton;
- выбери неповторяющийся story_engine;
- по возможности не повторяй один и тот же story_format во всех сценариях;
- не начинай все ролики одинаково;
- не используй "почему мне никто не сказал" чаще чем в одном из четырех сценариев;
- следи, чтобы визуальные семьи различались;
- возвращай массив JSON-объектов;
- каждый сценарий 18-24 сцены;
- в каждом сценарии 4-6 TEXT_ONLY, 4-6 AVATAR, остальные COLLAGE;
- у каждой сцены обязательно должен быть непустой voiceover_line;
- не добавляй отдельное поле для экранного текста: в pipeline v3 видимый текст сцены всегда
  берется из voiceover_line, чтобы ElevenLabs word timings точно управляли
  typewriter-текстом и появлением assets;
- если фраза слишком длинная для кадра, разбей ее на несколько сцен, а не
  добавляй отдельный короткий screen headline;
- для AVATAR voiceover_line становится центральной marquee/kinetic строкой;
  background будет автоматически резолвиться как Pinterest/stock footage,
  avatar будет маленьким overlay внизу справа, примерно 1/5 площади кадра;
- voiceover без упоминания источника.

Материалы:
{{PASTE_BATCH_HERE}}
