"""Select platform for Parental Controls."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CONTENT_RATING_MAX,
    CONF_FILTER_STRICTNESS,
    CONF_MUSIC_RATING_MAX,
    CONTENT_RATINGS,
    DEFAULT_CONTENT_RATING,
    DEFAULT_FILTER_STRICTNESS,
    DEFAULT_MUSIC_RATING,
    DOMAIN,
    FILTER_STRICTNESS_OPTIONS,
    MUSIC_RATINGS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities from a config entry."""
    async_add_entities(
        [
            ContentRatingSelect(config_entry),
            MusicRatingSelect(config_entry),
            FilterStrictnessSelect(config_entry),
        ]
    )


class ParentalControlsSelectBase(SelectEntity):
    """Base class for parental controls select entities."""

    _attr_has_entity_name = True

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


class ContentRatingSelect(ParentalControlsSelectBase):
    """Select entity for maximum content rating."""

    _attr_icon = "mdi:certificate"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_content_rating"
        self._attr_name = "Maximum content rating"
        self._attr_options = CONTENT_RATINGS

    @property
    def current_option(self) -> str:
        """Return current content rating."""
        return self._get_option(CONF_CONTENT_RATING_MAX, DEFAULT_CONTENT_RATING)

    async def async_select_option(self, option: str) -> None:
        """Set a new content rating."""
        self._set_option(CONF_CONTENT_RATING_MAX, option)


class MusicRatingSelect(ParentalControlsSelectBase):
    """Select entity for music rating policy."""

    _attr_icon = "mdi:music-note"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_music_rating"
        self._attr_name = "Music rating policy"
        self._attr_options = MUSIC_RATINGS

    @property
    def current_option(self) -> str:
        """Return current music rating."""
        return self._get_option(CONF_MUSIC_RATING_MAX, DEFAULT_MUSIC_RATING)

    async def async_select_option(self, option: str) -> None:
        """Set a new music rating."""
        self._set_option(CONF_MUSIC_RATING_MAX, option)


class FilterStrictnessSelect(ParentalControlsSelectBase):
    """Select entity for title filter strictness level."""

    _attr_icon = "mdi:filter-variant"

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_filter_strictness"
        self._attr_name = "Filter strictness"
        self._attr_options = FILTER_STRICTNESS_OPTIONS

    @property
    def current_option(self) -> str:
        """Return current strictness level."""
        return self._get_option(CONF_FILTER_STRICTNESS, DEFAULT_FILTER_STRICTNESS)

    async def async_select_option(self, option: str) -> None:
        """Set a new strictness level."""
        self._set_option(CONF_FILTER_STRICTNESS, option)
