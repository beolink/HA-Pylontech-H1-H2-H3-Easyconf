# Pylontech Easyconf for Home Assistant

Every value a Pylontech Force H1, H2 or H3 battery stack knows, in Home
Assistant: the stack's charge, health, cycles, voltage, current and energy,
each module's voltage and temperature, and each cell's voltage and
temperature. It reads the battery management system (BMS) itself, so the
values are the battery's own, not what an inverter passes on.

It reads and never writes. Nothing in the integration can change a setting
on the battery, and the battery's link to the inverter is not touched.

## How it reaches the battery

In this order of preference; the set-up finds the first by itself.

1. **The battery's own Wi-Fi or LAN module.** A Force H2 control module
   (FC0500M-40S) has a Wi-Fi module and a Force H3 controller (FC1000) has
   Wi-Fi and LAN ports. They are Solarman data loggers: they send the data to
   the Solarman cloud, and they also answer on the local network, on TCP port
   8899, in the Solarman V5 protocol. The integration speaks that protocol
   itself, reads the logger's serial number from the logger, and asks the BMS
   behind it for its registers.
2. **Modbus TCP**, for a logger or gateway that offers it: port 502, or 8899
   on an Elfin (High-Flying) module, as the LAN connection of one Force H3
   turned out to be.
3. **An RS485 converter** on the BMS's RS485 port (an Elfin EW11, a Waveshare
   RS485-to-Ethernet and the like, in transparent mode, 9600 baud unless the
   BMS was set to 115200), for a battery whose module cannot be reached. On a
   battery whose inverter talks CAN, as a Ferroamp EnergyHub does, the RS485
   port is free.
4. **The Solarman cloud**, when none of the above can be reached from Home
   Assistant. The values are up to five minutes old and fewer: no single
   cells. It needs an app id and an app secret for Solarman's OpenAPI, which
   Solarman's customer service gives out on request
   (customerservice@solarmanpv.com).

## Install

It needs Home Assistant 2026.5 or later.

**With HACS.** Add it as a custom repository: in HACS, the three dots at the
top right, *Custom repositories*, the address
`https://github.com/beolink/HA-Pylontech-H1-H2-H3-Easyconf` and the type
*Integration*. Then search HACS for *Pylontech Easyconf*, download it and
restart Home Assistant.

**By hand.** Copy the folder `custom_components/pylontech_easyconf` into the
`custom_components` folder of your Home Assistant configuration and restart
Home Assistant.

There is no library to install: the protocols are part of the integration.

## Setup

*Settings, Devices and services, Add integration, Pylontech Easyconf*, then
one of three:

- **Search the network.** The integration asks every Solarman logger on the
  networks Home Assistant is on who it is (a UDP broadcast on port 48899),
  and tries a connection to ports 8899 and 502 on every address of those
  networks, for a Modbus TCP gateway that answers no greeting (an Elfin
  module from High-Flying, as on one Force H3). It asks each module it found
  whether a Pylontech BMS is behind it, reading only the BMS's name, and
  offers the batteries by name. Pick one; nothing to type. A logger in front
  of an inverter is recognised as such and left out. The scan takes a few
  seconds on a home network and is skipped on a network larger than a /22.
- **Enter an address.** For a battery on another network than Home
  Assistant's, a logger that does not answer the search, or an RS485
  converter. The address, the port (8899 for the module, 502 for Modbus TCP,
  or the converter's own) and the protocol, *Automatic* by default, which
  tries the protocols in the order the port suggests. The logger's serial
  number is optional; it is read from the logger.
- **Through the Solarman cloud.** The app id, the app secret, and the account
  and password of the SOLARMAN Smart app. Only the password's SHA-256 hash is
  stored, which is what Solarman's API asks for. If the account has several
  batteries, you pick one.

Home Assistant also offers a battery by itself when it sees the battery's
module join the network (a Solarman logger, MAC 40:2A:8F or E8:FD:F8, or a
High-Flying gateway, 74:E9:D8) and a Pylontech BMS answers behind it, in
either protocol, and it follows a module that comes back on a new address.
It sees a module only when it asks for an address, which can take hours;
the search above finds it at once. *Reconfigure* on the integration's
entry sets a new address by hand.

## What you get

A device for the stack, named after its family (*Pylontech Force H2*), and a
device for each module under it (*Force H2 module 1*, ...). Modules are
numbered from 1 in the order the BMS lists them, and cells from 1 within
their module.

**The stack:** state of charge, state of health, state (charging,
discharging, idle), voltage, current and power (both positive while the
battery charges), the BMS's temperature, cycles, remaining energy, energy
charged and discharged today and in total, the highest and lowest cell
voltage (with the module and cell in the attributes) and their spread in mV,
the warmest and coldest cell, and *Fully charged*. As diagnostics: the
highest and lowest module voltage and temperature, the charge and discharge
voltage and current limits the BMS gives the inverter, and the number of
modules and cells.

**Each module:** voltage, temperature, its highest and lowest cell voltage
and their spread, and a voltage sensor for every cell. A temperature sensor
for every cell is there too, disabled: a Force module shares each
temperature sensor between several cells, so the module's temperature and
the stack's warmest and coldest cell already say almost all of it. Enable
the ones you want under the module's device.

A Force H1 module has 15 cells, a Force H2 module 15 (FH48074) or 30
(FH9637M), a Force H3 module (FH10050) 32. The count comes from the BMS, so a
module added later shows up with its cells at the next reading.

Through the cloud, the stack and the modules have what Solarman sends:
voltage, current, charge, health, cycles, state and each module's voltage
and temperature, and every other value Solarman sends for the battery, as a
diagnostic sensor under Solarman's own name.

### Options

*Configure* on the integration's entry:

- **Seconds between readings.** 60 by default locally, at least 10; the
  cloud's 300, at least 300, since Solarman has new data every five minutes.
- **Read every cell** (local only). Off, the cells' entities go and a reading
  takes four requests instead of twenty or more on a large Force H3 string; the
  modules and the stack's highest and lowest cell are still read.
- **Send anonymous usage statistics**, see below. Off stops the reporting;
  what was sent stays.

## How it behaves

- **A whole reading or none.** Every reading of a poll is checked before an
  entity sees it: a charge or health outside 0 to 100 %, a cell outside 1.5
  to 4.5 V, a temperature outside -40 to 90 degC, or modules and cells that
  do not add up to the stack's voltage refuse the whole reading.
- **A missed answer is not an outage.** A Solarman logger misses an answer
  now and then while it uploads to the cloud. Two missed polls in a row keep
  the last reading; the third makes the entities unavailable, and the next
  answer brings them back.
- **Energy totals that do not jump.** The published register scans warn that
  the BMS's total counters jump now and then. A total that climbs further
  than a battery could charge between two polls keeps its last value, and a
  lifetime total never falls.
- **One request at a time, a fresh connection after any trouble.** The
  connection to the logger stays open between polls and is opened again after
  anything goes wrong, so a logger that rebooted is picked up at the next
  poll.
- **The cloud keeps working.** The logger keeps uploading to Solarman while
  the integration reads it, and the inverter's link to the BMS (CAN or
  RS485) is a separate port.

## What is known, and what is not yet

- **The register map** is the one a Force H2 answers, verified register by
  register against the Solarman app and an inverter's telemetry
  ([goodwe_manager](https://github.com/piomar123/goodwe_manager), 2026), and
  the one [ha-solarman](https://github.com/davidrapan/ha-solarman)'s Force
  H1/H2/H3 profile reads. The tests decode that real Force H2 dump. No dump of
  a Force H1 or H3 has been published; the H3 is read the same way by
  ha-solarman's profile, and the tests use a made-up H3 string in that layout.
  The diagnostics file (below) holds the raw words of the last reading, which
  is what settles it for a battery that reads oddly.
- **Local access to a Force H3's module** is the least certain part. Owners
  report that recent Solarman logger firmwares refuse local connections. If
  the search finds the logger but no battery behind it, or the address does
  not answer on 8899, an RS485 converter or the cloud is the way.
- **Several strings in parallel** (a Force H3 system of up to six towers)
  have not been tried. The master string's BMS answers; whether it reports
  the other strings' cells is not known.
- **The current's sign through the cloud** is Solarman's, which has not been
  compared with the BMS's.

## Troubleshooting

*Settings, Devices and services, Pylontech Easyconf*, the three dots next to
the battery, *Download diagnostics*. The file says how the battery is reached,
how many requests and failures there were and the last error, and holds the
last reading with its raw register words. The address, the serial numbers,
the MAC address and the cloud credentials are taken out.

Debug logging:

```yaml
logger:
  logs:
    custom_components.pylontech_easyconf: debug
```

## Anonymous statistics

The integration sends one report per day to stats.rnet.se, as every beolink
integration does: its version, Home Assistant's version and installation
type, the country set in Home Assistant, a position rounded to about 11 km,
the battery's family, how it is reached, how many modules and cells per
module it has, its firmware, whether cell data is read, and how many polls
failed since the previous report. Never a reading, a name, an address, a
serial number or an entity name. It also sends a random id created when the
integration was installed, kept in `config/.storage/pylontech_easyconf.stats`,
so that the daily reports can be kept apart and erased on request.

It is on by default and switched off in the set-up or under *Configure*.
Switching it off stops the reporting and marks the installation as having
stopped. What has already been sent stays, and that is a deliberate choice:
the reports are anonymous, carry no free text and are stored per day, and
which installations have existed is what the statistics are for. If you want
what was sent erased anyway, ask whoever runs the service. The full list:
<https://stats.rnet.se/integritet>.

## Development

```bash
pip install -r requirements-test.txt
pytest
```

The tests need no Home Assistant: they drive the protocols over real loopback
sockets against `tests/fake_logger.py` (a Solarman logger, a Modbus TCP
gateway and an RS485 converter in one) and the cloud against
`tests/fake_cloud.py`. `scripts/smoke_real_ha.py` runs the whole integration
under a real Home Assistant against the same fakes: every set-up path, the
options, the diagnostics, an outage and a refused login.

```bash
pip install homeassistant==2026.9.4
python scripts/smoke_real_ha.py
```

The texts in `strings.json` and `translations/` are written by
`scripts/build_strings.py`; change them there.

## Credits

The register map and the Force H2 dump the tests decode come from
[goodwe_manager](https://github.com/piomar123/goodwe_manager) (MIT); the
Force H1/H2/H3 register profile and the logger's habits from
[ha-solarman](https://github.com/davidrapan/ha-solarman) (MIT); the V5
protocol from [pysolarmanv5](https://github.com/jmccrohan/pysolarmanv5)'s
documentation. The Pylontech icon and logo in the integration's `brand`
folder are Pylontech's trademarks, as Home Assistant's brands repository has
them; the white-lettered logo for dark themes is made from that one. Not
affiliated with Pylontech or Solarman.
