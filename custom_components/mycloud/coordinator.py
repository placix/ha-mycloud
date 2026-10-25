"""Data coordinator for the My Cloud integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from wdnas_client import client as nas_client
from wdnas_client.exceptions import InvalidLoginError, RequestFailedError

from .const import (
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    HOST,
    PASSWORD,
    UPDATE_TIMEOUT,
    USERNAME,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _is_auth_error(error: Exception) -> bool:
    """Return whether an older client exception represents an auth failure."""
    if isinstance(error, InvalidLoginError):
        return True
    return isinstance(error, RequestFailedError) and any(
        status in str(error) for status in ("401", "403")
    )


class MyCloudDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate one authenticated session and shared NAS polling."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, client: Any | None = None
    ) -> None:
        """Initialize the coordinator."""
        self.config_entry = config_entry
        self.client = client or nas_client(
            config_entry.data[USERNAME],
            config_entry.data[PASSWORD],
            config_entry.data[HOST],
            config_entry.data[VERSION],
        )
        update_interval = config_entry.options.get(
            "update_interval", DEFAULT_UPDATE_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_{config_entry.entry_id}",
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_setup(self) -> None:
        """Open and authenticate the shared client session once."""
        await self._async_login()

    async def _async_login(self) -> None:
        """Authenticate, translating failures into Home Assistant semantics."""
        try:
            async with asyncio.timeout(UPDATE_TIMEOUT):
                await self.client.__aenter__()
        except Exception as error:
            await self._async_close_client()
            if _is_auth_error(error):
                raise ConfigEntryAuthFailed("Invalid NAS credentials") from error
            if isinstance(
                error, (aiohttp.ClientError, TimeoutError, RequestFailedError)
            ):
                raise UpdateFailed(f"Unable to connect to the NAS: {error}") from error
            raise UpdateFailed(
                f"Unable to initialize the NAS client: {error}"
            ) from error

    async def _async_fetch_data(self) -> dict[str, Any]:
        """Fetch the four existing data sets without adding new API calls."""
        async with asyncio.timeout(UPDATE_TIMEOUT):
            return {
                "system_info": await self.client.system_info(),
                "system_status": await self.client.system_status(),
                "device_info": await self.client.device_info(),
                "system_version": await self.client.system_version(),
            }

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data and retry once after an expired authenticated session."""
        try:
            return await self._async_fetch_data()
        except Exception as error:
            if _is_auth_error(error):
                _LOGGER.debug("NAS session expired; re-authenticating once")
                try:
                    await self._async_close_client()
                    await self._async_login()
                    return await self._async_fetch_data()
                except ConfigEntryAuthFailed:
                    raise
                except Exception as retry_error:
                    if _is_auth_error(retry_error):
                        raise ConfigEntryAuthFailed(
                            "NAS credentials were rejected during reauthentication"
                        ) from retry_error
                    raise UpdateFailed(
                        f"Failed to fetch NAS data after reauthentication: {retry_error}"
                    ) from retry_error

            if isinstance(
                error, (aiohttp.ClientError, TimeoutError, RequestFailedError)
            ):
                raise UpdateFailed(f"Error fetching NAS data: {error}") from error
            raise UpdateFailed(f"Unexpected NAS response: {error}") from error

    async def async_shutdown(self) -> None:
        """Stop coordinator timers and close the shared client session."""
        await super().async_shutdown()
        await self._async_close_client()

    async def _async_close_client(self) -> None:
        """Close only the client session so reauthentication remains possible."""
        session = getattr(self.client, "session", None)
        if session is not None and not getattr(session, "closed", False):
            await self.client.__aexit__(None, None, None)
