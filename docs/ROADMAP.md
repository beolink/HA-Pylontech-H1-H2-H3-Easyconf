# Roadmap

Where Pylontech Easyconf goes from 0.2.0, in the order it is meant to be
done, and what a review of the whole integration found in November 2026.
Nothing here is promised by a date. An item moves up when an owner of the
hardware it concerns can send a diagnostics file for it.

## What the review found

The review read every module of the integration against what the four
batteries it runs on have shown since October (one Force H2, three Force H3,
behind Solarman loggers and one Modbus TCP gateway).

Mended in 0.2.0:

- The diagnostics file could name the battery's address: the text of a failed
  connection carries it, and the two "last error" lines passed it on.
- New firmware on the BMS did not reach the device page until the entry was
  reloaded.
- Six sensors had no icon of their own.

Open, and on the list below:

- **The first tower of several in parallel shows the whole system's totals**
  as its own (1).
- **A module that is not a Pylontech battery is asked again at every start of
  Home Assistant**, for up to a minute since 0.1.5 (5).
- **The anonymous statistics are on unless switched off**, which the HACS
  default list does not accept (9).
- **A module taken out of the stack leaves its devices behind** (11).
- **"Charged today" and "Discharged today" follow the BMS's clock, not the
  house's:** they start again at about five in the afternoon, Swedish time
  (14).
- The network search shows nothing while it works, and can take a minute (7).
- The Home Assistant side is tested by the smoke script alone (12).

Sound, and left as it is: the protocol code (Solarman V5, Modbus TCP, RTU
over TCP) with its three tries per request, the plausibility check that
refuses a whole reading rather than show a garbled one, the energy counters'
guard (0.1.6), and reading without ever writing.

## 1. Towers in parallel

An owner of three Force H3 towers found that the first tower's BMS keeps two
summary blocks: 0x1400 with the tower's own values and 0x1100 with the whole
system's, with the number of towers in word 0x31 and the highest and lowest
cell given as tower × 1000 + index (issue #1, pull request #2). On our four
single towers the two blocks hold the same values, word 0x31 is 1 in 0x1100
and 0 in 0x1400.

1. **Read the tower's own block first** (0x1400, then 0x1100), so the first
   tower shows its own charge, current and energy. Safe on a single tower.
2. **A System device on the first tower's entry** when 0x1100 names more than
   one tower: the system's charge, power, energy and limits, read with the
   same connection, with the highest and lowest cell located by tower. No
   second entry and no second connection.
3. **Towers told apart by name.** Three towers of one family are three
   devices called *Pylontech Force H3* today. Word 0x30 of 0x1400 is 1 on a
   second tower and 0 on every single tower seen, so it may be the tower's
   number; until that is known, the Modbus address.
4. **Refuse an answer meant for another block:** a tower's block that carries
   a tower count above 1, or tower × 1000 indices. And read 0x1100 in chunks
   of another size than 0x1400, so that a logger that hands one client
   another's answer is caught by the length.

Waiting for: the raw words of both blocks from a first tower in parallel,
and from a third tower. The diagnostics file holds both blocks since 0.2.0.

## 2. Quiet on a shared network

5. **Remember what is not a battery.** Home Assistant hands the integration
   every network module it sees in the manifest's three MAC ranges, again
   after each start. Those ranges also hold the loggers of inverters and the
   RS485 gateways of other devices. Each is asked for a Pylontech
   BMS; since 0.1.5, when the module speaks the protocol and nothing answers
   on address 1, the addresses 2 to 8 are tried too, 7.5 s each, which keeps
   a logger busy for most of a minute. A module that turned out not to be a
   battery should be remembered by its MAC and left alone for a month.
6. **Stop the address search on a real refusal.** A device that answers
   address 1 with "illegal data address" is there and is not a Force BMS; a
   gateway that answers "target failed to respond" has nobody on that
   address. Which of the two a tower's module gives is not known yet.
7. **Show the search working.** The search can take a minute and shows a
   spinner. Home Assistant's progress step would say what it is doing.
8. **Step aside for another client.** Where ha-solarman polls the same
   logger every few seconds, 2 to 6 % of requests are dropped and asked
   again. A poll could wait out the other client's run of requests, and a
   repair notice could say so when the share of retries stays high.

## 3. Fit for the HACS default list

9. **Statistics asked for, not assumed.** Off by default in every set-up
   form and off for installations that never chose. The same change in the
   client shared by the beolink integrations.
10. **A repair notice for a battery that stays away**, naming what to try:
    the logger refuses local connections (recent Force H3 firmwares), an
    RS485 converter, the cloud.
11. **A module taken out is taken away:** its device and entities removed
    when the BMS has reported fewer modules for a day, and the device page's
    own Delete for what is no longer reported.
12. **The Home Assistant side in pytest** (pytest-homeassistant-custom-component)
    beside the smoke script, a `quality_scale.yaml`, and the messages of
    errors raised to the user translated.

## 4. More of what the BMS knows

13. **Rated capacity.** Words 0x3A and 0x3B of 0x1400 are the stack's nominal
    voltage (0.1 V) and its capacity (Ah) on all four batteries: 614.4 V and
    50 Ah for six FH10050 modules (30.72 kWh), 512.0 V and 50 Ah for five
    (25.6 kWh), 480.0 V and 37 Ah for five FH9637M (17.76 kWh). Two sensors,
    and with them the remaining energy as a share of what the battery was
    built for.
14. **A day that is the house's.** The BMS's two "today" counters go back
    to zero by the BMS's own clock: at about 15:42, 16:07, 16:12 and 16:17
    UTC on the four batteries, each at the same time two days running, which
    is around midnight in China and five in the afternoon in Sweden.
    The sensors show what the BMS reports, so their "today" runs from five to
    five. Two sensors of the integration's own would add up what the BMS's
    counters gain and start again at midnight where Home Assistant is, kept
    over a restart, with the BMS's own counters left as they are. Whether
    the BMS's clock can be read, or set, is not known.
15. **Alarms and protections.** The bits of the status word above the state,
    and the two words after it, are read into the diagnostics and not shown.
    A binary sensor for an alarm and one for a protection, with the cause
    in the attributes, once the bits are mapped against a battery that has
    raised one.
16. **What follows from the readings:** time to full and to empty at the
    present power, the round-trip efficiency from the two lifetime totals,
    the temperature spread, and the day's highest cell spread.
17. **Blueprints** for the things an owner wants to hear about: a cell
    spread above a limit, a health that fell, a temperature out of range.

## 5. The dashboard

18. **A picture of the cells** in place of 192 numbers: a small card of the
    integration's own that draws each module's cells as bars between the
    lowest and the highest, the outliers marked.
19. **Built again when a release changes the layout**, for those who ask for
    it in the options, with tabs changed by hand left alone.
20. **A System tab** for towers in parallel, with (2).
21. **Names in the viewer's language.** The tiles carry the names Home
    Assistant registered, which are in the server's language.
22. **A button and an action** that build the dashboard, for those who
    automate.

## 6. Hardware not seen yet

23. **A real RS485 converter.** RTU over TCP is tested against a fake only.
24. **A Force H1.** No dump of one has been published; its layout is assumed
    to be the Force H2's.
25. **The cloud's sign of the current**, compared with the BMS's.

## Not planned

- **Writing to the battery.** The integration reads, and holds no function
  that could change a setting.
- **Pylontech's low-voltage batteries** (US2000, US5000 and the like), which
  speak another protocol on another port.
