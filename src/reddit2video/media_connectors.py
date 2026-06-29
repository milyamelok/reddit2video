from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx


@dataclass(frozen=True)
class MediaCandidate:
    candidate_id: str
    provider: str
    query: str
    title: str = ""
    page_url: str = ""
    thumbnail_url: str = ""
    media_url: str = ""
    width: int | None = None
    height: int | None = None
    position: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaSearchResult:
    provider: str
    query: str
    candidates: list[MediaCandidate]
    screenshot_path: str
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PlaywrightMediaConnector(ABC):
    provider: str
    label_prefix: str
    requires_browser = True

    @abstractmethod
    async def search(
        self,
        *,
        context: Any,
        query: str,
        limit: int,
        screenshot_path: Path,
        scroll_steps: int = 2,
    ) -> MediaSearchResult:
        raise NotImplementedError

    async def _search_dom_page(
        self,
        *,
        context: Any,
        url: str,
        query: str,
        selectors: list[str],
        limit: int,
        screenshot_path: Path,
        scroll_steps: int = 2,
        wait_selector: str | None = None,
        extra_wait_ms: int = 1500,
    ) -> MediaSearchResult:
        page = await context.new_page()
        errors: list[str] = []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
            await _accept_common_dialogs(page)
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=12_000)
                except Exception as exc:
                    errors.append(f"wait_selector_failed:{type(exc).__name__}")
            await page.wait_for_timeout(extra_wait_ms)
            await _gentle_scroll(page, steps=scroll_steps)
            if await _looks_blocked_or_captcha(page):
                errors.append("blocked_or_captcha_detected")
            raw_candidates = await page.evaluate(
                _EXTRACT_MEDIA_CANDIDATES_SCRIPT,
                {
                    "provider": self.provider,
                    "labelPrefix": self.label_prefix,
                    "query": query,
                    "selectors": selectors,
                    "limit": limit,
                },
            )
            candidates = [
                _candidate_from_raw(self.provider, query, item)
                for item in raw_candidates
                if item.get("candidate_id")
            ]
            await page.evaluate(_INJECT_LABELS_SCRIPT)
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot_path), full_page=False)
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=candidates,
                screenshot_path=str(screenshot_path),
                errors=errors,
                metadata={"url": url},
            )
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=errors,
                metadata={"url": url},
            )
        finally:
            await page.close()


class GiphyPlaywrightConnector(PlaywrightMediaConnector):
    provider = "giphy"
    label_prefix = "G"

    async def search(
        self,
        *,
        context: Any,
        query: str,
        limit: int,
        screenshot_path: Path,
        scroll_steps: int = 2,
    ) -> MediaSearchResult:
        slug = quote_plus(query).replace("+", "-")
        url = f"https://giphy.com/search/{slug}"
        return await self._search_dom_page(
            context=context,
            url=url,
            query=query,
            selectors=[
                'a[href*="/gifs/"]',
                '[data-testid*="gif"]',
                'img[src*="giphy"]',
                'video',
            ],
            limit=limit,
            screenshot_path=screenshot_path,
            scroll_steps=scroll_steps,
            wait_selector="img, video",
            extra_wait_ms=2200,
        )


class GiphyApiConnector(PlaywrightMediaConnector):
    provider = "giphy"
    label_prefix = "G"
    requires_browser = False
    base_endpoint = "https://api.giphy.com/v1"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        scope: str = "auto",
        api_key_source: str = "env",
        web_key_cache_path: str | Path = "outputs/cache/giphy_web_api_key.json",
        rating: str = "pg",
        lang: str = "en",
        bundle: str = "",
        remove_low_contrast: bool = True,
        download_assets: bool = True,
        download_concurrency: int = 8,
        cache_api_responses: bool = True,
        asset_dir: Path | None = None,
    ) -> None:
        self.api_key_source = (api_key_source or "env").strip().lower()
        if self.api_key_source not in {"env", "web", "auto"}:
            self.api_key_source = "env"
        self.api_key = api_key or (os.getenv("GIPHY_API_KEY", "") if self.api_key_source != "web" else "")
        self.scope = scope or "auto"
        self.web_key_cache_path = Path(web_key_cache_path)
        self.rating = rating
        self.lang = lang
        self.bundle = bundle
        self.remove_low_contrast = remove_low_contrast
        self.download_assets = download_assets
        self.download_concurrency = download_concurrency
        self.cache_api_responses = cache_api_responses
        self.asset_dir = asset_dir
        self.requires_browser = self.api_key_source in {"web", "auto"} and not (
            self.api_key or _read_giphy_web_api_key_cache(self.web_key_cache_path)
        )

    async def search(
        self,
        *,
        context: Any,
        query: str,
        limit: int,
        screenshot_path: Path,
        scroll_steps: int = 2,
    ) -> MediaSearchResult:
        errors: list[str] = []
        api_key, key_metadata, key_errors = await self._resolve_api_key(context=context)
        errors.extend(key_errors)
        if not api_key:
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=["missing_giphy_api_key"],
                metadata={
                    "transport": "api",
                    "url": self.base_endpoint,
                    "scope": self.scope,
                    "api_key": key_metadata,
                },
            )

        api_query = _giphy_query(query)
        scopes = _giphy_api_scopes(self.scope)
        max_candidates = min(max(int(limit), 1), 12)
        proxy = os.getenv("OUTBOUND_PROXY") or None
        asset_root = self.asset_dir or screenshot_path.parent / "giphy_assets"
        api_cache_hits = 0
        candidates: list[MediaCandidate] = []
        seen_giphy_ids: set[str] = set()
        endpoints: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=25, proxy=proxy, follow_redirects=True) as client:
                for active_scope in scopes:
                    if len(candidates) >= max_candidates:
                        break
                    endpoint = f"{self.base_endpoint}/{active_scope}/search"
                    endpoints.append(endpoint)
                    params: dict[str, Any] = {
                        "api_key": api_key,
                        "q": api_query,
                        "limit": max_candidates,
                        "offset": 0,
                        "rating": self.rating,
                        "lang": self.lang,
                        "type": active_scope,
                        "remove_low_contrast": "true" if self.remove_low_contrast else "false",
                    }
                    if self.bundle:
                        params["bundle"] = self.bundle
                    cache_path = (
                        _giphy_api_cache_path(asset_root / active_scope, params)
                        if self.cache_api_responses
                        else None
                    )
                    if cache_path and cache_path.exists():
                        payload = json.loads(cache_path.read_text(encoding="utf-8"))
                        api_cache_hits += 1
                    else:
                        response = await client.get(endpoint, params=params)
                        if response.status_code in {401, 403} and self.api_key_source in {"web", "auto"}:
                            refreshed_key, refreshed_metadata, refreshed_errors = await self._resolve_api_key(
                                context=context,
                                force_refresh=True,
                            )
                            key_metadata.update({f"refresh_{key}": value for key, value in refreshed_metadata.items()})
                            errors.extend(refreshed_errors)
                            if refreshed_key and refreshed_key != api_key:
                                api_key = refreshed_key
                                params["api_key"] = api_key
                                response = await client.get(endpoint, params=params)
                        if response.status_code >= 400:
                            errors.append(f"giphy_api_http_{response.status_code}_{active_scope}: {response.text[:300]}")
                            continue
                        payload = response.json()
                        if cache_path:
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            cache_path.write_text(json.dumps(payload), encoding="utf-8")
                    for item in payload.get("data", []) or []:
                        if len(candidates) >= max_candidates:
                            break
                        giphy_id = str(item.get("id") or "")
                        if giphy_id and giphy_id in seen_giphy_ids:
                            continue
                        candidate = _giphy_candidate_from_raw(
                            index=len(candidates) + 1,
                            query=query,
                            item=item,
                            api_scope=active_scope,
                        )
                        if candidate.media_url:
                            candidates.append(candidate)
                            if giphy_id:
                                seen_giphy_ids.add(giphy_id)
        except Exception as exc:
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=[f"{type(exc).__name__}: {exc}"],
                metadata={
                    "transport": "api",
                    "url": self.base_endpoint,
                    "scope": self.scope,
                    "requested_scopes": scopes,
                    "api_query": api_query,
                    "api_key": key_metadata,
                },
            )

        if candidates and self.download_assets:
            try:
                candidates, download_errors, download_metadata = await _download_giphy_candidate_assets(
                    candidates=candidates,
                    download_root=asset_root,
                    concurrency=self.download_concurrency,
                )
                errors.extend(download_errors)
            except Exception as exc:
                download_metadata = {"enabled": True, "error": f"{type(exc).__name__}: {exc}"}
                errors.append(f"giphy_asset_download_failed:{type(exc).__name__}: {exc}")
        else:
            download_metadata = {"enabled": bool(self.download_assets), "downloaded_files": 0, "cache_hits": 0}
        if candidates and context is not None:
            try:
                await _render_api_contact_sheet(
                    context=context,
                    provider="giphy",
                    candidates=candidates,
                    screenshot_path=screenshot_path,
                )
            except Exception as exc:
                errors.append(f"contact_sheet_failed:{type(exc).__name__}: {exc}")

        return MediaSearchResult(
            provider=self.provider,
            query=query,
            candidates=candidates,
            screenshot_path=str(screenshot_path),
            errors=errors,
            metadata={
                "transport": "api",
                "url": endpoints[0] if len(endpoints) == 1 else self.base_endpoint,
                "api_endpoints": endpoints,
                "scope": self.scope,
                "requested_scopes": scopes,
                "api_query": api_query,
                "api_key": key_metadata,
                "api_cache_hits": api_cache_hits,
                "asset_download": download_metadata,
            },
        )

    async def _resolve_api_key(self, *, context: Any, force_refresh: bool = False) -> tuple[str, dict[str, Any], list[str]]:
        errors: list[str] = []
        metadata: dict[str, Any] = {"source": self.api_key_source}
        if self.api_key_source == "env":
            metadata["resolved_from"] = "env"
            return self.api_key, metadata, errors
        if self.api_key_source == "auto" and self.api_key and not force_refresh:
            metadata["resolved_from"] = "env"
            return self.api_key, metadata, errors

        cached_key = "" if force_refresh else _read_giphy_web_api_key_cache(self.web_key_cache_path)
        if cached_key:
            metadata["resolved_from"] = "web_cache"
            return cached_key, metadata, errors

        if context is None:
            errors.append("giphy_web_key_refresh_requires_browser_context")
            if self.api_key_source == "auto" and self.api_key:
                metadata["resolved_from"] = "env_fallback"
                return self.api_key, metadata, errors
            metadata["resolved_from"] = "missing_browser_context"
            return "", metadata, errors

        try:
            web_key = await _discover_giphy_web_api_key(context)
        except Exception as exc:
            errors.append(f"giphy_web_key_refresh_failed:{type(exc).__name__}: {exc}")
            if self.api_key_source == "auto" and self.api_key:
                metadata["resolved_from"] = "env_fallback"
                return self.api_key, metadata, errors
            metadata["resolved_from"] = "web_refresh_failed"
            return "", metadata, errors
        if web_key:
            _write_giphy_web_api_key_cache(self.web_key_cache_path, web_key)
            metadata["resolved_from"] = "web_refresh"
            self.requires_browser = False
            return web_key, metadata, errors

        errors.append("giphy_web_key_not_found")
        if self.api_key_source == "auto" and self.api_key:
            metadata["resolved_from"] = "env_fallback"
            return self.api_key, metadata, errors
        metadata["resolved_from"] = "web_refresh_empty"
        return "", metadata, errors


class GoogleImagesPlaywrightConnector(PlaywrightMediaConnector):
    provider = "google_images"
    label_prefix = "I"

    async def search(
        self,
        *,
        context: Any,
        query: str,
        limit: int,
        screenshot_path: Path,
        scroll_steps: int = 2,
    ) -> MediaSearchResult:
        encoded = quote_plus(query)
        url = f"https://www.google.com/search?tbm=isch&hl=en&safe=active&q={encoded}"
        return await self._search_dom_page(
            context=context,
            url=url,
            query=query,
            selectors=[
                'a[href*="/imgres"]',
                'a[href*="imgurl="]',
                "img",
            ],
            limit=limit,
            screenshot_path=screenshot_path,
            scroll_steps=scroll_steps,
            wait_selector="img",
            extra_wait_ms=1800,
        )


class BrightDataGoogleImagesConnector(PlaywrightMediaConnector):
    provider = "brightdata_google_images"
    label_prefix = "B"
    requires_browser = False
    endpoint = "https://api.brightdata.com/request"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        zone: str = "",
        size: str = "large",
        cache_api_responses: bool = True,
        cache_dir: Path | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("BRIGHTDATA_API_KEY", "")
        self.zone = zone or os.getenv("BRIGHTDATA_ZONE", "") or "serp_api1"
        self.size = size if size in {"small", "medium", "large"} else "large"
        self.cache_api_responses = cache_api_responses
        self.cache_dir = cache_dir

    async def search(
        self,
        *,
        context: Any,
        query: str,
        limit: int,
        screenshot_path: Path,
        scroll_steps: int = 2,
    ) -> MediaSearchResult:
        if not self.api_key:
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=["missing_brightdata_api_key"],
                metadata={"transport": "brightdata_request", "zone": self.zone, "size": self.size},
            )

        size_param = {"small": "s", "medium": "m", "large": "l"}[self.size]
        google_url = (
            "https://www.google.com/search?"
            f"q={quote_plus(query)}&tbm=isch&tbs=isz:{size_param},sur:cl&brd_json=1"
        )
        payload = {
            "zone": self.zone,
            "url": google_url,
            "format": "raw",
            "method": "GET",
        }
        max_candidates = min(max(int(limit), 1), 100)
        cache_root = self.cache_dir or screenshot_path.parent / "brightdata_google_images"
        cache_path = (
            _brightdata_google_cache_path(cache_root, payload, self.size)
            if self.cache_api_responses
            else None
        )
        errors: list[str] = []
        api_cache_hit = False
        try:
            if cache_path and cache_path.exists():
                response_payload = json.loads(cache_path.read_text(encoding="utf-8"))
                api_cache_hit = True
            else:
                proxy = os.getenv("OUTBOUND_PROXY") or None
                headers = {
                    "Authorization": _brightdata_authorization_header(self.api_key),
                    "Content-Type": "application/json",
                }
                async with httpx.AsyncClient(timeout=45, proxy=proxy, follow_redirects=True) as client:
                    response = await client.post(self.endpoint, json=payload, headers=headers)
                    if response.status_code == 500:
                        await asyncio.sleep(5)
                        response = await client.post(self.endpoint, json=payload, headers=headers)
                    if response.status_code >= 400:
                        return MediaSearchResult(
                            provider=self.provider,
                            query=query,
                            candidates=[],
                            screenshot_path=str(screenshot_path),
                            errors=[f"brightdata_http_{response.status_code}: {response.text[:240]}"],
                            metadata={
                                "transport": "brightdata_request",
                                "zone": self.zone,
                                "size": self.size,
                                "url": google_url,
                            },
                        )
                    try:
                        response_payload = response.json()
                    except Exception:
                        return MediaSearchResult(
                            provider=self.provider,
                            query=query,
                            candidates=[],
                            screenshot_path=str(screenshot_path),
                            errors=[f"brightdata_invalid_json_response: {response.text[:240]}"],
                            metadata={
                                "transport": "brightdata_request",
                                "zone": self.zone,
                                "size": self.size,
                                "url": google_url,
                            },
                        )
                    if cache_path:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_text(json.dumps(response_payload), encoding="utf-8")
        except Exception as exc:
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=[f"brightdata_request_failed:{type(exc).__name__}: {exc}"],
                metadata={
                    "transport": "brightdata_request",
                    "zone": self.zone,
                    "size": self.size,
                    "url": google_url,
                },
            )

        raw_images = response_payload.get("images") if isinstance(response_payload, dict) else None
        if not isinstance(raw_images, list):
            raw_images = []
            errors.append("brightdata_response_missing_images")
        candidates: list[MediaCandidate] = []
        seen_urls: set[str] = set()
        for raw in raw_images:
            if not isinstance(raw, dict):
                continue
            candidate = _brightdata_google_candidate_from_raw(
                index=len(candidates) + 1,
                query=query,
                item=raw,
            )
            if not candidate or not candidate.media_url or candidate.media_url in seen_urls:
                continue
            candidates.append(candidate)
            seen_urls.add(candidate.media_url)
            if len(candidates) >= max_candidates:
                break

        if candidates and context is not None:
            try:
                await _render_api_contact_sheet(
                    context=context,
                    provider=self.provider,
                    candidates=candidates,
                    screenshot_path=screenshot_path,
                )
            except Exception as exc:
                errors.append(f"contact_sheet_failed:{type(exc).__name__}: {exc}")

        return MediaSearchResult(
            provider=self.provider,
            query=query,
            candidates=candidates,
            screenshot_path=str(screenshot_path),
            errors=errors,
            metadata={
                "transport": "brightdata_request",
                "zone": self.zone,
                "size": self.size,
                "url": google_url,
                "api_cache_hit": api_cache_hit,
            },
        )


class SerperDevImagesConnector(PlaywrightMediaConnector):
    provider = "serper_images"
    label_prefix = "S"
    requires_browser = False
    endpoint = "https://google.serper.dev/images"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        gl: str = "us",
        hl: str = "en",
        cache_api_responses: bool = True,
        cache_dir: Path | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("SERPER_API_KEY", "")
        self.gl = gl or os.getenv("SERPER_GL", "") or "us"
        self.hl = hl or os.getenv("SERPER_HL", "") or "en"
        self.cache_api_responses = cache_api_responses
        self.cache_dir = cache_dir

    async def search(
        self,
        *,
        context: Any,
        query: str,
        limit: int,
        screenshot_path: Path,
        scroll_steps: int = 2,
    ) -> MediaSearchResult:
        if not self.api_key:
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=["missing_serper_api_key"],
                metadata={"transport": "serper_dev", "gl": self.gl, "hl": self.hl},
            )

        max_candidates = min(max(int(limit), 1), 100)
        payload: dict[str, Any] = {"q": query, "gl": self.gl, "hl": self.hl}
        # Serper returns 10 images for one credit by default. Asking for ~100 costs
        # more, so only request num when the node actually needs more than 10.
        if max_candidates > 10:
            payload["num"] = max_candidates
        cache_root = self.cache_dir or screenshot_path.parent / "serper_images"
        cache_path = _serper_images_cache_path(cache_root, payload) if self.cache_api_responses else None
        errors: list[str] = []
        api_cache_hit = False
        try:
            if cache_path and cache_path.exists():
                response_payload = json.loads(cache_path.read_text(encoding="utf-8"))
                api_cache_hit = True
            else:
                proxy = os.getenv("OUTBOUND_PROXY") or None
                headers = {
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                }
                async with httpx.AsyncClient(timeout=30, proxy=proxy, follow_redirects=True) as client:
                    response = await client.post(self.endpoint, json=payload, headers=headers)
                    if response.status_code >= 400:
                        return MediaSearchResult(
                            provider=self.provider,
                            query=query,
                            candidates=[],
                            screenshot_path=str(screenshot_path),
                            errors=[f"serper_http_{response.status_code}: {response.text[:240]}"],
                            metadata={
                                "transport": "serper_dev",
                                "gl": self.gl,
                                "hl": self.hl,
                                "endpoint": self.endpoint,
                            },
                        )
                    response_payload = response.json()
                    if cache_path:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_text(json.dumps(response_payload), encoding="utf-8")
        except Exception as exc:
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=[f"serper_request_failed:{type(exc).__name__}: {exc}"],
                metadata={
                    "transport": "serper_dev",
                    "gl": self.gl,
                    "hl": self.hl,
                    "endpoint": self.endpoint,
                },
            )

        raw_images = response_payload.get("images") if isinstance(response_payload, dict) else None
        if not isinstance(raw_images, list):
            raw_images = []
            errors.append("serper_response_missing_images")
        candidates: list[MediaCandidate] = []
        seen_urls: set[str] = set()
        for raw in raw_images:
            if not isinstance(raw, dict):
                continue
            candidate = _serper_image_candidate_from_raw(
                index=len(candidates) + 1,
                query=query,
                item=raw,
            )
            if not candidate or not candidate.media_url or candidate.media_url in seen_urls:
                continue
            candidates.append(candidate)
            seen_urls.add(candidate.media_url)
            if len(candidates) >= max_candidates:
                break

        if candidates and context is not None:
            try:
                await _render_api_contact_sheet(
                    context=context,
                    provider=self.provider,
                    candidates=candidates,
                    screenshot_path=screenshot_path,
                )
            except Exception as exc:
                errors.append(f"contact_sheet_failed:{type(exc).__name__}: {exc}")

        return MediaSearchResult(
            provider=self.provider,
            query=query,
            candidates=candidates,
            screenshot_path=str(screenshot_path),
            errors=errors,
            metadata={
                "transport": "serper_dev",
                "gl": self.gl,
                "hl": self.hl,
                "endpoint": self.endpoint,
                "credits": response_payload.get("credits") if isinstance(response_payload, dict) else None,
                "api_cache_hit": api_cache_hit,
            },
        )


class WikimediaCommonsImagesConnector(PlaywrightMediaConnector):
    provider = "wikimedia_commons"
    label_prefix = "W"
    requires_browser = False
    endpoint = "https://commons.wikimedia.org/w/api.php"

    def __init__(
        self,
        *,
        cache_api_responses: bool = True,
        cache_dir: Path | None = None,
        thumb_width: int = 1400,
    ) -> None:
        self.cache_api_responses = cache_api_responses
        self.cache_dir = cache_dir
        self.thumb_width = max(720, int(thumb_width or 1400))

    async def search(
        self,
        *,
        context: Any,
        query: str,
        limit: int,
        screenshot_path: Path,
        scroll_steps: int = 2,
    ) -> MediaSearchResult:
        max_candidates = min(max(int(limit), 1), 12)
        params: dict[str, Any] = {
            "action": "query",
            "generator": "search",
            "gsrsearch": _wikimedia_search_query(query),
            "gsrnamespace": "6",
            "gsrlimit": max_candidates,
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": self.thumb_width,
            "format": "json",
            "formatversion": "2",
            "origin": "*",
        }
        cache_root = self.cache_dir or screenshot_path.parent / "wikimedia_commons"
        cache_path = _wikimedia_commons_cache_path(cache_root, params) if self.cache_api_responses else None
        errors: list[str] = []
        api_cache_hit = False
        try:
            if cache_path and cache_path.exists():
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                api_cache_hit = True
            else:
                proxy = os.getenv("OUTBOUND_PROXY") or None
                user_agent = _wikimedia_user_agent()
                headers = {"User-Agent": user_agent, "Api-User-Agent": user_agent}
                async with httpx.AsyncClient(timeout=30, proxy=proxy, follow_redirects=True) as client:
                    response = await client.get(self.endpoint, params=params, headers=headers)
                    if response.status_code >= 400:
                        return MediaSearchResult(
                            provider=self.provider,
                            query=query,
                            candidates=[],
                            screenshot_path=str(screenshot_path),
                            errors=[f"wikimedia_http_{response.status_code}: {response.text[:240]}"],
                            metadata={"transport": "mediawiki_api", "endpoint": self.endpoint},
                        )
                    payload = response.json()
                    if cache_path:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as exc:
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=[f"wikimedia_request_failed:{type(exc).__name__}: {exc}"],
                metadata={"transport": "mediawiki_api", "endpoint": self.endpoint},
            )

        pages = ((payload.get("query") or {}).get("pages") or []) if isinstance(payload, dict) else []
        if not isinstance(pages, list):
            pages = []
            errors.append("wikimedia_response_missing_pages")
        candidates: list[MediaCandidate] = []
        seen_urls: set[str] = set()
        for raw in pages:
            if not isinstance(raw, dict):
                continue
            candidate = _wikimedia_commons_candidate_from_raw(
                index=len(candidates) + 1,
                query=query,
                item=raw,
            )
            if not candidate or not candidate.media_url or candidate.media_url in seen_urls:
                continue
            candidates.append(candidate)
            seen_urls.add(candidate.media_url)
            if len(candidates) >= max_candidates:
                break

        return MediaSearchResult(
            provider=self.provider,
            query=query,
            candidates=candidates,
            screenshot_path=str(screenshot_path),
            errors=errors,
            metadata={
                "transport": "mediawiki_api",
                "endpoint": self.endpoint,
                "api_cache_hit": api_cache_hit,
                "thumb_width": self.thumb_width,
            },
        )


class PinterestPlaywrightConnector(PlaywrightMediaConnector):
    provider = "pinterest"
    label_prefix = "P"

    def __init__(self, *, scope: str = "auto") -> None:
        self.scope = scope or "auto"

    async def search(
        self,
        *,
        context: Any,
        query: str,
        limit: int,
        screenshot_path: Path,
        scroll_steps: int = 3,
    ) -> MediaSearchResult:
        encoded = quote_plus(query)
        scopes = _pinterest_api_scopes(self.scope)
        search_kind = "videos" if scopes == ["videos"] else "pins"
        url = f"https://www.pinterest.com/search/{search_kind}/?q={encoded}&rs=typed"
        page = await context.new_page()
        errors: list[str] = []
        network_candidates: list[MediaCandidate] = []
        response_tasks: set[asyncio.Task[None]] = set()
        seen_pin_ids: set[str] = set()

        async def capture_base_search_response(response: Any) -> None:
            if "BaseSearchResource/get" not in str(response.url):
                return
            try:
                payload = await response.json()
            except Exception as exc:
                errors.append(f"pinterest_base_search_json_failed:{type(exc).__name__}")
                return
            results = _pinterest_base_search_results(payload)
            for raw in results:
                if len(network_candidates) >= limit:
                    break
                if not isinstance(raw, dict):
                    continue
                pin_id = str(raw.get("id") or "")
                if pin_id and pin_id in seen_pin_ids:
                    continue
                candidate = _pinterest_candidate_from_raw(
                    index=len(network_candidates) + 1,
                    query=query,
                    item=raw,
                    api_scope=search_kind,
                )
                if candidate and candidate.media_url:
                    network_candidates.append(candidate)
                    if pin_id:
                        seen_pin_ids.add(pin_id)

        def on_response(response: Any) -> None:
            task = asyncio.create_task(capture_base_search_response(response))
            response_tasks.add(task)
            task.add_done_callback(response_tasks.discard)

        page.on("response", on_response)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
            await _accept_common_dialogs(page)
            try:
                await page.wait_for_selector("img, video", timeout=12_000)
            except Exception as exc:
                errors.append(f"wait_selector_failed:{type(exc).__name__}")
            await page.wait_for_timeout(2500)
            await _gentle_scroll(page, steps=scroll_steps)
            if response_tasks:
                try:
                    await asyncio.wait_for(asyncio.gather(*response_tasks, return_exceptions=True), timeout=6)
                except asyncio.TimeoutError:
                    errors.append("pinterest_network_capture_timeout")
            if await _looks_blocked_or_captcha(page):
                errors.append("blocked_or_captcha_detected")
            raw_candidates = await page.evaluate(
                _EXTRACT_MEDIA_CANDIDATES_SCRIPT,
                {
                    "provider": self.provider,
                    "labelPrefix": self.label_prefix,
                    "query": query,
                    "selectors": [
                        'a[href*="/pin/"]',
                        'img[src*="pinimg.com"]',
                        "video",
                    ],
                    "limit": limit,
                },
            )
            dom_candidates = [
                _candidate_from_raw(self.provider, query, item)
                for item in raw_candidates
                if item.get("candidate_id")
            ]
            candidates = _merge_and_renumber_candidates(
                network_candidates,
                dom_candidates,
                prefix=self.label_prefix,
                limit=limit,
            )
            await page.evaluate(_INJECT_LABELS_SCRIPT)
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(screenshot_path), full_page=False)
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=candidates,
                screenshot_path=str(screenshot_path),
                errors=errors,
                metadata={
                    "url": url,
                    "transport": "playwright_with_base_search_capture",
                    "network_candidates": len(network_candidates),
                    "dom_candidates": len(dom_candidates),
                },
            )
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=errors,
                metadata={"url": url, "transport": "playwright_with_base_search_capture"},
            )
        finally:
            await page.close()


class PinterestApiConnector(PlaywrightMediaConnector):
    provider = "pinterest"
    label_prefix = "P"
    requires_browser = False
    default_endpoint = "https://ru.pinterest.com/resource/BaseSearchResource/get/"

    def __init__(
        self,
        *,
        request_dump_path: str | Path | None = None,
        scope: str = "auto",
        cache_api_responses: bool = True,
        cache_dir: Path | None = None,
    ) -> None:
        dump_value = str(request_dump_path or os.getenv("PINTEREST_REQUEST_DUMP_PATH", "") or "")
        self.request_dump_path = Path(dump_value) if dump_value else None
        self.scope = scope or "auto"
        self.cache_api_responses = cache_api_responses
        self.cache_dir = cache_dir

    async def search(
        self,
        *,
        context: Any,
        query: str,
        limit: int,
        screenshot_path: Path,
        scroll_steps: int = 2,
    ) -> MediaSearchResult:
        if self.request_dump_path is None or not self.request_dump_path.exists():
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=["missing_pinterest_request_dump"],
                metadata={"transport": "api", "scope": self.scope},
            )

        try:
            dump = json.loads(self.request_dump_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return MediaSearchResult(
                provider=self.provider,
                query=query,
                candidates=[],
                screenshot_path=str(screenshot_path),
                errors=[f"pinterest_request_dump_read_failed:{type(exc).__name__}: {exc}"],
                metadata={"transport": "api", "scope": self.scope},
            )

        endpoint = str(dump.get("url") or self.default_endpoint)
        headers = _pinterest_api_headers(dump)
        max_candidates = min(max(int(limit), 1), 100)
        page_budget = max(1, int(scroll_steps or 1))
        cache_root = self.cache_dir or screenshot_path.parent / "pinterest_api"
        candidates: list[MediaCandidate] = []
        errors: list[str] = []
        scopes = _pinterest_api_scopes(self.scope)
        seen_pin_ids: set[str] = set()
        api_cache_hits = 0

        proxy = os.getenv("OUTBOUND_PROXY") or None
        async with httpx.AsyncClient(timeout=25, proxy=proxy, follow_redirects=True) as client:
            per_scope_target = (max_candidates + len(scopes) - 1) // len(scopes)
            for scope_index, active_scope in enumerate(scopes):
                bookmark: str | None = None
                scope_candidates = 0
                scope_limit = max_candidates if scope_index == len(scopes) - 1 else per_scope_target
                for page_index in range(1, page_budget + 1):
                    post_data = _pinterest_api_post_data(
                        query=query,
                        scope=active_scope,
                        page_size=min(max_candidates, 25),
                        bookmark=bookmark,
                    )
                    cache_path = (
                        _pinterest_api_cache_path(cache_root, post_data, active_scope, page_index)
                        if self.cache_api_responses
                        else None
                    )
                    try:
                        if cache_path and cache_path.exists():
                            payload = json.loads(cache_path.read_text(encoding="utf-8"))
                            api_cache_hits += 1
                        else:
                            request_headers = _pinterest_api_headers_for_post(
                                headers,
                                endpoint=endpoint,
                                source_url=post_data["source_url"],
                            )
                            response: httpx.Response | None = None
                            for attempt in range(3):
                                try:
                                    response = await client.post(endpoint, data=post_data, headers=request_headers)
                                    break
                                except Exception as exc:
                                    if attempt >= 2:
                                        errors.append(
                                            f"pinterest_api_request_failed_{active_scope}:{type(exc).__name__}: {exc}"
                                        )
                                        break
                                    await asyncio.sleep(0.6 * (attempt + 1))
                            if response is None:
                                break
                            if response.status_code >= 400:
                                errors.append(
                                    f"pinterest_api_http_{response.status_code}_{active_scope}: {response.text[:240]}"
                                )
                                break
                            payload = response.json()
                            if cache_path:
                                cache_path.parent.mkdir(parents=True, exist_ok=True)
                                cache_path.write_text(json.dumps(payload), encoding="utf-8")
                    except Exception as exc:
                        errors.append(f"pinterest_api_request_failed_{active_scope}:{type(exc).__name__}: {exc}")
                        break

                    resource_response = payload.get("resource_response", {})
                    if resource_response.get("status") not in {None, "success"}:
                        errors.append(f"pinterest_api_status_{active_scope}_{resource_response.get('status')}")
                    results = resource_response.get("data", {}).get("results", []) or []
                    for raw in results:
                        if len(candidates) >= max_candidates:
                            break
                        if scope_candidates >= scope_limit:
                            break
                        pin_id = str(raw.get("id") or "")
                        if pin_id and pin_id in seen_pin_ids:
                            continue
                        candidate = _pinterest_candidate_from_raw(
                            index=len(candidates) + 1,
                            query=query,
                            item=raw,
                            api_scope=active_scope,
                        )
                        if candidate and candidate.media_url:
                            candidates.append(candidate)
                            scope_candidates += 1
                            if pin_id:
                                seen_pin_ids.add(pin_id)
                    bookmark = resource_response.get("bookmark")
                    if (
                        len(candidates) >= max_candidates
                        or scope_candidates >= scope_limit
                        or not bookmark
                        or bookmark == "-end-"
                    ):
                        break
                if len(candidates) >= max_candidates:
                    break

        if candidates and context is not None:
            try:
                await _render_api_contact_sheet(
                    context=context,
                    provider="pinterest",
                    candidates=candidates,
                    screenshot_path=screenshot_path,
                )
            except Exception as exc:
                errors.append(f"contact_sheet_failed:{type(exc).__name__}: {exc}")

        return MediaSearchResult(
            provider=self.provider,
            query=query,
            candidates=candidates,
            screenshot_path=str(screenshot_path),
            errors=errors,
            metadata={
                "transport": "api",
                "scope": self.scope,
                "requested_scopes": scopes,
                "url": endpoint,
                "pages_requested": page_budget,
                "api_cache_hits": api_cache_hits,
            },
        )


def connector_for_provider(
    provider: str,
    *,
    giphy_mode: str = "auto",
    pinterest_mode: str = "auto",
    pinterest_request_dump_path: str = "",
    pinterest_api_scope: str = "auto",
    pinterest_cache_api_responses: bool = True,
    giphy_api_scope: str = "auto",
    giphy_api_key_source: str = "env",
    giphy_web_key_cache_path: str | Path = "outputs/cache/giphy_web_api_key.json",
    pinterest_cache_dir: Path | None = None,
    giphy_rating: str = "pg",
    giphy_lang: str = "en",
    giphy_bundle: str = "",
    giphy_download_assets: bool = True,
    giphy_download_concurrency: int = 8,
    giphy_cache_api_responses: bool = True,
    giphy_asset_dir: Path | None = None,
    brightdata_zone: str = "",
    brightdata_size: str = "large",
    brightdata_cache_api_responses: bool = True,
    brightdata_cache_dir: Path | None = None,
    serper_gl: str = "us",
    serper_hl: str = "en",
    serper_cache_api_responses: bool = True,
    serper_cache_dir: Path | None = None,
) -> PlaywrightMediaConnector:
    if provider == "giphy":
        mode = (giphy_mode or "auto").lower()
        if mode == "playwright" or (mode == "auto" and not os.getenv("GIPHY_API_KEY")):
            return GiphyPlaywrightConnector()
        return GiphyApiConnector(
            scope=giphy_api_scope,
            api_key_source=giphy_api_key_source,
            web_key_cache_path=giphy_web_key_cache_path,
            rating=giphy_rating,
            lang=giphy_lang,
            bundle=giphy_bundle,
            download_assets=giphy_download_assets,
            download_concurrency=giphy_download_concurrency,
            cache_api_responses=giphy_cache_api_responses,
            asset_dir=giphy_asset_dir,
        )
    if provider == "giphy_playwright":
        return GiphyPlaywrightConnector()
    if provider == "giphy_api":
        return GiphyApiConnector(
            scope=giphy_api_scope,
            api_key_source=giphy_api_key_source,
            web_key_cache_path=giphy_web_key_cache_path,
            rating=giphy_rating,
            lang=giphy_lang,
            bundle=giphy_bundle,
            download_assets=giphy_download_assets,
            download_concurrency=giphy_download_concurrency,
            cache_api_responses=giphy_cache_api_responses,
            asset_dir=giphy_asset_dir,
        )
    if provider == "google_images":
        return GoogleImagesPlaywrightConnector()
    if provider in {"serper_images", "serper", "serper_dev_images", "serp_dev_images"}:
        return SerperDevImagesConnector(
            gl=serper_gl,
            hl=serper_hl,
            cache_api_responses=serper_cache_api_responses,
            cache_dir=serper_cache_dir,
        )
    if provider in {"wikimedia_commons", "commons_images", "wikimedia"}:
        return WikimediaCommonsImagesConnector(
            cache_api_responses=serper_cache_api_responses,
            cache_dir=serper_cache_dir,
        )
    if provider in {"brightdata_google_images", "brightdata", "brightdata_google"}:
        return BrightDataGoogleImagesConnector(
            zone=brightdata_zone,
            size=brightdata_size,
            cache_api_responses=brightdata_cache_api_responses,
            cache_dir=brightdata_cache_dir,
        )
    if provider == "pinterest":
        mode = (pinterest_mode or "auto").lower()
        dump_value = str(pinterest_request_dump_path or os.getenv("PINTEREST_REQUEST_DUMP_PATH", "") or "")
        dump_path = Path(dump_value) if dump_value else None
        if mode == "api" or (mode == "auto" and dump_path is not None and dump_path.exists()):
            return PinterestApiConnector(
                request_dump_path=dump_path,
                scope=pinterest_api_scope,
                cache_api_responses=pinterest_cache_api_responses,
                cache_dir=pinterest_cache_dir,
            )
        return PinterestPlaywrightConnector(scope=pinterest_api_scope)
    if provider == "pinterest_api":
        return PinterestApiConnector(
            request_dump_path=pinterest_request_dump_path,
            scope=pinterest_api_scope,
            cache_api_responses=pinterest_cache_api_responses,
            cache_dir=pinterest_cache_dir,
        )
    if provider == "pinterest_playwright":
        return PinterestPlaywrightConnector(scope=pinterest_api_scope)
    raise ValueError(f"Unsupported media provider: {provider}")


async def _accept_common_dialogs(page: Any) -> None:
    labels = [
        "Accept all",
        "I agree",
        "Agree",
        "Accept",
        "Reject all",
        "Not now",
        "Maybe later",
        "Continue",
    ]
    for label in labels:
        try:
            button = page.get_by_text(label, exact=True).first
            if await button.count():
                await button.click(timeout=900)
                await page.wait_for_timeout(300)
                return
        except Exception:
            continue


async def _gentle_scroll(page: Any, *, steps: int = 2) -> None:
    for _ in range(max(0, steps)):
        try:
            await page.mouse.wheel(0, 700)
            await page.wait_for_timeout(650)
        except Exception:
            return


async def _looks_blocked_or_captcha(page: Any) -> bool:
    try:
        text = (await page.locator("body").inner_text(timeout=1000)).lower()
    except Exception:
        return False
    markers = [
        "unusual traffic",
        "recaptcha",
        "i'm not a robot",
        "я не робот",
        "verify you are human",
        "detected unusual traffic",
    ]
    return any(marker in text for marker in markers)


def _candidate_from_raw(provider: str, query: str, item: dict[str, Any]) -> MediaCandidate:
    return MediaCandidate(
        candidate_id=str(item.get("candidate_id", "")),
        provider=provider,
        query=query,
        title=str(item.get("title", ""))[:500],
        page_url=str(item.get("page_url", "")),
        thumbnail_url=str(item.get("thumbnail_url", "")),
        media_url=str(item.get("media_url", "")),
        width=_int_or_none(item.get("width")),
        height=_int_or_none(item.get("height")),
        position=int(item.get("position") or 0),
        metadata={
            "source_tag": item.get("source_tag"),
            "rect": item.get("rect"),
        },
    )


def _pinterest_base_search_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    resource_response = payload.get("resource_response") if isinstance(payload, dict) else {}
    data = resource_response.get("data") if isinstance(resource_response, dict) else {}
    if isinstance(data, dict):
        results = data.get("results") or []
    elif isinstance(data, list):
        results = data
    else:
        results = []
    return [item for item in results if isinstance(item, dict)]


def _merge_and_renumber_candidates(
    primary: list[MediaCandidate],
    secondary: list[MediaCandidate],
    *,
    prefix: str,
    limit: int,
) -> list[MediaCandidate]:
    merged: list[MediaCandidate] = []
    seen: set[str] = set()
    for candidate in [*primary, *secondary]:
        dedupe_key = candidate.media_url or candidate.page_url or candidate.thumbnail_url
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        merged.append(
            replace(
                candidate,
                candidate_id=f"{prefix}{len(merged) + 1:02d}",
                position=len(merged) + 1,
            )
        )
        if len(merged) >= limit:
            break
    return merged


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _giphy_query(query: str) -> str:
    cleaned = _clean_query(query)
    if len(cleaned) <= 50:
        return cleaned
    words: list[str] = []
    for word in cleaned.split():
        candidate = " ".join([*words, word]).strip()
        if len(candidate) > 50:
            break
        words.append(word)
    return " ".join(words) or cleaned[:50]


def _read_giphy_web_api_key_cache(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    api_key = str(payload.get("api_key") or "")
    return api_key if _looks_like_giphy_api_key(api_key) else ""


def _write_giphy_web_api_key_cache(path: Path, api_key: str) -> None:
    if not _looks_like_giphy_api_key(api_key):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "api_key": api_key,
        "fetched_at_unix": int(time.time()),
        "source": "giphy_web_network",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def _discover_giphy_web_api_key(context: Any) -> str:
    keys: list[str] = []
    page = await context.new_page()

    def capture(url: str) -> None:
        key = _extract_giphy_api_key_from_url(url)
        if key and key not in keys:
            keys.append(key)

    page.on("request", lambda request: capture(request.url))
    page.on("response", lambda response: capture(response.url))
    try:
        await page.goto("https://giphy.com/search/funny-cat", wait_until="domcontentloaded", timeout=35_000)
        deadline = time.monotonic() + 8
        while not keys and time.monotonic() < deadline:
            await page.wait_for_timeout(250)
        if not keys:
            await page.mouse.wheel(0, 900)
            await page.wait_for_timeout(1500)
    finally:
        await page.close()
    return keys[0] if keys else ""


def _extract_giphy_api_key_from_url(url: str) -> str:
    if "api.giphy.com/v1/" not in url:
        return ""
    try:
        values = parse_qs(urlparse(url).query).get("api_key") or []
    except Exception:
        values = []
    for value in values:
        if _looks_like_giphy_api_key(value):
            return value
    return ""


def _looks_like_giphy_api_key(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{20,80}", value or ""))


def _giphy_api_scopes(scope: str) -> list[str]:
    normalized = (scope or "auto").strip().lower()
    aliases = {
        "gif": "gifs",
        "image": "gifs",
        "images": "gifs",
        "sticker": "gifs",
        "stickers": "gifs",
        "clip": "clips",
        "video": "clips",
        "videos": "clips",
    }
    if normalized in {"all", "both", "mixed"}:
        return ["gifs", "clips"]
    if normalized == "auto":
        return ["gifs"]
    parts = [part.strip() for part in re.split(r"[,;+]", normalized) if part.strip()]
    scopes: list[str] = []
    for part in parts or [normalized]:
        mapped = aliases.get(part, part)
        if mapped in {"gifs", "clips"} and mapped not in scopes:
            scopes.append(mapped)
    return scopes or ["gifs"]


def _giphy_candidate_from_raw(
    *,
    index: int,
    query: str,
    item: dict[str, Any],
    api_scope: str = "gifs",
) -> MediaCandidate:
    images = item.get("images") or {}
    video_rendition = _giphy_best_clip_video(item.get("video") or {}) if api_scope == "clips" else {}
    media_rendition = (
        video_rendition
        or _first_rendition(
            images,
            ["original", "downsized_medium", "downsized", "fixed_width", "fixed_height"],
        )
    )
    fallback_gif_rendition = _first_rendition(
        images,
        ["original", "downsized_medium", "downsized", "fixed_width", "fixed_height"],
    )
    thumb_rendition = _first_rendition(
        images,
        ["preview_gif", "fixed_width_small", "downsized_still", "original_still", "fixed_width_still"],
    )
    media_url = str(media_rendition.get("mp4") or media_rendition.get("url") or "")
    thumbnail_url = str(thumb_rendition.get("url") or media_url)
    fallback_gif_url = str(fallback_gif_rendition.get("url") or "")
    title = str(item.get("title") or item.get("alt_text") or item.get("slug") or "")[:500]
    return MediaCandidate(
        candidate_id=f"G{index:02d}",
        provider="giphy",
        query=query,
        title=title,
        page_url=str(item.get("url") or ""),
        thumbnail_url=thumbnail_url,
        media_url=media_url,
        width=_int_or_none(media_rendition.get("width")),
        height=_int_or_none(media_rendition.get("height")),
        position=index,
        metadata={
            "transport": "api",
            "api_scope": api_scope,
            "giphy_id": item.get("id"),
            "slug": item.get("slug"),
            "rating": item.get("rating"),
            "username": item.get("username"),
            "source": item.get("source"),
            "import_datetime": item.get("import_datetime"),
            "clip_duration": (item.get("video") or {}).get("duration"),
            "media_rendition_key": media_rendition.get("key") or "",
            "media_rendition_format": "mp4" if urlparse(media_url).path.lower().endswith(".mp4") else "gif",
            "fallback_gif_url": fallback_gif_url if fallback_gif_url != media_url else "",
        },
    )


def _giphy_best_clip_video(video: dict[str, Any]) -> dict[str, Any]:
    assets = video.get("assets") if isinstance(video.get("assets"), dict) else {}
    best: dict[str, Any] = {}
    best_score = -1
    for key, value in assets.items():
        if not isinstance(value, dict) or not value.get("url"):
            continue
        width = _int_or_none(value.get("width")) or 0
        height = _int_or_none(value.get("height")) or 0
        score = width * height
        if key == "source":
            score += 1_000_000_000
        if score > best_score:
            best = {**value, "key": key}
            best_score = score
    return best


def _first_rendition(images: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    for key in keys:
        value = images.get(key)
        if isinstance(value, dict) and value.get("url"):
            return {**value, "key": key}
    return {}


def _pinterest_api_headers(dump: dict[str, Any]) -> dict[str, str]:
    headers = {
        str(key).lower(): str(value)
        for key, value in (dump.get("headers") or {}).items()
        if value is not None and not str(key).startswith(":")
    }
    for key in ("content-length", "accept-encoding"):
        headers.pop(key, None)
    # Avoid zstd/br response bodies in environments without optional decoders.
    headers["accept-encoding"] = "gzip, deflate"
    headers.setdefault("accept", "application/json, text/javascript, */*, q=0.01")
    headers.setdefault("origin", "https://ru.pinterest.com")
    headers.setdefault("referer", "https://ru.pinterest.com/")
    return headers


def _pinterest_api_headers_for_post(
    headers: dict[str, str],
    *,
    endpoint: str,
    source_url: str,
) -> dict[str, str]:
    request_headers = dict(headers)
    endpoint_parts = urlparse(endpoint)
    if endpoint_parts.scheme and endpoint_parts.netloc:
        origin = f"{endpoint_parts.scheme}://{endpoint_parts.netloc}"
        request_headers["origin"] = origin
        request_headers["referer"] = f"{origin}{source_url}"
    request_headers["x-pinterest-source-url"] = source_url
    csrf_token = _cookie_header_value(request_headers.get("cookie", ""), "csrftoken")
    if csrf_token:
        request_headers["x-csrftoken"] = csrf_token
    return request_headers


def _cookie_header_value(cookie_header: str, name: str) -> str:
    for part in str(cookie_header or "").split(";"):
        key, separator, value = part.strip().partition("=")
        if separator and key == name:
            return value
    return ""


def _pinterest_api_scopes(scope: str) -> list[str]:
    normalized = (scope or "auto").strip().lower()
    if normalized in {"all", "both", "mixed"}:
        return ["videos", "pins"]
    if normalized in {"pin", "pins", "image", "images", "photo", "photos"}:
        return ["pins"]
    if normalized in {"video", "videos", "gif", "motion"}:
        return ["videos"]
    return ["videos", "pins"]


def _pinterest_api_post_data(
    *,
    query: str,
    scope: str,
    page_size: int,
    bookmark: str | None = None,
) -> dict[str, str]:
    source_url = f"/search/{scope}/?q={query}&rs=typed"
    options: dict[str, Any] = {
        "query": query,
        "scope": scope,
        "rs": "typed",
        "redux_normalize_feed": True,
        "page_size": page_size,
        "auto_correction_disabled": False,
        "source_url": source_url,
    }
    if bookmark:
        options["bookmarks"] = [bookmark]
    return {
        "source_url": source_url,
        "data": json.dumps({"options": options, "context": {}}, separators=(",", ":")),
    }


def _pinterest_candidate_from_raw(
    *,
    index: int,
    query: str,
    item: dict[str, Any],
    api_scope: str = "",
) -> MediaCandidate | None:
    if item.get("type") != "pin":
        return None
    pin_id = str(item.get("id") or "")
    images = item.get("images") or {}
    image = _pinterest_best_image(images)
    video = _pinterest_best_video((item.get("videos") or {}).get("video_list") or {})
    prefer_video = api_scope in {"video", "videos", "gif", "motion"} and bool(video.get("url"))
    media_url = str(video.get("url") if prefer_video else image.get("url") or "")
    if not media_url:
        media_url = str(video.get("url") or image.get("url") or "")
    if not pin_id or not media_url:
        return None
    width_source = video if prefer_video and video else image
    height_source = video if prefer_video and video else image
    title = str(item.get("grid_title") or item.get("title") or item.get("description") or "")[:500]
    return MediaCandidate(
        candidate_id=f"P{index:02d}",
        provider="pinterest",
        query=query,
        title=title,
        page_url=f"https://www.pinterest.com/pin/{pin_id}/",
        thumbnail_url=str(image.get("url") or media_url),
        media_url=media_url,
        width=_int_or_none(width_source.get("width")),
        height=_int_or_none(height_source.get("height")),
        position=index,
        metadata={
            "transport": "api",
            "api_scope": api_scope,
            "pin_id": pin_id,
            "dominant_color": item.get("dominant_color"),
            "video_hls_url": video.get("url") or "",
            "video_width": video.get("width"),
            "video_height": video.get("height"),
            "image_key": image.get("key") or "",
            "available_image_keys": sorted(str(key) for key in images.keys()),
            "domain": item.get("domain"),
            "link": item.get("link"),
        },
    )


def _pinterest_best_image(images: dict[str, Any]) -> dict[str, Any]:
    best: dict[str, Any] = {}
    best_score = -1
    for key in ("orig", "originals", "736x", "564x", "474x", "236x", "170x"):
        value = images.get(key)
        if not isinstance(value, dict) or not value.get("url"):
            continue
        width = _int_or_none(value.get("width")) or 0
        height = _int_or_none(value.get("height")) or 0
        score = width * height
        if key in {"orig", "originals"}:
            score += 1_000_000_000
        if score > best_score:
            best = {**value, "key": key}
            best_score = score
    return best


def _pinterest_best_video(video_list: dict[str, Any]) -> dict[str, Any]:
    best: dict[str, Any] = {}
    best_score = -1
    for key, value in video_list.items():
        if not isinstance(value, dict) or not value.get("url"):
            continue
        width = _int_or_none(value.get("width")) or 0
        height = _int_or_none(value.get("height")) or 0
        score = width * height
        if "HLS" in str(key).upper():
            score += 1
        if score > best_score:
            best = {**value, "key": key}
            best_score = score
    return best


def _pinterest_api_cache_path(root: Path, post_data: dict[str, str], scope: str, page_index: int) -> Path:
    digest = hashlib.sha1(json.dumps(post_data, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    return root / "_api_cache" / f"pinterest_{_clean_query(scope)}_{page_index:02d}_{digest}.json"


def _brightdata_google_candidate_from_raw(
    *,
    index: int,
    query: str,
    item: dict[str, Any],
) -> MediaCandidate | None:
    media_url = str(
        item.get("original_image")
        or item.get("image")
        or item.get("image_url")
        or item.get("url")
        or ""
    )
    if not media_url:
        return None
    thumbnail_url = str(item.get("thumbnail") or item.get("thumbnail_url") or item.get("image") or media_url)
    rank = _int_or_none(item.get("global_rank") or item.get("rank") or item.get("position")) or index
    width = _int_or_none(item.get("original_width") or item.get("width"))
    height = _int_or_none(item.get("original_height") or item.get("height"))
    return MediaCandidate(
        candidate_id=f"B{index:02d}",
        provider="brightdata_google_images",
        query=query,
        title=str(item.get("title") or item.get("alt") or item.get("description") or "")[:500],
        page_url=str(item.get("link") or item.get("source") or item.get("source_url") or ""),
        thumbnail_url=thumbnail_url,
        media_url=media_url,
        width=width,
        height=height,
        position=rank,
        metadata={
            "transport": "brightdata_request",
            "global_rank": item.get("global_rank"),
            "source": item.get("source"),
            "domain": item.get("domain"),
            "original_width": item.get("original_width"),
            "original_height": item.get("original_height"),
        },
    )


def _serper_image_candidate_from_raw(
    *,
    index: int,
    query: str,
    item: dict[str, Any],
) -> MediaCandidate | None:
    media_url = str(item.get("imageUrl") or item.get("image_url") or item.get("url") or "")
    if not media_url:
        return None
    thumbnail_url = str(item.get("thumbnailUrl") or item.get("thumbnail_url") or item.get("thumbnail") or media_url)
    rank = _int_or_none(item.get("position")) or index
    return MediaCandidate(
        candidate_id=f"S{index:02d}",
        provider="serper_images",
        query=query,
        title=str(item.get("title") or "")[:500],
        page_url=str(item.get("link") or item.get("googleUrl") or ""),
        thumbnail_url=thumbnail_url,
        media_url=media_url,
        width=_int_or_none(item.get("imageWidth") or item.get("image_width") or item.get("width")),
        height=_int_or_none(item.get("imageHeight") or item.get("image_height") or item.get("height")),
        position=rank,
        metadata={
            "transport": "serper_dev",
            "source": item.get("source"),
            "domain": item.get("domain"),
            "google_url": item.get("googleUrl"),
            "thumbnail_width": item.get("thumbnailWidth"),
            "thumbnail_height": item.get("thumbnailHeight"),
        },
    )


def _wikimedia_commons_candidate_from_raw(
    *,
    index: int,
    query: str,
    item: dict[str, Any],
) -> MediaCandidate | None:
    imageinfo = item.get("imageinfo") if isinstance(item.get("imageinfo"), list) else []
    info = imageinfo[0] if imageinfo and isinstance(imageinfo[0], dict) else {}
    mime = str(info.get("mime") or "").lower()
    if mime and mime not in {"image/jpeg", "image/png", "image/webp"}:
        return None
    media_url = str(info.get("thumburl") or info.get("url") or "")
    if not media_url:
        return None
    title = str(item.get("title") or "").replace("File:", "").strip()
    extmetadata = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}
    description = _wikimedia_extmetadata_text(extmetadata, "ImageDescription")
    object_name = _wikimedia_extmetadata_text(extmetadata, "ObjectName")
    license_short_name = _wikimedia_extmetadata_text(extmetadata, "LicenseShortName")
    page_url = str(info.get("descriptionurl") or "")
    width = _int_or_none(info.get("thumbwidth") or info.get("width"))
    height = _int_or_none(info.get("thumbheight") or info.get("height"))
    return MediaCandidate(
        candidate_id=f"W{index:02d}",
        provider="wikimedia_commons",
        query=query,
        title=(object_name or title or description)[:500],
        page_url=page_url,
        thumbnail_url=media_url,
        media_url=media_url,
        width=width,
        height=height,
        position=index,
        metadata={
            "transport": "mediawiki_api",
            "mime": mime,
            "original_url": info.get("url"),
            "original_width": info.get("width"),
            "original_height": info.get("height"),
            "license": license_short_name,
            "description": description[:500],
            "source_url": page_url,
        },
    )


def _wikimedia_search_query(query: str) -> str:
    clean = " ".join(str(query or "").split())
    tokens = [
        token
        for token in re.findall(r"[a-z][a-z0-9]+", clean.lower())
        if token not in _WIKIMEDIA_QUERY_STOPWORDS and len(token) >= 3
    ]
    simplified = " ".join(tokens[:5])
    search = simplified or clean
    return f"{search} -incategory:SVG" if search else "-incategory:SVG"


_WIKIMEDIA_QUERY_STOPWORDS = {
    "aesthetic",
    "and",
    "background",
    "broll",
    "casual",
    "clean",
    "closeup",
    "footage",
    "girl",
    "girls",
    "holding",
    "huge",
    "lifestyle",
    "minimalist",
    "morning",
    "the",
    "with",
    "person",
    "photo",
    "soft",
    "stock",
    "thin",
    "vertical",
    "video",
    "walking",
    "woman",
    "women",
}


def _wikimedia_user_agent() -> str:
    return (
        os.getenv("REDDIT2VIDEO_HTTP_USER_AGENT")
        or "reddit2video-girly-static-v5-flow/1.0 (https://github.com/openai/codex; local media resolver)"
    )


def _wikimedia_extmetadata_text(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, dict):
        return ""
    text = str(value.get("value") or "").strip()
    return re.sub(r"<[^>]+>", " ", html.unescape(text)).strip()


def _brightdata_google_cache_path(root: Path, payload: dict[str, Any], size: str) -> Path:
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    return root / "_api_cache" / f"brightdata_google_{_clean_query(size)}_{digest}.json"


def _serper_images_cache_path(root: Path, payload: dict[str, Any]) -> Path:
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    return root / "_api_cache" / f"serper_images_{digest}.json"


def _wikimedia_commons_cache_path(root: Path, params: dict[str, Any]) -> Path:
    digest = hashlib.sha1(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    return root / "_api_cache" / f"wikimedia_commons_{digest}.json"


def _brightdata_authorization_header(api_key: str) -> str:
    token = str(api_key or "").strip()
    if re.match(r"^(bearer|basic)\s+", token, flags=re.IGNORECASE):
        return token
    return f"Bearer {token}"


async def _render_api_contact_sheet(
    *,
    context: Any,
    provider: str,
    candidates: list[MediaCandidate],
    screenshot_path: Path,
) -> None:
    await _render_candidate_contact_sheet(
        context=context,
        provider=provider,
        candidates=candidates,
        screenshot_path=screenshot_path,
    )


async def render_candidate_contact_sheets(
    *,
    context: Any,
    provider: str,
    candidates: list[MediaCandidate],
    screenshot_root: Path,
    stem: str,
    sheet_size: int = 10,
) -> list[str]:
    if not candidates:
        return []
    screenshot_root.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    size = max(1, sheet_size)
    for sheet_index, start in enumerate(range(0, len(candidates), size), start=1):
        chunk = candidates[start : start + size]
        screenshot_path = screenshot_root / f"{stem}_sheet_{sheet_index:02d}.png"
        await _render_candidate_contact_sheet(
            context=context,
            provider=provider,
            candidates=chunk,
            screenshot_path=screenshot_path,
            sheet_index=sheet_index,
            total_sheets=(len(candidates) + size - 1) // size,
        )
        paths.append(str(screenshot_path))
    return paths


async def _render_candidate_contact_sheet(
    *,
    context: Any,
    provider: str,
    candidates: list[MediaCandidate],
    screenshot_path: Path,
    sheet_index: int = 1,
    total_sheets: int = 1,
) -> None:
    page = await context.new_page()
    try:
        await page.set_viewport_size({"width": 1365, "height": 1600})
        await page.set_content(
            _contact_sheet_html(
                provider=provider,
                candidates=candidates,
                sheet_index=sheet_index,
                total_sheets=total_sheets,
            ),
            wait_until="domcontentloaded",
        )
        try:
            await page.wait_for_load_state("networkidle", timeout=7000)
        except Exception:
            pass
        await page.evaluate(
            """
            async () => {
              const videos = Array.from(document.querySelectorAll('video'));
              await Promise.all(videos.map((video) => new Promise((resolve) => {
                const finish = () => resolve(null);
                const setMidpoint = () => {
                  try {
                    if (Number.isFinite(video.duration) && video.duration > 0) {
                      video.currentTime = Math.max(0, Math.min(video.duration - 0.05, video.duration * 0.5));
                    }
                  } catch (err) {}
                  window.setTimeout(finish, 450);
                };
                if (video.readyState >= 1) {
                  setMidpoint();
                } else {
                  video.addEventListener('loadedmetadata', setMidpoint, {once: true});
                  window.setTimeout(finish, 1800);
                }
              })));
            }
            """
        )
        await page.wait_for_timeout(900)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(screenshot_path), full_page=False)
    finally:
        await page.close()


def _contact_sheet_html(
    *,
    provider: str,
    candidates: list[MediaCandidate],
    sheet_index: int = 1,
    total_sheets: int = 1,
) -> str:
    cards: list[str] = []
    for candidate in candidates:
        title = html.escape(candidate.title or candidate.page_url or candidate.media_url)
        candidate_id = html.escape(candidate.candidate_id)
        source = html.escape(candidate.provider)
        media_html = _contact_sheet_media_html(candidate, title)
        motion_meta = _contact_sheet_motion_metadata(candidate)
        motion_html = f'<div class="motion">{html.escape(motion_meta)}</div>' if motion_meta else ""
        quality_meta = _contact_sheet_quality_metadata(candidate)
        quality_html = f'<div class="quality">{html.escape(quality_meta)}</div>' if quality_meta else ""
        cards.append(
            f"""
            <article class="card">
              <div class="label">{candidate_id}</div>
              {media_html}
              <div class="source">{source}</div>
              {motion_html}
              {quality_html}
              <div class="title">{title}</div>
            </article>
            """
        )
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <style>
          * {{ box-sizing: border-box; }}
          body {{
            margin: 0;
            padding: 24px;
            background: #f7f8fb;
            color: #17171f;
            font-family: Arial, sans-serif;
          }}
          .header {{
            font-size: 28px;
            font-weight: 800;
            margin-bottom: 18px;
          }}
          .grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 18px;
          }}
          .card {{
            position: relative;
            min-height: 300px;
            padding: 12px;
            border: 2px solid #d7d9e8;
            border-radius: 16px;
            background: white;
            overflow: hidden;
          }}
          .label {{
            position: absolute;
            z-index: 2;
            top: 16px;
            left: 16px;
            padding: 7px 11px;
            border-radius: 999px;
            background: #ff2d8d;
            color: white;
            border: 2px solid white;
            font-size: 18px;
            font-weight: 900;
            box-shadow: 0 4px 18px rgba(0,0,0,.28);
          }}
          img, video {{
            width: 100%;
            height: 218px;
            display: block;
            object-fit: cover;
            border-radius: 10px;
            background: #eef0f6;
          }}
          .title {{
            margin-top: 6px;
            font-size: 15px;
            line-height: 1.25;
            max-height: 38px;
            overflow: hidden;
          }}
          .source {{
            margin-top: 8px;
            color: #676879;
            font-size: 12px;
            font-weight: 800;
            letter-spacing: .04em;
            text-transform: uppercase;
          }}
          .motion {{
            margin-top: 5px;
            color: #0b6b59;
            font-size: 12px;
            line-height: 1.2;
            font-weight: 800;
          }}
          .quality {{
            margin-top: 5px;
            color: #7b3150;
            font-size: 12px;
            line-height: 1.2;
            font-weight: 800;
          }}
        </style>
      </head>
      <body>
        <div class="header">{html.escape(provider)} candidates · sheet {sheet_index}/{total_sheets}</div>
        <main class="grid">
          {''.join(cards)}
        </main>
      </body>
    </html>
    """


def _contact_sheet_media_html(candidate: MediaCandidate, title: str) -> str:
    image_url = html.escape(_candidate_display_image_url(candidate))
    video_url = html.escape(_candidate_display_video_url(candidate))
    if video_url:
        return (
            f'<video src="{video_url}" poster="{image_url}" '
            f'aria-label="{title}" autoplay muted loop playsinline></video>'
        )
    return f'<img src="{image_url}" alt="{title}" />'


def _candidate_display_video_url(candidate: MediaCandidate) -> str:
    metadata = candidate.metadata or {}
    local_media = metadata.get("local_media_path")
    if isinstance(local_media, str) and _video_url_suffix(local_media) in {".mp4", ".webm", ".mov"}:
        path = Path(local_media)
        if path.exists():
            return path.resolve().as_uri()
    media_url = candidate.media_url or ""
    if _video_url_suffix(media_url) in {".mp4", ".webm", ".mov"}:
        return media_url
    return ""


def _contact_sheet_motion_metadata(candidate: MediaCandidate) -> str:
    metadata = candidate.metadata or {}
    markers: list[str] = []
    suffix = _video_url_suffix(candidate.media_url or candidate.thumbnail_url)
    if suffix in {".gif", ".mp4", ".webm", ".mov", ".m3u8", ".webp"}:
        markers.append(f"media:{suffix[1:]}")
    if metadata.get("video_hls_url"):
        markers.append("hls")
    if metadata.get("clip_duration"):
        markers.append(f"duration:{metadata.get('clip_duration')}s")
    if metadata.get("media_rendition_format"):
        markers.append(f"rendition:{metadata.get('media_rendition_format')}")
    if metadata.get("api_scope"):
        markers.append(f"scope:{metadata.get('api_scope')}")
    return "motion " + " / ".join(markers) if markers else ""


def _contact_sheet_quality_metadata(candidate: MediaCandidate) -> str:
    metadata = candidate.metadata or {}
    width = metadata.get("video_width") or candidate.width
    height = metadata.get("video_height") or candidate.height
    markers: list[str] = []
    if width and height:
        markers.append(f"{width}x{height}")
        try:
            min_side = min(int(width), int(height))
            if min_side < 720:
                markers.append("LOW<720")
        except (TypeError, ValueError):
            pass
    image_key = str(metadata.get("image_key") or "")
    if image_key:
        markers.append(f"image:{image_key}")
    if "/736x/" in str(candidate.media_url or candidate.thumbnail_url).lower():
        markers.append("resized-736x")
    if any(part in str(candidate.media_url or candidate.thumbnail_url).lower() for part in ("/236x/", "/170x/", "/136x/", "/60x60/")):
        markers.append("thumbnail")
    return "quality " + " / ".join(markers) if markers else ""


def _video_url_suffix(url: str) -> str:
    return Path(urlparse(str(url or "").split("?", 1)[0]).path).suffix.lower()


def provider_hint_for_slot(slot: dict[str, Any], configured_providers: list[str]) -> list[str]:
    providers = list(configured_providers)
    if _slot_allows_giphy(slot):
        giphy_providers = _providers_by_family(providers, "giphy")
        return _prefer_providers(giphy_providers, ["giphy", "giphy_api", "giphy_playwright"]) if giphy_providers else []

    non_giphy = [provider for provider in providers if _provider_family(provider) != "giphy"]
    if _slot_prefers_motion_search(slot):
        pinterest_providers = _providers_by_family(non_giphy, "pinterest")
        return _prefer_providers(pinterest_providers, ["pinterest", "pinterest_api", "pinterest_playwright"])

    if _slot_prefers_exact_image_search(slot):
        exact_providers = _providers_by_family(non_giphy, "google_images")
        if exact_providers:
            return _prefer_providers(
                non_giphy,
                [
                    "serper_images",
                    "serper",
                    "serper_dev_images",
                    "serp_dev_images",
                    "wikimedia_commons",
                    "commons_images",
                    "wikimedia",
                    "brightdata_google_images",
                    "brightdata",
                    "brightdata_google",
                    "google_images",
                    "pinterest",
                    "pinterest_api",
                    "pinterest_playwright",
                ],
            )

    return _prefer_providers(non_giphy, ["pinterest", "pinterest_api", "pinterest_playwright"])


def _prefer_providers(providers: list[str], preferred: list[str]) -> list[str]:
    return [provider for provider in preferred if provider in providers] + [
        provider for provider in providers if provider not in preferred
    ]


def _providers_by_family(providers: list[str], family: str) -> list[str]:
    return [provider for provider in providers if _provider_family(provider) == family]


def _provider_family(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized.startswith("giphy"):
        return "giphy"
    if normalized.startswith("pinterest"):
        return "pinterest"
    if normalized in {
        "google_images",
        "serper_images",
        "serper",
        "serper_dev_images",
        "serp_dev_images",
        "wikimedia_commons",
        "commons_images",
        "wikimedia",
        "brightdata_google_images",
        "brightdata",
        "brightdata_google",
    }:
        return "google_images"
    return normalized


def _slot_prefers_motion_search(slot: dict[str, Any]) -> bool:
    role = str(slot.get("role") or "").lower()
    return role == "background_texture"


def _slot_prefers_exact_image_search(slot: dict[str, Any]) -> bool:
    kind = str(slot.get("kind") or "").lower()
    role = str(slot.get("role") or "").lower()
    strategy = str(slot.get("source_strategy") or "").lower()
    if kind != "image" or role == "background_texture":
        return False
    if strategy in {"pinterest", "pinterest_search"}:
        return False
    if strategy in {"google_images", "google_images_search", "web_search", "exact_search", "literal_search"}:
        return True
    return bool(slot.get("search_query_en") or slot.get("search_query_ru"))


def _slot_allows_giphy(slot: dict[str, Any]) -> bool:
    kind = str(slot.get("kind") or "").lower()
    strategy = str(slot.get("source_strategy") or "").lower()
    if kind == "gif" or strategy in {"gif_search", "giphy", "giphy_search"}:
        return True
    haystack = " ".join(
        str(slot.get(key) or "").lower().replace("_", " ")
        for key in (
            "role",
            "search_query_en",
            "search_query_ru",
            "visual_prompt",
            "asset_id",
            "motion_hint",
        )
    )
    return bool(
        re.search(
            r"(?<![a-z0-9])("
            r"meme|reaction|reacts?|reaction gif|reaction clip|"
            r"emotional reaction|comedic|comedy|funny gif|funny reaction|"
            r"funny(?:\s+[a-z0-9_-]+){1,4}"
            r")(?![a-z0-9])",
            haystack,
        )
    )


def build_slot_query(slot: dict[str, Any]) -> str:
    for key in ("search_query_en", "search_query_ru", "visual_prompt"):
        value = slot.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_query(value)
    parts = [
        str(slot.get("role") or ""),
        str(slot.get("asset_id") or ""),
        str(slot.get("kind") or ""),
    ]
    return _clean_query(" ".join(parts))


async def _download_giphy_candidate_assets(
    *,
    candidates: list[MediaCandidate],
    download_root: Path,
    concurrency: int = 8,
) -> tuple[list[MediaCandidate], list[str], dict[str, Any]]:
    download_root.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    stats = {"enabled": True, "downloaded_files": 0, "cache_hits": 0, "failed_files": 0}
    semaphore = asyncio.Semaphore(max(1, concurrency))
    proxy = os.getenv("OUTBOUND_PROXY") or None

    async with httpx.AsyncClient(timeout=45, proxy=proxy, follow_redirects=True) as client:

        async def download_one(candidate: MediaCandidate) -> MediaCandidate:
            async with semaphore:
                high_path = await _download_asset_url(
                    client=client,
                    url=candidate.media_url,
                    path=_asset_path(download_root, candidate, "highres", candidate.media_url),
                    errors=errors,
                    stats=stats,
                )
                low_path = await _download_asset_url(
                    client=client,
                    url=candidate.thumbnail_url or candidate.media_url,
                    path=_asset_path(download_root, candidate, "lowres", candidate.thumbnail_url or candidate.media_url),
                    errors=errors,
                    stats=stats,
                )
            metadata = dict(candidate.metadata)
            cache_payload = {
                "highres_url": candidate.media_url,
                "lowres_url": candidate.thumbnail_url or candidate.media_url,
                "highres_path": str(high_path) if high_path else "",
                "lowres_path": str(low_path) if low_path else "",
            }
            metadata["asset_cache"] = cache_payload
            metadata["local_media_path"] = cache_payload["highres_path"]
            metadata["local_thumbnail_path"] = cache_payload["lowres_path"]
            return replace(candidate, metadata=metadata)

        downloaded = await asyncio.gather(*(download_one(candidate) for candidate in candidates))
    return list(downloaded), errors, stats


async def _download_asset_url(
    *,
    client: httpx.AsyncClient,
    url: str,
    path: Path,
    errors: list[str],
    stats: dict[str, Any],
) -> Path | None:
    if not url:
        return None
    if path.exists() and path.stat().st_size > 0:
        stats["cache_hits"] += 1
        return path
    try:
        response = await client.get(url)
        if response.status_code >= 400:
            stats["failed_files"] += 1
            errors.append(f"asset_http_{response.status_code}:{url[:160]}")
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        stats["downloaded_files"] += 1
        return path
    except Exception as exc:
        stats["failed_files"] += 1
        errors.append(f"asset_download_failed:{type(exc).__name__}:{url[:160]}")
        return None


def _asset_path(root: Path, candidate: MediaCandidate, rendition: str, url: str) -> Path:
    giphy_id = str(candidate.metadata.get("giphy_id") or candidate.candidate_id)
    filename = f"{_safe_asset_token(giphy_id)}_{rendition}{_media_suffix(url)}"
    return root / filename


def _giphy_api_cache_path(root: Path, params: dict[str, Any]) -> Path:
    cache_params = {key: value for key, value in params.items() if key != "api_key"}
    payload = json.dumps(cache_params, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return root / "_api_cache" / f"{digest}.json"


def _candidate_display_image_url(candidate: MediaCandidate) -> str:
    local_thumbnail = (candidate.metadata or {}).get("local_thumbnail_path")
    local_media = (candidate.metadata or {}).get("local_media_path")
    for value in (local_thumbnail, local_media):
        if isinstance(value, str) and value:
            path = Path(value)
            if path.exists():
                return path.resolve().as_uri()
    return candidate.thumbnail_url or candidate.media_url


def _media_suffix(url: str) -> str:
    path = urlparse(url).path if url else ""
    suffix = Path(path).suffix.lower()
    if suffix in {".gif", ".mp4", ".webp", ".jpg", ".jpeg", ".png"}:
        return suffix
    return ".bin"


def _safe_asset_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return token[:80] or "asset"


def _clean_query(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value[:180]


_EXTRACT_MEDIA_CANDIDATES_SCRIPT = r"""
({provider, labelPrefix, query, selectors, limit}) => {
  const selector = selectors.join(',');
  const roots = Array.from(document.querySelectorAll(selector));
  const seen = new Set();
  const candidates = [];

  function absolute(url) {
    if (!url) return '';
    try { return new URL(url, location.href).toString(); } catch { return ''; }
  }

  function bestMediaUrl(el, pageUrl) {
    const img = el.matches('img, video, picture') ? el : el.querySelector('img, video, picture');
    if (!img) return {node: null, mediaUrl: '', thumbUrl: '', title: '', width: null, height: null};
    const tag = img.tagName.toLowerCase();
    let mediaUrl = '';
    let thumbUrl = '';
    let width = img.naturalWidth || img.videoWidth || img.width || null;
    let height = img.naturalHeight || img.videoHeight || img.height || null;
    function bestFromSrcset(value) {
      if (!value) return '';
      let best = {url: '', score: 0};
      for (const item of value.split(',')) {
        const parts = item.trim().split(/\s+/);
        if (!parts[0]) continue;
        let score = 1;
        if (parts[1] && parts[1].endsWith('w')) score = Number.parseInt(parts[1], 10) || score;
        if (parts[1] && parts[1].endsWith('x')) score = (Number.parseFloat(parts[1]) || 1) * 1000;
        if (score >= best.score) best = {url: parts[0], score};
      }
      return absolute(best.url);
    }
    if (tag === 'video') {
      const source = img.querySelector('source');
      mediaUrl = absolute(img.currentSrc || img.src || (source && source.src) || img.poster || '');
      thumbUrl = absolute(img.poster || mediaUrl);
    } else if (tag === 'picture') {
      const nested = img.querySelector('img');
      mediaUrl = bestFromSrcset(nested && nested.getAttribute('srcset')) ||
        absolute(nested && (nested.currentSrc || nested.src || nested.getAttribute('data-src')) || '');
      thumbUrl = mediaUrl;
      width = nested && (nested.naturalWidth || nested.width) || width;
      height = nested && (nested.naturalHeight || nested.height) || height;
    } else {
      thumbUrl = absolute(img.currentSrc || img.src || img.getAttribute('data-src') || img.getAttribute('data-iurl') || '');
      mediaUrl = bestFromSrcset(img.getAttribute('srcset')) || thumbUrl;
    }
    if (provider === 'google_images' && pageUrl) {
      try {
        const parsed = new URL(pageUrl);
        mediaUrl = parsed.searchParams.get('imgurl') || mediaUrl;
      } catch {}
    }
    const title =
      img.getAttribute('alt') ||
      img.getAttribute('aria-label') ||
      img.getAttribute('title') ||
      (img.closest('a') && img.closest('a').getAttribute('aria-label')) ||
      '';
    return {node: img, mediaUrl, thumbUrl, title, width, height};
  }

  for (const root of roots) {
    if (candidates.length >= limit) break;
    const link = root.closest('a') || root.querySelector('a') || root;
    const pageUrl = absolute(link && link.href || '');
    const {node, mediaUrl, thumbUrl, title, width, height} = bestMediaUrl(root, pageUrl);
    if (!node || !mediaUrl) continue;
    if (mediaUrl.startsWith('data:') || mediaUrl.startsWith('blob:')) continue;
    if (provider === 'giphy') {
      const lowered = `${mediaUrl} ${thumbUrl} ${title}`.toLowerCase();
      if (lowered.includes('giphy-logo') || lowered.includes('giphy logo')) continue;
    }
    const rect = node.getBoundingClientRect();
    if (rect.width < 40 || rect.height < 40) continue;
    const key = mediaUrl || pageUrl;
    if (seen.has(key)) continue;
    seen.add(key);
    const candidateId = `${labelPrefix}${String(candidates.length + 1).padStart(2, '0')}`;
    const marker = node.closest('a, [role="link"], [data-grid-item], div') || node;
    marker.dataset.r2vCandidateId = candidateId;
    node.dataset.r2vCandidateId = candidateId;
    candidates.push({
      candidate_id: candidateId,
      provider,
      query,
      title,
      page_url: pageUrl,
      thumbnail_url: thumbUrl,
      media_url: mediaUrl,
      width,
      height,
      position: candidates.length + 1,
      source_tag: node.tagName.toLowerCase(),
      rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
    });
  }
  return candidates;
}
"""


_INJECT_LABELS_SCRIPT = r"""
() => {
  document.querySelectorAll('.r2v-media-label').forEach((node) => node.remove());
  const marked = Array.from(document.querySelectorAll('[data-r2v-candidate-id]'));
  const used = new Set();
  for (const node of marked) {
    const id = node.dataset.r2vCandidateId;
    if (!id || used.has(id)) continue;
    const rect = node.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) continue;
    used.add(id);
    const label = document.createElement('div');
    label.className = 'r2v-media-label';
    label.textContent = id;
    Object.assign(label.style, {
      position: 'fixed',
      zIndex: '2147483647',
      left: `${Math.max(6, rect.left + 6)}px`,
      top: `${Math.max(6, rect.top + 6)}px`,
      padding: '5px 8px',
      borderRadius: '999px',
      background: '#ff2d8d',
      color: 'white',
      font: '700 14px/1.1 Arial, sans-serif',
      border: '2px solid white',
      boxShadow: '0 2px 10px rgba(0,0,0,.35)',
      pointerEvents: 'none'
    });
    document.body.appendChild(label);
  }
}
"""
