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
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TimeSelector,
)
from homeassistant.util import dt as dt_util

from .api import WinTaxAuthError, WinTaxClient, WinTaxConnectionError
from .const import (
    CONF_ACTIVE_GRACE_MINUTES,
    CONF_AFTERNOON_END,
    CONF_AFTERNOON_START,
    CONF_HOME,
    CONF_MORNING_END,
    CONF_MORNING_START,
    CONF_POLL_INTERVAL,
    CONF_RIDE_LOOKAHEAD_DAYS,
    CONF_RIDE_LOOKBACK_DAYS,
    CONF_WEEKDAYS_ONLY,
    DEFAULT_ACTIVE_GRACE_MINUTES,
    DEFAULT_AFTERNOON_END,
    DEFAULT_AFTERNOON_START,
    DEFAULT_BASE_URL,
    DEFAULT_MORNING_END,
    DEFAULT_MORNING_START,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_WEEKDAYS_ONLY,
    DOMAIN,
    MAX_ACTIVE_GRACE_MINUTES,
    MAX_POLL_INTERVAL_SECONDS,
    MAX_RIDE_LOOKAHEAD_DAYS,
    MAX_RIDE_LOOKBACK_DAYS,
    MIN_ACTIVE_GRACE_MINUTES,
    MIN_POLL_INTERVAL_SECONDS,
    MIN_RIDE_LOOKAHEAD_DAYS,
    MIN_RIDE_LOOKBACK_DAYS,
    RIDE_LOOKAHEAD_DAYS,
    RIDE_LOOKBACK_DAYS,
)
from .geo import parse_home_option, suggested_home, validate_home

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def default_options() -> dict[str, Any]:
    """Return options applied when a field has never been saved."""
    return {
        CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL_SECONDS,
        CONF_WEEKDAYS_ONLY: DEFAULT_WEEKDAYS_ONLY,
        CONF_MORNING_START: DEFAULT_MORNING_START,
        CONF_MORNING_END: DEFAULT_MORNING_END,
        CONF_AFTERNOON_START: DEFAULT_AFTERNOON_START,
        CONF_AFTERNOON_END: DEFAULT_AFTERNOON_END,
        CONF_RIDE_LOOKBACK_DAYS: RIDE_LOOKBACK_DAYS,
        CONF_RIDE_LOOKAHEAD_DAYS: RIDE_LOOKAHEAD_DAYS,
        CONF_ACTIVE_GRACE_MINUTES: DEFAULT_ACTIVE_GRACE_MINUTES,
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
            vol.Required(
                CONF_RIDE_LOOKBACK_DAYS,
                default=current.get(CONF_RIDE_LOOKBACK_DAYS, RIDE_LOOKBACK_DAYS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_RIDE_LOOKBACK_DAYS,
                    max=MAX_RIDE_LOOKBACK_DAYS,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="days",
                )
            ),
            vol.Required(
                CONF_RIDE_LOOKAHEAD_DAYS,
                default=current.get(CONF_RIDE_LOOKAHEAD_DAYS, RIDE_LOOKAHEAD_DAYS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_RIDE_LOOKAHEAD_DAYS,
                    max=MAX_RIDE_LOOKAHEAD_DAYS,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="days",
                )
            ),
            vol.Required(
                CONF_ACTIVE_GRACE_MINUTES,
                default=current.get(
                    CONF_ACTIVE_GRACE_MINUTES, DEFAULT_ACTIVE_GRACE_MINUTES
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_ACTIVE_GRACE_MINUTES,
                    max=MAX_ACTIVE_GRACE_MINUTES,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
        }
    )


def _home_schema(current: dict[str, float]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOME, default=current): LocationSelector(
                LocationSelectorConfig(radius=True, icon="mdi:home")
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
                    options=default_options(),
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
    """Handle WinTax options without dropping keys from the other step."""

    def _merged_options(self, updates: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = {**default_options(), **self.config_entry.options}
        if updates:
            merged.update(updates)
        return merged

    def _home_form_default(self) -> dict[str, float]:
        stored = parse_home_option(self.config_entry.options.get(CONF_HOME))
        if stored is not None:
            return {
                "latitude": stored.latitude,
                "longitude": stored.longitude,
                "radius": stored.radius,
            }
        latitude = self.hass.config.latitude
        longitude = self.hass.config.longitude
        radius: float | None = None
        zone = self.hass.states.get("zone.home")
        if zone is not None:
            latitude = zone.attributes.get("latitude", latitude)
            longitude = zone.attributes.get("longitude", longitude)
            raw_radius = zone.attributes.get("radius")
            if isinstance(raw_radius, (int, float)) and not isinstance(raw_radius, bool):
                radius = float(raw_radius)
        try:
            fallback_latitude = float(latitude)
            fallback_longitude = float(longitude)
        except (TypeError, ValueError):
            fallback_latitude = None
            fallback_longitude = None
        return suggested_home(
            latitude=fallback_latitude,
            longitude=fallback_longitude,
            radius=radius,
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose which settings to change."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["schedule", "home"],
        )

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the weekday pickup/drop-off poll schedule."""
        if user_input is not None:
            cleaned = {
                **user_input,
                CONF_POLL_INTERVAL: int(user_input[CONF_POLL_INTERVAL]),
                CONF_RIDE_LOOKBACK_DAYS: int(user_input[CONF_RIDE_LOOKBACK_DAYS]),
                CONF_RIDE_LOOKAHEAD_DAYS: int(user_input[CONF_RIDE_LOOKAHEAD_DAYS]),
                CONF_ACTIVE_GRACE_MINUTES: int(user_input[CONF_ACTIVE_GRACE_MINUTES]),
            }
            return self.async_create_entry(title="", data=self._merged_options(cleaned))

        current = self._merged_options()
        return self.async_show_form(
            step_id="schedule",
            data_schema=_options_schema(current),
        )

    async def async_step_home(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the home pin and radius on a map."""
        errors: dict[str, str] = {}
        if user_input is not None:
            target, error = validate_home(user_input.get(CONF_HOME))
            if error is not None or target is None:
                errors["base"] = error or "invalid_location"
            else:
                stored = {
                    "latitude": target.latitude,
                    "longitude": target.longitude,
                    "radius": target.radius,
                }
                return self.async_create_entry(
                    title="",
                    data=self._merged_options({CONF_HOME: stored}),
                )

        return self.async_show_form(
            step_id="home",
            data_schema=_home_schema(self._home_form_default()),
            errors=errors,
        )
