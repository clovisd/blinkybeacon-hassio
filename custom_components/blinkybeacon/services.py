"""The spin, flash and stop actions, aimed at beacon devices.

They target devices rather than the light entity because Home Assistant skips
unavailable entities in entity actions without an error, and a beacon that did
not light must show up in the automation's trace.

A call made by a user is carried out only when that user may control every
beacon chosen, as Home Assistant's own entity actions require; a call no user
made, such as an automation's, is not checked.
"""

from __future__ import annotations

import asyncio

from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
import voluptuous as vol

from .const import DOMAIN, MAX_DURATION, MIN_DURATION, STATE_FLASH, STATE_SPIN
from .coordinator import BlinkyBeaconConfigEntry, beacon_error

SERVICE_STOP = "stop"
ATTR_DEVICE_ID = "device_id"
ATTR_DURATION = "duration"

_DEVICES = vol.All(cv.ensure_list, [cv.string])
START_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): _DEVICES,
        vol.Optional(ATTR_DURATION): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_DURATION, max=MAX_DURATION)
        ),
    }
)
STOP_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): _DEVICES})


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""
    for service, schema in (
        (STATE_SPIN, START_SCHEMA),
        (STATE_FLASH, START_SCHEMA),
        (SERVICE_STOP, STOP_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, service, _async_handle, schema=schema)


async def _async_handle(call: ServiceCall) -> None:
    """Send the command to every chosen beacon; raise if any did not take it."""
    entries = _entries(call.hass, call.data[ATTR_DEVICE_ID])
    await _async_check_control(call, entries)
    results = await asyncio.gather(
        *(_async_command(entry, call) for entry in entries), return_exceptions=True
    )
    failed: list[tuple[ConfigEntry, HomeAssistantError]] = []
    for entry, result in zip(entries, results, strict=True):
        if isinstance(result, HomeAssistantError):
            failed.append((entry, result))
        elif isinstance(result, BaseException):
            raise result
    if not failed:
        return
    if len(entries) == 1:
        raise failed[0][1]
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="commands_failed",
        translation_placeholders={"names": ", ".join(e.title for e, _ in failed)},
    )


async def _async_check_control(
    call: ServiceCall, entries: list[BlinkyBeaconConfigEntry]
) -> None:
    """Refuse a call made by a user who may not control every beacon chosen.

    A call no user made is not checked, and an administrator may control
    everything. Any other user must hold Home Assistant's control permission on
    every entity of every beacon chosen. Raises Unauthorized, before any
    command is sent, for the first entity that user may not control, for a
    beacon with no entity to hold it on, and for a user who is not there.
    """
    if not call.context.user_id:
        return
    user = await call.hass.auth.async_get_user(call.context.user_id)
    if user is None:
        raise UnknownUser(context=call.context, permission=POLICY_CONTROL)
    if user.is_admin:
        return
    entity_registry = er.async_get(call.hass)
    for entry in entries:
        entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        if not entities:
            raise Unauthorized(
                context=call.context,
                config_entry_id=entry.entry_id,
                permission=POLICY_CONTROL,
            )
        for entity in entities:
            if not user.permissions.check_entity(entity.entity_id, POLICY_CONTROL):
                raise Unauthorized(
                    context=call.context,
                    entity_id=entity.entity_id,
                    permission=POLICY_CONTROL,
                )


async def _async_command(entry: BlinkyBeaconConfigEntry, call: ServiceCall) -> None:
    if entry.state is not ConfigEntryState.LOADED:
        raise beacon_error(entry, "cannot_reach")
    await entry.runtime_data.async_command(call.service, call.data.get(ATTR_DURATION))


def _entries(
    hass: HomeAssistant, device_ids: list[str]
) -> list[BlinkyBeaconConfigEntry]:
    """The beacon entry behind each device, in order, each once."""
    device_registry = dr.async_get(hass)
    by_device = {
        device.id: entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    }
    entries: dict[str, BlinkyBeaconConfigEntry] = {}
    for device_id in device_ids:
        if (entry := by_device.get(device_id)) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_device",
                translation_placeholders={"device_id": device_id},
            )
        entries.setdefault(entry.entry_id, entry)
    return list(entries.values())
