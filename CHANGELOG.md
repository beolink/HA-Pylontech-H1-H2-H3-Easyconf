# Changelog

## [0.2.0] - 2026-11-26

- **A dashboard for the battery.** Tick *Show the battery on the Pylontech
  dashboard* under Configure and a dashboard named Pylontech appears in the
  sidebar. Its overview has the state of charge as a gauge, power, energy
  today and in total with the day's graphs, the cell balance and the BMS's
  limits; a tab has every module, with all the modules' voltages and
  temperatures in one graph each; and a tab has every cell's voltage as a
  grid per module. It is made of the cards Home Assistant ships, so there is
  nothing else to install. It is built again every time the dialog is saved
  with the box ticked, and never by itself; tabs you added yourself are kept.
  Unticked, the battery is taken off, and the dashboard goes with its last
  battery. Several batteries share the one dashboard, and two of the same
  name are told apart by the end of their serial numbers.
- **Icons** for the state, the state of health, the cycles, the cell voltage
  spread, *Fully charged* and the numbers of modules and cells, which had
  Home Assistant's eye.
- **The diagnostics file holds both summary blocks**, 0x1100 and 0x1400, read
  as the file is made. On a single tower they hold the same values; on the
  first of several towers in parallel one is the tower's own and the other
  the whole system's, and the file now shows them side by side.
- **No address in the diagnostics' error texts.** The message of a failed
  connection names the battery's address and port, and the file's two "last
  error" lines carried it; they leave it out now, as the rest of the file
  does.
- **New firmware shows on the device page** when the BMS's identity is read
  again (every six hours), without a reload of the entry.

## [0.1.6] - 2026-11-26

- **A day's energy total no longer sticks after one wrong reading.** A day's
  charge and discharge totals took any fall as the reset at midnight. One
  wrong lower reading during the day, such as another client's answer handed
  over by a shared Solarman logger, became the last value, and every true
  value after it was refused as a jump until midnight. A falling day's total
  is now held back until three readings in a row agree with it.
- **Energy moved while Home Assistant was down is counted.** The rise allowed
  between two readings went by the poll interval, not by the time that had
  passed, so after a restart a battery that had moved more than a poll's worth
  of energy was refused: a day's total until midnight, a lifetime total for
  good. The rise allowed now grows with the time since the last reading, and
  a larger one is believed once three readings in a row agree with it.
- A missed poll, which hands on the last reading, is not counted as one of
  the three. A lifetime total still never falls: a false lower value
  believed and then the true one again would count the battery's whole
  lifetime once more in the energy statistics.

## [0.1.5] - 2026-11-26

- **A second and third tower are found without knowing their Modbus
  address.** In a system of several towers each tower's BMS has a Modbus
  address of its own, and the set-up asked address 1 only: an owner of three
  towers had to find the address field before their second and third tower
  would set up (issue #1). With the field left at 1, the set-up now tries the
  addresses 1 to 8 and keeps the one that answers; the search and DHCP do
  the same; an address typed in is tried alone. The further addresses are
  tried only behind a module that has shown it speaks the protocol (a
  Solarman logger by its serial number, any module by a Modbus exception),
  so a device that speaks something else costs one wait, not eight. A
  Solarman logger stays busy about six seconds after a request to an address
  with no BMS and holds the next request until then (measured on a Force H3's
  logger), so each further address gets 7.5 s: on that logger the BMS was
  found behind two empty addresses in 13 to 18 s. A tower on address 2 takes
  about 7 s, one on address 3 about 14; a module with no BMS behind it at all
  takes about a minute to give up.
- **The right message when no BMS answers.** A Modbus exception from the
  module, which means that nothing answered on that address, was shown as
  "not a Pylontech BMS, the logger of an inverter perhaps". It is now the
  message that no BMS answered behind the module, which names the Modbus
  address and several towers. "Not a Pylontech BMS" is left for a device that
  names itself as something else.

## [0.1.4] - 2026-10-28

- **The search finds a battery behind a Modbus TCP gateway too.** On one
  Force H3 the LAN connection is a High-Flying (Elfin) module that speaks
  plain Modbus TCP on port 8899 and does not answer the Solarman loggers'
  UDP greeting, so the search never saw it and the address had to be typed.
  The search now also tries a connection to ports 8899 and 502 on every
  address of the networks Home Assistant is on (a few seconds for a home
  network, skipped above a /22), and asks whatever takes one for the BMS's
  name, read only. A logger found by its greeting is asked in its own
  protocol first and then as plain Modbus TCP.
- **DHCP knows that module.** High-Flying's MAC range 74:E9:D8 is listed, and
  a module Home Assistant sees joining the network is asked in either
  protocol, Solarman V5 first and then Modbus TCP on 502 and 8899, as an
  address typed in already was.
- **One try per protocol when probing.** Finding out what an address speaks
  asks each protocol once; the three tries per request are for polling a
  battery already set up, so a device that speaks something else costs one
  wait, not three.
- An address already set up is recognised by address and port together, so a
  second module at the same address on another port is still offered.

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
