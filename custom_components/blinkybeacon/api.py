"""A client for the blinkybeacon-tray HTTP API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus

import aiohttp
from yarl import URL

from .const import REQUEST_TIMEOUT


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
                    try:
                        body = await response.json(content_type=None)
                    except ValueError as err:
                        raise BlinkyBeaconResponseError(
                            f"{method} {path} did not answer JSON"
                        ) from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise BlinkyBeaconConnectionError(str(err)) from err

        if (
            not isinstance(body, dict)
            or not isinstance(body.get("state"), str)
            or not isinstance(body.get("connected"), bool)
        ):
            raise BlinkyBeaconResponseError(f"{method} {path} answered {body!r}")
        return BeaconStatus(body["state"], body["connected"])
