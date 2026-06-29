from __future__ import annotations

import asyncio

from reddit2video import pronunciation_repair as repair
from reddit2video.pronunciation_repair import (
    PronunciationAudit,
    PronunciationIssue,
    PronunciationVerification,
    build_revoiced_scene_lines,
    is_pronunciation_repair_candidate,
    locate_pronunciation_issues,
    repair_pronunciation_audio,
    scene_spans_from_scene_lines,
    word_spans_from_alignment,
)
from reddit2video.word_timing import align_words_to_character_alignment


def character_alignment(text: str) -> dict:
    return {
        "characters": list(text),
        "character_start_times_seconds": [index * 0.1 for index in range(len(text))],
        "character_end_times_seconds": [(index + 1) * 0.1 for index in range(len(text))],
    }


def test_locate_pronunciation_issue_uses_scene_alignment():
    scene_lines = {
        "full_text": "Я люблю пилатеса. Латте рядом.",
        "scenes": [
            {"scene_id": 1, "voiceover_line": "Я люблю пилатеса."},
            {"scene_id": 2, "voiceover_line": "Латте рядом."},
        ],
    }
    spans = word_spans_from_alignment(
        scene_lines["full_text"],
        character_alignment(scene_lines["full_text"]),
        scene_spans=scene_spans_from_scene_lines(scene_lines),
    )
    assert [span.text for span in spans] == ["Я", "люблю", "пилатеса.", "Латте", "рядом."]

    located, skipped = locate_pronunciation_issues(
        [
            PronunciationIssue(
                scene_id=1,
                heard_word="пилатеса",
                expected_word="pilates-а",
                replacement_text="pilates-а",
                reason="Wrong stress.",
                confidence=0.9,
            )
        ],
        scene_lines=scene_lines,
        alignment=character_alignment(scene_lines["full_text"]),
    )

    assert skipped == []
    assert len(located) == 1
    assert located[0].word.text == "пилатеса."
    assert located[0].word.scene_id == 1
    assert located[0].word.start_sec == 0.8
    assert round(located[0].word.end_sec, 3) == 1.7


def test_repair_pronunciation_audio_pass_no_issues(tmp_path):
    class CleanGemini:
        async def generate_structured_multimodal(self, **kwargs):
            return PronunciationAudit(verdict="pass", issues=[], notes=["clean"])

    class UnusedTTS:
        async def text_to_speech_with_timestamps(self, **kwargs):
            raise AssertionError("TTS should not run when Gemini finds no issues")

    async def run():
        result = await repair_pronunciation_audio(
            gemini=CleanGemini(),
            tts=UnusedTTS(),
            audio_path=tmp_path / "voice.mp3",
            alignment=character_alignment("Пилатес хорош."),
            scene_lines={
                "full_text": "Пилатес хорош.",
                "scenes": [{"scene_id": 1, "voiceover_line": "Пилатес хорош."}],
            },
            voice_id="Svetlana",
            work_dir=tmp_path / "work",
            output_path=tmp_path / "patched.mp3",
            strategy="splice",
        )
        assert result.status == "pass_no_issues"
        assert result.repaired_audio_path.endswith("voice.mp3")

    asyncio.run(run())


def test_pronunciation_candidate_filter_rejects_service_words_and_phrases():
    assert not is_pronunciation_repair_candidate(
        PronunciationIssue(
            scene_id=12,
            heard_word="к",
            expected_word="к",
            replacement_text="вдобавок к",
            reason="Not a stress issue.",
            severity="medium",
            confidence=0.9,
        ),
        min_confidence=0.55,
    )
    assert not is_pronunciation_repair_candidate(
        PronunciationIssue(
            scene_id=12,
            heard_word="вдобавок",
            expected_word="вдобавок",
            replacement_text="вдобавок к",
            reason="Replacement is a phrase.",
            severity="medium",
            confidence=0.9,
        ),
        min_confidence=0.55,
    )


def test_invalid_pronunciation_issues_do_not_trigger_full_revoice(tmp_path):
    text = "Они не едят его вдобавок к сытному завтраку."
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"original")

    class BadIssueGemini:
        async def generate_structured_multimodal(self, *, response_model, **kwargs):
            return PronunciationAudit(
                verdict="needs_repair",
                issues=[
                    PronunciationIssue(
                        scene_id=1,
                        heard_word="к",
                        expected_word="к",
                        replacement_text="вдобавок к",
                        reason="Service word should not be repaired.",
                        severity="medium",
                        confidence=0.9,
                    )
                ],
            )

    class UnusedTTS:
        async def text_to_speech_with_timestamps(self, **kwargs):
            raise AssertionError("Invalid pronunciation issues should not trigger TTS")

    async def run():
        result = await repair_pronunciation_audio(
            gemini=BadIssueGemini(),
            tts=UnusedTTS(),
            audio_path=audio_path,
            alignment=character_alignment(text),
            scene_lines={"full_text": text, "scenes": [{"scene_id": 1, "voiceover_line": text}]},
            voice_id="Svetlana",
            work_dir=tmp_path / "work",
            output_path=tmp_path / "patched.mp3",
        )
        assert result.status == "pass_no_issues"

    asyncio.run(run())


def test_build_revoiced_scene_lines_applies_tts_hints_without_splicing():
    scene_lines = {
        "full_text": "Я люблю пилатеса. В нем сироп.",
        "scenes": [
            {"scene_id": 1, "voiceover_line": "Я люблю пилатеса."},
            {"scene_id": 2, "voiceover_line": "В нем сироп."},
        ],
    }

    repaired, applied, skipped = build_revoiced_scene_lines(
        scene_lines,
        [
            PronunciationIssue(
                scene_id=1,
                heard_word="пилатеса",
                expected_word="pilates-а",
                replacement_text="pilates-а",
                reason="Wrong stress.",
                confidence=0.9,
            ),
            PronunciationIssue(
                scene_id=2,
                heard_word="нем",
                expected_word="нём",
                replacement_text="нём",
                reason="Missing ё.",
                confidence=0.9,
            ),
        ],
    )

    assert skipped == []
    assert len(applied) == 2
    assert repaired["scenes"][0]["voiceover_line"] == "Я люблю pilates-а."
    assert repaired["scenes"][1]["voiceover_line"] == "В нём сироп."
    assert repaired["full_text"] == "Я люблю pilates-а. В нём сироп."


def test_repair_pronunciation_audio_full_revoice_uses_one_full_tts_pass(tmp_path):
    text = "Я люблю пилатеса."
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"original")
    calls = []

    class OneIssueGemini:
        async def generate_structured_multimodal(self, *, response_model, **kwargs):
            if response_model is PronunciationAudit:
                return PronunciationAudit(
                    verdict="needs_repair",
                    issues=[
                        PronunciationIssue(
                            issue_id="pilates",
                            scene_id=1,
                            heard_word="пилатеса",
                            expected_word="pilates-а",
                            replacement_text="pilates-а",
                            reason="Stress should fall on A.",
                            severity="high",
                            confidence=0.92,
                        )
                    ],
                )
            return PronunciationVerification(verdict="pass", remaining_issues=[])

    class FakeTTS:
        async def text_to_speech_with_timestamps(self, *, text, voice_id, output_path):
            calls.append((text, voice_id))
            output_path.write_bytes(b"full revoice")
            return {"alignment": character_alignment(text), "audio_path": str(output_path)}

    async def run():
        result = await repair_pronunciation_audio(
            gemini=OneIssueGemini(),
            tts=FakeTTS(),
            audio_path=audio_path,
            alignment=character_alignment(text),
            scene_lines={"full_text": text, "scenes": [{"scene_id": 1, "voiceover_line": text}]},
            voice_id="Svetlana",
            work_dir=tmp_path / "work",
            output_path=tmp_path / "patched.mp3",
            alignment_output_path=tmp_path / "patched.alignment.json",
            scene_lines_output_path=tmp_path / "patched.scene-lines.tts.json",
        )
        assert result.status == "revoiced"
        assert calls == [("Я люблю pilates-а.", "Svetlana")]
        assert result.applied_repairs == []
        assert len(result.applied_text_repairs) == 1
        assert (tmp_path / "patched.mp3").read_bytes() == b"full revoice"
        assert (tmp_path / "patched.alignment.json").exists()
        assert (tmp_path / "patched.scene-lines.tts.json").exists()

    asyncio.run(run())


def test_word_alignment_matches_clean_text_to_pronunciation_hint_alignment():
    clean_text = "Я был в нем. Потом ушел."
    hinted_text = "Я был в нём. Потом ушёл."

    words, warnings = align_words_to_character_alignment(clean_text, character_alignment(hinted_text))

    assert warnings == []
    assert [word["word"] for word in words] == ["Я", "был", "в", "нем.", "Потом", "ушел."]


def test_word_alignment_matches_clean_text_to_latin_loanword_alignment():
    clean_text = "После пилатеса она пьет латте."
    hinted_text = "После pilates-а она пьет latte."

    words, warnings = align_words_to_character_alignment(clean_text, character_alignment(hinted_text))

    assert warnings == []
    assert [word["word"] for word in words] == ["После", "пилатеса", "она", "пьет", "латте."]


def test_repair_pronunciation_audio_one_attempt_then_verify(tmp_path, monkeypatch):
    text = "Я люблю пилатеса."
    audio_path = tmp_path / "voice.mp3"
    audio_path.write_bytes(b"original")
    calls = []

    class OneIssueGemini:
        async def generate_structured_multimodal(self, *, response_model, **kwargs):
            if response_model is PronunciationAudit:
                return PronunciationAudit(
                    verdict="needs_repair",
                    issues=[
                        PronunciationIssue(
                            issue_id="pilates",
                            scene_id=1,
                            heard_word="пилатеса",
                            expected_word="pilates-а",
                            replacement_text="pilates-а",
                            alternatives=["pilatesa"],
                            reason="Stress should fall on A.",
                            severity="high",
                            confidence=0.92,
                        )
                    ],
                )
            return PronunciationVerification(verdict="pass", remaining_issues=[])

    class FakeTTS:
        async def text_to_speech_with_timestamps(self, *, text, voice_id, output_path):
            calls.append((text, voice_id))
            output_path.write_bytes(b"replacement")
            return {"alignment": character_alignment(text), "audio_path": str(output_path)}

    def fake_fit(source_path, output_path, *, target_duration_sec):
        output_path.write_bytes(b"fitted")

    def fake_splice(*, original_audio_path, replacements, output_path, work_dir):
        output_path.write_bytes(b"patched")

    monkeypatch.setattr(repair, "fit_audio_to_duration", fake_fit)
    monkeypatch.setattr(repair, "splice_audio_replacements", fake_splice)

    async def run():
        result = await repair_pronunciation_audio(
            gemini=OneIssueGemini(),
            tts=FakeTTS(),
            audio_path=audio_path,
            alignment=character_alignment(text),
            scene_lines={"full_text": text, "scenes": [{"scene_id": 1, "voiceover_line": text}]},
            voice_id="Svetlana",
            work_dir=tmp_path / "work",
            output_path=tmp_path / "patched.mp3",
            strategy="splice",
        )
        assert result.status == "repaired"
        assert calls == [("pilates-а", "Svetlana")]
        assert result.verification is not None
        assert result.verification.verdict == "pass"
        assert (tmp_path / "patched.mp3").read_bytes() == b"patched"

    asyncio.run(run())
