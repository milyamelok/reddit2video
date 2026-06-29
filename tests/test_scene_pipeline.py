from __future__ import annotations

import asyncio

from reddit2video.models import ScenePipelineNodeRequest, VoiceoverScriptBatch, VoiceoverScriptItem
from reddit2video.nodes.scene_pipeline import ScenePipelineNode, align_fragments_to_character_alignment
from reddit2video.scene_schema import (
    BoundaryStrength,
    FragmentTag,
    LabeledFragment,
    SceneGroup,
    ScenePlanOutput,
    SceneTag,
    SceneTextRow,
    SemanticFragmentOutput,
    TemplateHint,
    TimedFragment,
    VisualDensity,
    RowRole,
)
from reddit2video.scene_validator import validate_scene_plan


def test_semantic_model_ignores_extra_fields():
    parsed = LabeledFragment.model_validate(
        {
            "fragment_id": 1,
            "text": "Лишние поля не ломают схему.",
            "tag": "hook",
            "boundary_after": "forced",
            "is_anchor": True,
            "vendor_specific_note": "ignored",
        }
    )
    assert parsed.fragment_id == 1
    assert not hasattr(parsed, "vendor_specific_note")


def test_fragment_alignment_maps_exact_text_to_character_times():
    text = "Привет мир. Еще тест."
    fragments = [
        LabeledFragment(
            fragment_id=1,
            text="Привет мир.",
            tag=FragmentTag.HOOK,
            boundary_after=BoundaryStrength.FORCED,
            is_anchor=True,
        ),
        LabeledFragment(
            fragment_id=2,
            text=" Еще тест.",
            tag=FragmentTag.CONTEXT,
            boundary_after=BoundaryStrength.PREFERRED,
            is_anchor=False,
        ),
    ]
    alignment = {
        "characters": list(text),
        "character_start_times_seconds": [index * 0.1 for index in range(len(text))],
        "character_end_times_seconds": [(index + 1) * 0.1 for index in range(len(text))],
    }
    timed, warnings = align_fragments_to_character_alignment(fragments, text, alignment)
    assert warnings == []
    assert timed[0].start_sec == 0
    assert timed[0].end_sec == 1.1
    assert timed[1].start_sec == 1.1
    assert timed[1].end_sec == 2.1


def test_scene_validator_catches_skipped_fragments():
    timed = [
        TimedFragment(
            fragment_id=1,
            text="A",
            tag=FragmentTag.HOOK,
            boundary_after=BoundaryStrength.FORCED,
            start_sec=0,
            end_sec=1,
            duration_sec=1,
        ),
        TimedFragment(
            fragment_id=2,
            text="B",
            tag=FragmentTag.CONTEXT,
            boundary_after=BoundaryStrength.PREFERRED,
            start_sec=1,
            end_sec=2,
            duration_sec=1,
        ),
    ]
    plan = ScenePlanOutput(
        target_scene_count=1,
        scenes=[
            SceneGroup(
                scene_id=1,
                fragment_ids=[1],
                scene_tag=SceneTag.COLD_HOOK,
                visual_density=VisualDensity.LOW,
                template_hint=TemplateHint.HERO_TEXT,
                attention_job="Hook.",
                screen_rows=[SceneTextRow(text="A", role=RowRole.HERO, source_fragment_ids=[1])],
                exit_energy="Cut.",
            )
        ],
    )
    errors, _, _ = validate_scene_plan(plan, timed, min_scenes=1, max_scenes=2)
    assert any("every fragment exactly once" in error for error in errors)


def test_scene_pipeline_cache_hit_skips_clients(tmp_path):
    item = VoiceoverScriptItem(
        post_id="post1",
        subreddit="test",
        title="Test",
        script={"script": {"voiceover_full_text": "Привет мир."}},
        validator={"verdict": "pass"},
        attempts=1,
        from_cache=False,
        cache_path="",
    )
    cache_path = tmp_path / "scene_pipeline" / "period" / "post1.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        """
        {
          "post_id": "post1",
          "subreddit": "test",
          "title": "Test",
          "status": "pass",
          "audio_path": "a.mp3",
          "alignment": {},
          "semantic_fragments": {},
          "timed_fragments": [],
          "scene_plan": {},
          "timed_scenes": [],
          "validator_errors": [],
          "validator_warnings": [],
          "attempts": 0,
          "from_cache": false,
          "cache_path": ""
        }
        """,
        encoding="utf-8",
    )

    class FailingGemini:
        async def generate_structured(self, **kwargs):
            raise AssertionError("Gemini should not be called on cache hit")

    class FailingElevenLabs:
        async def text_to_speech_with_timestamps(self, **kwargs):
            raise AssertionError("ElevenLabs should not be called on cache hit")

    async def run():
        result = await ScenePipelineNode(gemini=FailingGemini(), elevenlabs=FailingElevenLabs()).run(
            ScenePipelineNodeRequest(
                voiceover_batch=VoiceoverScriptBatch(items=[item], fetched_at="now"),
                period_key="period",
                cache_dir=str(tmp_path),
            )
        )
        assert result.items[0].from_cache is True
        assert result.metadata["cache_hits"] == 1

    asyncio.run(run())


def test_failed_scene_validation_triggers_one_repair_call(tmp_path):
    words = [f"w{i:02d}" for i in range(1, 19)]
    text = " ".join(words)
    item = VoiceoverScriptItem(
        post_id="post2",
        subreddit="test",
        title="Repair Test",
        script={"script": {"voiceover_full_text": text}},
        validator={"verdict": "pass"},
        attempts=1,
        from_cache=False,
        cache_path="",
    )

    def scene(scene_id, fragment_ids, tag=SceneTag.PUNCH):
        return SceneGroup(
            scene_id=scene_id,
            fragment_ids=fragment_ids,
            scene_tag=tag,
            visual_density=VisualDensity.LOW,
            template_hint=TemplateHint.ONE_WORD_PUNCH,
            attention_job="Keep momentum.",
            screen_rows=[SceneTextRow(text=f"S{scene_id}", role=RowRole.HERO, source_fragment_ids=fragment_ids)],
            exit_energy="Cut.",
        )

    class RepairGemini:
        def __init__(self):
            self.scene_calls = 0

        async def generate_structured(self, *, response_model, **kwargs):
            if response_model is SemanticFragmentOutput:
                fragments = []
                for index, word in enumerate(words, start=1):
                    suffix = " " if index < len(words) else ""
                    fragments.append(
                        LabeledFragment(
                            fragment_id=index,
                            text=f"{word}{suffix}",
                            tag=FragmentTag.PUNCH,
                            boundary_after=BoundaryStrength.FORCED,
                            is_anchor=index == 1,
                        )
                    )
                return SemanticFragmentOutput(original_voiceover=text, fragments=fragments)

            self.scene_calls += 1
            if self.scene_calls == 1:
                return ScenePlanOutput(target_scene_count=18, scenes=[scene(1, [1])])
            return ScenePlanOutput(
                target_scene_count=18,
                scenes=[scene(index, [index]) for index in range(1, 19)],
            )

    class FakeElevenLabs:
        async def text_to_speech_with_timestamps(self, *, text, voice_id, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake mp3")
            return {
                "audio_path": str(output_path),
                "alignment": {
                    "characters": list(text),
                    "character_start_times_seconds": [index * 0.2 for index in range(len(text))],
                    "character_end_times_seconds": [(index + 1) * 0.2 for index in range(len(text))],
                },
            }

    async def run():
        gemini = RepairGemini()
        result = await ScenePipelineNode(gemini=gemini, elevenlabs=FakeElevenLabs()).run(
            ScenePipelineNodeRequest(
                voiceover_batch=VoiceoverScriptBatch(items=[item], fetched_at="now"),
                period_key="period",
                cache_dir=str(tmp_path / "cache"),
                audio_dir=str(tmp_path / "audio"),
                target_scene_count=18,
                repair_retries=1,
                use_cache=False,
            )
        )
        assert gemini.scene_calls == 2
        assert result.items[0].status == "pass"
        assert result.items[0].validator_errors == []
        assert result.items[0].attempts == 2

    asyncio.run(run())


def test_scene_exception_preserves_partial_audio_and_semantic(tmp_path):
    text = "alpha beta"
    item = VoiceoverScriptItem(
        post_id="post3",
        subreddit="test",
        title="Partial Test",
        script={"script": {"voiceover_full_text": text}},
        validator={"verdict": "pass"},
        attempts=1,
        from_cache=False,
        cache_path="",
    )

    class SceneFailGemini:
        async def generate_structured(self, *, response_model, **kwargs):
            if response_model is SemanticFragmentOutput:
                return SemanticFragmentOutput(
                    original_voiceover=text,
                    fragments=[
                        LabeledFragment(
                            fragment_id=1,
                            text="alpha ",
                            tag=FragmentTag.HOOK,
                            boundary_after=BoundaryStrength.PREFERRED,
                        ),
                        LabeledFragment(
                            fragment_id=2,
                            text="beta",
                            tag=FragmentTag.PUNCH,
                            boundary_after=BoundaryStrength.FORCED,
                        ),
                    ],
                )
            raise RuntimeError("scene service down")

    class FakeElevenLabs:
        async def text_to_speech_with_timestamps(self, *, text, voice_id, output_path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"fake mp3")
            return {
                "alignment": {
                    "characters": list(text),
                    "character_start_times_seconds": [index * 0.2 for index in range(len(text))],
                    "character_end_times_seconds": [(index + 1) * 0.2 for index in range(len(text))],
                },
                "audio_path": str(output_path),
            }

    async def run():
        result = await ScenePipelineNode(gemini=SceneFailGemini(), elevenlabs=FakeElevenLabs()).run(
            ScenePipelineNodeRequest(
                voiceover_batch=VoiceoverScriptBatch(items=[item], fetched_at="now"),
                period_key="period",
                cache_dir=str(tmp_path / "cache"),
                audio_dir=str(tmp_path / "audio"),
                use_cache=False,
            )
        )
        output = result.items[0]
        assert output.status == "fail"
        assert output.audio_path.endswith("post3.mp3")
        assert output.semantic_fragments["fragments"]
        assert len(output.timed_fragments) == 2
        assert output.metadata["failed_stage"] == "scene_plan"

    asyncio.run(run())
