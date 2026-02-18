"""Number platform for Parental Controls."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_MAX_STRIKES,
    CONF_SCREEN_TIME_DAILY_LIMIT,
    CONF_YOUTUBE_DAILY_LIMIT,
    DEFAULT_MAX_STRIKES,
    DEFAULT_SCREEN_TIME_DAILY_LIMIT,
    DEFAULT_YOUTUBE_DAILY_LIMIT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities from a config entry."""
    async_add_entities(
        [
            YouTubeLimitNumber(config_entry),
            ScreenTimeLimitNumber(config_entry),
            MaxStrikesNumber(config_entry),
        ]
    )


class ParentalControlsNumberBase(NumberEntity):
    """Base class for parental controls number entities."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        self._config_entry = config_entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": "Parental Controls",
            "manufacturer": "Custom",
            "model": "Media Monitor",
            "entry_type": "service",
        }

    def _get_option(self, key: str, default: Any) -> Any:
        """Get value from options or data."""
        if key in self._config_entry.options:
            return self._config_entry.options[key]
        return self._config_entry.data.get(key, default)

    def _set_option(self, key: str, value: Any) -> None:
        """Update an option value."""
        new_options = dict(self._config_entry.options)
        new_options[key] = value
        self.hass.config_entries.async_update_entry(
            self._config_entry, options=new_options
        )


class YouTubeLimitNumber(ParentalControlsNumberBase):
    """Number entity for YouTube daily limit in minutes."""

    _attr_icon = "mdi:youtube"
    _attr_native_min_value = 0
    _attr_native_max_value = 1440
    _attr_native_step = 15
    _attr_native_unit_of_measurement = "min"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_youtube_limit"
        self._attr_name = "YouTube daily limit"

    @property
    def native_value(self) -> float:
        """Return current YouTube daily limit."""
        return self._get_option(CONF_YOUTUBE_DAILY_LIMIT, DEFAULT_YOUTUBE_DAILY_LIMIT)

    async def async_set_native_value(self, value: float) -> None:
        """Set a new YouTube daily limit."""
        self._set_option(CONF_YOUTUBE_DAILY_LIMIT, value)


class ScreenTimeLimitNumber(ParentalControlsNumberBase):
    """Number entity for total screen time daily limit in minutes."""

    _attr_icon = "mdi:timer-sand"
    _attr_native_min_value = 0
    _attr_native_max_value = 1440
    _attr_native_step = 15
    _attr_native_unit_of_measurement = "min"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_screen_time_limit"
        self._attr_name = "Screen time daily limit"

    @property
    def native_value(self) -> float:
        """Return current screen time daily limit."""
        return self._get_option(
            CONF_SCREEN_TIME_DAILY_LIMIT, DEFAULT_SCREEN_TIME_DAILY_LIMIT
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set a new screen time daily limit."""
        self._set_option(CONF_SCREEN_TIME_DAILY_LIMIT, value)


class MaxStrikesNumber(ParentalControlsNumberBase):
    """Number entity for maximum strikes before lockout."""

    _attr_icon = "mdi:alert-octagon"
    _attr_native_min_value = 1
    _attr_native_max_value = 10
    _attr_native_step = 1

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_max_strikes"
        self._attr_name = "Max strikes before lockout"

    @property
    def native_value(self) -> float:
        """Return current max strikes setting."""
        return self._get_option(CONF_MAX_STRIKES, DEFAULT_MAX_STRIKES)

    async def async_set_native_value(self, value: float) -> None:
        """Set a new max strikes value."""
        self._set_option(CONF_MAX_STRIKES, int(value))
