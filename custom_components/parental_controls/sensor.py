"""Sensor platform for Parental Controls."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_MONITORED_PLAYERS, DOMAIN, device_slug

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator = config_entry.runtime_data
    players = config_entry.data.get(
        CONF_MONITORED_PLAYERS,
        config_entry.options.get(CONF_MONITORED_PLAYERS, []),
    )

    # Migrate old YouTube usage sensor unique_ids to tracked apps
    ent_reg = er.async_get(hass)
    for player_id in players:
        slug = device_slug(player_id)
        old_uid = f"{config_entry.entry_id}_{slug}_youtube_usage_today"
        new_uid = f"{config_entry.entry_id}_{slug}_tracked_apps_usage_today"
        existing = ent_reg.async_get_entity_id("sensor", DOMAIN, old_uid)
        if existing:
            ent_reg.async_update_entity(existing, new_unique_id=new_uid)
            _LOGGER.info(
                "Migrated sensor unique_id from %s to %s", old_uid, new_uid
            )

    entities: list[SensorEntity] = []
    for player_id in players:
        entities.append(StrikeSensor(coordinator, config_entry, player_id))
        entities.append(UsageTodaySensor(coordinator, config_entry, player_id))
        entities.append(TrackedAppsUsageSensor(coordinator, config_entry, player_id))

    entities.append(LastBlockedSensor(coordinator, config_entry))

    async_add_entities(entities)


class ParentalControlsSensorBase(RestoreEntity, SensorEntity):
    """Base class for parental controls sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Any,
        config_entry: ConfigEntry,
    ) -> None:
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
        """Register for updates when added to hass."""
        await super().async_added_to_hass()
        self._coordinator.register_listener(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when removed."""
        self._coordinator.unregister_listener(self._handle_coordinator_update)

    @callback
    def _handle_coordinator_update(self, entity_id: str) -> None:
        """Handle coordinator state update."""
        self.async_write_ha_state()


class StrikeSensor(ParentalControlsSensorBase):
    """Sensor showing current strike count for a monitored device."""

    _attr_icon = "mdi:alert-octagon"
    _attr_native_unit_of_measurement = "strikes"

    def __init__(
        self,
        coordinator: Any,
        config_entry: ConfigEntry,
        player_entity_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, config_entry)
        self._player_entity_id = player_entity_id
        slug = device_slug(player_entity_id)
        self._attr_unique_id = f"{config_entry.entry_id}_{slug}_strikes"
        self._attr_name = f"{slug} strikes"

    @callback
    def _handle_coordinator_update(self, entity_id: str) -> None:
        """Handle coordinator state update for this device only."""
        if entity_id == self._player_entity_id:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore strike count on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                count = int(float(last_state.state))
                self._coordinator.restore_strikes(self._player_entity_id, count)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Failed to restore strike count for %s from state '%s'",
                    self._player_entity_id,
                    last_state.state,
                )

    @property
    def native_value(self) -> int:
        """Return current strike count."""
        return self._coordinator.get_strikes(self._player_entity_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {
            "max_strikes": self._coordinator.get_max_strikes(),
            "monitored_player": self._player_entity_id,
            "locked": self._coordinator.is_device_locked(self._player_entity_id),
        }


class UsageTodaySensor(ParentalControlsSensorBase):
    """Sensor showing total usage today in minutes for a device."""

    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = "min"

    def __init__(
        self,
        coordinator: Any,
        config_entry: ConfigEntry,
        player_entity_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, config_entry)
        self._player_entity_id = player_entity_id
        slug = device_slug(player_entity_id)
        self._attr_unique_id = f"{config_entry.entry_id}_{slug}_usage_today"
        self._attr_name = f"{slug} usage today"

    @callback
    def _handle_coordinator_update(self, entity_id: str) -> None:
        """Handle coordinator state update for this device only."""
        if entity_id == self._player_entity_id:
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore usage on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            try:
                total = float(last_state.state)
                app_usage = last_state.attributes.get("app_usage", {})
                self._coordinator.restore_usage(
                    self._player_entity_id, total, app_usage
                )
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Failed to restore usage for %s from state '%s'",
                    self._player_entity_id,
                    last_state.state,
                )

    @property
    def native_value(self) -> float:
        """Return total usage today in minutes."""
        return round(self._coordinator.get_usage_today(self._player_entity_id), 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-app breakdown."""
        return {
            "monitored_player": self._player_entity_id,
            "app_usage": self._coordinator.get_all_app_usage_today(
                self._player_entity_id
            ),
        }


class TrackedAppsUsageSensor(ParentalControlsSensorBase):
    """Sensor showing aggregate tracked apps usage today in minutes for a device."""

    _attr_icon = "mdi:apps"
    _attr_native_unit_of_measurement = "min"

    def __init__(
        self,
        coordinator: Any,
        config_entry: ConfigEntry,
        player_entity_id: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, config_entry)
        self._player_entity_id = player_entity_id
        slug = device_slug(player_entity_id)
        self._attr_unique_id = f"{config_entry.entry_id}_{slug}_tracked_apps_usage_today"
        self._attr_name = f"{slug} tracked apps usage today"

    @callback
    def _handle_coordinator_update(self, entity_id: str) -> None:
        """Handle coordinator state update for this device only."""
        if entity_id == self._player_entity_id:
            self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        """Return aggregate tracked apps usage today in minutes."""
        return round(
            self._coordinator.get_tracked_apps_usage_today(self._player_entity_id),
            1,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return per-app breakdown for tracked apps."""
        tracked = self._coordinator._get_tracked_apps()
        all_usage = self._coordinator.get_all_app_usage_today(
            self._player_entity_id
        )
        tracked_breakdown = {
            app: round(minutes, 1)
            for app, minutes in all_usage.items()
            if app in tracked
        }
        return {
            "monitored_player": self._player_entity_id,
            "tracked_apps": tracked,
            "app_usage": tracked_breakdown,
        }


class LastBlockedSensor(ParentalControlsSensorBase):
    """Sensor showing the last blocked content details."""

    _attr_icon = "mdi:block-helper"

    def __init__(
        self,
        coordinator: Any,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{config_entry.entry_id}_last_blocked"
        self._attr_name = "Last blocked content"
        self._last_reason: str = ""
        self._last_device: str = ""
        self._last_layer: int = 0

        # Listen for block events
        self._event_unsub = None

    async def async_added_to_hass(self) -> None:
        """Register for block events."""
        await super().async_added_to_hass()

        # Restore last state
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (None, "unknown", "unavailable"):
            self._last_reason = last_state.state
            self._last_device = last_state.attributes.get("device", "")
            self._last_layer = last_state.attributes.get("layer", 0)

        @callback
        def handle_block_event(event):
            self._last_reason = event.data.get("reason", "")
            self._last_device = event.data.get("entity_id", "")
            self._last_layer = event.data.get("layer", 0)
            self.async_write_ha_state()

        self._event_unsub = self.hass.bus.async_listen(
            f"{DOMAIN}_blocked", handle_block_event
        )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up event listener."""
        await super().async_will_remove_from_hass()
        if self._event_unsub:
            self._event_unsub()

    @property
    def native_value(self) -> str:
        """Return the last blocked reason."""
        return self._last_reason or "None"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        return {
            "device": self._last_device,
            "layer": self._last_layer,
        }
