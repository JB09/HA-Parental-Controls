"""Content filtering pipeline for Parental Controls.

Pure logic module with no Home Assistant dependencies.
All functions take plain data and return FilterResult decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

from .const import CONTENT_RATINGS, TITLE_PATTERNS


@dataclass
class FilterResult:
    """Result of running the content filter pipeline."""

    action: str  # "allow" or "block"
    reason: str
    layer: int
    should_strike: bool


@dataclass
class MediaInfo:
    """Media attributes extracted from a media_player entity."""

    entity_id: str
    app_name: str
    media_title: str
    media_artist: str
    media_content_type: str


@dataclass
class FilterConfig:
    """Configuration for the filter pipeline."""

    blocked_apps: list[str]
    allowed_apps: list[str]
    blocked_keywords: list[str]
    content_rating_max: str
    music_rating_max: str
    filter_strictness: str
    tracked_apps: list[str]  # lowercase app names in the tracked basket
    tracked_apps_daily_limit: float  # minutes (0 = unlimited)
    media_usage_daily_limit: float  # minutes
    media_usage_start: str  # "HH:MM"
    media_usage_end: str  # "HH:MM"
    openai_enabled: bool
    is_device_locked: bool
    tracked_apps_usage_today: float  # aggregate minutes across tracked apps
    total_usage_today: float  # minutes
    cached_results: dict[str, str]


def _parse_time(time_str: str) -> time:
    """Parse HH:MM string to time object."""
    parts = time_str.split(":")
    return time(int(parts[0]), int(parts[1]))


def _normalize_list(csv_string: str) -> list[str]:
    """Split comma-separated string into normalized lowercase list."""
    return [item.strip().lower() for item in csv_string.split(",") if item.strip()]


def _check_schedule(current_time: time, config: FilterConfig) -> FilterResult | None:
    """Layer 1: Check if current time is within allowed hours."""
    start = _parse_time(config.media_usage_start)
    end = _parse_time(config.media_usage_end)

    if start <= end:
        # Normal range: e.g., 08:00 to 20:00
        if current_time < start or current_time > end:
            return FilterResult(
                action="block",
                reason=f"Outside allowed media usage hours ({config.media_usage_start} - {config.media_usage_end})",
                layer=1,
                should_strike=False,
            )
    else:
        # Overnight range: e.g., 20:00 to 08:00 (allowed overnight)
        if current_time > end and current_time < start:
            return FilterResult(
                action="block",
                reason=f"Outside allowed media usage hours ({config.media_usage_start} - {config.media_usage_end})",
                layer=1,
                should_strike=False,
            )
    return None


def _check_device_locked(config: FilterConfig) -> FilterResult | None:
    """Layer 2: Check if the device is locked due to max strikes."""
    if config.is_device_locked:
        return FilterResult(
            action="block",
            reason="Device is locked due to too many content violations. A parent must unlock it.",
            layer=2,
            should_strike=False,
        )
    return None


def _check_blocked_apps(media: MediaInfo, config: FilterConfig) -> FilterResult | None:
    """Layer 3: Check if the app is on the blocklist."""
    app_lower = media.app_name.lower()
    if not app_lower:
        return None

    for blocked in config.blocked_apps:
        if blocked and blocked == app_lower:
            return FilterResult(
                action="block",
                reason=f"App '{media.app_name}' is on the blocked list",
                layer=3,
                should_strike=True,
            )
    return None


def _check_allowed_apps(media: MediaInfo, config: FilterConfig) -> FilterResult | None:
    """Layer 4: Check if the app is on the allowlist (skip remaining checks)."""
    app_lower = media.app_name.lower()
    if not app_lower:
        return None

    for allowed in config.allowed_apps:
        if allowed and allowed == app_lower:
            return FilterResult(
                action="allow",
                reason=f"App '{media.app_name}' is on the allowed list",
                layer=4,
                should_strike=False,
            )
    return None


def _check_blocked_keywords(
    media: MediaInfo, config: FilterConfig
) -> FilterResult | None:
    """Layer 5: Check if title/artist contains blocked keywords."""
    content = f"{media.media_title} {media.media_artist}".lower()
    if not content.strip():
        return None

    for keyword in config.blocked_keywords:
        if keyword and keyword in content:
            return FilterResult(
                action="block",
                reason=f"Content matched blocked keyword: '{keyword}'",
                layer=5,
                should_strike=True,
            )
    return None


def _build_pattern_list(strictness: str) -> list[str]:
    """Build the combined word list based on strictness level."""
    words: list[str] = []

    # Relaxed level always included
    for category_words in TITLE_PATTERNS.get("relaxed", {}).values():
        words.extend(category_words)

    if strictness in ("moderate", "strict"):
        for category_words in TITLE_PATTERNS.get("moderate", {}).values():
            words.extend(category_words)

    if strictness == "strict":
        for category_words in TITLE_PATTERNS.get("strict", {}).values():
            words.extend(category_words)

    return words


# Pre-compiled regex patterns keyed by strictness level.
# Built lazily on first use so the module loads fast.
_compiled_patterns: dict[str, list[tuple[re.Pattern[str], str]]] = {}


def _get_compiled_patterns(strictness: str) -> list[tuple[re.Pattern[str], str]]:
    """Return pre-compiled (pattern, word) pairs for a strictness level."""
    if strictness not in _compiled_patterns:
        words = _build_pattern_list(strictness)
        compiled: list[tuple[re.Pattern[str], str]] = []
        for word in words:
            escaped = re.escape(word)
            if " " not in word:
                escaped = rf"\b{escaped}\b"
            compiled.append((re.compile(escaped), word))
        _compiled_patterns[strictness] = compiled
    return _compiled_patterns[strictness]


def _check_title_patterns(
    media: MediaInfo, config: FilterConfig
) -> FilterResult | None:
    """Layer 6: Regex-based title pattern analysis for inappropriate content."""
    content = f"{media.app_name} {media.media_title} {media.media_artist}".lower()
    if not content.strip():
        return None

    for pattern, word in _get_compiled_patterns(config.filter_strictness):
        if pattern.search(content):
            return FilterResult(
                action="block",
                reason=f"Title/artist matched inappropriate content pattern: '{word}'",
                layer=6,
                should_strike=True,
            )
    return None


def cache_key(title: str) -> str:
    """Generate a normalized cache key from a media title."""
    return title.lower().strip()[:100]


def _check_cache(media: MediaInfo, config: FilterConfig) -> FilterResult | None:
    """Layer 7: Check if this title has been previously analyzed by OpenAI."""
    if not media.media_title:
        return None

    key = cache_key(media.media_title)
    cached = config.cached_results.get(key)

    if cached == "blocked":
        return FilterResult(
            action="block",
            reason="Content previously flagged by AI analysis (cached)",
            layer=7,
            should_strike=True,
        )
    if cached == "safe":
        return FilterResult(
            action="allow",
            reason="Content previously cleared by AI analysis (cached)",
            layer=7,
            should_strike=False,
        )
    return None


def _check_time_limits(media: MediaInfo, config: FilterConfig) -> FilterResult | None:
    """Layer 8: Check daily usage time limits."""
    app_lower = media.app_name.lower()

    # Tracked apps basket limit (0 = unlimited)
    if (
        config.tracked_apps_daily_limit > 0
        and app_lower in config.tracked_apps
        and config.tracked_apps_usage_today >= config.tracked_apps_daily_limit
    ):
        return FilterResult(
            action="block",
            reason=f"Tracked apps daily limit reached ({config.tracked_apps_daily_limit:.0f} minutes)",
            layer=8,
            should_strike=False,
        )

    # Total media usage limit (0 = unlimited)
    if config.media_usage_daily_limit > 0 and config.total_usage_today >= config.media_usage_daily_limit:
        return FilterResult(
            action="block",
            reason=f"Total daily media usage limit reached ({config.media_usage_daily_limit:.0f} minutes)",
            layer=8,
            should_strike=False,
        )
    return None


def _should_call_openai(media: MediaInfo, config: FilterConfig) -> bool:
    """Layer 9: Determine if OpenAI analysis should be called."""
    return (
        config.openai_enabled
        and len(media.media_title.strip()) > 2
    )


def run_local_filters(
    media: MediaInfo,
    config: FilterConfig,
    current_time: time,
) -> FilterResult | None:
    """Run all local (zero-token) filter layers.

    Returns a FilterResult if a decision was made, or None if OpenAI
    analysis is needed (and enabled).
    """
    # Layer 1: Schedule
    result = _check_schedule(current_time, config)
    if result:
        return result

    # Layer 2: Device locked
    result = _check_device_locked(config)
    if result:
        return result

    # Layer 3: Blocked apps
    result = _check_blocked_apps(media, config)
    if result:
        return result

    # Layer 4: Allowed apps (skip remaining if matched)
    result = _check_allowed_apps(media, config)
    if result:
        return result

    # Layer 5: Blocked keywords
    result = _check_blocked_keywords(media, config)
    if result:
        return result

    # Layer 6: Title pattern analysis
    result = _check_title_patterns(media, config)
    if result:
        return result

    # Layer 7: Cache lookup
    result = _check_cache(media, config)
    if result:
        return result

    # Layer 8: Time limits
    result = _check_time_limits(media, config)
    if result:
        return result

    # Layer 9: Check if OpenAI should be called
    if _should_call_openai(media, config):
        return None  # Signal to caller that OpenAI analysis is needed

    # No issues found, allow
    return FilterResult(
        action="allow",
        reason="Content passed all local checks",
        layer=0,
        should_strike=False,
    )


def build_openai_prompt(
    media: MediaInfo,
    content_rating_max: str,
    music_rating_max: str,
) -> str:
    """Build the OpenAI classification prompt for a media item."""
    return (
        "Classify this media content as 'safe' or 'blocked' (one word only). "
        "Consider: (1) Is the song/video NAME itself inappropriate, vulgar, "
        "suggestive, or nonsensical/troll content for a child? "
        "(2) Is the artist known for explicit content? "
        f"(3) Content rating max: {content_rating_max}. "
        f"Music rating: {music_rating_max}. "
        f"App: {media.app_name}. Title: {media.media_title}. "
        f"Artist: {media.media_artist}."
    )


def parse_openai_response(response_text: str) -> FilterResult:
    """Parse the OpenAI single-word response into a FilterResult."""
    cleaned = response_text.strip().lower()

    if "blocked" in cleaned:
        return FilterResult(
            action="block",
            reason="AI content analysis flagged as inappropriate",
            layer=9,
            should_strike=True,
        )

    # Default to safe if response is unclear (avoid false positives)
    return FilterResult(
        action="allow",
        reason="AI content analysis cleared as safe",
        layer=9,
        should_strike=False,
    )
