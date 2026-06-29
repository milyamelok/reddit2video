from __future__ import annotations

from reddit2video.media_asset_hygiene import (
    publication_asset_hygiene_rejection_reason,
    publication_render_asset_hygiene_rejection_reason,
)


def test_render_hygiene_rejects_obvious_pinterest_app_listicle() -> None:
    reason = publication_render_asset_hygiene_rejection_reason(
        {
            "provider": "pinterest",
            "query": "calorie counter nutrition label video",
            "title": "5 Best Free Calorie Counting Apps to Build Muscle and Lose Fat - 2024",
            "media_url": "https://v1.pinimg.com/videos/iht/hls/calories.m3u8",
            "metadata": {"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/calories.m3u8"},
        },
        slot={"kind": "video", "search_query_en": "calorie counter nutrition label video"},
    )

    assert reason == "render_creator_or_social_asset"


def test_render_hygiene_rejects_obvious_pinterest_tutorial_or_marketing_clip() -> None:
    for title in (
        "Minimal Coffee Videos for Faceless Marketing",
        "How to Make Almond Milk",
        "Easy Blender Strawberry Almond Milk",
        "Easy All-Butter Flaky Pie Crust",
        "Green Goddess Salad Bowls",
        "Korean BBQ Chicken Salad",
        "Galette des Rois (French Kings' Cake)",
        "How to Refuse Food Politely, According to an Expert",
        "Create a Restaurant Receipt - Free Restaurant Receipt Receipt Generator",
        "The Coffee Walk: Your Simplest New Health Habit",
        "Momentum Coffee Online Menu",
        "Hand Painted Croissant Figural Appetizer Plate",
        "Free image of Half eaten chocolate sponge cake with knife",
        "Kitchen Lighting Fixtures",
        "christmas cafe aesthetic ☕️🤎✨",
        "Living + Dining + Kitchen in ONE sleek design!",
        "Upgrade your sandwich bread with this amazing croissant loaf",
    ):
        reason = publication_render_asset_hygiene_rejection_reason(
            {
                "provider": "pinterest",
                "query": "aesthetic cafe video",
                "title": title,
                "media_url": "https://v1.pinimg.com/videos/iht/hls/clip.m3u8",
                "metadata": {"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/clip.m3u8"},
            },
            slot={"kind": "video", "search_query_en": "aesthetic cafe video"},
        )

        assert reason is not None


def test_hygiene_rejects_social_laundered_pinterest_sources() -> None:
    for domain in (
        "instagram.com",
        "tiktok.com",
        "youtube.com",
        "medium.com",
        "substack.com",
        "facebook.com",
        "threads.com",
        "liketk.it",
        "packsia.com",
        "amzn.to",
        "stockfood.com",
        "toppng.com",
        "templated.io",
        "makereceipt.com",
        "next.us",
        "people.com",
        "allrecipes.com",
        "seriouseats.com",
        "npr.org",
        "californiagripsocks.com",
        "webstaurantstore.com",
        "nutrisystem.com",
        "eater.com",
        "huffpost.com",
        "huffingtonpost.com",
        "Uploaded by user",
    ):
        reason = publication_asset_hygiene_rejection_reason(
            {
                "provider": "pinterest",
                "query": "aesthetic cafe video",
                "title": "soft cafe broll",
                "media_url": "https://v1.pinimg.com/videos/iht/hls/clip.m3u8",
                "metadata": {"domain": domain, "video_hls_url": "https://v1.pinimg.com/videos/iht/hls/clip.m3u8"},
            },
            slot={"kind": "video", "search_query_en": "aesthetic cafe video"},
        )

        assert reason == "commerce_or_low_trust_asset"


def test_hygiene_allows_trusted_open_media_free_stock_title_format() -> None:
    pexels_reason = publication_asset_hygiene_rejection_reason(
        {
            "provider": "serper_images",
            "query": "pastry plate pexels",
            "title": "Puff Pastry Served on Plate · Free Stock Photo",
            "page_url": "https://www.pexels.com/photo/puff-pastry-served-on-plate-18954039/",
            "media_url": "https://images.pexels.com/photos/18954039/pexels-photo-18954039.jpeg",
            "width": 1200,
            "height": 900,
            "metadata": {"domain": "www.pexels.com"},
        },
        slot={"kind": "image", "role": "subject", "search_query_en": "pastry plate"},
    )
    random_reason = publication_asset_hygiene_rejection_reason(
        {
            "provider": "serper_images",
            "query": "pastry plate",
            "title": "Puff Pastry Served on Plate · Free Stock Photo",
            "page_url": "https://example-stock.test/pastry",
            "media_url": "https://example-stock.test/pastry.jpg",
            "width": 1200,
            "height": 900,
            "metadata": {"domain": "example-stock.test"},
        },
        slot={"kind": "image", "role": "subject", "search_query_en": "pastry plate"},
    )

    assert pexels_reason is None
    assert random_reason == "commerce_or_low_trust_asset"


def test_hygiene_rejects_unsplash_plus_premium_watermarked_assets() -> None:
    reason = publication_asset_hygiene_rejection_reason(
        {
            "provider": "serper_images",
            "query": "bakery display",
            "title": "Vintage Bakery Pictures | Download Free Images on Unsplash",
            "page_url": "https://unsplash.com/s/photos/vintage-bakery",
            "media_url": "https://plus.unsplash.com/premium_photo-1665669263531-cdcbe18e7fe4?fm=jpg",
            "width": 3000,
            "height": 1881,
            "metadata": {"domain": "unsplash.com"},
        },
        slot={"kind": "image", "role": "subject", "search_query_en": "bakery display"},
    )
    clean_reason = publication_asset_hygiene_rejection_reason(
        {
            "provider": "serper_images",
            "query": "pastries",
            "title": "Pastries Pictures | Download Free Images on Unsplash",
            "page_url": "https://unsplash.com/s/photos/pastries",
            "media_url": "https://images.unsplash.com/photo-1583338917451-face2751d8d5?fm=jpg",
            "width": 3000,
            "height": 4500,
            "metadata": {"domain": "unsplash.com"},
        },
        slot={"kind": "image", "role": "subject", "search_query_en": "pastries"},
    )

    assert reason == "commerce_or_low_trust_asset"
    assert clean_reason is None


def test_render_hygiene_rejects_obvious_external_template_or_product_videos() -> None:
    for title in (
        "AI ART MOTION: An abstract depiction of the human brain",
        "Dumbbell Full-Body Hourglass Shape Workout",
        "Medically accurate 3d heart model",
        "high transparency Ice pattern crystal bricks",
        "Finnish sauna UNtutorial",
        "The 120 Tooth is the Perfect wrench for very tight spaces!",
        "Einfaches Schlafzimmer-Makeover",
        "Glowing Cells Made With Jellyfish DNA",
    ):
        reason = publication_render_asset_hygiene_rejection_reason(
            {
                "provider": "pinterest",
                "query": "sauna science",
                "title": title,
                "media_url": "https://v1.pinimg.com/videos/iht/hls/clip.m3u8",
                "metadata": {"video_hls_url": "https://v1.pinimg.com/videos/iht/hls/clip.m3u8"},
            },
            slot={"kind": "video", "search_query_en": "sauna science"},
        )

        assert reason is not None
