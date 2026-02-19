"""Number platform for Parental Controls."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MAX_STRIKES,
    CONF_MEDIA_USAGE_DAILY_LIMIT,
    CONF_TRACKED_APPS_DAILY_LIMIT,
    DEFAULT_MAX_STRIKES,
    DEFAULT_MEDIA_USAGE_DAILY_LIMIT,
    DEFAULT_TRACKED_APPS_DAILY_LIMIT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities from a config entry."""
    coordinator = config_entry.runtime_data

    # Migrate old YouTube limit number unique_id
    ent_reg = er.async_get(hass)
    old_uid = f"{config_entry.entry_id}_youtube_limit"
    new_uid = f"{config_entry.entry_id}_tracked_apps_limit"
    existing = ent_reg.async_get_entity_id("number", DOMAIN, old_uid)
    if existing:
        ent_reg.async_update_entity(existing, new_unique_id=new_uid)
        _LOGGER.info("Migrated number unique_id from %s to %s", old_uid, new_uid)

    async_add_entities(
        [
            TrackedAppsLimitNumber(coordinator, config_entry),
            MediaUsageLimitNumber(coordinator, config_entry),
            MaxStrikesNumber(coordinator, config_entry),
        ]
    )


class ParentalControlsNumberBase(NumberEntity):
    """Base class for parental controls number entities."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: Any, config_entry: ConfigEntry) -> None:
        """Initialize."""
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Parental Controls",
            "manufacturer": "Custom",
            "model": "Media Monitor",
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        """Register for updates."""
        await super().async_added_to_hass()
        self._coordinator.register_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up."""
        self._coordinator.unregister_listener(self._handle_update)

    @callback
    def _handle_update(self, entity_id: str) -> None:
        """Handle coordinator update."""
        self.async_write_ha_state()


class TrackedAppsLimitNumber(ParentalControlsNumberBase):
    """Number entity for tracked apps daily limit in minutes."""

    _attr_icon = "mdi:apps"
    _attr_native_min_value = 0
    _attr_native_max_value = 1440
    _attr_native_step = 15
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator: Any, config_entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_tracked_apps_limit"
        self._attr_name = "Tracked apps daily limit"

    @property
    def native_value(self) -> float:
        """Return current tracked apps daily limit."""
        return self._coordinator._get_option(
            CONF_TRACKED_APPS_DAILY_LIMIT, DEFAULT_TRACKED_APPS_DAILY_LIMIT
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set a new tracked apps daily limit."""
        self._coordinator.set_runtime_setting(CONF_TRACKED_APPS_DAILY_LIMIT, value)


class MediaUsageLimitNumber(ParentalControlsNumberBase):
    """Number entity for total media usage daily limit in minutes."""

    _attr_icon = "mdi:timer-sand"
    _attr_native_min_value = 0
    _attr_native_max_value = 1440
    _attr_native_step = 15
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator: Any, config_entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_media_usage_limit"
        self._attr_name = "Media usage daily limit"

    @property
    def native_value(self) -> float:
        """Return current media usage daily limit."""
        return self._coordinator._get_option(
            CONF_MEDIA_USAGE_DAILY_LIMIT, DEFAULT_MEDIA_USAGE_DAILY_LIMIT
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set a new media usage daily limit."""
        self._coordinator.set_runtime_setting(CONF_MEDIA_USAGE_DAILY_LIMIT, value)


class MaxStrikesNumber(ParentalControlsNumberBase):
    """Number entity for maximum strikes before lockout."""

    _attr_icon = "mdi:alert-octagon"
    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 1

    def __init__(self, coordinator: Any, config_entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_max_strikes"
        self._attr_name = "Max strikes before lockout"

    @property
    def native_value(self) -> float:
        """Return current max strikes setting."""
        return self._coordinator._get_option(CONF_MAX_STRIKES, DEFAULT_MAX_STRIKES)

    async def async_set_native_value(self, value: float) -> None:
        """Set a new max strikes value."""
        self._coordinator.set_runtime_setting(CONF_MAX_STRIKES, int(value))
