#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from html import unescape
import json
import os
import re
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from reddit2video.gemini import GeminiClient, GeminiClientError  # noqa: E402


class EditorialObservation(BaseModel):
    area: str
    assessment: Literal["publication_ready", "minor_issue", "major_issue", "blocker"]
    explanation: str
    visible_evidence: str = ""


class VideoQualityVerdict(BaseModel):
    verdict: Literal["pass", "fail"]
    publication_summary: str
    editorial_observations: list[EditorialObservation]
    blocking_defects: list[str]
    must_fix_before_publish: list[str] = Field(default_factory=list)
    nice_to_improve: list[str] = Field(default_factory=list)
    anti_degradation_flags: list[str] = Field(default_factory=list)
    calibration_risk_flags: list[str] = Field(default_factory=list)


RUBRIC_PROMPT = """Ты независимый выпускной редактор short/reels видео, а не дружелюбный оценщик.
Оцени загруженный reddit-to-video ролик как финальный кандидат на публикацию: {video_file}.
{transcript_context}

Не сравнивай его с другими версиями и не делай предположений о процессе генерации. Оцени только финальный видеофайл.
Не выставляй числовые оценки и не пытайся "найти хороший балл".
Это не метрика и не leaderboard. Это редакторский выпускной вердикт:
- pass: ролик можно публиковать как есть или с мелкими необязательными улучшениями;
- fail: перед публикацией нужно исправить хотя бы один blocker/major issue.

Если сомневаешься, ставь fail и объясняй видимое основание. Не проходи ролик за "старание".

Отдельно проверь анти-деградацию:
- ролик не должен быть в основном одним синхронным текстом поверх слабого/случайного фона;
- картинки, видео, коллажи или графические приемы должны реально поддерживать сцены, а не быть редкими украшениями;
- если много сцен выглядят как одинаковые текстовые карточки, это major/blocker даже при хорошей читаемости;
- если медиа выглядят спрятанными, подавленными или смысл держится только на caption, это не publication-ready.

Для каждого критерия дай visible_evidence: конкретный видимый признак, timestamp, повторяющийся паттерн или "not visible".
Если не можешь привести видимое доказательство для высокой оценки критерия, оценка по этому критерию не должна быть 5.

Обязательно проверь эти области:
1. Понятность истории и reddit-формата.
2. Синхронизация аудио, субтитров и визуала.
3. Качество озвучки.
4. Читаемость субтитров/текста.
5. Визуальная цельность.
6. Темп и удержание внимания.
7. Техническая чистота рендера.
8. Соответствие короткому вертикальному видео.
9. Общее впечатление публикационной готовности.

Для каждой области верни assessment:
- publication_ready;
- minor_issue;
- major_issue;
- blocker.

Для каждого assessment дай visible_evidence: конкретный видимый/слышимый признак, timestamp, повторяющийся паттерн или "not visible".
Если есть blocker или major_issue, verdict должен быть fail, а must_fix_before_publish должен содержать конкретное исправление.
Если ролик выглядит как "один текст с редкими фонами", это fail даже если технически все чисто.

При проверке озвучки сверяй слышимый текст с EXPECTED TRANSCRIPT, если он дан ниже.
Не считай дефектом слово, частицу или слог, которые присутствуют в ожидаемом тексте этой сцены.
Если подозрение на сбой голоса основано только на том, что ожидаемая фраза звучит необычно, добавь calibration_risk_flags, но не делай это blocker без явного несовпадения с transcript.

Верни verdict: pass/fail, publication_summary, editorial_observations, blocking_defects, must_fix_before_publish, nice_to_improve, anti_degradation_flags и calibration_risk_flags.

anti_degradation_flags используй для видимых признаков, которые мешают публикации:
- mostly_text_cards;
- media_is_decorative_not_semantic;
- generic_template_feel;
- weak_scene_variety;
- caption_carries_the_video;
- unreadable_or_crowded_text;
- broken_or_blank_visuals.

calibration_risk_flags используй только если твоя оценка может быть ненадежной:
- evidence_too_generic;
- audio_not_confidently_checked.

Ответ верни строго в JSON."""


def main() -> int:
    return asyncio.run(_amain(parse_args()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate one MP4 with Gemini against the independent video rubric.")
    parser.add_argument("--video", required=True, help="Path to the MP4 to evaluate.")
    parser.add_argument("--payload", default="", help="Optional Remotion payload JSON with scene transcript/timings.")
    parser.add_argument("--out", default="", help="Optional JSON output path.")
    parser.add_argument("--model", default="gemini-3.1-pro-preview")
    parser.add_argument("--vertex", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--env-file", action="append", default=[".env.iac", ".env"])
    return parser.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    for env_file in args.env_file:
        load_env_file(Path(env_file))

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        raise SystemExit(f"video does not exist: {video_path}")
    transcript_context = transcript_context_from_payload(resolve_optional_path(str(args.payload)))

    client = GeminiClient.from_env(model=str(args.model), vertex=bool(args.vertex))
    try:
        try:
            verdict = await client.generate_structured_multimodal(
                prompt=RUBRIC_PROMPT.format(video_file=str(video_path), transcript_context=transcript_context),
                image_paths=[video_path],
                response_model=VideoQualityVerdict,
            )
        except GeminiClientError as exc:
            raise SystemExit(f"Gemini quality oracle unavailable: {exc}") from None
    finally:
        await client.aclose()

    payload = verdict.model_dump()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    return 0


def resolve_optional_path(value: str) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def transcript_context_from_payload(payload_path: Path | None) -> str:
    if payload_path is None or not payload_path.exists():
        return ""
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    scenes = payload.get("scenes") if isinstance(payload, dict) else None
    if not isinstance(scenes, list):
        return ""
    lines: list[str] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        line = transcript_line_for_scene(scene)
        if not line:
            continue
        scene_id = int(scene.get("scene_id") or len(lines) + 1)
        start_sec, end_sec = scene_time_bounds(scene)
        lines.append(f"- s{scene_id:02d} {start_sec:.2f}-{end_sec:.2f}s: {line}")
    if not lines:
        return ""
    return "\nEXPECTED TRANSCRIPT (слова, которые диктор должен произнести; используй для проверки TTS):\n" + "\n".join(
        lines[:80]
    )


def transcript_line_for_scene(scene: dict) -> str:
    timed_words = scene.get("word_timings")
    if isinstance(timed_words, list):
        words = [
            str(word.get("text") or word.get("word") or "").strip()
            for word in timed_words
            if isinstance(word, dict) and str(word.get("text") or word.get("word") or "").strip()
        ]
        if words:
            return normalize_transcript_text(" ".join(words))
    html = str(scene.get("html") or "")
    match = re.search(
        r"<div\b[^>]*\bdata-girly-sync-caption=(['\"])true\1[^>]*>(?P<body>.*?)</div>",
        html,
        flags=re.I | re.S,
    )
    if not match:
        return ""
    return normalize_transcript_text(match.group("body"))


def normalize_transcript_text(value: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def scene_time_bounds(scene: dict) -> tuple[float, float]:
    words = [word for word in scene.get("word_timings") or [] if isinstance(word, dict)]
    starts = [float(word.get("start_sec")) for word in words if isinstance(word.get("start_sec"), (int, float))]
    ends = [float(word.get("end_sec")) for word in words if isinstance(word.get("end_sec"), (int, float))]
    if starts and ends:
        return min(starts), max(ends)
    fps = 30.0
    start_frame = float(scene.get("start_frame") or 0)
    duration_frames = float(scene.get("duration_frames") or 0)
    return start_frame / fps, (start_frame + duration_frames) / fps


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
