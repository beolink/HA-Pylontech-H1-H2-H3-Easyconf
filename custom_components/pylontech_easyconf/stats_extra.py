"""What this integration adds to the anonymous daily report.

Free of Home Assistant imports on purpose, so the tests can prove without a
Home Assistant installation that only agreed values leave. The family of the
battery, how it is reached, how many modules and cells per module it has, its
firmware and how many polls failed since the previous report. Never a
reading: no voltage, no charge, no temperature, no serial number.

See https://stats.rnet.se/integritet for the full list and the reasoning.
"""

from __future__ import annotations

from typing import Any

#: The families the report may name; anything else is sent as "force".
MODELS = {"Force H1": "force_h1", "Force H2": "force_h2", "Force H3": "force_h3"}
TRANSPORTS = ("solarman_v5", "modbus_tcp", "rtu_over_tcp", "cloud")


class FailureCounter:
    """Turns a cumulative failure count into "since the previous report"."""

    def __init__(self) -> None:
        self._seen = 0

    def delta(self, total: int) -> int:
        if total < self._seen:
            self._seen = 0
        change = total - self._seen
        self._seen = total
        return change


def build_extra(*, model: str | None, transport: str | None, modules: int | None,
                cells_per_module: int | None, cell_data: bool, firmware: str | None,
                failures: int) -> dict[str, Any]:
    """Assemble the integration's part of the report."""
    metrics: dict[str, float] = {}
    if modules:
        metrics["modules"] = int(modules)
    if cells_per_module:
        metrics["cells_per_module"] = int(cells_per_module)
    extra: dict[str, Any] = {
        "models": [MODELS.get(model or "", "force")],
        "features": {
            **{name: transport == name for name in TRANSPORTS},
            "cell_data": bool(cell_data),
        },
        "metrics": metrics,
        "errors": max(0, int(failures)),
    }
    if firmware and len(firmware) <= 16:
        extra["firmware"] = firmware
    return extra
