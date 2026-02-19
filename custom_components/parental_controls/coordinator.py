"""Central coordinator for Parental Controls.

Manages state tracking, strike counts, OpenAI cache, and
orchestrates the content filter pipeline + blocking actions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.media_player import DOMAIN as MP_DOMAIN
from homeassistant.const import STATE_PLAYING
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    CONF_ALLOWED_APPS,
    CONF_BLOCKED_APPS,
    CONF_BLOCKED_KEYWORDS,
    CONF_CONTENT_RATING_MAX,
    CONF_FILTER_STRICTNESS,
    CONF_MAX_STRIKES,
    CONF_MONITORED_PLAYERS,
    CONF_MUSIC_RATING_MAX,
    CONF_OPENAI_AGENT_ID,
    CONF_OPENAI_ENABLED,
    CONF_SCREEN_TIME_DAILY_LIMIT,
    CONF_SCREEN_TIME_END,
    CONF_SCREEN_TIME_START,
    CONF_TTS_ENABLED,
    CONF_TTS_SERVICE,
    CONF_YOUTUBE_DAILY_LIMIT,
    DEFAULT_ALLOWED_APPS,
    DEFAULT_BLOCKED_APPS,
    DEFAULT_BLOCKED_KEYWORDS,
    DEFAULT_CONTENT_RATING,
    DEFAULT_FILTER_STRICTNESS,
    DEFAULT_MAX_STRIKES,
    DEFAULT_MUSIC_RATING,
    DEFAULT_OPENAI_AGENT_ID,
    DEFAULT_OPENAI_ENABLED,
    DEFAULT_SCREEN_TIME_DAILY_LIMIT,
    DEFAULT_SCREEN_TIME_END,
    DEFAULT_SCREEN_TIME_START,
    DEFAULT_TTS_ENABLED,
    DEFAULT_TTS_SERVICE,
    DEFAULT_YOUTUBE_DAILY_LIMIT,
    DOMAIN,
    LOCKOUT_COOLDOWN_SECONDS,
    OPENAI_CACHE_MAX_ENTRIES,
)
from .content_filter import (
    FilterConfig,
    FilterResult,
    MediaInfo,
    build_openai_prompt,
    parse_openai_response,
    run_local_filters,
    _cache_key,
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
        # Global master toggle
        self._global_enabled: bool = True
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

    # --- Usage Tracking ---

    def get_usage_today(self, entity_id: str) -> float:
        """Get total usage today in minutes."""
        return self._usage_today.get(entity_id, 0.0)

    def get_app_usage_today(self, entity_id: str, app_name: str) -> float:
        """Get per-app usage today in minutes."""
        app_usage = self._app_usage_today.get(entity_id, {})
        return app_usage.get(app_name.lower(), 0.0)

    def start_tracking_playback(self, entity_id: str) -> None:
        """Mark that a device started playing (for usage calculation)."""
        self._play_start[entity_id] = datetime.now()

    def stop_tracking_playback(self, entity_id: str, app_name: str = "") -> None:
        """Mark that a device stopped playing, accumulate usage."""
        start = self._play_start.pop(entity_id, None)
        if start is None:
            return

        elapsed = (datetime.now() - start).total_seconds() / 60.0
        self._usage_today[entity_id] = self._usage_today.get(entity_id, 0.0) + elapsed

        if app_name:
            if entity_id not in self._app_usage_today:
                self._app_usage_today[entity_id] = {}
            app_key = app_name.lower()
            self._app_usage_today[entity_id][app_key] = (
                self._app_usage_today[entity_id].get(app_key, 0.0) + elapsed
            )
        self._notify_entity_update(entity_id)

    def reset_daily_usage(self) -> None:
        """Reset all usage counters (called at midnight)."""
        self._usage_today.clear()
        self._app_usage_today.clear()
        self._play_start.clear()
        _LOGGER.info("Daily usage counters reset")
        for entity_id in self.monitored_players:
            self._notify_entity_update(entity_id)

    def restore_usage(self, entity_id: str, total: float, app_usage: dict[str, float]) -> None:
        """Restore usage from persistent storage."""
        self._usage_today[entity_id] = total
        self._app_usage_today[entity_id] = app_usage

    # --- OpenAI Cache ---

    def get_cached_result(self, title: str) -> str | None:
        """Get cached OpenAI result for a title."""
        key = _cache_key(title)
        return self._openai_cache.get(key)

    def set_cached_result(self, title: str, result: str) -> None:
        """Cache an OpenAI result."""
        key = _cache_key(title)
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
        if app_name not in apps:
            apps.append(app_name)
            new_options = dict(self.config_entry.options)
            new_options[CONF_BLOCKED_APPS] = ",".join(apps)
            self.hass.config_entries.async_update_entry(
                self.config_entry, options=new_options
            )

    def remove_blocked_app(self, app_name: str) -> None:
        """Remove an app from the blocklist at runtime."""
        current = self._get_option(CONF_BLOCKED_APPS, DEFAULT_BLOCKED_APPS)
        apps = [a.strip() for a in current.split(",") if a.strip()]
        apps = [a for a in apps if a.lower() != app_name.lower()]
        new_options = dict(self.config_entry.options)
        new_options[CONF_BLOCKED_APPS] = ",".join(apps)
        self.hass.config_entries.async_update_entry(
            self.config_entry, options=new_options
        )

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
            app_name = old_state.attributes.get("app_name", "")
            self.stop_tracking_playback(entity_id, app_name)
            return

        # Only process when transitioning to playing
        if new_state.state != STATE_PLAYING:
            return

        # Check if parental controls are enabled for this device
        if not self.is_device_enabled(entity_id):
            self.start_tracking_playback(entity_id)
            return

        # Check cooldown for locked devices
        if self.is_device_locked(entity_id):
            last_block = self._last_block_time.get(entity_id)
            if last_block:
                elapsed = (datetime.now() - last_block).total_seconds()
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
        config = FilterConfig(
            blocked_apps=self._get_blocked_apps(),
            allowed_apps=self._get_allowed_apps(),
            blocked_keywords=self._get_blocked_keywords(),
            content_rating_max=self._get_option(CONF_CONTENT_RATING_MAX, DEFAULT_CONTENT_RATING),
            music_rating_max=self._get_option(CONF_MUSIC_RATING_MAX, DEFAULT_MUSIC_RATING),
            filter_strictness=self._get_option(CONF_FILTER_STRICTNESS, DEFAULT_FILTER_STRICTNESS),
            youtube_daily_limit=self._get_option(CONF_YOUTUBE_DAILY_LIMIT, DEFAULT_YOUTUBE_DAILY_LIMIT),
            screen_time_daily_limit=self._get_option(CONF_SCREEN_TIME_DAILY_LIMIT, DEFAULT_SCREEN_TIME_DAILY_LIMIT),
            screen_time_start=self._get_option(CONF_SCREEN_TIME_START, DEFAULT_SCREEN_TIME_START),
            screen_time_end=self._get_option(CONF_SCREEN_TIME_END, DEFAULT_SCREEN_TIME_END),
            openai_enabled=self._get_option(CONF_OPENAI_ENABLED, DEFAULT_OPENAI_ENABLED),
            is_device_locked=self.is_device_locked(entity_id),
            youtube_usage_today=self.get_app_usage_today(entity_id, "youtube"),
            total_usage_today=self.get_usage_today(entity_id),
            cached_results=self._openai_cache,
        )

        await self._run_pipeline(entity_id, media, config)

    async def _run_pipeline(
        self, entity_id: str, media: MediaInfo, config: FilterConfig
    ) -> None:
        """Run the full filter pipeline and take action."""
        current_time = datetime.now().time()
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
            self.start_tracking_playback(entity_id)
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
            self.set_cached_result(media.media_title, result.action)

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
        self._last_block_time[entity_id] = datetime.now()
        friendly_name = self.hass.states.get(entity_id)
        friendly = (
            friendly_name.attributes.get("friendly_name", entity_id)
            if friendly_name
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
                # Parse service: e.g., "tts.google_translate_say" -> domain="tts", service="google_translate_say"
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

        # Step 5: Fire custom event
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
