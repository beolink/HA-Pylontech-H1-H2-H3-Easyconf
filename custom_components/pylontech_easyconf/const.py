"""Constants for Pylontech Easyconf."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "pylontech_easyconf"
NAME = "Pylontech Easyconf"
MANUFACTURER = "Pylontech"

# Config entry data.
CONF_SOURCE = "source"
SOURCE_LOCAL = "local"
SOURCE_CLOUD = "cloud"
CONF_TRANSPORT = "transport"
CONF_LOGGER_SERIAL = "logger_serial"
CONF_SLAVE = "slave"
CONF_MAC = "mac"
CONF_APP_ID = "app_id"
CONF_APP_SECRET = "app_secret"
CONF_ACCOUNT = "account"
CONF_PASSWORD = "password"  # the form field only; never stored
CONF_PASSWORD_SHA256 = "password_sha256"
CONF_ORG_ID = "org_id"
CONF_DEVICE_SN = "device_sn"
CONF_STATION_NAME = "station_name"
CONF_MODEL = "model"

# Options.
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CELL_DATA = "cell_data"
CONF_SEND_STATISTICS = "send_statistics"

DEFAULT_SLAVE = 1
DEFAULT_LOCAL_INTERVAL = 60
MIN_LOCAL_INTERVAL = 10
MAX_LOCAL_INTERVAL = 3600
DEFAULT_CLOUD_INTERVAL = 300
MIN_CLOUD_INTERVAL = 300
MAX_CLOUD_INTERVAL = 3600

#: How many polls in a row may fail before the entities go unavailable. A
#: Solarman logger misses an answer now and then while it uploads to the
#: cloud, and a value that blinks unavailable for that is noise.
FAILURES_BEFORE_UNAVAILABLE = 3

#: How often the identity (firmware, serial) is read again.
IDENTITY_REFRESH = timedelta(hours=6)

# hassfest rejects URLs in strings.json, so the addresses travel as
# placeholders instead.
STATS_PLACEHOLDERS = {
    "endpoint": "stats.rnet.se",
    "endpoint_url": "https://stats.rnet.se",
    "privacy_url": "https://stats.rnet.se/integritet",
}
CLOUD_PLACEHOLDERS = {
    "openapi_url": "https://globalapi.solarmanpv.com",
    "service_mail": "customerservice@solarmanpv.com",
}
