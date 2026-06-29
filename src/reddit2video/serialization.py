from __future__ import annotations

from reddit2video.models import (
    RedditComment,
    RedditDiscoveryCandidate,
    RedditPost,
    RedditPostSummary,
    RedditThread,
    RedditThreadBatch,
    ScenePipelineBatch,
    ScenePipelineItem,
    HtmlLayoutBatch,
    HtmlLayoutItem,
    GoogleImagePlanBatch,
    GoogleImagePlanItem,
    GoogleImageResolverBatch,
    GoogleImageResolverItem,
    VoiceoverScriptBatch,
    VoiceoverScriptItem,
)


def reddit_batch_from_dict(data: dict) -> RedditThreadBatch:
    return RedditThreadBatch(
        threads=[reddit_thread_from_dict(thread) for thread in data.get("threads", [])],
        candidates=[reddit_candidate_from_dict(candidate) for candidate in data.get("candidates", [])],
        fetched_at=str(data.get("fetched_at", "")),
        metadata=dict(data.get("metadata", {})),
    )


def voiceover_batch_from_dict(data: dict) -> VoiceoverScriptBatch:
    return VoiceoverScriptBatch(
        items=[voiceover_item_from_dict(item) for item in data.get("items", [])],
        fetched_at=str(data.get("fetched_at", "")),
        metadata=dict(data.get("metadata", {})),
    )


def voiceover_item_from_dict(data: dict) -> VoiceoverScriptItem:
    return VoiceoverScriptItem(
        post_id=str(data.get("post_id", "")),
        subreddit=str(data.get("subreddit", "")),
        title=str(data.get("title", "")),
        script=dict(data.get("script", {})),
        validator=data.get("validator"),
        attempts=int(data.get("attempts") or 0),
        from_cache=bool(data.get("from_cache")),
        cache_path=str(data.get("cache_path", "")),
        metadata=dict(data.get("metadata", {})),
    )


def scene_pipeline_batch_from_dict(data: dict) -> ScenePipelineBatch:
    return ScenePipelineBatch(
        items=[scene_pipeline_item_from_dict(item) for item in data.get("items", [])],
        fetched_at=str(data.get("fetched_at", "")),
        metadata=dict(data.get("metadata", {})),
    )


def scene_pipeline_item_from_dict(data: dict) -> ScenePipelineItem:
    status = data.get("status") if data.get("status") in {"pass", "fail"} else "fail"
    return ScenePipelineItem(
        post_id=str(data.get("post_id", "")),
        subreddit=str(data.get("subreddit", "")),
        title=str(data.get("title", "")),
        status=status,
        audio_path=str(data.get("audio_path", "")),
        alignment=dict(data.get("alignment", {})),
        semantic_fragments=dict(data.get("semantic_fragments", {})),
        timed_fragments=list(data.get("timed_fragments", [])),
        scene_plan=data.get("scene_plan"),
        timed_scenes=list(data.get("timed_scenes", [])),
        validator_errors=[str(error) for error in data.get("validator_errors", [])],
        validator_warnings=[str(warning) for warning in data.get("validator_warnings", [])],
        attempts=int(data.get("attempts") or 0),
        from_cache=bool(data.get("from_cache")),
        cache_path=str(data.get("cache_path", "")),
        timed_words=list(data.get("timed_words", [])),
        metadata=dict(data.get("metadata", {})),
    )


def google_image_plan_batch_from_dict(data: dict) -> GoogleImagePlanBatch:
    return GoogleImagePlanBatch(
        items=[google_image_plan_item_from_dict(item) for item in data.get("items", [])],
        fetched_at=str(data.get("fetched_at", "")),
        metadata=dict(data.get("metadata", {})),
    )


def google_image_plan_item_from_dict(data: dict) -> GoogleImagePlanItem:
    status = data.get("status") if data.get("status") in {"pass", "fail"} else "fail"
    return GoogleImagePlanItem(
        post_id=str(data.get("post_id", "")),
        subreddit=str(data.get("subreddit", "")),
        title=str(data.get("title", "")),
        status=status,
        scene_plans=list(data.get("scene_plans", [])),
        planner_errors=[str(error) for error in data.get("planner_errors", [])],
        from_cache=bool(data.get("from_cache")),
        cache_path=str(data.get("cache_path", "")),
        metadata=dict(data.get("metadata", {})),
    )


def google_image_resolver_batch_from_dict(data: dict) -> GoogleImageResolverBatch:
    return GoogleImageResolverBatch(
        items=[google_image_resolver_item_from_dict(item) for item in data.get("items", [])],
        fetched_at=str(data.get("fetched_at", "")),
        metadata=dict(data.get("metadata", {})),
    )


def google_image_resolver_item_from_dict(data: dict) -> GoogleImageResolverItem:
    status = data.get("status") if data.get("status") in {"pass", "fail"} else "fail"
    return GoogleImageResolverItem(
        post_id=str(data.get("post_id", "")),
        subreddit=str(data.get("subreddit", "")),
        title=str(data.get("title", "")),
        status=status,
        resolved_slots=list(data.get("resolved_slots", [])),
        provider_errors=[str(error) for error in data.get("provider_errors", [])],
        from_cache=bool(data.get("from_cache")),
        cache_path=str(data.get("cache_path", "")),
        metadata=dict(data.get("metadata", {})),
    )


def html_layout_batch_from_dict(data: dict) -> HtmlLayoutBatch:
    return HtmlLayoutBatch(
        items=[html_layout_item_from_dict(item) for item in data.get("items", [])],
        fetched_at=str(data.get("fetched_at", "")),
        metadata=dict(data.get("metadata", {})),
    )


def html_layout_item_from_dict(data: dict) -> HtmlLayoutItem:
    status = data.get("status") if data.get("status") in {"pass", "fail"} else "fail"
    return HtmlLayoutItem(
        post_id=str(data.get("post_id", "")),
        subreddit=str(data.get("subreddit", "")),
        title=str(data.get("title", "")),
        status=status,
        html_path=str(data.get("html_path", "")),
        raw_path=str(data.get("raw_path", "")),
        prompt_path=str(data.get("prompt_path", "")),
        preview_path=str(data.get("preview_path", "")),
        qa=dict(data.get("qa", {})),
        repair_attempts=int(data.get("repair_attempts") or 0),
        from_existing=bool(data.get("from_existing")),
        metadata=dict(data.get("metadata", {})),
    )


def reddit_thread_from_dict(data: dict) -> RedditThread:
    return RedditThread(
        post=reddit_post_from_dict(data.get("post", {})),
        comments=[reddit_comment_from_dict(comment) for comment in data.get("comments", [])],
        source_url=str(data.get("source_url", "")),
        fetched_at=str(data.get("fetched_at", "")),
        metadata=dict(data.get("metadata", {})),
    )


def reddit_post_from_dict(data: dict) -> RedditPost:
    return RedditPost(
        id=str(data.get("id", "")),
        fullname=str(data.get("fullname", "")),
        subreddit=str(data.get("subreddit", "")),
        title=str(data.get("title", "")),
        selftext=str(data.get("selftext", "")),
        url=str(data.get("url", "")),
        permalink=str(data.get("permalink", "")),
        author=data.get("author"),
        score=int(data.get("score") or 0),
        upvote_ratio=_float_or_none(data.get("upvote_ratio")),
        num_comments=int(data.get("num_comments") or 0),
        created_utc=_float_or_none(data.get("created_utc")),
        over_18=bool(data.get("over_18")),
        spoiler=bool(data.get("spoiler")),
        is_self=bool(data.get("is_self")),
        link_flair_text=data.get("link_flair_text"),
    )


def reddit_comment_from_dict(data: dict) -> RedditComment:
    return RedditComment(
        id=str(data.get("id", "")),
        fullname=str(data.get("fullname", "")),
        parent_id=str(data.get("parent_id", "")),
        link_id=str(data.get("link_id", "")),
        author=data.get("author"),
        body=str(data.get("body", "")),
        score=int(data.get("score") or 0),
        created_utc=_float_or_none(data.get("created_utc")),
        permalink=str(data.get("permalink", "")),
        depth=int(data.get("depth") or 0),
        replies=[reddit_comment_from_dict(reply) for reply in data.get("replies", [])],
    )


def reddit_candidate_from_dict(data: dict) -> RedditDiscoveryCandidate:
    return RedditDiscoveryCandidate(
        post=reddit_post_summary_from_dict(data.get("post", {})),
        interesting_score=float(data.get("interesting_score") or 0),
        relevance_score=float(data.get("relevance_score") or 0),
        age_hours=_float_or_none(data.get("age_hours")),
        reasons=[str(reason) for reason in data.get("reasons", [])],
    )


def reddit_post_summary_from_dict(data: dict) -> RedditPostSummary:
    return RedditPostSummary(
        id=str(data.get("id", "")),
        fullname=str(data.get("fullname", "")),
        subreddit=str(data.get("subreddit", "")),
        title=str(data.get("title", "")),
        author=data.get("author"),
        permalink=str(data.get("permalink", "")),
        score=int(data.get("score") or 0),
        num_comments=int(data.get("num_comments") or 0),
        created_utc=_float_or_none(data.get("created_utc")),
        over_18=bool(data.get("over_18")),
        stickied=bool(data.get("stickied")),
    )


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
