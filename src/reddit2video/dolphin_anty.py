from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class DolphinStartResult:
    browser: Any
    playwright: Any
    profile_id: str
    port: int
    ws_endpoint: str


class DolphinAntyError(RuntimeError):
    pass


async def start_dolphin_browser(
    *,
    profile_id: str,
    local_api_url: str,
    headless: bool = False,
) -> DolphinStartResult:
    from playwright.async_api import async_playwright

    base = local_api_url.rstrip("/")
    params: dict[str, str] = {"automation": "1"}
    if headless:
        params["headless"] = "true"
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.get(f"{base}/v1.0/browser_profiles/{profile_id}/start", params=params)
    try:
        payload = response.json()
    except ValueError as exc:
        raise DolphinAntyError(f"Dolphin Anty returned non-JSON response: {response.text[:300]}") from exc
    if response.status_code >= 400 or payload.get("error") or not payload.get("success"):
        message = payload.get("error") or payload.get("message") or str(payload)
        raise DolphinAntyError(f"Dolphin Anty start failed: {message}")
    automation = payload.get("automation") or {}
    port = int(automation.get("port") or 0)
    ws_endpoint = str(automation.get("wsEndpoint") or "")
    if not port or not ws_endpoint:
        raise DolphinAntyError(f"Dolphin Anty start did not return CDP endpoint: {payload}")
    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(f"ws://127.0.0.1:{port}{ws_endpoint}")
    return DolphinStartResult(
        browser=browser,
        playwright=playwright,
        profile_id=profile_id,
        port=port,
        ws_endpoint=ws_endpoint,
    )


async def stop_dolphin_profile(*, profile_id: str, local_api_url: str) -> None:
    base = local_api_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20) as client:
        await client.get(f"{base}/v1.0/browser_profiles/{profile_id}/stop")
