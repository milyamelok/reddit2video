# reddit2video

Node-based pipeline sketch for turning Reddit threads into Remotion videos.

## Nodes

- `step-0`: `RedditDiscoveryNode` discovers interesting recent Reddit posts and retrieves comments through Reddit OAuth.
- `step-0`: `RedditThreadNode` retrieves one exact post and its comments through Reddit OAuth.
- `step-2`: `PrepareContextBundleNode` mock for thread + design-kit context.
- `step-3`: `VoiceoverScriptNode` generates structured Gemini voiceover scripts, validates, and rewrites once by default.
- `step-3`: `GeminiScriptNode` mock for script generation.
- `step-4`: `ScenePipelineNode` generates ElevenLabs MP3 + timestamps, semantic fragments, scene plan, and media slots.
- `step-4`: `ElevenLabsVoiceNode` mock for voiceover generation.
- `step-5`: `HtmlLayoutNode` generates static-girly HTML boards with reference screenshots, Playwright QA, and one repair pass by default.
- `step-5`: `HtmlGenerationNode` mock for Jinja2-template vs Gemini-full-HTML experiments.
- `step-6`: `ImageParseNode` mock for Giphy / Google Images scraping.
- `step-7a`: `RenderBundleNode` prepares gapless visual scene timings, 1080x1920 scene PNGs, audio paths, and Remotion data.
- `step-7a`: `RemotionTransferNode` mock for HTML-to-TSX conversion.
- `step-7b`: Remotion TSX app renders MP4 videos with scene reveal animation and voiceover audio.
- `step-7b`: `RemotionRenderNode` mock for Remotion rendering.

## Reddit credentials

For an external script, use Reddit Data API OAuth credentials:

```bash
cp .env.example .env
# fill REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
```

The current implementation uses application-only OAuth with the
`client_credentials` grant, so it does not need your Reddit username/password.

## Fetch one thread

```bash
PYTHONPATH=src python -m reddit2video.cli fetch-reddit \
  --url "https://www.reddit.com/r/AskReddit/comments/POST_ID/title/" \
  --out outputs/thread.json
```

## Smoke test 20 different posts

```bash
PYTHONPATH=src python scripts/smoke_reddit_20.py \
  --subreddit AskReddit \
  --runs 20 \
  --out outputs/reddit-smoke
```

## Collect 20 wellness/fitness threads from the last 24 hours

```bash
PYTHONPATH=src python -m reddit2video.cli collect-reddit \
  --posts 20 \
  --hours 24 \
  --out outputs/reddit-wellness-24h.json
```

## Generate voiceover scripts with Gemini

```bash
PYTHONPATH=src python -m reddit2video.cli generate-voiceover \
  --input outputs/reddit-wellness-24h.json \
  --out outputs/voiceover-scripts.json
```

The node cache is per item and per daily period. If 5 of 20 posts already have
cached `voiceover_script` output, only the remaining 15 are generated.

## Generate audio + scene/media-slot plans

```bash
PYTHONPATH=src python -m reddit2video.cli generate-scenes \
  --input outputs/voiceover-scripts.json \
  --out outputs/scene-pipeline.json
```

This writes ElevenLabs MP3 files under `outputs/audio/<date>/`, maps semantic
fragments to character-level timings, and produces `ScenePlanOutput` media
slots only. Asset downloading is intentionally left for a later resolver node.

## Generate HTML layouts with visual reference + repair

```bash
PYTHONPATH=src python -m reddit2video.cli generate-html-layouts \
  --input outputs/scene-pipeline.json \
  --out outputs/html-layouts.json \
  --period-key 2026-05-13 \
  --repair-retries 1
```

The node sends the static-girly HTML style library plus reference screenshots to
Gemini, writes one HTML storyboard per post, runs Playwright layout QA, then uses
a screenshot-based Gemini repair gate. If the gate says the detected issue is a
false positive, the HTML is left unchanged; otherwise the problem scenes go back
to Gemini for a surgical repair pass.

## Prepare Remotion render bundle

```bash
PYTHONPATH=src python -m reddit2video.cli prepare-render-bundle \
  --scene-input outputs/scene-pipeline.json \
  --html-input outputs/html-layouts.json \
  --word-timing-input outputs/html-word-timing-experiment.json \
  --out outputs/render-bundle.json \
  --period-key 2026-05-13
```

Visual scenes are gapless: each scene is extended until the next scene starts,
so the next visual start equals the previous visual end. The node screenshots
every final HTML scene frame into `remotion/public/render-assets/<period>/`,
copies MP3 files into `remotion/public/audio/<period>/`, and writes
`remotion/src/render-bundle.generated.json`.

## Render videos with Remotion

```bash
cd remotion
source ~/.nvm/nvm.sh
npm install
REMOTION_RENDER_CONCURRENCY=2 npm run render:all
```

The Remotion app creates one composition per post, uses the generated scene PNGs
as TSX-rendered scenes, fades each scene in over its background at scene start,
and places the ElevenLabs voiceover on the audio track. MP4 files are written to
`outputs/videos/`.

## Docker Compose

```bash
docker compose up -d --build
docker compose exec app python -m reddit2video.cli collect-reddit
docker compose exec app python -m reddit2video.cli generate-voiceover
docker compose exec app python -m reddit2video.cli generate-scenes
docker compose exec app python -m reddit2video.cli generate-html-layouts
```

Kafka is started next to the app for local compatibility. The recommended
topic layout is one output topic per node plus a DLQ topic, not one topic per
single post.
