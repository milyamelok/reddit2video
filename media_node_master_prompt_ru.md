# Master Prompt: Media Search Node + Playwright Connectors + Gemini Visual Selector

Ты — senior TypeScript/Node.js engineer, automation architect и product-minded media retrieval engineer.

Нужно разработать ноду для пайплайна коротких видео, которая подбирает медиа-ассеты для сцен: картинки, GIF, короткие видео, мемы, reaction-визуалы, Pinterest moodboard-референсы и визуальные метафоры.

Главная цель ноды: не просто найти «релевантную картинку», а подобрать визуал, который усиливает сцену по досматриваемости, эмоции, мемности, сохранениям/пересылкам и комментам.

---

## 0. Product Context

У нас есть short-form video pipeline.

На вход media-node получает список сцен. Каждая сцена уже имеет:

- `scene_id`
- `start_sec`
- `end_sec`
- `duration_sec`
- `voiceover_fragment`
- `scene_tag`
- `attention_job`
- `screen_rows`
- `visual_density`
- `template_hint`
- `media_slots`

Пример `media_slot`:

```json
{
  "slot_id": "s05_m01",
  "kind": "gif",
  "role": "reaction",
  "meaning": "семья получила быстрый результат и как будто нажала skip",
  "stance": "unfair advantage / cheated progress / jealous but funny",
  "query_ru": "семья хвастается быстрый результат реакция",
  "query_en": "cheat code reaction gif unfair advantage skip the grind",
  "must_have": ["reaction", "unfair", "fast-forward feeling"],
  "avoid": ["medical misinformation", "graphic injections", "too literal stock photo"],
  "crop_hint": "9:16 vertical, central face/object must remain readable",
  "motion_hint": "quick zoom, slight shake, stamp appears at end"
}
```

Нода должна найти несколько кандидатов на каждый media slot, выбрать лучшие с помощью Gemini по screenshot + DOM candidates, и вернуть structured output для Remotion/asset resolver.

---

## 1. Important Philosophy

Не оптимизируемся на «буквальную релевантность».

Оптимизируемся на визуал, который делает сцену:

1. понятнее;
2. смешнее;
3. злее / спорнее;
4. эмоциональнее;
5. более пересылаемой;
6. более сохраняемой;
7. более мемной;
8. более watchable.

Если визуал просто «подходит по теме», но не добавляет stance — это слабый визуал.

### Working definition of meme

Мем — это не просто смешная картинка.

Мем = узнаваемая культурная грамматика, которая передает не только смысл, но и отношение к смыслу.

У мема есть:

- `form` — узнаваемый формат: reaction GIF, template, cursed collage, fake UI, screenshot, starter pack, wojak-like archetype, old internet fossil, etc.
- `content` — что буквально изображено;
- `stance` — отношение: ирония, раздражение, smug, cringe, тревога, сочувствие, «мы все таких знаем»;
- `social_use` — зачем зритель это перешлет: «это ты», «это я», «смотри как точно», «я не согласен», «это наш спор»;
- `mutation` — можно ли визуал превратить в формат / повторяющуюся метафору.

---

## 2. Connectors to Build

Разработай TypeScript/Node.js project.

Use:

- Node.js 20+
- TypeScript
- Playwright
- Zod or Pydantic-equivalent validation in TS if needed
- dotenv
- local file cache
- structured JSON outputs

Do NOT rely primarily on official search APIs.

Use Playwright browser automation.

### Required connectors

1. `GiphyConnector`
2. `GoogleImagesConnector`
3. `PinterestConnector`
4. Optional but useful: `RedditMemeScoutConnector`

The user specifically wants:

- Giphy through Playwright
- Google Images through Playwright
- Pinterest through Playwright
- Dolphin Anty browser profile startup before running browser automation
- For Pinterest, check local desktop for an existing folder named approximately `pinterest parser` and reuse its logic if available

---

## 3. Dolphin Anty Requirement

Before browser automation, attempt to start via Dolphin Anty.

Implement:

- `DolphinClient`
- create a new profile if credentials/config allow
- start profile with automation enabled
- connect Playwright to the browser over CDP/WebSocket if Dolphin returns automation endpoint
- graceful fallback to local Playwright chromium if Dolphin is not configured or fails

Environment variables:

```bash
DOLPHIN_API_TOKEN=
DOLPHIN_LOCAL_API_URL=http://localhost:3001
DOLPHIN_PROFILE_NAME=media-node-profile
USE_DOLPHIN=true
```

Important:

- Do not crash if Dolphin is absent.
- Log clear diagnostics.
- Never expose tokens in logs.
- Keep profile creation/start logic isolated.

Pseudo-interface:

```ts
export interface BrowserSession {
  browser: Browser;
  context: BrowserContext;
  page: Page;
  source: 'dolphin' | 'local-playwright';
  profileId?: string;
}

export class BrowserFactory {
  async createSession(): Promise<BrowserSession>;
  async closeSession(session: BrowserSession): Promise<void>;
}
```

---

## 4. Core Search Flow

For each `media_slot`:

1. Generate search queries from slot metadata:
   - literal query
   - emotional/reaction query
   - meme/template query
   - visual metaphor query
   - evergreen/fresh query

2. Search sources:
   - Giphy for GIF/reaction/motion
   - Google Images for literal/metaphor/reference image
   - Pinterest for moodboard/archetype/aesthetic/collage refs
   - Reddit Meme Scout for meme names and cultural labels, not necessarily final assets

3. Open result page in Playwright.

4. Extract visible candidates from DOM.

5. Overlay visible candidate IDs on the page:
   - A1, A2, A3… or 1,2,3…
   - Use bright labels directly above/inside candidate boxes.
   - Include only candidates with visible bounding boxes.

6. Take screenshot.

7. Send screenshot + candidate metadata + scene/media_slot brief to Gemini.

8. Gemini chooses ranked candidates and explains briefly.

9. Resolve candidate URLs if possible:
   - original page URL
   - image preview URL
   - media URL if available
   - source name
   - selected reason
   - crop/motion hints

10. Return structured output.

---

## 5. DOM Candidate Extraction

Implement candidate extractor.

For each page, extract candidates with:

```ts
interface DomCandidate {
  id: string;
  source: 'giphy' | 'google_images' | 'pinterest' | 'reddit';
  title?: string;
  alt?: string;
  href?: string;
  imageUrl?: string;
  videoUrl?: string;
  thumbnailUrl?: string;
  width: number;
  height: number;
  x: number;
  y: number;
  visible: boolean;
  domText?: string;
  rankOnPage: number;
}
```

Filtering:

- visible only
- bounding box must be meaningful
- ignore tiny icons, logos, avatars unless search mode asks for icons
- prioritize candidates above fold but allow scrolling if needed
- avoid duplicates by normalized URL/hash

Overlay:

- Inject CSS labels with candidate ID.
- Use high-contrast label.
- Make sure labels are readable in screenshot.
- Return screenshot path and candidate list.

---

## 6. Gemini Visual Selector Prompt

Create a prompt file: `prompts/gemini_visual_selector.md`.

Use this prompt:

```text
You are a visual creative director for short-form vertical videos.

You receive:
1. A scene brief.
2. A media slot brief.
3. A screenshot of a search results page with visible candidates labeled by IDs.
4. Metadata for each candidate ID.

Your job:
Choose the best media candidates for this scene.

Do NOT choose the most literally relevant image by default.
Choose the candidate that best improves retention, emotion, meme value, shareability, and visual clarity.

SCENE BRIEF:
- scene_id: {{scene_id}}
- voiceover: {{voiceover_fragment}}
- attention_job: {{attention_job}}
- scene_tag: {{scene_tag}}
- visual_density: {{visual_density}}
- template_hint: {{template_hint}}
- duration_sec: {{duration_sec}}

MEDIA SLOT:
- slot_id: {{slot_id}}
- kind: {{kind}}
- role: {{role}}
- meaning: {{meaning}}
- stance: {{stance}}
- must_have: {{must_have}}
- avoid: {{avoid}}
- crop_hint: {{crop_hint}}
- motion_hint: {{motion_hint}}

CANDIDATE METADATA:
{{candidate_metadata_json}}

SELECTION PRINCIPLES:

1. Scene fit beats literal relevance.
The visual must serve the scene's attention job.

2. Stance matters.
Prefer visuals that clearly express an attitude:
- smug
- unfair
- panic
- jealousy
- cringe
- fake calm
- suspicion
- victory
- failure
- social pressure
- absurdity

3. Phone readability matters.
The visual should be understandable on a vertical phone screen in 0.5–1.0 seconds.

4. Motion matters.
For GIF/video, prefer candidates with a clear loop, strong facial reaction, or obvious action.

5. Cropability matters.
Prefer candidates that can survive 9:16 crop or can be placed inside a collage card.

6. Cultural fluency matters.
Reject visuals that feel accidentally outdated, unless the scene explicitly wants old-internet/post-ironic fossil energy.

7. Avoid bland stock imagery.
If a candidate only illustrates the noun but does not add emotion or attitude, rank it low.

8. Avoid platform-risky visuals.
Reject candidates with gore, hateful symbols, sexually explicit content, minors in sensitive contexts, graphic medical scenes, or misleading medical authority vibes.

9. For save/share artifact scenes:
Prefer clean, legible, low-chaos images or no external image at all.
The scene may work better as text/diagram/fake UI.

10. For comment-bait scenes:
Prefer contrast, split-screen, debate framing, or visually polarized choices.

SCORING:
Score each relevant candidate 0–5 on:
- readability
- scene_relevance
- stance_clarity
- emotional_charge
- meme_or_cultural_value
- cropability
- motion_potential
- platform_safety

Return only valid JSON:

{
  "slot_id": "",
  "verdict": "select" | "no_good_candidate",
  "selected": [
    {
      "candidate_id": "A1",
      "rank": 1,
      "use_case": "primary" | "backup" | "collage_element" | "reference_only",
      "why_selected": "",
      "scores": {
        "readability": 0,
        "scene_relevance": 0,
        "stance_clarity": 0,
        "emotional_charge": 0,
        "meme_or_cultural_value": 0,
        "cropability": 0,
        "motion_potential": 0,
        "platform_safety": 0
      },
      "crop_instruction": "",
      "animation_instruction": "",
      "risk_note": ""
    }
  ],
  "rejected_reasons": [
    {
      "candidate_id": "A2",
      "reason": ""
    }
  ],
  "better_search_queries": [""],
  "notes_for_editor": ""
}
```

---

## 7. Connector Details

### GiphyConnector

Purpose:

- reaction GIFs
- emotion loops
- meme motion
- expressive faces
- dramatic/absurd reactions

Search modes:

- `reaction`
- `meme_template`
- `emotion`
- `action`
- `absurd`

Implementation:

- Navigate to Giphy search page with encoded query.
- Wait for results.
- Scroll modestly.
- Extract visible GIF cards.
- Capture GIF/video preview URLs if available.
- Overlay IDs.
- Screenshot.
- Send to Gemini.

Good Giphy queries:

- `cheat code reaction gif`
- `unfair advantage reaction gif`
- `trying not to cry reaction`
- `fake smile reaction gif`
- `panic reaction gif`
- `smug reaction gif`
- `skip button meme gif`

Avoid:

- hyper-specific literal medical terms unless needed
- random celebrity reaction if stance does not match
- low-resolution unreadable loops

### GoogleImagesConnector

Purpose:

- literal objects
- visual metaphors
- reference images
- diagrams
- objects for collages
- before/after visual contrast

Search modes:

- `literal`
- `visual_metaphor`
- `object`
- `diagram_reference`
- `editorial_photo`
- `fake_ui_reference`

Implementation:

- Navigate to Google Images.
- Search query.
- Extract image cards and links.
- Avoid relying on raw selectors too rigidly; write robust heuristics.
- Overlay IDs.
- Screenshot.
- Gemini selects.

Good Google Images queries:

- `fast forward button close up`
- `rental contract keys metaphor`
- `construction foundation concrete`
- `bathroom scale close up`
- `family group chat phone screenshot`
- `warning label medication`

### PinterestConnector

Purpose:

- moodboards
- archetypes
- aesthetics
- collage references
- character vibes
- visual texture

Search modes:

- `moodboard`
- `archetype`
- `aesthetic`
- `collage_reference`
- `visual_style_reference`

Important:

Before implementing from scratch, inspect desktop/local project folders for something like:

- `pinterest parser`
- `Pinterest Parser`
- `pinterest_parser`
- `pinterest-scraper`

If it exists, review the logic and reuse patterns.

Implementation:

- Pinterest often requires login/cookies/profile. Prefer Dolphin profile.
- Use modest scrolling.
- Extract pin cards.
- Capture title/description if visible.
- Overlay IDs.
- Screenshot.
- Gemini selects.

Good Pinterest queries:

- `wellness aesthetic collage supplements`
- `weight loss journey moodboard`
- `discipline fitness aesthetic dark`
- `biohacker desk supplements aesthetic`
- `family group chat aesthetic`
- `medical warning label design`

### RedditMemeScoutConnector optional

Purpose:

Do not use Reddit mainly to download final assets.
Use Reddit to discover:

- meme/template names
- reaction labels
- cultural context
- whether something feels current, evergreen, dead, or post-ironic
- search terms for Giphy/Google/Pinterest

Search targets:

- `r/MemeTemplatesOfficial`
- `r/ReactionMemes`
- `r/gifMemes`
- niche meme subs depending on topic

Methods:

- Reddit search page via Playwright
- Search posts
- Search comments if UI supports it
- Extract title, post link, visible comments, template names, top phrases

Return:

```ts
interface MemeScoutResult {
  query: string;
  candidateTemplateNames: string[];
  reactionLabels: string[];
  culturalStatus: 'current' | 'evergreen' | 'old_but_post_ironic' | 'dead_cringe' | 'unknown';
  nextSearchQueries: string[];
  notes: string[];
}
```

---

## 8. Media Selection Framework

For each media candidate, reason through F.C.S.U.M.

### F — Form

What is the format?

- reaction GIF
- meme template
- literal image
- fake UI
- screenshot aesthetic
- Pinterest moodboard
- cursed collage
- diagram
- visual metaphor
- object cutout
- old internet fossil

Does the form read instantly?

### C — Content

What is literally shown?

Does it connect to the scene nouns?

### S — Stance

What attitude does it add?

Examples:

- jealousy
- smugness
- panic
- fake calm
- moral judgment
- unfairness
- cheating
- discipline
- shame
- absurdity
- post-irony

### U — Use

Why would someone send/save this?

Examples:

- “это ты”
- “это я”
- “смотри как точно”
- “это наш спор”
- “я не согласен”
- “это аргумент”
- “это красный флаг”

### M — Mutation

Can this become a reusable visual motif?

Examples:

- `фундамент vs аренда`
- `нажал skip`
- `медовый месяц добавок`
- `читерство или лайфхак`
- `база vs верхушка пирамиды`

---

## 9. Output Types

Final output per media slot:

```ts
interface SelectedMediaCandidate {
  scene_id: number;
  slot_id: string;
  source: 'giphy' | 'google_images' | 'pinterest' | 'reddit_scout';
  candidate_id: string;
  rank: number;
  use_case: 'primary' | 'backup' | 'collage_element' | 'reference_only';
  title?: string;
  pageUrl?: string;
  thumbnailUrl?: string;
  mediaUrl?: string;
  imageUrl?: string;
  videoUrl?: string;
  localPath?: string;
  width?: number;
  height?: number;
  whySelected: string;
  scores: {
    readability: number;
    sceneRelevance: number;
    stanceClarity: number;
    emotionalCharge: number;
    memeOrCulturalValue: number;
    cropability: number;
    motionPotential: number;
    platformSafety: number;
  };
  cropInstruction: string;
  animationInstruction: string;
  riskNote?: string;
}
```

Overall output:

```ts
interface MediaNodeOutput {
  job_id: string;
  created_at: string;
  scenes: Array<{
    scene_id: number;
    selected_media: SelectedMediaCandidate[];
    no_good_candidate_slots: Array<{
      slot_id: string;
      reason: string;
      better_queries: string[];
    }>;
  }>;
  diagnostics: {
    browser_source: 'dolphin' | 'local-playwright';
    searches_run: number;
    screenshots_taken: number;
    gemini_calls: number;
    warnings: string[];
  };
}
```

---

## 10. Project Structure

Create:

```text
media-node/
  package.json
  tsconfig.json
  .env.example
  README.md
  prompts/
    gemini_visual_selector.md
    query_generator.md
  src/
    index.ts
    types.ts
    config.ts
    browser/
      browserFactory.ts
      dolphinClient.ts
      localPlaywright.ts
    connectors/
      baseConnector.ts
      giphyConnector.ts
      googleImagesConnector.ts
      pinterestConnector.ts
      redditMemeScoutConnector.ts
    dom/
      extractCandidates.ts
      overlayCandidates.ts
      screenshot.ts
    gemini/
      geminiClient.ts
      visualSelector.ts
    scoring/
      mediaGuidelines.ts
      fallbackRanker.ts
    cache/
      fileCache.ts
    utils/
      logger.ts
      safeFilename.ts
      rateLimit.ts
    examples/
      runExample.ts
  data/
    screenshots/.gitkeep
    downloads/.gitkeep
    cache/.gitkeep
```

---

## 11. CLI

Implement CLI:

```bash
npm run media:search -- --input ./examples/scenes.json --output ./out/media_plan.json
```

Optional flags:

```bash
--sources giphy,google,pinterest,reddit
--max-candidates 24
--use-dolphin true
--download false
--screenshot true
--gemini true
--dry-run false
```

---

## 12. Safety / Robustness

Important:

- Use rate limits.
- Use human-like modest scrolling, but do not over-engineer stealth.
- Do not mass scrape.
- Do not bypass paywalls or private content.
- Respect robots/terms as much as possible for a prototype.
- Cache screenshots and candidate metadata.
- If a source fails, continue with other sources.
- If Gemini fails, use fallback scoring based on metadata and source.
- If no good candidate, return `no_good_candidate` with better queries.

---

## 13. Quality Criteria

The implementation is good if:

1. It can run end-to-end on example scene slots.
2. It opens browser through Dolphin when available.
3. It falls back locally when Dolphin is unavailable.
4. It can search Giphy, Google Images, Pinterest.
5. It overlays IDs on DOM candidates.
6. It saves screenshots.
7. It sends screenshot + candidate metadata to Gemini.
8. It returns structured media selections.
9. It does not confuse literal relevance with visual strength.
10. It includes docs and examples.

---

## 14. Example Scene Slot

Use this for testing:

```json
{
  "scene_id": 5,
  "voiceover_fragment": "А потом её сестра и вся семья просто... сели на препараты.",
  "attention_job": "Show unfair speed advantage and emotional escalation.",
  "scene_tag": "escalation",
  "visual_density": "medium",
  "template_hint": "fake_ui",
  "duration_sec": 2.8,
  "media_slots": [
    {
      "slot_id": "s05_m01",
      "kind": "gif",
      "role": "reaction",
      "meaning": "семья получила быстрый результат и как будто нажала skip",
      "stance": "unfair advantage / cheated progress / jealous but funny",
      "query_ru": "семья хвастается быстрый результат реакция",
      "query_en": "cheat code reaction gif unfair advantage skip the grind",
      "must_have": ["reaction", "unfair advantage", "fast-forward feeling"],
      "avoid": ["graphic injections", "medical misinformation", "boring stock photo"],
      "crop_hint": "central face/object readable in 9:16",
      "motion_hint": "quick zoom, small shake, SKIP stamp appears at end"
    }
  ]
}
```

---

## 15. Final Instruction

Build the project as a real working scaffold, not just pseudocode.

Where exact selectors are fragile, use robust heuristics and clearly mark TODOs.

Prioritize:

1. clean architecture;
2. working Playwright flows;
3. screenshot + DOM candidate IDs;
4. Gemini selector integration;
5. structured output;
6. easy future extension.
