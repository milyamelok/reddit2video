#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.models import RedditDiscoveryRequest, to_jsonable  # noqa: E402
from reddit2video.nodes.base import NodeError  # noqa: E402
from reddit2video.nodes.reddit import RedditDiscoveryNode  # noqa: E402


def main() -> int:
    return asyncio.run(_amain())


async def _amain() -> int:
    _load_env_file(ROOT / ".env")
    output_path = ROOT / "outputs" / "reddit-wellness-24h.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        batch = await RedditDiscoveryNode().run(RedditDiscoveryRequest())
    except NodeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output_path.write_text(json.dumps(to_jsonable(batch), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Collected {len(batch.threads)} Reddit threads from {batch.metadata['candidate_count']} candidates")
    print(f"Wrote {output_path.relative_to(ROOT)}")
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
