"""Config flow for the My Cloud integration."""

from __future__ import annotations

import asyncio
import ipaddress
import re
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from wdnas_client import client as nas_client
from wdnas_client.exceptions import InvalidLoginError, RequestFailedError

from .const import (
    CONFIG_FLOW_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    HOST,
    MIN_UPDATE_INTERVAL,
    PASSWORD,
    USERNAME,
)
from .const import (
    VERSION as API_VERSION,
)

_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class CannotConnect(Exception):
    """Raised when the NAS cannot be reached."""


class InvalidAuth(Exception):
    """Raised when the NAS rejects the credentials."""


class UnsupportedFirmware(Exception):
    """Raised when the selected API version is unsupported."""


def _validate_host(value: str) -> str:
    """Validate and normalize a plain IP address or hostname."""
    host = value.strip()
    if not host or "://" in host or any(char in host for char in "/?#"):
        raise vol.Invalid("Enter an IP address or hostname without a URL or path")
    try:
        ipaddress.ip_address(host.strip("[]"))
        return host.lower()
    except ValueError:
        pass
    if len(host) > 253 or any(
        not _HOST_LABEL.fullmatch(label) for label in host.rstrip(".").split(".")
    ):
        raise vol.Invalid("Invalid hostname")
    return host.rstrip(".").lower()


def _is_auth_error(error: Exception) -> bool:
    """Classify auth failures exposed by current and older client releases."""
    if isinstance(error, InvalidLoginError):
        return True
    return isinstance(error, RequestFailedError) and any(
        status in str(error) for status in ("401", "403")
    )


async def _async_close_client(client: Any) -> None:
    """Close a partially or fully opened client session."""
    session = getattr(client, "session", None)
    if session is not None and not getattr(session, "closed", False):
        await client.__aexit__(None, None, None)


async def async_validate_input(data: dict[str, Any]) -> dict[str, str]:
    """Authenticate and return stable device identity data."""
    version = data[API_VERSION]
    if version not in (2, 5):
        raise UnsupportedFirmware

    client = nas_client(data[USERNAME], data[PASSWORD], data[HOST], version)
    try:
        async with asyncio.timeout(CONFIG_FLOW_TIMEOUT):
            await client.__aenter__()
            device = await client.device_info()
    except ValueError as error:
        raise UnsupportedFirmware from error
    except Exception as error:
        if _is_auth_error(error):
            raise InvalidAuth from error
        if isinstance(error, (aiohttp.ClientError, TimeoutError, RequestFailedError)):
            raise CannotConnect from error
        raise
    finally:
        await _async_close_client(client)

    serial = str(device.get("serial_number") or "").strip()
    name = str(device.get("name") or data[HOST]).strip()
    return {
        "title": name,
        "unique_id": serial or f"{version}:{data[HOST]}",
    }


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the setup schema while retaining existing config-entry keys."""
    defaults = defaults or {}
    host_key = (
        vol.Required(HOST, default=defaults[HOST])
        if HOST in defaults
        else vol.Required(HOST)
    )
    username_key = (
        vol.Required(USERNAME, default=defaults[USERNAME])
        if USERNAME in defaults
        else vol.Required(USERNAME)
    )
    password_key = (
        vol.Required(PASSWORD, default=defaults[PASSWORD])
        if PASSWORD in defaults
        else vol.Required(PASSWORD)
    )
    return vol.Schema(
        {
            host_key: _validate_host,
            username_key: str,
            password_key: str,
            vol.Required(API_VERSION, default=defaults.get(API_VERSION, 5)): vol.All(
                vol.Coerce(int), vol.In((2, 5))
            ),
        }
    )


class MyCloudOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle polling options."""

    async def async_step_init(self, user_input=None):
        """Manage the existing update-interval option."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            "update_interval", DEFAULT_UPDATE_INTERVAL
        )
        options_schema = vol.Schema(
            {
                vol.Optional("update_interval", default=current_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=options_schema)


class MyCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle My Cloud configuration and reauthentication."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return MyCloudOptionsFlowHandler()

    async def async_step_user(self, user_input=None):
        """Validate and create a new NAS config entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(
                {
                    HOST: user_input[HOST],
                    API_VERSION: user_input[API_VERSION],
                }
            )
            try:
                info = await async_validate_input(user_input)
            except InvalidAuth:
                errors["base"] = "auth"
            except CannotConnect:
                errors["base"] = "connection"
            except UnsupportedFirmware:
                errors["base"] = "unsupported_firmware"
            except Exception:  # noqa: BLE001 - config flows must return a safe error
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(user_input), errors=errors
        )

    async def async_step_reauth(self, entry_data):
        """Start reauthentication for an existing entry."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Validate replacement credentials and reload the entry."""
        entry = self._reauth_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {
                **entry.data,
                USERNAME: user_input[USERNAME],
                PASSWORD: user_input[PASSWORD],
            }
            try:
                info = await async_validate_input(candidate)
            except InvalidAuth:
                errors["base"] = "auth"
            except CannotConnect:
                errors["base"] = "connection"
            except UnsupportedFirmware:
                errors["base"] = "unsupported_firmware"
            except Exception:  # noqa: BLE001 - config flows must return a safe error
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_id"])
                if entry.unique_id is not None:
                    self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=info["unique_id"],
                    data_updates={
                        USERNAME: user_input[USERNAME],
                        PASSWORD: user_input[PASSWORD],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(USERNAME, default=entry.data[USERNAME]): str,
                vol.Required(PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )
