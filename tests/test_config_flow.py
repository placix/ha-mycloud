"""Offline tests for setup validation and reauthentication."""

import asyncio
from unittest.mock import patch

import aiohttp
import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from wdnas_client.exceptions import InvalidLoginError

from custom_components.mycloud.config_flow import (
    CannotConnect,
    InvalidAuth,
    UnsupportedFirmware,
    _validate_host,
    async_validate_input,
)
from custom_components.mycloud.const import DOMAIN

USER_INPUT = {
    "Host": "nas.local",
    "Username": "admin",
    "Password": "secret",
    "Version": 5,
}


@pytest.mark.parametrize(
    ("value", "expected"),
    [("192.168.1.10", "192.168.1.10"), ("NAS.Local", "nas.local")],
)
def test_host_validation(value, expected):
    assert _validate_host(value) == expected


@pytest.mark.parametrize("value", ["", "http://nas.local", "nas/path", "bad host"])
def test_invalid_host_rejected(value):
    with pytest.raises(vol.Invalid):
        _validate_host(value)


async def test_validate_input_closes_session(make_nas_client):
    client = make_nas_client()
    with patch("custom_components.mycloud.config_flow.nas_client", return_value=client):
        result = await async_validate_input(USER_INPUT)
    assert result == {"title": "Test NAS", "unique_id": "NAS-SERIAL-1"}
    client.__aexit__.assert_awaited_once()
    assert client.session.closed


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (InvalidLoginError("bad"), InvalidAuth),
        (aiohttp.ClientConnectionError("offline"), CannotConnect),
    ],
)
async def test_validate_input_classifies_failures(make_nas_client, error, expected):
    client = make_nas_client()
    client.__aenter__.side_effect = error
    with (
        patch("custom_components.mycloud.config_flow.nas_client", return_value=client),
        pytest.raises(expected),
    ):
        await async_validate_input(USER_INPUT)


async def test_validate_input_timeout(make_nas_client):
    client = make_nas_client()

    async def never_connect():
        await asyncio.Event().wait()

    client.__aenter__.side_effect = never_connect
    with (
        patch("custom_components.mycloud.config_flow.nas_client", return_value=client),
        patch("custom_components.mycloud.config_flow.CONFIG_FLOW_TIMEOUT", 0.01),
        pytest.raises(CannotConnect),
    ):
        await async_validate_input(USER_INPUT)


async def test_unsupported_firmware_rejected_before_client_creation():
    with (
        patch("custom_components.mycloud.config_flow.nas_client") as constructor,
        pytest.raises(UnsupportedFirmware),
    ):
        await async_validate_input({**USER_INPUT, "Version": 3})
    constructor.assert_not_called()


async def test_user_flow_success_and_duplicate(hass):
    info = {"title": "Test NAS", "unique_id": "NAS-SERIAL-1"}
    with (
        patch(
            "custom_components.mycloud.config_flow.async_validate_input",
            return_value=info,
        ),
        patch("custom_components.mycloud.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT

    with patch(
        "custom_components.mycloud.config_flow.async_validate_input",
        return_value=info,
    ):
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_configured"


async def test_user_flow_rejects_legacy_entry_with_same_host(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=USER_INPUT, unique_id=None)
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data=USER_INPUT,
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("error", "error_key"),
    [
        (InvalidAuth(), "auth"),
        (CannotConnect(), "connection"),
        (UnsupportedFirmware(), "unsupported_firmware"),
        (RuntimeError("unexpected"), "unknown"),
    ],
)
async def test_user_flow_errors(hass, error, error_key):
    with patch(
        "custom_components.mycloud.config_flow.async_validate_input",
        side_effect=error,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error_key}


@pytest.mark.parametrize("existing_unique_id", ["NAS-SERIAL-1", None])
async def test_reauthentication_updates_only_credentials(hass, existing_unique_id):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT,
        unique_id=existing_unique_id,
    )
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.mycloud.config_flow.async_validate_input",
            return_value={"title": "Test NAS", "unique_id": "NAS-SERIAL-1"},
        ),
        patch.object(hass.config_entries, "async_reload"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"Username": "new-admin", "Password": "new-secret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {
        **USER_INPUT,
        "Username": "new-admin",
        "Password": "new-secret",
    }
    assert entry.unique_id == "NAS-SERIAL-1"
