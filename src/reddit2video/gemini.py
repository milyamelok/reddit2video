from __future__ import annotations

import base64
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar

from pydantic import BaseModel

from reddit2video.errors import NodeError


StructuredT = TypeVar("StructuredT", bound=BaseModel)


class GeminiClientError(NodeError):
    pass


class GeminiClient:
    def __init__(
        self,
        *,
        model: str = "gemini-3.1-pro-preview",
        vertex: bool = True,
        project: str | None = None,
        location: str | None = None,
        service_account_json: str | None = None,
    ) -> None:
        self.model = model
        self.vertex = vertex
        self.project = project
        self.location = location or "global"
        self.service_account_json = service_account_json
        self._client: Any | None = None

    @classmethod
    def from_env(cls, *, model: str = "gemini-3.1-pro-preview", vertex: bool = True) -> "GeminiClient":
        _apply_proxy_env()
        _clear_missing_adc_env()
        service_account_json = (
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or os.getenv("PATH_TO_VERTEX_JSON")
            or None
        )
        project = (
            os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("VERTEX_PROJECT_ID")
            or _project_id_from_service_account(service_account_json)
        )
        location = os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("VERTEX_LOCATION") or "global"
        return cls(
            model=model,
            vertex=vertex,
            project=project,
            location=location,
            service_account_json=service_account_json,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            close = getattr(self._client.aio, "aclose", None)
            if close is not None:
                await close()
            self._client = None

    async def generate_structured(
        self,
        *,
        prompt: str,
        response_model: type[StructuredT],
        model: str | None = None,
        cached_content: str | None = None,
    ) -> StructuredT:
        if self._use_vertex_express_rest() and not cached_content:
            return await self._generate_structured_vertex_express(
                prompt=prompt,
                response_model=response_model,
                model=model,
            )
        client = self._ensure_client()
        try:
            from google.genai import types
        except ImportError as exc:
            raise GeminiClientError("google-genai is not installed. Run `pip install -e .`.") from exc

        config_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": response_model,
        }
        if cached_content:
            config_kwargs["cached_content"] = cached_content

        response = await client.aio.models.generate_content(
            model=model or self.model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, response_model):
            return parsed
        if parsed is not None:
            return response_model.model_validate(parsed)
        if not getattr(response, "text", None):
            raise GeminiClientError("Gemini returned an empty structured response.")
        return response_model.model_validate_json(response.text)

    async def create_text_cache(
        self,
        *,
        text: str,
        display_name: str = "reddit2video-cache",
        model: str | None = None,
        ttl: str = "3600s",
    ) -> str:
        """Create a Gemini cached content entry through the SDK client.

        This intentionally uses the SDK service-account/project path instead of
        the Vertex Express REST shortcut because cachedContent is managed as a
        first-class resource.
        """
        client = self._ensure_client()
        try:
            from google.genai import types
        except ImportError as exc:
            raise GeminiClientError("google-genai is not installed. Run `pip install -e .`.") from exc

        cached = await client.aio.caches.create(
            model=model or self.model,
            config=types.CreateCachedContentConfig(
                display_name=display_name,
                ttl=ttl,
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=text)])],
            ),
        )
        name = getattr(cached, "name", None)
        if not name:
            raise GeminiClientError(f"Gemini cache create returned an unexpected response: {cached!r}")
        return str(name)

    async def generate_structured_multimodal(
        self,
        *,
        prompt: str,
        image_paths: list[str | Path],
        response_model: type[StructuredT],
        model: str | None = None,
        cached_content: str | None = None,
    ) -> StructuredT:
        if self._use_vertex_express_rest() and not cached_content:
            return await self._generate_structured_multimodal_vertex_express(
                prompt=prompt,
                image_paths=image_paths,
                response_model=response_model,
                model=model,
            )
        client = self._ensure_client()
        try:
            from google.genai import types
        except ImportError as exc:
            raise GeminiClientError("google-genai is not installed. Run `pip install -e .`.") from exc

        parts: list[Any] = [types.Part.from_text(text=prompt)]
        for image_path in image_paths:
            path = Path(image_path)
            if not path.exists():
                continue
            parts.append(
                types.Part.from_bytes(
                    data=path.read_bytes(),
                    mime_type=_mime_type_for_path(path),
                )
            )
        config_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": response_model,
        }
        if cached_content:
            config_kwargs["cached_content"] = cached_content
        response = await client.aio.models.generate_content(
            model=model or self.model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(**config_kwargs),
        )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, response_model):
            return parsed
        if parsed is not None:
            return response_model.model_validate(parsed)
        if not getattr(response, "text", None):
            raise GeminiClientError("Gemini returned an empty structured multimodal response.")
        return response_model.model_validate_json(response.text)

    async def generate_content_parts(
        self,
        *,
        parts: list[Any],
        config: Any = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> Any:
        if self._use_vertex_express_rest():
            return await self._generate_content_parts_vertex_express(
                parts=parts,
                config=config,
                seed=seed,
                model=model,
            )
        client = self._ensure_client()
        try:
            from google.genai import types
        except ImportError as exc:
            raise GeminiClientError("google-genai is not installed. Run `pip install -e .`.") from exc
        return await client.aio.models.generate_content(
            model=model or self.model,
            contents=[types.Content(role="user", parts=parts)],
            config=config,
        )

    async def _generate_structured_vertex_express(
        self,
        *,
        prompt: str,
        response_model: type[StructuredT],
        model: str | None = None,
    ) -> StructuredT:
        response_schema = _response_schema(response_model)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
            },
        }
        try:
            return await self._post_vertex_express(
                payload=payload,
                response_model=response_model,
                model=model,
            )
        except GeminiClientError as exc:
            if not _looks_like_schema_constraint_error(str(exc)):
                raise
            fallback_payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": "\n\n".join(
                                    [
                                        prompt,
                                        "Return JSON only. It must validate locally against this JSON schema:",
                                        json.dumps(response_schema, ensure_ascii=False),
                                    ]
                                )
                            }
                        ],
                    }
                ],
                "generationConfig": {"responseMimeType": "application/json"},
            }
            return await self._post_vertex_express(
                payload=fallback_payload,
                response_model=response_model,
                model=model,
            )

    async def _generate_content_parts_vertex_express(
        self,
        *,
        parts: list[Any],
        config: Any = None,
        seed: int | None = None,
        model: str | None = None,
    ) -> Any:
        generation_config: dict[str, Any] = {}
        response_schema_model: type[BaseModel] | None = None
        if seed is not None:
            generation_config["seed"] = seed
        if config is not None:
            response_mime_type = getattr(config, "response_mime_type", None)
            if response_mime_type:
                generation_config["responseMimeType"] = response_mime_type
            config_seed = getattr(config, "seed", None)
            if config_seed is not None:
                generation_config["seed"] = config_seed
            response_schema = getattr(config, "response_schema", None)
            if isinstance(response_schema, type) and issubclass(response_schema, BaseModel):
                response_schema_model = response_schema
                generation_config["responseSchema"] = _response_schema(response_schema)
            elif isinstance(response_schema, dict):
                generation_config["responseSchema"] = response_schema
        payload = {
            "contents": [{"role": "user", "parts": [_vertex_part_from_genai_part(part) for part in parts]}],
        }
        if generation_config:
            payload["generationConfig"] = generation_config
        text = await self._post_vertex_express_text(payload=payload, model=model)
        parsed = None
        if response_schema_model is not None and text.strip():
            try:
                parsed = response_schema_model.model_validate_json(text)
            except Exception:
                parsed = None
        return SimpleNamespace(text=text, parsed=parsed)

    async def _generate_structured_multimodal_vertex_express(
        self,
        *,
        prompt: str,
        image_paths: list[str | Path],
        response_model: type[StructuredT],
        model: str | None = None,
    ) -> StructuredT:
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for image_path in image_paths:
            path = Path(image_path)
            if not path.exists():
                continue
            parts.append(
                {
                    "inlineData": {
                        "mimeType": _mime_type_for_path(path),
                        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                    }
                }
            )
        response_schema = _response_schema(response_model)
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
            },
        }
        try:
            return await self._post_vertex_express(
                payload=payload,
                response_model=response_model,
                model=model,
            )
        except GeminiClientError as exc:
            if not _looks_like_schema_constraint_error(str(exc)):
                raise
            fallback_parts = list(parts)
            fallback_parts[0] = {
                "text": "\n\n".join(
                    [
                        prompt,
                        "Return JSON only. It must validate locally against this JSON schema:",
                        json.dumps(response_schema, ensure_ascii=False),
                    ]
                )
            }
            fallback_payload = {
                "contents": [{"role": "user", "parts": fallback_parts}],
                "generationConfig": {"responseMimeType": "application/json"},
            }
            return await self._post_vertex_express(
                payload=fallback_payload,
                response_model=response_model,
                model=model,
            )

    async def _post_vertex_express(
        self,
        *,
        payload: dict[str, Any],
        response_model: type[StructuredT],
        model: str | None = None,
    ) -> StructuredT:
        api_key = os.getenv("VERTEX_AI_API_KEY_V2") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise GeminiClientError("Missing VERTEX_AI_API_KEY_V2 for Vertex Express mode.")
        model_id = model or self.model
        if "/" not in model_id:
            model_id = f"publishers/google/models/{model_id}"
        url = f"https://aiplatform.googleapis.com/v1beta1/{model_id}:generateContent"
        try:
            import httpx
        except ImportError as exc:
            raise GeminiClientError("httpx is not installed. Run `pip install -e .`.") from exc

        timeout_sec = float(os.getenv("REDDIT2VIDEO_VERTEX_TIMEOUT_SEC", "600"))
        timeout = httpx.Timeout(timeout_sec, connect=30.0, write=60.0, pool=timeout_sec)
        response = await _post_with_retries(url=url, params={"key": api_key}, json_payload=payload, timeout=timeout)
        if response.status_code >= 400:
            raise GeminiClientError(f"Vertex Express request failed: {response.status_code} {response.text[:1000]}")
        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(str(part.get("text") or "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiClientError(f"Vertex Express returned an unexpected response: {data}") from exc
        if not text.strip():
            raise GeminiClientError("Vertex Express returned an empty structured response.")
        return response_model.model_validate_json(text)

    async def _post_vertex_express_text(
        self,
        *,
        payload: dict[str, Any],
        model: str | None = None,
    ) -> str:
        api_key = os.getenv("VERTEX_AI_API_KEY_V2") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise GeminiClientError("Missing VERTEX_AI_API_KEY_V2 for Vertex Express mode.")
        model_id = model or self.model
        if "/" not in model_id:
            model_id = f"publishers/google/models/{model_id}"
        url = f"https://aiplatform.googleapis.com/v1beta1/{model_id}:generateContent"
        try:
            import httpx
        except ImportError as exc:
            raise GeminiClientError("httpx is not installed. Run `pip install -e .`.") from exc

        timeout_sec = float(os.getenv("REDDIT2VIDEO_VERTEX_TIMEOUT_SEC", "600"))
        timeout = httpx.Timeout(timeout_sec, connect=30.0, write=60.0, pool=timeout_sec)
        response = await _post_with_retries(url=url, params={"key": api_key}, json_payload=payload, timeout=timeout)
        if response.status_code >= 400:
            raise GeminiClientError(f"Vertex Express request failed: {response.status_code} {response.text[:1000]}")
        data = response.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(str(part.get("text") or "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiClientError(f"Vertex Express returned an unexpected response: {data}") from exc

    def _use_vertex_express_rest(self) -> bool:
        if not self.vertex:
            return False
        if not (os.getenv("VERTEX_AI_API_KEY_V2") or os.getenv("GOOGLE_API_KEY")):
            return False
        auth_mode = os.getenv("REDDIT2VIDEO_VERTEX_AUTH_MODE", "").strip().lower()
        if auth_mode in {"service_account", "project", "adc"}:
            return False
        if os.getenv("REDDIT2VIDEO_VERTEX_EXPRESS_REST", "1").strip().lower() in {"0", "false", "no"}:
            return False
        if auth_mode in {"express", "api_key", "api-key"}:
            return True
        # API-key Vertex Express is the default for preview models in this project.
        # Keep service-account Vertex available through REDDIT2VIDEO_VERTEX_AUTH_MODE=service_account.
        return True

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:
            raise GeminiClientError("google-genai is not installed. Run `pip install -e .`.") from exc

        credentials = _load_credentials(self.service_account_json)
        if self.vertex:
            api_key = os.getenv("VERTEX_AI_API_KEY_V2") or os.getenv("GOOGLE_API_KEY")
            if self.project:
                self._client = genai.Client(
                    vertexai=True,
                    project=self.project,
                    location=self.location,
                    credentials=credentials,
                )
            elif api_key:
                self._client = genai.Client(
                    vertexai=True,
                    api_key=api_key,
                )
            else:
                raise GeminiClientError(
                    "Missing Vertex AI auth. Set GOOGLE_CLOUD_PROJECT with credentials, or VERTEX_AI_API_KEY_V2."
                )
        else:
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("VERTEX_AI_API_KEY_V2")
            if not api_key:
                raise GeminiClientError("Missing Gemini API key for non-Vertex mode.")
            self._client = genai.Client(api_key=api_key)
        return self._client


def _load_credentials(service_account_json: str | None) -> Any | None:
    if not service_account_json:
        return None
    path = Path(service_account_json).expanduser()
    if not path.exists():
        return None
    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise GeminiClientError("google-auth is not installed. Run `pip install -e .`.") from exc
    return service_account.Credentials.from_service_account_file(
        str(path),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def _project_id_from_service_account(service_account_json: str | None) -> str | None:
    if not service_account_json:
        return None
    path = Path(service_account_json).expanduser()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    project_id = payload.get("project_id")
    return str(project_id) if project_id else None


def _apply_proxy_env() -> None:
    proxy = os.getenv("OUTBOUND_PROXY", "").strip()
    if not proxy:
        return
    os.environ.setdefault("HTTPS_PROXY", proxy)
    os.environ.setdefault("HTTP_PROXY", proxy)


def _clear_missing_adc_env() -> None:
    for key in ("GOOGLE_APPLICATION_CREDENTIALS", "PATH_TO_VERTEX_JSON"):
        credentials_path = os.getenv(key, "").strip()
        if credentials_path and not Path(credentials_path).expanduser().exists():
            os.environ.pop(key, None)


async def _post_with_retries(
    *,
    url: str,
    params: dict[str, str],
    json_payload: dict[str, Any],
    timeout: Any,
    attempts: int = 4,
) -> Any:
    try:
        import httpx
    except ImportError as exc:
        raise GeminiClientError("httpx is not installed. Run `pip install -e .`.") from exc

    retry_attempts = int(os.getenv("REDDIT2VIDEO_VERTEX_RETRY_ATTEMPTS", str(attempts)))
    retry_statuses = {429, 500, 502, 503, 504}
    last_exc: Exception | None = None
    last_response: Any | None = None
    for attempt in range(1, max(1, retry_attempts) + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(url, params=params, json=json_payload)
                if response.status_code not in retry_statuses or attempt >= retry_attempts:
                    return response
                last_response = response
                await asyncio.sleep(_retry_delay_seconds(attempt, response))
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            if attempt >= retry_attempts:
                break
            await asyncio.sleep(_retry_delay_seconds(attempt, None))
    if last_response is not None:
        return last_response
    assert last_exc is not None
    raise last_exc


def _retry_delay_seconds(attempt: int, response: Any | None) -> float:
    retry_after = None
    if response is not None:
        retry_after = response.headers.get("retry-after")
    try:
        if retry_after:
            return min(30.0, max(1.0, float(retry_after)))
    except ValueError:
        pass
    return min(30.0, 1.0 * (2 ** (attempt - 1)))


def _mime_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".mp4":
        return "video/mp4"
    if suffix == ".mov":
        return "video/quicktime"
    if suffix == ".webm":
        return "video/webm"
    return "application/octet-stream"


def _looks_like_schema_constraint_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "invalid_argument" in lowered
        and (
            "schema" in lowered
            or "too many states" in lowered
            or "constraint" in lowered
            or "invalid argument" in lowered
        )
    )


def _response_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    schema = response_model.model_json_schema()
    return _inline_json_schema_refs(schema)


def _vertex_part_from_genai_part(part: Any) -> dict[str, Any]:
    text = getattr(part, "text", None)
    if text is not None:
        return {"text": str(text)}
    inline_data = getattr(part, "inline_data", None)
    if inline_data is not None:
        data = getattr(inline_data, "data", b"") or b""
        if isinstance(data, str):
            encoded = data
        else:
            encoded = base64.b64encode(data).decode("ascii")
        return {
            "inlineData": {
                "mimeType": getattr(inline_data, "mime_type", None) or "application/octet-stream",
                "data": encoded,
            }
        }
    if isinstance(part, dict):
        return part
    return {"text": str(part)}


def _inline_json_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = str(node["$ref"])
                prefix = "#/$defs/"
                if ref.startswith(prefix):
                    return resolve(defs.get(ref[len(prefix) :], {}))
            clean: dict[str, Any] = {}
            for key, value in node.items():
                if key in {"$defs", "title", "default"}:
                    continue
                clean[key] = resolve(value)
            return clean
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)
