"""Vestaboard local client."""

from __future__ import annotations

import asyncio
from enum import StrEnum
import json
import logging

from aiohttp import ClientResponse, ClientResponseError, ClientSession

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 7000
DEFAULT_URL = f"http://vestaboard.local:{DEFAULT_PORT}"

INVALID_API_KEY = "Invalid API key"


class InvalidApiKeyError(Exception):
    """Invalid API key error."""


async def _parse_response(
    response: ClientResponse, key: str | None = None
) -> dict | str | list[list[int]] | None:
    """Parse response."""
    raw = await response.text()
    try:
        payload = json.loads(raw)
        return payload.get(key) if key else payload
    except json.JSONDecodeError:
        _LOGGER.warning("Unable to parse response: %s", raw)
        return None


class EndpointStatus(StrEnum):
    """Endpoint status."""

    VALID = "valid"
    INVALID_API_KEY = "invalid_api_key"
    UNKNOWN = "unknown"


class VestaboardLocalClient:
    """Provides a Vestaboard Local API client interface.

    A Local API key is required to read or write messages. This key is obtained
    by enabling the Vestaboard's Local API using a Local API Enablement Token.

    If you've already enabled your Vestaboard's Local API, that key can be
    provided immediately. Otherwise, it can be set after the client is
    constructed by calling :py:meth:`~enable`, which also returns the Local API
    key for future reuse.

    An alternate ``base_url`` can also be specified.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_URL,
        session: ClientSession | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.session = session or ClientSession()
        self.should_close = session is None
        self.data: list[list[int]] | None = None
        self.firmware_version: str | None = None

    def __repr__(self):
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    @property
    def enabled(self) -> bool:
        """Check if :py:attr:`~api_key` has been set, indicating that Local API
        support has been enabled."""
        return self.api_key is not None

    @property
    def messaging_endpoint(self) -> str:
        """Return the endpoint for reading and writing messages."""
        return f"{self.base_url}/local-api/message"

    async def enable(self, enablement_token: str) -> str | None:
        """Enable the Vestaboard's Local API using a Local API Enablement Token.

        If successful, the Vestaboard's Local API key will be returned and the
        client's :py:attr:`~api_key` property will be updated to the new value.
        """
        resp = await self.session.post(
            f"{self.base_url}/local-api/enablement",
            headers={"X-Vestaboard-Local-Api-Enablement-Token": enablement_token},
        )
        resp.raise_for_status()

        api_key: str | None = None
        if api_key := await _parse_response(resp, "apiKey"):
            self.api_key = api_key

        return api_key

    async def read_message(
        self, *, check_enabled: bool = True, timeout: float | None = None
    ) -> list[list[int]] | None:
        """Read the Vestaboard's current message."""
        if check_enabled and not self.enabled:
            raise RuntimeError("Local API has not been enabled")
        resp = await self.session.get(
            self.messaging_endpoint,
            headers={"X-Vestaboard-Local-Api-Key": self.api_key or ""},
            timeout=timeout,
        )
        if not self.firmware_version and (server := resp.headers.get("Server")):
            self.firmware_version = server.replace("Vestaboard/", "")
        if resp.status == 401 and (await resp.text()) == INVALID_API_KEY:
            raise InvalidApiKeyError(INVALID_API_KEY)
        resp.raise_for_status()
        if message := await _parse_response(resp, "message"):
            self.data = message
        return message

    async def write_message(
        self,
        json: dict[str, str | int | list[list[int]]] | list[list[int]],
        *,
        timeout: float | None = None,
    ) -> bool:
        """Write a message to the Vestaboard.

        `json` must be a json object and may contain:
            - `characters` - a 6x22 array of character codes
            - `step_interval_ms` - step interval in milliseconds
            - `step_size` - number of columns to animate
            - `strategy` - animation type, one of:
                - `classic` -> "Classic", default (not actually sent in payload)
                - `column` -> "Wave" in the app
                - `reverse-column` -> "Drift" in the app
                - `edges-to-center` -> "Curtain" in the app
                - `row` -> Row-by-row animation
                - `diagonal` -> Corner-to-corner animation
                - `random` -> Animates the number in step_size at a time randomly

        :raises ValueError: if ``characters`` is a list with unsupported dimensions
        """
        if not self.enabled:
            raise RuntimeError("Local API has not been enabled")

        payload = dict(json) if isinstance(json, dict) else json
        if isinstance(payload, dict) and payload.get("strategy") == "classic":
            payload.pop("strategy")

        resp = await self.session.post(
            self.messaging_endpoint,
            headers={"X-Vestaboard-Local-Api-Key": self.api_key},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.status == 201

    async def check_endpoint(self) -> EndpointStatus:
        """Test the Vestaboard's endpoint to determine if it is a Vestaboard."""
        _LOGGER.debug("Checking endpoint %s", self.messaging_endpoint)
        try:
            message = await self.read_message(check_enabled=False, timeout=5)
        except InvalidApiKeyError:
            return EndpointStatus.INVALID_API_KEY
        except ClientResponseError:
            return EndpointStatus.UNKNOWN

        if not message:
            _LOGGER.warning(
                "Received 200 response with no message while attempting to read, "
                "attempting to write to the board for validation"
            )
            if not await self.write_message([[0]]):
                return EndpointStatus.UNKNOWN
            await asyncio.sleep(1)
            message = await self.read_message(check_enabled=False, timeout=5)

        self.data = message
        return EndpointStatus.VALID

    async def close(self) -> None:
        """Close the underlying session if owned by the client."""
        if self.should_close:
            await self.session.close()


class VestaboardVirtualClient:
    """An in-memory stand-in for :py:class:`VestaboardLocalClient`.

    A virtual Vestaboard has no hardware behind it, which makes it useful for
    trying out messages and arrays. Messages written to it are held in memory;
    pass ``message`` to start with a saved message.
    """

    firmware_version: str | None = None

    def __init__(
        self,
        name: str,
        rows: int,
        columns: int,
        message: list[list[int]] | None = None,
    ) -> None:
        self.base_url = f"virtual://{name}"
        self.data: list[list[int]] = [[0] * columns for _ in range(rows)]
        if message is not None and self._fits(message):
            self.data = [list(row) for row in message]

    def __repr__(self):
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    async def read_message(self, **kwargs) -> list[list[int]]:
        """Read the virtual board's current message."""
        return [list(row) for row in self.data]

    async def write_message(
        self, json: dict[str, str | int | list[list[int]]], **kwargs
    ) -> bool:
        """Write a message to the virtual board. Transition settings are ignored."""
        characters = json["characters"]
        if not self._fits(characters):
            raise ValueError(
                f"Expected {len(self.data)}x{len(self.data[0])} characters for {self!r}"
            )
        self.data = [list(row) for row in characters]
        return True

    def _fits(self, characters: list[list[int]]) -> bool:
        """Return True if the characters are the size of this board."""
        return len(characters) == len(self.data) and all(
            len(row) == len(self.data[0]) for row in characters
        )

    async def close(self) -> None:
        """Nothing to close for a virtual board."""
