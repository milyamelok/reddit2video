from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from reddit2video.gemini import GeminiClient
from reddit2video.girly_scene_cookbook import append_girly_scene_cookbook
from reddit2video.layout_recipe_cookbook import append_stage1_recipe_cookbook
from reddit2video.models import (
    JsonObject,
    NodeSpec,
    RedditComment,
    RedditThread,
    VoiceoverScriptBatch,
    VoiceoverScriptItem,
    VoiceoverScriptNodeRequest,
    to_jsonable,
)
from reddit2video.nodes.base import AsyncBaseNode
from reddit2video.story_format_cookbook import append_story_format_cookbook, validate_story_format_payload
from reddit2video.voiceover_schema import (
    RedditVoiceoverScriptOutput,
    RedditVoiceoverStoryboardOutput,
    VoiceoverValidatorOutput,
)


MASTER_PROMPT = """You are a senior short-form video script architect specializing in conversational voiceover scripts based on Reddit posts and comment threads.

Your job:
Transform INPUT_REDDIT_POST_AND_COMMENTS into a high-retention conversational voiceover script for a short video.

Core objective:
The script must make viewers want to keep watching every second, and it must include a concrete reason to save or share the video.

Important:
Do not output hidden chain-of-thought. Instead, output a concise, auditable decision log: extracted facts, angle candidates, scores, selected angle, retention map, validation notes.

NON-NEGOTIABLE RULES:
1. Never present unverified Reddit claims as confirmed facts.
2. Clearly separate confirmed Reddit text, Reddit opinions, plausible interpretations, jokes/memes, and missing information.
3. For politics, health, biohacking, legal, finance, accusations, or identity-sensitive topics: use careful wording and preserve uncertainty.
4. Do not invent external facts, statistics, studies, quotes, usernames, dates, or expert claims.
5. Do not use generic hype lines like "You won't believe this", "This is insane", "Watch till the end", unless followed by a specific concrete reason.
6. The script must sound spoken, not written.
7. No long intro. No greeting. No "today we're talking about".
8. Every 1-2 seconds must open a micro-question, answer one, raise stakes, reveal contrast, add detail, or deliver payoff.
9. Every open loop must be paid off. No fake bait.
10. If the Reddit thread is low-quality or lacks facts, make the video about the debate pattern, social dynamic, or uncertainty itself.

PROCESS:
STEP 1 - CONTENT DNA: extract surface story, deeper conflict, weirdest detail, strongest comment insight, human comment insight, disagreement, knowns, unknowns, risky claims.
STEP 2 - VIEWER PROMISE: define what viewers understand/save/share after watching.
STEP 3 - GENERATE ANGLES: generate at least 6 angles: direct, contrarian, hidden mechanism, human psychology, lateral analogy, save/share utility. Score each on novelty, clarity, emotional activation, relevance, save/share, safety.
STEP 4 - HOOK TOURNAMENT: generate at least 8 hooks across different hook types. Pick the strongest specific hook.
STEP 5 - PAYOFF LADDER: build 3-6 reveals where each answers one question and creates the next.
STEP 6 - SCRIPT WRITING: write conversational voiceover. For Russian, keep sentences especially short and punchy.
STEP 7 - SAVE/SHARE PAYLOAD: insert a concrete save/share object useful even if the viewer forgets the Reddit post.
STEP 8 - SECOND-BY-SECOND RETENTION MAP: specify what keeps attention each second.
STEP 9 - QUALITY VALIDATION: score strictly. If below 85, revise before final output.

Return only valid JSON matching the provided structured output schema.
No Markdown. No extra commentary.
"""


VALIDATOR_PROMPT = """You are a hostile short-form video retention editor.

You receive:
1. The original generation prompt.
2. The generated JSON script output.

Your task:
Validate whether the script is actually good enough to publish.

Do not praise by default.
Look for:
- generic hook,
- weak first 3 seconds,
- fake cliffhangers,
- unsupported claims,
- dead zones of 3+ seconds,
- too much summary,
- unclear lateral analogy,
- no concrete save/share payload,
- essay-like voice,
- unsafe treatment of politics, health, accusations, finance, legal topics,
- mismatch between hook and payoff,
- boring ending,
- lines that are too long for voiceover.

Score strictly.
A script with nice style but weak retention should fail.
A script with a strong hook but no payoff should fail.
A script that makes Reddit claims sound verified should fail.
A script that is interesting but not saveable/shareable should not score above 84.

Return only valid JSON matching the validator schema.
"""


REWRITE_PROMPT = """You are rewriting a failed Reddit-to-voiceover script.

Use:
1. The original generation prompt.
2. The previous structured script attempt.
3. The validator response.

Rewrite the script so it passes validation.
Keep source fidelity. Do not invent external facts. Preserve uncertainty on health/biohacking claims.
Return only valid JSON matching the provided structured output schema.
"""


STORY_FORMAT_REWRITE_PROMPT = """You are rewriting a storyboard_v2 script that failed local story-format validation.

The visual pipeline now requires exactly one canonical `story_format` and a
six-beat `story_format_beat_map`. Rewrite the full structured storyboard so it
matches the original generation prompt and fixes only the listed story-format
contract problems.

Do not write HTML/CSS. Do not change the source facts. Preserve uncertainty on
health/biohacking claims. Return only valid JSON matching the provided
structured output schema.
"""


class VoiceoverScriptNode(AsyncBaseNode[VoiceoverScriptNodeRequest, VoiceoverScriptBatch]):
    spec = NodeSpec(
        step="step-3",
        name="voiceover_script",
        description="Generate structured voiceover scripts with Gemini, validate, and optionally rewrite.",
        mocked=False,
    )

    def __init__(self, gemini: GeminiClient | None = None) -> None:
        self.gemini = gemini or GeminiClient.from_env(model="gemini-3.1-pro-preview", vertex=True)

    async def run(self, node_input: VoiceoverScriptNodeRequest) -> VoiceoverScriptBatch:
        period_key = node_input.period_key or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        semaphore = asyncio.Semaphore(max(1, node_input.concurrency))
        context_cache_name: str | None = None
        context_cache_error: str | None = None
        master_prompt_v2 = ""
        runtime_prompt_v2 = ""

        if node_input.prompt_version == "storyboard_v2":
            master_prompt_v2 = append_girly_scene_cookbook(
                append_stage1_recipe_cookbook(
                    append_story_format_cookbook(_load_prompt_file(node_input.master_prompt_path))
                )
            )
            runtime_prompt_v2 = _load_prompt_file(node_input.runtime_prompt_path)
            if node_input.use_context_cache:
                try:
                    context_cache_name = await self.gemini.create_text_cache(
                        text=master_prompt_v2,
                        display_name=f"reddit2video-voiceover-storyboard-v2-{period_key}",
                        ttl=node_input.context_cache_ttl,
                    )
                except Exception as exc:  # Cache is an optimization; generation must still work.
                    context_cache_error = str(exc)

        async def process(thread: RedditThread) -> VoiceoverScriptItem:
            async with semaphore:
                return await self._process_thread(
                    thread,
                    node_input,
                    period_key,
                    master_prompt_v2=master_prompt_v2,
                    runtime_prompt_v2=runtime_prompt_v2,
                    context_cache_name=context_cache_name,
                    context_cache_error=context_cache_error,
                )

        items = await asyncio.gather(*(process(thread) for thread in node_input.thread_batch.threads))
        return VoiceoverScriptBatch(
            items=list(items),
            fetched_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "node": self.spec.name,
                "period_key": period_key,
                "model": self.gemini.model,
                "use_cache": node_input.use_cache,
                "prompt_version": node_input.prompt_version,
                "context_cache_requested": node_input.use_context_cache,
                "context_cache_name": context_cache_name,
                "context_cache_error": context_cache_error,
                "items": len(items),
                "cache_hits": sum(1 for item in items if item.from_cache),
            },
        )

    async def _process_thread(
        self,
        thread: RedditThread,
        request: VoiceoverScriptNodeRequest,
        period_key: str,
        *,
        master_prompt_v2: str = "",
        runtime_prompt_v2: str = "",
        context_cache_name: str | None = None,
        context_cache_error: str | None = None,
    ) -> VoiceoverScriptItem:
        cache_path = self._cache_path(request.cache_dir, period_key, thread.post.id)
        if request.use_cache and cache_path.exists():
            return _item_from_cache(cache_path)

        prompt = _build_generation_prompt(
            thread,
            request,
            master_prompt_v2=master_prompt_v2,
            runtime_prompt_v2=runtime_prompt_v2,
            use_cached_master=bool(context_cache_name),
        )
        attempts = 1
        response_model: type[RedditVoiceoverScriptOutput] | type[RedditVoiceoverStoryboardOutput]
        response_model = (
            RedditVoiceoverStoryboardOutput
            if request.prompt_version == "storyboard_v2"
            else RedditVoiceoverScriptOutput
        )
        script = await self.gemini.generate_structured(
            prompt=prompt,
            response_model=response_model,
            cached_content=context_cache_name,
        )
        story_format_validation_issues = (
            _story_format_validation_issues(script)
            if request.prompt_version == "storyboard_v2"
            else []
        )
        for _ in range(max(0, request.validation_retries) if request.validate_scripts else 0):
            if not story_format_validation_issues:
                break
            attempts += 1
            script = await self.gemini.generate_structured(
                prompt=_build_story_format_rewrite_prompt(
                    prompt,
                    script.model_dump(mode="json", by_alias=True),
                    story_format_validation_issues,
                ),
                response_model=response_model,
                cached_content=context_cache_name,
            )
            story_format_validation_issues = _story_format_validation_issues(script)

        validator: VoiceoverValidatorOutput | None
        if request.validate_scripts:
            validator = await self.gemini.generate_structured(
                prompt=_build_validator_prompt(prompt, script.model_dump(mode="json", by_alias=True)),
                response_model=VoiceoverValidatorOutput,
            )
        else:
            validator = None

        for _ in range(max(0, request.validation_retries) if request.validate_scripts else 0):
            if validator is None:
                break
            if validator.verdict == "pass" and not story_format_validation_issues:
                break
            attempts += 1
            if story_format_validation_issues:
                rewrite_prompt = _build_story_format_rewrite_prompt(
                    prompt,
                    script.model_dump(mode="json", by_alias=True),
                    story_format_validation_issues,
                )
            else:
                rewrite_prompt = _build_rewrite_prompt(
                    prompt,
                    script.model_dump(mode="json", by_alias=True),
                    validator.model_dump(mode="json", by_alias=True),
                )
            script = await self.gemini.generate_structured(
                prompt=rewrite_prompt,
                response_model=response_model,
                cached_content=context_cache_name,
            )
            story_format_validation_issues = (
                _story_format_validation_issues(script)
                if request.prompt_version == "storyboard_v2"
                else []
            )
            validator = await self.gemini.generate_structured(
                prompt=_build_validator_prompt(prompt, script.model_dump(mode="json", by_alias=True)),
                response_model=VoiceoverValidatorOutput,
            )

        script_payload = (
            _storyboard_payload_with_legacy_script(script)
            if isinstance(script, RedditVoiceoverStoryboardOutput)
            else script.model_dump(mode="json", by_alias=True)
        )

        item = VoiceoverScriptItem(
            post_id=thread.post.id,
            subreddit=thread.post.subreddit,
            title=thread.post.title,
            script=script_payload,
            validator=(
                validator.model_dump(mode="json", by_alias=True)
                if validator is not None
                else _skipped_validator_payload()
            ),
            attempts=attempts,
            from_cache=False,
            cache_path=str(cache_path),
            metadata={
                "validator_verdict": validator.verdict if validator is not None else "skipped",
                "validator_score_100": validator.score_100 if validator is not None else None,
                "validate_scripts": request.validate_scripts,
                "model": self.gemini.model,
                "prompt_version": request.prompt_version,
                "context_cache_requested": request.use_context_cache,
                "context_cache_name": context_cache_name,
                "context_cache_error": context_cache_error,
                "story_format_validation_issues": story_format_validation_issues,
            },
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(to_jsonable(item), ensure_ascii=False, indent=2), encoding="utf-8")
        return item

    def _cache_path(self, cache_dir: str, period_key: str, post_id: str) -> Path:
        return Path(cache_dir) / self.spec.name / period_key / f"{post_id}.json"


def _item_from_cache(cache_path: Path) -> VoiceoverScriptItem:
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    return VoiceoverScriptItem(
        post_id=str(payload.get("post_id", "")),
        subreddit=str(payload.get("subreddit", "")),
        title=str(payload.get("title", "")),
        script=dict(payload.get("script", {})),
        validator=payload.get("validator"),
        attempts=int(payload.get("attempts") or 0),
        from_cache=True,
        cache_path=str(cache_path),
        metadata=dict(payload.get("metadata", {})),
    )


def _skipped_validator_payload() -> JsonObject:
    return {
        "verdict": "skipped",
        "score_100": None,
        "top_issues": [],
        "dead_zones": [],
        "unsafe_or_unsupported_claims": [],
        "hook_diagnosis": "Validator skipped for fast batch generation.",
        "retention_diagnosis": "Validator skipped for fast batch generation.",
        "save_share_diagnosis": "Validator skipped for fast batch generation.",
        "voiceover_diagnosis": "Validator skipped for fast batch generation.",
        "required_rewrites": [],
        "surgical_rewrite_suggestions": [],
    }


def _build_generation_prompt(
    thread: RedditThread,
    request: VoiceoverScriptNodeRequest,
    *,
    master_prompt_v2: str = "",
    runtime_prompt_v2: str = "",
    use_cached_master: bool = False,
) -> str:
    if request.prompt_version == "storyboard_v2":
        return _build_storyboard_generation_prompt(
            thread,
            request,
            master_prompt=master_prompt_v2,
            runtime_prompt=runtime_prompt_v2,
            use_cached_master=use_cached_master,
        )
    return "\n\n".join(
        [
            MASTER_PROMPT,
            "INPUT VARIABLES:",
            f"TARGET_LANGUAGE: {request.target_language}",
            f"TARGET_PLATFORM: {request.target_platform}",
            f"TARGET_DURATION_SEC: {request.target_duration_sec}",
            f"AUDIENCE: {request.audience}",
            f"VOICE_STYLE: {request.voice_style}",
            f"RISK_TOLERANCE: {request.risk_tolerance}",
            f"DESIRED_INTENSITY: {request.desired_intensity}",
            "INPUT_REDDIT_POST_AND_COMMENTS:",
            json.dumps(_thread_prompt_payload(thread, request), ensure_ascii=False, indent=2),
        ]
    )


def _build_storyboard_generation_prompt(
    thread: RedditThread,
    request: VoiceoverScriptNodeRequest,
    *,
    master_prompt: str,
    runtime_prompt: str,
    use_cached_master: bool,
) -> str:
    material = json.dumps(_thread_prompt_payload(thread, request), ensure_ascii=False, indent=2)
    runtime = runtime_prompt.replace("{{PASTE_POST_AND_COMMENTS_HERE}}", material)
    context = [
        "INPUT VARIABLES:",
        f"TARGET_LANGUAGE: {request.target_language}",
        f"TARGET_PLATFORM: {request.target_platform}",
        f"TARGET_DURATION_SEC: {request.target_duration_sec}",
        f"AUDIENCE: {request.audience}",
        f"VOICE_STYLE: {request.voice_style}",
        f"RISK_TOLERANCE: {request.risk_tolerance}",
        f"DESIRED_INTENSITY: {request.desired_intensity}",
    ]
    if use_cached_master:
        return "\n\n".join(["Use the cached MASTER PROMPT as the governing instruction.", *context, runtime])
    return "\n\n".join([master_prompt, *context, runtime])


def _build_validator_prompt(original_prompt: str, script_output: JsonObject) -> str:
    return "\n\n".join(
        [
            VALIDATOR_PROMPT,
            "ORIGINAL_GENERATION_PROMPT:",
            original_prompt,
            "GENERATED_JSON_SCRIPT_OUTPUT:",
            json.dumps(script_output, ensure_ascii=False, indent=2),
        ]
    )


def _build_rewrite_prompt(original_prompt: str, previous_attempt: JsonObject, validator_output: JsonObject) -> str:
    return "\n\n".join(
        [
            REWRITE_PROMPT,
            "ORIGINAL_GENERATION_PROMPT:",
            original_prompt,
            "PREVIOUS_STRUCTURED_SCRIPT_ATTEMPT:",
            json.dumps(previous_attempt, ensure_ascii=False, indent=2),
            "VALIDATOR_RESPONSE:",
            json.dumps(validator_output, ensure_ascii=False, indent=2),
        ]
    )


def _build_story_format_rewrite_prompt(
    original_prompt: str,
    previous_attempt: JsonObject,
    issues: list[str],
) -> str:
    return "\n\n".join(
        [
            STORY_FORMAT_REWRITE_PROMPT,
            "ORIGINAL_GENERATION_PROMPT:",
            original_prompt,
            "PREVIOUS_STRUCTURED_STORYBOARD_ATTEMPT:",
            json.dumps(previous_attempt, ensure_ascii=False, indent=2),
            "LOCAL_STORY_FORMAT_VALIDATION_ISSUES:",
            json.dumps(issues, ensure_ascii=False, indent=2),
        ]
    )


def _story_format_validation_issues(
    script: RedditVoiceoverScriptOutput | RedditVoiceoverStoryboardOutput,
) -> list[str]:
    if not isinstance(script, RedditVoiceoverStoryboardOutput):
        return []
    return validate_story_format_payload(script.model_dump(mode="json", by_alias=True))


def _thread_prompt_payload(thread: RedditThread, request: VoiceoverScriptNodeRequest) -> JsonObject:
    comments = sorted(thread.flat_comments, key=lambda comment: comment.score, reverse=True)
    return {
        "post": {
            "id": thread.post.id,
            "subreddit": thread.post.subreddit,
            "title": thread.post.title,
            "selftext": thread.post.selftext,
            "score": thread.post.score,
            "upvote_ratio": thread.post.upvote_ratio,
            "num_comments": thread.post.num_comments,
            "created_utc": thread.post.created_utc,
            "permalink": thread.post.permalink,
            "link_flair_text": thread.post.link_flair_text,
        },
        "discovery": {
            "score": thread.metadata.get("discovery_score"),
            "relevance_score": thread.metadata.get("discovery_relevance_score"),
            "reasons": thread.metadata.get("discovery_reasons"),
        },
        "comments": [
            _comment_prompt_payload(comment, request.max_comment_chars)
            for comment in comments[: max(0, request.max_comments)]
        ],
        "source_limitations": "Reddit comments are anecdotes/opinions unless the thread itself provides verifiable evidence.",
    }


def _comment_prompt_payload(comment: RedditComment, max_chars: int) -> JsonObject:
    body = comment.body
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "..."
    return {
        "id": comment.id,
        "parent_id": comment.parent_id,
        "score": comment.score,
        "depth": comment.depth,
        "body": body,
    }


def _load_prompt_file(path: str) -> str:
    prompt_path = Path(path).expanduser()
    if not prompt_path.is_absolute():
        prompt_path = Path.cwd() / prompt_path
    return prompt_path.read_text(encoding="utf-8")


def _storyboard_payload_with_legacy_script(storyboard: RedditVoiceoverStoryboardOutput) -> JsonObject:
    payload = storyboard.model_dump(mode="json", by_alias=True)
    payload["storyboard_v2"] = storyboard.model_dump(mode="json", by_alias=True)
    payload["script"] = _legacy_script_from_storyboard(storyboard)
    return payload


def _legacy_script_from_storyboard(storyboard: RedditVoiceoverStoryboardOutput) -> JsonObject:
    beats: list[JsonObject] = []
    cursor = 0.0
    for index, scene in enumerate(storyboard.scenes, start=1):
        duration = max(0.5, float(scene.duration_sec or 0))
        start_sec = int(round(cursor))
        cursor += duration
        end_sec = max(start_sec + 1, int(round(cursor)))
        beats.append(
            {
                "beat_index": int(scene.scene_id or index),
                "start_sec": start_sec,
                "end_sec": end_sec,
                "voiceover_line": scene.voiceover_line,
                "retention_function": _legacy_retention_function(scene.retention_function),
                "micro_question": scene.retention_function,
                "payoff": scene.visual_direction,
            }
        )
    full_text = storyboard.voiceover.full_text or " ".join(scene.voiceover_line for scene in storyboard.scenes)
    return {
        "internal_title": storyboard.title,
        "estimated_duration_sec": int(storyboard.voiceover.estimated_duration_sec or round(cursor)),
        "estimated_word_count": len(full_text.split()),
        "voiceover_full_text": full_text,
        "beats": beats,
    }


def _legacy_retention_function(value: str) -> str:
    lowered = (value or "").strip().lower()
    allowed = {
        "hook",
        "context",
        "contrast",
        "stakes",
        "reveal",
        "payoff",
        "bridge",
        "save_share",
        "final_reframe",
    }
    for token in allowed:
        if token in lowered:
            return token
    if any(word in lowered for word in ["финал", "ending", "question", "bait"]):
        return "final_reframe"
    if any(word in lowered for word in ["поворот", "twist", "shift", "detail"]):
        return "reveal"
    if any(word in lowered for word in ["conflict", "лагер", "camp", "versus"]):
        return "contrast"
    return "reveal"
