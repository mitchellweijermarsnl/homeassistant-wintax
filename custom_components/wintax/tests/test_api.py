"""Tests for the WinTax HTTP client helpers and login flow."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest

from custom_components.wintax.api import (
    WinTaxAuthError,
    WinTaxClient,
    _decode_html,
    redact_url,
)
from custom_components.wintax.parser import extract_session_id, is_login_page

_FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def test_redact_url_strips_session_and_password() -> None:
    url = "https://example/client/index.wts?sessionid=secret&sd=01-08-2026"
    redacted = redact_url(url)
    assert "secret" not in redacted
    assert "sessionid=[redacted]" in redacted
    assert "password" not in redact_url("https://example/?p=hunter2")
    assert "hunter2" not in redact_url("https://example/?p=hunter2")


def test_decode_html_windows_1252() -> None:
    raw = "caf\xe9".encode("windows-1252")
    assert _decode_html(raw, "windows-1252") == "café"


class _FakeResponse:
    def __init__(self, url: str, body: str, status: int = 200) -> None:
        self.url = url
        self._body = body.encode("windows-1252", errors="replace")
        self.status = status
        self.charset = "windows-1252"

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError(f"Unexpected request {method} {url}")
        return self._responses.pop(0)


def test_login_success_extracts_session() -> None:
    login_html = load_fixture("login.html")
    rides_html = load_fixture("rides.html")
    session = _FakeSession(
        [
            _FakeResponse("https://example/client/user.wts?m=login", login_html),
            _FakeResponse(
                "https://example/client/index.wts?sessionid=testsession",
                rides_html,
            ),
        ]
    )
    client = WinTaxClient(session, "user@example.com", "secret", base_url="https://example")  # type: ignore[arg-type]

    session_id = asyncio.run(client.async_login())
    assert session_id == "testsession"
    assert client.session_id == "testsession"
    assert session.calls[1][0] == "POST"
    posted = session.calls[1][2]["data"]
    assert posted["u"] == "user@example.com"
    assert posted["p"] == "secret"


def test_login_failure_still_on_login_page() -> None:
    login_html = load_fixture("login.html")
    session = _FakeSession(
        [
            _FakeResponse("https://example/client/user.wts?m=login", login_html),
            _FakeResponse("https://example/client/user.wts?m=login_post", login_html),
        ]
    )
    client = WinTaxClient(session, "user@example.com", "wrong", base_url="https://example")  # type: ignore[arg-type]
    with pytest.raises(WinTaxAuthError):
        asyncio.run(client.async_login())


def test_fetch_rides_sends_date_params() -> None:
    login_html = load_fixture("login.html")
    rides_html = load_fixture("rides.html")
    session = _FakeSession(
        [
            _FakeResponse("https://example/client/user.wts?m=login", login_html),
            _FakeResponse(
                "https://example/client/index.wts?sessionid=testsession",
                rides_html,
            ),
            _FakeResponse(
                "https://example/client/index.wts?sessionid=testsession",
                rides_html,
            ),
        ]
    )
    client = WinTaxClient(session, "user@example.com", "secret", base_url="https://example")  # type: ignore[arg-type]
    html = asyncio.run(client.async_fetch_rides(date(2026, 8, 1), date(2026, 8, 31)))
    assert "maintrips" in html
    params = session.calls[-1][2]["params"]
    assert params["sd"] == "01-08-2026"
    assert params["ed"] == "31-08-2026"
    assert params["ec"] == "0"
    assert params["sessionid"] == "testsession"


def test_is_login_page_helper() -> None:
    assert is_login_page(load_fixture("login.html"))
    assert not is_login_page(load_fixture("rides.html"))
    assert extract_session_id(None, load_fixture("login.html")) is None
