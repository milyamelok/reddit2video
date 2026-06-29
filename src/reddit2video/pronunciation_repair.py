from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from reddit2video.errors import NodeError


class PronunciationRepairError(NodeError):
    pass


class PronunciationIssue(BaseModel):
    issue_id: str = ""
    scene_id: Optional[int] = None
    heard_word: str
    expected_word: str = ""
    replacement_text: str
    alternatives: list[str] = Field(default_factory=list)
    reason: str
    severity: Literal["low", "medium", "high"] = "medium"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_repair: bool = True


class PronunciationAudit(BaseModel):
    verdict: Literal["pass", "needs_repair"]
    issues: list[PronunciationIssue] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RemainingPronunciationIssue(BaseModel):
    word: str
    scene_id: Optional[int] = None
    reason: str
    severity: Literal["low", "medium", "high"] = "medium"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PronunciationVerification(BaseModel):
    verdict: Literal["pass", "remaining_issues"]
    remaining_issues: list[RemainingPronunciationIssue] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AppliedPronunciationRepair(BaseModel):
    issue: PronunciationIssue
    source_start_sec: float
    source_end_sec: float
    replacement_audio_path: str
    fitted_audio_path: str


class AppliedPronunciationTextRepair(BaseModel):
    issue: PronunciationIssue
    scene_id: Optional[int] = None
    original_word: str
    replacement_text: str
    original_scene_line: str
    repaired_scene_line: str


class PronunciationRepairResult(BaseModel):
    status: Literal["pass_no_issues", "repaired", "revoiced", "skipped_no_locatable_issues"]
    strategy: Literal["splice", "full_revoice"] = "full_revoice"
    original_audio_path: str
    repaired_audio_path: str
    audit: PronunciationAudit
    applied_repairs: list[AppliedPronunciationRepair] = Field(default_factory=list)
    applied_text_repairs: list[AppliedPronunciationTextRepair] = Field(default_factory=list)
    skipped_issues: list[PronunciationIssue] = Field(default_factory=list)
    revoiced_alignment_path: str = ""
    revoiced_scene_lines_path: str = ""
    verification: Optional[PronunciationVerification] = None


@dataclass(frozen=True)
class SceneSpan:
    scene_id: int
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class WordSpan:
    text: str
    start_char: int
    end_char: int
    start_sec: float
    end_sec: float
    scene_id: int | None = None


@dataclass(frozen=True)
class LocatedIssue:
    issue: PronunciationIssue
    word: WordSpan


AUDIT_PROMPT = """Ты аудитор русской TTS-озвучки для вертикального reddit-video.
Прослушай аудиофайл и сравни произношение с транскриптом.

Нужно найти только реальные ошибки ударения или произношения, которые слышит обычный русскоязычный зритель.
Особое внимание: англицизмы, латиница, аббревиатуры, бренды, термины, слова вроде "пилатес".
Не флагай естественные варианты диктора, паузы, интонацию или вкусовщину.
Не флагай односложные служебные слова и частицы/предлоги/союзы: "в", "к", "с", "и", "а",
"но", "не", "на", "по", "за", "от", "до", "из", "у", "о".
Не флагай "слито", "проглочено", "пауза", "интонация", "дикция" или "темп", если проблема
не является ошибкой ударения в конкретном слове.
Не флагай грамматику, согласование, число, падеж или окончание слова. Это другой тип QA,
не pronunciation/stress repair.

Для каждой проблемы верни:
- scene_id, если понятно из транскрипта;
- heard_word: слово из транскрипта, которое звучит неправильно;
- expected_word: как слово должно читаться обычной русской речью;
- replacement_text: ровно один лучший токен для замены одного слова. Без пробелов.
  Нельзя возвращать фразу; если нужно заменить фразу или переписать контекст, пропусти issue.
  Важно: внутренние заглавные буквы для ударения НЕ работают надежно.
  Для англицизмов и заимствований вроде "пилатес" и "латте" предпочитай латиницу:
  "пилатес" -> "pilates", "латте" -> "latte"; склонение через дефис:
  "пилатесу" -> "pilates-у", "пилатеса" -> "pilates-а".
  Если латиница неуместна, предложи короткий перефраз.
- alternatives: 1-3 запасных варианта.

Ограничение продакшена: на переозвучку есть одна попытка, поэтому replacement_text должен быть самым надежным вариантом.

Транскрипт сцен JSON:
{scene_transcript}

Ответ строго JSON."""


VERIFY_PROMPT = """Ты проверяешь уже исправленную русскую TTS-озвучку.
Прослушай аудиофайл и сравни произношение с транскриптом.
Нужно оценить только ошибки ударения/произношения, особенно англицизмы, аббревиатуры и термины.
Не флагай односложные служебные слова, паузы, слитность речи, дикцию, темп, грамматику,
согласование, число, падеж или окончания слов. Это не часть pronunciation/stress repair.
Не оценивай дизайн, монтаж, качество ассетов или стиль текста.

Транскрипт сцен JSON:
{scene_transcript}

Верни verdict="pass", если явных ошибок ударения не осталось.
Если остались, верни remaining_issues с кратким reason.
Ответ строго JSON."""


async def repair_pronunciation_audio(
    *,
    gemini: Any,
    tts: Any,
    audio_path: Path,
    alignment: dict[str, Any],
    scene_lines: dict[str, Any],
    voice_id: str,
    work_dir: Path,
    output_path: Path,
    model: str = "gemini-3.1-pro-preview",
    max_issues: int = 4,
    min_confidence: float = 0.55,
    verify: bool = True,
    strategy: Literal["splice", "full_revoice"] = "full_revoice",
    alignment_output_path: Path | None = None,
    scene_lines_output_path: Path | None = None,
    seed_issues: list[PronunciationIssue] | None = None,
) -> PronunciationRepairResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    audit = await audit_pronunciation(
        gemini=gemini,
        audio_path=audio_path,
        scene_lines=scene_lines,
        model=model,
    )
    all_issues = merge_pronunciation_issues(list(seed_issues or []), audit.issues)
    candidates = [
        issue
        for issue in all_issues
        if is_pronunciation_repair_candidate(issue, min_confidence=min_confidence)
    ][:max_issues]
    if not candidates:
        return PronunciationRepairResult(
            status="pass_no_issues",
            strategy=strategy,
            original_audio_path=str(audio_path),
            repaired_audio_path=str(audio_path),
            audit=audit,
        )

    if strategy == "full_revoice":
        repaired_scene_lines, applied_text_repairs, skipped = build_revoiced_scene_lines(scene_lines, candidates)
        if not applied_text_repairs:
            return PronunciationRepairResult(
                status="skipped_no_locatable_issues",
                strategy=strategy,
                original_audio_path=str(audio_path),
                repaired_audio_path=str(audio_path),
                audit=audit,
                skipped_issues=skipped,
            )

        tts_result = await tts.text_to_speech_with_timestamps(
            text=str(repaired_scene_lines["full_text"]),
            voice_id=voice_id,
            output_path=output_path,
        )
        tts_result["source_voiceover"] = repaired_scene_lines["full_text"]
        if scene_lines_output_path:
            scene_lines_output_path.parent.mkdir(parents=True, exist_ok=True)
            scene_lines_output_path.write_text(
                json.dumps(repaired_scene_lines, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if alignment_output_path:
            alignment_output_path.parent.mkdir(parents=True, exist_ok=True)
            alignment_output_path.write_text(
                json.dumps(tts_result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        verification: PronunciationVerification | None = None
        if verify:
            verification = await verify_pronunciation(
                gemini=gemini,
                audio_path=output_path,
                scene_lines=repaired_scene_lines,
                model=model,
            )
        return PronunciationRepairResult(
            status="revoiced",
            strategy=strategy,
            original_audio_path=str(audio_path),
            repaired_audio_path=str(output_path),
            audit=audit,
            applied_text_repairs=applied_text_repairs,
            skipped_issues=skipped,
            revoiced_alignment_path=str(alignment_output_path or ""),
            revoiced_scene_lines_path=str(scene_lines_output_path or ""),
            verification=verification,
        )

    located, skipped = locate_pronunciation_issues(candidates, scene_lines=scene_lines, alignment=alignment)
    if not located:
        return PronunciationRepairResult(
            status="skipped_no_locatable_issues",
            strategy=strategy,
            original_audio_path=str(audio_path),
            repaired_audio_path=str(audio_path),
            audit=audit,
            skipped_issues=skipped,
        )

    replacement_dir = work_dir / "pronunciation-replacements"
    fitted_dir = work_dir / "pronunciation-fitted"
    replacement_dir.mkdir(parents=True, exist_ok=True)
    fitted_dir.mkdir(parents=True, exist_ok=True)

    applied: list[AppliedPronunciationRepair] = []
    for index, located_issue in enumerate(located, start=1):
        issue = located_issue.issue
        repair_id = issue.issue_id or f"repair-{index:02d}"
        replacement_path = replacement_dir / f"{safe_filename(repair_id)}.mp3"
        fitted_path = fitted_dir / f"{safe_filename(repair_id)}.mp3"
        await tts.text_to_speech_with_timestamps(
            text=issue.replacement_text.strip(),
            voice_id=voice_id,
            output_path=replacement_path,
        )
        fit_audio_to_duration(
            replacement_path,
            fitted_path,
            target_duration_sec=max(0.08, located_issue.word.end_sec - located_issue.word.start_sec),
        )
        applied.append(
            AppliedPronunciationRepair(
                issue=issue,
                source_start_sec=round(located_issue.word.start_sec, 4),
                source_end_sec=round(located_issue.word.end_sec, 4),
                replacement_audio_path=str(replacement_path),
                fitted_audio_path=str(fitted_path),
            )
        )

    splice_audio_replacements(
        original_audio_path=audio_path,
        replacements=applied,
        output_path=output_path,
        work_dir=work_dir / "pronunciation-splice",
    )

    verification: PronunciationVerification | None = None
    if verify:
        verification = await verify_pronunciation(
            gemini=gemini,
            audio_path=output_path,
            scene_lines=scene_lines,
            model=model,
        )

    return PronunciationRepairResult(
        status="repaired",
        strategy=strategy,
        original_audio_path=str(audio_path),
        repaired_audio_path=str(output_path),
        audit=audit,
        applied_repairs=applied,
        skipped_issues=skipped,
        verification=verification,
    )


def merge_pronunciation_issues(
    *groups: list[PronunciationIssue],
) -> list[PronunciationIssue]:
    merged: list[PronunciationIssue] = []
    seen: set[tuple[int | None, str]] = set()
    for issue in [issue for group in groups for issue in group]:
        key = (issue.scene_id, normalize_token(issue.heard_word or issue.expected_word))
        if key in seen:
            continue
        seen.add(key)
        merged.append(issue)
    return merged


def is_pronunciation_repair_candidate(issue: PronunciationIssue, *, min_confidence: float) -> bool:
    if not issue.needs_repair:
        return False
    if issue.severity not in {"medium", "high"}:
        return False
    if issue.confidence < min_confidence:
        return False
    heard = normalize_token(issue.heard_word or issue.expected_word)
    if len(heard) <= 2:
        return False
    replacement = issue.replacement_text.strip()
    if not replacement:
        return False
    if any(char.isspace() for char in replacement):
        return False
    return True


def build_revoiced_scene_lines(
    scene_lines: dict[str, Any],
    issues: list[PronunciationIssue],
) -> tuple[dict[str, Any], list[AppliedPronunciationTextRepair], list[PronunciationIssue]]:
    repaired = json.loads(json.dumps(scene_lines, ensure_ascii=False))
    scenes = repaired.get("scenes") if isinstance(repaired, dict) else []
    if not isinstance(scenes, list):
        return repaired, [], issues

    applied: list[AppliedPronunciationTextRepair] = []
    skipped: list[PronunciationIssue] = []
    used: set[tuple[int, str]] = set()
    for issue in issues:
        replacement = issue.replacement_text.strip()
        if not replacement:
            skipped.append(issue)
            continue
        scene_index = find_scene_index_for_issue(scenes, issue, used=used)
        if scene_index is None:
            skipped.append(issue)
            continue
        scene = scenes[scene_index]
        original_line = str(scene.get("voiceover_line") or "")
        changed_line, original_word = replace_issue_word(original_line, issue, replacement)
        if changed_line == original_line:
            skipped.append(issue)
            continue
        scene["voiceover_line"] = changed_line
        used.add((int(scene.get("scene_id") or scene_index + 1), normalize_token(original_word)))
        applied.append(
            AppliedPronunciationTextRepair(
                issue=issue,
                scene_id=int(scene.get("scene_id") or scene_index + 1),
                original_word=original_word,
                replacement_text=replacement,
                original_scene_line=original_line,
                repaired_scene_line=changed_line,
            )
        )

    repaired["full_text"] = " ".join(
        str(scene.get("voiceover_line") or "").strip()
        for scene in scenes
        if isinstance(scene, dict) and str(scene.get("voiceover_line") or "").strip()
    )
    repaired["pronunciation_repair_hints"] = [repair.model_dump() for repair in applied]
    return repaired, applied, skipped


def find_scene_index_for_issue(
    scenes: list[Any],
    issue: PronunciationIssue,
    *,
    used: set[tuple[int, str]],
) -> int | None:
    needles = [normalize_token(issue.heard_word), normalize_token(issue.expected_word)]
    needles = [needle for needle in needles if needle]
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        scene_id = int(scene.get("scene_id") or index + 1)
        if issue.scene_id is not None and scene_id != issue.scene_id:
            continue
        line = str(scene.get("voiceover_line") or "")
        for word in re.finditer(r"\S+", line):
            normalized = normalize_token(word.group(0))
            if normalized in needles and (scene_id, normalized) not in used:
                return index
    return None


def replace_issue_word(
    line: str,
    issue: PronunciationIssue,
    replacement: str,
) -> tuple[str, str]:
    needles = [normalize_token(issue.heard_word), normalize_token(issue.expected_word)]
    needles = [needle for needle in needles if needle]
    for match in re.finditer(r"\S+", line):
        original = match.group(0)
        if normalize_token(original) not in needles:
            continue
        replacement = tts_replacement_for_issue(issue=issue, original_word=original, fallback=replacement)
        leading = re.match(r"^\W*", original, flags=re.UNICODE).group(0)
        trailing = re.search(r"\W*$", original, flags=re.UNICODE).group(0)
        repaired_word = f"{leading}{replacement}{trailing}"
        return line[: match.start()] + repaired_word + line[match.end() :], original
    return line, ""


def tts_replacement_for_issue(
    *,
    issue: PronunciationIssue,
    original_word: str,
    fallback: str,
) -> str:
    """Normalize Gemini-selected anglicism fixes to TTS-friendly Latin spelling."""
    core = normalize_token(original_word)
    pilates_suffixes = {
        "пилатес": "",
        "пилатеса": "а",
        "пилатесу": "у",
        "пилатесом": "ом",
        "пилатесе": "е",
    }
    if core in pilates_suffixes:
        suffix = pilates_suffixes[core]
        return "pilates" if not suffix else f"pilates-{suffix}"
    if core == "латте":
        return "latte"
    return fallback


async def audit_pronunciation(
    *,
    gemini: Any,
    audio_path: Path,
    scene_lines: dict[str, Any],
    model: str,
) -> PronunciationAudit:
    return await gemini.generate_structured_multimodal(
        prompt=AUDIT_PROMPT.format(scene_transcript=scene_transcript_json(scene_lines)),
        image_paths=[audio_path],
        response_model=PronunciationAudit,
        model=model,
    )


async def verify_pronunciation(
    *,
    gemini: Any,
    audio_path: Path,
    scene_lines: dict[str, Any],
    model: str,
) -> PronunciationVerification:
    return await gemini.generate_structured_multimodal(
        prompt=VERIFY_PROMPT.format(scene_transcript=scene_transcript_json(scene_lines)),
        image_paths=[audio_path],
        response_model=PronunciationVerification,
        model=model,
    )


def locate_pronunciation_issues(
    issues: list[PronunciationIssue],
    *,
    scene_lines: dict[str, Any],
    alignment: dict[str, Any],
) -> tuple[list[LocatedIssue], list[PronunciationIssue]]:
    word_spans = word_spans_from_alignment(
        str(scene_lines.get("full_text") or alignment.get("source_voiceover") or ""),
        alignment,
        scene_spans=scene_spans_from_scene_lines(scene_lines),
    )
    located: list[LocatedIssue] = []
    skipped: list[PronunciationIssue] = []
    used_spans: set[tuple[int, int]] = set()
    for issue in issues:
        word = find_issue_word_span(issue, word_spans)
        if word is None or (word.start_char, word.end_char) in used_spans:
            skipped.append(issue)
            continue
        used_spans.add((word.start_char, word.end_char))
        located.append(LocatedIssue(issue=issue, word=word))
    located.sort(key=lambda item: item.word.start_sec)
    return located, skipped


def scene_spans_from_scene_lines(scene_lines: dict[str, Any]) -> list[SceneSpan]:
    spans: list[SceneSpan] = []
    cursor = 0
    for index, scene in enumerate(scene_lines.get("scenes") or [], start=1):
        if not isinstance(scene, dict):
            continue
        text = str(scene.get("voiceover_line") or "").strip()
        if not text:
            continue
        scene_id = int(scene.get("scene_id") or index)
        start = cursor
        end = start + len(text)
        spans.append(SceneSpan(scene_id=scene_id, text=text, start_char=start, end_char=end))
        cursor = end + 1
    return spans


def word_spans_from_alignment(
    full_text: str,
    alignment: dict[str, Any],
    *,
    scene_spans: list[SceneSpan] | None = None,
) -> list[WordSpan]:
    raw_alignment = alignment.get("alignment") if isinstance(alignment.get("alignment"), dict) else alignment
    characters = [str(char) for char in raw_alignment.get("characters") or []]
    starts = [float(value) for value in raw_alignment.get("character_start_times_seconds") or []]
    ends = [float(value) for value in raw_alignment.get("character_end_times_seconds") or []]
    if not full_text:
        full_text = "".join(characters)
    if not full_text or len(starts) < len(full_text) or len(ends) < len(full_text):
        return []

    spans = scene_spans or []
    words: list[WordSpan] = []
    for match in re.finditer(r"\S+", full_text):
        start_char = match.start()
        end_char = match.end()
        if end_char > len(ends):
            continue
        scene_id = scene_id_for_char(start_char, spans)
        words.append(
            WordSpan(
                text=match.group(0),
                start_char=start_char,
                end_char=end_char,
                start_sec=starts[start_char],
                end_sec=ends[end_char - 1],
                scene_id=scene_id,
            )
        )
    return words


def find_issue_word_span(issue: PronunciationIssue, word_spans: list[WordSpan]) -> WordSpan | None:
    needles = [
        normalize_token(issue.heard_word),
        normalize_token(issue.expected_word),
    ]
    needles = [needle for needle in needles if needle]
    if not needles:
        return None

    scene_matches = [
        word
        for word in word_spans
        if (issue.scene_id is None or word.scene_id == issue.scene_id)
        and normalize_token(word.text) in needles
    ]
    if scene_matches:
        return scene_matches[0]

    fuzzy = [
        word
        for word in word_spans
        if (issue.scene_id is None or word.scene_id == issue.scene_id)
        and any(needle in normalize_token(word.text) or normalize_token(word.text) in needle for needle in needles)
    ]
    if fuzzy:
        return fuzzy[0]
    return None


def scene_id_for_char(char_index: int, scene_spans: list[SceneSpan]) -> int | None:
    for scene in scene_spans:
        if scene.start_char <= char_index < scene.end_char:
            return scene.scene_id
    return None


def fit_audio_to_duration(source_path: Path, output_path: Path, *, target_duration_sec: float) -> None:
    ffmpeg = require_binary("ffmpeg")
    duration = probe_duration_sec(source_path)
    tempo = duration / target_duration_sec if duration > 0 and target_duration_sec > 0 else 1.0
    filters = atempo_filters(tempo)
    filters.append(f"apad=whole_dur={target_duration_sec:.4f}")
    filters.append(f"atrim=0:{target_duration_sec:.4f}")
    filters.append("asetpts=N/SR/TB")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-af",
            ",".join(filters),
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output_path),
        ],
        check=True,
    )


def splice_audio_replacements(
    *,
    original_audio_path: Path,
    replacements: list[AppliedPronunciationRepair],
    output_path: Path,
    work_dir: Path,
) -> None:
    if not replacements:
        output_path.write_bytes(original_audio_path.read_bytes())
        return
    ffmpeg = require_binary("ffmpeg")
    work_dir.mkdir(parents=True, exist_ok=True)
    total_duration = probe_duration_sec(original_audio_path)
    cursor = 0.0
    segment_paths: list[Path] = []
    for index, replacement in enumerate(sorted(replacements, key=lambda item: item.source_start_sec), start=1):
        start = max(cursor, replacement.source_start_sec)
        end = min(total_duration, max(start, replacement.source_end_sec))
        if start > cursor + 0.005:
            original_segment = work_dir / f"segment-{index:02d}-before.mp3"
            extract_audio_segment(original_audio_path, original_segment, start_sec=cursor, end_sec=start)
            segment_paths.append(original_segment)
        segment_paths.append(Path(replacement.fitted_audio_path))
        cursor = end
    if cursor < total_duration - 0.005:
        tail = work_dir / "segment-tail.mp3"
        extract_audio_segment(original_audio_path, tail, start_sec=cursor, end_sec=total_duration)
        segment_paths.append(tail)

    concat_file = work_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in segment_paths) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output_path),
        ],
        check=True,
    )


def extract_audio_segment(source_path: Path, output_path: Path, *, start_sec: float, end_sec: float) -> None:
    ffmpeg = require_binary("ffmpeg")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            f"{max(0.0, start_sec):.4f}",
            "-to",
            f"{max(0.0, end_sec):.4f}",
            "-i",
            str(source_path),
            "-vn",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output_path),
        ],
        check=True,
    )


def probe_duration_sec(path: Path) -> float:
    ffprobe = require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip() or "0")


def atempo_filters(tempo: float) -> list[str]:
    tempo = max(0.25, min(4.0, tempo))
    filters: list[str] = []
    while tempo > 2.0:
        filters.append("atempo=2.0")
        tempo /= 2.0
    while tempo < 0.5:
        filters.append("atempo=0.5")
        tempo /= 0.5
    filters.append(f"atempo={tempo:.5f}")
    return filters


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if path:
        return path
    raise PronunciationRepairError(f"Required binary not found: {name}")


def scene_transcript_json(scene_lines: dict[str, Any]) -> str:
    scenes = []
    for scene in scene_lines.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        scenes.append(
            {
                "scene_id": scene.get("scene_id"),
                "voiceover_line": scene.get("voiceover_line"),
            }
        )
    return json.dumps({"full_text": scene_lines.get("full_text"), "scenes": scenes}, ensure_ascii=False, indent=2)


def normalize_token(value: str) -> str:
    value = value.lower().replace("ё", "е")
    value = re.sub(r"[^0-9a-zа-я]+", "", value, flags=re.IGNORECASE)
    return value


def safe_filename(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return safe[:80] or "pronunciation-repair"
