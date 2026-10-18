# Changelog

## [0.1.3] - 2026-10-18

- **Two more tries, after a pause, for a request the logger drops.** On the
  second house, where ha-solarman polls the same logger every five seconds,
  6 % of requests were dropped, and a try straight after a miss failed more
  often than chance: one reading in ten still failed on 0.1.2. A chunk is now
  asked for up to three times, with a short random pause that grows between
  tries. The logger also handed one client the other's answer once; the
  length check refused it, as it must.
- **Pylontech's own icon and logo** in the integration's `brand` folder, where
  Home Assistant 2026.3 and later read them, with a white-lettered logo for
  dark themes. The HACS action runs with no check switched off.

## [0.1.2] - 2026-10-18

- **A search by hand is no longer stopped by a discovery.** When Home
  Assistant had already found the battery by DHCP and the discovery was
  waiting in the list, setting the battery up by hand through the network
  search, an address or the cloud ended in "already in progress". Now the
  owner's own choice goes through and Home Assistant closes the waiting
  discovery. Found on the first house the integration was installed on.
- **A request the logger drops is asked again.** A Solarman logger passes one
  request at a time to the battery and drops one when two clients ask at the
  same moment, which on a Force H2 that ha-solarman also polls every five
  seconds happened within the first reading. One dropped request no longer
  fails the whole reading: it is asked once more on a new connection. The
  diagnostics count the retries.
- **Verified on a real Force H2** of five FH9637M modules, 150 cells: the cells
  add up to 499.60 V, the modules to 499.57 V and the stack reads 499.6 V.

## [0.1.1] - 2026-10-18

- **Found by DHCP on a Force H3.** The Wi-Fi module of a Force H3 has a MAC
  address from 40:2A:8F, not from the Solarman range the manifest listed, so
  Home Assistant never offered the battery when the module joined the
  network. Both ranges are listed now.
- **A real Force H3 in the tests.** Six modules, 192 cells, read through its
  own Wi-Fi module on 2026-10-18: the register map holds on the H3 as on the
  H2, the cells add up to 640.37 V, the modules to 640.36 V and the stack reads
  640.3 V.

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
