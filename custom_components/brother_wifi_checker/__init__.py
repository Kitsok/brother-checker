"""Home Assistant integration for the Brother printer Wi-Fi checker.

Core modules intentionally have no Home Assistant imports so the local CLI can
reuse the same Telnet client and restart policy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

DOMAIN = "brother_wifi_checker"

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured printer."""
    from homeassistant.const import Platform

    from .coordinator import PrinterCoordinator

    platforms = (Platform.BINARY_SENSOR, Platform.SENSOR, Platform.BUTTON)
    coordinator = PrinterCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a printer entry."""
    from homeassistant.const import Platform

    platforms = (Platform.BINARY_SENSOR, Platform.SENSOR, Platform.BUTTON)
    if await hass.config_entries.async_unload_platforms(entry, platforms):
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return True
    return False
