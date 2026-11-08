"""Transport-independent observations; no network, credentials or scheduling."""
from dataclasses import asdict, dataclass


class CheckError(RuntimeError):
    """Device response was unavailable or unsafe to interpret."""


@dataclass(frozen=True)
class WirelessStatus:
    ssid: str
    authentication: str
    encryption: str
    mode: str
    channel: int
    signal: str

    @property
    def incomplete(self):
        return self.channel == 0 and not self.mode


@dataclass(frozen=True)
class Observation:
    reachable: bool
    wireless: WirelessStatus | None
    mismatch: bool

    def to_dict(self):
        return asdict(self)


class Checker:
    """Printer-only observation; the transport enforces its timeout."""
    def __init__(self, printer):
        self.printer = printer

    def status(self) -> Observation:
        wireless = self.printer.wireless_status()
        return Observation(True, wireless, wireless.incomplete)
