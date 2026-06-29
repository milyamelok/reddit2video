#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit2video.gemini import GeminiClient  # noqa: E402
from reddit2video.serialization import reddit_batch_from_dict  # noqa: E402
from reddit2video.source_quality_gate import (  # noqa: E402
    DEFAULT_SOURCE_QUALITY_FALLBACK_MODELS,
    DEFAULT_SOURCE_QUALITY_MIN_SCORE,
    DEFAULT_SOURCE_QUALITY_MODEL,
    evaluate_source_quality_batch,
    filter_thread_batch_by_source_quality,
)
from reddit2video.models import to_jsonable  # noqa: E402


def main() -> int:
    return asyncio.run(_amain(parse_args()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Filter Reddit threads before Stage 1 using Gemini source-quality gate.")
    parser.add_argument("--input", required=True, help="RedditThreadBatch JSON.")
    parser.add_argument("--out", required=True, help="Filtered RedditThreadBatch JSON.")
    parser.add_argument("--report", default="", help="Gate report JSON. Defaults to OUT.source-quality-gate.json.")
    parser.add_argument("--env-file", action="append", default=[".env.iac", ".env"])
    parser.add_argument("--model", default=DEFAULT_SOURCE_QUALITY_MODEL)
    parser.add_argument(
        "--fallback-model",
        action="append",
        default=[],
        help="Fallback model. Repeatable. Defaults to gemini-3-flash-preview if omitted.",
    )
    parser.add_argument("--min-score", type=int, default=DEFAULT_SOURCE_QUALITY_MIN_SCORE)
    parser.add_argument("--accept-safe-mode", action="store_true")
    parser.add_argument("--cache-dir", default="outputs/cache")
    parser.add_argument("--period-key", default="")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    for env_file in args.env_file:
        load_env_file(ROOT / env_file)

    input_path = resolve_path(args.input)
    out_path = resolve_path(args.out)
    report_path = resolve_path(args.report) if args.report else out_path.with_suffix(".source-quality-gate.json")
    batch = reddit_batch_from_dict(json.loads(input_path.read_text(encoding="utf-8")))
    fallback_models = args.fallback_model or DEFAULT_SOURCE_QUALITY_FALLBACK_MODELS

    client = GeminiClient.from_env(model=str(args.model), vertex=True)
    try:
        gate = await evaluate_source_quality_batch(
            batch,
            gemini=client,
            model=str(args.model),
            fallback_models=[str(model) for model in fallback_models],
            min_score=max(0, min(100, int(args.min_score))),
            accept_safe_mode=bool(args.accept_safe_mode),
            cache_dir=str(args.cache_dir),
            period_key=args.period_key or None,
            concurrency=max(1, int(args.concurrency)),
            force=bool(args.force),
        )
    finally:
        await client.aclose()

    filtered = filter_thread_batch_by_source_quality(batch, gate)
    write_json(out_path, to_jsonable(filtered))
    write_json(report_path, gate.model_dump())
    print(
        json.dumps(
            {
                "input": str(input_path),
                "out": str(out_path),
                "report": str(report_path),
                "model": args.model,
                "accepted": gate.accepted_post_ids,
                "rejected": gate.rejected_post_ids,
                "metadata": gate.metadata,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not filtered.threads:
        raise SystemExit("source-quality gate rejected every thread")
    return 0


def resolve_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else ROOT / candidate


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_env_file(path: Path) -> None:
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
