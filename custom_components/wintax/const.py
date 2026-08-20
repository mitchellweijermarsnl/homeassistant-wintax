"""Constants for the WinTax custom integration."""

from datetime import timedelta
from typing import Final
from zoneinfo import ZoneInfo

DOMAIN: Final = "wintax"

# Confirmed from the live UVO Vervoer customer portal login page.
DEFAULT_BASE_URL: Final = "https://uvovervoer.customer.wintax.nl:40083"
CLIENT_BASE_PATH: Final = "/client"

LOGIN_PAGE: Final = "user.wts"
LOGIN_MODE: Final = "login"
LOGIN_POST_MODE: Final = "login_post"
RIDES_PAGE: Final = "index.wts"
MAP_PAGE: Final = "map.wts"

# WinTax login form field names (from user.wts?m=login).
LOGIN_USERNAME_FIELD: Final = "u"
LOGIN_PASSWORD_FIELD: Final = "p"

DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=60)
MIN_SCAN_INTERVAL_SECONDS: Final = 30
MAX_SCAN_INTERVAL_SECONDS: Final = 3600

# Fetch a window around "now" so we can pick an active, upcoming, or recent ride
# without requesting the entire month on every poll.
RIDE_LOOKBACK_DAYS: Final = 1
RIDE_LOOKAHEAD_DAYS: Final = 14

HTTP_TIMEOUT_SECONDS: Final = 30

# WinTax stores and displays times in the Netherlands.
DEFAULT_TIMEZONE: Final = ZoneInfo("Europe/Amsterdam")

CONF_BASE_URL: Final = "base_url"

# Labels that describe ride metadata rather than live status.
METADATA_LABEL_PREFIXES: Final = (
    "starttijd",
    "eindtijd",
    "berekende voorrijtijd",
)
METADATA_LABELS: Final = frozenset(
    {
        "samenstelling",
        "retour",
    }
)

# Statuses that indicate the vehicle is currently executing the ride.
# Keep this list conservative; only labels actually observed in WinTax HTML.
ACTIVE_STATUS_KEYWORDS: Final = (
    "onderweg",
)

ATTRIBUTION: Final = "Data provided by WinTax"
MANUFACTURER: Final = "Beedr"
MODEL: Final = "WinTax customer portal"
