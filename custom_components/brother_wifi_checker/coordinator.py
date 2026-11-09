"""Coordinator and blocking-I/O adapter for the printer."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path
import threading
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .brother import Checker
from .const import (
    CONF_HOST,
    CONF_AUTO_RECOVERY,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
)
from .recovery import Recovery
from .state import FileState
from .telnet_client import TelnetClient

_LOGGER = logging.getLogger(__name__)


class PrinterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll Wi-Fi and idle state without blocking HA's event loop."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.host = str(entry.data[CONF_HOST])
        self.printer = TelnetClient(
            self.host,
            str(entry.data[CONF_PASSWORD]),
            float(entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
        )
        self._io_lock = threading.Lock()
        self._auto_recovery_task: asyncio.Task | None = None
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(
                seconds=int(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            ),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch device data in an executor because the Telnet client is blocking."""
        data = await self.hass.async_add_executor_job(self._collect)
        if self.entry.options.get(CONF_AUTO_RECOVERY, False) and self._wifi_fault(data):
            if self._auto_recovery_task is None or self._auto_recovery_task.done():
                self._auto_recovery_task = self.hass.async_create_task(
                    self._async_run_auto_recovery()
                )
        return data

    @staticmethod
    def _wifi_fault(data: dict[str, Any]) -> bool:
        """Match only the observed OFF/channel-0 Telnet fault while reachable."""
        wireless = data.get("wireless") or {}
        return bool(
            data.get("reachable")
            and wireless.get("channel") == 0
            and not wireless.get("mode")
        )

    def _collect(self) -> dict[str, Any]:
        """Read each status group independently; preserve partial telemetry."""
        from dataclasses import asdict

        result: dict[str, Any] = {
            "reachable": False,
            "wireless": None,
            "status_error": None,
            "idle": None,
            "idle_error": None,
        }
        with self._io_lock:
            try:
                wireless = self.printer.wireless_status()
                result["reachable"] = True
                result["wireless"] = asdict(wireless)
            except Exception as err:  # keep the entity online state explicit
                result["status_error"] = type(err).__name__
            try:
                result["idle"] = self.printer.idle_status()
                result["reachable"] = True
            except Exception as err:
                result["idle_error"] = type(err).__name__
        return result

    async def async_request_restart(self) -> None:
        """Run the existing guarded, single-shot restart policy once."""
        try:
            events = await self.hass.async_add_executor_job(self._request_restart)
        except Exception as err:
            raise HomeAssistantError("Printer restart request failed; do not retry blindly") from err

        accepted = next((data for event, data in events if event == "restart_requested"), None)
        if accepted is None:
            reason = next(
                (data.get("reason") for event, data in reversed(events) if event in ("skipped", "restart_uncertain")),
                "Restart was not acknowledged",
            )
            raise HomeAssistantError(str(reason))
        _LOGGER.warning("Printer reset request acknowledged: %s", accepted.get("message", "acknowledged"))

    async def _async_run_auto_recovery(self) -> None:
        """Run the CLI-equivalent multi-sample recovery only when opted in."""
        try:
            block_reason = await self.hass.async_add_executor_job(
                self._restart_block_reason
            )
            if block_reason:
                _LOGGER.debug("Automatic printer recovery withheld: %s", block_reason)
                return

            _code, events = await self.hass.async_add_executor_job(
                self._run_auto_recovery
            )
            accepted = next(
                (data for event, data in events if event == "restart_requested"), None
            )
            if accepted:
                _LOGGER.warning(
                    "Automatic printer reset request acknowledged: %s",
                    accepted.get("message", "acknowledged"),
                )
                return
            uncertain = next(
                (data for event, data in reversed(events) if event == "restart_uncertain"),
                None,
            )
            if uncertain:
                _LOGGER.error(
                    "Automatic printer reset result is uncertain; it will not be retried: %s",
                    uncertain.get("reason", "unknown acknowledgement"),
                )
                return
            reason = next(
                (data.get("reason") for event, data in reversed(events) if event == "skipped"),
                "No reset request was sent",
            )
            _LOGGER.info("Automatic printer recovery finished without reset: %s", reason)
        except Exception as err:
            _LOGGER.warning(
                "Automatic printer recovery failed (%s); no blind retry was made",
                type(err).__name__,
            )
        finally:
            self._auto_recovery_task = None

    def _make_store(self) -> FileState:
        """Create the single HA restart-budget store shared by both reset paths."""
        storage_dir = Path(self.hass.config.path(".storage", DOMAIN))
        storage_dir.mkdir(parents=True, exist_ok=True)
        return FileState(storage_dir / f"{self.entry.entry_id}.json", self.host)

    def _restart_block_reason(self) -> str | None:
        """Read the persisted budget before spending time on three new samples."""
        store = self._make_store()
        with self._io_lock, store:
            return store.block_reason()

    def _run_auto_recovery(self) -> tuple[int, list[tuple[str, dict[str, Any]]]]:
        """Run three 10-second-spaced samples and all existing reset guards."""
        return self._run_recovery(stage="run")

    def _request_restart(self) -> list[tuple[str, dict[str, Any]]]:
        """Synchronous reset flow; called only in the HA executor."""
        _code, events = self._run_recovery(stage="restart")
        return events

    def _run_recovery(
        self, stage: str
    ) -> tuple[int, list[tuple[str, dict[str, Any]]]]:
        """Run one recovery sequence while serializing all Telnet operations."""
        events: list[tuple[str, dict[str, Any]]] = []

        def report(event: str, data: dict[str, Any]) -> None:
            events.append((event, data))
            if event == "before_restart":
                # Recovery invokes this callback synchronously before it sends
                # INITIALIZE, so the status is observable in the HA log first.
                _LOGGER.warning("Printer pre-restart status: %s", data)
            elif event == "status":
                _LOGGER.info("Printer recovery status sample: %s", data)
            elif event == "idle":
                _LOGGER.info("Printer idle/port check: %s", data)

        store = self._make_store()
        with self._io_lock, store:
            policy = Recovery(Checker(self.printer), store, report)
            code = policy.run(stage=stage, samples=3, interval=10)
        return code, events
