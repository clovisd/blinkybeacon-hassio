"""Constants for the BlinkyBeacon integration."""

from datetime import timedelta

DOMAIN = "blinkybeacon"

DEFAULT_NAME = "BlinkyBeacon"
DEFAULT_PORT = 1337

SCAN_INTERVAL = timedelta(seconds=5)
REQUEST_TIMEOUT = 10

STATE_SPIN = "spin"
STATE_FLASH = "flash"
STATE_IDLE = "idle"

MIN_DURATION = 1
MAX_DURATION = 3600
# A timed stop the beacon does not take is sent again this many times, this many
# seconds apart; then a repair names the beacon.
TIMED_STOP_RETRIES = 3
TIMED_STOP_RETRY_INTERVAL = 5

CONF_USB_PORT = "usb_port"
KEEPALIVE_INTERVAL = timedelta(seconds=5)
USB_SCAN_INTERVAL = timedelta(seconds=10)
NAMING_FLASH_TIMEOUT = timedelta(minutes=2)
