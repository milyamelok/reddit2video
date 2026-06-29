from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from reddit2video.production import girly_static_v5 as flow


def test_vfx_annotation_skips_payload_already_on_canonical_recipe(monkeypatch, tmp_path: Path) -> None:
    payload_path = tmp_path / "post1.html-layout.generated.json"
    payload_path.write_text(
        json.dumps(
            {
                "composition_id": "girly-static-v5-final-post1",
                "layout_mode": flow.CANONICAL_LAYOUT_RECIPE,
                "scenes": [{"scene_id": 1, "vfx_timings": [{"target": ".card", "appear_frame": 4}]}],
            }
        ),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(flow, "run_command", lambda cmd, *, cwd: calls.append(cmd))

    outputs = flow.annotate_layout_vfx_payloads(
        {"post1": payload_path},
        defaults={"layout_recipe": flow.CANONICAL_LAYOUT_RECIPE},
        args=SimpleNamespace(force=False, force_payloads=False, force_vfx=False, vfx_timing_mode=""),
        paths=flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public"),
    )

    assert outputs == {"post1": payload_path}
    assert calls == []


def test_mark_payload_layout_recipe_preserves_scene_html_assets_and_timings(tmp_path: Path) -> None:
    payload_path = tmp_path / "post1.html-layout.generated.json"
    html = '<div data-asset-id="asset_1"><span class="sync-word">Не трогать</span></div>'
    payload = {
        "composition_id": "girly-static-v5-final-post1",
        "scenes": [
            {
                "scene_id": 1,
                "html": html,
                "asset_timings": {"asset_1": {"appear_frame": 3}},
                "word_timings": [{"index": 1, "word": "Не", "appear_frame": 0}],
                "vfx_timings": [{"target": '[data-asset-id="asset_1"]', "appear_frame": 3}],
            }
        ],
    }
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    flow.mark_payload_layout_recipe(payload_path, recipe=flow.CANONICAL_LAYOUT_RECIPE)

    updated = json.loads(payload_path.read_text(encoding="utf-8"))
    assert updated["layout_mode"] == flow.CANONICAL_LAYOUT_RECIPE
    assert updated["scenes"][0]["html"] == html
    assert updated["scenes"][0]["asset_timings"] == payload["scenes"][0]["asset_timings"]
    assert updated["scenes"][0]["word_timings"] == payload["scenes"][0]["word_timings"]
    assert updated["scenes"][0]["vfx_timings"] == payload["scenes"][0]["vfx_timings"]


def test_avatar_overlay_without_source_is_skipped(monkeypatch, tmp_path: Path) -> None:
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")
    base_video = tmp_path / "renders-final" / "post1-final-sync.mp4"
    base_video.parent.mkdir(parents=True)
    base_video.write_bytes(b"base")
    calls = []
    monkeypatch.setattr(flow, "run_command", lambda cmd, *, cwd: calls.append(cmd))

    outputs = flow.apply_avatar_overlay_to_renders(
        {"post1": base_video},
        defaults={"avatar_overlay": {"enabled": True, "source_video_path": ""}},
        args=SimpleNamespace(
            avatar_overlay=None,
            avatar_overlay_source_video="",
            avatar_overlay_width_px=None,
            avatar_overlay_position="",
            force=False,
            force_render=False,
        ),
        paths=paths,
    )

    assert outputs == {}
    assert calls == []
    config = flow.avatar_overlay_config(
        {"avatar_overlay": {"enabled": True, "source_video_path": ""}},
        SimpleNamespace(avatar_overlay=None, avatar_overlay_source_video="", avatar_overlay_width_px=None, avatar_overlay_position=""),
    )
    assert config["enabled"] is True
    assert config["auto_discover_source"] is True


def test_avatar_overlay_reuses_fresh_cached_output(monkeypatch, tmp_path: Path) -> None:
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")
    base_video = tmp_path / "renders-final" / "post1-final-sync.mp4"
    avatar_video = tmp_path / "avatar.mp4"
    out_path = paths.avatar_overlay_dir / "post1-final-sync-avatar.mp4"
    base_video.parent.mkdir(parents=True)
    paths.avatar_overlay_dir.mkdir(parents=True)
    base_video.write_bytes(b"base")
    avatar_video.write_bytes(b"avatar")
    out_path.write_bytes(b"cached")
    future = max(base_video.stat().st_mtime, avatar_video.stat().st_mtime) + 10
    os.utime(out_path, (future, future))
    calls = []
    monkeypatch.setattr(flow, "run_command", lambda cmd, *, cwd: calls.append(cmd))

    outputs = flow.apply_avatar_overlay_to_renders(
        {"post1": base_video},
        defaults={"avatar_overlay": {"enabled": True, "source_video_path": str(avatar_video)}},
        args=SimpleNamespace(
            avatar_overlay=None,
            avatar_overlay_source_video="",
            avatar_overlay_width_px=None,
            avatar_overlay_position="",
            force=False,
            force_render=False,
        ),
        paths=paths,
    )

    assert outputs == {"post1": out_path}
    assert calls == []


def test_avatar_overlay_auto_discovers_heygen_downloaded_video(monkeypatch, tmp_path: Path) -> None:
    paths = flow.FlowPaths(run_dir=tmp_path, public_dir=tmp_path / "public")
    base_video = tmp_path / "renders-final" / "post1-final-sync.mp4"
    avatar_video = tmp_path / "heygen-source.mp4"
    base_video.parent.mkdir(parents=True)
    paths.avatar_overlay_dir.mkdir(parents=True)
    paths.heygen_dir.mkdir(parents=True)
    base_video.write_bytes(b"base")
    avatar_video.write_bytes(b"avatar")
    (paths.heygen_dir / "heygen-avatar-manifest.json").write_text(
        json.dumps({"post1": {"downloaded_video": str(avatar_video)}}),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(flow, "run_command", lambda cmd, *, cwd: calls.append(cmd))

    outputs = flow.apply_avatar_overlay_to_renders(
        {"post1": base_video},
        defaults={"avatar_overlay": {"enabled": True, "source_video_path": ""}},
        args=SimpleNamespace(
            avatar_overlay=None,
            avatar_overlay_source_video="",
            avatar_overlay_width_px=None,
            avatar_overlay_position="",
            force=False,
            force_render=False,
        ),
        paths=paths,
    )

    assert outputs == {"post1": paths.avatar_overlay_dir / "post1-final-sync-avatar.mp4"}
    assert len(calls) == 1
    assert str(avatar_video) in calls[0]


def test_avatar_overlay_final_scene_start_uses_payload_frames(tmp_path: Path) -> None:
    payload_path = tmp_path / "post1.html-layout.generated.json"
    payload_path.write_text(
        json.dumps(
            {
                "fps": 30,
                "scenes": [
                    {"scene_id": 1, "start_frame": 0, "duration_frames": 90},
                    {"scene_id": 2, "start_frame": 90, "duration_frames": 60},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert flow.avatar_overlay_final_scene_start_sec(payload_path) == 3.0


def test_avatar_overlay_filter_fades_out_for_final_scene_guardrail() -> None:
    filter_complex = flow.avatar_overlay_filter(width_px=240, position="bottom_right", hide_from_sec=49.733)

    assert "fade=t=out:st=49.733:d=0.250:alpha=1" in filter_complex
    assert "overlay=x=W-w-12:y=H-h+6" in filter_complex


def test_heygen_download_cli_enables_avatar_overlay_auto_discovery() -> None:
    config = flow.avatar_overlay_config(
        {"avatar_overlay": {"enabled": False, "source_video_path": "", "auto_discover_source": True}},
        SimpleNamespace(
            avatar_overlay=None,
            avatar_overlay_source_video="",
            avatar_overlay_width_px=None,
            avatar_overlay_position="",
            with_heygen_avatar=True,
            heygen_download=True,
        ),
    )

    assert config["requested"] is True
    assert config["enabled"] is True
    assert config["auto_discover_source"] is True
    assert config["heygen_generation_in_scope"] is True


def test_production_run_recorder_writes_stage_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"posts":[]}', encoding="utf-8")
    paths = flow.FlowPaths(run_dir=tmp_path / "run", public_dir=tmp_path / "public")
    paths.run_dir.mkdir(parents=True)
    out_path = paths.run_dir / "stage.json"
    out_path.write_text('{"ok":true}', encoding="utf-8")

    recorder = flow.ProductionRunRecorder(
        path=paths.production_manifest,
        manifest_path=manifest_path,
        run_id="run1",
        paths=paths,
        post_ids=["post1"],
        defaults={"layout_recipe": flow.CANONICAL_LAYOUT_RECIPE},
        args=SimpleNamespace(
            layout_recipe="",
            vfx_timing_mode="",
            avatar_overlay=None,
            avatar_overlay_source_video="",
            avatar_overlay_width_px=None,
            avatar_overlay_position="",
        ),
    )
    recorder.record("stage", "cached", inputs=[manifest_path], outputs=[out_path], external_calls={"gemini": 0})
    recorder.complete({"done": True})

    manifest = json.loads(paths.production_manifest.read_text(encoding="utf-8"))
    assert manifest["schema"] == "reddit2video.girly_static_v5.production_run.v1"
    assert manifest["status"] == "completed"
    assert manifest["recipe"]["layout_recipe"] == flow.CANONICAL_LAYOUT_RECIPE
    assert manifest["stages"][0]["name"] == "stage"
    assert manifest["stages"][0]["status"] == "cached"
    assert manifest["summary"] == {"done": True}


def test_dry_run_stage_preview_reports_cached_recipe_and_skipped_avatar(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    paths = flow.FlowPaths(run_dir=tmp_path / "run", public_dir=tmp_path / "public")
    paths.html_payload_dir.mkdir(parents=True)
    paths.render_dir.mkdir(parents=True)
    payload_path = paths.html_payload_dir / "post1.html-layout.generated.json"
    render_path = paths.render_dir / "post1-final-sync.mp4"
    payload_path.write_text(
        json.dumps(
            {
                "layout_mode": flow.CANONICAL_LAYOUT_RECIPE,
                "scenes": [{"scene_id": 1, "vfx_timings": []}],
            }
        ),
        encoding="utf-8",
    )
    render_path.write_bytes(b"video")

    preview = flow.dry_run_stage_preview(
        manifest_path,
        [{"post_id": "post1"}],
        {"layout_recipe": flow.CANONICAL_LAYOUT_RECIPE, "avatar_overlay": {"enabled": False}},
        paths,
        SimpleNamespace(
            force=False,
            force_media=False,
            force_payloads=False,
            force_vfx=False,
            force_render=False,
            force_oracle=False,
            generate_tts=False,
            resolve_media=True,
            render=True,
            with_heygen_avatar=False,
            repair_pronunciation=None,
            render_visual_smoke=False,
            render_av_integrity=False,
            gemini_quality_oracle=False,
            layout_recipe="",
            vfx_timing_mode="",
            avatar_overlay=None,
            avatar_overlay_source_video="",
            avatar_overlay_width_px=None,
            avatar_overlay_position="",
        ),
    )

    by_name = {stage["name"]: stage["status"] for stage in preview}
    assert by_name["vfx_annotation"] == "cached"
    assert by_name["render"] == "cached"
    assert by_name["avatar_overlay"] == "skipped"
