#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.gemini import GeminiClient  # noqa: E402
from reddit2video.inworld import InworldTTSClient  # noqa: E402
from reddit2video.pronunciation_repair import PronunciationIssue, repair_pronunciation_audio  # noqa: E402


def main() -> int:
    return asyncio.run(_amain(parse_args()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use Gemini to locate Russian TTS pronunciation/stress errors, then full-revoice corrected TTS text or splice one-word fixes.",
    )
    parser.add_argument("--audio", required=True, help="Original generated audio path.")
    parser.add_argument("--alignment", required=True, help="Inworld/ElevenLabs character alignment JSON.")
    parser.add_argument("--scene-lines", required=True, help="scene-lines.tts.json used for the generated audio.")
    parser.add_argument("--out-audio", required=True, help="Patched audio path.")
    parser.add_argument("--out-alignment", default="", help="Alignment JSON for full-revoice output.")
    parser.add_argument("--out-scene-lines", default="", help="TTS scene-lines JSON with pronunciation hints for full-revoice output.")
    parser.add_argument("--report", required=True, help="JSON report path.")
    parser.add_argument("--work-dir", default="", help="Temp/intermediate directory. Defaults next to report.")
    parser.add_argument("--voice-id", default="", help="Voice id. Defaults to scene-lines voice_id or env/default.")
    parser.add_argument("--model", default="gemini-3.1-pro-preview")
    parser.add_argument("--vertex", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-issues", type=int, default=4)
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--strategy", choices=["full_revoice", "splice"], default="full_revoice")
    parser.add_argument(
        "--seed-report",
        action="append",
        default=[],
        help="Previous pronunciation repair report whose audit issues should be reused as forced hints.",
    )
    parser.add_argument(
        "--force-fix",
        action="append",
        default=[],
        help="Forced hint as word=replacement or scene_id:word=replacement, e.g. 1:пилатеса=pilates-а.",
    )
    parser.add_argument("--verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--env-file", action="append", default=[".env.iac", ".env"])
    return parser.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    for env_file in args.env_file:
        load_env_file(ROOT / env_file)

    audio_path = resolve_path(args.audio)
    alignment_path = resolve_path(args.alignment)
    scene_lines_path = resolve_path(args.scene_lines)
    out_audio_path = resolve_path(args.out_audio)
    report_path = resolve_path(args.report)
    work_dir = resolve_path(args.work_dir) if args.work_dir else report_path.parent / "pronunciation-work"
    out_alignment_path = resolve_path(args.out_alignment) if args.out_alignment else report_path.parent / "revoiced.alignment.json"
    out_scene_lines_path = (
        resolve_path(args.out_scene_lines) if args.out_scene_lines else report_path.parent / "revoiced.scene-lines.tts.json"
    )

    alignment = read_json(alignment_path)
    scene_lines = read_json(scene_lines_path)
    seed_issues = load_seed_issues(args.seed_report, args.force_fix)
    voice_id = str(args.voice_id or scene_lines.get("voice_id") or os.getenv("INWORLD_TTS_VOICE_ID") or "Svetlana")

    gemini = GeminiClient.from_env(model=str(args.model), vertex=bool(args.vertex))
    tts = InworldTTSClient.from_env()
    try:
        result = await repair_pronunciation_audio(
            gemini=gemini,
            tts=tts,
            audio_path=audio_path,
            alignment=alignment,
            scene_lines=scene_lines,
            voice_id=voice_id,
            work_dir=work_dir,
            output_path=out_audio_path,
            model=str(args.model),
            max_issues=max(0, int(args.max_issues)),
            min_confidence=max(0.0, min(1.0, float(args.min_confidence))),
            verify=bool(args.verify),
            strategy=str(args.strategy),
            alignment_output_path=out_alignment_path,
            scene_lines_output_path=out_scene_lines_path,
            seed_issues=seed_issues,
        )
    finally:
        await gemini.aclose()
        await tts.aclose()

    payload = result.model_dump()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"missing JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_seed_issues(report_paths: list[str], force_fixes: list[str]) -> list[PronunciationIssue]:
    issues: list[PronunciationIssue] = []
    for index, raw_fix in enumerate(force_fixes, start=1):
        issues.append(parse_force_fix(raw_fix, index=index))
    for report_path in report_paths:
        payload = read_json(resolve_path(report_path))
        raw_issues = (payload.get("audit") or {}).get("issues") or []
        for raw in raw_issues:
            if isinstance(raw, dict):
                issues.append(PronunciationIssue.model_validate(raw))
    return issues


def parse_force_fix(raw_fix: str, *, index: int) -> PronunciationIssue:
    if "=" not in raw_fix:
        raise SystemExit(f"--force-fix must look like word=replacement or scene_id:word=replacement: {raw_fix}")
    left, replacement = raw_fix.split("=", 1)
    scene_id = None
    word = left.strip()
    if ":" in left:
        raw_scene_id, word = left.split(":", 1)
        try:
            scene_id = int(raw_scene_id)
        except ValueError as exc:
            raise SystemExit(f"--force-fix scene id must be an integer: {raw_fix}") from exc
    word = word.strip()
    replacement = replacement.strip()
    if not word or not replacement:
        raise SystemExit(f"--force-fix must include both word and replacement: {raw_fix}")
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


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


if __name__ == "__main__":
    raise SystemExit(main())
