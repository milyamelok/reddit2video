from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import httpx


class VertexImageGenerationError(RuntimeError):
    pass


async def generate_vertex_express_image(
    *,
    prompt: str,
    output_path: Path,
    model: str = "gemini-3.1-flash-image-preview",
    aspect_ratio: str = "4:3",
) -> dict[str, Any]:
    """Generate a single image through the Vertex Express image endpoint.

    The normal project/location google-genai Vertex path did not work for the
    Gemini image preview models in this project. This follows the documented
    local smoke path in docs/vertex_image_generation_notes.md.
    """

    api_key = os.getenv("VERTEX_AI_API_KEY_V2") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise VertexImageGenerationError("Missing VERTEX_AI_API_KEY_V2 or GOOGLE_API_KEY.")

    if output_path.exists() and output_path.stat().st_size > 0:
        metadata_path = output_path.with_suffix(".metadata.json")
        metadata = {
            "model": model,
            "aspect_ratio": aspect_ratio,
            "endpoint": "vertex_express_v1beta1",
            "mime_type": _mime_type_from_suffix(output_path.suffix),
            "output_path": str(output_path),
            "usage_metadata": {},
            "text": "",
            "cache_hit": True,
        }
        if metadata_path.exists():
            try:
                metadata.update(json.loads(metadata_path.read_text(encoding="utf-8")))
                metadata["cache_hit"] = True
            except json.JSONDecodeError:
                pass
        return metadata

    model_id = model if "/" in model else f"publishers/google/models/{model}"
    url = f"https://aiplatform.googleapis.com/v1beta1/{model_id}:generateContent"
    image_prompt = _prompt_with_aspect_ratio(prompt=prompt, aspect_ratio=aspect_ratio)
    payload = _build_payload(prompt=image_prompt, aspect_ratio=aspect_ratio, include_image_config=True)

    timeout_sec = float(os.getenv("REDDIT2VIDEO_VERTEX_IMAGE_TIMEOUT_SEC", "600"))
    timeout = httpx.Timeout(timeout_sec, connect=30.0, write=60.0, pool=timeout_sec)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        response = await client.post(url, params={"key": api_key}, json=payload)
        if response.status_code >= 400 and "imageConfig" in response.text:
            payload = _build_payload(prompt=image_prompt, aspect_ratio=aspect_ratio, include_image_config=False)
            response = await client.post(url, params={"key": api_key}, json=payload)
    if response.status_code >= 400:
        raise VertexImageGenerationError(
            f"Vertex image request failed: {response.status_code} {response.text[:1000]}"
        )

    data = response.json()
    image_parts = _image_parts(data)
    if not image_parts:
        raise VertexImageGenerationError(f"Vertex image response did not contain inline image data: {data}")
    inline = image_parts[0]
    mime_type = str(inline.get("mimeType") or inline.get("mime_type") or "image/png")
    suffix = _suffix_from_mime_type(mime_type)
    output_path = output_path.with_suffix(suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(str(inline.get("data") or "")))

    metadata = {
        "model": model,
        "aspect_ratio": aspect_ratio,
        "endpoint": "vertex_express_v1beta1",
        "mime_type": mime_type,
        "output_path": str(output_path),
        "usage_metadata": data.get("usageMetadata") or data.get("usage_metadata") or {},
        "text": _response_text(data),
    }
    metadata_path = output_path.with_suffix(".metadata.json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def _build_payload(*, prompt: str, aspect_ratio: str, include_image_config: bool) -> dict[str, Any]:
    generation_config: dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"]}
    if include_image_config:
        generation_config["imageConfig"] = {"aspectRatio": aspect_ratio}
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }


def _prompt_with_aspect_ratio(*, prompt: str, aspect_ratio: str) -> str:
    clean = " ".join(str(prompt or "").split())
    if not clean:
        clean = "Editorial vertical-video insert image, no text."
    return (
        f"Generate a single production-ready raster image for a vertical video layout. "
        f"Required image aspect ratio: {aspect_ratio}. No text, no captions, no UI screenshots. "
        f"Image brief: {clean}"
    )


def _image_parts(data: dict[str, Any]) -> list[dict[str, Any]]:
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    result: list[dict[str, Any]] = []
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline, dict) and inline.get("data"):
            result.append(inline)
    return result


def _response_text(data: dict[str, Any]) -> str:
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return "\n".join(str(part.get("text") or "") for part in parts if part.get("text")).strip()


def _suffix_from_mime_type(mime_type: str) -> str:
    normalized = mime_type.lower()
    if "jpeg" in normalized or "jpg" in normalized:
        return ".jpg"
    if "webp" in normalized:
        return ".webp"
    return ".png"


def _mime_type_from_suffix(suffix: str) -> str:
    normalized = suffix.lower()
    if normalized in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if normalized == ".webp":
        return "image/webp"
    return "image/png"
