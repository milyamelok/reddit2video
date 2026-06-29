from __future__ import annotations

import base64
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import parse

import httpx

from reddit2video.models import (
    RedditDiscoveryCandidate,
    RedditDiscoveryRequest,
    NodeSpec,
    RedditComment,
    RedditPost,
    RedditPostSummary,
    RedditThread,
    RedditThreadBatch,
    RedditThreadRequest,
)
from reddit2video.nodes.base import AsyncBaseNode, NodeError


REDDIT_WEB_BASE = "https://www.reddit.com"
REDDIT_OAUTH_BASE = "https://oauth.reddit.com"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"

DEFAULT_DISCOVERY_SUBREDDITS = [
    "Biohackers",
    "biohacking",
    "longevity",
    "Supplements",
    "nutrition",
    "loseit",
    "WeightLossAdvice",
    "intermittentfasting",
    "fasting",
    "CICO",
    "Fitness",
    "bodyweightfitness",
    "AdvancedFitness",
    "weightroom",
    "running",
    "xxfitness",
    "leangains",
]

DEFAULT_TOPIC_KEYWORDS = [
    "biohack",
    "biohacking",
    "longevity",
    "wellness",
    "health",
    "sleep",
    "recovery",
    "supplement",
    "vitamin",
    "magnesium",
    "creatine",
    "protein",
    "diet",
    "nutrition",
    "calorie",
    "weight loss",
    "fat loss",
    "fasting",
    "workout",
    "training",
    "fitness",
    "cardio",
    "strength",
    "running",
    "sport",
]

META_TITLE_PATTERNS = [
    "daily thread",
    "weekly thread",
    "simple questions",
    "questions thread",
    "discussion thread",
    "megathread",
    "check-in",
    "moronic monday",
    "rant wednesday",
    "this sub",
    "this subreddit",
    "voting",
    "voting system",
    "downvote",
    "upvote",
    "moderator",
    "moderation",
    "mods",
    "karma",
]


class RedditApiError(NodeError):
    pass


@dataclass(frozen=True)
class RedditCredentials:
    client_id: str
    client_secret: str
    user_agent: str

    @classmethod
    def from_env(cls) -> "RedditCredentials":
        client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
        user_agent = os.getenv("REDDIT_USER_AGENT", "").strip()
        missing = [
            name
            for name, value in {
                "REDDIT_CLIENT_ID": client_id,
                "REDDIT_CLIENT_SECRET": client_secret,
                "REDDIT_USER_AGENT": user_agent,
            }.items()
            if not value
        ]
        if missing:
            raise RedditApiError(
                "Missing Reddit OAuth config: "
                + ", ".join(missing)
                + ". Fill them in .env or export them in your shell."
            )
        return cls(client_id=client_id, client_secret=client_secret, user_agent=user_agent)


@dataclass
class _AccessToken:
    value: str
    expires_at: float

    def is_valid(self) -> bool:
        return time.time() < self.expires_at - 60


class RedditClient:
    def __init__(
        self,
        credentials: RedditCredentials,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.credentials = credentials
        self.timeout_seconds = timeout_seconds
        self._token: _AccessToken | None = None
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_env(cls, timeout_seconds: float = 20.0) -> "RedditClient":
        return cls(RedditCredentials.from_env(), timeout_seconds=timeout_seconds)

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_posts(
        self,
        subreddit: str,
        *,
        sort: str = "hot",
        time_filter: str = "day",
        limit: int = 25,
    ) -> list[RedditPostSummary]:
        clean_subreddit = _clean_subreddit(subreddit)
        sort = _clean_sort(sort)
        limit = max(1, min(limit, 100))
        params: dict[str, Any] = {"limit": limit, "raw_json": 1}
        if sort in {"top", "controversial"}:
            params["t"] = time_filter
        payload = await self._oauth_get(f"/r/{clean_subreddit}/{sort}.json", params)
        children = payload.get("data", {}).get("children", [])
        return [_parse_post_summary(child.get("data", {})) for child in children if child.get("kind") == "t3"]

    async def fetch_thread(self, thread_request: RedditThreadRequest) -> RedditThread:
        post_id = normalize_post_id(thread_request.post_id or thread_request.post_url or "")
        subreddit = _clean_subreddit(thread_request.subreddit) if thread_request.subreddit else None
        comment_limit = max(1, min(thread_request.comment_limit, 500))
        comment_depth = max(0, min(thread_request.comment_depth, 10))
        params = {
            "limit": comment_limit,
            "depth": comment_depth,
            "sort": thread_request.comment_sort,
            "raw_json": 1,
        }
        path = f"/comments/{post_id}.json"
        if subreddit:
            path = f"/r/{subreddit}/comments/{post_id}.json"

        payload = await self._oauth_get(path, params)
        if not isinstance(payload, list) or len(payload) < 2:
            raise RedditApiError(f"Unexpected Reddit thread payload for post {post_id}")

        post_children = payload[0].get("data", {}).get("children", [])
        if not post_children:
            raise RedditApiError(f"Reddit returned no post for {post_id}")

        post_data = post_children[0].get("data", {})
        post = _parse_post(post_data)
        comments = _parse_comments_listing(payload[1], depth=0)
        source_url = _absolute_permalink(post.permalink)
        return RedditThread(
            post=post,
            comments=comments,
            source_url=source_url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "comment_limit": comment_limit,
                "comment_depth": comment_depth,
                "comment_sort": thread_request.comment_sort,
                "top_level_comments": len(comments),
                "flat_comments": sum(len(comment.flatten()) for comment in comments),
            },
        )

    async def _oauth_get(self, path: str, params: dict[str, Any]) -> Any:
        token = await self._get_access_token()
        query = parse.urlencode(params)
        url = f"{REDDIT_OAUTH_BASE}{path}"
        if query:
            url = f"{url}?{query}"
        return await self._request_json(
            "GET",
            url,
            headers={
                "Authorization": f"bearer {token}",
                "User-Agent": self.credentials.user_agent,
                "Accept": "application/json",
            },
        )

    async def _get_access_token(self) -> str:
        if self._token and self._token.is_valid():
            return self._token.value

        basic_value = base64.b64encode(
            f"{self.credentials.client_id}:{self.credentials.client_secret}".encode("utf-8")
        ).decode("ascii")
        data = parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
        payload = await self._request_json(
            "POST",
            REDDIT_TOKEN_URL,
            content=data,
            headers={
                "Authorization": f"Basic {basic_value}",
                "User-Agent": self.credentials.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        access_token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 3600))
        if not access_token:
            raise RedditApiError("Reddit token response did not contain access_token")
        self._token = _AccessToken(value=access_token, expires_at=time.time() + expires_in)
        return access_token

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes | None = None,
    ) -> Any:
        try:
            response = await self._http_client().request(method, url, headers=headers, content=content)
            response.raise_for_status()
            body = response.text
        except httpx.HTTPStatusError as exc:
            raise RedditApiError(
                f"Reddit HTTP {exc.response.status_code}: {_compact_error_body(exc.response.text)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RedditApiError(f"Reddit request failed: {exc}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RedditApiError("Reddit returned invalid JSON") from exc

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=True)
        return self._client


class RedditParser:
    def __init__(self, client: RedditClient | None = None) -> None:
        self.client = client or RedditClient.from_env()

    async def aclose(self) -> None:
        await self.client.aclose()

    async def fetch_thread(self, thread_request: RedditThreadRequest) -> RedditThread:
        return await self.client.fetch_thread(thread_request)

    async def discover_threads(self, discovery_request: RedditDiscoveryRequest) -> RedditThreadBatch:
        candidates, discovery_errors = await self.discover_candidates(discovery_request)
        selected_candidates: list[RedditDiscoveryCandidate] = []
        threads: list[RedditThread] = []
        fetch_errors: list[dict[str, str]] = []

        for candidate in candidates:
            if len(threads) >= discovery_request.post_limit:
                break
            try:
                thread = await self.client.fetch_thread(
                    RedditThreadRequest(
                        post_id=candidate.post.id,
                        subreddit=candidate.post.subreddit,
                        comment_limit=discovery_request.comment_limit,
                        comment_depth=discovery_request.comment_depth,
                        comment_sort=discovery_request.comment_sort,
                    )
                )
            except RedditApiError as exc:
                fetch_errors.append({"post_id": candidate.post.id, "error": str(exc)})
                continue
            thread.metadata.update(
                {
                    "discovery_score": candidate.interesting_score,
                    "discovery_relevance_score": candidate.relevance_score,
                    "discovery_reasons": candidate.reasons,
                }
            )
            threads.append(thread)
            selected_candidates.append(candidate)

        return RedditThreadBatch(
            threads=threads,
            candidates=selected_candidates,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "requested_post_limit": discovery_request.post_limit,
                "hours": discovery_request.hours,
                "time_filter": discovery_request.time_filter,
                "topics": discovery_request.topics,
                "subreddits": _resolve_discovery_subreddits(discovery_request.subreddits),
                "candidate_count": len(candidates),
                "discovery_errors": discovery_errors,
                "fetch_errors": fetch_errors,
            },
        )

    async def discover_candidates(
        self, discovery_request: RedditDiscoveryRequest
    ) -> tuple[list[RedditDiscoveryCandidate], list[dict[str, str]]]:
        now = time.time()
        oldest_created_utc = now - max(1, discovery_request.hours) * 3600
        subreddits = _resolve_discovery_subreddits(discovery_request.subreddits)
        keywords = _topic_keywords(discovery_request.topics)
        seen_post_ids: set[str] = set()
        candidates: list[RedditDiscoveryCandidate] = []
        errors: list[dict[str, str]] = []

        for subreddit in subreddits:
            for sort_mode in discovery_request.sort_modes:
                try:
                    posts = await self.client.list_posts(
                        subreddit,
                        sort=sort_mode,
                        time_filter=discovery_request.time_filter,
                        limit=discovery_request.per_subreddit_limit,
                    )
                except RedditApiError as exc:
                    errors.append({"subreddit": subreddit, "sort": sort_mode, "error": str(exc)})
                    continue

                for post in posts:
                    if post.id in seen_post_ids:
                        continue
                    if not _passes_discovery_filters(post, discovery_request, oldest_created_utc):
                        continue
                    candidate = _score_candidate(post, keywords, now)
                    seen_post_ids.add(post.id)
                    candidates.append(candidate)

        candidates.sort(key=lambda candidate: candidate.interesting_score, reverse=True)
        return candidates, errors


class RedditThreadNode(AsyncBaseNode[RedditThreadRequest, RedditThread]):
    spec = NodeSpec(
        step="step-0",
        name="reddit_thread",
        description="Retrieve a Reddit post and nested comments via Reddit OAuth.",
        mocked=False,
    )

    def __init__(self, parser: RedditParser | None = None, client: RedditClient | None = None) -> None:
        self.parser = parser or RedditParser(client=client)

    async def run(self, node_input: RedditThreadRequest) -> RedditThread:
        return await self.parser.fetch_thread(node_input)


class RedditDiscoveryNode(AsyncBaseNode[RedditDiscoveryRequest, RedditThreadBatch]):
    spec = NodeSpec(
        step="step-0",
        name="reddit_discovery",
        description="Discover interesting recent Reddit posts and fetch their comment threads.",
        mocked=False,
    )

    def __init__(self, parser: RedditParser | None = None, client: RedditClient | None = None) -> None:
        self.parser = parser or RedditParser(client=client)

    async def run(self, node_input: RedditDiscoveryRequest) -> RedditThreadBatch:
        return await self.parser.discover_threads(node_input)


def _resolve_discovery_subreddits(subreddits: list[str]) -> list[str]:
    clean_subreddits = [_clean_subreddit(subreddit) for subreddit in subreddits if subreddit.strip()]
    if clean_subreddits:
        return list(dict.fromkeys(clean_subreddits))
    return DEFAULT_DISCOVERY_SUBREDDITS.copy()


def _topic_keywords(topics: list[str]) -> list[str]:
    keywords = DEFAULT_TOPIC_KEYWORDS.copy()
    for topic in topics:
        cleaned_topic = topic.strip().lower()
        if cleaned_topic:
            keywords.append(cleaned_topic)
            keywords.extend(part for part in re.split(r"[^a-z0-9]+", cleaned_topic) if len(part) > 3)
    return list(dict.fromkeys(keywords))


def _passes_discovery_filters(
    post: RedditPostSummary,
    discovery_request: RedditDiscoveryRequest,
    oldest_created_utc: float,
) -> bool:
    if not post.id or post.stickied:
        return False
    if post.over_18 and not discovery_request.include_nsfw:
        return False
    if post.created_utc is None or post.created_utc < oldest_created_utc:
        return False
    if post.score < discovery_request.min_score:
        return False
    if post.num_comments < discovery_request.min_comments:
        return False
    title = post.title.lower()
    return not any(pattern in title for pattern in META_TITLE_PATTERNS)


def _score_candidate(post: RedditPostSummary, keywords: list[str], now: float) -> RedditDiscoveryCandidate:
    age_hours = None
    if post.created_utc is not None:
        age_hours = max(0.25, (now - post.created_utc) / 3600)
    effective_age = age_hours or 24.0
    matched_keywords = _matched_keywords(post.title, keywords)
    relevance_score = min(10.0, len(matched_keywords) * 1.6)
    popularity_score = math.log1p(max(0, post.score)) * 4.0
    discussion_score = math.log1p(max(0, post.num_comments)) * 5.0
    velocity_score = math.log1p((max(0, post.score) + max(0, post.num_comments) * 2) / effective_age) * 3.0
    interesting_score = popularity_score + discussion_score + velocity_score + relevance_score
    reasons = [
        f"score={post.score}",
        f"comments={post.num_comments}",
    ]
    if age_hours is not None:
        reasons.append(f"age_hours={age_hours:.1f}")
    if matched_keywords:
        reasons.append("matched=" + ",".join(matched_keywords[:6]))
    return RedditDiscoveryCandidate(
        post=post,
        interesting_score=round(interesting_score, 3),
        relevance_score=round(relevance_score, 3),
        age_hours=round(age_hours, 3) if age_hours is not None else None,
        reasons=reasons,
    )


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword in lowered]


def normalize_post_id(value: str) -> str:
    value = value.strip()
    if not value:
        raise RedditApiError("Reddit post id or URL is required")
    if value.startswith("t3_"):
        return value[3:]
    if re.fullmatch(r"[A-Za-z0-9_]+", value) and "/" not in value:
        return value
    match = re.search(r"/comments/([A-Za-z0-9_]+)", value)
    if match:
        return match.group(1)
    match = re.search(r"redd\.it/([A-Za-z0-9_]+)", value)
    if match:
        return match.group(1)
    raise RedditApiError(f"Cannot extract Reddit post id from: {value}")


def _parse_post_summary(data: dict[str, Any]) -> RedditPostSummary:
    return RedditPostSummary(
        id=str(data.get("id", "")),
        fullname=str(data.get("name", "")),
        subreddit=str(data.get("subreddit", "")),
        title=str(data.get("title", "")),
        author=_author(data),
        permalink=_absolute_permalink(str(data.get("permalink", ""))),
        score=int(data.get("score") or 0),
        num_comments=int(data.get("num_comments") or 0),
        created_utc=_float_or_none(data.get("created_utc")),
        over_18=bool(data.get("over_18")),
        stickied=bool(data.get("stickied")),
    )


def _parse_post(data: dict[str, Any]) -> RedditPost:
    return RedditPost(
        id=str(data.get("id", "")),
        fullname=str(data.get("name", "")),
        subreddit=str(data.get("subreddit", "")),
        title=str(data.get("title", "")),
        selftext=str(data.get("selftext") or ""),
        url=str(data.get("url") or ""),
        permalink=_absolute_permalink(str(data.get("permalink", ""))),
        author=_author(data),
        score=int(data.get("score") or 0),
        upvote_ratio=_float_or_none(data.get("upvote_ratio")),
        num_comments=int(data.get("num_comments") or 0),
        created_utc=_float_or_none(data.get("created_utc")),
        over_18=bool(data.get("over_18")),
        spoiler=bool(data.get("spoiler")),
        is_self=bool(data.get("is_self")),
        link_flair_text=data.get("link_flair_text"),
    )


def _parse_comments_listing(payload: Any, *, depth: int) -> list[RedditComment]:
    if not isinstance(payload, dict):
        return []
    children = payload.get("data", {}).get("children", [])
    comments: list[RedditComment] = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data", {})
        replies_payload = data.get("replies")
        comment_depth = int(data.get("depth") if data.get("depth") is not None else depth)
        comment = RedditComment(
            id=str(data.get("id", "")),
            fullname=str(data.get("name", "")),
            parent_id=str(data.get("parent_id", "")),
            link_id=str(data.get("link_id", "")),
            author=_author(data),
            body=str(data.get("body") or ""),
            score=int(data.get("score") or 0),
            created_utc=_float_or_none(data.get("created_utc")),
            permalink=_absolute_permalink(str(data.get("permalink", ""))),
            depth=comment_depth,
            replies=_parse_comments_listing(replies_payload, depth=comment_depth + 1),
        )
        comments.append(comment)
    return comments


def _author(data: dict[str, Any]) -> str | None:
    author = data.get("author")
    if not author or author == "[deleted]":
        return None
    return str(author)


def _absolute_permalink(permalink: str) -> str:
    if permalink.startswith("http://") or permalink.startswith("https://"):
        return permalink
    if permalink.startswith("/"):
        return f"{REDDIT_WEB_BASE}{permalink}"
    return permalink


def _clean_subreddit(subreddit: str) -> str:
    subreddit = subreddit.strip()
    if subreddit.startswith("r/"):
        subreddit = subreddit[2:]
    if not subreddit:
        raise RedditApiError("Subreddit is required")
    if not re.fullmatch(r"[A-Za-z0-9_+]+", subreddit):
        raise RedditApiError(f"Invalid subreddit value: {subreddit}")
    return subreddit


def _clean_sort(sort: str) -> str:
    sort = sort.strip().lower()
    allowed = {"hot", "new", "top", "rising", "controversial"}
    if sort not in allowed:
        raise RedditApiError(f"Invalid subreddit sort '{sort}'. Allowed: {', '.join(sorted(allowed))}")
    return sort


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compact_error_body(body: str) -> str:
    body = body.strip()
    if len(body) > 500:
        return body[:500] + "..."
    return body
