from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parent.parent


def load_module() -> ModuleType:
    path = ROOT / "scripts" / "repair_media_resolver_dedupe.py"
    spec = importlib.util.spec_from_file_location("repair_media_resolver_dedupe", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dedupe_repair_rejects_social_raw_search_replacement_for_video_slot() -> None:
    module = load_module()
    slot = {
        "scene_id": 1,
        "asset_id": "a1",
        "slot": {"kind": "video", "role": "subject"},
        "selected_candidates": [
            {
                "candidate_id": "P01",
                "provider": "pinterest",
                "title": "creator workout #fitness #stretch",
                "media_url": "https://v1.pinimg.com/videos/iht/hls/bad.m3u8",
                "metadata": {"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/bad.m3u8"},
            }
        ],
        "candidate_pool": [
            {
                "candidate_id": "P02",
                "provider": "pinterest",
                "title": "coffee cup pour",
                "media_url": "https://v1.pinimg.com/videos/iht/hls/good.m3u8",
                "metadata": {"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/good.m3u8"},
            }
        ],
    }

    selected = module._deduped_selection(slot, fallback_slot=slot, used_keys=set())

    assert [candidate["candidate_id"] for candidate in selected] == ["P02"]


def test_dedupe_repair_allows_static_replacement_for_subject_video_slot() -> None:
    module = load_module()
    slot = {
        "scene_id": 1,
        "asset_id": "a1",
        "slot": {"kind": "video", "role": "subject"},
        "selected_candidates": [],
        "candidate_pool": [
                {
                    "candidate_id": "P01",
                    "provider": "pinterest",
                    "title": "coffee cup on cafe table",
                    "media_url": "https://i.pinimg.com/originals/a/b/c.jpg",
                    "width": 1080,
                    "height": 1920,
            }
        ],
    }

    selected = module._deduped_selection(slot, fallback_slot=slot, used_keys=set())

    assert [candidate["candidate_id"] for candidate in selected] == ["P01"]


def test_dedupe_repair_does_not_resurrect_raw_search_results_from_failed_slot() -> None:
    module = load_module()
    slot = {
        "scene_id": 1,
        "asset_id": "a1",
        "status": "fail",
        "slot": {"kind": "image", "role": "subject"},
        "selected_candidates": [],
        "candidate_pool": [],
        "search_results": [
            {
                "provider": "serper_images",
                "query": "declining food",
                "candidates": [
                    {
                        "candidate_id": "S01",
                        "provider": "serper_images",
                        "title": "Generic article image",
                        "media_url": "https://example.com/article.jpg",
                        "width": 1200,
                        "height": 900,
                    }
                ],
            }
        ],
    }

    selected = module._deduped_selection(slot, fallback_slot=slot, used_keys=set())

    assert selected == []


def test_dedupe_repair_rejects_static_replacement_for_background_video_slot() -> None:
    module = load_module()
    slot = {
        "scene_id": 1,
        "asset_id": "a1",
        "slot": {"kind": "video", "role": "background_texture"},
        "selected_candidates": [],
        "candidate_pool": [
            {
                "candidate_id": "P01",
                "provider": "pinterest",
                "title": "coffee cup",
                "media_url": "https://i.pinimg.com/originals/a/b/c.jpg",
                "width": 1080,
                "height": 1920,
            }
        ],
    }

    assert module._deduped_selection(slot, fallback_slot=slot, used_keys=set()) == []


def test_repair_clears_selected_candidates_when_required_slot_fails_policy() -> None:
    module = load_module()
    stats = {
        "overlay_slots_used": 0,
        "duplicate_selected_replaced": 0,
        "failed_slots_after_repair": 0,
        "selected_assets": 0,
        "unique_selected_media": 0,
    }
    item = {
        "post_id": "post1",
        "resolved_slots": [
            {
                "scene_id": 3,
                "asset_id": "calorie_app",
                "slot": {"kind": "video", "required": True, "search_query_en": "calorie counter video"},
                "selected_candidates": [
                    {
                        "candidate_id": "bad-app",
                        "provider": "pinterest",
                        "title": "5 Best Free Calorie Counting Apps to Build Muscle and Lose Fat - 2024",
                        "media_url": "https://v1.pinimg.com/videos/iht/hls/app.m3u8",
                        "metadata": {"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/app.m3u8"},
                    }
                ],
            }
        ],
    }

    repaired = module._repair_item(item, overlay_item=None, used_keys=set(), stats=stats)
    slot = repaired["resolved_slots"][0]

    assert slot["status"] == "fail"
    assert slot["selected_candidates"] == []
    assert stats["failed_slots_after_repair"] == 1
