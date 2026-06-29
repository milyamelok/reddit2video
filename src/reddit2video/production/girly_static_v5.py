#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reddit2video.gemini import GeminiClient  # noqa: E402
from reddit2video.inworld import InworldTTSClient  # noqa: E402
from reddit2video.models import (  # noqa: E402
    MediaResolverNodeRequest,
    RedditThreadBatch,
    RedditThreadRequest,
    VoiceoverScriptNodeRequest,
    to_jsonable,
)
from reddit2video.nodes.media_resolver import MediaResolverNode  # noqa: E402
from reddit2video.nodes.reddit import RedditParser  # noqa: E402
from reddit2video.nodes.voiceover_script import VoiceoverScriptNode  # noqa: E402
from reddit2video.pronunciation_repair import PronunciationIssue, repair_pronunciation_audio  # noqa: E402
from reddit2video.publication_readiness import (  # noqa: E402
    build_publication_readiness_report,
    gemini_quality_oracle_defects as publication_oracle_defects,
)
from reddit2video.render_av_integrity import inspect_render_av_integrity  # noqa: E402
from reddit2video.render_visual_smoke import inspect_render_visual_smoke  # noqa: E402
from reddit2video.serialization import reddit_batch_from_dict, scene_pipeline_batch_from_dict, voiceover_batch_from_dict  # noqa: E402
from reddit2video.source_quality_gate import (  # noqa: E402
    DEFAULT_SOURCE_QUALITY_FALLBACK_MODELS,
    DEFAULT_SOURCE_QUALITY_MIN_SCORE,
    DEFAULT_SOURCE_QUALITY_MODEL,
    evaluate_source_quality_batch,
    filter_thread_batch_by_source_quality,
)
from reddit2video.storyboard_assets import storyboard_assets_to_scene_batch  # noqa: E402
from reddit2video.tts_text import normalize_russian_tts_orthography  # noqa: E402
from reddit2video.video_publishability import inspect_html_payload  # noqa: E402

Json = dict[str, Any]
CANONICAL_LAYOUT_RECIPE = "b_layout_staged_vfx_no_labels"
DEFAULT_VFX_TIMING_MODE = "cached_gemini_or_deterministic"
DEFAULT_AVATAR_OVERLAY_WIDTH_PX = 240
DEFAULT_AVATAR_OVERLAY_POSITION = "bottom_right"

HeyGenInternalClient: Any | None = None
_latest_storage_state: Any | None = None


class ProductionRunRecorder:
    def __init__(
        self,
        *,
        path: Path,
        manifest_path: Path,
        run_id: str,
        paths: "FlowPaths",
        post_ids: list[str],
        defaults: Json,
        args: argparse.Namespace,
    ) -> None:
        self.path = path
        self.payload: Json = {
            "schema": "reddit2video.girly_static_v5.production_run.v1",
            "status": "running",
            "run_id": run_id,
            "run_dir": display(paths.run_dir),
            "public_dir": display(paths.public_dir),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "input_manifest": production_file_entry(manifest_path),
            "post_ids": post_ids,
            "recipe": {
                "source_quality_gate": source_quality_gate_config(defaults, args),
                "layout_recipe": layout_recipe(defaults, args),
                "vfx_timing": {
                    "mode": vfx_timing_mode(defaults, args),
                    "model": vfx_timing_model(defaults),
                },
                "avatar_overlay": avatar_overlay_config(defaults, args),
            },
            "stages": [],
            "external_call_totals": {},
            "summary": {},
        }

    def record(
        self,
        name: str,
        status: str,
        *,
        inputs: list[Path | None] | None = None,
        outputs: list[Path | None] | None = None,
        external_calls: Json | None = None,
        metadata: Json | None = None,
    ) -> None:
        stage = {
            "name": name,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "inputs": [production_file_entry(path) for path in inputs or [] if path is not None],
            "outputs": [production_file_entry(path) for path in outputs or [] if path is not None],
            "external_calls": external_calls or {},
            "metadata": metadata or {},
        }
        stages = [item for item in self.payload["stages"] if item.get("name") != name]
        stages.append(stage)
        self.payload["stages"] = stages
        totals = dict(self.payload.get("external_call_totals") or {})
        for key, value in (external_calls or {}).items():
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0) + value
        self.payload["external_call_totals"] = totals
        self.payload["updated_at"] = stage["updated_at"]
        self.write()

    def complete(self, summary: Json) -> None:
        self.payload["status"] = "completed"
        self.payload["summary"] = summary
        self.payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.write()

    def write(self) -> None:
        write_json(self.path, self.payload)


def main() -> int:
    return asyncio.run(_amain(parse_args()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the static_girly_2 four-post production flow.")
    parser.add_argument("--manifest", default="config/girly_static_v5_posts_4.json")
    parser.add_argument("--run-id", default="", help="Defaults to manifest run_id_prefix + UTC timestamp.")
    parser.add_argument("--env-file", action="append", default=[".env.iac", ".env"])
    parser.add_argument("--dry-run", action="store_true", help="Print the execution graph without calling external APIs.")
    parser.add_argument("--force", action="store_true", help="Regenerate files that already exist.")
    parser.add_argument("--post-id", action="append", default=[], help="Process only this post id; repeat or comma-separate.")
    parser.add_argument("--force-media", action="store_true", help="Refresh resolver/dedupe/hydrate only, bypassing resolver item cache.")
    parser.add_argument("--force-source-quality", action="store_true", help="Regenerate the source-quality gate report.")
    parser.add_argument("--force-payloads", action="store_true", help="Regenerate Remotion payloads without forcing upstream steps.")
    parser.add_argument("--force-vfx", action="store_true", help="Regenerate layout-only staged VFX annotation.")
    parser.add_argument("--force-render", action="store_true", help="Regenerate MP4 renders without forcing upstream steps.")
    parser.add_argument("--force-oracle", action="store_true", help="Regenerate Gemini post-render oracle reports.")
    parser.add_argument("--layout-recipe", default="", help="Production layout recipe. Defaults to manifest or canonical v5 recipe.")
    parser.add_argument(
        "--vfx-timing-mode",
        choices=["cached_gemini_or_deterministic", "deterministic"],
        default="",
        help="How to annotate non-caption layout VFX timings.",
    )

    parser.add_argument("--comment-limit", type=int, default=160)
    parser.add_argument("--comment-depth", type=int, default=8)
    parser.add_argument("--comment-sort", default="top")
    parser.add_argument("--source-quality-gate", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--source-quality-model", default="")
    parser.add_argument("--source-quality-fallback-model", action="append", default=[])
    parser.add_argument("--source-quality-min-score", type=int, default=None)
    parser.add_argument("--source-quality-accept-safe-mode", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--source-quality-concurrency", type=int, default=None)
    parser.add_argument("--voiceover-concurrency", type=int, default=2)
    parser.add_argument("--media-concurrency", type=int, default=2)
    parser.add_argument("--media-selected-per-slot", type=int, default=None)
    parser.add_argument("--media-max-slots-per-item", type=int, default=None)
    parser.add_argument("--media-candidates-per-provider", type=int, default=None)
    parser.add_argument("--media-contact-sheet-size", type=int, default=None)
    parser.add_argument("--asset-download-concurrency", type=int, default=None)
    parser.add_argument("--hls-duration-sec", type=float, default=8.0)
    parser.add_argument("--media-selection-mode", choices=["gemini", "heuristic", "first"], default="")
    parser.add_argument("--remotion-concurrency", type=int, default=2)
    parser.add_argument("--render", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--resolve-media", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--generate-tts", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--quality-gate", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--quality-gate-min-scenes", type=int, default=None)
    parser.add_argument("--quality-gate-min-duration-sec", type=float, default=None)
    parser.add_argument("--quality-gate-min-media-scene-ratio", type=float, default=None)
    parser.add_argument("--quality-gate-min-unique-assets", type=int, default=None)
    parser.add_argument("--quality-gate-min-video-assets", type=int, default=None)
    parser.add_argument("--quality-gate-min-real-media-scene-ratio", type=float, default=None)
    parser.add_argument("--quality-gate-max-generated-visual-scene-ratio", type=float, default=None)
    parser.add_argument("--quality-gate-max-text-only-run", type=int, default=None)
    parser.add_argument("--quality-gate-require-audio", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--render-visual-smoke", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--render-visual-smoke-fail", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--render-av-integrity", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--render-av-integrity-fail", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--gemini-quality-oracle", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--gemini-quality-oracle-model", default="")
    parser.add_argument("--gemini-quality-oracle-fail", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--publication-readiness-oracle-required", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--publication-readiness-fail", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--repair-pronunciation", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--pronunciation-repair-model", default="")
    parser.add_argument("--pronunciation-repair-strategy", choices=["full_revoice", "splice"], default="")
    parser.add_argument("--pronunciation-repair-max-issues", type=int, default=4)
    parser.add_argument("--pronunciation-repair-min-confidence", type=float, default=0.55)
    parser.add_argument("--pronunciation-force-fix", action="append", default=[])
    parser.add_argument("--verify-pronunciation-repair", action=argparse.BooleanOptionalAction, default=True)

    parser.add_argument("--with-heygen-avatar", action="store_true")
    parser.add_argument("--heygen-template-video-id", default="")
    parser.add_argument("--heygen-storage-state", default="")
    parser.add_argument("--heygen-submit", action="store_true")
    parser.add_argument("--heygen-wait", action="store_true")
    parser.add_argument("--heygen-download", action="store_true")
    parser.add_argument("--avatar-overlay", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--avatar-overlay-source-video", default="")
    parser.add_argument("--avatar-overlay-width-px", type=int, default=None)
    parser.add_argument("--avatar-overlay-position", choices=["bottom_right"], default="")
    return parser.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    for env_file in args.env_file:
        load_env_file(ROOT / env_file)

    manifest_path = resolve_path(args.manifest)
    manifest = read_json(manifest_path)
    posts = validate_posts(manifest)
    selected_post_ids = requested_post_ids(args, posts)
    scoped_posts = filter_manifest_posts(posts, selected_post_ids)
    defaults = manifest.get("defaults") if isinstance(manifest.get("defaults"), dict) else {}
    run_id = args.run_id or make_run_id(str(manifest.get("run_id_prefix") or "girly-static-v5"))
    run_dir = ROOT / "outputs" / "girly-static-v5" / run_id
    public_dir = ROOT / "remotion" / "public" / "girly-static-v5" / run_id
    paths = FlowPaths(run_dir=run_dir, public_dir=public_dir)
    if selected_post_ids:
        paths.scope_media_outputs(scope_token_for_posts(selected_post_ids))

    if args.dry_run:
        print(json.dumps(dry_run_plan(manifest_path, scoped_posts, defaults, run_id, paths, args), ensure_ascii=False, indent=2))
        return 0

    ensure_dirs(paths)
    (run_dir / "manifest.input.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    recorder = ProductionRunRecorder(
        path=paths.production_manifest,
        manifest_path=manifest_path,
        run_id=run_id,
        paths=paths,
        post_ids=[post["post_id"] for post in scoped_posts],
        defaults=defaults,
        args=args,
    )
    recorder.record("inputs", "generated", inputs=[manifest_path], outputs=[run_dir / "manifest.input.json"])

    reddit_before = output_snapshot([paths.reddit_threads])
    reddit_batch = await fetch_reddit_threads(posts, args=args, out_path=paths.reddit_threads)
    recorder.record(
        "reddit",
        stage_status_from_snapshot([paths.reddit_threads], reddit_before, force=args.force),
        inputs=[manifest_path],
        outputs=[paths.reddit_threads],
        external_calls={"reddit_fetch": len(posts)} if not snapshot_had_all_outputs(reddit_before) or args.force else {},
    )

    source_quality_report: Json = {}
    if should_run_source_quality_gate(defaults, args):
        source_before = output_snapshot([paths.reddit_threads_filtered, paths.source_quality_report])
        reddit_batch, source_quality_report = await apply_source_quality_gate(
            reddit_batch,
            defaults=defaults,
            args=args,
            paths=paths,
        )
        source_status = stage_status_from_snapshot(
            [paths.reddit_threads_filtered, paths.source_quality_report],
            source_before,
            force=args.force or bool(getattr(args, "force_source_quality", False)),
        )
        source_metadata = source_quality_report.get("metadata") if isinstance(source_quality_report, dict) else {}
        recorder.record(
            "source_quality_gate",
            source_status,
            inputs=[paths.reddit_threads],
            outputs=[paths.reddit_threads_filtered, paths.source_quality_report],
            external_calls={"gemini_source_quality": int(source_metadata.get("gemini_calls") or 0)}
            if source_status == "generated"
            else {},
            metadata=source_quality_gate_config(defaults, args),
        )
        if not reddit_batch.threads:
            raise SystemExit("Source-quality gate rejected every post; nothing left for Stage 1.")
    else:
        recorder.record(
            "source_quality_gate",
            "skipped",
            inputs=[paths.reddit_threads],
            outputs=[paths.reddit_threads_filtered, paths.source_quality_report],
            metadata=source_quality_gate_config(defaults, args),
        )

    voiceover_input_path = paths.reddit_threads_filtered if source_quality_report else paths.reddit_threads
    voiceover_before = output_snapshot([paths.voiceover])
    voiceover_batch = await generate_voiceover(
        reddit_batch,
        defaults=defaults,
        args=args,
        out_path=paths.voiceover,
        input_path=voiceover_input_path,
    )
    voiceover_status = stage_status_from_snapshot([paths.voiceover], voiceover_before, force=args.force)
    recorder.record(
        "voiceover",
        voiceover_status,
        inputs=[voiceover_input_path],
        outputs=[paths.voiceover],
        external_calls={"gemini_voiceover": len(reddit_batch.threads)} if voiceover_status == "generated" else {},
        metadata={"model": str(defaults.get("voiceover_model") or "gemini-3.1-pro-preview")},
    )

    media_plan_before = output_snapshot([paths.media_plan])
    scene_batch = build_storyboard_media_plan(voiceover_batch, run_id=run_id, out_path=paths.media_plan, force=args.force)
    recorder.record(
        "media_plan",
        stage_status_from_snapshot([paths.media_plan], media_plan_before, force=args.force),
        inputs=[paths.voiceover],
        outputs=[paths.media_plan],
    )
    if selected_post_ids:
        voiceover_batch = filter_batch_by_post_ids(voiceover_batch, selected_post_ids, label="voiceover")
        scene_batch = filter_batch_by_post_ids(scene_batch, selected_post_ids, label="media_plan")

    media_before = output_snapshot([paths.media_resolver, paths.media_resolver_deduped, paths.media_resolver_hydrated])
    if args.resolve_media:
        resolver_path = await resolve_and_hydrate_media(scene_batch, defaults=defaults, args=args, paths=paths, run_id=run_id)
        media_status = stage_status_from_snapshot(
            [paths.media_resolver, paths.media_resolver_deduped, paths.media_resolver_hydrated],
            media_before,
            force=args.force or bool(getattr(args, "force_media", False)),
        )
    else:
        resolver_path = paths.media_resolver_hydrated
        if not resolver_path.exists():
            raise SystemExit(f"--no-resolve-media requires existing resolver: {resolver_path}")
        media_status = "skipped"
    recorder.record(
        "media",
        media_status,
        inputs=[paths.media_plan],
        outputs=[paths.media_resolver, paths.media_resolver_deduped, paths.media_resolver_hydrated],
        external_calls={"media_resolution": 1, "asset_download": 1} if media_status == "generated" and args.resolve_media else {},
        metadata={"selection_mode": media_selection_mode(defaults, args), "resolver_path": display(resolver_path)},
    )

    tts_outputs = {}
    tts_before = output_snapshot([paths.tts_manifest])
    if args.generate_tts:
        tts_outputs = await generate_inworld_tts(voiceover_batch, defaults=defaults, args=args, paths=paths)
    elif paths.tts_manifest.exists():
        tts_outputs = read_json(paths.tts_manifest).get("items", {})
    recorder.record(
        "tts",
        tts_stage_status(tts_outputs, generated=bool(args.generate_tts), before=tts_before, manifest_path=paths.tts_manifest),
        inputs=[paths.voiceover],
        outputs=[paths.tts_manifest],
        external_calls={"inworld_tts": count_tts_generated_items(tts_outputs)} if args.generate_tts else {},
    )

    pronunciation_before = output_snapshot([paths.tts_manifest])
    if should_repair_pronunciation(defaults, args) and tts_outputs:
        tts_outputs = await repair_tts_pronunciations(tts_outputs, defaults=defaults, args=args, paths=paths)
        recorder.record(
            "pronunciation_repair",
            stage_status_from_snapshot([paths.tts_manifest], pronunciation_before, force=args.force),
            inputs=[paths.tts_manifest],
            outputs=[paths.tts_manifest],
            external_calls={"gemini_pronunciation_repair": len(tts_outputs)},
        )
    else:
        recorder.record("pronunciation_repair", "skipped", inputs=[paths.tts_manifest], outputs=[paths.tts_manifest])

    if args.with_heygen_avatar:
        heygen_before = output_snapshot([paths.heygen_dir / "heygen-avatar-manifest.json"])
        generate_heygen_avatars(tts_outputs, defaults=defaults, args=args, paths=paths)
        recorder.record(
            "legacy_heygen_generation",
            stage_status_from_snapshot([paths.heygen_dir / "heygen-avatar-manifest.json"], heygen_before, force=True),
            inputs=[paths.tts_manifest],
            outputs=[paths.heygen_dir / "heygen-avatar-manifest.json"],
            external_calls={"heygen_internal_clone": len(tts_outputs)},
        )
    else:
        recorder.record("legacy_heygen_generation", "skipped", inputs=[paths.tts_manifest])

    payload_before = output_snapshot(expected_payload_paths(voiceover_batch, paths))
    html_payloads = build_remotion_payloads(
        voiceover_batch=voiceover_batch,
        resolver_path=resolver_path,
        tts_outputs=tts_outputs,
        defaults=defaults,
        args=args,
        paths=paths,
    )
    payload_status = stage_status_from_snapshot(
        list(html_payloads.values()),
        payload_before,
        force=args.force or bool(getattr(args, "force_payloads", False)),
    )
    recorder.record(
        "layout_payload",
        payload_status,
        inputs=[paths.voiceover, resolver_path, paths.tts_manifest],
        outputs=list(html_payloads.values()),
        metadata={"layout_recipe": layout_recipe(defaults, args)},
    )

    vfx_before = output_snapshot(list(html_payloads.values()))
    html_payloads = annotate_layout_vfx_payloads(
        html_payloads,
        defaults=defaults,
        args=args,
        paths=paths,
    )
    vfx_status = stage_status_from_snapshot(
        list(html_payloads.values()),
        vfx_before,
        force=args.force or bool(getattr(args, "force_payloads", False)) or bool(getattr(args, "force_vfx", False)),
    )
    recorder.record(
        "vfx_annotation",
        vfx_status,
        inputs=list(html_payloads.values()),
        outputs=list(html_payloads.values()),
        external_calls={"gemini_vfx_timing": len(html_payloads)} if vfx_status == "generated" and vfx_timing_mode(defaults, args) != "deterministic" else {},
        metadata={"mode": vfx_timing_mode(defaults, args), "layout_recipe": layout_recipe(defaults, args)},
    )

    publishability_before = output_snapshot([paths.publishability_dir / f"{post_id}.publishability.json" for post_id in html_payloads])
    publishability_reports = inspect_remotion_payload_publishability(
        html_payloads,
        defaults=defaults,
        args=args,
        paths=paths,
    )
    recorder.record(
        "qa_payload_publishability",
        stage_status_from_snapshot(list(publishability_reports.values()), publishability_before, force=True),
        inputs=list(html_payloads.values()),
        outputs=list(publishability_reports.values()),
    )

    render_before = output_snapshot([paths.render_dir / f"{post_id}-final-sync.mp4" for post_id in html_payloads])
    rendered = render_remotion_payloads(html_payloads, args=args, paths=paths) if args.render else {}
    recorder.record(
        "render",
        stage_status_from_snapshot(
            list(rendered.values()),
            render_before,
            force=args.force or bool(getattr(args, "force_render", False)),
            skipped=not args.render,
        ),
        inputs=list(html_payloads.values()),
        outputs=list(rendered.values()),
        external_calls={"remotion_render": len(rendered)}
        if rendered and (args.force or bool(getattr(args, "force_render", False)) or not snapshot_had_all_outputs(render_before))
        else {},
    )

    avatar_before = output_snapshot([paths.avatar_overlay_dir / f"{post_id}-final-sync-avatar.mp4" for post_id in rendered])
    avatar_rendered = apply_avatar_overlay_to_renders(rendered, defaults=defaults, args=args, paths=paths)
    rendered_for_qa = {post_id: avatar_rendered.get(post_id, path) for post_id, path in rendered.items()}
    avatar_config = avatar_overlay_config(defaults, args)
    avatar_inputs = [*list(rendered.values()), *avatar_overlay_input_paths(rendered, defaults=defaults, args=args, paths=paths)]
    avatar_enabled = bool(avatar_config.get("enabled"))
    recorder.record(
        "avatar_overlay",
        stage_status_from_snapshot(
            list(avatar_rendered.values()),
            avatar_before,
            force=args.force or bool(getattr(args, "force_render", False)),
            skipped=not avatar_enabled or not avatar_rendered,
        ),
        inputs=avatar_inputs,
        outputs=list(avatar_rendered.values()),
        external_calls={},
        metadata=avatar_config,
    )

    rendered = rendered_for_qa

    visual_smoke_before = output_snapshot(
        [paths.render_visual_smoke_dir / post_id / f"{post_id}.render-visual-smoke.json" for post_id in rendered]
    )
    visual_smoke_reports = (
        inspect_render_visual_smoke_reports(rendered, html_payloads=html_payloads, defaults=defaults, args=args, paths=paths)
        if rendered and should_run_render_visual_smoke(defaults, args)
        else {}
    )
    recorder.record(
        "qa_render_visual_smoke",
        stage_status_from_snapshot(
            list(visual_smoke_reports.values()),
            visual_smoke_before,
            force=True,
            skipped=not bool(visual_smoke_reports),
        ),
        inputs=[*list(rendered.values()), *list(html_payloads.values())],
        outputs=list(visual_smoke_reports.values()),
    )

    av_before = output_snapshot([paths.render_av_integrity_dir / f"{post_id}.render-av-integrity.json" for post_id in rendered])
    av_integrity_reports = (
        inspect_render_av_integrity_reports(rendered, html_payloads=html_payloads, defaults=defaults, args=args, paths=paths)
        if rendered and should_run_render_av_integrity(defaults, args)
        else {}
    )
    recorder.record(
        "qa_render_av_integrity",
        stage_status_from_snapshot(
            list(av_integrity_reports.values()),
            av_before,
            force=True,
            skipped=not bool(av_integrity_reports),
        ),
        inputs=[*list(rendered.values()), *list(html_payloads.values())],
        outputs=list(av_integrity_reports.values()),
    )

    oracle_before = output_snapshot([paths.quality_oracle_dir / f"{post_id}.video-quality.json" for post_id in rendered])
    oracle_reports = (
        run_gemini_quality_oracle(rendered, html_payloads=html_payloads, defaults=defaults, args=args, paths=paths)
        if rendered and should_run_gemini_quality_oracle(defaults, args)
        else {}
    )
    oracle_status = stage_status_from_snapshot(
        list(oracle_reports.values()),
        oracle_before,
        force=args.force or bool(getattr(args, "force_oracle", False)),
        skipped=not bool(oracle_reports),
    )
    recorder.record(
        "qa_gemini_quality_oracle",
        oracle_status,
        inputs=[*list(rendered.values()), *list(html_payloads.values())],
        outputs=list(oracle_reports.values()),
        external_calls={"gemini_quality_oracle": len(oracle_reports)} if oracle_status == "generated" else {},
        metadata={"model": str(args.gemini_quality_oracle_model or defaults.get("gemini_quality_oracle_model") or "gemini-3.1-pro-preview")},
    )

    publication_readiness = build_publication_readiness_report(
        post_ids=[item.post_id for item in voiceover_batch.items],
        video_paths=rendered,
        html_payload_paths=html_payloads,
        publishability_report_paths=publishability_reports,
        render_visual_smoke_report_paths=visual_smoke_reports,
        render_av_integrity_report_paths=av_integrity_reports,
        gemini_quality_oracle_report_paths=oracle_reports,
        oracle_required=should_require_publication_oracle(defaults, args),
    )
    write_json(paths.publication_readiness, publication_readiness.model_dump())
    publication_manifest = build_flow_publication_manifest(publication_readiness.model_dump(), paths=paths)
    write_json(paths.publication_manifest, publication_manifest)
    recorder.record(
        "manifest",
        "generated",
        inputs=[paths.publication_readiness],
        outputs=[paths.publication_manifest, paths.summary, paths.production_manifest],
        metadata={"publication_readiness_verdict": publication_readiness.verdict},
    )

    summary = {
        "run_id": run_id,
        "manifest": display(manifest_path),
        "run_dir": display(run_dir),
        "public_dir": display(public_dir),
        "posts": [post["post_id"] for post in posts],
        "source_quality_gate": display(paths.source_quality_report) if source_quality_report else "",
        "source_quality_accepted": source_quality_report.get("accepted_post_ids", []) if source_quality_report else [],
        "source_quality_rejected": source_quality_report.get("rejected_post_ids", []) if source_quality_report else [],
        "voiceover": display(paths.voiceover),
        "media_plan": display(paths.media_plan),
        "media_resolver": display(resolver_path),
        "tts_manifest": display(paths.tts_manifest) if paths.tts_manifest.exists() else "",
        "html_payloads": {post_id: display(path) for post_id, path in html_payloads.items()},
        "publishability_reports": {post_id: display(path) for post_id, path in publishability_reports.items()},
        "renders": {post_id: display(path) for post_id, path in rendered.items()},
        "render_visual_smoke": {post_id: display(path) for post_id, path in visual_smoke_reports.items()},
        "render_av_integrity": {post_id: display(path) for post_id, path in av_integrity_reports.items()},
        "gemini_quality_oracle": {post_id: display(path) for post_id, path in oracle_reports.items()},
        "publication_readiness": display(paths.publication_readiness),
        "publication_readiness_verdict": publication_readiness.verdict,
        "publication_manifest": display(paths.publication_manifest),
        "publication_manifest_verdict": publication_manifest["verdict"],
        "publish_allowed": publication_manifest["publish_allowed"],
        "production_manifest": display(paths.production_manifest),
        "source_quality_gate_config": source_quality_gate_config(defaults, args),
        "layout_recipe": layout_recipe(defaults, args),
        "vfx_timing_mode": vfx_timing_mode(defaults, args),
        "avatar_overlay": avatar_overlay_config(defaults, args),
    }
    paths.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    recorder.complete(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if should_fail_publication_readiness(defaults, args) and publication_readiness.verdict != "publication_ready":
        raise SystemExit(publication_readiness_failure_message(publication_readiness.model_dump()))
    return 0


class FlowPaths:
    def __init__(self, *, run_dir: Path, public_dir: Path) -> None:
        self.run_dir = run_dir
        self.public_dir = public_dir
        self.reddit_threads = run_dir / "reddit-threads-4.json"
        self.reddit_threads_filtered = run_dir / "reddit-threads.source-filtered.json"
        self.source_quality_report = run_dir / "source-quality-gate.json"
        self.voiceover = run_dir / "voiceover-storyboards.json"
        self.media_plan = run_dir / "media-plan.json"
        self.media_resolver = run_dir / "media-resolver.json"
        self.media_resolver_deduped = run_dir / "media-resolver.deduped.json"
        self.media_resolver_hydrated = run_dir / "media-resolver.hydrated.json"
        self.html_payload_dir = run_dir / "html-layouts-final"
        self.render_dir = run_dir / "renders-final"
        self.tts_dir = run_dir / "tts-inworld"
        self.tts_manifest = run_dir / "tts-inworld" / "manifest.json"
        self.public_assets = public_dir / "assets-final"
        self.public_audio = public_dir / "audio-inworld"
        self.publishability_dir = run_dir / "publishability"
        self.render_visual_smoke_dir = run_dir / "render-visual-smoke"
        self.render_av_integrity_dir = run_dir / "render-av-integrity"
        self.quality_oracle_dir = run_dir / "gemini-quality-oracle"
        self.tts_pronunciation_dir = run_dir / "tts-pronunciation-repair"
        self.heygen_dir = run_dir / "heygen-avatar"
        self.avatar_overlay_dir = run_dir / "avatar-overlay"
        self.publication_readiness = run_dir / "publication-readiness.json"
        self.publication_manifest = run_dir / "publication-manifest.json"
        self.summary = run_dir / "flow-summary.json"
        self.production_manifest = run_dir / "production-run-manifest.json"

    def scope_media_outputs(self, scope: str) -> None:
        self.media_resolver = self.run_dir / f"media-resolver.{scope}.json"
        self.media_resolver_deduped = self.run_dir / f"media-resolver.{scope}.deduped.json"
        self.media_resolver_hydrated = self.run_dir / f"media-resolver.{scope}.hydrated.json"


def ensure_dirs(paths: FlowPaths) -> None:
    for path in (
        paths.run_dir,
        paths.public_dir,
        paths.html_payload_dir,
        paths.render_dir,
        paths.tts_dir,
        paths.tts_pronunciation_dir,
        paths.public_assets,
        paths.public_audio,
        paths.publishability_dir,
        paths.render_visual_smoke_dir,
        paths.render_av_integrity_dir,
        paths.quality_oracle_dir,
        paths.heygen_dir,
        paths.avatar_overlay_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


async def fetch_reddit_threads(posts: list[Json], *, args: argparse.Namespace, out_path: Path) -> RedditThreadBatch:
    if out_path.exists() and not args.force:
        from reddit2video.serialization import reddit_batch_from_dict

        return reddit_batch_from_dict(read_json(out_path))

    parser = RedditParser()
    try:
        threads = []
        for post in posts:
            thread = await parser.fetch_thread(
                RedditThreadRequest(
                    post_id=post["post_id"],
                    subreddit=post.get("subreddit") or None,
                    comment_limit=args.comment_limit,
                    comment_depth=args.comment_depth,
                    comment_sort=args.comment_sort,
                )
            )
            threads.append(thread)
    finally:
        await parser.aclose()

    batch = RedditThreadBatch(
        threads=threads,
        candidates=[],
        fetched_at=datetime.now(timezone.utc).isoformat(),
        metadata={
            "node": "reddit_thread_manifest",
            "items": len(threads),
            "manifest_posts": [post["post_id"] for post in posts],
        },
    )
    write_json(out_path, to_jsonable(batch))
    return batch


async def apply_source_quality_gate(
    reddit_batch: RedditThreadBatch,
    *,
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> tuple[RedditThreadBatch, Json]:
    force = bool(args.force or getattr(args, "force_source_quality", False))
    if (
        paths.reddit_threads_filtered.exists()
        and paths.source_quality_report.exists()
        and not force
        and _is_fresh(paths.reddit_threads_filtered, [paths.reddit_threads])
        and _is_fresh(paths.source_quality_report, [paths.reddit_threads])
    ):
        return reddit_batch_from_dict(read_json(paths.reddit_threads_filtered)), read_json(paths.source_quality_report)

    config = source_quality_gate_config(defaults, args)
    client = GeminiClient.from_env(model=str(config["model"]), vertex=True)
    try:
        gate = await evaluate_source_quality_batch(
            reddit_batch,
            gemini=client,
            model=str(config["model"]),
            fallback_models=[str(model) for model in config.get("fallback_models", [])],
            min_score=int(config["min_score"]),
            accept_safe_mode=bool(config["accept_safe_mode"]),
            cache_dir="outputs/cache",
            period_key=paths.run_dir.name,
            concurrency=max(1, int(config["concurrency"])),
            force=force,
        )
    finally:
        await client.aclose()

    filtered = filter_thread_batch_by_source_quality(reddit_batch, gate)
    report = gate.model_dump()
    write_json(paths.source_quality_report, report)
    write_json(paths.reddit_threads_filtered, to_jsonable(filtered))
    return filtered, report


async def generate_voiceover(
    reddit_batch: RedditThreadBatch,
    *,
    defaults: Json,
    args: argparse.Namespace,
    out_path: Path,
    input_path: Path | None = None,
):
    if out_path.exists() and not args.force and (input_path is None or _is_fresh(out_path, [input_path])):
        return voiceover_batch_from_dict(read_json(out_path))

    client = GeminiClient.from_env(model=str(defaults.get("voiceover_model") or "gemini-3.1-pro-preview"), vertex=True)
    try:
        result = await VoiceoverScriptNode(gemini=client).run(
            VoiceoverScriptNodeRequest(
                thread_batch=reddit_batch,
                target_language=str(defaults.get("target_language") or "Russian"),
                target_platform=str(defaults.get("target_platform") or "short-form vertical video"),
                target_duration_sec=int(defaults.get("target_duration_sec") or 60),
                risk_tolerance=str(defaults.get("risk_tolerance") or "medium"),
                prompt_version="storyboard_v2",
                master_prompt_path="prompts/voiceover_storyboard_master_v3.md",
                runtime_prompt_path="prompts/voiceover_storyboard_runtime_single_v3.md",
                validation_retries=1,
                use_cache=True,
                cache_dir="outputs/cache",
                period_key=out_path.parent.name,
                concurrency=max(1, int(args.voiceover_concurrency)),
            )
        )
    finally:
        await client.aclose()
    write_json(out_path, to_jsonable(result))
    return result


def build_storyboard_media_plan(voiceover_batch: Any, *, run_id: str, out_path: Path, force: bool = False) -> Any:
    if out_path.exists() and not force:
        return scene_pipeline_batch_from_dict(read_json(out_path))
    result = storyboard_assets_to_scene_batch(voiceover_batch, period_key=run_id)
    write_json(out_path, to_jsonable(result))
    return result


async def resolve_and_hydrate_media(
    scene_batch: Any,
    *,
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
    run_id: str,
) -> Path:
    resolver_generated = False
    force_media = bool(getattr(args, "force_media", False))
    if not paths.media_resolver.exists() or args.force or force_media:
        providers = [str(provider) for provider in defaults.get("providers") or ["pinterest", "serper_images", "giphy"]]
        result = await MediaResolverNode().run(
            MediaResolverNodeRequest(
                scene_batch=scene_batch,
                providers=providers,
                selected_per_slot=int(_arg_or_default(args.media_selected_per_slot, defaults, "media_selected_per_slot", 1)),
                max_slots_per_item=int(_arg_or_default(args.media_max_slots_per_item, defaults, "media_max_slots_per_item", 120)),
                candidates_per_provider=int(
                    _arg_or_default(args.media_candidates_per_provider, defaults, "media_candidates_per_provider", 50)
                ),
                contact_sheet_size=int(_arg_or_default(args.media_contact_sheet_size, defaults, "media_contact_sheet_size", 10)),
                selection_mode=media_selection_mode(defaults, args),
                media_selector_model=str(defaults.get("media_selector_model") or "gemini-3-flash-preview"),
                media_selector_fallback_models=[
                    str(model)
                    for model in defaults.get("media_selector_fallback_models", [])
                    if str(model).strip()
                ],
                media_query_rewrite_enabled=bool(defaults.get("media_query_rewrite_enabled", True)),
                media_query_rewrite_model=str(defaults.get("media_query_rewrite_model") or "gemini-3-flash-preview"),
                media_query_rewrite_max_slots_per_item=int(
                    defaults.get("media_query_rewrite_max_slots_per_item", 4)
                ),
                media_query_rewrite_timeout_sec=float(defaults.get("media_query_rewrite_timeout_sec", 10.0)),
                media_provider_search_timeout_sec=float(defaults.get("media_provider_search_timeout_sec", 15.0)),
                giphy_connector_mode=str(defaults.get("giphy_connector_mode") or "api"),  # type: ignore[arg-type]
                pinterest_connector_mode=str(defaults.get("pinterest_connector_mode") or "api"),  # type: ignore[arg-type]
                pinterest_api_scope=str(defaults.get("pinterest_api_scope") or "all"),
                giphy_api_key_source=str(defaults.get("giphy_api_key_source") or "web"),  # type: ignore[arg-type]
                giphy_web_key_cache_path=str(
                    defaults.get("giphy_web_key_cache_path") or "outputs/cache/giphy_web_api_key.json"
                ),
                serper_gl="us",
                serper_hl="en",
                use_cache=not (args.force or force_media),
                cache_dir="outputs/cache",
                out_dir="outputs/media",
                screenshot_dir="outputs/media-screens",
                period_key=run_id,
                concurrency=max(1, int(args.media_concurrency)),
            )
        )
        write_json(paths.media_resolver, to_jsonable(result))
        resolver_generated = True

    dedupe_ran = False
    if resolver_generated or args.force or force_media or not _is_fresh(paths.media_resolver_deduped, [paths.media_resolver]):
        run_command(
            [
                sys.executable,
                "scripts/repair_media_resolver_dedupe.py",
                "--resolver-input",
                str(paths.media_resolver),
                "--out",
                str(paths.media_resolver_deduped),
            ],
            cwd=ROOT,
        )
        dedupe_ran = True
    if resolver_generated or dedupe_ran or args.force or force_media or not _is_fresh(
        paths.media_resolver_hydrated,
        [paths.media_resolver_deduped],
    ):
        run_command(
            [
                sys.executable,
                "scripts/download_selected_storyboard_assets.py",
                "--resolver-input",
                str(paths.media_resolver_deduped),
                "--out",
                str(paths.media_resolver_hydrated),
                "--asset-dir",
                str(paths.public_assets),
                "--concurrency",
                str(max(1, int(_arg_or_default(args.asset_download_concurrency, defaults, "asset_download_concurrency", 3)))),
                "--hls-duration-sec",
                str(float(args.hls_duration_sec)),
            ],
            cwd=ROOT,
        )
    return paths.media_resolver_hydrated


async def generate_inworld_tts(
    voiceover_batch: Any,
    *,
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> dict[str, Json]:
    voice_id = str(defaults.get("voice_id") or "Svetlana")
    existing_manifest = read_json(paths.tts_manifest) if paths.tts_manifest.exists() and not args.force else {}
    existing_items = existing_manifest.get("items") if isinstance(existing_manifest.get("items"), dict) else {}
    if isinstance(existing_manifest.get("voice_id"), str) and existing_manifest.get("voice_id"):
        voice_id = str(existing_manifest.get("voice_id"))
    client = InworldTTSClient.from_env()
    items: dict[str, Json] = {}
    try:
        for item in voiceover_batch.items:
            post_id = item.post_id
            scene_lines = scene_lines_for_item(item, voice_id=voice_id)
            audio_path = paths.public_audio / f"{post_id}-inworld-{safe_token(voice_id)}.mp3"
            alignment_path = paths.tts_dir / f"{post_id}.alignment.json"
            scene_lines_path = paths.tts_dir / f"{post_id}.scene-lines.tts.json"
            if audio_path.exists() and alignment_path.exists() and scene_lines_path.exists() and not args.force:
                items[post_id] = {
                    "audio_public_path": public_path(audio_path),
                    "audio_path": str(audio_path),
                    "alignment": str(alignment_path),
                    "scene_lines": str(scene_lines_path),
                    "status": "cached",
                }
                continue
            write_json(scene_lines_path, scene_lines)
            alignment = await client.text_to_speech_with_timestamps(
                text=str(scene_lines["full_text"]),
                voice_id=voice_id,
                output_path=audio_path,
            )
            alignment["source_voiceover"] = scene_lines["full_text"]
            alignment["scene_lines_path"] = display(scene_lines_path)
            write_json(alignment_path, alignment)
            items[post_id] = {
                "audio_public_path": public_path(audio_path),
                "audio_path": str(audio_path),
                "alignment": str(alignment_path),
                "scene_lines": str(scene_lines_path),
                "status": "generated",
            }
    finally:
        await client.aclose()
    merged_items = {**existing_items, **items}
    write_json(paths.tts_manifest, {"items": merged_items, "voice_id": voice_id})
    return items


async def repair_tts_pronunciations(
    tts_outputs: dict[str, Json],
    *,
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> dict[str, Json]:
    voice_id = str(defaults.get("voice_id") or "Svetlana")
    existing_manifest = read_json(paths.tts_manifest) if paths.tts_manifest.exists() else {}
    existing_items = existing_manifest.get("items") if isinstance(existing_manifest.get("items"), dict) else {}
    if existing_manifest:
        manifest_voice = str(existing_manifest.get("voice_id") or "").strip()
        voice_id = manifest_voice or voice_id

    model = str(args.pronunciation_repair_model or defaults.get("pronunciation_repair_model") or "gemini-3.1-pro-preview")
    strategy = str(args.pronunciation_repair_strategy or defaults.get("pronunciation_repair_strategy") or "full_revoice")
    seed_issues = forced_pronunciation_issues(defaults, args)
    gemini = GeminiClient.from_env(model=model, vertex=True)
    tts = InworldTTSClient.from_env()
    repaired_items: dict[str, Json] = {}
    try:
        for post_id, raw_item in tts_outputs.items():
            item = dict(raw_item)
            audio_path = resolve_required_input_path(str(item.get("audio_path") or ""))
            alignment_path = resolve_required_input_path(str(item.get("alignment") or ""))
            scene_lines_path = resolve_required_input_path(str(item.get("scene_lines") or ""))
            report_path = paths.tts_pronunciation_dir / f"{post_id}.pronunciation-repair.json"
            repaired_audio_path = paths.public_audio / f"{post_id}-inworld-{safe_token(voice_id)}.pronunciation.mp3"
            repaired_alignment_path = paths.tts_pronunciation_dir / f"{post_id}.pronunciation.alignment.json"
            repaired_scene_lines_path = paths.tts_pronunciation_dir / f"{post_id}.pronunciation.scene-lines.tts.json"

            if report_path.exists() and not args.force:
                report = read_json(report_path)
                cached_status = str(report.get("status") or "")
                needs_audio = cached_status in {"repaired", "revoiced"}
                needs_alignment = cached_status == "revoiced"
                if (
                    (not needs_audio or repaired_audio_path.exists())
                    and (not needs_alignment or repaired_alignment_path.exists())
                ):
                    if needs_audio:
                        item["original_audio_path"] = item.get("audio_path")
                        item["audio_path"] = str(repaired_audio_path)
                        item["audio_public_path"] = public_path(repaired_audio_path)
                    if cached_status == "revoiced":
                        item["alignment"] = str(repaired_alignment_path)
                        item["pronunciation_tts_scene_lines"] = str(repaired_scene_lines_path)
                    item["pronunciation_repair"] = str(report_path)
                    item["pronunciation_repair_status"] = cached_status or "cached"
                    repaired_items[post_id] = item
                    continue

            missing = [
                str(path)
                for path in (audio_path, alignment_path, scene_lines_path)
                if not path.exists()
            ]
            if missing:
                item["pronunciation_repair_status"] = "skipped_missing_inputs"
                item["pronunciation_repair_missing"] = missing
                repaired_items[post_id] = item
                continue

            result = await repair_pronunciation_audio(
                gemini=gemini,
                tts=tts,
                audio_path=audio_path,
                alignment=read_json(alignment_path),
                scene_lines=read_json(scene_lines_path),
                voice_id=voice_id,
                work_dir=paths.tts_pronunciation_dir / post_id,
                output_path=repaired_audio_path,
                model=model,
                max_issues=max(0, int(args.pronunciation_repair_max_issues)),
                min_confidence=max(0.0, min(1.0, float(args.pronunciation_repair_min_confidence))),
                verify=bool(args.verify_pronunciation_repair),
                strategy=strategy,  # type: ignore[arg-type]
                alignment_output_path=repaired_alignment_path,
                scene_lines_output_path=repaired_scene_lines_path,
                seed_issues=seed_issues,
            )
            write_json(report_path, result.model_dump())
            item["pronunciation_repair"] = str(report_path)
            item["pronunciation_repair_status"] = result.status
            if result.status in {"repaired", "revoiced"}:
                item["original_audio_path"] = item.get("audio_path")
                item["audio_path"] = str(repaired_audio_path)
                item["audio_public_path"] = public_path(repaired_audio_path)
            if result.status == "revoiced":
                item["alignment"] = str(repaired_alignment_path)
                item["pronunciation_tts_scene_lines"] = str(repaired_scene_lines_path)
            repaired_items[post_id] = item
    finally:
        await gemini.aclose()
        await tts.aclose()

    merged_items = {**existing_items, **repaired_items}
    write_json(
        paths.tts_manifest,
        {
            "items": merged_items,
            "voice_id": voice_id,
            "pronunciation_repair": {
                "enabled": True,
                "model": model,
                "strategy": strategy,
                "forced_fixes": [issue.model_dump() for issue in seed_issues],
                "max_issues": max(0, int(args.pronunciation_repair_max_issues)),
                "min_confidence": max(0.0, min(1.0, float(args.pronunciation_repair_min_confidence))),
                "verify": bool(args.verify_pronunciation_repair),
            },
        },
    )
    return repaired_items


def generate_heygen_avatars(tts_outputs: dict[str, Json], *, defaults: Json, args: argparse.Namespace, paths: FlowPaths) -> None:
    if not args.heygen_template_video_id:
        raise SystemExit("--with-heygen-avatar requires --heygen-template-video-id")
    heygen_client_cls, latest_storage_state = load_heygen_internal()
    state_path = Path(args.heygen_storage_state) if args.heygen_storage_state else latest_storage_state()
    client = heygen_client_cls(state_path)
    manifest: dict[str, Json] = {}
    for post_id, item in tts_outputs.items():
        audio_path = Path(str(item.get("audio_path") or ""))
        scene_lines_path = Path(str(item.get("scene_lines") or ""))
        if not audio_path.exists() or not scene_lines_path.exists():
            raise SystemExit(f"missing TTS files for HeyGen avatar: {post_id}")
        raw_dir = paths.heygen_dir / post_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        upload_path = raw_dir / "upload-audio.json"
        if upload_path.exists():
            upload = read_json(upload_path)
        else:
            upload = client.upload_audio(audio_path)
            write_json(upload_path, upload)
        script_text = str(read_json(scene_lines_path).get("full_text") or "")
        clone_path = raw_dir / "clone-draft.json"
        if clone_path.exists():
            clone = read_json(clone_path)
        else:
            clone = client.clone_draft(
                args.heygen_template_video_id,
                title=f"{post_id} girly static v5 avatar",
                audio=upload,
                script_text=script_text,
                green_screen=True,
            )
            write_json(clone_path, clone)
        result: Json = {"clone_video_id": clone.get("video_id"), "version_id": clone.get("version_id")}
        if args.heygen_submit:
            generate_path = raw_dir / "generate-draft.json"
            if generate_path.exists():
                generate = read_json(generate_path)
            else:
                generate = client.generate_text_draft(
                    str(clone["video_id"]),
                    title=f"{post_id} girly static v5 avatar",
                    version_id=str(clone.get("version_id") or ""),
                )
                write_json(generate_path, generate)
            result["generate"] = generate
            if args.heygen_wait:
                wait_for_heygen(client, str(clone["video_id"]))
            if args.heygen_download:
                downloaded = client.download_video(str(clone["video_id"]), ROOT / "local_secrets" / "heygen_probe" / "downloads")
                result["downloaded_video"] = str(downloaded)
        manifest[post_id] = result
    write_json(paths.heygen_dir / "heygen-avatar-manifest.json", manifest)


def build_remotion_payloads(
    *,
    voiceover_batch: Any,
    resolver_path: Path,
    tts_outputs: dict[str, Json],
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    for index, item in enumerate(voiceover_batch.items):
        post_id = item.post_id
        tts = tts_outputs.get(post_id) or {}
        out_path = paths.html_payload_dir / f"{post_id}.html-layout.generated.json"
        payload_inputs = [
            paths.voiceover,
            resolver_path,
            resolve_optional_input_path(str(tts.get("alignment") or "")),
            resolve_optional_input_path(str(tts.get("scene_lines") or "")),
        ]
        if not args.force and not bool(getattr(args, "force_payloads", False)) and _is_fresh(out_path, payload_inputs):
            outputs[post_id] = out_path
            continue
        cmd = [
            sys.executable,
            "scripts/girly_static_v5_to_remotion_html_payload.py",
            "--input",
            str(paths.voiceover),
            "--item-index",
            str(index),
            "--media-resolver",
            str(resolver_path),
            "--audio-public-path",
            str(tts.get("audio_public_path") or ""),
            "--alignment",
            str(tts.get("alignment") or ""),
            "--scene-lines",
            str(tts.get("scene_lines") or ""),
            "--sync-caption-mode",
            "replace",
            "--composition-id",
            f"girly-static-v5-final-{post_id}",
            "--out",
            str(out_path),
            "--fps",
            str(int(defaults.get("fps") or 30)),
            "--width",
            str(int(defaults.get("width") or 720)),
            "--height",
            str(int(defaults.get("height") or 1280)),
        ]
        run_command(cmd, cwd=ROOT)
        outputs[post_id] = out_path
    return outputs


def inspect_remotion_payload_publishability(
    html_payloads: dict[str, Path],
    *,
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> dict[str, Path]:
    thresholds = quality_gate_thresholds(defaults, args)
    gate_enabled = should_run_quality_gate(defaults, args)
    outputs: dict[str, Path] = {}
    failed: dict[str, list[str]] = {}
    for post_id, payload_path in html_payloads.items():
        report = inspect_html_payload(read_json(payload_path), **thresholds)
        out_path = paths.publishability_dir / f"{post_id}.publishability.json"
        write_json(out_path, report.model_dump())
        outputs[post_id] = out_path
        if report.verdict == "fail":
            failed[post_id] = report.blocking_defects
    if gate_enabled and failed:
        details = "; ".join(f"{post_id}: {', '.join(defects)}" for post_id, defects in failed.items())
        raise SystemExit(f"Publishability gate failed before render: {details}")
    return outputs


def quality_gate_thresholds(defaults: Json, args: argparse.Namespace) -> Json:
    return {
        "min_scenes": int(_arg_or_default(args.quality_gate_min_scenes, defaults, "quality_gate_min_scenes", 8)),
        "min_duration_sec": float(
            _arg_or_default(args.quality_gate_min_duration_sec, defaults, "quality_gate_min_duration_sec", 20.0)
        ),
        "min_media_scene_ratio": float(
            _arg_or_default(
                args.quality_gate_min_media_scene_ratio,
                defaults,
                "quality_gate_min_media_scene_ratio",
                0.45,
            )
        ),
        "min_unique_assets": int(
            _arg_or_default(args.quality_gate_min_unique_assets, defaults, "quality_gate_min_unique_assets", 6)
        ),
        "min_video_assets": int(
            _arg_or_default(args.quality_gate_min_video_assets, defaults, "quality_gate_min_video_assets", 0)
        ),
        "min_real_media_scene_ratio": float(
            _arg_or_default(
                args.quality_gate_min_real_media_scene_ratio,
                defaults,
                "quality_gate_min_real_media_scene_ratio",
                0.35,
            )
        ),
        "max_generated_visual_scene_ratio": float(
            _arg_or_default(
                args.quality_gate_max_generated_visual_scene_ratio,
                defaults,
                "quality_gate_max_generated_visual_scene_ratio",
                0.65,
            )
        ),
        "max_text_only_run": int(
            _arg_or_default(args.quality_gate_max_text_only_run, defaults, "quality_gate_max_text_only_run", 3)
        ),
        "require_audio": bool(
            args.quality_gate_require_audio
            if args.quality_gate_require_audio is not None
            else defaults.get("quality_gate_require_audio", True)
        ),
    }


def should_run_quality_gate(defaults: Json, args: argparse.Namespace) -> bool:
    if args.quality_gate is not None:
        return bool(args.quality_gate)
    return bool(defaults.get("quality_gate", True))


def media_selection_mode(defaults: Json, args: argparse.Namespace) -> str:
    value = str(args.media_selection_mode or defaults.get("media_selection_mode") or "gemini").strip().lower()
    return value if value in {"gemini", "heuristic", "first"} else "gemini"


def inspect_render_visual_smoke_reports(
    rendered: dict[str, Path],
    *,
    html_payloads: dict[str, Path],
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    failed: dict[str, list[str]] = {}
    for post_id, video_path in rendered.items():
        payload_path = html_payloads.get(post_id)
        if not payload_path:
            continue
        frames_dir = paths.render_visual_smoke_dir / post_id / "frames"
        timeline_frames_dir = paths.render_visual_smoke_dir / post_id / "timeline-frames"
        contact_sheet_path = paths.render_visual_smoke_dir / post_id / f"{post_id}.midpoints.jpg"
        timeline_contact_sheet_path = paths.render_visual_smoke_dir / post_id / f"{post_id}.timeline.jpg"
        report_path = paths.render_visual_smoke_dir / post_id / f"{post_id}.render-visual-smoke.json"
        report = inspect_render_visual_smoke(
            video_path=video_path,
            payload=read_json(payload_path),
            payload_path=payload_path,
            frames_dir=frames_dir,
            contact_sheet_path=contact_sheet_path,
            timeline_frames_dir=timeline_frames_dir,
            timeline_contact_sheet_path=timeline_contact_sheet_path,
        )
        write_json(report_path, report.model_dump())
        outputs[post_id] = report_path
        if report.verdict == "fail":
            failed[post_id] = report.blocking_defects
    if failed and should_fail_render_visual_smoke(defaults, args):
        details = "; ".join(f"{post_id}: {', '.join(defects)}" for post_id, defects in failed.items())
        raise SystemExit(f"Render visual smoke rejected rendered video: {details}")
    return outputs


def should_run_render_visual_smoke(defaults: Json, args: argparse.Namespace) -> bool:
    if args.render_visual_smoke is not None:
        return bool(args.render_visual_smoke)
    return bool(defaults.get("render_visual_smoke", True))


def should_fail_render_visual_smoke(defaults: Json, args: argparse.Namespace) -> bool:
    if args.render_visual_smoke_fail is not None:
        return bool(args.render_visual_smoke_fail)
    return bool(defaults.get("render_visual_smoke_fail", True))


def inspect_render_av_integrity_reports(
    rendered: dict[str, Path],
    *,
    html_payloads: dict[str, Path],
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    failed: dict[str, list[str]] = {}
    for post_id, video_path in rendered.items():
        payload_path = html_payloads.get(post_id)
        payload = read_json(payload_path) if payload_path else {}
        report_path = paths.render_av_integrity_dir / f"{post_id}.render-av-integrity.json"
        report = inspect_render_av_integrity(video_path=video_path, payload=payload, payload_path=payload_path)
        write_json(report_path, report.model_dump())
        outputs[post_id] = report_path
        if report.verdict == "fail":
            failed[post_id] = report.blocking_defects
    if failed and should_fail_render_av_integrity(defaults, args):
        details = "; ".join(f"{post_id}: {', '.join(defects)}" for post_id, defects in failed.items())
        raise SystemExit(f"Render AV integrity rejected rendered video: {details}")
    return outputs


def should_run_render_av_integrity(defaults: Json, args: argparse.Namespace) -> bool:
    if args.render_av_integrity is not None:
        return bool(args.render_av_integrity)
    return bool(defaults.get("render_av_integrity", True))


def should_fail_render_av_integrity(defaults: Json, args: argparse.Namespace) -> bool:
    if args.render_av_integrity_fail is not None:
        return bool(args.render_av_integrity_fail)
    return bool(defaults.get("render_av_integrity_fail", True))


def run_gemini_quality_oracle(
    rendered: dict[str, Path],
    *,
    html_payloads: dict[str, Path],
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> dict[str, Path]:
    model = str(args.gemini_quality_oracle_model or defaults.get("gemini_quality_oracle_model") or "gemini-3.1-pro-preview")
    outputs: dict[str, Path] = {}
    failed: dict[str, list[str]] = {}
    for post_id, video_path in rendered.items():
        report_path = paths.quality_oracle_dir / f"{post_id}.video-quality.json"
        if not report_path.exists() or args.force or bool(getattr(args, "force_oracle", False)):
            run_command(
                [
                    sys.executable,
                    "scripts/evaluate_video_quality_gemini.py",
                "--video",
                str(video_path),
                "--payload",
                str(html_payloads.get(post_id) or paths.html_payload_dir / f"{post_id}.html-layout.generated.json"),
                "--out",
                str(report_path),
                "--model",
                    model,
                ],
                cwd=ROOT,
            )
        outputs[post_id] = report_path
        report = read_json(report_path)
        defects = gemini_quality_oracle_defects(report)
        if defects:
            failed[post_id] = defects
    if failed and args.gemini_quality_oracle_fail:
        details = "; ".join(f"{post_id}: {', '.join(defects)}" for post_id, defects in failed.items())
        raise SystemExit(f"Gemini quality oracle rejected rendered video: {details}")
    return outputs


def should_run_gemini_quality_oracle(defaults: Json, args: argparse.Namespace) -> bool:
    if args.gemini_quality_oracle is not None:
        return bool(args.gemini_quality_oracle)
    return bool(defaults.get("gemini_quality_oracle", False))


def gemini_quality_oracle_defects(report: Json) -> list[str]:
    return publication_oracle_defects(report)


def should_require_publication_oracle(defaults: Json, args: argparse.Namespace) -> bool:
    if args.publication_readiness_oracle_required is not None:
        return bool(args.publication_readiness_oracle_required)
    configured = defaults.get("publication_readiness_oracle_required")
    if configured is not None:
        return bool(configured)
    return bool(defaults.get("gemini_quality_oracle", False))


def should_fail_publication_readiness(defaults: Json, args: argparse.Namespace) -> bool:
    if args.publication_readiness_fail is not None:
        return bool(args.publication_readiness_fail)
    return bool(defaults.get("publication_readiness_fail", True))


def publication_readiness_failure_message(report: Json) -> str:
    verdict = str(report.get("verdict") or "missing").strip() or "missing"
    defects = _string_list(report.get("blocking_defects"))
    pending = _string_list(report.get("pending_reasons"))
    reasons = defects or pending
    detail = "; ".join(reasons[:12])
    if len(reasons) > 12:
        detail += f"; ... +{len(reasons) - 12} more"
    if not detail:
        detail = "publication_readiness report did not prove publication_ready"
    return f"Publication readiness rejected release: verdict={verdict}; {detail}"


def build_flow_publication_manifest(readiness_report: Json, *, paths: FlowPaths) -> Json:
    readiness_verdict = str(readiness_report.get("verdict") or "missing").strip() or "missing"
    manifest_verdict = _publication_manifest_verdict(readiness_verdict)
    items = [
        _flow_publication_manifest_item(item)
        for item in readiness_report.get("items") or []
        if isinstance(item, dict)
    ]
    return {
        "schema": "reddit2video.publication_manifest.v1",
        "run_dir": str(paths.run_dir),
        "verdict": manifest_verdict,
        "publish_allowed": manifest_verdict == "publication_ready",
        "release_policy": "requires_current_publication_readiness_publication_ready",
        "publication_readiness_verdict": readiness_verdict,
        "oracle_required": bool(readiness_report.get("oracle_required", True)),
        "blocking_defects": _string_list(readiness_report.get("blocking_defects")),
        "pending_reasons": _string_list(readiness_report.get("pending_reasons")),
        "item_count": len(items),
        "publishable_item_count": sum(1 for item in items if item["publish_allowed"]),
        "items": items,
    }


def _publication_manifest_verdict(readiness_verdict: str) -> str:
    if readiness_verdict == "publication_ready":
        return "publication_ready"
    if readiness_verdict == "local_pass_oracle_pending":
        return "local_ready_oracle_pending"
    return "fail"


def _flow_publication_manifest_item(item: Json) -> Json:
    post_id = str(item.get("post_id") or "")
    status = str(item.get("status") or "missing_evidence")
    pending = _string_list(item.get("pending_reasons"))
    blocking = _string_list(item.get("blocking_defects"))
    publish_allowed = status == "publication_ready" and not pending and not blocking
    hold_reasons = [*blocking, *pending]
    if not publish_allowed and not hold_reasons:
        hold_reasons = [f"status={status}"]
    raw_video_path = str(item.get("video_path") or "").strip()
    video_path = Path(raw_video_path) if raw_video_path else None
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    av = evidence.get("render_av_integrity") if isinstance(evidence.get("render_av_integrity"), dict) else {}
    return {
        "post_id": post_id,
        "publish_allowed": publish_allowed,
        "status": status,
        "hold_reasons": hold_reasons,
        "video_path": str(video_path or ""),
        "sha256": _sha256(video_path) if video_path and video_path.is_file() else "",
        "size_bytes": video_path.stat().st_size if video_path and video_path.is_file() else 0,
        "duration_sec": av.get("format_duration_sec"),
        "width": av.get("width"),
        "height": av.get("height"),
        "fps": av.get("fps"),
        "audio_codec": av.get("audio_codec"),
        "gemini_quality_oracle_report_path": str(item.get("gemini_quality_oracle_report_path") or ""),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_remotion_payloads(html_payloads: dict[str, Path], *, args: argparse.Namespace, paths: FlowPaths) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    remotion_payload_path = ROOT / "remotion" / "src" / "html-layout.generated.json"
    for post_id, payload_path in html_payloads.items():
        out_path = paths.render_dir / f"{post_id}-final-sync.mp4"
        if not args.force and not bool(getattr(args, "force_render", False)) and _is_fresh(out_path, [payload_path]):
            outputs[post_id] = out_path
            continue
        remotion_payload_path.write_text(payload_path.read_text(encoding="utf-8"), encoding="utf-8")
        run_command(
            [
                "npx",
                "remotion",
                "render",
                "src/index.ts",
                f"girly-static-v5-final-{post_id}",
                str(Path("..") / out_path.relative_to(ROOT)),
                "--codec=h264",
                "--crf=18",
                "--audio-codec=aac",
                f"--concurrency={max(1, int(args.remotion_concurrency))}",
                "--log=info",
            ],
            cwd=ROOT / "remotion",
        )
        outputs[post_id] = out_path
    return outputs


def scene_lines_for_item(item: Any, *, voice_id: str) -> Json:
    storyboard = item.script.get("storyboard_v2") if isinstance(item.script, dict) else None
    if not isinstance(storyboard, dict):
        storyboard = item.script if isinstance(item.script, dict) else {}
    scenes = []
    full_text_parts = []
    for index, scene in enumerate(storyboard.get("scenes") or [], start=1):
        raw = str(scene.get("voiceover_line") or "").strip()
        line = normalize_scene_line_for_tts(raw)
        scene_id = int(scene.get("scene_id") or index)
        scenes.append({"scene_id": scene_id, "voiceover_line": line, "raw_voiceover_line": raw})
        full_text_parts.append(line)
    return {
        "post_id": item.post_id,
        "title": item.title,
        "voice_id": voice_id,
        "provider": "inworld",
        "full_text": " ".join(full_text_parts),
        "scenes": scenes,
    }


def normalize_scene_line_for_tts(text: str) -> str:
    text = normalize_russian_tts_orthography(re.sub(r"\s+", " ", text.strip()))
    letters = re.findall(r"[А-Яа-яЁё]", text)
    if letters:
        upper = sum(1 for char in letters if char.isupper())
        lower = sum(1 for char in letters if char.islower())
        if upper / len(letters) >= 0.8 and lower == 0:
            lowered = text.lower()
            text = lowered[:1].upper() + lowered[1:]
    return text


def wait_for_heygen(client: HeyGenInternalClient, video_id: str, *, timeout_sec: int = 1200) -> None:
    deadline = datetime.now(timezone.utc).timestamp() + timeout_sec
    while datetime.now(timezone.utc).timestamp() < deadline:
        status = client.project_status(video_id)
        item_status = _heygen_project_status_value(status)
        if item_status in {"completed", "success"}:
            return
        if item_status in {"failed", "error"}:
            raise SystemExit(f"HeyGen generation failed for {video_id}: {status}")
        import time

        time.sleep(10)
    raise SystemExit(f"HeyGen generation timed out for {video_id}")


def _heygen_project_status_value(payload: Json) -> str:
    data = payload.get("data") if isinstance(payload, dict) else None
    item = data[0] if isinstance(data, list) and data else {}
    if not isinstance(item, dict):
        return ""
    return str(item.get("status") or "").lower()


def dry_run_plan(
    manifest_path: Path,
    posts: list[Json],
    defaults: Json,
    run_id: str,
    paths: FlowPaths,
    args: argparse.Namespace,
) -> Json:
    commands = []
    for index, post in enumerate(posts):
        post_id = post["post_id"]
        commands.append(
            {
                "step": "build_remotion_payload",
                "post_id": post_id,
                "out": display(paths.html_payload_dir / f"{post_id}.html-layout.generated.json"),
                "composition_id": f"girly-static-v5-final-{post_id}",
                "item_index": index,
            }
        )
        if args.render:
            commands.append(
                {
                    "step": "render",
                    "post_id": post_id,
                    "out": display(paths.render_dir / f"{post_id}-final-sync.mp4"),
                }
            )
    return {
        "mode": "dry_run",
        "manifest": display(manifest_path),
        "run_id": run_id,
        "posts": posts,
        "defaults": defaults,
        "runtime_outputs": {
            "run_dir": display(paths.run_dir),
            "public_dir": display(paths.public_dir),
            "selected_post_ids": requested_post_ids(args, posts),
            "source_quality_gate": source_quality_gate_config(defaults, args),
            "source_quality_report": display(paths.source_quality_report),
            "reddit_threads_filtered": display(paths.reddit_threads_filtered),
            "voiceover": display(paths.voiceover),
            "media_plan": display(paths.media_plan),
            "media_resolver": display(paths.media_resolver),
            "media_resolver_deduped": display(paths.media_resolver_deduped),
            "media_resolver_hydrated": display(paths.media_resolver_hydrated),
            "tts_manifest": display(paths.tts_manifest),
            "publication_readiness": display(paths.publication_readiness),
            "publication_manifest": display(paths.publication_manifest),
            "media_selection_mode": media_selection_mode(defaults, args),
            "media_selected_per_slot": int(_arg_or_default(args.media_selected_per_slot, defaults, "media_selected_per_slot", 1)),
            "media_max_slots_per_item": int(_arg_or_default(args.media_max_slots_per_item, defaults, "media_max_slots_per_item", 120)),
            "media_candidates_per_provider": int(
                _arg_or_default(args.media_candidates_per_provider, defaults, "media_candidates_per_provider", 50)
            ),
            "media_contact_sheet_size": int(_arg_or_default(args.media_contact_sheet_size, defaults, "media_contact_sheet_size", 10)),
            "asset_download_concurrency": int(
                _arg_or_default(args.asset_download_concurrency, defaults, "asset_download_concurrency", 3)
            ),
            "publication_readiness_oracle_required": should_require_publication_oracle(defaults, args),
            "publication_readiness_fail": should_fail_publication_readiness(defaults, args),
            "production_manifest": display(paths.production_manifest),
            "layout_recipe": layout_recipe(defaults, args),
            "vfx_timing_mode": vfx_timing_mode(defaults, args),
            "avatar_overlay": avatar_overlay_config(defaults, args),
        },
        "external_steps": [
            "reddit_fetch",
            *(["gemini_source_quality_gate"] if should_run_source_quality_gate(defaults, args) else []),
            "gemini_voiceover",
            "media_resolution",
            "asset_download",
            "inworld_tts",
            *(
                ["deterministic_publishability_gate"]
                if should_run_quality_gate(defaults, args)
                else ["deterministic_publishability_report"]
            ),
            *(
                [
                    "gemini_pronunciation_audit",
                    "inworld_full_pronunciation_revoice",
                    "gemini_pronunciation_verify",
                ]
                if should_repair_pronunciation(defaults, args)
                else []
            ),
            "layout_vfx_annotation",
            "remotion_render",
            *(["avatar_overlay"] if avatar_overlay_config(defaults, args).get("enabled") else []),
            *(["render_visual_smoke"] if should_run_render_visual_smoke(defaults, args) else []),
            *(["render_av_integrity"] if should_run_render_av_integrity(defaults, args) else []),
            *(["gemini_post_render_quality_oracle"] if should_run_gemini_quality_oracle(defaults, args) else []),
            "publication_readiness_report",
            "publication_manifest",
            *(["publication_readiness_release_gate"] if should_fail_publication_readiness(defaults, args) else []),
        ]
        + (["heygen_avatar"] if args.with_heygen_avatar else []),
        "stage_preview": dry_run_stage_preview(manifest_path, posts, defaults, paths, args),
        "commands": commands,
    }


def dry_run_stage_preview(
    manifest_path: Path,
    posts: list[Json],
    defaults: Json,
    paths: FlowPaths,
    args: argparse.Namespace,
) -> list[Json]:
    post_ids = [str(post.get("post_id") or "") for post in posts]
    payload_paths = [paths.html_payload_dir / f"{post_id}.html-layout.generated.json" for post_id in post_ids]
    render_paths = [paths.render_dir / f"{post_id}-final-sync.mp4" for post_id in post_ids]
    publishability_paths = [paths.publishability_dir / f"{post_id}.publishability.json" for post_id in post_ids]
    visual_smoke_paths = [
        paths.render_visual_smoke_dir / post_id / f"{post_id}.render-visual-smoke.json" for post_id in post_ids
    ]
    av_paths = [paths.render_av_integrity_dir / f"{post_id}.render-av-integrity.json" for post_id in post_ids]
    oracle_paths = [paths.quality_oracle_dir / f"{post_id}.video-quality.json" for post_id in post_ids]
    avatar_paths = [paths.avatar_overlay_dir / f"{post_id}-final-sync-avatar.mp4" for post_id in post_ids]
    avatar_render_inputs = [*render_paths, *avatar_overlay_input_paths_for_post_ids(post_ids, defaults=defaults, args=args, paths=paths)]
    voiceover_inputs = [paths.reddit_threads_filtered if should_run_source_quality_gate(defaults, args) else paths.reddit_threads]
    return [
        {"name": "inputs", "status": "generated", "outputs": [display(paths.run_dir / "manifest.input.json")]},
        {
            "name": "reddit",
            "status": "generated" if args.force or not paths.reddit_threads.exists() else "cached",
            "outputs": [display(paths.reddit_threads)],
        },
        {
            "name": "source_quality_gate",
            "status": dry_run_many_fresh_status(
                [paths.reddit_threads_filtered, paths.source_quality_report],
                [paths.reddit_threads],
                force=args.force or bool(getattr(args, "force_source_quality", False)),
                skipped=not should_run_source_quality_gate(defaults, args),
            ),
            "outputs": [display(paths.reddit_threads_filtered), display(paths.source_quality_report)],
        },
        {
            "name": "voiceover",
            "status": dry_run_many_fresh_status([paths.voiceover], voiceover_inputs, force=args.force),
            "outputs": [display(paths.voiceover)],
        },
        {
            "name": "media_plan",
            "status": "generated" if args.force or not paths.media_plan.exists() else "cached",
            "outputs": [display(paths.media_plan)],
        },
        {
            "name": "media",
            "status": dry_run_media_status(paths, args),
            "outputs": [display(paths.media_resolver), display(paths.media_resolver_deduped), display(paths.media_resolver_hydrated)],
        },
        {
            "name": "tts",
            "status": dry_run_single_output_status(paths.tts_manifest, force=args.force, skipped=not args.generate_tts and not paths.tts_manifest.exists()),
            "outputs": [display(paths.tts_manifest)],
        },
        {
            "name": "pronunciation_repair",
            "status": "generated" if should_repair_pronunciation(defaults, args) else "skipped",
            "outputs": [display(paths.tts_manifest)],
        },
        {
            "name": "legacy_heygen_generation",
            "status": "generated" if args.with_heygen_avatar else "skipped",
            "outputs": [display(paths.heygen_dir / "heygen-avatar-manifest.json")],
        },
        {
            "name": "layout_payload",
            "status": dry_run_many_output_status(payload_paths, force=args.force or bool(getattr(args, "force_payloads", False))),
            "outputs": [display(path) for path in payload_paths],
        },
        {
            "name": "vfx_annotation",
            "status": dry_run_vfx_status(payload_paths, defaults, args),
            "outputs": [display(path) for path in payload_paths],
        },
        {
            "name": "render",
            "status": dry_run_many_fresh_status(
                render_paths,
                payload_paths,
                force=args.force or bool(getattr(args, "force_render", False)),
                skipped=not args.render,
            ),
            "outputs": [display(path) for path in render_paths],
        },
        {
            "name": "avatar_overlay",
            "status": dry_run_many_fresh_status(
                avatar_paths,
                avatar_render_inputs,
                force=args.force or bool(getattr(args, "force_render", False)),
                skipped=not bool(avatar_overlay_config(defaults, args).get("enabled")),
            ),
            "outputs": [display(path) for path in avatar_paths],
        },
        {
            "name": "qa_payload_publishability",
            "status": dry_run_many_output_status(publishability_paths, force=True),
            "outputs": [display(path) for path in publishability_paths],
        },
        {
            "name": "qa_render_visual_smoke",
            "status": dry_run_many_output_status(visual_smoke_paths, force=True, skipped=not should_run_render_visual_smoke(defaults, args)),
            "outputs": [display(path) for path in visual_smoke_paths],
        },
        {
            "name": "qa_render_av_integrity",
            "status": dry_run_many_output_status(av_paths, force=True, skipped=not should_run_render_av_integrity(defaults, args)),
            "outputs": [display(path) for path in av_paths],
        },
        {
            "name": "qa_gemini_quality_oracle",
            "status": dry_run_many_output_status(
                oracle_paths,
                force=args.force or bool(getattr(args, "force_oracle", False)),
                skipped=not should_run_gemini_quality_oracle(defaults, args),
            ),
            "outputs": [display(path) for path in oracle_paths],
        },
    ]


def dry_run_media_status(paths: FlowPaths, args: argparse.Namespace) -> str:
    if not args.resolve_media:
        return "skipped" if paths.media_resolver_hydrated.exists() else "generated"
    if args.force or bool(getattr(args, "force_media", False)):
        return "generated"
    if _is_fresh(paths.media_resolver_hydrated, [paths.media_resolver_deduped]):
        return "cached"
    return "generated"


def dry_run_vfx_status(payload_paths: list[Path], defaults: Json, args: argparse.Namespace) -> str:
    if layout_recipe(defaults, args) != CANONICAL_LAYOUT_RECIPE:
        return "skipped"
    if args.force or bool(getattr(args, "force_payloads", False)) or bool(getattr(args, "force_vfx", False)):
        return "generated"
    return "cached" if payload_paths and all(payload_matches_layout_recipe(path, CANONICAL_LAYOUT_RECIPE) for path in payload_paths) else "generated"


def dry_run_single_output_status(output: Path, *, force: bool = False, skipped: bool = False) -> str:
    return dry_run_many_output_status([output], force=force, skipped=skipped)


def dry_run_many_output_status(outputs: list[Path], *, force: bool = False, skipped: bool = False) -> str:
    if skipped:
        return "skipped"
    if not outputs:
        return "skipped"
    return "generated" if force or not all(path.exists() for path in outputs) else "cached"


def dry_run_many_fresh_status(
    outputs: list[Path],
    inputs: list[Path | None],
    *,
    force: bool = False,
    skipped: bool = False,
) -> str:
    if skipped:
        return "skipped"
    if not outputs:
        return "skipped"
    required_inputs = [path for path in inputs if path is not None]
    if any(not path.exists() for path in required_inputs):
        return "generated"
    return "cached" if not force and all(_is_fresh(output, inputs) for output in outputs) else "generated"


def source_quality_gate_config(defaults: Json, args: argparse.Namespace) -> Json:
    configured = defaults.get("source_quality_gate") if isinstance(defaults.get("source_quality_gate"), dict) else {}
    enabled = (
        bool(getattr(args, "source_quality_gate"))
        if getattr(args, "source_quality_gate", None) is not None
        else bool(configured.get("enabled", False))
    )
    model = str(getattr(args, "source_quality_model", "") or configured.get("model") or DEFAULT_SOURCE_QUALITY_MODEL).strip()
    raw_fallback_models = (
        getattr(args, "source_quality_fallback_model", [])
        or configured.get("fallback_models")
        or DEFAULT_SOURCE_QUALITY_FALLBACK_MODELS
    )
    fallback_models = _string_list(raw_fallback_models)
    min_score = int(
        _arg_or_default(
            getattr(args, "source_quality_min_score", None),
            configured,
            "min_score",
            DEFAULT_SOURCE_QUALITY_MIN_SCORE,
        )
    )
    accept_safe_mode = (
        bool(getattr(args, "source_quality_accept_safe_mode"))
        if getattr(args, "source_quality_accept_safe_mode", None) is not None
        else bool(configured.get("accept_safe_mode", False))
    )
    concurrency = int(
        _arg_or_default(
            getattr(args, "source_quality_concurrency", None),
            configured,
            "concurrency",
            2,
        )
    )
    return {
        "enabled": enabled,
        "model": model or DEFAULT_SOURCE_QUALITY_MODEL,
        "fallback_models": fallback_models,
        "min_score": max(0, min(100, min_score)),
        "accept_safe_mode": accept_safe_mode,
        "concurrency": max(1, concurrency),
    }


def should_run_source_quality_gate(defaults: Json, args: argparse.Namespace) -> bool:
    return bool(source_quality_gate_config(defaults, args).get("enabled"))


def layout_recipe(defaults: Json, args: argparse.Namespace) -> str:
    value = str(getattr(args, "layout_recipe", "") or defaults.get("layout_recipe") or CANONICAL_LAYOUT_RECIPE).strip()
    return value or CANONICAL_LAYOUT_RECIPE


def vfx_timing_mode(defaults: Json, args: argparse.Namespace) -> str:
    configured = defaults.get("vfx_timing") if isinstance(defaults.get("vfx_timing"), dict) else {}
    value = str(getattr(args, "vfx_timing_mode", "") or configured.get("mode") or DEFAULT_VFX_TIMING_MODE).strip()
    return value if value in {"cached_gemini_or_deterministic", "deterministic"} else DEFAULT_VFX_TIMING_MODE


def vfx_timing_model(defaults: Json) -> str:
    configured = defaults.get("vfx_timing") if isinstance(defaults.get("vfx_timing"), dict) else {}
    return str(configured.get("model") or "gemini-3-flash-preview")


def avatar_overlay_config(defaults: Json, args: argparse.Namespace) -> Json:
    configured = defaults.get("avatar_overlay") if isinstance(defaults.get("avatar_overlay"), dict) else {}
    source = str(getattr(args, "avatar_overlay_source_video", "") or configured.get("source_video_path") or "").strip()
    auto_discover = bool(configured.get("auto_discover_source", True))
    heygen_download_requested = bool(getattr(args, "with_heygen_avatar", False) and getattr(args, "heygen_download", False))
    requested = (
        bool(getattr(args, "avatar_overlay"))
        if getattr(args, "avatar_overlay", None) is not None
        else bool(configured.get("enabled", False) or source or heygen_download_requested)
    )
    width = int(getattr(args, "avatar_overlay_width_px", None) or configured.get("width_px") or DEFAULT_AVATAR_OVERLAY_WIDTH_PX)
    position = str(getattr(args, "avatar_overlay_position", "") or configured.get("position") or DEFAULT_AVATAR_OVERLAY_POSITION)
    if position != DEFAULT_AVATAR_OVERLAY_POSITION:
        position = DEFAULT_AVATAR_OVERLAY_POSITION
    auto_discover_source = bool(requested and not source and auto_discover)
    return {
        "requested": requested,
        "enabled": bool(requested and (source or auto_discover_source)),
        "source_video_path": source,
        "auto_discover_source": auto_discover_source,
        "source_discovery": "explicit_path" if source else "heygen_avatar_manifest",
        "width_px": max(80, min(420, width)),
        "position": position,
        "chromakey": "green",
        "heygen_generation_in_scope": bool(heygen_download_requested),
    }


def expected_payload_paths(voiceover_batch: Any, paths: FlowPaths) -> list[Path]:
    return [paths.html_payload_dir / f"{item.post_id}.html-layout.generated.json" for item in getattr(voiceover_batch, "items", [])]


def annotate_layout_vfx_payloads(
    html_payloads: dict[str, Path],
    *,
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> dict[str, Path]:
    recipe = layout_recipe(defaults, args)
    if recipe != CANONICAL_LAYOUT_RECIPE:
        return html_payloads
    outputs: dict[str, Path] = {}
    force_vfx = bool(getattr(args, "force_vfx", False) or getattr(args, "force_payloads", False) or args.force)
    mode = vfx_timing_mode(defaults, args)
    for post_id, payload_path in html_payloads.items():
        if payload_matches_layout_recipe(payload_path, recipe) and not force_vfx:
            outputs[post_id] = payload_path
            continue
        cmd = [
            sys.executable,
            "scripts/annotate_layout_vfx_timings.py",
            "--input",
            str(payload_path),
            "--output",
            str(payload_path),
            "--composition-id",
            f"girly-static-v5-final-{post_id}",
            "--model",
            vfx_timing_model(defaults),
        ]
        if mode == "deterministic":
            cmd.append("--no-gemini")
        if force_vfx:
            cmd.append("--force")
        run_command(cmd, cwd=ROOT)
        mark_payload_layout_recipe(payload_path, recipe=recipe)
        outputs[post_id] = payload_path
    return outputs


def payload_matches_layout_recipe(payload_path: Path, recipe: str) -> bool:
    if not payload_path.exists():
        return False
    try:
        payload = read_json(payload_path)
    except (OSError, json.JSONDecodeError):
        return False
    scenes = payload.get("scenes") if isinstance(payload.get("scenes"), list) else []
    return payload.get("layout_mode") == recipe and all(
        isinstance(scene, dict) and isinstance(scene.get("vfx_timings"), list)
        for scene in scenes
    )


def mark_payload_layout_recipe(payload_path: Path, *, recipe: str) -> None:
    payload = read_json(payload_path)
    payload["layout_mode"] = recipe
    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "variant": recipe,
            "layout_recipe": recipe,
            "change_scope": (
                "layout-only: hide repeated caption chrome text labels; keep bars/tape/rails/media micro captions/assets/timings"
            ),
        }
    )
    payload["metadata"] = metadata
    write_json(payload_path, payload)


def apply_avatar_overlay_to_renders(
    rendered: dict[str, Path],
    *,
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> dict[str, Path]:
    config = avatar_overlay_config(defaults, args)
    if not config["enabled"]:
        return {}
    outputs: dict[str, Path] = {}
    for post_id, base_video in rendered.items():
        source_path = avatar_overlay_source_for_post(post_id, defaults=defaults, args=args, paths=paths)
        if source_path is None or not source_path.exists():
            continue
        out_path = paths.avatar_overlay_dir / f"{post_id}-final-sync-avatar.mp4"
        payload_path = paths.html_payload_dir / f"{post_id}.html-layout.generated.json"
        final_scene_start_sec = avatar_overlay_final_scene_start_sec(payload_path)
        overlay_inputs = [base_video, source_path, payload_path]
        if (
            not args.force
            and not bool(getattr(args, "force_render", False))
            and _is_fresh(out_path, overlay_inputs)
        ):
            outputs[post_id] = out_path
            continue
        run_command(
            [
                ffmpeg_binary(),
                "-hide_banner",
                "-y",
                "-i",
                str(base_video),
                "-i",
                str(source_path),
                "-filter_complex",
                avatar_overlay_filter(
                    width_px=int(config["width_px"]),
                    position=str(config["position"]),
                    hide_from_sec=final_scene_start_sec,
                ),
                "-map",
                "[v]",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(out_path),
            ],
            cwd=ROOT,
        )
        outputs[post_id] = out_path
    return outputs


def avatar_overlay_source_for_post(
    post_id: str,
    *,
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> Path | None:
    config = avatar_overlay_config(defaults, args)
    explicit_source = str(config.get("source_video_path") or "").strip()
    if explicit_source:
        return resolve_required_input_path(explicit_source)
    if not config.get("auto_discover_source"):
        return None
    manifest = heygen_avatar_manifest(paths)
    item = manifest.get(post_id) if isinstance(manifest.get(post_id), dict) else {}
    downloaded = str(item.get("downloaded_video") or "").strip()
    return resolve_required_input_path(downloaded) if downloaded else None


def avatar_overlay_input_paths(
    rendered: dict[str, Path],
    *,
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> list[Path]:
    return avatar_overlay_input_paths_for_post_ids(list(rendered.keys()), defaults=defaults, args=args, paths=paths)


def avatar_overlay_input_paths_for_post_ids(
    post_ids: list[str],
    *,
    defaults: Json,
    args: argparse.Namespace,
    paths: FlowPaths,
) -> list[Path]:
    config = avatar_overlay_config(defaults, args)
    if not config.get("enabled"):
        return []
    explicit_source = str(config.get("source_video_path") or "").strip()
    if explicit_source:
        return [resolve_required_input_path(explicit_source)]
    manifest_path = paths.heygen_dir / "heygen-avatar-manifest.json"
    inputs = [manifest_path]
    for post_id in post_ids:
        source = avatar_overlay_source_for_post(post_id, defaults=defaults, args=args, paths=paths)
        if source is not None:
            inputs.append(source)
        inputs.append(paths.html_payload_dir / f"{post_id}.html-layout.generated.json")
    return dedupe_paths(inputs)


def heygen_avatar_manifest(paths: FlowPaths) -> Json:
    manifest_path = paths.heygen_dir / "heygen-avatar-manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def dedupe_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def avatar_overlay_final_scene_start_sec(payload_path: Path) -> float | None:
    if not payload_path.exists():
        return None
    try:
        payload = read_json(payload_path)
    except (OSError, json.JSONDecodeError):
        return None
    scenes = payload.get("scenes") if isinstance(payload, dict) else None
    if not isinstance(scenes, list) or not scenes:
        return None
    last_scene = scenes[-1]
    if not isinstance(last_scene, dict):
        return None
    fps = float(payload.get("fps") or 30)
    if fps <= 0:
        fps = 30
    start_frame = last_scene.get("start_frame")
    if start_frame is None:
        start_frame = sum(
            int(scene.get("duration_frames") or 0)
            for scene in scenes[:-1]
            if isinstance(scene, dict)
        )
    try:
        return max(0.0, float(start_frame) / fps)
    except (TypeError, ValueError):
        return None


def avatar_overlay_filter(*, width_px: int, position: str, hide_from_sec: float | None = None) -> str:
    if position != DEFAULT_AVATAR_OVERLAY_POSITION:
        position = DEFAULT_AVATAR_OVERLAY_POSITION
    overlay = "x=W-w-12:y=H-h+6"
    fade = ""
    if hide_from_sec is not None:
        fade_start = max(0.0, float(hide_from_sec))
        fade = f",fade=t=out:st={fade_start:.3f}:d=0.250:alpha=1"
    return (
        f"[1:v]scale={width_px}:-1,format=rgba,"
        f"colorkey=0x00ff00:0.18:0.06,despill=green{fade}[avatar];"
        f"[0:v][avatar]overlay={overlay}:shortest=1:format=auto[v]"
    )


def ffmpeg_binary() -> str:
    return os.environ.get("FFMPEG_BINARY") or "ffmpeg"


def output_snapshot(paths: list[Path | None]) -> dict[str, Json]:
    snapshot: dict[str, Json] = {}
    for path in paths:
        if path is None:
            continue
        try:
            stat = path.stat()
        except OSError:
            snapshot[str(path)] = {"exists": False}
            continue
        snapshot[str(path)] = {
            "exists": True,
            "mtime_ns": stat.st_mtime_ns,
            "size_bytes": stat.st_size if path.is_file() else 0,
        }
    return snapshot


def snapshot_had_all_outputs(snapshot: dict[str, Json]) -> bool:
    return bool(snapshot) and all(bool(item.get("exists")) for item in snapshot.values())


def stage_status_from_snapshot(
    outputs: list[Path],
    before: dict[str, Json],
    *,
    force: bool = False,
    skipped: bool = False,
) -> str:
    if skipped:
        return "skipped"
    if not outputs:
        return "skipped"
    if force or not snapshot_had_all_outputs(before):
        return "generated"
    after = output_snapshot(outputs)
    for output in outputs:
        key = str(output)
        if before.get(key) != after.get(key):
            return "generated"
    return "cached"


def tts_stage_status(tts_outputs: dict[str, Json], *, generated: bool, before: dict[str, Json], manifest_path: Path) -> str:
    if not generated and not tts_outputs:
        return "skipped"
    if any(str(item.get("status") or "") == "generated" for item in tts_outputs.values() if isinstance(item, dict)):
        return "generated"
    if generated and not snapshot_had_all_outputs(before) and manifest_path.exists():
        return "generated"
    return "cached" if tts_outputs else "skipped"


def count_tts_generated_items(tts_outputs: dict[str, Json]) -> int:
    return sum(
        1
        for item in tts_outputs.values()
        if isinstance(item, dict) and str(item.get("status") or "") == "generated"
    )


def production_file_entry(path: Path) -> Json:
    entry: Json = {"path": display(path), "exists": path.exists()}
    if not path.exists():
        return entry
    try:
        stat = path.stat()
    except OSError:
        return entry
    entry["mtime"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    if path.is_file():
        entry["size_bytes"] = stat.st_size
        entry["sha256"] = sha256_file(path)
    return entry


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_heygen_internal() -> tuple[Any, Any]:
    global HeyGenInternalClient, _latest_storage_state
    if HeyGenInternalClient is None or _latest_storage_state is None:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        from heygen_internal import HeyGenInternalClient as loaded_client  # noqa: PLC0415
        from heygen_internal import _latest_storage_state as loaded_latest_storage_state  # noqa: PLC0415

        HeyGenInternalClient = loaded_client
        _latest_storage_state = loaded_latest_storage_state
    return HeyGenInternalClient, _latest_storage_state


def should_repair_pronunciation(defaults: Json, args: argparse.Namespace) -> bool:
    if args.repair_pronunciation is not None:
        return bool(args.repair_pronunciation)
    return bool(defaults.get("pronunciation_repair"))


def forced_pronunciation_issues(defaults: Json, args: argparse.Namespace) -> list[PronunciationIssue]:
    raw_fixes = [str(value) for value in defaults.get("pronunciation_repair_force_fixes") or []]
    raw_fixes.extend(str(value) for value in args.pronunciation_force_fix)
    return [parse_forced_pronunciation_issue(raw_fix, index=index) for index, raw_fix in enumerate(raw_fixes, start=1)]


def parse_forced_pronunciation_issue(raw_fix: str, *, index: int) -> PronunciationIssue:
    if "=" not in raw_fix:
        raise SystemExit(f"pronunciation force fix must look like word=replacement or scene_id:word=replacement: {raw_fix}")
    left, replacement = raw_fix.split("=", 1)
    scene_id = None
    word = left.strip()
    if ":" in left:
        raw_scene_id, word = left.split(":", 1)
        try:
            scene_id = int(raw_scene_id)
        except ValueError as exc:
            raise SystemExit(f"pronunciation force fix scene id must be an integer: {raw_fix}") from exc
    word = word.strip()
    replacement = replacement.strip()
    if not word or not replacement:
        raise SystemExit(f"pronunciation force fix must include both word and replacement: {raw_fix}")
    return PronunciationIssue(
        issue_id=f"forced_{index}",
        scene_id=scene_id,
        heard_word=word,
        expected_word=replacement,
        replacement_text=replacement,
        reason="Forced pronunciation hint.",
        severity="high",
        confidence=1.0,
        needs_repair=True,
    )


def validate_posts(manifest: Json) -> list[Json]:
    posts = manifest.get("posts")
    if not isinstance(posts, list) or not posts:
        raise SystemExit("manifest must contain a non-empty posts array")
    result = []
    for raw in posts:
        if not isinstance(raw, dict):
            raise SystemExit("manifest posts must be objects")
        post_id = str(raw.get("post_id") or "").strip()
        if not post_id:
            raise SystemExit("every manifest post needs post_id")
        result.append({**raw, "post_id": post_id})
    return result


def requested_post_ids(args: argparse.Namespace, posts: list[Json]) -> list[str]:
    requested: list[str] = []
    for raw_value in getattr(args, "post_id", []) or []:
        for raw_post_id in str(raw_value).split(","):
            post_id = raw_post_id.strip()
            if post_id and post_id not in requested:
                requested.append(post_id)
    if not requested:
        return []
    known = {str(post.get("post_id") or "") for post in posts}
    unknown = [post_id for post_id in requested if post_id not in known]
    if unknown:
        raise SystemExit(f"Unknown --post-id values: {', '.join(unknown)}")
    return requested


def filter_manifest_posts(posts: list[Json], post_ids: list[str]) -> list[Json]:
    if not post_ids:
        return posts
    wanted = set(post_ids)
    return [post for post in posts if str(post.get("post_id") or "") in wanted]


def filter_batch_by_post_ids(batch: Any, post_ids: list[str], *, label: str) -> Any:
    if not post_ids:
        return batch
    items = getattr(batch, "items", None)
    if not isinstance(items, list):
        raise SystemExit(f"Cannot filter {label}: batch has no items list")
    wanted = set(post_ids)
    filtered_items = [item for item in items if str(getattr(item, "post_id", "")) in wanted]
    found = {str(getattr(item, "post_id", "")) for item in filtered_items}
    missing = [post_id for post_id in post_ids if post_id not in found]
    if missing:
        raise SystemExit(f"Cannot filter {label}: missing post ids: {', '.join(missing)}")
    return replace(batch, items=filtered_items)


def scope_token_for_posts(post_ids: list[str]) -> str:
    return safe_token("posts-" + "-".join(post_ids))


def run_command(cmd: list[str], *, cwd: Path) -> None:
    print("+ " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def read_json(path: Path) -> Json:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _arg_or_default(value: Any, defaults: Json, key: str, fallback: Any) -> Any:
    if value is not None:
        return value
    configured = defaults.get(key)
    return configured if configured is not None else fallback


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def resolve_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def resolve_required_input_path(path: str) -> Path:
    if not path.strip():
        return ROOT / "__missing_input__"
    return resolve_path(path)


def resolve_optional_input_path(path: str) -> Path | None:
    return resolve_path(path) if path.strip() else None


def _is_fresh(output: Path, inputs: list[Path | None]) -> bool:
    if not output.exists():
        return False
    try:
        output_mtime = output.stat().st_mtime
    except OSError:
        return False
    for input_path in inputs:
        if input_path is None or not input_path.exists():
            continue
        try:
            if input_path.stat().st_mtime > output_mtime:
                return False
        except OSError:
            return False
    return True


def make_run_id(prefix: str) -> str:
    return f"{safe_token(prefix)}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def safe_token(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return safe[:90] or "item"


def public_path(path: Path) -> str:
    public_root = ROOT / "remotion" / "public"
    try:
        return str(path.resolve().relative_to(public_root.resolve()))
    except ValueError:
        return str(path)


def display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
