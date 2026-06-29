from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType


ROOT = Path(__file__).resolve().parent.parent


def load_flow_module() -> ModuleType:
    import reddit2video.production.girly_static_v5 as module

    return module


def test_gemini_oracle_gate_does_not_require_weighted_score() -> None:
    flow = load_flow_module()

    defects = flow.gemini_quality_oracle_defects(
        {
            "verdict": "pass",
            "publication_summary": "Looks ready.",
            "editorial_observations": [
                {
                    "area": "visual variety",
                    "assessment": "publication_ready",
                    "explanation": "Media supports the scenes.",
                    "visible_evidence": "Several distinct media scenes.",
                }
            ],
            "blocking_defects": [],
            "must_fix_before_publish": [],
            "anti_degradation_flags": [],
            "calibration_risk_flags": [],
        }
    )

    assert defects == []


def test_gemini_oracle_gate_blocks_editorial_major_issue() -> None:
    flow = load_flow_module()

    defects = flow.gemini_quality_oracle_defects(
        {
            "verdict": "pass",
            "editorial_observations": [
                {
                    "area": "visual variety",
                    "assessment": "major_issue",
                    "visible_evidence": "Most scenes are the same text card.",
                }
            ],
            "blocking_defects": [],
            "must_fix_before_publish": [],
            "anti_degradation_flags": [],
            "calibration_risk_flags": [],
        }
    )

    assert any(defect.startswith("major_issue:visual variety") for defect in defects)


def test_gemini_oracle_gate_blocks_anti_degradation_flags() -> None:
    flow = load_flow_module()

    defects = flow.gemini_quality_oracle_defects(
        {
            "verdict": "pass",
            "editorial_observations": [],
            "blocking_defects": [],
            "must_fix_before_publish": [],
            "anti_degradation_flags": ["mostly_text_cards"],
            "calibration_risk_flags": [],
        }
    )

    assert "anti_degradation_flags=mostly_text_cards" in defects


def test_gemini_oracle_gate_blocks_unreliable_oracle_verdict() -> None:
    flow = load_flow_module()

    defects = flow.gemini_quality_oracle_defects(
        {
            "verdict": "pass",
            "editorial_observations": [],
            "blocking_defects": [],
            "must_fix_before_publish": [],
            "anti_degradation_flags": [],
            "calibration_risk_flags": ["audio_not_confidently_checked"],
        }
    )

    assert "oracle_reliability_flags=audio_not_confidently_checked" in defects


def test_publication_readiness_release_gate_defaults_to_enforced() -> None:
    flow = load_flow_module()

    assert flow.should_fail_publication_readiness({}, SimpleNamespace(publication_readiness_fail=None)) is True
    assert (
        flow.should_fail_publication_readiness(
            {"publication_readiness_fail": False},
            SimpleNamespace(publication_readiness_fail=None),
        )
        is False
    )
    assert (
        flow.should_fail_publication_readiness(
            {"publication_readiness_fail": True},
            SimpleNamespace(publication_readiness_fail=False),
        )
        is False
    )


def test_publication_readiness_failure_message_uses_pending_or_defects() -> None:
    flow = load_flow_module()

    message = flow.publication_readiness_failure_message(
        {
            "verdict": "fail",
            "blocking_defects": [],
            "pending_reasons": ["post1:gemini_quality_oracle_report_missing"],
        }
    )

    assert "verdict=fail" in message
    assert "post1:gemini_quality_oracle_report_missing" in message


def test_flow_publication_manifest_keeps_blocking_and_pending_hold_reasons(tmp_path: Path) -> None:
    flow = load_flow_module()
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")
    video_path = tmp_path / "renders-final" / "post1-final-sync.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"fixture mp4")

    manifest = flow.build_flow_publication_manifest(
        {
            "verdict": "fail",
            "oracle_required": True,
            "blocking_defects": [],
            "pending_reasons": ["post1:gemini_quality_oracle_report_missing"],
            "items": [
                {
                    "post_id": "post1",
                    "status": "local_rejected",
                    "blocking_defects": ["publishability:not enough real media"],
                    "pending_reasons": ["gemini_quality_oracle_report_missing"],
                    "video_path": str(video_path),
                    "gemini_quality_oracle_report_path": str(
                        tmp_path / "gemini-quality-oracle" / "post1.video-quality.json"
                    ),
                    "evidence": {
                        "render_av_integrity": {
                            "format_duration_sec": 42.0,
                            "width": 720,
                            "height": 1280,
                            "fps": 30,
                            "audio_codec": "aac",
                        }
                    },
                }
            ],
        },
        paths=paths,
    )

    assert manifest["verdict"] == "fail"
    assert manifest["publish_allowed"] is False
    assert manifest["item_count"] == 1
    assert manifest["publishable_item_count"] == 0
    assert manifest["items"][0]["publish_allowed"] is False
    assert manifest["items"][0]["hold_reasons"] == [
        "publishability:not enough real media",
        "gemini_quality_oracle_report_missing",
    ]
    assert manifest["items"][0]["sha256"] == hashlib.sha256(b"fixture mp4").hexdigest()


def test_flow_publication_manifest_handles_no_render_video_path(tmp_path: Path) -> None:
    flow = load_flow_module()
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")

    manifest = flow.build_flow_publication_manifest(
        {
            "verdict": "fail",
            "oracle_required": True,
            "blocking_defects": [],
            "pending_reasons": ["post1:render_missing"],
            "items": [
                {
                    "post_id": "post1",
                    "status": "local_rejected",
                    "blocking_defects": [],
                    "pending_reasons": ["render_missing"],
                    "video_path": "",
                    "evidence": {},
                }
            ],
        },
        paths=paths,
    )

    assert manifest["items"][0]["video_path"] == ""
    assert manifest["items"][0]["sha256"] == ""
    assert manifest["items"][0]["size_bytes"] == 0


def test_resolve_and_hydrate_media_skips_existing_outputs(monkeypatch, tmp_path: Path) -> None:
    flow = load_flow_module()
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")
    paths.media_resolver.write_text("{}", encoding="utf-8")
    paths.media_resolver_deduped.write_text("{}", encoding="utf-8")
    paths.media_resolver_hydrated.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(flow, "run_command", lambda cmd, *, cwd: calls.append(cmd))

    class FailingMediaResolverNode:
        async def run(self, request):  # noqa: ANN001
            raise AssertionError("media resolver should not run when hydrated output already exists")

    monkeypatch.setattr(flow, "MediaResolverNode", FailingMediaResolverNode)

    result = asyncio.run(
        flow.resolve_and_hydrate_media(
            object(),
            defaults={},
            args=SimpleNamespace(
                force=False,
                media_concurrency=1,
                asset_download_concurrency=1,
                hls_duration_sec=1.0,
                media_selection_mode="",
            ),
            paths=paths,
            run_id="cached-run",
        )
    )

    assert result == paths.media_resolver_hydrated
    assert calls == []


def test_resolve_and_hydrate_media_downloads_missing_hydrated_output(monkeypatch, tmp_path: Path) -> None:
    flow = load_flow_module()
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")
    paths.media_resolver.write_text("{}", encoding="utf-8")
    paths.media_resolver_deduped.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(flow, "run_command", lambda cmd, *, cwd: calls.append(cmd))

    class FailingMediaResolverNode:
        async def run(self, request):  # noqa: ANN001
            raise AssertionError("media resolver should not run when resolver output already exists")

    monkeypatch.setattr(flow, "MediaResolverNode", FailingMediaResolverNode)

    result = asyncio.run(
        flow.resolve_and_hydrate_media(
            object(),
            defaults={},
            args=SimpleNamespace(
                force=False,
                media_concurrency=1,
                asset_download_concurrency=1,
                hls_duration_sec=1.0,
                media_selection_mode="",
            ),
            paths=paths,
            run_id="cached-run",
        )
    )

    assert result == paths.media_resolver_hydrated
    assert len(calls) == 1
    assert "scripts/download_selected_storyboard_assets.py" in calls[0]


def test_resolve_and_hydrate_media_force_media_bypasses_resolver_cache(monkeypatch, tmp_path: Path) -> None:
    flow = load_flow_module()
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")
    paths.media_resolver.write_text("{}", encoding="utf-8")
    paths.media_resolver_deduped.write_text("{}", encoding="utf-8")
    paths.media_resolver_hydrated.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(flow, "run_command", lambda cmd, *, cwd: calls.append(cmd))

    class CapturingMediaResolverNode:
        async def run(self, request):  # noqa: ANN001
            assert request.use_cache is False
            return {"items": [], "metadata": {"use_cache": request.use_cache}}

    monkeypatch.setattr(flow, "MediaResolverNode", CapturingMediaResolverNode)

    result = asyncio.run(
        flow.resolve_and_hydrate_media(
            object(),
            defaults={},
            args=SimpleNamespace(
                force=False,
                force_media=True,
                media_concurrency=1,
                asset_download_concurrency=1,
                hls_duration_sec=1.0,
                media_selection_mode="",
                media_selected_per_slot=None,
                media_max_slots_per_item=None,
                media_candidates_per_provider=None,
                media_contact_sheet_size=None,
            ),
            paths=paths,
            run_id="cached-run",
        )
    )

    assert result == paths.media_resolver_hydrated
    assert calls[0][1] == "scripts/repair_media_resolver_dedupe.py"
    assert calls[1][1] == "scripts/download_selected_storyboard_assets.py"


def test_scoped_media_outputs_do_not_clobber_canonical_resolver_paths(tmp_path: Path) -> None:
    flow = load_flow_module()
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")

    canonical = paths.media_resolver_hydrated
    paths.scope_media_outputs("posts-post1")

    assert paths.media_resolver == tmp_path / "media-resolver.posts-post1.json"
    assert paths.media_resolver_hydrated == tmp_path / "media-resolver.posts-post1.hydrated.json"
    assert paths.media_resolver_hydrated != canonical


def test_subset_tts_generation_preserves_existing_manifest_items(monkeypatch, tmp_path: Path) -> None:
    flow = load_flow_module()
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")
    paths.tts_dir.mkdir(parents=True)
    paths.public_audio.mkdir(parents=True)
    audio_path = paths.public_audio / "post1-inworld-Svetlana.mp3"
    alignment_path = paths.tts_dir / "post1.alignment.json"
    scene_lines_path = paths.tts_dir / "post1.scene-lines.tts.json"
    audio_path.write_bytes(b"audio")
    alignment_path.write_text("{}", encoding="utf-8")
    scene_lines_path.write_text("{}", encoding="utf-8")
    paths.tts_manifest.write_text(
        json.dumps(
            {
                "voice_id": "Svetlana",
                "items": {
                    "post2": {
                        "audio_path": "kept.mp3",
                        "alignment": "kept.alignment.json",
                        "scene_lines": "kept.scene-lines.json",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class DummyTTSClient:
        @classmethod
        def from_env(cls):  # noqa: ANN102
            return cls()

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(flow, "InworldTTSClient", DummyTTSClient)

    result = asyncio.run(
        flow.generate_inworld_tts(
            SimpleNamespace(
                items=[
                    SimpleNamespace(
                        post_id="post1",
                        title="Post one",
                        script={"storyboard_v2": {"scenes": [{"scene_id": 1, "voiceover_line": "Привет"}]}},
                    )
                ]
            ),
            defaults={"voice_id": "Svetlana"},
            args=SimpleNamespace(force=False),
            paths=paths,
        )
    )

    manifest = json.loads(paths.tts_manifest.read_text(encoding="utf-8"))
    assert sorted(manifest["items"]) == ["post1", "post2"]
    assert result["post1"]["status"] == "cached"


def test_build_remotion_payloads_skips_existing_payload(monkeypatch, tmp_path: Path) -> None:
    flow = load_flow_module()
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")
    out_path = paths.html_payload_dir / "post1.html-layout.generated.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("{}", encoding="utf-8")

    def fail_run_command(cmd, *, cwd):  # noqa: ANN001
        raise AssertionError("payload generation should not run when output already exists")

    monkeypatch.setattr(flow, "run_command", fail_run_command)

    outputs = flow.build_remotion_payloads(
        voiceover_batch=SimpleNamespace(items=[SimpleNamespace(post_id="post1")]),
        resolver_path=tmp_path / "media-resolver.hydrated.json",
        tts_outputs={},
        defaults={},
        args=SimpleNamespace(force=False),
        paths=paths,
    )

    assert outputs == {"post1": out_path}
