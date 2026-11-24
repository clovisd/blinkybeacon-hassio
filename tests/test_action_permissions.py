"""Tests for who may call the spin, flash and stop actions.

A call made by a user is carried out only when that user may control every
beacon chosen, as Home Assistant's own entity actions require; a call no user
made is carried out as before.
"""

from __future__ import annotations

from homeassistant.auth.const import (
    GROUP_ID_ADMIN,
    GROUP_ID_READ_ONLY,
    GROUP_ID_USER,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized, UnknownUser
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockUser
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blinkybeacon.const import DOMAIN

from .conftest import BASE, PORT, setup_integration, status_json
from .fake_usb import FakeUsb

AWAY = "http://192.0.2.11:1337"
ACTIONS = ("spin", "flash", "stop")


def _device_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    return dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)[0].id


def _entity_ids(hass: HomeAssistant, entry: MockConfigEntry) -> list[str]:
    found = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
    ]
    assert found
    return found


async def _add_tray(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    entry: MockConfigEntry,
    base: str,
) -> str:
    """Set up a beacon whose tray obeys; return its device id."""
    aioclient_mock.get(f"{base}/status", json=status_json())
    aioclient_mock.post(f"{base}/spin", json=status_json("spin"))
    aioclient_mock.post(f"{base}/flash", json=status_json("flash"))
    aioclient_mock.post(f"{base}/stop", json=status_json("idle"))
    await setup_integration(hass, entry)
    return _device_id(hass, entry)


@pytest.fixture
async def home(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> str:
    """The home beacon's device id."""
    return await _add_tray(hass, aioclient_mock, mock_config_entry, BASE)


@pytest.fixture
def away_entry() -> MockConfigEntry:
    """A config entry for the away team's beacon."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Away beacon",
        data={"host": "192.0.2.11", "port": PORT},
        unique_id="192.0.2.11:1337",
    )


@pytest.fixture
async def away(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    away_entry: MockConfigEntry,
) -> str:
    """The away beacon's device id."""
    return await _add_tray(hass, aioclient_mock, away_entry, AWAY)


def _commands(aioclient_mock: AiohttpClientMocker) -> list[str]:
    """Every command sent to a tray, as its URL."""
    return [
        str(url) for method, url, *_ in aioclient_mock.mock_calls if method == "POST"
    ]


async def _in_group(hass: HomeAssistant, group_id: str) -> str:
    """The id of a new user of one of Home Assistant's own groups."""
    group = await hass.auth.async_get_group(group_id)
    assert group is not None
    return MockUser(groups=[group]).add_to_hass(hass).id


def _allowed_only(hass: HomeAssistant, entities: list[str]) -> str:
    """The id of a new user who may read and control those entities alone."""
    user = MockUser().add_to_hass(hass)
    user.mock_policy({"entities": {"entity_ids": dict.fromkeys(entities, True)}})
    return user.id


async def _call(
    hass: HomeAssistant, action: str, device_ids: list[str], user_id: str | None
) -> None:
    """Call the action for those beacons as that user; as no user with None."""
    await hass.services.async_call(
        DOMAIN,
        action,
        {"device_id": device_ids},
        blocking=True,
        context=Context(user_id=user_id),
    )


@pytest.mark.parametrize("action", ACTIONS)
async def test_a_call_no_user_made_is_carried_out(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, home: str, action: str
) -> None:
    """An automation's call, which has no user, is sent as before."""
    await _call(hass, action, [home], None)

    assert _commands(aioclient_mock) == [f"{BASE}/{action}"]


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("group_id", [GROUP_ID_ADMIN, GROUP_ID_USER])
async def test_an_administrator_and_a_user_are_allowed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    home: str,
    action: str,
    group_id: str,
) -> None:
    """An administrator and an ordinary user may call each action."""
    user_id = await _in_group(hass, group_id)

    await _call(hass, action, [home], user_id)

    assert _commands(aioclient_mock) == [f"{BASE}/{action}"]


async def test_the_owner_is_allowed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, home: str
) -> None:
    """The owner may call the actions."""
    owner = MockUser(is_owner=True).add_to_hass(hass)

    await _call(hass, "spin", [home], owner.id)

    assert _commands(aioclient_mock) == [f"{BASE}/spin"]


@pytest.mark.parametrize("action", ACTIONS)
async def test_a_read_only_user_is_refused_and_nothing_is_sent(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    home: str,
    action: str,
) -> None:
    """A user of the read-only group is refused before any command is sent."""
    user_id = await _in_group(hass, GROUP_ID_READ_ONLY)

    with pytest.raises(Unauthorized) as err:
        await _call(hass, action, [home], user_id)

    assert _commands(aioclient_mock) == []
    assert err.value.user_id == user_id
    assert err.value.permission == "control"
    assert err.value.entity_id in _entity_ids(hass, mock_config_entry)
    assert err.value.context is not None
    assert err.value.context.user_id == user_id


@pytest.mark.parametrize("action", ACTIONS)
async def test_a_user_who_is_not_there_is_refused_and_nothing_is_sent(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, home: str, action: str
) -> None:
    """A user id Home Assistant no longer has is refused."""
    gone = MockUser().id

    with pytest.raises(UnknownUser) as err:
        await _call(hass, action, [home], gone)

    assert _commands(aioclient_mock) == []
    assert err.value.user_id == gone


@pytest.mark.parametrize("action", ACTIONS)
async def test_one_beacon_the_user_may_not_control_refuses_the_whole_call(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    away_entry: MockConfigEntry,
    home: str,
    away: str,
    action: str,
) -> None:
    """With several beacons chosen and one not allowed, none gets a command."""
    user_id = _allowed_only(hass, _entity_ids(hass, mock_config_entry))

    for chosen in ([home, away], [away, home], [away]):
        with pytest.raises(Unauthorized) as err:
            await _call(hass, action, chosen, user_id)
        assert err.value.entity_id in _entity_ids(hass, away_entry)
    assert _commands(aioclient_mock) == []

    # The beacon that user may control is still theirs to command.
    await _call(hass, action, [home], user_id)
    assert _commands(aioclient_mock) == [f"{BASE}/{action}"]


async def test_a_beacon_is_the_users_only_with_every_entity_of_it(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    home: str,
) -> None:
    """Control of some of a beacon's entities is not control of the beacon."""
    kept_out, *others = _entity_ids(hass, mock_config_entry)
    user_id = _allowed_only(hass, others)

    with pytest.raises(Unauthorized) as err:
        await _call(hass, "spin", [home], user_id)

    assert err.value.entity_id == kept_out
    assert _commands(aioclient_mock) == []


@pytest.mark.parametrize("action", ACTIONS)
async def test_a_read_only_user_is_refused_on_a_usb_beacon(
    hass: HomeAssistant, fake_usb: FakeUsb, usb_entry: MockConfigEntry, action: str
) -> None:
    """A beacon plugged into Home Assistant gets no report from a refused call."""
    fake_usb.plug("1-1")
    await setup_integration(hass, usb_entry)
    device_id = _device_id(hass, usb_entry)
    user_id = await _in_group(hass, GROUP_ID_READ_ONLY)
    before = fake_usb.written()

    with pytest.raises(Unauthorized):
        await _call(hass, action, [device_id], user_id)
    assert fake_usb.written() == before

    await _call(hass, action, [device_id], None)
    assert len(fake_usb.written()) == len(before) + 1
