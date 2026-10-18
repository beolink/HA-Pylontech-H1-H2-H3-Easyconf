#!/usr/bin/env python3
"""Write strings.json and the translations from the texts below.

strings.json and translations/en.json are the English texts, the same file
twice as Home Assistant wants it; translations/sv.json is the Swedish. Kept
in one place so the three never drift apart: change a text here and run

    python3 scripts/build_strings.py

``--check`` exits non-zero when the files on disk differ from what this
script would write, which is what the tests run.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "pylontech_easyconf"

STATS = {
    "en": (
        "One report per day to {endpoint}: the integration's version, Home Assistant's version "
        "and installation type, the country you configured in Home Assistant, an approximate "
        "position rounded to about 11 km, the battery family (Force H1, H2 or H3), how it is "
        "reached (Wi-Fi or LAN module, Modbus TCP, RS485 converter or the Solarman cloud), how "
        "many modules and cells per module it has, its firmware, whether cell data is read, and "
        "how many polls failed since the last report. No reading: no voltage, no charge, no "
        "temperature. Never a name, an address, an exact position, a serial number or an entity "
        "name, and your IP address is not stored. It also sends a random id created when the "
        "integration was installed, so that the daily reports can be kept apart and erased on "
        "request (the server keeps it only as a hash, and it says nothing about who you are), a "
        "hash that links the beolink plugins running on the same Home Assistant, how many warnings "
        "and errors the integration logged since the previous report, and whether it is running or "
        "waiting to start again, never the messages themselves or the reason. Switching this off "
        "stops the reporting, and the installation is marked as having stopped. What has already "
        "been sent stays: it is anonymous, carries no free text and is stored per day, and which "
        "installations have existed is what the statistics are for. Erasure on request, from "
        "whoever runs the service. The full list: {privacy_url}"
    ),
    "sv": (
        "En rapport per dygn till {endpoint}: integrationens version, Home Assistants version och "
        "installationstyp, landet du angett i Home Assistant, en ungefärlig position avrundad till "
        "ungefär 11 km, batteriets familj (Force H1, H2 eller H3), hur det nås (wifi- eller "
        "LAN-modul, Modbus TCP, RS485-omvandlare eller Solarman-molnet), hur många moduler och "
        "celler per modul det har, dess firmware, om celldata läses och hur många avläsningar som "
        "misslyckats sedan förra rapporten. Inga mätvärden: ingen spänning, ingen laddning, ingen "
        "temperatur. Aldrig ett namn, en adress, en exakt position, ett serienummer eller ett "
        "entitetsnamn, och din IP-adress sparas inte. Dessutom skickas ett slumpat id som skapas vid "
        "installationen, så att dygnsrapporterna kan hållas isär och raderas på begäran (servern "
        "sparar det bara som en hash, och det säger inget om vem du är), en hash som knyter ihop "
        "beolinks tillägg på samma Home Assistant, hur många varningar och fel integrationen loggat "
        "sedan förra rapporten, och om den är igång eller väntar på att starta igen, aldrig själva "
        "meddelandena eller skälet. Stänger du av den slutar rapporteringen, och installationen "
        "märks som avanmäld. Det som redan skickats står kvar: det är anonymt, bär ingen fritext och "
        "lagras per dygn, och vilka anläggningar som funnits är det statistiken är till för. "
        "Radering på begäran, av den som driver tjänsten. Hela listan: {privacy_url}"
    ),
}

STATS_LABEL = {"en": "Send anonymous usage statistics", "sv": "Skicka anonym användningsstatistik"}

ERRORS = {
    "en": {
        "cannot_connect": "Nothing answered at that address and port. Check the address, and that Home Assistant can reach that network.",
        "no_battery": "Something answered at that address, but no battery answered behind it. Is the battery switched on, and is the Modbus address right (1 unless it was changed)?",
        "not_pylontech": "A device answered, but it is not a Pylontech BMS. It may be the logger of an inverter.",
        "invalid_serial": "The logger's serial number is digits only. Leave it empty to have it read from the logger.",
        "invalid_auth": "Solarman refused the app id, the app secret or the account.",
        "cloud_unreachable": "The Solarman cloud did not answer. Try again in a while.",
        "no_cloud_battery": "The account has no battery in the Solarman cloud.",
    },
    "sv": {
        "cannot_connect": "Inget svarade på den adressen och porten. Kontrollera adressen och att Home Assistant når det nätet.",
        "no_battery": "Något svarade på adressen, men inget batteri svarade bakom det. Är batteriet påslaget, och stämmer Modbus-adressen (1 om den inte ändrats)?",
        "not_pylontech": "En enhet svarade, men det är ingen Pylontech-BMS. Det kan vara loggaren till en växelriktare.",
        "invalid_serial": "Loggarens serienummer består bara av siffror. Lämna fältet tomt så läses det från loggaren.",
        "invalid_auth": "Solarman godtog inte app-id, app-hemlighet eller kontot.",
        "cloud_unreachable": "Solarman-molnet svarade inte. Försök igen om en stund.",
        "no_cloud_battery": "Kontot har inget batteri i Solarman-molnet.",
    },
}

ABORTS = {
    "en": {
        "already_configured": "This battery is already set up.",
        "already_in_progress": "This battery is already being set up.",
        "not_pylontech": "No Pylontech battery answered at this address.",
        "reauth_successful": "The new credentials work.",
        "reconfigure_successful": "The battery's new address is saved.",
        "another_battery": "A different battery answered at that address than the one set up here.",
        "reconfigure_cloud": "A battery read through the cloud has no address to change. If the password or secret changed, Home Assistant asks for them by itself.",
    },
    "sv": {
        "already_configured": "Det här batteriet är redan konfigurerat.",
        "already_in_progress": "Det här batteriet håller redan på att konfigureras.",
        "not_pylontech": "Inget Pylontech-batteri svarade på den här adressen.",
        "reauth_successful": "De nya uppgifterna fungerar.",
        "reconfigure_successful": "Batteriets nya adress är sparad.",
        "another_battery": "Ett annat batteri svarade på adressen än det som är konfigurerat här.",
        "reconfigure_cloud": "Ett batteri som läses via molnet har ingen adress att ändra. Har lösenordet eller hemligheten ändrats frågar Home Assistant efter dem av sig själv.",
    },
}

MANUAL_DATA = {
    "en": {
        "host": "Address",
        "port": "Port",
        "transport": "Protocol",
        "logger_serial": "Logger serial number (optional)",
        "slave": "Modbus address of the BMS",
    },
    "sv": {
        "host": "Adress",
        "port": "Port",
        "transport": "Protokoll",
        "logger_serial": "Loggarens serienummer (valfritt)",
        "slave": "BMS:ens Modbus-adress",
    },
}
MANUAL_HELP = {
    "en": {
        "host": "The IP address or name of the battery's Wi-Fi or LAN module, or of the converter on its RS485 port.",
        "port": "8899 for the Wi-Fi or LAN module (Solarman), 502 for Modbus TCP, or the converter's own port.",
        "transport": "Automatic tries Solarman, Modbus TCP and RTU over TCP in the order the port suggests.",
        "logger_serial": "Only for the Solarman protocol, and read from the logger when left empty.",
        "slave": "1 unless the installer changed it.",
    },
    "sv": {
        "host": "IP-adressen eller namnet på batteriets wifi- eller LAN-modul, eller på omvandlaren på dess RS485-port.",
        "port": "8899 för wifi- eller LAN-modulen (Solarman), 502 för Modbus TCP, eller omvandlarens egen port.",
        "transport": "Automatiskt provar Solarman, Modbus TCP och RTU över TCP i den ordning porten antyder.",
        "logger_serial": "Bara för Solarman-protokollet, och läses från loggaren om fältet lämnas tomt.",
        "slave": "1 om installatören inte ändrat den.",
    },
}

CLOUD_DATA = {
    "en": {
        "app_id": "App id",
        "app_secret": "App secret",
        "account": "Account (e-mail or user name)",
        "password": "Password",
        "org_id": "Organisation id (business accounts only)",
    },
    "sv": {
        "app_id": "App-id",
        "app_secret": "App-hemlighet",
        "account": "Konto (e-post eller användarnamn)",
        "password": "Lösenord",
        "org_id": "Organisations-id (bara företagskonton)",
    },
}
CLOUD_HELP = {
    "en": {
        "password": "Only its SHA-256 hash is stored, which is what Solarman's API asks for.",
        "org_id": "Leave empty for a private SOLARMAN Smart account.",
    },
    "sv": {
        "password": "Bara dess SHA-256-hash sparas, vilket är vad Solarmans API vill ha.",
        "org_id": "Lämna tomt för ett privat SOLARMAN Smart-konto.",
    },
}


def config(lang: str) -> dict:
    stats = {"send_statistics": STATS[lang]}
    stats_data = {"send_statistics": STATS_LABEL[lang]}
    en = lang == "en"
    return {
        "flow_title": "{name}",
        "step": {
            "user": {
                "title": "Pylontech Force",
                "description": (
                    "How should Home Assistant reach the battery?" if en
                    else "Hur ska Home Assistant nå batteriet?"
                ),
                "menu_options": {
                    "discover": "Search the network for the battery's Wi-Fi or LAN module" if en
                    else "Sök på nätverket efter batteriets wifi- eller LAN-modul",
                    "manual": "Enter an address" if en else "Ange en adress",
                    "cloud": "Through the Solarman cloud" if en else "Via Solarman-molnet",
                },
            },
            "discover_none": {
                "title": "No battery found" if en else "Inget batteri hittades",
                "description": (
                    "{loggers} Solarman loggers answered the search, and none had a Pylontech BMS "
                    "behind it that is not set up already. Next you can enter an address by hand: "
                    "that of the battery's Wi-Fi or LAN module, or of a converter on its RS485 port."
                    if en else
                    "{loggers} Solarman-loggare svarade på sökningen, och ingen hade en Pylontech-BMS "
                    "bakom sig som inte redan är konfigurerad. Härnäst kan du ange en adress för hand: "
                    "den till batteriets wifi- eller LAN-modul, eller till en omvandlare på dess RS485-port."
                ),
            },
            "pick": {
                "title": "Batteries found" if en else "Hittade batterier",
                "description": (
                    "{count} Pylontech batteries answered. Pick the one to set up; set up the others "
                    "the same way afterwards." if en else
                    "{count} Pylontech-batterier svarade. Välj det som ska konfigureras; de andra "
                    "konfigureras på samma sätt efteråt."
                ),
                "data": {"battery": "Battery" if en else "Batteri", **stats_data},
                "data_description": stats,
            },
            "manual": {
                "title": "Battery address" if en else "Batteriets adress",
                "description": (
                    "The battery's control module has a Wi-Fi module (Force H2) or Wi-Fi and LAN "
                    "ports (Force H3), which answer on port 8899. A converter on the BMS's RS485 "
                    "port answers on its own port." if en else
                    "Batteriets styrenhet har en wifi-modul (Force H2) eller wifi- och LAN-portar "
                    "(Force H3), som svarar på port 8899. En omvandlare på BMS:ens RS485-port svarar "
                    "på sin egen port."
                ),
                "data": {**MANUAL_DATA[lang], **stats_data},
                "data_description": {**MANUAL_HELP[lang], **stats},
            },
            "dhcp_confirm": {
                "title": "{name}",
                "description": (
                    "A {name} answered at {host}. Set it up?" if en
                    else "Ett {name} svarade på {host}. Konfigurera det?"
                ),
                "data": stats_data,
                "data_description": stats,
            },
            "cloud": {
                "title": "Solarman cloud" if en else "Solarman-molnet",
                "description": (
                    "The second way in, when the battery's logger cannot be reached on the local "
                    "network. The data is at most five minutes old and has fewer values than the "
                    "local way: no single cells. Solarman's OpenAPI ({openapi_url}) needs an app id "
                    "and an app secret, which Solarman's customer service ({service_mail}) gives "
                    "out on request, besides the account you use in the SOLARMAN Smart app." if en else
                    "Andra vägen in, när batteriets loggare inte nås på det lokala nätet. Datan är "
                    "upp till fem minuter gammal och har färre värden än den lokala vägen: inga "
                    "enskilda celler. Solarmans OpenAPI ({openapi_url}) kräver ett app-id och en "
                    "app-hemlighet, som Solarmans kundtjänst ({service_mail}) lämnar ut på begäran, "
                    "utöver kontot du använder i appen SOLARMAN Smart."
                ),
                "data": {**CLOUD_DATA[lang], **stats_data},
                "data_description": {**CLOUD_HELP[lang], **stats},
            },
            "cloud_pick": {
                "title": "Batteries in the cloud" if en else "Batterier i molnet",
                "description": (
                    "The account has several batteries. Pick the one to set up." if en
                    else "Kontot har flera batterier. Välj det som ska konfigureras."
                ),
                "data": {"battery": "Battery" if en else "Batteri"},
            },
            "reauth_confirm": {
                "title": "Solarman cloud" if en else "Solarman-molnet",
                "description": (
                    "Solarman no longer accepts the credentials of {account}. Enter the app secret "
                    "and the password again." if en else
                    "Solarman godtar inte längre uppgifterna för {account}. Ange app-hemligheten "
                    "och lösenordet igen."
                ),
                "data": {"app_secret": CLOUD_DATA[lang]["app_secret"],
                         "password": CLOUD_DATA[lang]["password"]},
            },
            "reconfigure": {
                "title": "Battery address" if en else "Batteriets adress",
                "description": (
                    "A new address for the same battery, for example after the module got a new "
                    "IP address." if en else
                    "En ny adress för samma batteri, till exempel när modulen fått en ny IP-adress."
                ),
                "data": MANUAL_DATA[lang],
                "data_description": MANUAL_HELP[lang],
            },
        },
        "error": ERRORS[lang],
        "abort": ABORTS[lang],
    }


def options(lang: str) -> dict:
    en = lang == "en"
    return {
        "step": {
            "init": {
                "title": "Pylontech Easyconf",
                "data": {
                    "scan_interval": "Seconds between readings" if en else "Sekunder mellan avläsningar",
                    "cell_data": "Read every cell" if en else "Läs varje cell",
                    "send_statistics": STATS_LABEL[lang],
                },
                "data_description": {
                    "scan_interval": (
                        "Locally 10 seconds at the least; the cloud has new data every five minutes."
                        if en else
                        "Lokalt minst 10 sekunder; molnet har nya data var femte minut."
                    ),
                    "cell_data": (
                        "Each cell's voltage and temperature. Off, the modules and the stack's "
                        "highest and lowest cell are still read, with far fewer requests to the logger."
                        if en else
                        "Varje cells spänning och temperatur. Avstängt läses modulerna och stapelns "
                        "högsta och lägsta cell ändå, med betydligt färre frågor till loggaren."
                    ),
                    "send_statistics": STATS[lang],
                },
            }
        }
    }


SELECTOR = {
    "en": {"auto": "Automatic", "solarman_v5": "Solarman (Wi-Fi or LAN module)",
           "modbus_tcp": "Modbus TCP", "rtu_over_tcp": "Modbus RTU over TCP (RS485 converter)"},
    "sv": {"auto": "Automatiskt", "solarman_v5": "Solarman (wifi- eller LAN-modul)",
           "modbus_tcp": "Modbus TCP", "rtu_over_tcp": "Modbus RTU över TCP (RS485-omvandlare)"},
}

WHERE = {
    "en": {"module": "Module", "cell": "Cell"},
    "sv": {"module": "Modul", "cell": "Cell"},
}

SENSORS = {
    # key: (en, sv, has the module/cell attributes)
    "soc": ("State of charge", "Laddningsnivå", False),
    "soh": ("State of health", "Batterihälsa", False),
    "voltage": ("Voltage", "Spänning", False),
    "current": ("Current", "Ström", False),
    "power": ("Power", "Effekt", False),
    "bms_temperature": ("BMS temperature", "BMS-temperatur", False),
    "cycles": ("Cycles", "Cykler", False),
    "remaining_energy": ("Remaining energy", "Kvarvarande energi", False),
    "charge_today": ("Charged today", "Laddat i dag", False),
    "discharge_today": ("Discharged today", "Urladdat i dag", False),
    "charge_total": ("Charged in total", "Laddat totalt", False),
    "discharge_total": ("Discharged in total", "Urladdat totalt", False),
    "cell_voltage_max": ("Highest cell voltage", "Högsta cellspänning", True),
    "cell_voltage_min": ("Lowest cell voltage", "Lägsta cellspänning", True),
    "cell_voltage_spread": ("Cell voltage spread", "Cellspridning", False),
    "cell_temperature_max": ("Warmest cell", "Varmaste cell", True),
    "cell_temperature_min": ("Coldest cell", "Kallaste cell", True),
    "module_voltage_max": ("Highest module voltage", "Högsta modulspänning", True),
    "module_voltage_min": ("Lowest module voltage", "Lägsta modulspänning", True),
    "module_temperature_max": ("Warmest module", "Varmaste modul", True),
    "module_temperature_min": ("Coldest module", "Kallaste modul", True),
    "charge_voltage_limit": ("Charge voltage limit", "Gräns för laddspänning", False),
    "charge_current_limit": ("Charge current limit", "Gräns för laddström", False),
    "discharge_voltage_limit": ("Discharge voltage limit", "Gräns för urladdningsspänning", False),
    "discharge_current_limit": ("Discharge current limit", "Gräns för urladdningsström", False),
    "module_count": ("Modules", "Moduler", False),
    "cell_count": ("Cells", "Celler", False),
    "module_voltage": ("Voltage", "Spänning", False),
    "module_temperature": ("Temperature", "Temperatur", False),
    "cell_voltage": ("Cell {cell} voltage", "Cell {cell} spänning", False),
    "cell_temperature": ("Cell {cell} temperature", "Cell {cell} temperatur", False),
}

STATES = {
    "en": {"charging": "Charging", "discharging": "Discharging", "idle": "Idle"},
    "sv": {"charging": "Laddar", "discharging": "Laddar ur", "idle": "Vilar"},
}


def entity(lang: str) -> dict:
    index = 0 if lang == "en" else 1
    sensors: dict[str, dict] = {}
    for key, (en, sv, where) in SENSORS.items():
        item: dict = {"name": (en, sv)[index]}
        if where:
            item["state_attributes"] = {k: {"name": v} for k, v in WHERE[lang].items()}
        sensors[key] = item
    sensors["state"] = {"name": ("State", "Läge")[index], "state": STATES[lang]}
    return {
        "sensor": dict(sorted(sensors.items())),
        "binary_sensor": {"fully_charged": {"name": ("Fully charged", "Fulladdat")[index]}},
    }


def device(lang: str) -> dict:
    return {"module": {"name": "{model} module {number}" if lang == "en" else "{model} modul {number}"}}


def build(lang: str) -> dict:
    return {
        "config": config(lang),
        "options": options(lang),
        "selector": {"transport": {"options": SELECTOR[lang]}},
        "entity": entity(lang),
        "device": device(lang),
    }


def files() -> dict[Path, str]:
    def dump(data: dict) -> str:
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    en = dump(build("en"))
    return {
        PACKAGE / "strings.json": en,
        PACKAGE / "translations" / "en.json": en,
        PACKAGE / "translations" / "sv.json": dump(build("sv")),
    }


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for path, text in files().items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    for path in stale:
        print(f"{path.relative_to(ROOT)} is not what scripts/build_strings.py writes")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
