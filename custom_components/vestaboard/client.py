"""Vestaboard local client."""

from __future__ import annotations

from enum import StrEnum
import json

from aiohttp import ClientResponse, ClientSession

DEFAULT_PORT = 7000
DEFAULT_URL = f"http://vestaboard.local:{DEFAULT_PORT}"


class InvalidApiKeyError(Exception):
    """Invalid API key error."""


async def _parse_response(
    response: ClientResponse, key: str | None = None
) -> dict | str | list[list[int]] | None:
    """Parse response."""
    try:
        raw = await response.text()
        payload = json.loads(raw)
        return payload.get(key) if key else payload
    except json.JSONDecodeError:
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

    def __repr__(self):
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    @property
    def enabled(self) -> bool:
        """Check if :py:attr:`~api_key` has been set, indicating that Local API
        support has been enabled."""
        return self.api_key is not None

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

    async def read_message(self) -> list[list[int]] | None:
        """Read the Vestaboard's current message."""
        if not self.enabled:
            raise RuntimeError("Local API has not been enabled")
        resp = await self.session.get(
            f"{self.base_url}/local-api/message",
            headers={"X-Vestaboard-Local-Api-Key": self.api_key},
        )
        if resp.status == 401 and (await resp.text()) == "Invalid API key":
            raise InvalidApiKeyError("Invalid API key")
        resp.raise_for_status()
        if message := await _parse_response(resp, "message"):
            self.data = message
        return message

    async def write_message(
        self, json: dict[str, str | int | list[list[int]]] | list[list[int]]
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
            f"{self.base_url}/local-api/message",
            headers={"X-Vestaboard-Local-Api-Key": self.api_key},
            json=payload,
        )
        resp.raise_for_status()
        return resp.status == 201

    async def check_endpoint(self) -> EndpointStatus:
        """Test the Vestaboard's endpoint to determine if it is a Vestaboard."""
        resp = await self.session.get(
            f"{self.base_url}/local-api/message",
            headers={"X-Vestaboard-Local-Api-Key": self.api_key or ""},
            timeout=5,
        )
        if resp.status == 200 and (message := await _parse_response(resp, "message")):
            self.data = message
            return EndpointStatus.VALID
        if resp.status == 401 and (await resp.text()) == "Invalid API key":
            return EndpointStatus.INVALID_API_KEY
        return EndpointStatus.UNKNOWN

    async def close(self) -> None:
        """Close the underlying session if owned by the client."""
        if self.should_close:
            await self.session.close()
