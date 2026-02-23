"""Central coordinator for Parental Controls.

Manages state tracking, strike counts, OpenAI cache, and
orchestrates the content filter pipeline + blocking actions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.const import STATE_PLAYING
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    CONF_ALLOWED_APPS,
    CONF_AUDIO_DAILY_LIMIT,
    CONF_BLOCKED_APPS,
    CONF_BLOCKED_KEYWORDS,
    CONF_CONTENT_RATING_MAX,
    CONF_FILTER_STRICTNESS,
    CONF_MAX_STRIKES,
    CONF_MONITORED_PLAYERS,
    CONF_MUSIC_RATING_MAX,
    CONF_OPENAI_AGENT_ID,
    CONF_OPENAI_ENABLED,
    CONF_MEDIA_USAGE_DAILY_LIMIT,
    CONF_MEDIA_USAGE_END,
    CONF_MEDIA_USAGE_START,
    CONF_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
    CONF_PUSH_NOTIFY_ENABLED,
    CONF_PUSH_NOTIFY_SERVICES,
    CONF_TTS_ENABLED,
    CONF_TTS_SERVICE,
    CONF_TRACKED_APPS,
    CONF_TRACKED_APPS_DAILY_LIMIT,
    CONF_USAGE_LIMIT_MODE,
    CONF_VIDEO_DAILY_LIMIT,
    DEFAULT_ALLOWED_APPS,
    DEFAULT_AUDIO_DAILY_LIMIT,
    DEFAULT_BLOCKED_APPS,
    DEFAULT_BLOCKED_KEYWORDS,
    DEFAULT_CONTENT_RATING,
    DEFAULT_FILTER_STRICTNESS,
    DEFAULT_MAX_STRIKES,
    DEFAULT_MUSIC_RATING,
    DEFAULT_OPENAI_AGENT_ID,
    DEFAULT_OPENAI_ENABLED,
    DEFAULT_MEDIA_USAGE_DAILY_LIMIT,
    DEFAULT_MEDIA_USAGE_END,
    DEFAULT_MEDIA_USAGE_START,
    DEFAULT_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
    DEFAULT_PUSH_NOTIFY_ENABLED,
    DEFAULT_PUSH_NOTIFY_SERVICES,
    DEFAULT_TTS_ENABLED,
    DEFAULT_TTS_SERVICE,
    DEFAULT_TRACKED_APPS,
    DEFAULT_TRACKED_APPS_DAILY_LIMIT,
    DEFAULT_USAGE_LIMIT_MODE,
    DEFAULT_VIDEO_DAILY_LIMIT,
    ACTION_UNLOCK_DEVICE,
    DOMAIN,
    LOCKOUT_COOLDOWN_SECONDS,
    OPENAI_CACHE_MAX_ENTRIES,
)
from .content_filter import (
    FilterConfig,
    FilterResult,
    MediaInfo,
    build_openai_prompt,
    cache_key,
    classify_media_type,
    parse_openai_response,
    run_local_filters,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


class ParentalControlsCoordinator:
    """Central coordinator for parental controls state and logic."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.config_entry = config_entry

        # Strike counters: entity_id -> count
        self._strikes: dict[str, int] = {}
        # OpenAI result cache: normalized_title -> "safe"/"blocked"
        self._openai_cache: dict[str, str] = {}
        # Usage tracking: entity_id -> minutes played today
        self._usage_today: dict[str, float] = {}
        # Per-app usage: entity_id -> {app_name_lower: minutes}
        self._app_usage_today: dict[str, dict[str, float]] = {}
        # Last block timestamps for cooldown: entity_id -> datetime
        self._last_block_time: dict[str, datetime] = {}
        # Last known playing start: entity_id -> datetime (for usage calc)
        self._play_start: dict[str, datetime] = {}
        # Device enabled state: entity_id -> bool
        self._device_enabled: dict[str, bool] = {}
        # Parent mode: entity_id -> bool (bypasses filtering + tracking)
        self._parent_mode: dict[str, bool] = {}
        # Global master toggle
        self._global_enabled: bool = True
        # Per-device media type usage: entity_id -> {"audio": min, "video": min}
        self._media_type_usage_today: dict[str, dict[str, float]] = {}
        # Media class at play start: entity_id -> "audio" or "video"
        self._play_media_class: dict[str, str] = {}
        # Runtime settings: mutable overrides for config entry options.
        # Written by number/select entities, checked before config_entry.options.
        # Persisted to config entry only on unload to avoid reload loops.
        self._runtime_settings: dict[str, Any] = {}
        # Entity update callbacks
        self._listeners: list[Any] = []

    @property
    def monitored_players(self) -> list[str]:
        """Return list of monitored media_player entity IDs."""
        return self._get_option(CONF_MONITORED_PLAYERS, [])

    def _get_option(self, key: str, default: Any) -> Any:
        """Get a config value: runtime_settings > options > data > default."""
        if key in self._runtime_settings:
            return self._runtime_settings[key]
        if key in self.config_entry.options:
            return self.config_entry.options[key]
        return self.config_entry.data.get(key, default)

    def set_runtime_setting(self, key: str, value: Any) -> None:
        """Set a runtime setting (no config entry update, no reload)."""
        self._runtime_settings[key] = value
        # Notify entities so they reflect the new value
        for entity_id in self.monitored_players:
            self._notify_entity_update(entity_id)

    def persist_runtime_settings(self) -> None:
        """Persist runtime settings to config entry options.

        Called during async_unload_entry so values survive restarts
        without triggering a reload during normal operation.
        """
        if not self._runtime_settings:
            return
        new_options = dict(self.config_entry.options)
        new_options.update(self._runtime_settings)
        self.hass.config_entries.async_update_entry(
            self.config_entry, options=new_options
        )

    def _get_blocked_apps(self) -> list[str]:
        """Get normalized blocked apps list."""
        raw = self._get_option(CONF_BLOCKED_APPS, DEFAULT_BLOCKED_APPS)
        return [a.strip().lower() for a in raw.split(",") if a.strip()]

    def _get_allowed_apps(self) -> list[str]:
        """Get normalized allowed apps list."""
        raw = self._get_option(CONF_ALLOWED_APPS, DEFAULT_ALLOWED_APPS)
        return [a.strip().lower() for a in raw.split(",") if a.strip()]

    def _get_blocked_keywords(self) -> list[str]:
        """Get normalized blocked keywords list."""
        raw = self._get_option(CONF_BLOCKED_KEYWORDS, DEFAULT_BLOCKED_KEYWORDS)
        return [k.strip().lower() for k in raw.split(",") if k.strip()]

    def _get_tracked_apps(self) -> list[str]:
        """Get normalized tracked apps list."""
        raw = self._get_option(CONF_TRACKED_APPS, DEFAULT_TRACKED_APPS)
        return [a.strip().lower() for a in raw.split(",") if a.strip()]

    # --- Strike Management ---

    def get_strikes(self, entity_id: str) -> int:
        """Get current strike count for a device."""
        return self._strikes.get(entity_id, 0)

    def get_max_strikes(self) -> int:
        """Get the configured max strikes."""
        return self._get_option(CONF_MAX_STRIKES, DEFAULT_MAX_STRIKES)

    def is_device_locked(self, entity_id: str) -> bool:
        """Check if a device is locked due to max strikes.

        Returns False when max_strikes is 0 (unlimited).
        """
        max_strikes = self.get_max_strikes()
        if max_strikes == 0:
            return False
        return self.get_strikes(entity_id) >= max_strikes

    def record_strike(self, entity_id: str) -> bool:
        """Record a strike. Returns True if device is now locked."""
        self._strikes[entity_id] = self._strikes.get(entity_id, 0) + 1
        locked = self.is_device_locked(entity_id)
        self._notify_entity_update(entity_id)
        if locked:
            _LOGGER.warning(
                "Device %s is now locked after %d strikes",
                entity_id,
                self._strikes[entity_id],
            )
        return locked

    def reset_strikes(self, entity_id: str) -> None:
        """Reset strikes for a device (unlock)."""
        self._strikes[entity_id] = 0
        self._last_block_time.pop(entity_id, None)
        self._notify_entity_update(entity_id)
        _LOGGER.info("Strikes reset for %s", entity_id)

    def reset_all_strikes(self) -> None:
        """Reset strikes for all devices."""
        for entity_id in list(self._strikes):
            self.reset_strikes(entity_id)

    def restore_strikes(self, entity_id: str, count: int) -> None:
        """Restore strike count from persistent storage."""
        self._strikes[entity_id] = count

    # --- Global Enabled State ---

    @property
    def global_enabled(self) -> bool:
        """Check if parental controls are globally enabled."""
        return self._global_enabled

    def set_global_enabled(self, enabled: bool) -> None:
        """Set the global parental controls toggle."""
        self._global_enabled = enabled
        _LOGGER.info("Global parental controls %s", "enabled" if enabled else "disabled")
        # Notify all device entities to update their state
        for entity_id in self.monitored_players:
            self._notify_entity_update(entity_id)

    def restore_global_enabled(self, enabled: bool) -> None:
        """Restore global enabled state from persistent storage."""
        self._global_enabled = enabled

    # --- Device Enabled State ---

    def is_device_enabled(self, entity_id: str) -> bool:
        """Check if parental controls are enabled for a device.

        Both the global toggle AND the per-device toggle must be ON.
        """
        if not self._global_enabled:
            return False
        return self._device_enabled.get(entity_id, True)

    def set_device_enabled(self, entity_id: str, enabled: bool) -> None:
        """Set whether parental controls are enabled for a device."""
        self._device_enabled[entity_id] = enabled
        self._notify_entity_update(entity_id)

    def restore_device_enabled(self, entity_id: str, enabled: bool) -> None:
        """Restore device enabled state from persistent storage."""
        self._device_enabled[entity_id] = enabled

    # --- Parent Mode ---

    def is_parent_mode(self, entity_id: str) -> bool:
        """Check if parent mode is active for a device."""
        return self._parent_mode.get(entity_id, False)

    def set_parent_mode(self, entity_id: str, enabled: bool) -> None:
        """Set parent mode for a device.

        When enabling, flushes any accumulated tracking time first so
        time the child was watching before the parent took over still counts.
        """
        if enabled:
            # Flush any in-progress tracking before switching to parent mode
            self.stop_tracking_playback(entity_id)
        self._parent_mode[entity_id] = enabled
        _LOGGER.info(
            "Parent mode %s for %s",
            "enabled" if enabled else "disabled",
            entity_id,
        )
        self._notify_entity_update(entity_id)

    def restore_parent_mode(self, entity_id: str, enabled: bool) -> None:
        """Restore parent mode state from persistent storage."""
        self._parent_mode[entity_id] = enabled

    # --- Usage Tracking ---

    def get_usage_today(self, entity_id: str) -> float:
        """Get total usage today in minutes."""
        return self._usage_today.get(entity_id, 0.0)

    def get_app_usage_today(self, entity_id: str, app_name: str) -> float:
        """Get per-app usage today in minutes."""
        app_usage = self._app_usage_today.get(entity_id, {})
        return app_usage.get(app_name.lower(), 0.0)

    def get_all_app_usage_today(self, entity_id: str) -> dict[str, float]:
        """Get full per-app usage breakdown for a device."""
        return dict(self._app_usage_today.get(entity_id, {}))

    def get_tracked_apps_usage_today(self, entity_id: str) -> float:
        """Get aggregate usage today across all tracked apps, in minutes."""
        tracked = self._get_tracked_apps()
        app_usage = self._app_usage_today.get(entity_id, {})
        return sum(mins for app, mins in app_usage.items() if app in tracked)

    def start_tracking_playback(
        self, entity_id: str, media: MediaInfo | None = None
    ) -> None:
        """Mark that a device started playing (for usage calculation)."""
        self._play_start[entity_id] = dt_util.now()
        if media is not None:
            self._play_media_class[entity_id] = classify_media_type(media)

    def stop_tracking_playback(
        self,
        entity_id: str,
        app_name: str = "",
        media: MediaInfo | None = None,
    ) -> None:
        """Mark that a device stopped playing, accumulate usage."""
        start = self._play_start.pop(entity_id, None)
        if start is None:
            return

        elapsed = (dt_util.now() - start).total_seconds() / 60.0
        self._usage_today[entity_id] = self._usage_today.get(entity_id, 0.0) + elapsed

        if app_name:
            if entity_id not in self._app_usage_today:
                self._app_usage_today[entity_id] = {}
            app_key = app_name.lower()
            self._app_usage_today[entity_id][app_key] = (
                self._app_usage_today[entity_id].get(app_key, 0.0) + elapsed
            )

        # Accumulate media type usage
        media_class = self._play_media_class.pop(entity_id, None)
        if media_class is None and media is not None:
            media_class = classify_media_type(media)
        if media_class is None:
            media_class = "video"  # default fallback
        if entity_id not in self._media_type_usage_today:
            self._media_type_usage_today[entity_id] = {}
        self._media_type_usage_today[entity_id][media_class] = (
            self._media_type_usage_today[entity_id].get(media_class, 0.0) + elapsed
        )

        self._notify_entity_update(entity_id)
        self._notify_entity_update("__aggregate__")

    def reset_daily_usage(self) -> None:
        """Reset all usage counters (called at midnight)."""
        self._usage_today.clear()
        self._app_usage_today.clear()
        self._play_start.clear()
        self._media_type_usage_today.clear()
        self._play_media_class.clear()
        _LOGGER.info("Daily usage counters reset")
        for entity_id in self.monitored_players:
            self._notify_entity_update(entity_id)
        self._notify_entity_update("__aggregate__")

    def restore_usage(
        self,
        entity_id: str,
        total: float,
        app_usage: dict[str, float],
        media_type_usage: dict[str, float] | None = None,
    ) -> None:
        """Restore usage from persistent storage."""
        self._usage_today[entity_id] = total
        self._app_usage_today[entity_id] = app_usage
        if media_type_usage is not None:
            self._media_type_usage_today[entity_id] = media_type_usage

    # --- Aggregate Usage Getters ---

    def get_aggregate_usage_today(self) -> float:
        """Get total usage today summed across all monitored devices."""
        return sum(
            self._usage_today.get(eid, 0.0) for eid in self.monitored_players
        )

    def get_aggregate_tracked_apps_usage_today(self) -> float:
        """Get tracked apps usage summed across all monitored devices."""
        return sum(
            self.get_tracked_apps_usage_today(eid)
            for eid in self.monitored_players
        )

    def get_aggregate_video_usage_today(self) -> float:
        """Get video usage minutes summed across all monitored devices."""
        return sum(
            self.get_device_video_usage_today(eid)
            for eid in self.monitored_players
        )

    def get_aggregate_audio_usage_today(self) -> float:
        """Get audio usage minutes summed across all monitored devices."""
        return sum(
            self.get_device_audio_usage_today(eid)
            for eid in self.monitored_players
        )

    def get_media_type_usage_today(self, entity_id: str) -> dict[str, float]:
        """Get per-device media type usage breakdown."""
        return dict(self._media_type_usage_today.get(entity_id, {}))

    def get_device_video_usage_today(self, entity_id: str) -> float:
        """Get video usage minutes for a single device."""
        return self._media_type_usage_today.get(entity_id, {}).get("video", 0.0)

    def get_device_audio_usage_today(self, entity_id: str) -> float:
        """Get audio usage minutes for a single device."""
        return self._media_type_usage_today.get(entity_id, {}).get("audio", 0.0)

    # --- Tracking Schedule Helpers ---

    def _is_within_allowed_hours(self) -> bool:
        """Check if current time is within the allowed media usage hours."""
        from .content_filter import _parse_time

        start_str = self._get_option(CONF_MEDIA_USAGE_START, DEFAULT_MEDIA_USAGE_START)
        end_str = self._get_option(CONF_MEDIA_USAGE_END, DEFAULT_MEDIA_USAGE_END)
        start = _parse_time(start_str)
        end = _parse_time(end_str)
        now = dt_util.now().time()

        if start <= end:
            return start <= now <= end
        else:
            # Overnight range (e.g., 20:00 to 08:00)
            return now >= start or now <= end

    def _should_track_now(self) -> bool:
        """Check if usage tracking should happen right now.

        Returns False when 'track only during allowed hours' is enabled
        and the current time is outside the allowed window.
        """
        track_only = self._get_option(
            CONF_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
            DEFAULT_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
        )
        if not track_only:
            return True
        return self._is_within_allowed_hours()

    # --- OpenAI Cache ---

    def get_cached_result(self, title: str, artist: str = "") -> str | None:
        """Get cached OpenAI result for a title."""
        key = cache_key(title, artist)
        return self._openai_cache.get(key)

    def set_cached_result(self, title: str, artist: str = "", *, result: str) -> None:
        """Cache an OpenAI result."""
        key = cache_key(title, artist)
        # Evict oldest entries if cache is full
        if len(self._openai_cache) >= OPENAI_CACHE_MAX_ENTRIES:
            # Remove first 20% of entries
            to_remove = list(self._openai_cache.keys())[
                : OPENAI_CACHE_MAX_ENTRIES // 5
            ]
            for k in to_remove:
                del self._openai_cache[k]
        self._openai_cache[key] = result

    def clear_cache(self) -> None:
        """Clear all cached OpenAI results."""
        self._openai_cache.clear()
        _LOGGER.info("OpenAI cache cleared")

    def restore_cache(self, cache: dict[str, str]) -> None:
        """Restore cache from persistent storage."""
        self._openai_cache = cache

    # --- Blocklist Management ---

    def add_blocked_app(self, app_name: str) -> None:
        """Add an app to the blocklist at runtime."""
        current = self._get_option(CONF_BLOCKED_APPS, DEFAULT_BLOCKED_APPS)
        apps = [a.strip() for a in current.split(",") if a.strip()]
        existing_lower = {a.lower() for a in apps}
        if app_name.lower() not in existing_lower:
            apps.append(app_name)
            self.set_runtime_setting(CONF_BLOCKED_APPS, ",".join(apps))

    def remove_blocked_app(self, app_name: str) -> None:
        """Remove an app from the blocklist at runtime."""
        current = self._get_option(CONF_BLOCKED_APPS, DEFAULT_BLOCKED_APPS)
        apps = [a.strip() for a in current.split(",") if a.strip()]
        apps = [a for a in apps if a.lower() != app_name.lower()]
        self.set_runtime_setting(CONF_BLOCKED_APPS, ",".join(apps))

    # --- Entity Update Notification ---

    def register_listener(self, listener: Any) -> None:
        """Register a callback for entity updates."""
        self._listeners.append(listener)

    def unregister_listener(self, listener: Any) -> None:
        """Unregister a callback."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify_entity_update(self, entity_id: str) -> None:
        """Notify all listeners that state changed for an entity."""
        for listener in self._listeners:
            try:
                listener(entity_id)
            except Exception:
                _LOGGER.exception("Error notifying listener")

    # --- Core Pipeline ---

    async def async_handle_media_state_change(self, event: Event) -> None:
        """Handle media_player state change events."""
        try:
            await self._handle_media_state_change_inner(event)
        except Exception:
            _LOGGER.exception(
                "Unhandled error processing state change for %s",
                event.data.get("entity_id", "unknown"),
            )

    async def _handle_media_state_change_inner(self, event: Event) -> None:
        """Inner handler for media_player state changes."""
        entity_id = event.data.get("entity_id", "")
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if not new_state:
            return

        # Track usage when playback stops
        if old_state and old_state.state == STATE_PLAYING and new_state.state != STATE_PLAYING:
            if not self.is_parent_mode(entity_id):
                app_name = old_state.attributes.get("app_name", "")
                old_media = MediaInfo(
                    entity_id=entity_id,
                    app_name=app_name,
                    media_title=old_state.attributes.get("media_title", ""),
                    media_artist=old_state.attributes.get("media_artist", ""),
                    media_content_type=old_state.attributes.get("media_content_type", ""),
                )
                self.stop_tracking_playback(entity_id, app_name, old_media)
            return

        # Only process when transitioning to playing
        if new_state.state != STATE_PLAYING:
            return

        # Parent mode: skip all filtering and tracking
        if self.is_parent_mode(entity_id):
            return

        # Check if parental controls are enabled for this device
        if not self.is_device_enabled(entity_id):
            if self._should_track_now():
                disabled_media = MediaInfo(
                    entity_id=entity_id,
                    app_name=new_state.attributes.get("app_name", ""),
                    media_title=new_state.attributes.get("media_title", ""),
                    media_artist=new_state.attributes.get("media_artist", ""),
                    media_content_type=new_state.attributes.get("media_content_type", ""),
                )
                self.start_tracking_playback(entity_id, disabled_media)
            return

        # Check cooldown for locked devices
        if self.is_device_locked(entity_id):
            last_block = self._last_block_time.get(entity_id)
            if last_block:
                elapsed = (dt_util.now() - last_block).total_seconds()
                if elapsed < LOCKOUT_COOLDOWN_SECONDS:
                    # Fast-path block without full pipeline
                    await self._block_media(
                        entity_id,
                        FilterResult(
                            action="block",
                            reason="Device is locked. Ask a parent to unlock it.",
                            layer=2,
                            should_strike=False,
                        ),
                    )
                    return

        # Build media info from state attributes
        media = MediaInfo(
            entity_id=entity_id,
            app_name=new_state.attributes.get("app_name", ""),
            media_title=new_state.attributes.get("media_title", ""),
            media_artist=new_state.attributes.get("media_artist", ""),
            media_content_type=new_state.attributes.get("media_content_type", ""),
        )

        # Build filter config
        usage_mode = self._get_option(CONF_USAGE_LIMIT_MODE, DEFAULT_USAGE_LIMIT_MODE)
        config = FilterConfig(
            blocked_apps=self._get_blocked_apps(),
            allowed_apps=self._get_allowed_apps(),
            blocked_keywords=self._get_blocked_keywords(),
            content_rating_max=self._get_option(CONF_CONTENT_RATING_MAX, DEFAULT_CONTENT_RATING),
            music_rating_max=self._get_option(CONF_MUSIC_RATING_MAX, DEFAULT_MUSIC_RATING),
            filter_strictness=self._get_option(CONF_FILTER_STRICTNESS, DEFAULT_FILTER_STRICTNESS),
            tracked_apps=self._get_tracked_apps(),
            tracked_apps_daily_limit=self._get_option(CONF_TRACKED_APPS_DAILY_LIMIT, DEFAULT_TRACKED_APPS_DAILY_LIMIT),
            media_usage_daily_limit=self._get_option(CONF_MEDIA_USAGE_DAILY_LIMIT, DEFAULT_MEDIA_USAGE_DAILY_LIMIT),
            media_usage_start=self._get_option(CONF_MEDIA_USAGE_START, DEFAULT_MEDIA_USAGE_START),
            media_usage_end=self._get_option(CONF_MEDIA_USAGE_END, DEFAULT_MEDIA_USAGE_END),
            openai_enabled=self._get_option(CONF_OPENAI_ENABLED, DEFAULT_OPENAI_ENABLED),
            is_device_locked=self.is_device_locked(entity_id),
            tracked_apps_usage_today=self.get_tracked_apps_usage_today(entity_id),
            total_usage_today=self.get_usage_today(entity_id),
            cached_results=self._openai_cache,
            usage_limit_mode=usage_mode,
            aggregate_total_usage_today=self.get_aggregate_usage_today(),
            aggregate_tracked_apps_usage_today=self.get_aggregate_tracked_apps_usage_today(),
            video_daily_limit=self._get_option(CONF_VIDEO_DAILY_LIMIT, DEFAULT_VIDEO_DAILY_LIMIT),
            audio_daily_limit=self._get_option(CONF_AUDIO_DAILY_LIMIT, DEFAULT_AUDIO_DAILY_LIMIT),
            effective_video_usage_today=(
                self.get_aggregate_video_usage_today() if usage_mode == "aggregate"
                else self.get_device_video_usage_today(entity_id)
            ),
            effective_audio_usage_today=(
                self.get_aggregate_audio_usage_today() if usage_mode == "aggregate"
                else self.get_device_audio_usage_today(entity_id)
            ),
        )

        await self._run_pipeline(entity_id, media, config)

    async def _run_pipeline(
        self, entity_id: str, media: MediaInfo, config: FilterConfig
    ) -> None:
        """Run the full filter pipeline and take action."""
        current_time = dt_util.now().time()
        result = run_local_filters(media, config, current_time)

        # None means OpenAI analysis needed
        if result is None:
            result = await self._call_openai(media, config)

        if result.action == "block":
            if result.should_strike:
                now_locked = self.record_strike(entity_id)
                if now_locked:
                    result = FilterResult(
                        action="block",
                        reason=f"Device locked after {self.get_max_strikes()} content violations. {result.reason}",
                        layer=result.layer,
                        should_strike=False,
                    )
            await self._block_media(entity_id, result)
        else:
            # Content allowed, start tracking usage
            if self._should_track_now():
                self.start_tracking_playback(entity_id, media)
            _LOGGER.debug(
                "Content allowed on %s: %s - %s (layer %d: %s)",
                entity_id,
                media.app_name,
                media.media_title,
                result.layer,
                result.reason,
            )

    async def _call_openai(
        self, media: MediaInfo, config: FilterConfig
    ) -> FilterResult:
        """Call OpenAI for content analysis (Layer 9)."""
        prompt = build_openai_prompt(
            media, config.content_rating_max, config.music_rating_max
        )
        agent_id = self._get_option(CONF_OPENAI_AGENT_ID, DEFAULT_OPENAI_AGENT_ID)

        try:
            service_data: dict[str, Any] = {"text": prompt}
            if agent_id:
                service_data["agent_id"] = agent_id

            response = await self.hass.services.async_call(
                "conversation",
                "process",
                service_data,
                blocking=True,
                return_response=True,
            )

            response_text = ""
            if isinstance(response, dict):
                speech = response.get("response", {})
                if isinstance(speech, dict):
                    response_text = speech.get("speech", "")
                else:
                    response_text = str(speech)
            else:
                response_text = str(response) if response else ""

            result = parse_openai_response(response_text)

            # Cache the result
            self.set_cached_result(media.media_title, media.media_artist, result=result.action)

            _LOGGER.info(
                "OpenAI analysis for '%s' by '%s': %s",
                media.media_title,
                media.media_artist,
                result.action,
            )
            return result

        except Exception:
            _LOGGER.exception("OpenAI analysis failed, defaulting to safe")
            return FilterResult(
                action="allow",
                reason="OpenAI analysis failed, defaulting to safe",
                layer=9,
                should_strike=False,
            )

    async def _block_media(self, entity_id: str, result: FilterResult) -> None:
        """Execute the blocking sequence on a media player."""
        self._last_block_time[entity_id] = dt_util.now()
        state_obj = self.hass.states.get(entity_id)
        friendly = (
            state_obj.attributes.get("friendly_name", entity_id)
            if state_obj
            else entity_id
        )

        _LOGGER.warning(
            "Blocking content on %s (layer %d): %s",
            entity_id,
            result.layer,
            result.reason,
        )

        # Step 1: Pause
        try:
            await self.hass.services.async_call(
                MP_DOMAIN,
                "media_pause",
                {"entity_id": entity_id},
                blocking=True,
            )
        except Exception:
            _LOGGER.warning(
                "media_pause failed for %s", entity_id, exc_info=True
            )

        # Step 2: Stop
        try:
            await self.hass.services.async_call(
                MP_DOMAIN,
                "media_stop",
                {"entity_id": entity_id},
                blocking=True,
            )
        except Exception:
            _LOGGER.warning(
                "media_stop failed for %s", entity_id, exc_info=True
            )

        # Step 3: TTS announcement (if enabled)
        tts_enabled = self._get_option(CONF_TTS_ENABLED, DEFAULT_TTS_ENABLED)
        tts_service = self._get_option(CONF_TTS_SERVICE, DEFAULT_TTS_SERVICE)

        if tts_enabled and tts_service:
            tts_message = (
                "This device is locked. Ask a parent to unlock it."
                if self.is_device_locked(entity_id)
                else "This content has been blocked by parental controls."
            )
            try:
                # Modern HA: TTS engines are entities (e.g. tts.piper).
                # Use the tts.speak service with the engine entity_id.
                tts_state = self.hass.states.get(tts_service)
                if tts_state is not None:
                    await self.hass.services.async_call(
                        "tts",
                        "speak",
                        {
                            "entity_id": tts_service,
                            "media_player_entity_id": entity_id,
                            "message": tts_message,
                        },
                        blocking=False,
                    )
                else:
                    # Legacy fallback: call as domain.service directly
                    # e.g. "tts.google_translate_say" -> domain="tts", service="google_translate_say"
                    parts = tts_service.split(".", 1)
                    if len(parts) == 2:
                        await self.hass.services.async_call(
                            parts[0],
                            parts[1],
                            {
                                "entity_id": entity_id,
                                "message": tts_message,
                            },
                            blocking=False,
                        )
                    else:
                        _LOGGER.warning(
                            "TTS service '%s' is not in 'domain.service' format",
                            tts_service,
                        )
            except Exception:
                _LOGGER.warning(
                    "TTS announcement failed for %s", entity_id, exc_info=True
                )

        # Step 4: Persistent notification
        strikes = self.get_strikes(entity_id)
        max_strikes = self.get_max_strikes()
        locked = self.is_device_locked(entity_id)

        if max_strikes == 0:
            strikes_display = f"Strikes: {strikes} (no limit)"
        else:
            strikes_display = f"Strikes: {strikes}/{max_strikes}"

        notification_message = (
            f"**{friendly}**: {result.reason}\n"
            f"{strikes_display}"
        )
        if locked:
            notification_message += (
                "\n\n**Device is LOCKED.** "
                "Use the unlock switch or call `parental_controls.unlock_device` to restore access."
            )

        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Parental Controls Alert",
                    "message": notification_message,
                    "notification_id": f"parental_controls_{entity_id}",
                },
                blocking=False,
            )
        except Exception:
            _LOGGER.warning("Persistent notification failed", exc_info=True)

        # Step 5: Push notification to companion app (only on lockout)
        if locked:
            await self._send_push_notifications(
                entity_id, friendly, result.reason, strikes, max_strikes,
            )

        # Step 6: Fire custom event
        self.hass.bus.async_fire(
            f"{DOMAIN}_blocked",
            {
                "entity_id": entity_id,
                "friendly_name": friendly,
                "reason": result.reason,
                "layer": result.layer,
                "strikes": strikes,
                "max_strikes": max_strikes,
                "locked": locked,
            },
        )

        self._notify_entity_update(entity_id)

    # ------------------------------------------------------------------
    # Companion app push notifications
    # ------------------------------------------------------------------

    def _resolve_push_services(self) -> list[str]:
        """Return the list of mobile app notify service names."""
        push_services = self._get_option(
            CONF_PUSH_NOTIFY_SERVICES, DEFAULT_PUSH_NOTIFY_SERVICES
        )
        # Handle comma-separated string from text-selector fallback
        if isinstance(push_services, str):
            return [s.strip() for s in push_services.split(",") if s.strip()]
        return list(push_services) if push_services else []

    async def _send_push_notifications(
        self,
        entity_id: str,
        friendly_name: str,
        reason: str,
        strikes: int,
        max_strikes: int,
    ) -> None:
        """Send push notifications to configured companion app devices on lockout."""
        push_enabled = self._get_option(
            CONF_PUSH_NOTIFY_ENABLED, DEFAULT_PUSH_NOTIFY_ENABLED
        )
        if not push_enabled:
            return

        push_services = self._resolve_push_services()
        if not push_services:
            return

        # Build notification content
        if max_strikes == 0:
            strikes_text = f"Strikes: {strikes} (no limit)"
        else:
            strikes_text = f"Strikes: {strikes}/{max_strikes}"

        message = (
            f"{friendly_name}: {reason}\n"
            f"{strikes_text}\n"
            "Device is LOCKED."
        )

        notification_data: dict[str, Any] = {
            "tag": f"parental_controls_{entity_id}",
            "importance": "high",
            "push": {"sound": "default"},
            "actions": [
                {
                    "action": f"{ACTION_UNLOCK_DEVICE}_{entity_id}",
                    "title": "Unlock Device",
                }
            ],
        }

        for service_name in push_services:
            try:
                await self.hass.services.async_call(
                    "notify",
                    service_name,
                    {
                        "title": "Parental Controls Alert",
                        "message": message,
                        "data": notification_data,
                    },
                    blocking=False,
                )
            except Exception:
                _LOGGER.warning(
                    "Push notification failed for notify.%s",
                    service_name,
                    exc_info=True,
                )

    async def handle_push_action(self, action: str) -> None:
        """Handle an actionable notification response from the companion app.

        Expected action format: ``PARENTAL_CONTROLS_UNLOCK_<entity_id>``
        """
        prefix = f"{ACTION_UNLOCK_DEVICE}_"
        if not action.startswith(prefix):
            return

        entity_id = action[len(prefix):]
        if entity_id not in self.monitored_players:
            _LOGGER.warning(
                "Received unlock action for unmonitored device: %s", entity_id
            )
            return

        self.reset_strikes(entity_id)
        _LOGGER.info(
            "Device %s unlocked via companion app notification", entity_id
        )

        # Replace the alert notification with a confirmation
        push_services = self._resolve_push_services()
        for service_name in push_services:
            try:
                await self.hass.services.async_call(
                    "notify",
                    service_name,
                    {
                        "title": "Parental Controls",
                        "message": "Device unlocked successfully.",
                        "data": {"tag": f"parental_controls_{entity_id}"},
                    },
                    blocking=False,
                )
            except Exception:
                _LOGGER.warning(
                    "Confirmation notification failed for notify.%s",
                    service_name,
                    exc_info=True,
                )
