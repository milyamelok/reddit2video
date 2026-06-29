#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import http.client
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


JsonObject = dict[str, Any]
MAX_BYTES = 30 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description="Download selected resolver media candidates and write hydrated JSON.")
    parser.add_argument("--resolver-input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--asset-dir", required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--hls-duration-sec", type=float, default=8.0)
    args = parser.parse_args()

    resolver_path = Path(args.resolver_input)
    payload = json.loads(resolver_path.read_text(encoding="utf-8"))
    asset_dir = Path(args.asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)

    jobs = _selected_download_jobs(payload, asset_dir)

    results = _download_jobs(
        jobs,
        concurrency=int(args.concurrency),
        timeout=int(args.timeout),
        hls_duration_sec=float(args.hls_duration_sec),
    )
    failed_urls = _failed_download_urls(results)
    promoted_replacements = 0
    removed_failed = _drop_failed_remote_selected_candidates(payload)
    for _ in range(3):
        promoted = _promote_replacement_candidates(payload, failed_urls=failed_urls)
        if promoted <= 0:
            break
        promoted_replacements += promoted
        replacement_results = _download_jobs(
            _selected_download_jobs(payload, asset_dir),
            concurrency=int(args.concurrency),
            timeout=int(args.timeout),
            hls_duration_sec=float(args.hls_duration_sec),
        )
        results.extend(replacement_results)
        failed_urls.update(_failed_download_urls(replacement_results))
        removed_failed += _drop_failed_remote_selected_candidates(payload)

    downloaded = sum(1 for result in results if result.get("status") == "downloaded")
    cached = sum(1 for result in results if result.get("status") == "cached")
    failed = sum(1 for result in results if result.get("status") == "failed")
    payload.setdefault("metadata", {})["selected_asset_download"] = {
        "asset_dir": str(asset_dir),
        "jobs": len(jobs),
        "downloaded": downloaded,
        "cached": cached,
        "failed": failed,
        "removed_failed_selected_candidates": removed_failed,
        "promoted_replacement_selected_candidates": promoted_replacements,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Downloaded {downloaded}, cached {cached}, failed {failed} selected assets")
    if removed_failed:
        print(f"Removed {removed_failed} failed remote selected candidates")
    print(f"Wrote {out_path}")
    return 0


def _download_jobs(
    jobs: list[tuple[JsonObject, str, Path, str]],
    *,
    concurrency: int,
    timeout: int,
    hls_duration_sec: float,
) -> list[JsonObject]:
    results: list[JsonObject] = []
    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as pool:
        futures = {
            pool.submit(
                _download_one,
                candidate,
                url,
                out_dir,
                stem,
                timeout=timeout,
                hls_duration_sec=hls_duration_sec,
            ): (candidate, url)
            for candidate, url, out_dir, stem in jobs
        }
        for future in as_completed(futures):
            candidate, url = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # Keep one hostile URL from killing the whole hydration pass.
                error = f"{type(exc).__name__}: {exc}"
                candidate["download_error"] = error
                results.append({"status": "failed", "url": url, "error": error})
    return results


def _selected_download_jobs(payload: JsonObject, asset_dir: Path) -> list[tuple[JsonObject, str, Path, str]]:
    jobs: list[tuple[JsonObject, str, Path, str]] = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        post_id = _safe(str(item.get("post_id") or "post"))
        for slot in item.get("resolved_slots") or []:
            if not isinstance(slot, dict):
                continue
            if str(slot.get("status") or "").lower() in {"fail", "skipped"}:
                continue
            scene_id = int(slot.get("scene_id") or 0)
            asset_id = _safe(str(slot.get("asset_id") or "asset"))
            for index, candidate in enumerate(slot.get("selected_candidates") or [], start=1):
                if not isinstance(candidate, dict):
                    continue
                url = str(candidate.get("media_url") or candidate.get("thumbnail_url") or "").strip()
                if _candidate_already_has_valid_local_media(candidate, url):
                    continue
                if not url.startswith(("http://", "https://")):
                    continue
                stem = f"s{scene_id:03d}_{asset_id}_{index:02d}"
                jobs.append((candidate, url, asset_dir / post_id, stem))
    return jobs


def _candidate_already_has_valid_local_media(candidate: JsonObject, source_url: str) -> bool:
    path = _candidate_existing_local_path(candidate)
    if path is None or not path.exists() or path.stat().st_size <= 0:
        return False
    if source_url.startswith(("http://", "https://")) and not _cached_publication_asset_matches(path, source_url):
        return False
    candidate["local_path"] = str(path)
    candidate["public_path"] = _public_path(path)
    candidate["local_content_type"] = str(
        candidate.get("local_content_type") or _content_type_from_extension(path.suffix.lower()) or ""
    )
    return True


def _candidate_existing_local_path(candidate: JsonObject) -> Path | None:
    for key in ("local_path", "path", "downloaded_path", "file_path"):
        value = str(candidate.get(key) or "").strip()
        if not value:
            continue
        path = Path(value)
        if path.exists():
            return path
    return None


def _failed_download_urls(results: list[JsonObject]) -> set[str]:
    return {str(result.get("url") or "") for result in results if result.get("status") == "failed"}


def _promote_replacement_candidates(payload: JsonObject, *, failed_urls: set[str]) -> int:
    promoted = 0
    used_keys = _selected_media_keys(payload)
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        for slot in item.get("resolved_slots") or []:
            if not isinstance(slot, dict):
                continue
            if slot.get("selected_candidates"):
                continue
            if not _slot_required(slot):
                continue
            replacement = _first_downloadable_replacement(slot, used_keys=used_keys, failed_urls=failed_urls)
            if replacement is None:
                continue
            slot["selected_candidates"] = [replacement]
            slot["status"] = "pass"
            errors = slot.setdefault("errors", [])
            if isinstance(errors, list):
                errors.append(
                    "Promoted replacement selected media candidate after download failure: "
                    f"{replacement.get('candidate_id') or 'candidate'}."
                )
            key = _candidate_key(replacement)
            if key:
                used_keys.add(key)
            promoted += 1
    return promoted


def _first_downloadable_replacement(
    slot: JsonObject,
    *,
    used_keys: set[str],
    failed_urls: set[str],
) -> JsonObject | None:
    for candidate in slot.get("candidate_pool") or []:
        if not isinstance(candidate, dict):
            continue
        url = _candidate_download_url(candidate)
        if not url or url in failed_urls:
            continue
        key = _candidate_key(candidate)
        if key and key in used_keys:
            continue
        return deepcopy(candidate)
    return None


def _selected_media_keys(payload: JsonObject) -> set[str]:
    keys: set[str] = set()
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        for slot in item.get("resolved_slots") or []:
            if not isinstance(slot, dict):
                continue
            for candidate in slot.get("selected_candidates") or []:
                if isinstance(candidate, dict):
                    key = _candidate_key(candidate)
                    if key:
                        keys.add(key)
    return keys


def _candidate_download_url(candidate: JsonObject) -> str:
    url = str(candidate.get("media_url") or candidate.get("thumbnail_url") or "").strip()
    if url.startswith(("http://", "https://")):
        return url
    return ""


def _drop_failed_remote_selected_candidates(payload: JsonObject) -> int:
    removed = 0
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        for slot in item.get("resolved_slots") or []:
            if not isinstance(slot, dict):
                continue
            kept: list[JsonObject] = []
            slot_removed = 0
            for candidate in slot.get("selected_candidates") or []:
                if not isinstance(candidate, dict):
                    continue
                if _candidate_download_failed(candidate):
                    slot_removed += 1
                    continue
                kept.append(candidate)
            if slot_removed:
                removed += slot_removed
                slot["selected_candidates"] = kept
                errors = slot.setdefault("errors", [])
                if isinstance(errors, list):
                    errors.append(f"Removed {slot_removed} selected remote media candidate(s) after download failure.")
                if not kept and _slot_required(slot):
                    slot["status"] = "fail"
    return removed


def _candidate_download_failed(candidate: JsonObject) -> bool:
    if not candidate.get("download_error"):
        return False
    if candidate.get("local_path") or candidate.get("public_path"):
        return False
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    if metadata.get("local_media_path") or metadata.get("local_thumbnail_path"):
        return False
    url = str(candidate.get("media_url") or candidate.get("thumbnail_url") or "")
    return url.startswith(("http://", "https://"))


def _slot_required(slot: JsonObject) -> bool:
    slot_meta = slot.get("slot") if isinstance(slot.get("slot"), dict) else {}
    return bool(slot.get("required") or slot_meta.get("required"))


def _candidate_key(candidate: JsonObject) -> str:
    url = _candidate_download_url(candidate)
    if url:
        return url.split("?", 1)[0].strip().lower().rstrip("/")
    page_url = str(candidate.get("page_url") or "").strip()
    if page_url:
        return page_url.split("?", 1)[0].lower().rstrip("/")
    return ""


def _download_one(
    candidate: JsonObject,
    url: str,
    out_dir: Path,
    stem: str,
    *,
    timeout: int,
    hls_duration_sec: float,
) -> JsonObject:
    out_dir.mkdir(parents=True, exist_ok=True)
    hls_url = _candidate_hls_url(candidate) or (url if ".m3u8" in url else "")
    if hls_url:
        path = out_dir / f"{stem}.mp4"
        if _cached_publication_asset_matches(path, hls_url) and path.stat().st_size > 0:
            candidate["local_path"] = str(path)
            candidate["public_path"] = _public_path(path)
            candidate["local_content_type"] = "video/mp4"
            return {"status": "cached", "url": hls_url, "path": str(path), "content_type": "video/mp4"}
        if _convert_hls_to_mp4(hls_url=hls_url, output=path, duration_sec=hls_duration_sec):
            _write_cache_metadata(path, source_url=hls_url, content_type="video/mp4")
            candidate["local_path"] = str(path)
            candidate["public_path"] = _public_path(path)
            candidate["local_content_type"] = "video/mp4"
            return {"status": "downloaded", "url": hls_url, "path": str(path), "content_type": "video/mp4"}
        fallback_url = str(candidate.get("thumbnail_url") or "").strip()
        if fallback_url.startswith(("http://", "https://")) and ".m3u8" not in fallback_url:
            url = fallback_url
        else:
            candidate["download_error"] = "hls_conversion_failed"
            return {"status": "failed", "url": hls_url, "error": "hls_conversion_failed"}

    parsed_ext = _extension_from_url(url)
    existing = _existing_publication_asset(out_dir, stem, source_url=url)
    if existing and existing.stat().st_size > 0:
        candidate["local_path"] = str(existing)
        candidate["public_path"] = _public_path(existing)
        candidate["local_content_type"] = _content_type_from_extension(existing.suffix.lower())
        return {"status": "cached", "url": url, "path": str(existing)}

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            ),
            "Accept": "image/webp,image/apng,image/png,image/jpeg,image/*;q=0.8,video/*,*/*;q=0.5",
        },
    )
    try:
        context = ssl._create_unverified_context()
        with urlopen(request, timeout=timeout, context=context) as response:
            content_type = str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if _unsupported_publication_content_type(content_type):
                raise ValueError(f"unsupported_publication_content_type:{content_type}")
            ext = _extension_from_content_type(content_type) or parsed_ext or ".bin"
            path = out_dir / f"{stem}{ext}"
            with path.open("wb") as handle:
                total = 0
                while True:
                    chunk = response.read(1024 * 128)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError(f"download exceeds {MAX_BYTES} bytes")
                    handle.write(chunk)
        candidate["local_path"] = str(path)
        candidate["public_path"] = _public_path(path)
        candidate["local_content_type"] = content_type
        _write_cache_metadata(path, source_url=url, content_type=content_type)
        return {"status": "downloaded", "url": url, "path": str(path), "content_type": content_type}
    except (OSError, URLError, ValueError, http.client.HTTPException) as exc:
        candidate["download_error"] = str(exc)
        return {"status": "failed", "url": url, "error": str(exc)}


def _candidate_hls_url(candidate: JsonObject) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for value in (
        candidate.get("media_url"),
        candidate.get("url"),
        metadata.get("video_hls_url"),
    ):
        text = str(value or "")
        if text.startswith(("http://", "https://")) and ".m3u8" in text:
            return text
    return ""


def _convert_hls_to_mp4(*, hls_url: str, output: Path, duration_sec: float) -> bool:
    ffmpeg = _ffmpeg_path()
    if ffmpeg is None:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.with_suffix(".tmp.mp4")
    tmp_output.unlink(missing_ok=True)
    headers = (
        "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36\r\n"
        "Referer: https://ru.pinterest.com/\r\n"
        "Origin: https://ru.pinterest.com\r\n"
    )
    cmd = [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-headers",
        headers,
        "-i",
        hls_url,
        "-t",
        str(max(1.0, duration_sec)),
        "-map",
        "0:v:0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "24",
        "-an",
        "-movflags",
        "+faststart",
        str(tmp_output),
    ]
    env = os.environ.copy()
    lib_dir = str(ffmpeg.parent.resolve())
    env["DYLD_LIBRARY_PATH"] = f"{lib_dir}:{env['DYLD_LIBRARY_PATH']}" if env.get("DYLD_LIBRARY_PATH") else lib_dir
    env["LD_LIBRARY_PATH"] = f"{lib_dir}:{env['LD_LIBRARY_PATH']}" if env.get("LD_LIBRARY_PATH") else lib_dir
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=max(45, int(duration_sec * 12)),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        tmp_output.unlink(missing_ok=True)
        return False
    if not tmp_output.exists() or tmp_output.stat().st_size <= 0:
        tmp_output.unlink(missing_ok=True)
        return False
    tmp_output.replace(output)
    return True


def _ffmpeg_path() -> Path | None:
    configured = os.getenv("FFMPEG_PATH")
    if configured and Path(configured).exists():
        return Path(configured)
    system = shutil.which("ffmpeg")
    if system:
        return Path(system)
    root = Path(__file__).resolve().parent.parent
    for candidate in (
        Path("/opt/homebrew/bin/ffmpeg"),
        Path("/usr/local/bin/ffmpeg"),
        root / "remotion" / "node_modules" / "@remotion" / "compositor-darwin-arm64" / "ffmpeg",
        root / "remotion" / "node_modules" / "@remotion" / "compositor-linux-x64-gnu" / "ffmpeg",
        root / "remotion" / "node_modules" / "@remotion" / "compositor-linux-arm64-gnu" / "ffmpeg",
    ):
        if candidate.exists():
            return candidate
    return None


def _extension_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{2,5}", suffix or ""):
        return suffix
    return ""


def _extension_from_content_type(content_type: str) -> str:
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/svg+xml":
        return ".svg"
    guessed = mimetypes.guess_extension(content_type or "")
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ""


def _unsupported_publication_content_type(content_type: str) -> bool:
    return content_type in {
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        "application/mpegurl",
        "audio/mpegurl",
        "audio/x-mpegurl",
        "image/avif",
    }


def _existing_publication_asset(out_dir: Path, stem: str, *, source_url: str) -> Path | None:
    for path in sorted(out_dir.glob(f"{stem}.*")):
        if path.stat().st_size <= 0:
            continue
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm", ".mov"}:
            if _cached_publication_asset_matches(path, source_url):
                return path
    return None


def _cached_publication_asset_matches(path: Path, source_url: str) -> bool:
    metadata_path = _cache_metadata_path(path)
    if not metadata_path.exists():
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return str(metadata.get("source_url") or "") == source_url


def _write_cache_metadata(path: Path, *, source_url: str, content_type: str) -> None:
    metadata = {
        "source_url": source_url,
        "content_type": content_type,
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }
    _cache_metadata_path(path).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_metadata_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.download.json")


def _content_type_from_extension(suffix: str) -> str:
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".mp4":
        return "video/mp4"
    if suffix == ".mov":
        return "video/quicktime"
    if suffix == ".webm":
        return "video/webm"
    return ""


def _public_path(path: Path) -> str:
    try:
        return "__STATIC_FILE__" + path.resolve().relative_to((Path.cwd() / "remotion" / "public").resolve()).as_posix()
    except ValueError:
        return str(path)


def _safe(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return safe[:120] or "asset"


if __name__ == "__main__":
    raise SystemExit(main())
