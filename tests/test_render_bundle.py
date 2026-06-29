from reddit2video.nodes.render_bundle import _pinterest_highres_urls, _short_media_fingerprint


def test_pinterest_highres_urls_prefers_larger_variants() -> None:
    url = "https://i.pinimg.com/236x/91/35/40/example.jpg"

    variants = _pinterest_highres_urls(url)

    assert variants[:3] == [
        "https://i.pinimg.com/originals/91/35/40/example.jpg",
        "https://i.pinimg.com/736x/91/35/40/example.jpg",
        "https://i.pinimg.com/564x/91/35/40/example.jpg",
    ]
    assert variants[-1] == url


def test_short_media_fingerprint_is_stable_and_short() -> None:
    assert _short_media_fingerprint("https://example.com/a.jpg") == _short_media_fingerprint(
        "https://example.com/a.jpg"
    )
    assert len(_short_media_fingerprint("https://example.com/a.jpg")) == 10
