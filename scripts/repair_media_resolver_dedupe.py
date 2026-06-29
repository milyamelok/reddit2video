#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.media_asset_hygiene import publication_render_asset_hygiene_rejection_reason  # noqa: E402


JsonObject = dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair a media resolver batch by overlaying refreshed item caches and deduping selected media URLs."
    )
    parser.add_argument("--resolver-input", required=True)
    parser.add_argument("--overlay-cache-dir", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    payload = _read_json(Path(args.resolver_input))
    if not isinstance(payload.get("items"), list):
        raise SystemExit("--resolver-input must be a MediaResolverBatch JSON with items.")

    overlays = _load_overlay_items(Path(args.overlay_cache_dir)) if args.overlay_cache_dir else {}
    repaired_items: list[JsonObject] = []
    used_keys: set[str] = set()
    repair_stats = {
        "overlay_slots_used": 0,
        "duplicate_selected_replaced": 0,
        "failed_slots_after_repair": 0,
        "selected_assets": 0,
        "unique_selected_media": 0,
    }

    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        repaired = _repair_item(deepcopy(item), overlays.get(str(item.get("post_id") or "")), used_keys, repair_stats)
        repaired_items.append(repaired)

    repair_stats["unique_selected_media"] = len(used_keys)
    output = deepcopy(payload)
    output["items"] = repaired_items
    output.setdefault("metadata", {})["dedupe_repair"] = {
        **repair_stats,
        "source_resolver": args.resolver_input,
        "overlay_cache_dir": args.overlay_cache_dir,
        "repaired_at": datetime.now(timezone.utc).isoformat(),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_path), **repair_stats}, ensure_ascii=False, indent=2))
    return 0


def _repair_item(
    item: JsonObject,
    overlay_item: JsonObject | None,
    used_keys: set[str],
    stats: JsonObject,
) -> JsonObject:
    overlay_slots = _slots_by_key(overlay_item.get("resolved_slots") or []) if overlay_item else {}
    repaired_slots: list[JsonObject] = []
    failed_slots: list[str] = []
    for base_slot in item.get("resolved_slots") or []:
        if not isinstance(base_slot, dict):
            continue
        slot_key = _slot_key(base_slot)
        overlay_slot = overlay_slots.get(slot_key)
        slot = deepcopy(overlay_slot) if _slot_has_selection(overlay_slot) else deepcopy(base_slot)
        if overlay_slot and _slot_has_selection(overlay_slot):
            stats["overlay_slots_used"] += 1

        original_selected = list(slot.get("selected_candidates") or [])
        selected = _deduped_selection(slot, fallback_slot=base_slot, used_keys=used_keys)
        if selected:
            if _selection_keys(original_selected) != _selection_keys(selected):
                stats["duplicate_selected_replaced"] += 1
            slot["selected_candidates"] = selected
            slot["status"] = "pass"
            stats["selected_assets"] += len(selected)
        elif _slot_required(slot):
            slot["selected_candidates"] = []
            slot["status"] = "fail"
            failed_slots.append(f"scene={slot.get('scene_id')} asset={slot.get('asset_id')}")
        else:
            slot["selected_candidates"] = []
            slot["status"] = "skipped"
        repaired_slots.append(slot)

    item["resolved_slots"] = repaired_slots
    item["status"] = "fail" if failed_slots else "pass"
    item["provider_errors"] = _provider_errors_for_failed_slots(failed_slots)
    item.setdefault("metadata", {})["dedupe_repair"] = {
        "failed_slots_after_repair": len(failed_slots),
        "selected_asset_count": sum(len(slot.get("selected_candidates") or []) for slot in repaired_slots),
    }
    stats["failed_slots_after_repair"] += len(failed_slots)
    return item


def _deduped_selection(slot: JsonObject, *, fallback_slot: JsonObject, used_keys: set[str]) -> list[JsonObject]:
    candidates = list(_candidate_sources(slot))
    if fallback_slot is not slot:
        candidates.extend(_candidate_sources(fallback_slot))
    seen_in_slot: set[str] = set()
    first_usable: JsonObject | None = None
    for raw_candidate in candidates:
        if not isinstance(raw_candidate, dict):
            continue
        candidate = deepcopy(raw_candidate)
        if _candidate_rejection_reason(candidate, slot):
            continue
        key = _candidate_key(candidate)
        if not key:
            continue
        if first_usable is None:
            first_usable = candidate
        if key in seen_in_slot:
            continue
        seen_in_slot.add(key)
        if key in used_keys:
            continue
        used_keys.add(key)
        return [candidate]
    if first_usable is not None:
        key = _candidate_key(first_usable)
        if key:
            used_keys.add(key)
        return [first_usable]
    return []


def _candidate_rejection_reason(candidate: JsonObject, slot: JsonObject) -> str | None:
    slot_payload = slot.get("slot") if isinstance(slot.get("slot"), dict) else slot
    hygiene_reason = publication_render_asset_hygiene_rejection_reason(candidate, slot=slot_payload)
    if hygiene_reason:
        return hygiene_reason
    if _slot_requires_animated_media(slot_payload) and not _candidate_has_animated_media(candidate):
        return "static_candidate_for_gif_slot"
    if _slot_requires_motion_video(slot_payload) and not _candidate_has_video_motion(candidate):
        return "static_candidate_for_video_slot"
    return None


def _slot_requires_motion_video(slot: JsonObject) -> bool:
    role = str(slot.get("role") or "").lower()
    return role == "background_texture"


def _slot_requires_animated_media(slot: JsonObject) -> bool:
    return str(slot.get("kind") or "").lower() == "gif"


def _candidate_has_video_motion(candidate: JsonObject) -> bool:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    if metadata.get("video_hls_url"):
        return True
    if str(metadata.get("api_scope") or "").lower() == "clips":
        return True
    return _candidate_media_extension(candidate) in {".mp4", ".webm", ".mov", ".m3u8"}


def _candidate_has_animated_media(candidate: JsonObject) -> bool:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    if metadata.get("video_hls_url"):
        return True
    if str(metadata.get("api_scope") or "").lower() == "clips":
        return True
    if str(metadata.get("media_rendition_format") or "").lower() in {"gif", "mp4", "webp"}:
        return True
    return _candidate_media_extension(candidate) in {".gif", ".mp4", ".webm", ".mov", ".m3u8"}


def _candidate_media_extension(candidate: JsonObject) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for value in (
        candidate.get("media_url"),
        metadata.get("video_hls_url"),
        candidate.get("thumbnail_url"),
        candidate.get("public_path"),
        candidate.get("local_path"),
    ):
        suffix = Path(urlparse(str(value or "").split("?", 1)[0]).path).suffix.lower()
        if suffix:
            return suffix
    return ""


def _candidate_sources(slot: JsonObject) -> Iterable[JsonObject]:
    yield from [candidate for candidate in slot.get("selected_candidates") or [] if isinstance(candidate, dict)]
    yield from [candidate for candidate in slot.get("candidate_pool") or [] if isinstance(candidate, dict)]


def _slots_by_key(slots: Iterable[JsonObject]) -> dict[tuple[int, str], JsonObject]:
    return {_slot_key(slot): slot for slot in slots if isinstance(slot, dict)}


def _slot_key(slot: JsonObject) -> tuple[int, str]:
    return int(slot.get("scene_id") or 0), str(slot.get("asset_id") or "")


def _slot_has_selection(slot: JsonObject | None) -> bool:
    return bool(isinstance(slot, dict) and slot.get("selected_candidates"))


def _slot_required(slot: JsonObject) -> bool:
    slot_payload = slot.get("slot") if isinstance(slot.get("slot"), dict) else slot
    return slot_payload.get("required", True) is not False


def _candidate_key(candidate: JsonObject) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    for value in (
        candidate.get("media_url"),
        metadata.get("video_hls_url"),
        candidate.get("thumbnail_url"),
        candidate.get("page_url"),
        metadata.get("pin_id"),
        metadata.get("giphy_id"),
        candidate.get("local_path"),
    ):
        if isinstance(value, str) and value.strip():
            return _canonical_url(value)
    return ""


def _canonical_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path}".rstrip("/")
    return str(value or "").strip().lower()


def _selection_keys(candidates: list[Any]) -> list[str]:
    return [_candidate_key(candidate) for candidate in candidates if isinstance(candidate, dict)]


def _provider_errors_for_failed_slots(failed_slots: list[str]) -> list[str]:
    if not failed_slots:
        return []
    errors = [f"Failed media slots after dedupe repair: {', '.join(failed_slots[:10])}"]
    if len(failed_slots) > 10:
        errors.append(f"...and {len(failed_slots) - 10} more failed media slots.")
    return errors


def _load_overlay_items(cache_dir: Path) -> dict[str, JsonObject]:
    result: dict[str, JsonObject] = {}
    for path in sorted(cache_dir.glob("*.json")):
        payload = _read_json(path)
        post_id = str(payload.get("post_id") or "")
        if post_id:
            result[post_id] = payload
    return result


def _read_json(path: Path) -> JsonObject:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
