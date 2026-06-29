#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shlex
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SECRET_DIR = ROOT / "local_secrets" / "heygen_probe"


def main() -> int:
    args = parse_args()
    if args.cookie_header_file == "-":
        raw_cookie_input = sys.stdin.read()
    else:
        cookie_header_path = Path(args.cookie_header_file)
        if not cookie_header_path.exists():
            print(f"cookie header file not found: {cookie_header_path}", file=sys.stderr)
            return 1
        raw_cookie_input = cookie_header_path.read_text(encoding="utf-8")

    cookie_header = extract_cookie_header(raw_cookie_input)
    cookies = parse_cookie_header(cookie_header)
    if not cookies:
        print("no cookies found in cookie header file", file=sys.stderr)
        return 1

    out_path = Path(args.out) if args.out else default_out_path()
    ensure_local_secret(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    storage_state = {
        "cookies": [
            {
                "name": name,
                "value": value,
                "domain": args.domain,
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            }
            for name, value in cookies
        ],
        "origins": [],
    }
    out_path.write_text(json.dumps(storage_state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "storage_state": str(out_path),
                "cookie_count": len(cookies),
                "cookie_names": [name for name, _ in cookies],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.auth_probe:
        return auth_probe(out_path)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a copied HeyGen Cookie header or curl command into Playwright storage_state JSON."
    )
    parser.add_argument(
        "cookie_header_file",
        help="Local file, or '-' for stdin, containing `Cookie: a=b; c=d`, `a=b; c=d`, or a full curl command.",
    )
    parser.add_argument("--out", default="")
    parser.add_argument("--domain", default=".heygen.com")
    parser.add_argument("--auth-probe", action="store_true")
    return parser.parse_args()


def extract_cookie_header(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    from_curl = extract_curl_cookie_arg(text)
    if from_curl:
        return from_curl
    for index, line in enumerate(lines):
        lower = line.lower()
        if lower.startswith("cookie:"):
            return line.split(":", 1)[1].strip()
        if lower == "cookie" and index + 1 < len(lines):
            return lines[index + 1].strip()
    return " ".join(lines).strip()


def extract_curl_cookie_arg(text: str) -> str:
    normalized = text.replace("\\\n", " ")
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return ""
    for index, part in enumerate(parts):
        if part in ("-b", "--cookie") and index + 1 < len(parts):
            return parts[index + 1].strip()
        if part.startswith("--cookie="):
            return part.split("=", 1)[1].strip()
    return ""


def parse_cookie_header(header: str) -> list[tuple[str, str]]:
    cookies: list[tuple[str, str]] = []
    seen: set[str] = set()
    for chunk in header.split(";"):
        item = chunk.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or name in seen:
            continue
        cookies.append((name, value))
        seen.add(name)
    return cookies


def auth_probe(path: Path) -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from heygen_internal import HeyGenError, HeyGenInternalClient  # noqa: PLC0415

    try:
        payload: dict[str, Any] = HeyGenInternalClient(path).auth_probe()
    except HeyGenError as exc:
        print(
            json.dumps(
                {"ok": False, "auth_probe": "failed", "status": exc.status, "body": exc.body[:500]},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps({"ok": True, "auth_probe": "passed", "response_keys": sorted(payload.keys())}, indent=2))
    return 0


def default_out_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return SECRET_DIR / f"heygen-storage-state-manual-cookie-{stamp}.json"


def ensure_local_secret(path: Path) -> None:
    resolved = path.resolve()
    secret_root = SECRET_DIR.resolve()
    if secret_root not in (resolved, *resolved.parents):
        raise SystemExit(f"refusing to write outside local_secrets/heygen_probe: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
