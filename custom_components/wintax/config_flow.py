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
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import WinTaxAuthError, WinTaxClient, WinTaxConnectionError
from .const import (
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(
            CONF_SCAN_INTERVAL,
            default=int(DEFAULT_SCAN_INTERVAL.total_seconds()),
        ): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_SCAN_INTERVAL_SECONDS, max=MAX_SCAN_INTERVAL_SECONDS),
        ),
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
                    options={
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL,
                            int(DEFAULT_SCAN_INTERVAL.total_seconds()),
                        )
                    },
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
    """Handle WinTax options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the WinTax options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_SCAN_INTERVAL_SECONDS,
                            max=MAX_SCAN_INTERVAL_SECONDS,
                        ),
                    )
                }
            ),
        )
