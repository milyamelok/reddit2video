#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.media_asset_hygiene import publication_render_asset_hygiene_rejection_reason  # noqa: E402
from reddit2video.vertex_image import VertexImageGenerationError, generate_vertex_express_image  # noqa: E402


JsonObject = dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair weak/failing subject media slots with generated image assets.")
    parser.add_argument("--resolver-input", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--asset-dir", default="")
    parser.add_argument("--model", default="gemini-3.1-flash-image-preview")
    parser.add_argument("--max-slots", type=int, default=10)
    parser.add_argument("--max-per-scene", type=int, default=1)
    parser.add_argument("--aspect-ratio", default="4:3")
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--budget-ledger", default="outputs/budgets/ai-image-generation-ledger.json")
    parser.add_argument("--max-budget-usd", type=float, default=20.0)
    parser.add_argument("--estimated-cost-per-image-usd", type=float, default=0.40)
    parser.add_argument(
        "--allow-paid-generation",
        action="store_true",
        help="Actually call the paid Vertex image generation endpoint.",
    )
    args = parser.parse_args()
    if not args.allow_paid_generation:
        payload = json.loads(Path(args.resolver_input).read_text(encoding="utf-8"))
        result = estimate_ai_image_repair(
            payload,
            max_slots=max(0, int(args.max_slots)),
            max_per_scene=max(0, int(args.max_per_scene)),
            replace_existing=bool(args.replace_existing),
            budget_ledger_path=Path(args.budget_ledger),
            max_budget_usd=Decimal(str(args.max_budget_usd)),
            estimated_cost_per_image_usd=Decimal(str(args.estimated_cost_per_image_usd)),
        )
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "paid_generation_attempted": False,
                    "note": "No paid image generation was attempted. Pass --allow-paid-generation to spend budget.",
                    **result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not args.out:
        raise SystemExit("--out is required with --allow-paid-generation.")
    if not args.asset_dir:
        raise SystemExit("--asset-dir is required with --allow-paid-generation.")

    payload = json.loads(Path(args.resolver_input).read_text(encoding="utf-8"))
    result = asyncio.run(
        repair_with_ai_images(
            payload,
            asset_dir=Path(args.asset_dir),
            model=str(args.model),
            max_slots=max(0, int(args.max_slots)),
            max_per_scene=max(0, int(args.max_per_scene)),
            aspect_ratio=str(args.aspect_ratio),
            replace_existing=bool(args.replace_existing),
            budget_ledger_path=Path(args.budget_ledger),
            max_budget_usd=Decimal(str(args.max_budget_usd)),
            estimated_cost_per_image_usd=Decimal(str(args.estimated_cost_per_image_usd)),
        )
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out_path), **result}, ensure_ascii=False, indent=2))
    return 0


async def repair_with_ai_images(
    payload: JsonObject,
    *,
    asset_dir: Path,
    model: str,
    max_slots: int,
    max_per_scene: int,
    aspect_ratio: str,
    budget_ledger_path: Path,
    max_budget_usd: Decimal,
    estimated_cost_per_image_usd: Decimal,
    replace_existing: bool = False,
) -> JsonObject:
    asset_dir.mkdir(parents=True, exist_ok=True)
    budget_ledger = _load_budget_ledger(
        budget_ledger_path,
        max_budget_usd=max_budget_usd,
        estimated_cost_per_image_usd=estimated_cost_per_image_usd,
    )
    attempted = 0
    repaired = 0
    failed = 0
    budget_blocked = 0
    budget_exhausted = False
    for item, slot in _repair_slot_records(payload, replace_existing=replace_existing, max_per_scene=max_per_scene):
        if attempted >= max_slots or budget_exhausted:
            break
        post_id = _safe(str(item.get("post_id") or "post"))
        scene_id = int(slot.get("scene_id") or 0)
        asset_id = _safe(str(slot.get("asset_id") or f"asset_{scene_id}"))
        prompt = _image_prompt(item=item, slot=slot)
        output_path = asset_dir / post_id / f"s{scene_id:03d}_{asset_id}_ai.png"
        budget_event_id = _reserve_budget_attempt(
            budget_ledger,
            budget_ledger_path,
            estimated_cost=estimated_cost_per_image_usd,
            post_id=post_id,
            scene_id=scene_id,
            asset_id=asset_id,
            model=model,
        )
        if budget_event_id is None:
            budget_blocked += 1
            budget_exhausted = True
            slot.setdefault("errors", []).append(
                f"ai_image_repair_budget_blocked:max_budget_usd={_money(max_budget_usd)}"
            )
            break
        attempted += 1
        try:
            metadata = await generate_vertex_express_image(
                prompt=prompt,
                output_path=output_path,
                model=model,
                aspect_ratio=aspect_ratio,
            )
        except (VertexImageGenerationError, Exception) as exc:
            failed += 1
            _finalize_budget_attempt(
                budget_ledger,
                budget_ledger_path,
                budget_event_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            slot.setdefault("errors", []).append(f"ai_image_repair_failed:{type(exc).__name__}: {exc}")
            continue
        local_path = str(metadata.get("output_path") or output_path)
        candidate = _ai_candidate(
            local_path=local_path,
            public_path=_public_path(Path(local_path)),
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            scene_id=scene_id,
            asset_id=asset_id,
            metadata=metadata,
        )
        slot["status"] = "pass"
        slot["selected_candidates"] = [candidate]
        slot["candidate_pool"] = [candidate]
        slot.setdefault("repair_notes", []).append("Repaired weak/failing subject media with generated image asset.")
        repaired += 1
        _finalize_budget_attempt(
            budget_ledger,
            budget_ledger_path,
            budget_event_id,
            status="succeeded",
            output_path=local_path,
        )
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        selected_count = sum(len(slot.get("selected_candidates") or []) for slot in item.get("resolved_slots") or [])
        failed_required = [
            slot for slot in item.get("resolved_slots") or [] if isinstance(slot, dict) and slot.get("status") == "fail"
        ]
        item["status"] = "fail" if failed_required else "pass"
        item.setdefault("metadata", {})["ai_image_repair_selected_asset_count"] = selected_count
    payload.setdefault("metadata", {})["ai_image_repair"] = {
        "asset_dir": str(asset_dir),
        "model": model,
        "max_slots": max_slots,
        "max_per_scene": max_per_scene,
        "replace_existing": replace_existing,
        "budget_ledger": str(budget_ledger_path),
        "max_budget_usd": _money(max_budget_usd),
        "estimated_cost_per_image_usd": _money(estimated_cost_per_image_usd),
        "estimated_spent_usd": budget_ledger.get("estimated_spent_usd", "0.00"),
        "attempted": attempted,
        "repaired": repaired,
        "failed": failed,
        "budget_blocked": budget_blocked,
        "repaired_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "attempted": attempted,
        "repaired": repaired,
        "failed": failed,
        "budget_blocked": budget_blocked,
        "estimated_spent_usd": budget_ledger.get("estimated_spent_usd", "0.00"),
    }


def estimate_ai_image_repair(
    payload: JsonObject,
    *,
    max_slots: int,
    max_per_scene: int,
    replace_existing: bool,
    budget_ledger_path: Path,
    max_budget_usd: Decimal,
    estimated_cost_per_image_usd: Decimal,
) -> JsonObject:
    ledger = _budget_snapshot(
        budget_ledger_path,
        max_budget_usd=max_budget_usd,
        estimated_cost_per_image_usd=estimated_cost_per_image_usd,
    )
    records = _repair_slot_records(payload, replace_existing=replace_existing, max_per_scene=max_per_scene)
    candidates = [_repair_slot_summary(item, slot) for item, slot in records]
    spent = Decimal(str(ledger.get("estimated_spent_usd") or "0"))
    remaining = max(Decimal("0"), max_budget_usd - spent)
    if estimated_cost_per_image_usd > 0:
        budget_attempt_capacity = int(remaining // estimated_cost_per_image_usd)
    else:
        budget_attempt_capacity = max_slots
    planned_attempts = min(len(candidates), max_slots, budget_attempt_capacity)
    estimated_increment = estimated_cost_per_image_usd * planned_attempts
    return {
        "eligible_slot_count": len(candidates),
        "max_per_scene": max_per_scene,
        "planned_attempts": planned_attempts,
        "blocked_by_max_slots": max(0, len(candidates) - max_slots),
        "blocked_by_budget": max(0, min(len(candidates), max_slots) - budget_attempt_capacity),
        "estimated_incremental_cost_usd": _money(estimated_increment),
        "estimated_cost_per_image_usd": _money(estimated_cost_per_image_usd),
        "max_budget_usd": _money(max_budget_usd),
        "budget_ledger": str(budget_ledger_path),
        "ledger_exists": budget_ledger_path.exists(),
        "ledger_attempt_count": ledger.get("attempt_count", 0),
        "estimated_spent_usd": ledger.get("estimated_spent_usd", "0.00"),
        "estimated_remaining_before_usd": _money(remaining),
        "estimated_remaining_after_usd": _money(max(Decimal("0"), remaining - estimated_increment)),
        "sample_slots": candidates[: min(10, len(candidates))],
    }


def _should_repair_slot(slot: JsonObject, *, replace_existing: bool = False) -> bool:
    slot_payload = slot.get("slot") if isinstance(slot.get("slot"), dict) else {}
    if str(slot_payload.get("role") or "").lower() == "background_texture":
        return False
    if str(slot_payload.get("kind") or "").lower() not in {"image", "video"}:
        return False
    if slot_payload.get("required", True) is False:
        return False
    selected = [candidate for candidate in slot.get("selected_candidates") or [] if isinstance(candidate, dict)]
    if not selected:
        return True
    if replace_existing:
        return True
    return any(publication_render_asset_hygiene_rejection_reason(candidate, slot=slot_payload) for candidate in selected)


def _repair_slot_records(
    payload: JsonObject,
    *,
    replace_existing: bool,
    max_per_scene: int,
) -> list[tuple[JsonObject, JsonObject]]:
    grouped: dict[tuple[str, int], list[tuple[JsonObject, JsonObject]]] = {}
    order: list[tuple[str, int]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        post_id = str(item.get("post_id") or "post")
        for slot in item.get("resolved_slots") or []:
            if not isinstance(slot, dict) or not _should_repair_slot(slot, replace_existing=replace_existing):
                continue
            key = (post_id, int(slot.get("scene_id") or 0))
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append((item, slot))

    records: list[tuple[JsonObject, JsonObject]] = []
    per_scene_limit = max_per_scene if max_per_scene > 0 else 10_000
    for key in order:
        scene_records = sorted(grouped[key], key=lambda pair: _slot_repair_score(pair[1]), reverse=True)
        records.extend(scene_records[:per_scene_limit])
    return records


def _repair_slot_summary(item: JsonObject, slot: JsonObject) -> JsonObject:
    slot_payload = slot.get("slot") if isinstance(slot.get("slot"), dict) else {}
    return {
        "post_id": str(item.get("post_id") or "post"),
        "scene_id": int(slot.get("scene_id") or 0),
        "asset_id": str(slot.get("asset_id") or ""),
        "status": str(slot.get("status") or ""),
        "kind": str(slot_payload.get("kind") or ""),
        "role": str(slot_payload.get("role") or ""),
        "query": str(slot.get("query") or slot_payload.get("search_query_en") or ""),
        "has_selected": bool(slot.get("selected_candidates")),
        "repair_score": _slot_repair_score(slot),
    }


def _slot_repair_score(slot: JsonObject) -> int:
    slot_payload = slot.get("slot") if isinstance(slot.get("slot"), dict) else {}
    query = str(slot.get("query") or slot_payload.get("search_query_en") or slot_payload.get("visual_prompt") or "").lower()
    selected = [candidate for candidate in slot.get("selected_candidates") or [] if isinstance(candidate, dict)]
    score = 0
    if str(slot.get("status") or "").lower() == "fail" or not selected:
        score += 100
    if any(publication_render_asset_hygiene_rejection_reason(candidate, slot=slot_payload) for candidate in selected):
        score += 50
    positive_terms = (
        "latte",
        "croissant",
        "pastry",
        "coffee",
        "cafe",
        "receipt",
        "plate",
        "crumb",
        "salad",
        "almond",
        "syrup",
    )
    negative_terms = (
        "fitness",
        "walking",
        "office",
        "declining",
        "abandoned",
        "nutrition label",
        "butter dough",
    )
    score += sum(6 for term in positive_terms if term in query)
    score -= sum(5 for term in negative_terms if term in query)
    return score


def _image_prompt(*, item: JsonObject, slot: JsonObject) -> str:
    slot_payload = slot.get("slot") if isinstance(slot.get("slot"), dict) else {}
    scene_text = ""
    scene = slot_payload.get("storyboard_scene") if isinstance(slot_payload.get("storyboard_scene"), dict) else {}
    if scene:
        scene_text = str(scene.get("voiceover_fragment") or scene.get("screen_text") or scene.get("visual_direction") or "")
    parts = [
        "Realistic editorial lifestyle photo for a vertical short-form video.",
        "No text, no captions, no UI, no screenshots, no logos, no watermark, no product catalog, no recipe tutorial.",
        f"Video topic: {item.get('title') or ''}.",
        f"Scene context: {scene_text}.",
        f"Visual brief: {slot_payload.get('visual_prompt') or slot_payload.get('search_query_en') or slot.get('query') or ''}.",
        "Style: clean natural light, casual cafe/wellness editorial, phone-readable subject, publication quality.",
    ]
    return " ".join(part for part in parts if part.strip())


def _ai_candidate(
    *,
    local_path: str,
    public_path: str,
    prompt: str,
    model: str,
    aspect_ratio: str,
    scene_id: int,
    asset_id: str,
    metadata: JsonObject,
) -> JsonObject:
    return {
        "candidate_id": f"AI_{scene_id:03d}_{asset_id}",
        "provider": "ai_generated",
        "query": prompt,
        "title": f"Generated editorial image for {asset_id}",
        "page_url": "",
        "thumbnail_url": local_path,
        "media_url": local_path,
        "width": None,
        "height": None,
        "position": 1,
        "media_type": "image",
        "local_path": local_path,
        "public_path": public_path,
        "local_content_type": metadata.get("mime_type") or "image/png",
        "metadata": {
            "local_media_path": local_path,
            "generated": True,
            "repair_source": "ai_image_repair",
            "model": model,
            "aspect_ratio": aspect_ratio,
            "usage_metadata": metadata.get("usage_metadata") or {},
            "response_text": metadata.get("text") or "",
        },
    }


def _load_budget_ledger(
    path: Path,
    *,
    max_budget_usd: Decimal,
    estimated_cost_per_image_usd: Decimal,
) -> JsonObject:
    ledger = _budget_snapshot(
        path,
        max_budget_usd=max_budget_usd,
        estimated_cost_per_image_usd=estimated_cost_per_image_usd,
    )
    ledger["max_budget_usd"] = _money(max_budget_usd)
    ledger["estimated_cost_per_image_usd"] = _money(estimated_cost_per_image_usd)
    _recompute_budget_totals(ledger)
    _write_budget_ledger(path, ledger)
    return ledger


def _budget_snapshot(
    path: Path,
    *,
    max_budget_usd: Decimal,
    estimated_cost_per_image_usd: Decimal,
) -> JsonObject:
    if path.exists():
        ledger = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(ledger, dict):
            raise SystemExit(f"Budget ledger is not a JSON object: {path}")
    else:
        ledger = {
            "kind": "ai_image_generation_budget_ledger",
            "events": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ledger["max_budget_usd"] = _money(max_budget_usd)
    ledger["estimated_cost_per_image_usd"] = _money(estimated_cost_per_image_usd)
    _recompute_budget_totals(ledger)
    return ledger


def _reserve_budget_attempt(
    ledger: JsonObject,
    path: Path,
    *,
    estimated_cost: Decimal,
    post_id: str,
    scene_id: int,
    asset_id: str,
    model: str,
) -> int | None:
    max_budget = Decimal(str(ledger.get("max_budget_usd") or "0"))
    spent = Decimal(str(ledger.get("estimated_spent_usd") or "0"))
    if spent + estimated_cost > max_budget:
        return None
    events = ledger.setdefault("events", [])
    if not isinstance(events, list):
        raise SystemExit(f"Budget ledger events must be a list: {path}")
    event_id = len(events) + 1
    events.append(
        {
            "id": event_id,
            "status": "reserved",
            "estimated_cost_usd": _money(estimated_cost),
            "post_id": post_id,
            "scene_id": scene_id,
            "asset_id": asset_id,
            "model": model,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _recompute_budget_totals(ledger)
    _write_budget_ledger(path, ledger)
    return event_id


def _finalize_budget_attempt(
    ledger: JsonObject,
    path: Path,
    event_id: int,
    *,
    status: str,
    error: str = "",
    output_path: str = "",
) -> None:
    events = ledger.get("events")
    if not isinstance(events, list):
        return
    for event in events:
        if isinstance(event, dict) and event.get("id") == event_id:
            event["status"] = status
            event["finished_at"] = datetime.now(timezone.utc).isoformat()
            if error:
                event["error"] = error[:1000]
            if output_path:
                event["output_path"] = output_path
            break
    _recompute_budget_totals(ledger)
    _write_budget_ledger(path, ledger)


def _recompute_budget_totals(ledger: JsonObject) -> None:
    events = ledger.get("events")
    total = Decimal("0")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                total += Decimal(str(event.get("estimated_cost_usd") or "0"))
    ledger["attempt_count"] = len(events) if isinstance(events, list) else 0
    ledger["estimated_spent_usd"] = _money(total)
    max_budget = Decimal(str(ledger.get("max_budget_usd") or "0"))
    ledger["estimated_remaining_usd"] = _money(max(Decimal("0"), max_budget - total))
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()


def _write_budget_ledger(path: Path, ledger: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


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
