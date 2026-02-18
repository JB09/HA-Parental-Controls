"""Parental Controls integration for Home Assistant.

Monitors media_player devices and enforces content/time restrictions
with a layered filtering pipeline and strike-based lockout system.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)

from .const import CONF_MONITORED_PLAYERS, DOMAIN, PLATFORMS
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

    # Forward setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORM_LIST)

    # Get monitored players
    players = entry.data.get(
        CONF_MONITORED_PLAYERS, entry.options.get(CONF_MONITORED_PLAYERS, [])
    )

    # Register state change listener for monitored media_players
    if players:
        cancel_state_listener = async_track_state_change_event(
            hass,
            players,
            coordinator.async_handle_media_state_change,
        )
        entry.async_on_unload(cancel_state_listener)

    # Register midnight reset for daily usage counters
    cancel_midnight = async_track_time_change(
        hass,
        _create_midnight_callback(coordinator),
        hour=0,
        minute=0,
        second=0,
    )
    entry.async_on_unload(cancel_midnight)

    # Register services
    _register_services(hass, coordinator)

    # Listen for options updates to re-register state listeners
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info(
        "Parental Controls set up for %d device(s): %s",
        len(players),
        ", ".join(players),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORM_LIST)


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


def _create_midnight_callback(coordinator: ParentalControlsCoordinator):
    """Create a callback for midnight usage reset."""

    async def _midnight_reset(now) -> None:
        coordinator.reset_daily_usage()

    return _midnight_reset


def _register_services(
    hass: HomeAssistant, coordinator: ParentalControlsCoordinator
) -> None:
    """Register custom services for parental controls."""

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

    if not hass.services.has_service(DOMAIN, "unlock_device"):
        hass.services.async_register(
            DOMAIN,
            "unlock_device",
            handle_unlock_device,
            schema=vol.Schema(
                {vol.Required("entity_id"): cv.entity_id}
            ),
        )

    if not hass.services.has_service(DOMAIN, "unlock_all"):
        hass.services.async_register(
            DOMAIN,
            "unlock_all",
            handle_unlock_all,
            schema=vol.Schema({}),
        )

    if not hass.services.has_service(DOMAIN, "clear_cache"):
        hass.services.async_register(
            DOMAIN,
            "clear_cache",
            handle_clear_cache,
            schema=vol.Schema({}),
        )

    if not hass.services.has_service(DOMAIN, "add_blocked_app"):
        hass.services.async_register(
            DOMAIN,
            "add_blocked_app",
            handle_add_blocked_app,
            schema=vol.Schema(
                {vol.Required("app_name"): cv.string}
            ),
        )

    if not hass.services.has_service(DOMAIN, "remove_blocked_app"):
        hass.services.async_register(
            DOMAIN,
            "remove_blocked_app",
            handle_remove_blocked_app,
            schema=vol.Schema(
                {vol.Required("app_name"): cv.string}
            ),
        )
