"""UI configuration flow."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .brother import CheckError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .telnet_client import TelnetClient


def _test_connection(host: str, password: str, timeout: float) -> None:
    """Verify Telnet login and parse one read-only status response."""
    TelnetClient(host, password, timeout).wireless_status()


class BrotherWifiCheckerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a printer by host and Telnet administrator password."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial setup form."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            password = str(user_input[CONF_PASSWORD])
            timeout = float(user_input[CONF_TIMEOUT])
            await self.async_set_unique_id(host.lower())
            self._abort_if_unique_id_configured()
            try:
                await self.hass.async_add_executor_job(_test_connection, host, password, timeout)
            except (CheckError, OSError, TimeoutError, ValueError):
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Brother printer ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_PASSWORD: password,
                        CONF_TIMEOUT: timeout,
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
                    vol.Coerce(float), vol.Range(min=2, max=60)
                ),
                vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
