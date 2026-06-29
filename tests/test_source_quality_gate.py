from __future__ import annotations

import asyncio
from pathlib import Path

from reddit2video.models import RedditComment, RedditPost, RedditThread, RedditThreadBatch
from reddit2video.source_quality_gate import (
    SourceQualityDecision,
    deterministic_source_quality_decision,
    evaluate_source_quality_batch,
    filter_thread_batch_by_source_quality,
    source_quality_local_signals,
)


class FakeGemini:
    def __init__(self, decisions: dict[str, SourceQualityDecision]) -> None:
        self.decisions = decisions
        self.calls: list[str] = []

    async def generate_structured(self, *, prompt, response_model, model=None, cached_content=None):  # noqa: ANN001
        del response_model, cached_content
        for post_id, decision in self.decisions.items():
            if f'"id": "{post_id}"' in prompt:
                self.calls.append(str(model))
                return decision
        raise AssertionError("post id not found in prompt")

    async def aclose(self) -> None:
        return None


def test_source_quality_gate_filters_thin_post_and_keeps_rich_post(tmp_path: Path) -> None:
    thin = _thread(
        "thin1",
        "Biohacking",
        "65 lbs down. Reta/ GH/ MotC/ Slupp",
        "65 lbs using peps. Diet and exercise to maintain muscle mass.",
        ["Great job!", "Congrats!", "What dose?", "Holy hell fuck yeah dude!!!"],
    )
    rich = _thread(
        "rich1",
        "loseit",
        "How do people drink lattes and eat pastries regularly?",
        (
            "I am trying to understand how people fit coffee drinks and pastries into a week "
            "without feeling out of control. I track calories, but the social part keeps confusing me."
        ),
        [
            "I budget breakfast differently when I know I want a latte later, and that changes the whole day.",
            "For me the hidden lever is portion size: I split pastries, not ban them.",
            "This is less about one coffee and more about whether the rest of the day has structure.",
            "A lot of people underestimate how much walking and smaller meals offset the cafe habit.",
        ],
    )
    batch = RedditThreadBatch(threads=[thin, rich], candidates=[], fetched_at="", metadata={})
    gemini = FakeGemini(
        {
            "thin1": SourceQualityDecision(
                post_id="thin1",
                verdict="reject",
                score_100=24,
                source_depth="thin",
                story_risk="high",
                safe_story_mode="skip",
                rejection_reason_codes=["thin_post_body", "congrats_only_comments", "would_require_invention"],
                rationale="Only a result statement and generic praise.",
                confidence=0.96,
            ),
            "rich1": SourceQualityDecision(
                post_id="rich1",
                verdict="pass",
                score_100=86,
                source_depth="rich",
                story_risk="low",
                safe_story_mode="normal_story",
                usable_facts=["calorie tracking", "social cafe habit", "portion size"],
                usable_conflicts=["wants pastries but wants control"],
                rationale="Enough specific tension and mechanisms.",
                confidence=0.91,
            ),
        }
    )

    gate = asyncio.run(
        evaluate_source_quality_batch(
            batch,
            gemini=gemini,  # type: ignore[arg-type]
            model="gemini-3.1-flash-preview",
            fallback_models=[],
            cache_dir=tmp_path,
            min_score=70,
            concurrency=2,
        )
    )
    filtered = filter_thread_batch_by_source_quality(batch, gate)

    assert gate.accepted_post_ids == ["rich1"]
    assert gate.rejected_post_ids == ["thin1"]
    assert [thread.post.id for thread in filtered.threads] == ["rich1"]
    assert gate.metadata["gemini_calls"] == 2


def test_deterministic_source_quality_rejects_congrats_only_thin_source() -> None:
    thread = _thread(
        "thin1",
        "Biohacking",
        "65 lbs down. Reta/ GH/ MotC/ Slupp",
        "65 lbs using peps. Diet and exercise to maintain muscle mass.",
        ["Great job!", "Congrats!", "Looking amazing", "What dose?", "Bravo"],
    )

    signals = source_quality_local_signals(thread)
    decision = deterministic_source_quality_decision(thread, local_signals=signals)

    assert signals["generic_comment_count"] >= 3
    assert decision.verdict == "reject"
    assert "thin_post_body" in decision.rejection_reason_codes
    assert "would_require_invention" in decision.rejection_reason_codes


def _thread(post_id: str, subreddit: str, title: str, selftext: str, comments: list[str]) -> RedditThread:
    return RedditThread(
        post=RedditPost(
            id=post_id,
            fullname=f"t3_{post_id}",
            subreddit=subreddit,
            title=title,
            selftext=selftext,
            url=f"https://www.reddit.com/comments/{post_id}/",
            permalink=f"https://www.reddit.com/comments/{post_id}/",
            author="user",
            score=100,
            upvote_ratio=0.95,
            num_comments=len(comments),
            created_utc=0,
            over_18=False,
            spoiler=False,
            is_self=True,
        ),
        comments=[
            RedditComment(
                id=f"c{index}",
                fullname=f"t1_c{index}",
                parent_id=f"t3_{post_id}",
                link_id=f"t3_{post_id}",
                author=f"user{index}",
                body=body,
                score=max(1, 10 - index),
                created_utc=0,
                permalink="",
                depth=0,
            )
            for index, body in enumerate(comments, start=1)
        ],
        source_url=f"https://www.reddit.com/comments/{post_id}/",
        fetched_at="",
    )
