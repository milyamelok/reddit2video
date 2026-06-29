from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reddit2video.elevenlabs import ElevenLabsClient
from reddit2video.gemini import GeminiClient
from reddit2video.models import (
    JsonObject,
    NodeSpec,
    ScenePipelineBatch,
    ScenePipelineItem,
    ScenePipelineNodeRequest,
    VoiceoverScriptItem,
    to_jsonable,
)
from reddit2video.nodes.base import AsyncBaseNode
from reddit2video.scene_schema import LabeledFragment, ScenePlanOutput, SemanticFragmentOutput, TimedFragment
from reddit2video.scene_validator import validate_scene_plan


SEMANTIC_SLICER_PROMPT = """You are a semantic segmentation engine for short-form voiceover scripts.

Your task:
Split the voiceover into small meaning fragments and assign a primary tag to each fragment.

Important:
You are NOT creating scenes yet.
You are NOT assigning visual templates.
You are NOT planning images, GIFs, or video.
You are NOT creating timings.
You are only preparing a clean semantic skeleton for the next step.

INPUT:
- VOICEOVER_TEXT
- TARGET_DURATION_SEC

CORE RULES:
1. Preserve the original text. Every fragment.text must be an exact contiguous substring from VOICEOVER_TEXT.
2. Preserve order. fragment_id starts at 1 and increases sequentially.
3. Split by meaning, not by equal length.
4. If one sentence contains several attention moves, split it.
5. Do not over-split stable phrases.
6. Most fragments should be 3-12 words; punch fragments can be 1-3 words.
7. Assign exactly one primary tag.
8. Use boundary_after: none, weak, preferred, forced.
9. is_anchor=true only for structurally important fragments.
10. Fragments together should cover the whole voiceover in order. You may normalize whitespace slightly, but do not change words.
11. Do not include hidden chain-of-thought. segmentation_notes should contain only short production notes.

Return JSON only matching the SemanticFragmentOutput schema.
"""


SCENE_GROUPER_PROMPT = """You are a short-form scene planning engine for 9:16 voiceover videos.

Your task:
Group timed semantic voiceover fragments into visual scenes and plan what each scene contains:
- partial subtitles / hero words,
- images,
- GIFs,
- videos,
- stickers/icons,
- fake UI,
- simple diagrams,
- collage elements.

Important:
You are NOT rewriting the voiceover.
You are NOT creating a new script.
You are NOT generating HTML.
You are NOT inventing timings.
You are choosing cut points between fragments and describing the visual plan.

OUTPUT:
Return valid JSON matching the ScenePlanOutput Pydantic model.

CORE OBJECTIVE:
Create 18-25 scenes for a 60-second video. Each scene should be a small reason not to swipe.

GROUPING RULES:
1. Preserve order.
2. Use every fragment exactly once.
3. fragment_ids inside each scene must be contiguous.
4. screen_rows may compress the meaning for visual display, but must not add new factual content.
5. Do not output scene timings.
6. Use duration guidance: 1.2-2.0s only for punch/hook/one-word; 2.1-3.3s default; 3.4-5.0s for checklist/mechanism/split/metaphor/save/debate; over 5.0s should usually split.
7. Target TARGET_SCENE_COUNT, but if exact target damages quality, use nearest good count inside 18-25.
8. Prefer scene boundaries around hook, inversion, contrast, twist, mechanism, label, rule, save/share object, final debate.
9. Avoid three scenes in a row with same template_hint and four scenes with same visual_density.
10. First 3 scenes must be clear and not HIGH density.
11. Last 3-5 scenes should contain save/share/debate/punch energy if source supports it.

SCREEN TEXT RULES:
Rows are not full subtitles. Use 1-4 rows per scene. Most rows should be 1-5 words.

MEDIA SLOT RULES:
Media is not decoration. Every slot must have a job.
Allowed media kinds: image, gif, video, icon, sticker, fake_ui, diagram, text_shape.
Do not download assets. Only write source_strategy, search queries, visual_prompt, avoid, crop_hint, motion_hint.
For this project prefer a girly wellness/biohacking blogger style: pink and sky-blue accents, cream/pastel base, cute meme energy, fake UI, stamps, stickers, and only very simple diagrams.

Return JSON only.
"""


SCENE_REPAIR_PROMPT = """You are repairing a failed scene/media plan.

You receive:
- original scene planning prompt,
- timed fragments,
- previous scene plan,
- deterministic validator errors and warnings.

Repair only the grouping/media plan. Do not rewrite voiceover, do not invent timings, and use every fragment exactly once in order.
Return valid JSON matching the ScenePlanOutput schema. JSON only.
"""


class ScenePipelineNode(AsyncBaseNode[ScenePipelineNodeRequest, ScenePipelineBatch]):
    spec = NodeSpec(
        step="step-4",
        name="scene_pipeline",
        description="Generate ElevenLabs audio/timings and Gemini scene/media-slot plans.",
        mocked=False,
    )

    def __init__(
        self,
        *,
        gemini: GeminiClient | None = None,
        elevenlabs: ElevenLabsClient | None = None,
    ) -> None:
        self.gemini = gemini or GeminiClient.from_env(model="gemini-3.1-pro-preview", vertex=True)
        self.elevenlabs = elevenlabs or ElevenLabsClient.from_env()

    async def run(self, node_input: ScenePipelineNodeRequest) -> ScenePipelineBatch:
        period_key = node_input.period_key or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        semaphore = asyncio.Semaphore(max(1, node_input.concurrency))

        async def process(item: VoiceoverScriptItem) -> ScenePipelineItem:
            async with semaphore:
                return await self._process_item(item, node_input, period_key)

        items = await asyncio.gather(*(process(item) for item in node_input.voiceover_batch.items))
        return ScenePipelineBatch(
            items=list(items),
            fetched_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "node": self.spec.name,
                "period_key": period_key,
                "use_cache": node_input.use_cache,
                "items": len(items),
                "cache_hits": sum(1 for item in items if item.from_cache),
                "passes": sum(1 for item in items if item.status == "pass"),
                "fails": sum(1 for item in items if item.status == "fail"),
                "voice_id": node_input.voice_id,
                "voice_name": node_input.voice_name,
                "target_scene_count": node_input.target_scene_count,
            },
        )

    async def _process_item(
        self,
        item: VoiceoverScriptItem,
        request: ScenePipelineNodeRequest,
        period_key: str,
    ) -> ScenePipelineItem:
        cache_path = self._cache_path(request.cache_dir, period_key, item.post_id)
        if request.use_cache and cache_path.exists():
            return _item_from_cache(cache_path)

        try:
            result = await self._build_item(item, request, period_key, cache_path)
        except Exception as exc:
            result = ScenePipelineItem(
                post_id=item.post_id,
                subreddit=item.subreddit,
                title=item.title,
                status="fail",
                audio_path="",
                alignment={},
                semantic_fragments={},
                timed_fragments=[],
                scene_plan=None,
                timed_scenes=[],
                validator_errors=[f"{type(exc).__name__}: {exc}"],
                validator_warnings=[],
                attempts=0,
                from_cache=False,
                cache_path=str(cache_path),
                metadata={"error": str(exc)},
            )

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    async def _build_item(
        self,
        item: VoiceoverScriptItem,
        request: ScenePipelineNodeRequest,
        period_key: str,
        cache_path: Path,
    ) -> ScenePipelineItem:
        voiceover_text = _voiceover_text(item)
        audio_path = Path(request.audio_dir) / period_key / f"{item.post_id}.mp3"
        alignment_path = audio_path.with_suffix(".alignment.json")
        semantic_path = self._semantic_cache_path(request.cache_dir, period_key, item.post_id)

        audio_cache_hit = False
        if request.use_cache and audio_path.exists() and alignment_path.exists():
            alignment_payload = json.loads(alignment_path.read_text(encoding="utf-8"))
            audio_cache_hit = True
        else:
            alignment_payload = await self.elevenlabs.text_to_speech_with_timestamps(
                text=voiceover_text,
                voice_id=request.voice_id,
                output_path=audio_path,
            )
            alignment_path.parent.mkdir(parents=True, exist_ok=True)
            alignment_path.write_text(json.dumps(alignment_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        semantic_cache_hit = False
        if request.use_cache and semantic_path.exists():
            semantic = SemanticFragmentOutput.model_validate_json(semantic_path.read_text(encoding="utf-8"))
            semantic_cache_hit = True
        else:
            try:
                semantic = await self.gemini.generate_structured(
                    prompt=_build_semantic_prompt(voiceover_text, request.target_duration_sec),
                    response_model=SemanticFragmentOutput,
                )
            except Exception as exc:
                return self._failure_item(
                    item=item,
                    request=request,
                    cache_path=cache_path,
                    audio_path=audio_path,
                    alignment_path=alignment_path,
                    semantic_path=semantic_path,
                    alignment_payload=alignment_payload,
                    semantic=None,
                    timed_fragments=[],
                    scene_plan=None,
                    timed_scenes=[],
                    errors=[f"{type(exc).__name__}: {exc}"],
                    warnings=[],
                    attempts=0,
                    stage="semantic",
                    audio_cache_hit=audio_cache_hit,
                    semantic_cache_hit=semantic_cache_hit,
                )
            semantic_path.parent.mkdir(parents=True, exist_ok=True)
            semantic_path.write_text(semantic.model_dump_json(by_alias=True, indent=2), encoding="utf-8")

        timed_fragments, timing_warnings = align_fragments_to_character_alignment(
            semantic.fragments,
            voiceover_text,
            alignment_payload.get("alignment") or alignment_payload.get("normalized_alignment") or {},
        )

        attempts = 1
        scene_prompt = _build_scene_prompt(
            timed_fragments=timed_fragments,
            target_scene_count=request.target_scene_count,
            target_duration_sec=request.target_duration_sec,
            style_library_hint=request.style_library_hint,
            style_pack_path=request.style_pack_path,
        )
        try:
            scene_plan = await self.gemini.generate_structured(
                prompt=scene_prompt,
                response_model=ScenePlanOutput,
            )
        except Exception as exc:
            return self._failure_item(
                item=item,
                request=request,
                cache_path=cache_path,
                audio_path=audio_path,
                alignment_path=alignment_path,
                semantic_path=semantic_path,
                alignment_payload=alignment_payload,
                semantic=semantic,
                timed_fragments=timed_fragments,
                scene_plan=None,
                timed_scenes=[],
                errors=[f"{type(exc).__name__}: {exc}"],
                warnings=timing_warnings,
                attempts=attempts,
                stage="scene_plan",
                audio_cache_hit=audio_cache_hit,
                semantic_cache_hit=semantic_cache_hit,
            )
        errors, warnings, timed_scenes = validate_scene_plan(scene_plan, timed_fragments)
        warnings.extend(timing_warnings)

        for _ in range(max(0, request.repair_retries)):
            if not errors:
                break
            attempts += 1
            try:
                scene_plan = await self.gemini.generate_structured(
                    prompt=_build_repair_prompt(scene_prompt, timed_fragments, scene_plan, errors, warnings),
                    response_model=ScenePlanOutput,
                )
            except Exception as exc:
                return self._failure_item(
                    item=item,
                    request=request,
                    cache_path=cache_path,
                    audio_path=audio_path,
                    alignment_path=alignment_path,
                    semantic_path=semantic_path,
                    alignment_payload=alignment_payload,
                    semantic=semantic,
                    timed_fragments=timed_fragments,
                    scene_plan=scene_plan,
                    timed_scenes=timed_scenes,
                    errors=[*errors, f"Repair {attempts - 1} failed: {type(exc).__name__}: {exc}"],
                    warnings=warnings,
                    attempts=attempts,
                    stage="scene_repair",
                    audio_cache_hit=audio_cache_hit,
                    semantic_cache_hit=semantic_cache_hit,
                )
            errors, warnings, timed_scenes = validate_scene_plan(scene_plan, timed_fragments)
            warnings.extend(timing_warnings)

        return ScenePipelineItem(
            post_id=item.post_id,
            subreddit=item.subreddit,
            title=item.title,
            status="pass" if not errors else "fail",
            audio_path=str(audio_path),
            alignment=alignment_payload,
            semantic_fragments=semantic.model_dump(mode="json", by_alias=True),
            timed_fragments=[fragment.model_dump(mode="json", by_alias=True) for fragment in timed_fragments],
            scene_plan=scene_plan.model_dump(mode="json", by_alias=True),
            timed_scenes=[timed_scene.__dict__ for timed_scene in timed_scenes],
            validator_errors=errors,
            validator_warnings=warnings,
            attempts=attempts,
            from_cache=False,
            cache_path=str(cache_path),
            metadata={
                "failed_stage": "validator" if errors else None,
                "validation_passed": not errors,
                "audio_cache_hit": audio_cache_hit,
                "semantic_cache_hit": semantic_cache_hit,
                "alignment_path": str(alignment_path),
                "semantic_cache_path": str(semantic_path),
                "style_pack_path": request.style_pack_path,
            },
        )

    def _cache_path(self, cache_dir: str, period_key: str, post_id: str) -> Path:
        return Path(cache_dir) / self.spec.name / period_key / f"{post_id}.json"

    def _semantic_cache_path(self, cache_dir: str, period_key: str, post_id: str) -> Path:
        return Path(cache_dir) / self.spec.name / period_key / f"{post_id}.semantic.json"

    def _failure_item(
        self,
        *,
        item: VoiceoverScriptItem,
        request: ScenePipelineNodeRequest,
        cache_path: Path,
        audio_path: Path,
        alignment_path: Path,
        semantic_path: Path,
        alignment_payload: JsonObject,
        semantic: SemanticFragmentOutput | None,
        timed_fragments: list[TimedFragment],
        scene_plan: ScenePlanOutput | None,
        timed_scenes: list[Any],
        errors: list[str],
        warnings: list[str],
        attempts: int,
        stage: str,
        audio_cache_hit: bool,
        semantic_cache_hit: bool,
    ) -> ScenePipelineItem:
        return ScenePipelineItem(
            post_id=item.post_id,
            subreddit=item.subreddit,
            title=item.title,
            status="fail",
            audio_path=str(audio_path) if audio_path.exists() else "",
            alignment=alignment_payload,
            semantic_fragments=semantic.model_dump(mode="json", by_alias=True) if semantic else {},
            timed_fragments=[fragment.model_dump(mode="json", by_alias=True) for fragment in timed_fragments],
            scene_plan=scene_plan.model_dump(mode="json", by_alias=True) if scene_plan else None,
            timed_scenes=[timed_scene.__dict__ for timed_scene in timed_scenes],
            validator_errors=errors,
            validator_warnings=warnings,
            attempts=attempts,
            from_cache=False,
            cache_path=str(cache_path),
            metadata={
                "failed_stage": stage,
                "audio_cache_hit": audio_cache_hit,
                "semantic_cache_hit": semantic_cache_hit,
                "alignment_path": str(alignment_path),
                "semantic_cache_path": str(semantic_path),
                "style_pack_path": request.style_pack_path,
            },
        )


def align_fragments_to_character_alignment(
    fragments: list[LabeledFragment],
    voiceover_text: str,
    alignment: dict[str, Any],
) -> tuple[list[TimedFragment], list[str]]:
    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    alignment_text = "".join(str(character) for character in characters)
    duration = _last_number(ends) or _last_number(starts) or 0.0
    warnings: list[str] = []
    timed: list[TimedFragment] = []
    cursor = 0

    for fragment in fragments:
        start_index = voiceover_text.find(fragment.text, cursor)
        source_text = voiceover_text
        if start_index < 0:
            start_index = alignment_text.find(fragment.text, cursor)
            source_text = alignment_text
        if start_index < 0:
            warnings.append(f"Could not find exact fragment text for fragment_id={fragment.fragment_id}; used proportional timing.")
            start_index = cursor
            end_index = min(len(voiceover_text), start_index + len(fragment.text))
            cursor = end_index
        else:
            end_index = start_index + len(fragment.text)
            cursor = end_index

        start_sec = _time_at(starts, start_index, forward=True)
        end_sec = _time_at(ends, end_index - 1, forward=False)
        if start_sec is None or end_sec is None:
            text_len = max(1, len(source_text))
            start_sec = duration * (start_index / text_len)
            end_sec = duration * (end_index / text_len)
            warnings.append(f"Missing character timestamps for fragment_id={fragment.fragment_id}; used proportional fallback.")
        if end_sec <= start_sec:
            end_sec = start_sec + 0.05
        timed.append(
            TimedFragment(
                fragment_id=fragment.fragment_id,
                text=fragment.text,
                tag=fragment.tag,
                boundary_after=fragment.boundary_after,
                is_anchor=fragment.is_anchor,
                start_sec=round(float(start_sec), 3),
                end_sec=round(float(end_sec), 3),
                duration_sec=round(float(end_sec - start_sec), 3),
                asr_confidence=1.0 if not warnings else 0.85,
            )
        )

    return timed, warnings


def _time_at(values: list[Any], index: int, *, forward: bool) -> float | None:
    if not values:
        return None
    index = max(0, min(index, len(values) - 1))
    step = 1 if forward else -1
    current = index
    while 0 <= current < len(values):
        value = values[current]
        if isinstance(value, (int, float)):
            return float(value)
        current += step
    return None


def _last_number(values: list[Any]) -> float | None:
    for value in reversed(values):
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _voiceover_text(item: VoiceoverScriptItem) -> str:
    try:
        return str(item.script["script"]["voiceover_full_text"]).strip()
    except KeyError as exc:
        raise ValueError(f"Voiceover item {item.post_id} has no script.voiceover_full_text") from exc


def _build_semantic_prompt(voiceover_text: str, target_duration_sec: int) -> str:
    return "\n\n".join(
        [
            SEMANTIC_SLICER_PROMPT,
            f"TARGET_DURATION_SEC: {target_duration_sec}",
            "VOICEOVER_TEXT:",
            voiceover_text,
        ]
    )


def _build_scene_prompt(
    *,
    timed_fragments: list[TimedFragment],
    target_scene_count: int,
    target_duration_sec: int,
    style_library_hint: str,
    style_pack_path: str,
) -> str:
    return "\n\n".join(
        [
            SCENE_GROUPER_PROMPT,
            f"TARGET_DURATION_SEC: {target_duration_sec}",
            f"TARGET_SCENE_COUNT: {target_scene_count}",
            f"STYLE_LIBRARY_HINT: {style_library_hint}",
            f"STYLE_PACK_PATH_REFERENCE: {style_pack_path}",
            "TIMED_FRAGMENTS:",
            json.dumps([fragment.model_dump(mode="json", by_alias=True) for fragment in timed_fragments], ensure_ascii=False, indent=2),
        ]
    )


def _build_repair_prompt(
    scene_prompt: str,
    timed_fragments: list[TimedFragment],
    previous_plan: ScenePlanOutput,
    errors: list[str],
    warnings: list[str],
) -> str:
    return "\n\n".join(
        [
            SCENE_REPAIR_PROMPT,
            "ORIGINAL_SCENE_PROMPT:",
            scene_prompt,
            "TIMED_FRAGMENTS:",
            json.dumps([fragment.model_dump(mode="json", by_alias=True) for fragment in timed_fragments], ensure_ascii=False, indent=2),
            "PREVIOUS_SCENE_PLAN:",
            previous_plan.model_dump_json(by_alias=True, indent=2),
            "VALIDATOR_ERRORS:",
            json.dumps(errors, ensure_ascii=False, indent=2),
            "VALIDATOR_WARNINGS:",
            json.dumps(warnings, ensure_ascii=False, indent=2),
        ]
    )


def _item_from_cache(cache_path: Path) -> ScenePipelineItem:
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    return ScenePipelineItem(
        post_id=str(payload.get("post_id", "")),
        subreddit=str(payload.get("subreddit", "")),
        title=str(payload.get("title", "")),
        status=payload.get("status") if payload.get("status") in {"pass", "fail"} else "fail",
        audio_path=str(payload.get("audio_path", "")),
        alignment=dict(payload.get("alignment", {})),
        semantic_fragments=dict(payload.get("semantic_fragments", {})),
        timed_fragments=list(payload.get("timed_fragments", [])),
        scene_plan=payload.get("scene_plan"),
        timed_scenes=list(payload.get("timed_scenes", [])),
        validator_errors=[str(error) for error in payload.get("validator_errors", [])],
        validator_warnings=[str(warning) for warning in payload.get("validator_warnings", [])],
        attempts=int(payload.get("attempts") or 0),
        from_cache=True,
        cache_path=str(cache_path),
        metadata=dict(payload.get("metadata", {})),
    )
