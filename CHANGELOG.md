# Changelog

## [0.1.0] - 2026-10-18

The first release: every value a Pylontech Force H1, H2 or H3 BMS has, in
Home Assistant, read only.

- **Locally through the battery's own module.** The Wi-Fi module of a Force H2
  control module and the Wi-Fi and LAN ports of a Force H3 controller are
  Solarman loggers, and they answer Modbus requests wrapped in Solarman V5 on
  port 8899. The logger's serial number, which the protocol needs, is read
  from the logger itself. Modbus TCP (port 502) and an RS485 converter on the
  BMS's RS485 port (Modbus RTU over TCP) work the same way.
- **Found on the network.** The set-up searches every network Home Assistant
  is on for Solarman loggers, asks each whether a Pylontech BMS is behind it,
  and offers the batteries by name; a logger Home Assistant sees by DHCP is
  offered on its own, and one that comes back on a new address is followed.
- **Through the Solarman cloud** when the logger cannot be reached locally:
  Solarman's OpenAPI with an app id and secret, the password stored only as
  its SHA-256 hash, and a new password asked for when Solarman refuses the old.
- **What is read:** the stack's voltage, current, power, state, charge,
  health, cycles, remaining energy, energy charged and discharged today and in
  total, its charge and discharge limits, the BMS's temperature, the highest
  and lowest cell and module with where they are, and the fully-charged flag;
  each module's voltage and temperature and its highest, lowest and spread of
  cell voltages; each cell's voltage and, disabled until switched on, its
  temperature. A Force H1 or H2 module has 15 or 30 cells, a Force H3 module
  32; the count comes from the BMS.
- **A whole reading or none.** A reading that is not plausible (a charge above
  100 %, a cell at 0 V, modules that do not add up to the stack) is refused as
  a whole; two missed polls keep the last reading, the third makes the
  entities unavailable. An energy total that jumps further than a battery can
  charge between two polls is held at its last value.
- The register map is the one verified on a Force H2 against the Solarman app
  (goodwe_manager) and the one ha-solarman reads on the H1, H2 and H3; the
  summary block is read at 0x1100 or, where the BMS does not have it, at its
  mirror 0x1400.
