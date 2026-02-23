"""Parental Controls integration for Home Assistant.

Monitors media_player devices and enforces content/time restrictions
with a layered filtering pipeline and strike-based lockout system.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)

from .const import CONF_MONITORED_PLAYERS, DOMAIN
from .coordinator import ParentalControlsCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORM_LIST = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Parental Controls from a config entry."""
    coordinator = ParentalControlsCoordinator(hass, entry)
    entry.runtime_data = coordinator

    # Get monitored players
    players = entry.data.get(
        CONF_MONITORED_PLAYERS, entry.options.get(CONF_MONITORED_PLAYERS, [])
    )

    # Register state change listener BEFORE platform setup to avoid
    # missing state changes that occur during entity creation.
    if players:
        cancel_state_listener = async_track_state_change_event(
            hass,
            players,
            coordinator.async_handle_media_state_change,
        )
        entry.async_on_unload(cancel_state_listener)

    # Register listener for companion app actionable notification responses
    async def _handle_mobile_action(event: Event) -> None:
        """Handle mobile_app_notification_action events."""
        action = event.data.get("action", "")
        if action.startswith("PARENTAL_CONTROLS_"):
            await coordinator.handle_push_action(action)

    cancel_mobile_action = hass.bus.async_listen(
        "mobile_app_notification_action",
        _handle_mobile_action,
    )
    entry.async_on_unload(cancel_mobile_action)

    # Register midnight reset for daily usage counters
    cancel_midnight = async_track_time_change(
        hass,
        _create_midnight_callback(coordinator),
        hour=0,
        minute=0,
        second=0,
    )
    entry.async_on_unload(cancel_midnight)

    # Forward setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORM_LIST)

    # Register services (and schedule unregistration on unload)
    _register_services(hass, entry, coordinator)

    # Listen for options updates from the options flow only.
    # Number/select entities use runtime_settings (no reload needed).
    # Only the options flow UI triggers this, which is expected to reload.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info(
        "Parental Controls set up for %d device(s): %s",
        len(players),
        ", ".join(players),
    )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to a new version."""
    if entry.version > 3:
        return False

    new_data = dict(entry.data)
    new_options = dict(entry.options)

    if entry.version == 1:
        _LOGGER.info("Migrating config entry from version 1 to 2")

        # Migrate youtube_daily_limit -> tracked_apps_daily_limit
        if "youtube_daily_limit" in new_data:
            new_data["tracked_apps_daily_limit"] = new_data.pop(
                "youtube_daily_limit"
            )
        new_data.setdefault("tracked_apps", "YouTube")

        if "youtube_daily_limit" in new_options:
            new_options["tracked_apps_daily_limit"] = new_options.pop(
                "youtube_daily_limit"
            )
        if "tracked_apps_daily_limit" in new_options:
            new_options.setdefault("tracked_apps", "YouTube")

        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, version=2
        )
        _LOGGER.info("Migration to version 2 successful")

    if entry.version == 2:
        _LOGGER.info("Migrating config entry from version 2 to 3")
        new_data = dict(entry.data)
        new_options = dict(entry.options)

        new_data.setdefault("usage_limit_mode", "per_device")
        new_data.setdefault("video_daily_limit", 0)
        new_data.setdefault("audio_daily_limit", 0)

        new_options.setdefault("usage_limit_mode", "per_device")
        new_options.setdefault("video_daily_limit", 0)
        new_options.setdefault("audio_daily_limit", 0)

        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, version=3
        )
        _LOGGER.info("Migration to version 3 successful")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Persist runtime settings (number/select changes) to config entry
    # so they survive restarts without causing reloads during operation.
    coordinator: ParentalControlsCoordinator = entry.runtime_data
    coordinator.persist_runtime_settings()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORM_LIST)


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options flow update by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


def _create_midnight_callback(coordinator: ParentalControlsCoordinator):
    """Create a callback for midnight usage reset."""

    async def _midnight_reset(now) -> None:
        coordinator.reset_daily_usage()

    return _midnight_reset


def _register_services(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: ParentalControlsCoordinator,
) -> None:
    """Register custom services for parental controls."""

    service_names: list[str] = []

    def _register(name: str, handler, schema) -> None:
        """Register a service and track its name for cleanup."""
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, handler, schema=schema)
            service_names.append(name)

    async def handle_unlock_device(call: ServiceCall) -> None:
        """Reset strikes and unlock a specific device."""
        entity_id = call.data["entity_id"]
        coordinator.reset_strikes(entity_id)
        _LOGGER.info("Service call: unlocked device %s", entity_id)

    async def handle_unlock_all(call: ServiceCall) -> None:
        """Reset strikes for all devices."""
        coordinator.reset_all_strikes()
        _LOGGER.info("Service call: unlocked all devices")

    async def handle_clear_cache(call: ServiceCall) -> None:
        """Clear the OpenAI result cache."""
        coordinator.clear_cache()
        _LOGGER.info("Service call: cleared OpenAI cache")

    async def handle_add_blocked_app(call: ServiceCall) -> None:
        """Add an app to the blocklist."""
        app_name = call.data["app_name"]
        coordinator.add_blocked_app(app_name)
        _LOGGER.info("Service call: added '%s' to blocked apps", app_name)

    async def handle_remove_blocked_app(call: ServiceCall) -> None:
        """Remove an app from the blocklist."""
        app_name = call.data["app_name"]
        coordinator.remove_blocked_app(app_name)
        _LOGGER.info("Service call: removed '%s' from blocked apps", app_name)

    async def handle_set_parent_mode(call: ServiceCall) -> None:
        """Enable or disable parent mode for a media player."""
        entity_id = call.data["entity_id"]
        enabled = call.data["enabled"]
        coordinator.set_parent_mode(entity_id, enabled)
        _LOGGER.info(
            "Service call: parent mode %s for %s",
            "enabled" if enabled else "disabled",
            entity_id,
        )

    _register(
        "unlock_device",
        handle_unlock_device,
        vol.Schema({vol.Required("entity_id"): cv.entity_id}),
    )
    _register("unlock_all", handle_unlock_all, vol.Schema({}))
    _register("clear_cache", handle_clear_cache, vol.Schema({}))
    _register(
        "add_blocked_app",
        handle_add_blocked_app,
        vol.Schema({vol.Required("app_name"): cv.string}),
    )
    _register(
        "remove_blocked_app",
        handle_remove_blocked_app,
        vol.Schema({vol.Required("app_name"): cv.string}),
    )
    _register(
        "set_parent_mode",
        handle_set_parent_mode,
        vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Required("enabled"): cv.boolean,
            }
        ),
    )

    def _unregister_services() -> None:
        for name in service_names:
            hass.services.async_remove(DOMAIN, name)

    entry.async_on_unload(_unregister_services)
