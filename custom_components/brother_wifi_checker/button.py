"""Explicit guarded restart button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PrinterCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PrinterCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BrotherRestartButton(coordinator, entry)])


class BrotherRestartButton(CoordinatorEntity[PrinterCoordinator], ButtonEntity):
    """Submit one pre-checked reset request; never polls after it."""

    _attr_has_entity_name = True
    _attr_translation_key = "guarded_restart"
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: PrinterCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_guarded_restart"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": "Brother",
            "model": "DCP-L3520CDW",
            "name": "Brother DCP-L3520CDW",
        }

    async def async_press(self) -> None:
        await self.coordinator.async_request_restart()
