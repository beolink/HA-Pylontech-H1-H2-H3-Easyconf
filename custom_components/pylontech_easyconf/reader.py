"""Reading a whole stack through a transport, and finding out how to.

``read_snapshot`` reads the summary, the modules and the cells in as few
requests as the logger allows and decodes them in one go, so every entity of
a poll shows the same moment. ``probe`` is what the set-up uses to find out
which protocol an address speaks and whether a Pylontech BMS is behind it.

Free of Home Assistant on purpose, so the tests run without it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import logging

from . import registers
from .modbus import IllegalDataAddress, ModbusError
from .model import Identity, Snapshot
from .transport import (
    DEFAULT_TIMEOUT,
    MODBUS_TCP,
    RTU_OVER_TCP,
    SOLARMAN_V5,
    Transport,
    TransportError,
    make_transport,
)

_LOGGER = logging.getLogger(__name__)

AUTO = "auto"

#: The Modbus addresses tried, first to last, when the field is left at 1: in
#: a system of several towers each tower's BMS has an address of its own (an
#: owner of three towers found their second and third tower on another address
#: than 1, 2026-11).
AUTO_SLAVES = tuple(range(1, 9))
#: The wait for each address after the first. A Solarman logger does not
#: answer a request to an address with no BMS, and stays busy for about six
#: seconds after it: it holds the next request, on any connection, until then
#: and only then passes it on (measured on a Force H3's logger, 2026-11-25:
#: 6.2 to 6.3 s from the unanswered request to the next answer, with a wait of
#: 2 or 4 s and any pause up to 3 s). A shorter wait gives up on the next
#: address while the logger still holds it.
EXTRA_SLAVE_TIMEOUT = 7.5

#: Which reason wins when several attempts fail differently.
_RANK = {"cannot_connect": 0, "no_battery": 1, "not_pylontech": 2}


async def read_identity(transport: Transport) -> Identity:
    """The brand, name, firmware and serial number of the BMS."""
    words = await transport.read_registers(registers.IDENTITY_START, registers.IDENTITY_COUNT)
    try:
        serial = await transport.read_registers(registers.SERIAL_START, registers.SERIAL_COUNT)
    except ModbusError:
        serial = None
    return registers.decode_identity(words, serial)


@dataclass
class Reading:
    snapshot: Snapshot
    #: Where the summary block answered, to ask there first next time.
    summary_start: int


async def _optional(transport: Transport, start: int, count: int) -> list[int] | None:
    """A block the BMS may not have: None when it says so."""
    if count <= 0:
        return None
    try:
        return await transport.read_registers(start, count)
    except IllegalDataAddress:
        _LOGGER.debug("No block at %#06x on this BMS", start)
        return None


async def read_snapshot(transport: Transport, summary_start: int | None = None,
                        cells: bool = True) -> Reading:
    """One whole reading of the stack.

    ``summary_start`` is where the summary block answered last time; the
    other mirror is tried when the BMS does not have it. ``cells`` False
    leaves the two cell blocks out, which on a large Force H3 string is most
    of the requests of a poll.
    """
    starts: Sequence[int] = registers.SUMMARY_STARTS
    if summary_start in starts:
        starts = [summary_start, *[s for s in starts if s != summary_start]]
    summary: list[int] | None = None
    used = starts[0]
    for start in starts:
        try:
            summary = await transport.read_registers(start, registers.SUMMARY_COUNT)
            used = start
            break
        except IllegalDataAddress:
            continue
    if summary is None:
        raise registers.DecodeError("the BMS has neither summary block (0x1100, 0x1400)")
    modules, cell_count = registers.counts(summary)
    module_voltages = await _optional(transport, registers.MODULE_VOLTAGES_START, modules)
    module_temperatures = await _optional(transport, registers.MODULE_TEMPERATURES_START, modules)
    cell_voltages = cell_temperatures = None
    if cells and cell_count:
        cell_voltages = await _optional(transport, registers.CELL_VOLTAGES_START, cell_count)
        if cell_voltages is not None:
            cell_temperatures = await _optional(
                transport, registers.CELL_TEMPERATURES_START, cell_count
            )
    snapshot = registers.decode(
        summary, module_voltages, module_temperatures, cell_voltages, cell_temperatures
    )
    return Reading(snapshot, used)


class ProbeError(Exception):
    """Nothing usable at the address. ``reason`` is a config-flow error key."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class ProbeResult:
    kind: str
    port: int
    #: The logger's serial number, learned or given; 0 outside Solarman V5.
    serial: int
    identity: Identity
    #: The Modbus address the BMS answered on.
    slave: int = 1


def attempts(kind: str, port: int | None) -> list[tuple[str, int]]:
    """The protocols and ports to try, most likely first."""
    if kind != AUTO:
        return [(kind, port or {SOLARMAN_V5: 8899, MODBUS_TCP: 502}.get(kind, 8899))]
    if port in (None, 8899):
        return [(SOLARMAN_V5, 8899), (MODBUS_TCP, 502), (MODBUS_TCP, 8899)]
    if port == 502:
        return [(MODBUS_TCP, 502), (SOLARMAN_V5, 8899)]
    return [(RTU_OVER_TCP, port), (MODBUS_TCP, port), (SOLARMAN_V5, port)]


async def probe(host: str, port: int | None = None, kind: str = AUTO, serial: int = 0,
                slave: int = 1, timeout: float = DEFAULT_TIMEOUT,
                order: Sequence[tuple[str, int]] | None = None,
                slaves: Sequence[int] | None = None,
                extra_timeout: float | None = None) -> ProbeResult:
    """Find the protocol and the Modbus address that reach a Pylontech BMS.

    ``order`` names the protocols and ports to try, in that order, in place
    of the ones ``kind`` and ``port`` imply. Each is asked once: a device
    that speaks something else costs one timeout, not one per retry.

    ``slaves`` names the Modbus addresses to try, first to last (``slave``
    alone when it is not given). The addresses after the first are tried only
    behind a module that has shown it speaks the protocol: a Solarman logger
    by its serial number, given or learned, and any module by answering with
    a Modbus exception. A module that only stays silent may speak something
    else, and eight silences would cost eight timeouts.

    Raises ProbeError with ``cannot_connect`` when nothing took the
    connection, ``no_battery`` when something did but no BMS answered at any
    address tried, and ``not_pylontech`` when a device answered with a name
    that is not a Pylontech BMS's (the logger of an inverter, say).
    """
    addresses = list(slaves) if slaves else [slave]
    extra = EXTRA_SLAVE_TIMEOUT if extra_timeout is None else extra_timeout
    reason, detail = "cannot_connect", ""

    def note(new_reason: str, new_detail: str) -> None:
        nonlocal reason, detail
        if _RANK[new_reason] > _RANK[reason]:
            reason, detail = new_reason, new_detail

    for each_kind, each_port in order or attempts(kind, port):
        transport = make_transport(each_kind, host, each_port, addresses[0], serial, timeout,
                                   attempts=1)
        proven = False
        found: tuple[Identity, int] | None = None
        try:
            for index, address in enumerate(addresses):
                if index and not proven:
                    break
                transport.slave = address
                if index:
                    transport.timeout = max(timeout, extra)
                try:
                    identity = await read_identity(transport)
                except TransportError as err:
                    if not err.connected:
                        if reason == "cannot_connect":
                            detail = str(err)
                        break
                    note("no_battery", str(err))
                    if each_kind == SOLARMAN_V5 and (serial or getattr(transport, "serial", 0)):
                        proven = True
                    continue
                except ModbusError as err:
                    # A well-formed Modbus answer: the protocol is right, and
                    # nothing at this address has the BMS's identity block.
                    proven = True
                    note("no_battery", f"address {address}: {err}")
                    continue
                except registers.DecodeError as err:
                    note("not_pylontech", str(err))
                    break
                if not registers.is_pylontech(identity):
                    note("not_pylontech", f"{identity.brand!r} {identity.device_name!r}")
                    break
                found = (identity, address)
                break
        finally:
            await transport.close()
        if found is not None:
            learned = getattr(transport, "serial", 0)
            return ProbeResult(each_kind, each_port, learned, found[0], found[1])
    raise ProbeError(reason, detail)
