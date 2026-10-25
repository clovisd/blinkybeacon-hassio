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
