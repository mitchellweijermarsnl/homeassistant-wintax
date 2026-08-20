"""WinTax HTTP client.

Talks to the real .wts endpoints used by the UVO Vervoer customer portal.
Does not invent REST/JSON APIs.

Confirmed login flow (from the public login page):
  GET  /client/user.wts?m=login
  POST /client/user.wts?m=login_post&view=   fields: u, p
  Subsequent requests pass sessionid as a query parameter.
"""

from __future__ import annotations

from datetime import date
import asyncio
import logging
import re
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .const import (
    CLIENT_BASE_PATH,
    DEFAULT_BASE_URL,
    HTTP_TIMEOUT_SECONDS,
    LOGIN_MODE,
    LOGIN_PAGE,
    LOGIN_PASSWORD_FIELD,
    LOGIN_POST_MODE,
    LOGIN_USERNAME_FIELD,
    MAP_PAGE,
    RIDES_PAGE,
)
from .parser import (
    TrackingData,
    extract_session_id,
    is_authenticated_page,
    is_login_page,
    parse_rides,
    parse_tracking,
)

_LOGGER = logging.getLogger(__name__)

_REDACT_RE = re.compile(
    r"((?:sessionid|p|password)=)[^&]*",
    re.IGNORECASE,
)


class WinTaxError(Exception):
    """Base error for WinTax client failures."""


class WinTaxAuthError(WinTaxError):
    """Invalid credentials or expired session that cannot be renewed."""


class WinTaxConnectionError(WinTaxError):
    """Network, DNS, timeout, or HTTP 5xx failure."""


class WinTaxClient:
    """Async HTTP client for the WinTax customer portal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._session_id: str | None = None

    @property
    def session_id(self) -> str | None:
        """Return the current session id. Do not log this value."""
        return self._session_id

    def _client_url(self, page: str) -> str:
        return urljoin(f"{self._base_url}{CLIENT_BASE_PATH}/", page)

    async def async_login(self) -> str:
        """Authenticate and store the resulting sessionid."""
        # Load the login form first, matching the browser flow.
        await self._request("GET", self._client_url(LOGIN_PAGE), params={"m": LOGIN_MODE})
        final_url, html = await self._request(
            "POST",
            self._client_url(LOGIN_PAGE),
            params={"m": LOGIN_POST_MODE, "view": ""},
            data={
                LOGIN_USERNAME_FIELD: self._username,
                LOGIN_PASSWORD_FIELD: self._password,
            },
        )

        session_id = extract_session_id(final_url, html)
        if session_id is None or is_login_page(html) or not is_authenticated_page(html):
            if is_login_page(html) or session_id is None:
                raise WinTaxAuthError("WinTax rejected the supplied credentials")
            raise WinTaxAuthError("WinTax login did not establish a session")

        self._session_id = session_id
        _LOGGER.debug("WinTax session established")
        return session_id

    async def async_ensure_session(self) -> str:
        """Return a valid session id, logging in when necessary."""
        if self._session_id:
            return self._session_id
        return await self.async_login()

    async def async_fetch_rides(self, start: date, end: date) -> str:
        """Fetch index.wts HTML for the given inclusive date range (DD-MM-YYYY)."""
        await self.async_ensure_session()
        html = await self._authenticated_get(
            RIDES_PAGE,
            {
                "sd": _wintax_date(start),
                "ed": _wintax_date(end),
                "q": "",
                "ec": "0",
            },
        )
        return html

    async def async_fetch_tracking(self, trip_id: str) -> str:
        """Fetch map.wts HTML for a trip. The response format is not fully known."""
        await self.async_ensure_session()
        return await self._authenticated_get(MAP_PAGE, {"tripid": trip_id})

    async def async_get_rides(self, start: date, end: date, tz: Any = None) -> list:
        """Fetch and parse rides for the given date range."""
        html = await self.async_fetch_rides(start, end)
        return parse_rides(html, tz=tz)

    async def async_get_tracking(self, trip_id: str) -> TrackingData | None:
        """Fetch map.wts and parse GPS data when present."""
        try:
            html = await self.async_fetch_tracking(trip_id)
        except WinTaxError as err:
            _LOGGER.debug("WinTax tracking request failed: %s", err)
            return None
        return parse_tracking(html, trip_id=trip_id)

    async def _authenticated_get(self, page: str, params: dict[str, str]) -> str:
        if not self._session_id:
            await self.async_login()

        query = dict(params)
        query["sessionid"] = self._session_id or ""
        _final_url, html = await self._request("GET", self._client_url(page), params=query)

        if is_login_page(html):
            _LOGGER.debug("WinTax session expired; logging in again")
            self._session_id = None
            await self.async_login()
            query["sessionid"] = self._session_id or ""
            _final_url, html = await self._request(
                "GET", self._client_url(page), params=query
            )
            if is_login_page(html):
                raise WinTaxAuthError("WinTax session could not be renewed")

        return html

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                data=data,
                timeout=timeout,
                allow_redirects=True,
                headers={"Accept": "text/html,application/xhtml+xml"},
            ) as response:
                if response.status in (401, 403):
                    raise WinTaxAuthError(f"WinTax returned HTTP {response.status}")
                if response.status >= 400:
                    raise WinTaxConnectionError(f"WinTax returned HTTP {response.status}")
                raw = await response.read()
                html = _decode_html(raw, response.charset)
                return str(response.url), html
        except (TimeoutError, asyncio.TimeoutError) as err:
            raise WinTaxConnectionError("WinTax request timed out") from err
        except aiohttp.ClientError as err:
            raise WinTaxConnectionError("Could not connect to WinTax") from err

    def __repr__(self) -> str:
        return f"WinTaxClient(base_url={self._base_url!r})"


def redact_url(url: str) -> str:
    """Strip session ids and passwords from a URL before logging."""
    return _REDACT_RE.sub(r"\1[redacted]", url)


def _wintax_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _decode_html(raw: bytes, charset: str | None) -> str:
    # The portal advertises windows-1252; fall back through common encodings.
    for encoding in (charset, "windows-1252", "utf-8", "latin-1"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")
