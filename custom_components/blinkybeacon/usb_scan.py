"""Offers each beacon plugged into a USB port that no entry names yet."""

from __future__ import annotations

from datetime import datetime
from functools import partial

from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import discovery_flow
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.hass_dict import HassKey

from .const import CONF_USB_PORT, DOMAIN, USB_SCAN_INTERVAL
from .usb_beacon import find_beacons, usb_unique_id

DATA_USB_SCAN: HassKey[UsbScan] = HassKey(f"{DOMAIN}_usb_scan")


@callback
def async_start_usb_scan(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Scan while at least one entry is loaded; unloading this one ends its part."""
    if (scan := hass.data.get(DATA_USB_SCAN)) is None:
        scan = hass.data[DATA_USB_SCAN] = UsbScan(hass)
    scan.async_add(entry.entry_id)
    entry.async_on_unload(partial(scan.async_remove, entry.entry_id))


class UsbScan:
    """Looks for unnamed beacons every few seconds while any entry is loaded."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._entry_ids: set[str] = set()
        self._cancel: CALLBACK_TYPE | None = None

    @callback
    def async_add(self, entry_id: str) -> None:
        """Count a loaded entry; the first one starts the scan."""
        self._entry_ids.add(entry_id)
        if self._cancel is None:
            self._cancel = async_track_time_interval(
                self._hass,
                self._async_scan,
                USB_SCAN_INTERVAL,
                name="BlinkyBeacon USB scan",
                cancel_on_shutdown=True,
            )

    @callback
    def async_remove(self, entry_id: str) -> None:
        """Forget an unloaded entry; the last one stops the scan."""
        self._entry_ids.discard(entry_id)
        if not self._entry_ids and self._cancel is not None:
            self._cancel()
            self._cancel = None

    async def _async_scan(self, _now: datetime) -> None:
        ports = await self._hass.async_add_executor_job(find_beacons)
        for port in ports:
            unique_id = usb_unique_id(port)
            if self._hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, unique_id
            ) or self._hass.config_entries.flow.async_progress_by_handler(
                DOMAIN,
                include_uninitialized=True,
                match_context={"unique_id": unique_id},
            ):
                continue
            discovery_flow.async_create_flow(
                self._hass,
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={CONF_USB_PORT: port},
            )
