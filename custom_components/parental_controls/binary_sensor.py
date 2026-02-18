"""Binary sensor platform for Parental Controls."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_MONITORED_PLAYERS, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _device_slug(entity_id: str) -> str:
    """Convert media_player.living_room_tv to living_room_tv."""
    return entity_id.replace("media_player.", "").replace(".", "_")


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities from a config entry."""
    coordinator = config_entry.runtime_data
    players = config_entry.data.get(
        CONF_MONITORED_PLAYERS,
        config_entry.options.get(CONF_MONITORED_PLAYERS, []),
    )

    entities = [
        DeviceLockedSensor(coordinator, config_entry, player_id)
        for player_id in players
    ]

    async_add_entities(entities)


class DeviceLockedSensor(RestoreEntity, BinarySensorEntity):
    """Binary sensor showing if a device is locked due to max strikes."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.LOCK
    _attr_icon = "mdi:lock"

    def __init__(
        self,
        coordinator: Any,
        config_entry: ConfigEntry,
        player_entity_id: str,
    ) -> None:
        """Initialize."""
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._player_entity_id = player_entity_id
        slug = _device_slug(player_entity_id)
        self._attr_unique_id = f"{config_entry.entry_id}_{slug}_locked"
        self._attr_name = f"{slug} locked"
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

    @property
    def is_on(self) -> bool:
        """Return True if the device is locked."""
        return self._coordinator.is_device_locked(self._player_entity_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {
            "monitored_player": self._player_entity_id,
            "strikes": self._coordinator.get_strikes(self._player_entity_id),
            "max_strikes": self._coordinator.get_max_strikes(),
        }
