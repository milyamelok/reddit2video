from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx

from reddit2video.errors import NodeError


INWORLD_BASE_URL = "https://api.inworld.ai"


class InworldTTSError(NodeError):
    pass


class InworldTTSClient:
    def __init__(
        self,
        *,
        api_key: str,
        proxy: str | None = None,
        timeout_seconds: float = 180.0,
        model_id: str = "inworld-tts-2",
        delivery_mode: str = "BALANCED",
        speaking_rate: float = 1.25,
        language: str = "ru",
        audio_encoding: str = "MP3",
        sample_rate_hertz: int = 48000,
        bit_rate: int = 128000,
        apply_text_normalization: str = "ON",
        timestamp_type: str = "CHARACTER",
        base_url: str = INWORLD_BASE_URL,
    ) -> None:
        self.api_key = api_key
        self.proxy = proxy
        self.timeout_seconds = timeout_seconds
        self.model_id = model_id
        self.delivery_mode = delivery_mode
        self.speaking_rate = speaking_rate
        self.language = language
        self.audio_encoding = audio_encoding
        self.sample_rate_hertz = sample_rate_hertz
        self.bit_rate = bit_rate
        self.apply_text_normalization = apply_text_normalization
        self.timestamp_type = timestamp_type
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_env(cls) -> "InworldTTSClient":
        api_key = os.getenv("INWORLD_API_KEY", "").strip()
        if not api_key:
            raise InworldTTSError("Missing INWORLD_API_KEY in environment.")
        proxy = os.getenv("OUTBOUND_PROXY", "").strip() or None
        return cls(
            api_key=api_key,
            proxy=proxy,
            model_id=os.getenv("INWORLD_TTS_MODEL_ID", "inworld-tts-2").strip() or "inworld-tts-2",
            delivery_mode=os.getenv("INWORLD_TTS_DELIVERY_MODE", "BALANCED").strip() or "BALANCED",
            speaking_rate=float(os.getenv("INWORLD_TTS_SPEAKING_RATE", "1.25") or "1.25"),
            language=os.getenv("INWORLD_TTS_LANGUAGE", "ru").strip() or "ru",
            audio_encoding=os.getenv("INWORLD_TTS_AUDIO_ENCODING", "MP3").strip() or "MP3",
            sample_rate_hertz=int(os.getenv("INWORLD_TTS_SAMPLE_RATE_HERTZ", "48000") or "48000"),
            bit_rate=int(os.getenv("INWORLD_TTS_BIT_RATE", "128000") or "128000"),
            apply_text_normalization=(
                os.getenv("INWORLD_TTS_APPLY_TEXT_NORMALIZATION", "ON").strip() or "ON"
            ),
            timestamp_type=os.getenv("INWORLD_TTS_TIMESTAMP_TYPE", "CHARACTER").strip() or "CHARACTER",
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def text_to_speech_with_timestamps(
        self,
        *,
        text: str,
        voice_id: str,
        output_path: Path,
        output_format: str = "mp3_44100_128",
    ) -> dict[str, Any]:
        if len(text) > 2000:
            raise InworldTTSError(
                "Inworld REST TTS input exceeds 2,000 characters. "
                "Split/chunking is not wired into this client yet."
            )
        payload = self._build_payload(text=text, voice_id=voice_id)
        try:
            response = await self._http_client().post(
                f"{self.base_url}/tts/v1/voice",
                json=payload,
                headers={
                    "Authorization": f"Basic {self.api_key}",
                    "Content-Type": "application/json",
                    "accept": "application/json",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InworldTTSError(
                f"Inworld TTS HTTP {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise InworldTTSError(f"Inworld TTS request failed: {exc}") from exc

        data = response.json()
        audio_base64 = data.get("audioContent")
        if not audio_base64:
            raise InworldTTSError("Inworld response did not contain audioContent.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(audio_base64))
        alignment = _inworld_timestamp_info_to_alignment(data.get("timestampInfo") or {})
        return {
            "alignment": alignment,
            "normalized_alignment": {},
            "audio_path": str(output_path),
            "voice_id": voice_id,
            "voice_name": voice_id,
            "model_id": self.model_id,
            "provider": "inworld",
            "output_format": output_format,
            "inworld_payload": {k: v for k, v in payload.items() if k != "text"},
            "timestamp_info": data.get("timestampInfo") or {},
            "usage": data.get("usage") or {},
            "source_voiceover": text,
        }

    def _build_payload(self, *, text: str, voice_id: str) -> dict[str, Any]:
        return {
            "text": text,
            "voiceId": voice_id,
            "modelId": self.model_id,
            "audioConfig": {
                "audioEncoding": self.audio_encoding,
                "sampleRateHertz": self.sample_rate_hertz,
                "bitRate": self.bit_rate,
                "speakingRate": self.speaking_rate,
            },
            "language": self.language,
            "deliveryMode": self.delivery_mode,
            "timestampType": self.timestamp_type,
            "applyTextNormalization": self.apply_text_normalization,
        }

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(proxy=self.proxy, timeout=self.timeout_seconds)
        return self._client


def _inworld_timestamp_info_to_alignment(timestamp_info: dict[str, Any]) -> dict[str, list[Any]]:
    character_alignment = timestamp_info.get("characterAlignment")
    if isinstance(character_alignment, dict):
        characters = list(character_alignment.get("characters") or [])
        starts = list(character_alignment.get("characterStartTimeSeconds") or [])
        ends = list(character_alignment.get("characterEndTimeSeconds") or [])
        if characters and characters[0] == "":
            characters = characters[1:]
            starts = starts[1:]
            ends = ends[1:]
        return {
            "characters": [str(character) for character in characters],
            "character_start_times_seconds": [float(value) for value in starts],
            "character_end_times_seconds": [float(value) for value in ends],
        }
    word_alignment = timestamp_info.get("wordAlignment")
    if isinstance(word_alignment, dict):
        words = [str(word) for word in word_alignment.get("words") or []]
        starts = [float(value) for value in word_alignment.get("wordStartTimeSeconds") or []]
        ends = [float(value) for value in word_alignment.get("wordEndTimeSeconds") or []]
        characters: list[str] = []
        character_starts: list[float] = []
        character_ends: list[float] = []
        for index, word in enumerate(words):
            if index:
                characters.append(" ")
                character_starts.append(ends[index - 1])
                character_ends.append(starts[index] if index < len(starts) else ends[index - 1])
            start = starts[index] if index < len(starts) else 0.0
            end = ends[index] if index < len(ends) else start
            step = (end - start) / max(1, len(word))
            for char_index, character in enumerate(word):
                characters.append(character)
                character_starts.append(start + step * char_index)
                character_ends.append(start + step * (char_index + 1))
        return {
            "characters": characters,
            "character_start_times_seconds": character_starts,
            "character_end_times_seconds": character_ends,
        }
    return {}
