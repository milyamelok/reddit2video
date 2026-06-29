from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parent.parent


def load_oracle_module() -> ModuleType:
    path = ROOT / "scripts/evaluate_video_quality_gemini.py"
    spec = importlib.util.spec_from_file_location("evaluate_video_quality_gemini", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_transcript_context_uses_scene_word_timings(tmp_path: Path) -> None:
    module = load_oracle_module()
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "scene_id": 18,
                        "start_frame": 1316,
                        "duration_frames": 58,
                        "word_timings": [
                            {"text": "Кто-то", "start_sec": 43.87, "end_sec": 44.14},
                            {"text": "ест", "start_sec": 44.14, "end_sec": 44.45},
                            {"text": "сладкую", "start_sec": 44.45, "end_sec": 44.81},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    context = module.transcript_context_from_payload(payload_path)

    assert "EXPECTED TRANSCRIPT" in context
    assert "s18 43.87-44.81s: Кто-то ест сладкую" in context


def test_transcript_context_falls_back_to_sync_caption_html(tmp_path: Path) -> None:
    module = load_oracle_module()
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "scene_id": 1,
                        "start_frame": 30,
                        "duration_frames": 60,
                        "html": '<div data-girly-sync-caption="true">Кто-то<br>ест &amp; считает</div>',
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    context = module.transcript_context_from_payload(payload_path)

    assert "s01 1.00-3.00s: Кто-то ест & считает" in context
