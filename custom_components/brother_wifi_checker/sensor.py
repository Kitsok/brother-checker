"""Wi-Fi and port telemetry sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PrinterCoordinator

_SENSORS = {
    "ssid": "Wi-Fi SSID",
    "mode": "Wi-Fi mode",
    "channel": "Wi-Fi channel",
    "signal": "Wi-Fi signal",
    "authentication": "Wi-Fi authentication",
    "encryption": "Wi-Fi encryption",
    "port_state": "Printer port state",
    "current_job": "Current job present",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PrinterCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(BrotherStatusSensor(coordinator, entry, key) for key in _SENSORS)


class BrotherStatusSensor(CoordinatorEntity[PrinterCoordinator], SensorEntity):
    """Expose parsed values without leaking raw console output or job names."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PrinterCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self.key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": "Brother",
            "model": "DCP-L3520CDW",
            "name": "Brother DCP-L3520CDW",
        }
        self._attr_icon = "mdi:wifi" if key in _SENSORS and key not in ("port_state", "current_job") else "mdi:printer"

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        wireless = data.get("wireless") or {}
        idle = data.get("idle") or {}
        if self.key in ("ssid", "mode", "channel", "signal", "authentication", "encryption"):
            value = wireless.get(self.key)
            if self.key == "mode" and wireless and not value:
                return "off"
            return value
        if self.key == "port_state":
            return idle.get("state")
        if self.key == "current_job":
            present = idle.get("current_job_present")
            return None if present is None else ("present" if present else "none")
        return None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        if self.key == "current_job":
            idle = data.get("idle") or {}
            return {
                "queue_visibility": idle.get("queue_visibility"),
                "pending_jobs": idle.get("pending_jobs"),
                "idle": idle.get("idle"),
            }
        if self.key == "ssid":
            return {"status_error": data.get("status_error")}
        return {}
