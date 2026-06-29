from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx

from reddit2video.errors import NodeError


ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"


class ElevenLabsError(NodeError):
    pass


class ElevenLabsClient:
    def __init__(
        self,
        *,
        api_key: str,
        proxy: str | None = None,
        timeout_seconds: float = 120.0,
        model_id: str = "eleven_multilingual_v2",
    ) -> None:
        self.api_key = api_key
        self.proxy = proxy
        self.timeout_seconds = timeout_seconds
        self.model_id = model_id
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_env(cls) -> "ElevenLabsClient":
        api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            raise ElevenLabsError("Missing ELEVENLABS_API_KEY in environment.")
        proxy = os.getenv("OUTBOUND_PROXY", "").strip() or None
        return cls(api_key=api_key, proxy=proxy)

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
        url = f"{ELEVENLABS_BASE_URL}/v1/text-to-speech/{voice_id}/with-timestamps"
        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }
        try:
            response = await self._http_client().post(
                url,
                params={"output_format": output_format},
                json=payload,
                headers={"xi-api-key": self.api_key, "accept": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ElevenLabsError(
                f"ElevenLabs HTTP {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"ElevenLabs request failed: {exc}") from exc

        data = response.json()
        audio_base64 = data.get("audio_base64")
        if not audio_base64:
            raise ElevenLabsError("ElevenLabs response did not contain audio_base64.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(audio_base64))
        return {
            "alignment": data.get("alignment") or {},
            "normalized_alignment": data.get("normalized_alignment") or {},
            "audio_path": str(output_path),
            "voice_id": voice_id,
            "model_id": self.model_id,
            "output_format": output_format,
        }

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(proxy=self.proxy, timeout=self.timeout_seconds)
        return self._client

