from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parent.parent


def load_download_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "download_selected_storyboard_assets",
        ROOT / "scripts/download_selected_storyboard_assets.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_drop_failed_remote_selected_candidates_marks_required_slot_failed() -> None:
    module = load_download_module()
    payload = {
        "items": [
            {
                "resolved_slots": [
                    {
                        "status": "pass",
                        "slot": {"required": True},
                        "selected_candidates": [
                            {
                                "candidate_id": "W01",
                                "media_url": "https://upload.wikimedia.org/broken.jpg",
                                "download_error": "HTTP Error 403",
                            }
                        ],
                        "errors": [],
                    }
                ]
            }
        ]
    }

    removed = module._drop_failed_remote_selected_candidates(payload)
    slot = payload["items"][0]["resolved_slots"][0]

    assert removed == 1
    assert slot["selected_candidates"] == []
    assert slot["status"] == "fail"
    assert "Removed 1 selected remote media candidate(s) after download failure." in slot["errors"]


def test_drop_failed_remote_selected_candidates_keeps_local_candidate() -> None:
    module = load_download_module()
    payload = {
        "items": [
            {
                "resolved_slots": [
                    {
                        "status": "pass",
                        "slot": {"required": True},
                        "selected_candidates": [
                            {
                                "candidate_id": "P01",
                                "media_url": "https://assets.test/media.jpg",
                                "public_path": "__STATIC_FILE__media.jpg",
                                "download_error": "stale old error",
                            }
                        ],
                    }
                ]
            }
        ]
    }

    removed = module._drop_failed_remote_selected_candidates(payload)

    assert removed == 0
    assert payload["items"][0]["resolved_slots"][0]["status"] == "pass"


def test_promote_replacement_candidates_skips_failed_url() -> None:
    module = load_download_module()
    payload = {
        "items": [
            {
                "resolved_slots": [
                    {
                        "status": "fail",
                        "slot": {"required": True},
                        "selected_candidates": [],
                        "candidate_pool": [
                            {
                                "candidate_id": "S01",
                                "media_url": "https://assets.test/broken.jpg",
                                "title": "broken",
                            },
                            {
                                "candidate_id": "S02",
                                "media_url": "https://assets.test/backup.jpg",
                                "title": "backup",
                            },
                        ],
                        "errors": [],
                    }
                ]
            }
        ]
    }

    promoted = module._promote_replacement_candidates(payload, failed_urls={"https://assets.test/broken.jpg"})
    slot = payload["items"][0]["resolved_slots"][0]

    assert promoted == 1
    assert slot["status"] == "pass"
    assert slot["selected_candidates"][0]["candidate_id"] == "S02"
    assert "Promoted replacement selected media candidate after download failure: S02." in slot["errors"]


def test_selected_download_jobs_skip_explicit_failed_slots(tmp_path: Path) -> None:
    module = load_download_module()
    payload = {
        "items": [
            {
                "post_id": "post1",
                "resolved_slots": [
                    {
                        "scene_id": 3,
                        "asset_id": "bad_slot",
                        "status": "fail",
                        "selected_candidates": [
                            {
                                "media_url": "https://assets.test/stale.mp4",
                                "title": "stale rejected candidate",
                            }
                        ],
                    },
                    {
                        "scene_id": 4,
                        "asset_id": "good_slot",
                        "status": "pass",
                        "selected_candidates": [{"media_url": "https://assets.test/good.mp4"}],
                    },
                ],
            }
        ]
    }

    jobs = module._selected_download_jobs(payload, tmp_path)

    assert len(jobs) == 1
    assert jobs[0][1] == "https://assets.test/good.mp4"
    assert jobs[0][3] == "s004_good_slot_01"


def test_hls_download_falls_back_to_thumbnail_and_ignores_stale_playlist(monkeypatch, tmp_path: Path) -> None:
    module = load_download_module()
    out_dir = tmp_path / "assets"
    out_dir.mkdir()
    stale = out_dir / "scene_asset_01.m3u8"
    stale.write_text("#EXTM3U\n", encoding="utf-8")

    class FakeResponse:
        headers = {"content-type": "image/jpeg"}

        def __enter__(self):  # noqa: ANN001
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def read(self, size: int) -> bytes:
            if getattr(self, "_done", False):
                return b""
            self._done = True
            return b"jpg-bytes"

    def fake_urlopen(request, *, timeout, context):  # noqa: ANN001
        assert request.full_url == "https://i.pinimg.com/originals/thumb.jpg"
        return FakeResponse()

    monkeypatch.setattr(module, "_convert_hls_to_mp4", lambda **kwargs: False)
    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    candidate = {
        "media_url": "https://v1.pinimg.com/videos/iht/hls/video.m3u8",
        "thumbnail_url": "https://i.pinimg.com/originals/thumb.jpg",
        "metadata": {"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/video.m3u8"},
    }

    result = module._download_one(candidate, candidate["media_url"], out_dir, "scene_asset_01", timeout=5, hls_duration_sec=1)

    assert result["status"] == "downloaded"
    assert candidate["local_path"].endswith(".jpg")
    assert not candidate["local_path"].endswith(".m3u8")
    assert Path(candidate["local_path"]).read_bytes() == b"jpg-bytes"


def test_existing_asset_without_matching_cache_metadata_is_refreshed(monkeypatch, tmp_path: Path) -> None:
    module = load_download_module()
    stale = tmp_path / "scene_asset_01.jpg"
    stale.write_bytes(b"old-watermarked-image")

    class FakeResponse:
        headers = {"content-type": "image/jpeg"}

        def __enter__(self):  # noqa: ANN001
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

        def read(self, size: int) -> bytes:
            if getattr(self, "_done", False):
                return b""
            self._done = True
            return b"fresh-image"

    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: FakeResponse())
    candidate = {"media_url": "https://assets.test/fresh.jpg"}

    result = module._download_one(candidate, candidate["media_url"], tmp_path, "scene_asset_01", timeout=5, hls_duration_sec=1)

    assert result["status"] == "downloaded"
    assert stale.read_bytes() == b"fresh-image"
    cache_metadata = module.json.loads((tmp_path / "scene_asset_01.jpg.download.json").read_text(encoding="utf-8"))
    assert cache_metadata["source_url"] == "https://assets.test/fresh.jpg"


def test_existing_asset_with_matching_cache_metadata_is_reused(monkeypatch, tmp_path: Path) -> None:
    module = load_download_module()
    cached = tmp_path / "scene_asset_01.jpg"
    cached.write_bytes(b"cached-image")
    module._write_cache_metadata(cached, source_url="https://assets.test/cached.jpg", content_type="image/jpeg")

    def fail_urlopen(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("matching cache should not perform a network request")

    monkeypatch.setattr(module, "urlopen", fail_urlopen)
    candidate = {"media_url": "https://assets.test/cached.jpg"}

    result = module._download_one(candidate, candidate["media_url"], tmp_path, "scene_asset_01", timeout=5, hls_duration_sec=1)

    assert result["status"] == "cached"
    assert candidate["local_path"] == str(cached)
    assert cached.read_bytes() == b"cached-image"


def test_selected_download_jobs_skip_matching_local_candidate(tmp_path: Path) -> None:
    module = load_download_module()
    cached = tmp_path / "already.jpg"
    cached.write_bytes(b"cached-image")
    module._write_cache_metadata(cached, source_url="https://assets.test/already.jpg", content_type="image/jpeg")
    payload = {
        "items": [
            {
                "post_id": "post1",
                "resolved_slots": [
                    {
                        "scene_id": 4,
                        "asset_id": "already_slot",
                        "status": "pass",
                        "selected_candidates": [
                            {
                                "media_url": "https://assets.test/already.jpg",
                                "local_path": str(cached),
                            }
                        ],
                    }
                ],
            }
        ]
    }

    jobs = module._selected_download_jobs(payload, tmp_path)

    assert jobs == []
    candidate = payload["items"][0]["resolved_slots"][0]["selected_candidates"][0]
    assert candidate["public_path"].endswith("already.jpg")
    assert candidate["local_content_type"] == "image/jpeg"


def test_selected_download_jobs_keep_stale_local_candidate_for_refresh(tmp_path: Path) -> None:
    module = load_download_module()
    stale = tmp_path / "stale.jpg"
    stale.write_bytes(b"stale-image")
    payload = {
        "items": [
            {
                "post_id": "post1",
                "resolved_slots": [
                    {
                        "scene_id": 4,
                        "asset_id": "stale_slot",
                        "status": "pass",
                        "selected_candidates": [
                            {
                                "media_url": "https://assets.test/fresh.jpg",
                                "local_path": str(stale),
                            }
                        ],
                    }
                ],
            }
        ]
    }

    jobs = module._selected_download_jobs(payload, tmp_path)

    assert len(jobs) == 1
    assert jobs[0][1] == "https://assets.test/fresh.jpg"


def test_download_rejects_avif_publication_asset(monkeypatch, tmp_path: Path) -> None:
    module = load_download_module()

    class FakeResponse:
        headers = {"content-type": "image/avif"}

        def __enter__(self):  # noqa: ANN001
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: FakeResponse())
    candidate = {"media_url": "https://assets.test/photo.avif"}

    result = module._download_one(candidate, candidate["media_url"], tmp_path, "asset", timeout=5, hls_duration_sec=1)

    assert result["status"] == "failed"
    assert "unsupported_publication_content_type:image/avif" in candidate["download_error"]
