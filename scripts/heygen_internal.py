#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import http.cookiejar
import json
import mimetypes
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_GLOB = "local_secrets/heygen_probe/heygen-storage-state-*.json"
DEFAULT_DOWNLOAD_DIR = ROOT / "local_secrets" / "heygen_probe" / "downloads"
API_BASE = "https://api2.heygen.com"

JsonObject = dict[str, Any]


class HeyGenError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class HeyGenInternalClient:
    def __init__(self, storage_state_path: Path, *, timeout: int = 30) -> None:
        self.storage_state_path = storage_state_path
        self.timeout = timeout
        self.opener = build_opener(HTTPCookieProcessor(_cookie_jar_from_storage_state(storage_state_path)))

    def get_json(self, path_or_url: str, query: JsonObject | None = None) -> JsonObject:
        body, content_type = self.request("GET", path_or_url, query=query)
        return _decode_json(body, content_type=content_type)

    def post_json(self, path_or_url: str, payload: JsonObject) -> JsonObject:
        body, content_type = self.request("POST", path_or_url, json_payload=payload)
        return _decode_json(body, content_type=content_type)

    def request(
        self,
        method: str,
        path_or_url: str,
        *,
        query: JsonObject | None = None,
        json_payload: JsonObject | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[bytes, str]:
        url = _absolute_url(path_or_url)
        if query:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urlencode({k: v for k, v in query.items() if v is not None})}"

        request_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://app.heygen.com",
            "Referer": "https://app.heygen.com/",
        }
        if headers:
            request_headers.update(headers)

        body = data
        if json_payload is not None:
            body = json.dumps(json_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        request = Request(url, data=body, headers=request_headers, method=method.upper())
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read(), str(response.headers.get("content-type") or "")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", "replace")
            raise HeyGenError(
                f"HeyGen API returned HTTP {exc.code} for {method.upper()} {_safe_endpoint(url)}",
                status=exc.code,
                body=error_body,
            ) from exc
        except URLError as exc:
            raise HeyGenError(f"HeyGen API request failed for {method.upper()} {_safe_endpoint(url)}: {exc}") from exc

    def auth_probe(self) -> JsonObject:
        return self.get_json("/v1/user.get")

    def get_draft(self, video_id: str) -> JsonObject:
        return self.get_json("/v1/text_draft.get", {"video_id": video_id})

    def create_text_draft(self, video_output: JsonObject, *, folder_id: str = "", source_type: str = "ai_studio") -> JsonObject:
        return self.post_json(
            "/v1/text_draft.create",
            {
                "video_output": video_output,
                "folder_id": folder_id,
                "source_type": source_type,
            },
        )

    def save_text_draft(self, video_id: str, title: str, draft_with_metadata: JsonObject) -> JsonObject:
        text_draft = draft_with_metadata.get("text_draft") or {}
        metadata = draft_with_metadata.get("metadata") or {}
        return self.post_json(
            "/v1/text_draft.save",
            {
                "video_id": video_id,
                "title": title,
                "text_draft": text_draft,
                "video_output": draft_with_metadata.get("video_output") or {},
                "metadata": list(metadata.values()) if isinstance(metadata, dict) else metadata,
                "has_faceswap": _draft_has_faceswap(text_draft),
            },
        )

    def text_draft_versions(self, video_id: str) -> JsonObject:
        return self.get_json("/v1/text_draft.versions", {"video_id": video_id})

    def latest_text_draft_version_id(self, video_id: str) -> str:
        payload = self.text_draft_versions(video_id)
        versions = ((payload.get("data") or {}).get("versions") or [])
        if not versions:
            raise HeyGenError(f"text draft has no saved versions: {video_id}")
        return str(versions[0].get("id") or "")

    def clone_draft(
        self,
        template_video_id: str,
        *,
        title: str,
        audio: JsonObject | None = None,
        script_text: str | None = None,
        green_screen: bool = True,
    ) -> JsonObject:
        template_payload = self.get_draft(template_video_id)
        template_data = template_payload.get("data") or {}
        draft_with_metadata = deepcopy(template_data.get("text_draft") or {})
        if not draft_with_metadata:
            raise HeyGenError(f"template has no text draft: {template_video_id}")
        if audio or script_text is not None:
            _replace_primary_audio(draft_with_metadata, audio=audio, script_text=script_text)
        green_screen_count = _set_avatar_green_screen(draft_with_metadata) if green_screen else 0

        create_payload = self.create_text_draft(
            draft_with_metadata.get("video_output") or {},
            folder_id=str(template_data.get("project_id") or ""),
            source_type=str(template_data.get("source_type") or "ai_studio"),
        )
        video_id = str((create_payload.get("data") or {}).get("video_id") or "")
        if not video_id:
            raise HeyGenError(f"text_draft.create returned no video_id: {_scrub(create_payload)}")

        save_payload = self.save_text_draft(video_id, title, draft_with_metadata)
        version_id = self.latest_text_draft_version_id(video_id)
        return {
            "video_id": video_id,
            "version_id": version_id,
            "title": title,
            "green_screen_count": green_screen_count,
            "create": create_payload,
            "save": save_payload,
            "draft": self.get_draft(video_id),
        }

    def build_generate_payload(
        self,
        video_id: str,
        *,
        title: str | None = None,
        version_id: str | None = None,
        enable_watermark: bool = False,
    ) -> JsonObject:
        draft_payload = self.get_draft(video_id)
        data = draft_payload.get("data") or {}
        draft_with_metadata = data.get("text_draft") or {}
        resolved_title = title or str(data.get("title") or f"heygen_{video_id}")
        resolved_version_id = version_id or self.latest_text_draft_version_id(video_id)
        return {
            "video_id": video_id,
            "enable_watermark": enable_watermark,
            "generate_type": "normal",
            "version_id": resolved_version_id,
            "draft_details": {
                "title": resolved_title,
                "text_draft_with_metadata": draft_with_metadata,
            },
        }

    def generate_text_draft(
        self,
        video_id: str,
        *,
        title: str | None = None,
        version_id: str | None = None,
        enable_watermark: bool = False,
    ) -> JsonObject:
        return self.post_json(
            "/v1/text_draft.generate",
            self.build_generate_payload(video_id, title=title, version_id=version_id, enable_watermark=enable_watermark),
        )

    def project_items(self, *, item_types: str = "heygen_video", limit: int = 20, offset: int = 0) -> JsonObject:
        return self.get_json("/v1/project/items", {"item_types": item_types, "limit": limit, "offset": offset})

    def project_item(self, video_id: str) -> JsonObject | None:
        payload = self.project_items(item_types="heygen_video", limit=50)
        for item in ((payload.get("data") or {}).get("items") or []):
            if item.get("video_id") == video_id or item.get("item_id") == video_id:
                return item
        return None

    def project_status(self, video_id: str) -> JsonObject:
        return self.get_json("/v1/project/items/status", {"item_ids": video_id})

    def asset_get(self, asset_id: str) -> JsonObject:
        return self.get_json("/v1/asset.get", {"id": asset_id})

    def upload_audio(self, audio_path: Path, *, poll_timeout: int = 300, poll_interval: float = 1.0) -> JsonObject:
        if not audio_path.exists():
            raise HeyGenError(f"audio file not found: {audio_path}")
        content_type = _audio_content_type(audio_path)
        upload_url_payload = self.get_json(
            "/v1/file/url.get",
            {
                "file_type": "audio",
                "filename": audio_path.stem,
                "content_type": content_type,
                "properties[audio_source]": "voice_recording",
            },
        )
        upload_data = upload_url_payload.get("data") or {}
        resource_id = str(upload_data.get("id") or "")
        upload_url = str(upload_data.get("url") or "")
        if not resource_id or not upload_url:
            raise HeyGenError(f"file/url.get returned no upload target: {_scrub(upload_url_payload)}")

        self.request(
            "PUT",
            upload_url,
            data=audio_path.read_bytes(),
            headers={
                "Accept": "*/*",
                "Content-Type": content_type,
                "x-amz-server-side-encryption": "AES256",
            },
        )
        upload_payload = self.post_json(
            "/v1/file.upload",
            {
                "id": resource_id,
                "name": audio_path.name,
                "file_type": "audio",
                "pipeline": "asset",
                "properties": {"audio_source": "voice_recording"},
            },
        )
        asset_id = _uploaded_asset_id(upload_payload) or resource_id

        deadline = time.monotonic() + poll_timeout
        last_asset_payload: JsonObject | None = None
        while time.monotonic() < deadline:
            last_asset_payload = self.asset_get(asset_id)
            asset = _asset_data(last_asset_payload)
            if _asset_failed(asset):
                raise HeyGenError(f"audio upload failed in asset.get: {_scrub(asset)}")
            audio_url = _asset_audio_url(asset)
            if audio_url:
                return {
                    "id": asset_id,
                    "resource_id": resource_id,
                    "upload": upload_payload,
                    "asset": asset,
                    "audio": {
                        "id": asset_id,
                        "name": asset.get("name") or audio_path.name,
                        "duration": _asset_duration(asset),
                        "url": audio_url,
                    },
                }
            time.sleep(poll_interval)

        raise HeyGenError(f"audio upload did not finish within {poll_timeout}s: {_scrub(last_asset_payload)}")

    def download_video(self, video_id: str, out_dir: Path, *, force: bool = False) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{_safe_filename(video_id)}.mp4"
        if out_path.exists() and out_path.stat().st_size > 0 and not force:
            return out_path

        item = self.project_item(video_id)
        if not item:
            raise HeyGenError(f"project item not found for video_id={video_id}")
        url = item.get("video_download_url") or item.get("video_url")
        if not url:
            raise HeyGenError(f"project item has no video URL yet for video_id={video_id}")

        tmp_path = out_path.with_suffix(out_path.suffix + ".part")
        if tmp_path.exists():
            tmp_path.unlink()
        request = Request(
            str(url),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
                ),
                "Accept": "video/mp4,video/*,*/*",
                "Referer": "https://app.heygen.com/",
            },
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response, tmp_path.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            tmp_path.replace(out_path)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", "replace")
            raise HeyGenError(
                f"HeyGen video download returned HTTP {exc.code} for {_safe_endpoint(str(url))}",
                status=exc.code,
                body=error_body,
            ) from exc
        except (OSError, URLError) as exc:
            if tmp_path.exists():
                tmp_path.unlink()
            raise HeyGenError(f"HeyGen video download failed for video_id={video_id}: {exc}") from exc
        if out_path.stat().st_size < 100_000:
            raise HeyGenError(f"downloaded file is unexpectedly small: {out_path} ({out_path.stat().st_size} bytes)")
        return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Small internal HeyGen API client using saved app cookies.")
    parser.add_argument("--storage-state", default=None, help=f"Playwright storageState JSON. Defaults to latest {DEFAULT_STATE_GLOB}")
    parser.add_argument("--timeout", type=int, default=30)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth-probe", help="Check that saved cookies can call api2.heygen.com.")

    project_items = sub.add_parser("project-items", help="List recent project items.")
    project_items.add_argument("--limit", type=int, default=10)
    project_items.add_argument("--offset", type=int, default=0)
    project_items.add_argument("--item-types", default="heygen_video")

    status = sub.add_parser("project-status", help="Read render status for one video id.")
    status.add_argument("--video-id", required=True)

    draft = sub.add_parser("get-draft", help="Fetch a text draft by video id.")
    draft.add_argument("--video-id", required=True)
    draft.add_argument("--out", default=None, help="Write scrubbed draft JSON to this path.")
    draft.add_argument("--raw-out", default=None, help="Write raw draft JSON, including signed URLs. Keep under local_secrets/.")

    download = sub.add_parser("download", help="Download a completed video by video id.")
    download.add_argument("--video-id", required=True)
    download.add_argument("--out-dir", default=str(DEFAULT_DOWNLOAD_DIR))
    download.add_argument("--force", action="store_true")

    upload_audio = sub.add_parser("upload-audio", help="Upload and transcode an audio file as a HeyGen asset.")
    upload_audio.add_argument("audio_path")
    upload_audio.add_argument("--poll-timeout", type=int, default=300)
    upload_audio.add_argument("--poll-interval", type=float, default=1.0)
    upload_audio.add_argument("--raw-out", default=None, help="Write raw upload/asset JSON. Keep under local_secrets/.")

    clone_draft = sub.add_parser("clone-draft", help="Create and save a HeyGen draft from a template video draft.")
    clone_draft.add_argument("--template-video-id", required=True)
    clone_draft.add_argument("--title", required=True)
    clone_draft.add_argument("--audio-json", default=None, help="Raw JSON from upload-audio.")
    clone_draft.add_argument("--script-text-file", default=None)
    clone_draft.add_argument("--no-green-screen", action="store_true")
    clone_draft.add_argument("--raw-out", default=None, help="Write raw clone/save/draft JSON. Keep under local_secrets/.")

    generate = sub.add_parser("generate-draft", help="Generate a video from an existing saved HeyGen text draft.")
    generate.add_argument("--video-id", required=True)
    generate.add_argument("--title", default=None)
    generate.add_argument("--version-id", default=None)
    generate.add_argument("--enable-watermark", action="store_true")
    generate.add_argument("--submit", action="store_true", help="Actually call text_draft.generate. Without it this is a dry-run.")
    generate.add_argument("--wait", action="store_true")
    generate.add_argument("--wait-timeout", type=int, default=1200)
    generate.add_argument("--poll-interval", type=float, default=10.0)
    generate.add_argument("--download", action="store_true")
    generate.add_argument("--out-dir", default=str(DEFAULT_DOWNLOAD_DIR))
    generate.add_argument("--raw-out", default=None, help="Write raw generate/status JSON. Keep under local_secrets/.")

    args = parser.parse_args()
    state_path = Path(args.storage_state) if args.storage_state else _latest_storage_state()
    client = HeyGenInternalClient(state_path, timeout=int(args.timeout))

    try:
        if args.command == "auth-probe":
            payload = client.auth_probe()
            data = payload.get("data") or {}
            print(
                json.dumps(
                    {
                        "ok": payload.get("code") == 100,
                        "storage_state": _display(state_path),
                        "username": data.get("username"),
                        "name": " ".join(str(data.get(k) or "") for k in ("first_name", "last_name")).strip(),
                        "email_present": bool(data.get("email")),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.command == "project-items":
            payload = client.project_items(item_types=str(args.item_types), limit=int(args.limit), offset=int(args.offset))
            items = []
            for item in ((payload.get("data") or {}).get("items") or []):
                items.append(
                    {
                        "name": item.get("name"),
                        "video_id": item.get("video_id") or item.get("item_id"),
                        "status": item.get("status"),
                        "duration": item.get("duration"),
                        "aspect_ratio": item.get("aspect_ratio"),
                        "orientation": item.get("orientation"),
                        "created_ts": item.get("created_ts"),
                    }
                )
            print(json.dumps({"items": items}, ensure_ascii=False, indent=2))
            return 0

        if args.command == "project-status":
            payload = client.project_status(args.video_id)
            print(json.dumps(_scrub(payload), ensure_ascii=False, indent=2))
            return 0

        if args.command == "get-draft":
            payload = client.get_draft(args.video_id)
            scrubbed = _scrub(payload)
            if args.out:
                out_path = Path(args.out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(scrubbed, ensure_ascii=False, indent=2), encoding="utf-8")
            if args.raw_out:
                raw_path = Path(args.raw_out)
                _ensure_local_secret(raw_path)
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            data = payload.get("data") or {}
            draft_payload = (data.get("text_draft") or {}).get("text_draft") or {}
            script = draft_payload.get("script") or {}
            elements = script.get("elements") or {}
            print(
                json.dumps(
                    {
                        "ok": payload.get("code") == 100,
                        "title": data.get("title"),
                        "element_count": len(elements),
                        "element_types": {key: value.get("type") for key, value in elements.items()},
                        "scrubbed_out": args.out,
                        "raw_out": args.raw_out,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.command == "download":
            out_path = client.download_video(args.video_id, Path(args.out_dir), force=bool(args.force))
            print(json.dumps({"ok": True, "path": _display(out_path), "bytes": out_path.stat().st_size}, ensure_ascii=False, indent=2))
            return 0

        if args.command == "upload-audio":
            payload = client.upload_audio(Path(args.audio_path), poll_timeout=int(args.poll_timeout), poll_interval=float(args.poll_interval))
            if args.raw_out:
                raw_path = Path(args.raw_out)
                _ensure_local_secret(raw_path)
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            audio = payload.get("audio") or {}
            print(
                json.dumps(
                    {
                        "ok": True,
                        "id": audio.get("id"),
                        "name": audio.get("name"),
                        "duration": audio.get("duration"),
                        "url_present": bool(audio.get("url")),
                        "raw_out": args.raw_out,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.command == "clone-draft":
            audio = _load_uploaded_audio(args.audio_json) if args.audio_json else None
            script_text = Path(args.script_text_file).read_text(encoding="utf-8").strip() if args.script_text_file else None
            payload = client.clone_draft(
                args.template_video_id,
                title=str(args.title),
                audio=audio,
                script_text=script_text,
                green_screen=not bool(args.no_green_screen),
            )
            if args.raw_out:
                raw_path = Path(args.raw_out)
                _ensure_local_secret(raw_path)
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "ok": True,
                        "video_id": payload.get("video_id"),
                        "version_id": payload.get("version_id"),
                        "title": payload.get("title"),
                        "green_screen_count": payload.get("green_screen_count"),
                        "raw_out": args.raw_out,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.command == "generate-draft":
            generate_payload = client.build_generate_payload(
                args.video_id,
                title=args.title,
                version_id=args.version_id,
                enable_watermark=bool(args.enable_watermark),
            )
            result: JsonObject = {"dry_run": not bool(args.submit), "generate_payload": generate_payload}
            if args.submit:
                result["generate"] = client.post_json("/v1/text_draft.generate", generate_payload)
                if args.wait:
                    result["status"] = _wait_for_project_status(
                        client,
                        args.video_id,
                        timeout=int(args.wait_timeout),
                        poll_interval=float(args.poll_interval),
                    )
                if args.raw_out:
                    raw_path = Path(args.raw_out)
                    _ensure_local_secret(raw_path)
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                if args.download:
                    out_path = client.download_video(args.video_id, Path(args.out_dir), force=False)
                    result["download"] = {"path": _display(out_path), "bytes": out_path.stat().st_size}
            if args.raw_out:
                raw_path = Path(args.raw_out)
                _ensure_local_secret(raw_path)
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            summary: JsonObject = {
                "ok": True,
                "dry_run": not bool(args.submit),
                "video_id": args.video_id,
                "version_id": generate_payload.get("version_id"),
                "title": (generate_payload.get("draft_details") or {}).get("title"),
                "raw_out": args.raw_out,
            }
            if args.submit:
                summary["generate"] = _scrub(result.get("generate"))
                status = result.get("status")
                if status:
                    summary["status"] = _summarize_project_status(status)
                if result.get("download"):
                    summary["download"] = result.get("download")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

    except HeyGenError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "status": exc.status, "body": _scrub_text(exc.body[:1000])}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    raise AssertionError(f"unhandled command: {args.command}")


def _cookie_jar_from_storage_state(path: Path) -> http.cookiejar.CookieJar:
    data = json.loads(path.read_text(encoding="utf-8"))
    jar = http.cookiejar.CookieJar()
    for cookie in data.get("cookies") or []:
        domain = str(cookie.get("domain") or "")
        expires = cookie.get("expires")
        jar.set_cookie(
            http.cookiejar.Cookie(
                version=0,
                name=str(cookie.get("name") or ""),
                value=str(cookie.get("value") or ""),
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=bool(domain),
                domain_initial_dot=domain.startswith("."),
                path=str(cookie.get("path") or "/"),
                path_specified=True,
                secure=bool(cookie.get("secure")),
                expires=int(expires) if isinstance(expires, (int, float)) and expires > 0 else None,
                discard=False,
                comment=None,
                comment_url=None,
                rest={"HttpOnly": cookie.get("httpOnly")},
                rfc2109=False,
            )
        )
    return jar


def _latest_storage_state() -> Path:
    candidates = sorted((ROOT).glob(DEFAULT_STATE_GLOB), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit(f"No HeyGen storage state found: {DEFAULT_STATE_GLOB}")
    return candidates[0]


def _absolute_url(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    return f"{API_BASE}{path_or_url if path_or_url.startswith('/') else '/' + path_or_url}"


def _decode_json(body: bytes, *, content_type: str) -> JsonObject:
    text = body.decode("utf-8", "replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HeyGenError(f"expected JSON response, got content-type={content_type!r}: {text[:300]}") from exc
    if not isinstance(payload, dict):
        raise HeyGenError(f"expected JSON object response, got {type(payload).__name__}")
    return payload


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return _scrub_text(value)
    return value


def _scrub_text(value: str) -> str:
    value = re.sub(
        r"([?&](?:token|signature|x-amz-signature|x-amz-credential|x-amz-security-token|authorization|access_token|key|Signature)=)[^&\s]+",
        r"\1REDACTED",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer REDACTED", value)
    return value


def _safe_endpoint(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}"


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return safe[:120] or "heygen-video"


def _audio_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".m4a":
        return "audio/mp4"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _asset_data(payload: JsonObject) -> JsonObject:
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("asset"), dict):
        return data["asset"]
    if isinstance(data, dict):
        return data
    return {}


def _asset_failed(asset: JsonObject) -> bool:
    file_meta = asset.get("file_meta") if isinstance(asset.get("file_meta"), dict) else {}
    status = file_meta.get("status", asset.get("status"))
    return status in {-1, "failed", "error"}


def _uploaded_asset_id(payload: JsonObject) -> str:
    data = payload.get("data")
    candidates: list[Any] = []
    if isinstance(data, dict):
        candidates.extend(data.get(key) for key in ("id", "asset_id", "item_id", "resource_id"))
    candidates.extend(payload.get(key) for key in ("id", "asset_id", "item_id", "resource_id"))
    for value in candidates:
        if isinstance(value, str) and value:
            return value
    return ""


def _asset_duration(asset: JsonObject) -> float | None:
    file_meta = asset.get("file_meta") if isinstance(asset.get("file_meta"), dict) else {}
    meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
    for value in (meta.get("duration"), file_meta.get("duration"), asset.get("duration")):
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _asset_audio_url(asset: JsonObject) -> str:
    file_meta = asset.get("file_meta") if isinstance(asset.get("file_meta"), dict) else {}
    file_meta_meta = file_meta.get("meta") if isinstance(file_meta.get("meta"), dict) else {}
    audios = file_meta_meta.get("audios") if isinstance(file_meta_meta.get("audios"), dict) else {}
    value = audios.get("mp3")
    return value if isinstance(value, str) else ""


def _load_uploaded_audio(path_value: str) -> JsonObject:
    path = Path(path_value)
    data = json.loads(path.read_text(encoding="utf-8"))
    audio = data.get("audio") if isinstance(data, dict) else None
    if not isinstance(audio, dict) or not audio.get("url"):
        raise SystemExit(f"audio JSON does not look like upload-audio output: {path}")
    return audio


def _replace_primary_audio(draft_with_metadata: JsonObject, *, audio: JsonObject | None, script_text: str | None) -> None:
    text_draft = draft_with_metadata.get("text_draft") or {}
    script = text_draft.get("script") or {}
    elements = script.get("elements") or {}
    audio_element_id = ""
    for element_id, element in elements.items():
        if isinstance(element, dict) and element.get("type") == "audio":
            audio_element_id = str(element_id)
            break
    if not audio_element_id:
        for element_id, element in elements.items():
            if isinstance(element, dict) and element.get("type") == "tts":
                audio_element_id = str(element_id)
                break
    if not audio_element_id:
        raise HeyGenError("template draft has no primary audio/tts element")

    element = elements[audio_element_id]
    metadata = draft_with_metadata.setdefault("metadata", {}).setdefault(audio_element_id, {})
    current_text = str(element.get("text") or metadata.get("text") or "")
    resolved_text = script_text if script_text is not None else current_text
    if resolved_text:
        element["text"] = resolved_text
        metadata["text"] = resolved_text

    if not audio:
        return

    element["type"] = "audio"
    uploaded_audio = _uploaded_audio_data(audio)
    audio_url = str(uploaded_audio.get("url") or "")
    if not audio_url:
        raise HeyGenError("uploaded audio JSON has no audio.url")
    audio_name = str(uploaded_audio.get("name") or "uploaded_audio.mp3")
    duration = uploaded_audio.get("duration")

    attributes = element.setdefault("attributes", {})
    attributes["source_type"] = "url"
    attributes["src"] = audio_url
    attributes.setdefault("volume", 1.0)

    metadata.update(
        {
            "element_id": audio_element_id,
            "type": "audio",
            "url": audio_url.split("?", 1)[0],
            "source_audio_url": audio_url,
            "name": audio_name,
            "fileType": "upload",
            "asset_source": None,
            "audio_duration": None,
        }
    )
    if isinstance(duration, (int, float)):
        metadata["duration"] = float(duration)
    if script_text is not None:
        metadata["words"] = _rough_words_for_text(resolved_text, float(duration or metadata.get("duration") or 0))
        metadata["caption_override_words"] = None


def _uploaded_audio_data(audio: JsonObject) -> JsonObject:
    nested = audio.get("audio") if isinstance(audio.get("audio"), dict) else None
    return nested if isinstance(nested, dict) else audio


def _rough_words_for_text(text: str, duration: float) -> list[JsonObject]:
    words = re.findall(r"\S+", text)
    if duration <= 0 or not words:
        return [{"word": "<start>", "start_time": 0.0, "end_time": 0.0}, {"word": "<end>", "start_time": duration, "end_time": duration}]
    usable = max(duration - 0.2, 0.1)
    step = usable / max(len(words), 1)
    result: list[JsonObject] = [{"word": "<start>", "start_time": 0.0, "end_time": 0.0}]
    for index, word in enumerate(words):
        start = round(0.1 + index * step, 3)
        end = round(min(0.1 + (index + 0.82) * step, duration), 3)
        result.append({"word": word, "start_time": start, "end_time": end})
    result.append({"word": "<end>", "start_time": duration, "end_time": duration})
    return result


def _set_avatar_green_screen(draft_with_metadata: JsonObject) -> int:
    text_draft = draft_with_metadata.get("text_draft") or {}
    visual = text_draft.get("visual") or {}
    elements = visual.get("elements") or {}
    count = 0
    for element in elements.values():
        if not isinstance(element, dict) or element.get("type") != "avatar":
            continue
        content = element.setdefault("content", {})
        content["matting"] = True
        avatar_background = content.setdefault("avatar_background", {})
        avatar_background["background_color"] = "#00FF00"
        avatar_background["background_image"] = None
        count += 1
    return count


def _draft_has_faceswap(text_draft: JsonObject) -> bool:
    visual = text_draft.get("visual") if isinstance(text_draft, dict) else {}
    elements = visual.get("elements") if isinstance(visual, dict) else {}
    for element in (elements or {}).values():
        if not isinstance(element, dict) or element.get("type") != "avatar":
            continue
        content = element.get("content") if isinstance(element.get("content"), dict) else {}
        if content.get("face_id"):
            return True
    return False


def _wait_for_project_status(client: HeyGenInternalClient, video_id: str, *, timeout: int, poll_interval: float) -> JsonObject:
    deadline = time.monotonic() + timeout
    last_payload: JsonObject | None = None
    while time.monotonic() < deadline:
        last_payload = client.project_status(video_id)
        status = _summarize_project_status(last_payload).get("status")
        if status in {"completed", "failed", "error"}:
            return last_payload
        time.sleep(poll_interval)
    raise HeyGenError(f"video generation did not finish within {timeout}s: {_scrub(last_payload)}")


def _summarize_project_status(payload: Any) -> JsonObject:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data") or []
    item = data[0] if isinstance(data, list) and data else {}
    if not isinstance(item, dict):
        return {}
    return {
        "id": item.get("id"),
        "status": item.get("status"),
        "progress": item.get("progress"),
        "eta": item.get("eta"),
        "error_code": item.get("error_code"),
        "error_message": item.get("error_message"),
    }


def _ensure_local_secret(path: Path) -> None:
    try:
        path.resolve().relative_to((ROOT / "local_secrets").resolve())
    except ValueError as exc:
        raise SystemExit("--raw-out must be under local_secrets/ to avoid leaking signed URLs") from exc


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
