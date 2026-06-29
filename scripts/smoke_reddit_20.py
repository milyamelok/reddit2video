#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.models import RedditThreadRequest, to_jsonable  # noqa: E402
from reddit2video.nodes.base import NodeError  # noqa: E402
from reddit2video.nodes.reddit import RedditClient, RedditThreadNode  # noqa: E402


def main() -> int:
    return asyncio.run(_amain())


async def _amain() -> int:
    parser = argparse.ArgumentParser(description="Fetch 20 different Reddit posts through RedditThreadNode.")
    parser.add_argument("--env-file", default=".env", help="Optional dotenv-style file to load.")
    parser.add_argument("--subreddit", default="AskReddit", help="Subreddit to sample.")
    parser.add_argument("--sort", default="hot", choices=["hot", "new", "top", "rising", "controversial"])
    parser.add_argument("--time-filter", default="day", choices=["hour", "day", "week", "month", "year", "all"])
    parser.add_argument("--runs", type=int, default=20, help="How many different posts to fetch.")
    parser.add_argument("--listing-limit", type=int, default=80, help="How many posts to inspect before sampling.")
    parser.add_argument("--comment-limit", type=int, default=100)
    parser.add_argument("--comment-depth", type=int, default=8)
    parser.add_argument("--comment-sort", default="top")
    parser.add_argument("--include-nsfw", action="store_true")
    parser.add_argument("--sleep", type=float, default=1.0, help="Delay between thread fetches.")
    parser.add_argument("--out", default="outputs/reddit-smoke", help="Output directory.")
    args = parser.parse_args()

    _load_env_file(Path(args.env_file))

    try:
        client = RedditClient.from_env()
        node = RedditThreadNode(client=client)
    except NodeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        posts = await client.list_posts(
            args.subreddit,
            sort=args.sort,
            time_filter=args.time_filter,
            limit=args.listing_limit,
        )
    except NodeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    seen_post_ids: set[str] = set()
    candidates = []
    for post in posts:
        if not post.id or post.id in seen_post_ids:
            continue
        if post.stickied or (post.over_18 and not args.include_nsfw):
            continue
        seen_post_ids.add(post.id)
        candidates.append(post)
        if len(candidates) >= args.runs:
            break
    if len(candidates) < args.runs:
        raise SystemExit(
            f"Only found {len(candidates)} candidate posts, need {args.runs}. "
            "Try --listing-limit 100, --sort new, or --include-nsfw."
        )

    summary = []
    for index, post in enumerate(candidates, start=1):
        print(f"[{index:02d}/{len(candidates):02d}] fetching {post.id} from r/{post.subreddit}: {post.title[:90]}")
        started = time.time()
        try:
            thread = await node.run(
                RedditThreadRequest(
                    post_id=post.id,
                    subreddit=post.subreddit,
                    comment_limit=args.comment_limit,
                    comment_depth=args.comment_depth,
                    comment_sort=args.comment_sort,
                )
            )
        except NodeError as exc:
            print(f"Error fetching {post.id}: {exc}", file=sys.stderr)
            return 1
        output_path = out_dir / f"{index:02d}_{post.subreddit}_{post.id}.json"
        output_path.write_text(json.dumps(to_jsonable(thread), ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append(
            {
                "index": index,
                "post_id": thread.post.id,
                "subreddit": thread.post.subreddit,
                "title": thread.post.title,
                "output_path": str(output_path),
                "top_level_comments": len(thread.comments),
                "flat_comments": len(thread.flat_comments),
                "elapsed_seconds": round(time.time() - started, 3),
            }
        )
        if index < len(candidates) and args.sleep > 0:
            time.sleep(args.sleep)

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(summary)} thread files + {summary_path}")
    return 0


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


if __name__ == "__main__":
    raise SystemExit(main())
