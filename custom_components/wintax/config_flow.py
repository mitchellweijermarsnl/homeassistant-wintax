"""Config flow for the WinTax integration."""

from __future__ import annotations

from typing import Any
import logging

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TimeSelector,
)
from homeassistant.util import dt as dt_util

from .api import WinTaxAuthError, WinTaxClient, WinTaxConnectionError
from .const import (
    CONF_AFTERNOON_END,
    CONF_AFTERNOON_START,
    CONF_MORNING_END,
    CONF_MORNING_START,
    CONF_POLL_INTERVAL,
    CONF_WEEKDAYS_ONLY,
    DEFAULT_AFTERNOON_END,
    DEFAULT_AFTERNOON_START,
    DEFAULT_BASE_URL,
    DEFAULT_MORNING_END,
    DEFAULT_MORNING_START,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_WEEKDAYS_ONLY,
    DOMAIN,
    MAX_POLL_INTERVAL_SECONDS,
    MIN_POLL_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def default_poll_options() -> dict[str, Any]:
    """Return the default weekday pickup/drop-off poll schedule."""
    return {
        CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL_SECONDS,
        CONF_WEEKDAYS_ONLY: DEFAULT_WEEKDAYS_ONLY,
        CONF_MORNING_START: DEFAULT_MORNING_START,
        CONF_MORNING_END: DEFAULT_MORNING_END,
        CONF_AFTERNOON_START: DEFAULT_AFTERNOON_START,
        CONF_AFTERNOON_END: DEFAULT_AFTERNOON_END,
    }


def _options_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_POLL_INTERVAL,
                default=current.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_SECONDS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_POLL_INTERVAL_SECONDS,
                    max=MAX_POLL_INTERVAL_SECONDS,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="seconds",
                )
            ),
            vol.Required(
                CONF_WEEKDAYS_ONLY,
                default=current.get(CONF_WEEKDAYS_ONLY, DEFAULT_WEEKDAYS_ONLY),
            ): BooleanSelector(),
            vol.Required(
                CONF_MORNING_START,
                default=current.get(CONF_MORNING_START, DEFAULT_MORNING_START),
            ): TimeSelector(),
            vol.Required(
                CONF_MORNING_END,
                default=current.get(CONF_MORNING_END, DEFAULT_MORNING_END),
            ): TimeSelector(),
            vol.Required(
                CONF_AFTERNOON_START,
                default=current.get(CONF_AFTERNOON_START, DEFAULT_AFTERNOON_START),
            ): TimeSelector(),
            vol.Required(
                CONF_AFTERNOON_END,
                default=current.get(CONF_AFTERNOON_END, DEFAULT_AFTERNOON_END),
            ): TimeSelector(),
        }
    )


async def _validate_credentials(
    hass: HomeAssistant, username: str, password: str
) -> None:
    """Log in and fetch today's rides to confirm the account works."""
    session = async_get_clientsession(hass, verify_ssl=False)
    client = WinTaxClient(session, username, password, base_url=DEFAULT_BASE_URL)
    await client.async_login()
    today = dt_util.now().date()
    await client.async_fetch_rides(today, today)


class WinTaxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WinTax."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            await self.async_set_unique_id(username.casefold())
            self._abort_if_unique_id_configured()

            try:
                await _validate_credentials(self.hass, username, password)
            except WinTaxAuthError:
                errors["base"] = "invalid_auth"
            except WinTaxConnectionError as err:
                _LOGGER.warning("Could not connect to WinTax: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during WinTax setup")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="WinTax",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                    },
                    options=default_poll_options(),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Start a reauthentication flow."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for an updated password."""
        errors: dict[str, str] = {}
        entry_id = self.context["entry_id"]
        reauth_entry = self.hass.config_entries.async_get_entry(entry_id)
        assert reauth_entry is not None
        username = reauth_entry.data[CONF_USERNAME]

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            try:
                await _validate_credentials(self.hass, username, password)
            except WinTaxAuthError:
                errors["base"] = "invalid_auth"
            except WinTaxConnectionError as err:
                _LOGGER.warning("Could not connect to WinTax during reauth: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception during WinTax reauth")
                errors["base"] = "unknown"
            else:
                data = {**reauth_entry.data, CONF_PASSWORD: password}
                self.hass.config_entries.async_update_entry(reauth_entry, data=data)
                await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"username": username},
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return WinTaxOptionsFlow()


class WinTaxOptionsFlow(OptionsFlow):
    """Handle WinTax poll-window options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the weekday pickup/drop-off poll schedule."""
        if user_input is not None:
            merged = {**default_poll_options(), **user_input}
            return self.async_create_entry(title="", data=merged)

        current = {**default_poll_options(), **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current),
        )
