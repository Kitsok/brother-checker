"""Binary status entities."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
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
    async_add_entities(
        [
            BrotherStatusBinarySensor(coordinator, entry, "reachable"),
            BrotherStatusBinarySensor(coordinator, entry, "wifi_fault"),
            BrotherStatusBinarySensor(coordinator, entry, "idle"),
        ]
    )


class BrotherStatusBinarySensor(CoordinatorEntity[PrinterCoordinator], BinarySensorEntity):
    """A boolean view over cached printer telemetry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PrinterCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self.key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "manufacturer": "Brother",
            "model": "DCP-L3520CDW",
            "name": "Brother DCP-L3520CDW",
        }
        self._attr_translation_key = key
        if key == "wifi_fault":
            self._attr_device_class = BinarySensorDeviceClass.PROBLEM
            self._attr_icon = "mdi:wifi-alert"
        elif key == "reachable":
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        else:
            self._attr_icon = "mdi:printer-check"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        if self.key == "reachable":
            return bool(data["reachable"])
        if self.key == "wifi_fault":
            wireless = data.get("wireless")
            if wireless is None:
                return None
            return wireless.get("channel") == 0 and not wireless.get("mode")
        idle = data.get("idle")
        return None if idle is None else bool(idle.get("idle"))

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        if self.key == "wifi_fault":
            return {
                "ssid": (data.get("wireless") or {}).get("ssid"),
                "mode": (data.get("wireless") or {}).get("mode"),
                "channel": (data.get("wireless") or {}).get("channel"),
                "signal": (data.get("wireless") or {}).get("signal"),
                "interpretation": "Telnet-reported Wi-Fi fields; this is not a direct LED reading",
            }
        if self.key == "idle":
            idle = data.get("idle") or {}
            return {
                "port_state": idle.get("state"),
                "current_job_present": idle.get("current_job_present"),
                "reasons": idle.get("reasons"),
                "queue_visibility": idle.get("queue_visibility"),
                "pending_jobs": idle.get("pending_jobs"),
            }
        return {"status_error": data.get("status_error"), "idle_error": data.get("idle_error")}
