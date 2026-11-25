"""A client for the blinkybeacon-tray HTTP API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus
import json
from typing import Any

import aiohttp
from yarl import URL

from .const import MAX_REPLY, MAX_SHOWN, REQUEST_TIMEOUT


@dataclass(frozen=True)
class BeaconStatus:
    """What the tray reports: its light's state, and whether the USB light is there."""

    state: str
    connected: bool


class BlinkyBeaconError(Exception):
    """The tray did not do what was asked."""


class BlinkyBeaconConnectionError(BlinkyBeaconError):
    """The tray did not answer."""


class BlinkyBeaconNotConnectedError(BlinkyBeaconError):
    """The tray answered 503: its USB light is not plugged in."""


class BlinkyBeaconResponseError(BlinkyBeaconError):
    """The tray answered with something this client does not understand."""


class BlinkyBeaconClient:
    """Talks to one tray at host:port."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int) -> None:
        self._session = session
        self._url = URL.build(scheme="http", host=host, port=port)

    @property
    def base_url(self) -> str:
        """The tray's address as a URL, without a trailing slash."""
        return str(self._url)

    async def status(self) -> BeaconStatus:
        """Read the tray's state."""
        return await self._request("GET", "/status")

    async def spin(self) -> BeaconStatus:
        """Start spinning."""
        return await self._request("POST", "/spin")

    async def flash(self) -> BeaconStatus:
        """Start flashing."""
        return await self._request("POST", "/flash")

    async def stop(self) -> BeaconStatus:
        """Stop the light."""
        return await self._request("POST", "/stop")

    async def _request(self, method: str, path: str) -> BeaconStatus:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method, self._url.with_path(path)
                ) as response:
                    if response.status == HTTPStatus.SERVICE_UNAVAILABLE:
                        raise BlinkyBeaconNotConnectedError
                    if response.status != HTTPStatus.OK:
                        raise BlinkyBeaconResponseError(
                            f"{method} {path} answered {response.status}"
                        )
                    raw = await _read_capped(response)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise BlinkyBeaconConnectionError(str(err)) from err

        if raw is None:
            raise BlinkyBeaconResponseError(
                f"{method} {path} answered more than {MAX_REPLY} bytes"
            )
        try:
            body: Any = json.loads(raw)
        except (ValueError, RecursionError) as err:
            raise BlinkyBeaconResponseError(
                f"{method} {path} did not answer JSON"
            ) from err
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("state"), str)
            or not isinstance(body.get("connected"), bool)
        ):
            raise BlinkyBeaconResponseError(f"{method} {path} answered {_shown(body)}")
        return BeaconStatus(body["state"], body["connected"])


async def _read_capped(response: aiohttp.ClientResponse) -> bytes | None:
    """The reply's body, or None when it is longer than MAX_REPLY bytes: the
    reading stops at the chunk that passes it.
    """
    body = bytearray()
    async for chunk in response.content.iter_any():
        body += chunk
        if len(body) > MAX_REPLY:
            return None
    return bytes(body)


def _shown(body: Any) -> str:
    """A reply as an error shows it: its first MAX_SHOWN characters."""
    text = repr(body)
    return text if len(text) <= MAX_SHOWN else text[:MAX_SHOWN] + "…"
