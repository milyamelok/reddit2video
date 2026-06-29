from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from reddit2video.gemini import GeminiClient
from reddit2video.models import JsonObject, RedditComment, RedditThread, RedditThreadBatch, to_jsonable


DEFAULT_SOURCE_QUALITY_MODEL = "gemini-3-flash-preview"
DEFAULT_SOURCE_QUALITY_FALLBACK_MODELS: list[str] = []
DEFAULT_SOURCE_QUALITY_MIN_SCORE = 70

BOT_AUTHORS = {"automoderator", "moderator", "mod"}
REMOVED_BODIES = {"[removed]", "[deleted]"}
GENERIC_COMMENT_RE = re.compile(
    r"\b("
    r"congrats?|congratulations|great job|good job|keep it up|awesome|amazing|"
    r"holy|hell yeah|fuck yeah|bravo|crushing it|lookin|looking amazing|"
    r"proud of you|way to go|king|queen|nice work|outstanding"
    r")\b",
    re.IGNORECASE,
)


class SourceQualityDecision(BaseModel):
    post_id: str
    verdict: Literal["pass", "safe_mode", "reject"]
    score_100: int = Field(ge=0, le=100)
    source_depth: Literal["thin", "usable", "rich"]
    story_risk: Literal["low", "medium", "high"]
    safe_story_mode: Literal[
        "normal_story",
        "thin_source_summary",
        "debate_pattern",
        "skip",
    ]
    usable_facts: list[str] = Field(default_factory=list)
    usable_conflicts: list[str] = Field(default_factory=list)
    comment_signal_summary: str = ""
    rejection_reason_codes: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    rationale: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class SourceQualityGateItem(BaseModel):
    post_id: str
    subreddit: str
    title: str
    accepted: bool
    decision: SourceQualityDecision
    local_signals: JsonObject
    model: str
    requested_model: str
    fallback_models: list[str] = Field(default_factory=list)
    from_cache: bool = False
    cache_path: str = ""
    gemini_attempts: int = 0
    errors: list[str] = Field(default_factory=list)


class SourceQualityGateBatch(BaseModel):
    items: list[SourceQualityGateItem]
    accepted_post_ids: list[str]
    rejected_post_ids: list[str]
    fetched_at: str
    metadata: JsonObject = Field(default_factory=dict)


async def evaluate_source_quality_batch(
    thread_batch: RedditThreadBatch,
    *,
    gemini: GeminiClient | None = None,
    model: str = DEFAULT_SOURCE_QUALITY_MODEL,
    fallback_models: list[str] | None = None,
    min_score: int = DEFAULT_SOURCE_QUALITY_MIN_SCORE,
    accept_safe_mode: bool = False,
    cache_dir: str | Path = "outputs/cache",
    period_key: str | None = None,
    concurrency: int = 2,
    force: bool = False,
) -> SourceQualityGateBatch:
    models = [model, *(fallback_models if fallback_models is not None else DEFAULT_SOURCE_QUALITY_FALLBACK_MODELS)]
    models = _dedupe_nonempty(models)
    client = gemini or GeminiClient.from_env(model=models[0], vertex=True)
    should_close = gemini is None
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def process(thread: RedditThread) -> SourceQualityGateItem:
        async with semaphore:
            return await evaluate_thread_source_quality(
                thread,
                gemini=client,
                models=models,
                min_score=min_score,
                accept_safe_mode=accept_safe_mode,
                cache_dir=cache_dir,
                period_key=period_key,
                force=force,
            )

    try:
        items = list(await asyncio.gather(*(process(thread) for thread in thread_batch.threads)))
    finally:
        if should_close:
            await client.aclose()

    accepted_post_ids = [item.post_id for item in items if item.accepted]
    rejected_post_ids = [item.post_id for item in items if not item.accepted]
    return SourceQualityGateBatch(
        items=items,
        accepted_post_ids=accepted_post_ids,
        rejected_post_ids=rejected_post_ids,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        metadata={
            "node": "source_quality_gate",
            "model": models[0],
            "fallback_models": models[1:],
            "min_score": int(min_score),
            "accept_safe_mode": bool(accept_safe_mode),
            "items": len(items),
            "accepted": len(accepted_post_ids),
            "rejected": len(rejected_post_ids),
            "cache_hits": sum(1 for item in items if item.from_cache),
            "gemini_attempts": sum(item.gemini_attempts for item in items),
            "gemini_calls": sum(1 for item in items if item.gemini_attempts > 0 and not item.from_cache),
        },
    )


async def evaluate_thread_source_quality(
    thread: RedditThread,
    *,
    gemini: GeminiClient,
    models: list[str],
    min_score: int = DEFAULT_SOURCE_QUALITY_MIN_SCORE,
    accept_safe_mode: bool = False,
    cache_dir: str | Path = "outputs/cache",
    period_key: str | None = None,
    force: bool = False,
) -> SourceQualityGateItem:
    models = _dedupe_nonempty(models) or [DEFAULT_SOURCE_QUALITY_MODEL]
    cache_path = source_quality_cache_path(cache_dir, models[0], thread.post.id, period_key=period_key)
    local_signals = source_quality_local_signals(thread)
    if cache_path.exists() and not force:
        cached = SourceQualityGateItem.model_validate_json(cache_path.read_text(encoding="utf-8"))
        return _with_acceptance(
            cached.model_copy(
                update={
                    "accepted": False,
                    "local_signals": local_signals,
                    "from_cache": True,
                    "cache_path": str(cache_path),
                    "requested_model": models[0],
                    "fallback_models": models[1:],
                    "gemini_attempts": 0,
                }
            ),
            min_score=min_score,
            accept_safe_mode=accept_safe_mode,
        )

    prompt = build_source_quality_prompt(thread, local_signals=local_signals)
    errors: list[str] = []
    attempts = 0
    for model in models:
        attempts += 1
        try:
            decision = await gemini.generate_structured(
                prompt=prompt,
                response_model=SourceQualityDecision,
                model=model,
            )
            item = SourceQualityGateItem(
                post_id=thread.post.id,
                subreddit=thread.post.subreddit,
                title=thread.post.title,
                accepted=False,
                decision=_normalize_decision(decision, thread.post.id),
                local_signals=local_signals,
                model=model,
                requested_model=models[0],
                fallback_models=models[1:],
                from_cache=False,
                cache_path=str(cache_path),
                gemini_attempts=attempts,
                errors=errors,
            )
            item = _with_acceptance(item, min_score=min_score, accept_safe_mode=accept_safe_mode)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(item.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
            return item
        except Exception as exc:  # Fallback models are expected to catch preview churn.
            errors.append(f"{model}: {exc}")

    decision = deterministic_source_quality_decision(thread, local_signals=local_signals, errors=errors)
    item = SourceQualityGateItem(
        post_id=thread.post.id,
        subreddit=thread.post.subreddit,
        title=thread.post.title,
        accepted=False,
        decision=decision,
        local_signals=local_signals,
        model="deterministic_fallback",
        requested_model=models[0],
        fallback_models=models[1:],
        from_cache=False,
        cache_path=str(cache_path),
        gemini_attempts=attempts,
        errors=errors,
    )
    item = _with_acceptance(item, min_score=min_score, accept_safe_mode=accept_safe_mode)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(item.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return item


def filter_thread_batch_by_source_quality(
    thread_batch: RedditThreadBatch,
    gate_batch: SourceQualityGateBatch,
) -> RedditThreadBatch:
    accepted = set(gate_batch.accepted_post_ids)
    return replace(
        thread_batch,
        threads=[thread for thread in thread_batch.threads if thread.post.id in accepted],
        metadata={
            **thread_batch.metadata,
            "source_quality_gate": {
                "accepted_post_ids": gate_batch.accepted_post_ids,
                "rejected_post_ids": gate_batch.rejected_post_ids,
                "metadata": gate_batch.metadata,
            },
        },
    )


def build_source_quality_prompt(thread: RedditThread, *, local_signals: JsonObject) -> str:
    payload = source_quality_prompt_payload(thread)
    return "\n\n".join(
        [
            "You are a strict source-sufficiency gate before a Reddit-to-short-video script pipeline.",
            "Your job is NOT to make the post interesting. Your job is to decide whether the source material can support a 45-60 second short-form story without inventing facts, motives, mechanisms, or dramatic stakes.",
            "Reject thin sources aggressively. A post should be rejected when the body is very short, comments are mostly congratulations / dosage questions / bot messages / generic praise, or a real story would require causal fantasy.",
            "Pass only when the source contains enough concrete material: a specific situation, tension, mechanism, disagreement, useful details, or comments that add real evidence or contrasting viewpoints.",
            "Use safe_mode only when the post is not rich enough for a normal story but can still support a modest source-faithful video about uncertainty, debate pattern, or a simple documented observation. Do not use safe_mode for pure before-after flexes with generic comments.",
            "Reason only from the provided Reddit text. Do not use external facts. Do not reward popularity alone.",
            "Return JSON only matching the schema.",
            "REJECTION CODES you may use:",
            json.dumps(
                [
                    "thin_post_body",
                    "congrats_only_comments",
                    "no_specific_conflict",
                    "no_mechanism_or_details",
                    "dosage_or_stack_without_story",
                    "would_require_invention",
                    "mostly_bot_removed_or_generic",
                    "unsafe_health_claim_without_context",
                ],
                ensure_ascii=False,
            ),
            "LOCAL_SIGNALS:",
            json.dumps(local_signals, ensure_ascii=False, indent=2),
            "REDDIT_THREAD:",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


def source_quality_prompt_payload(thread: RedditThread, *, max_comments: int = 45, max_comment_chars: int = 900) -> JsonObject:
    comments = sorted(thread.flat_comments, key=lambda comment: comment.score, reverse=True)
    return {
        "post": {
            "id": thread.post.id,
            "subreddit": thread.post.subreddit,
            "title": thread.post.title,
            "selftext": _truncate(thread.post.selftext, 2500),
            "score": thread.post.score,
            "num_comments": thread.post.num_comments,
            "permalink": thread.post.permalink,
            "link_flair_text": thread.post.link_flair_text,
        },
        "comments": [
            {
                "score": comment.score,
                "depth": comment.depth,
                "author": comment.author,
                "body": _truncate(comment.body, max_comment_chars),
            }
            for comment in comments[:max_comments]
        ],
    }


def source_quality_local_signals(thread: RedditThread) -> JsonObject:
    comments = thread.flat_comments
    non_bot_comments = [comment for comment in comments if not _is_bot_comment(comment)]
    visible_comments = [comment for comment in non_bot_comments if _clean_body(comment.body).lower() not in REMOVED_BODIES]
    generic_comments = [comment for comment in visible_comments if _is_generic_comment(comment.body)]
    substantive_comments = [comment for comment in visible_comments if _is_substantive_comment(comment)]
    question_comments = [comment for comment in visible_comments if "?" in comment.body]
    post_words = _word_count(thread.post.selftext)
    title_words = _word_count(thread.post.title)
    visible_count = len(visible_comments)
    return {
        "post_body_chars": len(thread.post.selftext or ""),
        "post_body_words": post_words,
        "title_words": title_words,
        "flat_comment_count": len(comments),
        "visible_non_bot_comment_count": visible_count,
        "generic_comment_count": len(generic_comments),
        "generic_comment_ratio": round(len(generic_comments) / max(1, visible_count), 3),
        "substantive_comment_count": len(substantive_comments),
        "question_comment_count": len(question_comments),
        "removed_or_deleted_count": sum(1 for comment in non_bot_comments if _clean_body(comment.body).lower() in REMOVED_BODIES),
        "bot_comment_count": sum(1 for comment in comments if _is_bot_comment(comment)),
        "top_substantive_comment_snippets": [
            _truncate(_clean_body(comment.body), 180)
            for comment in sorted(substantive_comments, key=lambda item: item.score, reverse=True)[:5]
        ],
    }


def deterministic_source_quality_decision(
    thread: RedditThread,
    *,
    local_signals: JsonObject | None = None,
    errors: list[str] | None = None,
) -> SourceQualityDecision:
    signals = local_signals or source_quality_local_signals(thread)
    post_words = int(signals.get("post_body_words") or 0)
    substantive = int(signals.get("substantive_comment_count") or 0)
    generic_ratio = float(signals.get("generic_comment_ratio") or 0)
    questions = int(signals.get("question_comment_count") or 0)
    rejection_codes: list[str] = []
    score = 45

    if post_words < 35:
        rejection_codes.append("thin_post_body")
        score -= 12
    elif post_words >= 140:
        score += 22
    else:
        score += 8
    if substantive >= 8:
        score += 22
    elif substantive >= 4:
        score += 10
    else:
        rejection_codes.append("no_mechanism_or_details")
        score -= 14
    if generic_ratio >= 0.45:
        rejection_codes.append("congrats_only_comments")
        score -= 12
    if questions >= 3:
        score += 6

    score = max(0, min(100, score))
    verdict: Literal["pass", "safe_mode", "reject"]
    if score >= 72 and "thin_post_body" not in rejection_codes:
        verdict = "pass"
    elif score >= 58 and substantive >= 4:
        verdict = "safe_mode"
    else:
        verdict = "reject"
        rejection_codes.append("would_require_invention")

    return SourceQualityDecision(
        post_id=thread.post.id,
        verdict=verdict,
        score_100=score,
        source_depth="rich" if score >= 82 else "usable" if score >= 58 else "thin",
        story_risk="high" if verdict == "reject" else "medium" if verdict == "safe_mode" else "low",
        safe_story_mode="normal_story" if verdict == "pass" else "debate_pattern" if verdict == "safe_mode" else "skip",
        usable_facts=[_truncate(thread.post.title, 140), _truncate(thread.post.selftext, 220)] if thread.post.selftext else [_truncate(thread.post.title, 140)],
        usable_conflicts=[],
        comment_signal_summary=(
            f"{substantive} substantive comments; generic ratio {generic_ratio:.2f}; "
            f"{questions} question comments."
        ),
        rejection_reason_codes=_dedupe_nonempty(rejection_codes),
        missing_information=["Gemini source-quality call failed; local heuristic used.", *(errors or [])],
        rationale="Deterministic fallback based on post length, substantive comments, and generic-comment ratio.",
        confidence=0.55,
    )


def source_quality_cache_path(
    cache_dir: str | Path,
    model: str,
    post_id: str,
    *,
    period_key: str | None = None,
) -> Path:
    parts = [Path(cache_dir), "source_quality_gate", _safe_token(model)]
    if period_key:
        parts.append(_safe_token(period_key))
    return Path(*parts) / f"{_safe_token(post_id)}.json"


def _with_acceptance(
    item: SourceQualityGateItem,
    *,
    min_score: int,
    accept_safe_mode: bool,
) -> SourceQualityGateItem:
    decision = item.decision
    accepted = (
        decision.verdict == "pass"
        and int(decision.score_100) >= int(min_score)
    ) or (
        accept_safe_mode
        and decision.verdict == "safe_mode"
        and int(decision.score_100) >= int(min_score)
    )
    return item.model_copy(update={"accepted": bool(accepted)})


def _normalize_decision(decision: SourceQualityDecision, post_id: str) -> SourceQualityDecision:
    if decision.post_id != post_id:
        decision = decision.model_copy(update={"post_id": post_id})
    if decision.verdict == "reject" and not decision.rejection_reason_codes:
        decision = decision.model_copy(update={"rejection_reason_codes": ["would_require_invention"]})
    return decision


def _is_bot_comment(comment: RedditComment) -> bool:
    author = str(comment.author or "").strip().lower()
    return author in BOT_AUTHORS or author.endswith("bot")


def _is_generic_comment(body: str) -> bool:
    cleaned = _clean_body(body)
    if not cleaned or cleaned.lower() in REMOVED_BODIES:
        return False
    return bool(GENERIC_COMMENT_RE.search(cleaned)) and _word_count(cleaned) <= 28


def _is_substantive_comment(comment: RedditComment) -> bool:
    body = _clean_body(comment.body)
    if not body or body.lower() in REMOVED_BODIES:
        return False
    if _is_generic_comment(body):
        return False
    return _word_count(body) >= 16 or ("?" in body and _word_count(body) >= 8)


def _clean_body(body: str) -> str:
    return re.sub(r"\s+", " ", str(body or "")).strip()


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", str(text or ""), flags=re.UNICODE))


def _truncate(text: str, max_chars: int) -> str:
    value = _clean_body(text)
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "..."


def _safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    return token.strip("-") or "default"


def _dedupe_nonempty(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def source_quality_report_json(batch: SourceQualityGateBatch) -> JsonObject:
    return to_jsonable(batch)
