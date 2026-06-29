from __future__ import annotations

import json
import os

from pathlib import Path

from reddit2video.gemini import GeminiClient, _mime_type_for_path


def test_from_env_adc_ignores_missing_credentials_path(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing-service-account.json"
    monkeypatch.setenv("REDDIT2VIDEO_VERTEX_AUTH_MODE", "adc")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setenv("PATH_TO_VERTEX_JSON", str(missing_path))
    monkeypatch.setenv("VERTEX_AI_API_KEY_V2", "vertex-key-present-but-not-selected")

    client = GeminiClient.from_env(vertex=True)

    assert client.project == "demo-project"
    assert client.service_account_json is None
    assert "PATH_TO_VERTEX_JSON" not in os.environ
    assert client._use_vertex_express_rest() is False


def test_from_env_keeps_existing_service_account_path(monkeypatch, tmp_path):
    service_account = tmp_path / "service-account.json"
    service_account.write_text(json.dumps({"project_id": "service-account-project"}), encoding="utf-8")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("VERTEX_PROJECT_ID", raising=False)
    monkeypatch.setenv("PATH_TO_VERTEX_JSON", str(service_account))

    client = GeminiClient.from_env(vertex=True)

    assert client.project == "service-account-project"
    assert client.service_account_json == str(service_account)


def test_vertex_express_rest_disabled_for_adc(monkeypatch):
    monkeypatch.setenv("REDDIT2VIDEO_VERTEX_AUTH_MODE", "adc")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setenv("VERTEX_AI_API_KEY_V2", "vertex-key-present-but-not-selected")

    client = GeminiClient.from_env(vertex=True)

    assert client._use_vertex_express_rest() is False


def test_vertex_express_rest_default_with_api_key(monkeypatch):
    monkeypatch.delenv("REDDIT2VIDEO_VERTEX_AUTH_MODE", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("VERTEX_PROJECT_ID", raising=False)
    monkeypatch.setenv("VERTEX_AI_API_KEY_V2", "vertex-key")

    client = GeminiClient.from_env(vertex=True)

    assert client._use_vertex_express_rest() is True


def test_multimodal_mime_type_supports_video_without_png_masquerade():
    assert _mime_type_for_path(Path("render.mp4")) == "video/mp4"
    assert _mime_type_for_path(Path("frame.png")) == "image/png"
    assert _mime_type_for_path(Path("asset.unknown")) == "application/octet-stream"
