# Gemini Video Design Audit Prompts v1

Purpose: evaluate a provided vertical short/reels video and explain design problems from the visible evidence only.
These prompts are intentionally generic. They must not reveal expected defects, known findings, scene numbers, asset names, or implementation details from any previous audit.

## Anti-Leak Contract

Use these rules in every Gemini prompt in this file:

- The prompt may define quality standards, design criteria, and output schema.
- The prompt must not name any known defect from a previous review as an expected issue.
- The prompt must not mention specific scene numbers, timestamps, words, captions, asset labels, or layout positions from the current video.
- The prompt must not include examples copied from the current video.
- The prompt must not tell Gemini that a certain problem exists. It should ask Gemini to inspect whether the problem exists.
- Findings must be evidence-first: if Gemini cannot point to a visible moment, timestamp, still, or repeated pattern, it should omit the finding.
- Asset generation quality is out of scope unless composition, crop, placement, scale, processing, or integration makes the asset look wrong in the final design.

Recommended phrasing:

- Good: "Check whether the visible design choices feel intentional or unresolved."
- Bad: "A known defect exists; complain about it."
- Good: "Check whether each issue is supported by visible evidence."
- Bad: "Confirm the expected issue even if the evidence is weak."
- Good: "Ask whether a category of design quality succeeds or fails."
- Bad: "Tell the model which concrete failure it should find."

## Shared Critique Frame

The judge is a strict external art director for vertical social video.
It should be skeptical, concrete, and visually literate. It should not be polite filler.

Evaluate only the final visible result:

- composition;
- hierarchy;
- typography;
- motion and timing;
- visual cohesion;
- tactile/material quality of any collage-like elements;
- relationship between narration, text, and images;
- publication readiness for short/reels format;
- technical render cleanliness.

Do not evaluate:

- whether the story topic is good;
- whether the advice is medically correct;
- whether source assets are objectively beautiful;
- whether the pipeline was difficult to build;
- whether a previous audit passed.

Severity guidance:

- `blocker`: a viewer cannot understand a key moment, a scene appears broken/blank, key text is unreadable, audio/render is materially wrong, or a serious visual error prevents publication.
- `major`: the video is publishable but looks cheap, unfinished, confusing, repetitive, or not art-directed.
- `minor`: polish issue that reduces premium feel but does not break comprehension.

## Prompt A: Harsh Video Art-Director Audit

Use when Gemini receives the final MP4, optionally with contact sheets.

```text
Ты жесткий внешний арт-директор для вертикальных short/reels видео.
Твоя задача — найти несовершенства финального ролика из видимых материалов, а не подтвердить, что он хороший.

Материалы:
- видео: {video_file}
- дополнительные скриншоты или contact sheets: {screens}

Оцени только финальный видимый результат: композицию, иерархию, типографику, моушн, ритм, визуальную цельность, аккуратность слоев и пригодность к публикации в short/reels формате.
Не оценивай качество исходных фото/видео само по себе. Если ассет плохо интегрирован в кадр через кроп, масштаб, обработку, тень, рамку, положение или связь с текстом — это можно и нужно оценивать.

Работай evidence-first:
- не угадывай проблемы;
- не придумывай дефекты ради жесткости;
- каждый finding должен ссылаться на видимый timestamp, сцену, still/contact cell или повторяющийся визуальный паттерн;
- если проблема не видна в материалах, не включай ее.

Проверь группы критериев.

1. Композиция и пространство
Как должно быть: кадр имеет ясный визуальный якорь; текст, изображения и декоративные элементы связаны в одну композицию; негативное пространство выглядит намеренным; элементы не случайно прилипают к краям.
Как не должно быть: элементы выглядят разложенными автолейаутом; кадр кажется недособранным; пространство между объектами не работает на смысл; важные элементы слишком разнесены или слишком сжаты.

2. Визуальная иерархия
Как должно быть: зритель сразу понимает, что читать/смотреть первым, вторым и третьим; второстепенные элементы поддерживают главный тезис.
Как не должно быть: все элементы конкурируют; мелкие лейблы становятся шумом; главный смысл оказывается менее заметным, чем декоративные детали.

3. Типографика и читаемость
Как должно быть: размеры, переносы, межстрочие, контраст и акценты выглядят ручной системой; текст читается на мобильном экране за отведенное время.
Как не должно быть: случайные переносы, сиротливые слова, слишком мелкий вторичный текст, слишком много шрифтовых ролей, визуально неуверенные строки.

4. Моушн, входы и выходы сцен
Как должно быть: движение раскрывает смысл быстро и направляет взгляд; в начале, середине и конце сцены кадр остается понятным; переходы помогают ритму.
Как не должно быть: сцена долго выглядит как незавершенный шаблон; важный текст или объект появляется слишком поздно; motion скрывает смысл или создает промежуточные неудачные кадры.

5. Визуальный язык и арт-дирекшн
Как должно быть: палитра, материалы, рамки, тени, текстуры, декоративные приемы и переходы относятся к одному миру.
Как не должно быть: соседние сцены выглядят как разные шаблоны; декоративный прием кажется случайным; элементы не имеют общей физики или общей системы.

6. Коллажная/карточная физика, если она используется
Как должно быть: бумага, карточки, рамки, наклейки, тени, фактуры и перекрытия выглядят намеренно и правдоподобно для выбранного стиля.
Как не должно быть: материалы выглядят плоскими, дефолтными или компьютерными; тени/рамки/наклейки не подчиняются одной логике; декоративный слой дешевит кадр.

7. Связь текста, визуала и смысла
Как должно быть: визуальный объект или графический прием усиливает конкретную мысль сцены; доказательства, сравнения и выборы имеют достаточный визуальный вес.
Как не должно быть: визуалы выглядят как случайный фон; важные смысловые элементы слишком мелкие; графика не объясняет, а только украшает.

8. Разнообразие и темп
Как должно быть: сцены меняют плотность, масштаб, фокус и энергию без потери общего стиля; нет ощущения одной и той же раскладки много раз подряд.
Как не должно быть: однообразие, механическое повторение приемов, провисания, слишком слабые кульминационные моменты.

9. Финальная публикационная готовность
Как должно быть: ролик выглядит законченным, уверенным и осознанно смонтированным; финальный смысл или действие зрителя считывается ясно.
Как не должно быть: ощущение черновика, демо-шаблона, случайной сборки или недополированного proof-of-concept.

Верни строго JSON:
{
  "overall_verdict": "короткий жесткий вердикт по-русски",
  "verdict": "pass или fail",
  "blockers": [
    {
      "scene_or_time": "scene/timestamp/contact cell/global",
      "issue": "что не так",
      "evidence": "что именно видно",
      "why_it_matters": "почему это дешевит или ломает",
      "suggested_fix_direction": "направление правки без реализации"
    }
  ],
  "major": [],
  "minor": [],
  "pattern_level_problems": [],
  "three_highest_leverage_fixes": []
}

Не добавляй praise-section. Если сильных проблем мало, так и скажи, но не снижай строгость.
```

## Prompt B: Timeline Stills Audit

Use when Gemini receives stills sampled at early/mid/late points for every scene.

```text
Ты независимый жесткий визуальный критик для vertical reels.
Перед тобой contact sheets со сценами одного видео:
- early sheet: ранний момент каждой сцены;
- mid sheet: середина каждой сцены;
- late sheet: конец каждой сцены.

Порядок ячеек в каждом contact sheet: слева направо, сверху вниз, scene index 1..N.
Не оценивай качество исходных ассетов. Оцени финальную верстку, кадрирование, читаемость, композицию и timing-состояния сцены.

Цель: найти моменты, где сцена выглядит слабой не только в лучшем кадре, но и во входе/середине/выходе.

Проверь:

1. Early-state readiness
Как должно быть: уже в раннем моменте сцены зритель понимает визуальную задачу или получает интригующий, осмысленный старт.
Как не должно быть: early-state выглядит как пустой шаблон, незавершенная загрузка или случайный промежуточный кадр.

2. Mid-state clarity
Как должно быть: в середине сцены главный текст и главный визуальный объект читаются без борьбы.
Как не должно быть: середина перегружена, недозаполнена, не имеет фокуса, или важные элементы слишком мелкие.

3. Late-state completion
Как должно быть: к концу сцены композиция выглядит собранной, смысл завершен, nothing important is clipped or hidden.
Как не должно быть: финальное состояние выглядит неготовым, обрубленным, случайным, слишком похожим на соседние сцены или слабым для смыслового удара.

4. Temporal consistency
Как должно быть: вход, середина и конец ощущаются как одна намеренная анимационная дуга.
Как не должно быть: сцена проходит через некрасивые промежуточные состояния, которые зритель реально увидит на паузе или при скролле.

Верни по-русски строго JSON:
{
  "blockers": [
    {
      "scene": "scene NN / contact cell",
      "moment": "early/mid/late/all",
      "issue": "что не так",
      "evidence": "что видно в ячейке",
      "why_it_cheapens": "почему выглядит дешево/недособранно",
      "fix_direction": "как направить правку"
    }
  ],
  "major": [],
  "minor": [],
  "recurring_patterns": [],
  "three_highest_leverage_fixes": []
}

Не используй заранее заданные ожидания о том, какие сцены должны быть плохими. Судить только по contact sheets.
```

## Prompt C: Combined Audit Synthesis

Use after separate Gemini runs have produced a video audit and a stills/timeline audit.

```text
Ты design lead, который объединяет несколько независимых аудитов одного vertical short/reels видео.
Твоя задача — не усреднять и не смягчать, а отсортировать проблемы по приоритету.

Вход:
- video_audit_json: {video_audit_json}
- timeline_audit_json: {timeline_audit_json}

Правила:
- Не добавляй новых дефектов, если они не подтверждены хотя бы одним входным аудитом.
- Если два аудита говорят об одном паттерне разными словами, объедини их.
- Раздели: blocker / major / minor.
- Отдельно пометь consensus findings: проблемы, которые подтвердили оба аудита.
- Отдельно пометь single-source findings: проблемы, которые увидел только один аудит.
- Не превращай общие критерии в факты. Факт должен иметь evidence из входа.

Верни строго JSON:
{
  "consensus_findings": [],
  "blockers": [],
  "major": [],
  "minor": [],
  "single_source_findings": [],
  "top_5_fix_order": [
    {
      "priority": 1,
      "problem": "что чинить",
      "why_first": "почему это самое важное",
      "affected_scope": "global/scenes/timestamps",
      "expected_visual_gain": "что улучшится"
    }
  ],
  "notes_for_next_render_validation": []
}
```

## Prompt D: Prompt Leak Check

Use this prompt with a separate reviewer before using the audit prompts operationally.

```text
Ты проверяешь prompt pack для Gemini-аудита видео на leakage.

Нужно определить, подсказывает ли prompt заранее конкретные уже найденные дефекты конкретного видео.
Разрешено: общие критерии качества, нейтральные дизайн-антипаттерны, output schema.
Запрещено: конкретные scene numbers, timestamps, фразы из видео, названия видимых labels/assets, конкретные найденные дефекты в формулировке "это есть", слишком узнаваемые описания одного текущего кадра.

Проверь:
- нет ли scene-specific hints;
- нет ли названий конкретных слов/лейблов из текущего видео;
- нет ли утверждений о наличии конкретного дефекта;
- не слишком ли узкие примеры в "как не должно быть";
- может ли Gemini, не видя видео, угадать ожидаемые findings из prompt.

Верни:
{
  "leak_free": true,
  "risk_level": "low/medium/high",
  "leaks_or_risks": [
    {
      "quote": "короткий фрагмент prompt",
      "why_risky": "почему это может подсказать найденный дефект",
      "suggested_neutral_rewrite": "как переписать нейтрально"
    }
  ],
  "approved_after_rewrites": true
}
```
