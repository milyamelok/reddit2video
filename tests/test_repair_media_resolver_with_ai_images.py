from __future__ import annotations

import asyncio
from decimal import Decimal
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = ROOT / "scripts" / "repair_media_resolver_with_ai_images.py"
    spec = importlib.util.spec_from_file_location("repair_media_resolver_with_ai_images", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ai_image_repair_reserves_budget_before_paid_generation(monkeypatch, tmp_path) -> None:
    module = load_module()
    calls: list[str] = []

    async def fake_generate_vertex_express_image(*, prompt, output_path, model, aspect_ratio):  # noqa: ANN001
        calls.append(prompt)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-png")
        return {
            "output_path": str(output_path),
            "mime_type": "image/png",
            "usage_metadata": {},
            "text": "",
        }

    monkeypatch.setattr(module, "generate_vertex_express_image", fake_generate_vertex_express_image)
    payload = {
        "items": [
            {
                "post_id": "post1",
                "title": "Latte story",
                "resolved_slots": [
                    {
                        "scene_id": 1,
                        "asset_id": "a1",
                        "status": "pass",
                        "slot": {"kind": "video", "role": "subject", "required": True, "search_query_en": "latte"},
                        "selected_candidates": [{"provider": "serper_images", "title": "old", "media_url": "https://x/a.jpg"}],
                    },
                    {
                        "scene_id": 2,
                        "asset_id": "a2",
                        "status": "pass",
                        "slot": {"kind": "video", "role": "subject", "required": True, "search_query_en": "croissant"},
                        "selected_candidates": [{"provider": "serper_images", "title": "old", "media_url": "https://x/b.jpg"}],
                    },
                ],
            }
        ]
    }

    result = asyncio.run(
        module.repair_with_ai_images(
            payload,
            asset_dir=tmp_path / "assets",
            model="gemini-test-image",
            max_slots=2,
            max_per_scene=1,
            aspect_ratio="4:3",
            budget_ledger_path=tmp_path / "budget.json",
            max_budget_usd=Decimal("0.40"),
            estimated_cost_per_image_usd=Decimal("0.40"),
            replace_existing=True,
        )
    )

    assert len(calls) == 1
    assert result["attempted"] == 1
    assert result["repaired"] == 1
    assert result["budget_blocked"] == 1
    assert payload["items"][0]["resolved_slots"][0]["selected_candidates"][0]["provider"] == "ai_generated"
    assert "ai_image_repair_budget_blocked" in payload["items"][0]["resolved_slots"][1]["errors"][0]

    ledger = module.json.loads((tmp_path / "budget.json").read_text(encoding="utf-8"))
    assert ledger["attempt_count"] == 1
    assert ledger["estimated_spent_usd"] == "0.40"
    assert ledger["estimated_remaining_usd"] == "0.00"


def test_ai_image_repair_estimate_is_read_only(tmp_path) -> None:
    module = load_module()
    ledger_path = tmp_path / "missing-budget.json"
    payload = {
        "items": [
            {
                "post_id": "post1",
                "resolved_slots": [
                    {
                        "scene_id": 1,
                        "asset_id": "a1",
                        "status": "fail",
                        "slot": {"kind": "video", "role": "subject", "required": True, "search_query_en": "latte"},
                        "selected_candidates": [],
                    },
                    {
                        "scene_id": 2,
                        "asset_id": "bg",
                        "status": "fail",
                        "slot": {"kind": "video", "role": "background_texture", "required": True},
                        "selected_candidates": [],
                    },
                ],
            }
        ]
    }

    result = module.estimate_ai_image_repair(
        payload,
        max_slots=10,
        max_per_scene=1,
        replace_existing=False,
        budget_ledger_path=ledger_path,
        max_budget_usd=Decimal("20.00"),
        estimated_cost_per_image_usd=Decimal("0.40"),
    )

    assert result["eligible_slot_count"] == 1
    assert result["planned_attempts"] == 1
    assert result["estimated_incremental_cost_usd"] == "0.40"
    assert result["estimated_remaining_after_usd"] == "19.60"
    assert ledger_path.exists() is False
