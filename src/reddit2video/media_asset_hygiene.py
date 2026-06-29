from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Union
from urllib.parse import urlparse


JsonLike = Union[Mapping[str, Any], object]


COMMERCE_OR_LOW_TRUST_DOMAINS = (
    "amazon.",
    "amzn.to",
    "aliexpress.",
    "ebay.",
    "etsy.",
    "shopee.",
    "temu.",
    "walmart.",
    "walgreens.",
    "target.",
    "alamy.",
    "dreamstime.",
    "depositphotos.",
    "shutterstock.",
    "stock.adobe.",
    "istockphoto.",
    "gettyimages.",
    "envato.",
    "envatousercontent.",
    "123rf.",
    "vecteezy.",
    "freepik.",
    "pngtree.",
    "yopriceville.",
    "clipart",
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "medium.com",
    "substack.com",
    "facebook.com",
    "threads.com",
    "liketk.it",
    "packsia.com",
    "amzn.to",
    "stockfood.com",
    "toppng.com",
    "designbundles.net",
    "templated.io",
    "makereceipt.com",
    "next.us",
    "kroger.com",
    "fredmeyer.com",
    "frontroyalpregnancy.org",
    "stockfood.com",
    "momentumcoffee.org",
    "lexiscleankitchen.com",
    "thegirlonbloor.com",
    "lovingitvegan.com",
    "propersyrup.com",
    "yahoo.com",
    "people.com",
    "worldmarket.com",
    "creativemarket.com",
    "eatingwell.com",
    "allrecipes.com",
    "seriouseats.com",
    "freeimages.co.uk",
    "npr.org",
    "californiagripsocks.com",
    "webstaurantstore.com",
    "nutrisystem.com",
    "eater.com",
    "huffpost.com",
    "huffingtonpost.com",
    "plus.unsplash.com",
    "uploaded by user",
)


def publication_asset_hygiene_rejection_reason(asset: JsonLike, *, slot: Mapping[str, Any] | None = None) -> str | None:
    """Reject media candidates that make a rendered video feel scraped or template-like.

    This is intentionally not a beauty score. It catches explicit editorial
    defects that should not reach a publishable render: reaction GIF providers,
    screenshot/interface assets, ecommerce/product-card results, creator CTA
    captions, and clipart/vector/template graphics.
    """

    provider = _text_field(asset, "provider").lower()
    title = _text_field(asset, "title")
    query = _text_field(asset, "query")
    media_url = _text_field(asset, "media_url") or _text_field(asset, "src") or _text_field(asset, "url")
    thumbnail_url = _text_field(asset, "thumbnail_url")
    page_url = _text_field(asset, "page_url") or _text_field(asset, "source_url")
    metadata = _metadata(asset)

    slot_text = _slot_text(slot)
    title_text = _clean_text(title)
    query_text = _clean_text(query)
    haystack = _clean_text(
        " ".join(
            value
            for value in (
                title,
                query,
                page_url,
                media_url,
                thumbnail_url,
                _metadata_text(metadata),
                slot_text,
            )
            if value
        )
    )
    commerce_haystack = _commerce_haystack_for_domain(
        haystack,
        page_url,
        media_url,
        thumbnail_url,
        metadata=metadata,
    )

    file_reason = _publication_file_format_rejection_reason(asset)
    if file_reason:
        return file_reason
    if provider == "giphy":
        return "reaction_gif_provider"
    if _matches_any(haystack, (r"\bmeme\b", r"\breaction\s+gif\b", r"\bgif\b")) and "gif" not in slot_text:
        return "meme_or_reaction_asset"
    if _matches_any(
        haystack,
        (
            r"\bscreenshot\b",
            r"\bscreen\s*shot\b",
            r"\bphone\s*screen\b",
            r"\bapp\s*screen\b",
            r"\binterface\b",
            r"\bdashboard\b",
            r"\bui\s*kit\b",
            r"\breddit\b",
            r"\btweet\b",
            r"\btwitter\b",
            r"\bthreads\s*post\b",
            r"\bfacebook\s*post\b",
        ),
    ):
        return "interface_or_screenshot_asset"
    if _matches_any(
        haystack,
        (
            r"\bquote\s*(?:card|poster|post|template)?\b",
            r"\binfographic\b",
            r"\bworksheet\b",
            r"\btemplate\b",
            r"\bposter\b",
            r"\bflyer\b",
            r"\bflashcard\b",
            r"\bbusiness\s*card\b",
            r"\bdoctor\s*card\b",
            r"\bmedical\s*card\b",
            r"\bnotes?\s*(?:app|template)\b",
        ),
    ):
        return "text_or_template_asset"
    if _matches_any(
        haystack,
        (
            r"\bclip\s*art\b",
            r"\bclipart\b",
            r"\btransparent\s+png\b",
            r"\bpremium\s+vector\b",
            r"\bvector\b",
            r"\bstock\s+illustrations?\b",
            r"\bfree\s+images?\s+and\s+transparent\b",
            r"\bmockup\b",
            r"\bicon\s*(?:set|pack|video|animation)?\b",
        ),
    ):
        return "clipart_or_stock_graphic_asset"
    if (
        _commerce_or_low_trust_domain(page_url, media_url, thumbnail_url, metadata=metadata)
        or _product_or_marketing_landing_page(page_url, metadata=metadata)
        or _matches_any(
        commerce_haystack,
        (
            r"\bamazon\s*(?:shop|finds?|store|product)?\b",
            r"\bwalgreens\b",
            r"\bshopee\b",
            r"\bonline\s+store\b",
            r"\bfree\s+shipping\b",
            r"\bshop\s+now\b",
            r"\bbuy\s+it\b",
            r"\bproduct\s+(?:listing|photo|page)\b",
            r"\blicense\s+images?\b",
            r"\bworkout\s+set\b",
            r"\btracksuit\s+set\b",
            r"\boutfit\s+ideas?\b",
            r"\baccessory\s+essentials\b",
            r"\badd\s+to\s+cart\b",
            r"\b\d+\s*(?:pack|pcs|ct|count|dram|ml|mg)\b",
            r"\b(?:tablets?|capsules?|gummies?)\b",
            r"\b(?:pill|supplement|medicine|vitamin|serum)\s+(?:bottles?|jars?|vials?|containers?)\b",
            r"\b(?:white|amber|green|blue|clear)\s+(?:pill|supplement|plastic|glass)\s+(?:bottles?|jars?|vials?)\b",
            r"\b(?:bottles?|jars?|vials?)\s+(?:with|w/)\s+(?:white|black)?\s*caps?\b",
            r"\bglass\s+vitamin\s+jars?\b",
            r"\btespack\b",
            r"\bpackaging\b",
            r"\bproduct\s+mockup\b",
            r"\b(?:bottles?|jars?|vials?|containers?)\s+(?:mockup|packaging|product)\b",
            r"\bbox\s+sticker\s+mockup\b",
            r"\bfree\s+stock\s+photo\b",
            r"\bfree\s+stock\s+image\b",
            r"\bfree\s+.*\breceipt\b",
            r"\breceipt\s+generator\b",
            r"\bonline\s+menu\b",
            r"\b(?:buy|set)\s+of\s+\d+\b",
            r"\bappetizer\s+plate\b",
            r"\bfree\s+image\s+of\b",
            r"\bstock\s+photo(?:graphy)?\b",
            r"\bdownload\s+free\b",
            r"\bstock\s+illustrations?\b",
            r"\broyalty[-\s]?free\b",
            r"\blicensable\b",
            r"\b\d+\s*cc\b",
            r"\bwith\s+(?:black|white)?\s*caps?\b",
            r"\bby\s+specialty\s+bottle\b",
            r"\blab\s+coat\b",
            r"\bstorage\s+ideas?\b",
            r"\bsecure\s+storage\b",
        ),
        )
    ):
        return "commerce_or_low_trust_asset"
    if _social_campaign_title(title_text):
        return "social_caption_campaign_asset"
    if _matches_any(
        title_text,
        (
            r"\blink\s+in\s+bio\b",
            r"\bcomment\s+.*\b(?:link|links|code|shop)\b",
            r"\bfollow\s+@",
            r"\bswipe\s+(?:up|and|to)\b",
            r"\buse\s+code\b",
            r"\b#\s*ad\b",
            r"\bsponsored\b",
        ),
    ):
        return "creator_cta_asset"
    if _low_information_nonempty_title(provider=provider, title=title):
        return "low_information_title_asset"
    if _matches_any(query_text, (r"\bmeme\b", r"\breaction\b", r"\bgif\b")):
        return "brief_requests_meme_or_gif"
    if _query_title_mismatch(provider=provider, query=query_text, title=title_text):
        return "query_title_mismatch_asset"
    return None


def _commerce_haystack_for_domain(
    haystack: str,
    *urls: str,
    metadata: Mapping[str, Any],
) -> str:
    if not _trusted_open_media_domain(*urls, metadata=metadata):
        return haystack
    return re.sub(
        r"\b(?:free\s+stock\s+photo|free\s+stock\s+image|stock\s+photo(?:graphy)?|download\s+free|royalty[-\s]?free)\b",
        " ",
        haystack,
        flags=re.IGNORECASE,
    )


def _trusted_open_media_domain(*urls: str, metadata: Mapping[str, Any]) -> bool:
    candidates = list(urls)
    for key in ("domain", "link", "source_url"):
        value = metadata.get(key)
        if isinstance(value, str):
            candidates.append(value)
    for value in candidates:
        host = urlparse(str(value or "")).netloc.lower()
        if not host and value:
            host = str(value).lower()
        if any(domain in host for domain in ("pexels.com", "unsplash.com")):
            return True
    return False


def _publication_file_format_rejection_reason(asset: JsonLike) -> str | None:
    metadata = _metadata(asset)
    content_type = (
        _text_field(asset, "local_content_type")
        or _text_field(asset, "content_type")
        or str(metadata.get("local_content_type") or metadata.get("content_type") or "")
    ).strip().lower()
    if content_type in {
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        "application/mpegurl",
        "audio/mpegurl",
        "audio/x-mpegurl",
    }:
        return "unsupported_playlist_asset"
    if content_type == "image/avif":
        return "unsupported_image_format"
    for key in (
        "public_path",
        "media_public_path",
        "local_path",
        "path",
        "downloaded_path",
        "file_path",
    ):
        value = _text_field(asset, key)
        lowered = value.lower().split("?", 1)[0]
        if lowered.endswith((".m3u", ".m3u8")):
            return "unsupported_playlist_asset"
        if lowered.endswith(".avif") or "enc_avif" in value.lower() or "format=avif" in value.lower():
            return "unsupported_image_format"
    for key in ("media_url", "thumbnail_url"):
        value = _text_field(asset, key)
        lowered = value.lower().split("?", 1)[0]
        if lowered.endswith(".avif") or "enc_avif" in value.lower() or "format=avif" in value.lower():
            return "unsupported_image_format"
    return None


def publication_render_asset_hygiene_rejection_reason(
    asset: JsonLike, *, slot: Mapping[str, Any] | None = None
) -> str | None:
    """Stricter final-render hygiene for legacy scraped media.

    The resolver can keep a broad candidate pool for diagnostics and fallback.
    Final publication renders are less forgiving: ambiguous Pinterest/social
    captions, creator handles, short titles, and CTA-like clips should yield to
    the generated semantic visual layer instead of appearing in the MP4.
    """

    base_reason = publication_asset_hygiene_rejection_reason(asset, slot=slot)
    if base_reason:
        return base_reason
    provider = _text_field(asset, "provider").lower()
    title = _text_field(asset, "title")
    title_text = _clean_text(title)
    if provider == "pinterest":
        if _strict_low_information_title(title):
            return "render_low_information_pinterest_asset"
        if len(title_text) > 220:
            return "render_long_creator_caption_asset"
        if _matches_any(
            title_text,
            (
                r"#",
                r"\b@\w+",
                r"\blink\s+in\s+(?:our|my|the)?\s*bio\b",
                r"\bcomment\s+[\"']?[a-z0-9_-]+[\"']?\b",
                r"\bshop\s+now\b",
                r"\bclick\s+the\s+link\b",
                r"\bcall\s+us\b",
                r"\breels?\b",
                r"\bviral\b",
                r"\bfyp\b",
                r"\bcanva\b",
                r"\bcapcut\b",
                r"\bmidjourney\b",
                r"\bpov\b",
                r"\basap\b",
                r"\bfaceless\s+marketing\b",
                r"\bdigital\s+marketing\b",
                r"\bcontent\s+(?:creator|marketing|strategy)\b",
                r"\bpodcast\b",
                r"\b(?:top|best)\s+\d+\b",
                r"\b\d+\s+best\b",
                r"\b(?:calorie|macro|diet|fitness|weight\s*loss)\s+(?:counter|counting|tracker|tracking)?\s*apps?\b",
                r"\bapps?\s+to\s+(?:build|lose|track|count|manage)\b",
                r"\bhow\s+to\s+(?:make|cook|bake|prepare|create)\b",
                r"\b(?:recipe|recipes)\b",
                r"\beasy\s+(?:blender|all[-\s]?butter|flaky|homemade|healthy)\b",
                r"\b(?:pie\s+crust|puff\s+pastry|green\s+goddess|salad\s+bowls?|veggie\s+salad|chicken\s+salad|korean\s+bbq|blender\s+.*almond\s+milk)\b",
                r"\bhow\s+to\s+(?:refuse|use|choose|order)\b",
                r"\b(?:breakfast|lunch|dinner|dessert)\s+(?:recipe|ideas?)\b",
                r"\b(?:health\s+habit|nutritionist\s+decodes|bans\s+woman|half\s+eaten\s+cake|abandoned\s+ice\s+cream\s+shop|galette\s+des\s+rois|dinner\s+plate\s+gets|perfect\s+salad\s+bowl)\b",
                r"\bupgrade\s+your\s+(?:sandwich|bread|pastry|croissant)\b",
                r"\blighting\s+fixtures?\b",
                r"\b(?:pendant|ceiling|wall|kitchen)\s+lighting\b",
                r"\bbody\s+reset\b",
                r"\bcarb\s+cycling\b",
                r"\bfat\s+loss\s+simplified\b",
                r"\bhourglass\s+shape\b",
                r"\bfull[-\s]?body\s+workout\b",
                r"\bai\s+art\s+motion\b",
                r"\babstract\s+depiction\b",
                r"\b3d\s+(?:heart|brain|body|organ)\s+models?\b",
                r"\bmedically\s+accurate\s+3d\b",
                r"\b(?:cell|cells|bacterial|bacteria).{0,80}\bjellyfish\s+dna\b",
                r"\bcrystal\s+bricks?\b",
                r"\bhigh\s+transparency\b",
                r"\buntutorial\b",
                r"\bmakeover\b",
                r"\bsmart\s+home\b",
                r"\bwrench\b",
                r"\b(?:living|dining|kitchen|coffee\s*shop|cafe)\s*(?:\+|and)?\s*(?:interior|design|layout|renovation)\b",
                r"\b(?:living|dining|kitchen)\b.{0,80}\b(?:interior|design|layout|renovation)\b",
                r"\b(?:interior|kitchen|dining|living)\s*(?:design|decor|layout|renovation)\b",
                r"\bwill\s+you\s+be\b",
                r"\bstorage\s+ideas?\b",
                r"\bperfume\b",
                r"\bchanel\b",
                r"\bskincare\b",
                r"\bskin\s+hydration\b",
                r"\bjacuzzi\b",
                r"\bbrain[’']?s\s+new\s+best\s+friend\b",
                r"\bmedshrum\b",
                r"\blion[’']?s\s+mane\b",
                r"\bmushroom\s+powder\b",
                r"\biv\s+drip\b",
                r"\bhome\s+doctor\b",
                r"\bscrolling\s+addiction\b",
                r"\btag\s+your\b",
                r"\bchallenge\b",
                r"\bcontent\s+edukasi\b",
                r"\bwhat\s+high\s+blood\s+sugar\s+does\b",
                r"\banatomy\s+of\s+the\s+heart\b",
                r"\bheart\s+rate\s+monitor\b",
                r"\bekg\b",
                r"\bcell\s+division\b",
                r"\bmitosis\b",
                r"\bbrain\s+parts\b",
                r"\bneural\s+fire\b",
                r"\bx[-\s]?ray\b",
                r"\bcgi\b",
                r"\bvisuali[sz]ation\b",
                r"\banimation\b",
                r"\bhave\s+fun\s+and\s+be\s+happy\b",
                r"\b(?:be|stay|choose|feel)\s+happy\b",
                r"\bgood\s+vibes?\b",
                r"\bpositive\s+vibes?\b",
                r"\binspire\s+encourage\s+empower\b",
            ),
        ):
            return "render_creator_or_social_asset"
        if "christmas" in title_text and "christmas" not in _slot_text(slot):
            return "render_creator_or_social_asset"
    return None


def _text_field(asset: JsonLike, key: str) -> str:
    if isinstance(asset, Mapping):
        value = asset.get(key)
    else:
        value = getattr(asset, key, "")
    return str(value or "").strip() if isinstance(value, (str, int, float)) else ""


def _metadata(asset: JsonLike) -> Mapping[str, Any]:
    if isinstance(asset, Mapping):
        value = asset.get("metadata")
    else:
        value = getattr(asset, "metadata", {})
    return value if isinstance(value, Mapping) else {}


def _metadata_text(metadata: Mapping[str, Any]) -> str:
    values: list[str] = []
    for key in ("domain", "link", "source_url", "source_tag", "image_key", "api_scope", "pin_id", "giphy_id"):
        value = metadata.get(key)
        if isinstance(value, (str, int, float)):
            values.append(str(value))
    available = metadata.get("available_image_keys")
    if isinstance(available, list):
        values.extend(str(item) for item in available if isinstance(item, (str, int, float)))
    return " ".join(values)


def _slot_text(slot: Mapping[str, Any] | None) -> str:
    if not isinstance(slot, Mapping):
        return ""
    values: list[str] = []
    for key in (
        "kind",
        "role",
        "girly_asset_role",
        "source_strategy",
        "visual_prompt",
        "search_query_en",
        "search_query_ru",
    ):
        value = slot.get(key)
        if isinstance(value, (str, int, float)):
            values.append(str(value))
    return _clean_text(" ".join(values))


def _commerce_or_low_trust_domain(*urls: str, metadata: Mapping[str, Any]) -> bool:
    candidates = list(urls)
    for key in ("domain", "link", "source_url"):
        value = metadata.get(key)
        if isinstance(value, str):
            candidates.append(value)
    for value in candidates:
        host = urlparse(str(value or "")).netloc.lower()
        if not host and value:
            host = str(value).lower()
        if any(domain in host for domain in COMMERCE_OR_LOW_TRUST_DOMAINS):
            return True
    return False


def _product_or_marketing_landing_page(page_url: str, *, metadata: Mapping[str, Any]) -> bool:
    candidates = [page_url]
    for key in ("link", "source_url"):
        value = metadata.get(key)
        if isinstance(value, str):
            candidates.append(value)
    for value in candidates:
        parsed = urlparse(str(value or ""))
        path = parsed.path.lower()
        query = parsed.query.lower()
        if _matches_any(
            path,
            (
                r"/products?/",
                r"/collections?/",
                r"/shop(?:/|$)",
                r"/store(?:/|$)",
                r"/cart(?:/|$)",
            ),
        ):
            return True
        if _matches_any(query, (r"\butm_(?:campaign|content|medium|source|term)=", r"\bvariant=", r"\bsku=")):
            return True
    return False


def _social_campaign_title(title: str) -> bool:
    if not title:
        return False
    hashtag_count = title.count("#")
    if hashtag_count >= 2:
        return True
    if hashtag_count >= 1 and _matches_any(title, (r"@", r"\bfyp\b", r"\btiktok\b", r"\breels?video\b", r"\bshop\b")):
        return True
    return _matches_any(
        title,
        (
            r"\b(?:tiktok|studytok|reels?video|instagrammademebuyit|amazonfinds)\b",
            r"@\w+.*#",
            r"#.*@\w+",
        ),
    )


def _query_title_mismatch(*, provider: str, query: str, title: str) -> bool:
    if provider not in {"pinterest", "serper_images", "brightdata_google_images", "wikimedia_commons"}:
        return False
    if not query or not title:
        return False
    query_tokens = _content_tokens(query)
    if len(query_tokens) < 2:
        return False
    title_tokens = _content_tokens(title)
    if not title_tokens:
        return bool(re.search(r"[^\W\d_]", title, flags=re.UNICODE) and len(title) >= 18)
    expanded_query = _expand_tokens(query_tokens)
    expanded_title = _expand_tokens(title_tokens)
    return not bool(expanded_query & expanded_title)


def _low_information_nonempty_title(*, provider: str, title: str) -> bool:
    if provider not in {"pinterest", "serper_images", "brightdata_google_images"}:
        return False
    if not str(title or "").strip():
        return False
    return not bool(re.search(r"[a-zа-яё0-9]", title, flags=re.IGNORECASE))


def _strict_low_information_title(title: str) -> bool:
    clean = str(title or "").strip()
    if not clean:
        return True
    if not re.search(r"[a-zа-яё0-9]", clean, flags=re.IGNORECASE):
        return True
    return len(_content_tokens(clean)) < 2 and len(clean) < 24


def _content_tokens(text: str) -> set[str]:
    stopwords = {
        "aesthetic",
        "photo",
        "video",
        "footage",
        "vertical",
        "background",
        "broll",
        "girl",
        "girls",
        "woman",
        "women",
        "person",
        "people",
        "healthy",
        "clean",
        "closeup",
        "casual",
        "lifestyle",
        "minimalist",
        "wellness",
        "stock",
        "free",
        "image",
        "images",
    }
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9]+", text.lower())
        if len(token) >= 4 and token not in stopwords
    }


def _expand_tokens(tokens: set[str]) -> set[str]:
    groups = (
        {"coffee", "latte", "espresso", "matcha", "cafe"},
        {"pastry", "croissant", "muffin", "galette", "bakery", "cake", "bread"},
        {"sauna", "bath", "bathroom", "bathtub", "jacuzzi", "spa", "shower"},
        {"ice", "cold", "plunge", "frozen"},
        {"supplement", "vitamin", "pill", "capsule", "bottle", "jar"},
        {"desk", "laptop", "study", "work", "office"},
        {"fitness", "workout", "pilates", "gym", "cardio", "exercise"},
        {"receipt", "budget", "price", "money", "store"},
        {"lab", "laboratory", "scientist", "doctor", "clinic", "medical"},
        {"brain", "stress", "nerve", "neuro"},
        {"heart", "blood", "pressure", "vessel"},
        {"orange", "citrus", "slice"},
        {"tea", "chamomile", "cup"},
        {"bedroom", "bed", "sleep"},
        {"walk", "walking", "shoes", "park", "path"},
    )
    expanded = set(tokens)
    for group in groups:
        if expanded & group:
            expanded.update(group)
    return expanded


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.S) for pattern in patterns)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("_", " ")).strip().lower()
