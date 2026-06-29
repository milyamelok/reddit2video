#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SECRET_DIR = ROOT / "local_secrets" / "heygen_probe"
DEFAULT_HEYGEN_URL = "https://app.heygen.com/videos/calista-template-f252c1fe849d49b69336bab7c838baa9"
USER_GET_URL = "https://api2.heygen.com/v1/user.get"
CHROME_EXECUTABLE = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
MAC_CHROME_ROOT = Path.home() / "Library/Application Support/Google/Chrome"


def main() -> int:
    args = parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open or attach to Chrome, poll HeyGen auth cookies in real time, "
            "and save a Playwright storage_state once user.get is authorized."
        )
    )
    parser.add_argument("--mode", choices=("launch", "cdp"), default="launch")
    parser.add_argument("--url", default=DEFAULT_HEYGEN_URL)
    parser.add_argument("--interval-sec", type=float, default=5.0)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    parser.add_argument("--state-path", default="")
    parser.add_argument("--show-cookie-names", action="store_true")
    parser.add_argument("--keep-open", action="store_true", help="In launch mode, leave Chrome open after saving.")

    launch = parser.add_argument_group("launch mode")
    launch.add_argument("--chrome-executable", default=str(CHROME_EXECUTABLE))
    launch.add_argument("--user-data-dir", default="")
    launch.add_argument(
        "--profile-directory",
        default="Profile 9",
        help="Chrome profile directory name inside copied user-data-dir.",
    )
    launch.add_argument(
        "--profile-source",
        default=str(MAC_CHROME_ROOT / "Profile 9"),
        help="Existing Chrome profile to clone before launch. Pass '' with --fresh.",
    )
    launch.add_argument("--fresh", action="store_true", help="Use an empty user-data-dir instead of cloning Profile 9.")

    cdp = parser.add_argument_group("cdp mode")
    cdp.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    cdp.add_argument("--no-goto", action="store_true", help="Do not navigate the attached tab to --url.")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is not installed for this Python. Try: python3 -m pip install playwright") from exc

    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state_path) if args.state_path else default_state_path()

    async with async_playwright() as playwright:
        if args.mode == "cdp":
            browser = await playwright.chromium.connect_over_cdp(args.cdp_url)
            contexts = browser.contexts
            context = contexts[0] if contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            if not args.no_goto:
                await page.goto(args.url, wait_until="domcontentloaded", timeout=90_000)
            close_browser = False
        else:
            user_data_dir = prepare_user_data_dir(args)
            chrome_executable = Path(args.chrome_executable)
            if not chrome_executable.exists():
                raise RuntimeError(f"Chrome executable not found: {chrome_executable}")
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                executable_path=str(chrome_executable),
                headless=False,
                viewport={"width": 1440, "height": 1000},
                args=[f"--profile-directory={args.profile_directory}"],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(args.url, wait_until="domcontentloaded", timeout=90_000)
            close_browser = not args.keep_open
            print(f"user_data_dir={user_data_dir}", flush=True)

        print(f"url={args.url}", flush=True)
        print(f"state_path={state_path}", flush=True)
        print("waiting for HeyGen auth... log in in the opened Chrome window", flush=True)
        try:
            await watch_auth(context, page, state_path, args)
        finally:
            if args.mode == "cdp":
                await browser.close()
            elif close_browser:
                await context.close()


def prepare_user_data_dir(args: argparse.Namespace) -> Path:
    if args.user_data_dir:
        user_data_dir = Path(args.user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)
        return user_data_dir

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    user_data_dir = SECRET_DIR / f"chrome-user-data-heygen-auth-{stamp}"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    if args.fresh:
        return user_data_dir

    profile_source = Path(args.profile_source) if args.profile_source else None
    local_state = MAC_CHROME_ROOT / "Local State"
    if not profile_source or not profile_source.exists():
        raise RuntimeError(f"profile source not found: {profile_source}. Use --fresh for an empty auth profile.")
    if not local_state.exists():
        raise RuntimeError(f"Chrome Local State not found: {local_state}. Use --fresh for an empty auth profile.")

    shutil.copy2(local_state, user_data_dir / "Local State")
    ignore = shutil.ignore_patterns(
        "Cache",
        "Code Cache",
        "GPUCache",
        "GrShaderCache",
        "ShaderCache",
        "DawnCache",
        "Service Worker/CacheStorage",
        "Media Cache",
        "Crashpad",
        "BrowserMetrics",
        "*.tmp",
        "Singleton*",
    )
    shutil.copytree(profile_source, user_data_dir / args.profile_directory, dirs_exist_ok=True, ignore=ignore)
    return user_data_dir


async def watch_auth(context: Any, page: Any, state_path: Path, args: argparse.Namespace) -> None:
    max_polls = max(1, int(args.timeout_sec / args.interval_sec))
    last_signature = ""
    for poll in range(max_polls):
        cookies = await context.cookies(["https://app.heygen.com", "https://api2.heygen.com"])
        heygen_cookies = [
            cookie for cookie in cookies if "heygen" in cookie.get("domain", "") or "movio" in cookie.get("domain", "")
        ]
        user_result = await probe_user_get(page)
        signature = cookie_signature(heygen_cookies, user_result)
        if signature != last_signature or poll == 0:
            print_status(poll, heygen_cookies, user_result, args.show_cookie_names)
            last_signature = signature
        if is_authorized(user_result):
            await context.storage_state(path=str(state_path))
            print(f"saved={state_path}", flush=True)
            return
        await asyncio.sleep(args.interval_sec)
    raise RuntimeError(f"timeout without authorized HeyGen session after {args.timeout_sec}s")


async def probe_user_get(page: Any) -> dict[str, Any]:
    try:
        result = await page.evaluate(
            """
            async (url) => {
              try {
                const res = await fetch(url, {credentials: 'include'});
                const text = await res.text();
                let json = null;
                try { json = JSON.parse(text); } catch (_) {}
                return {ok: res.ok, status: res.status, text: text.slice(0, 500), json};
              } catch (error) {
                return {ok: false, status: 0, text: String(error).slice(0, 500), json: null};
              }
            }
            """,
            USER_GET_URL,
        )
    except Exception as exc:  # Browser may be mid-navigation/login redirect.
        return {"ok": False, "status": -1, "text": str(exc)[:500], "json": None}
    return dict(result)


def is_authorized(result: dict[str, Any]) -> bool:
    if int(result.get("status") or 0) != 200:
        return False
    text = str(result.get("text") or "").lower()
    if "unauthorized" in text:
        return False
    payload = result.get("json")
    if isinstance(payload, dict):
        if payload.get("code") in (400112, "400112"):
            return False
        data = payload.get("data")
        if data:
            return True
    return bool(text and text not in ("{}", "null"))


def print_status(poll: int, cookies: list[dict[str, Any]], result: dict[str, Any], show_names: bool) -> None:
    names = sorted({str(cookie.get("name") or "") for cookie in cookies if cookie.get("name")})
    body_hint = compact_body_hint(result.get("json"), str(result.get("text") or ""))
    line = f"poll={poll:03d} status={result.get('status')} cookies={len(cookies)} {body_hint}"
    if show_names:
        line += f" cookie_names={names}"
    print(line, flush=True)


def cookie_signature(cookies: list[dict[str, Any]], result: dict[str, Any]) -> str:
    cookie_bits = sorted(
        f"{cookie.get('domain')}:{cookie.get('name')}:{cookie.get('expires', 0)}" for cookie in cookies
    )
    return json.dumps([result.get("status"), result.get("text"), cookie_bits], sort_keys=True, ensure_ascii=True)


def compact_body_hint(payload: Any, text: str) -> str:
    if isinstance(payload, dict):
        code = payload.get("code")
        message = payload.get("message")
        data = payload.get("data")
        if isinstance(data, dict):
            user = data.get("user") or data.get("user_info") or data
            if isinstance(user, dict):
                email = user.get("email") or user.get("user_email") or user.get("account")
                if email:
                    return f"email={email}"
        if code or message:
            return f"code={code} message={message}"
    return text[:120].replace("\n", " ")


def default_state_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return SECRET_DIR / f"heygen-storage-state-{stamp}.json"


if __name__ == "__main__":
    raise SystemExit(main())
