"""Tests for shared coordinator updates and errors."""

import asyncio
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mycloud._vendor.wdnas_client.exceptions import (
    InvalidLoginError,
    RequestFailedError,
)
from custom_components.mycloud.const import DOMAIN
from custom_components.mycloud.coordinator import MyCloudDataUpdateCoordinator


def _entry(version=5, options=None):
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "Host": "nas.local",
            "Username": "admin",
            "Password": "secret",
            "Version": version,
        },
        options=options or {},
        unique_id=f"nas-{version}",
    )


async def _run_first_update(coordinator):
    """Exercise coordinator setup and its first data update in isolation."""
    await coordinator._async_setup()
    coordinator.async_set_updated_data(await coordinator._async_update_data())


@pytest.mark.parametrize("version", [2, 5])
async def test_coordinator_fetches_existing_data_for_os_versions(
    hass, make_nas_client, version
):
    """The refactor must keep all four established calls for OS 2 and OS 5."""
    client = make_nas_client()
    entry = _entry(version, {"update_interval": 123})
    entry.add_to_hass(hass)
    coordinator = MyCloudDataUpdateCoordinator(hass, entry, client)

    await _run_first_update(coordinator)

    expected_keys = {
        "system_info",
        "system_status",
        "device_info",
        "system_version",
    }
    if version == 5:
        expected_keys.update(
            {
                "diagnostics",
                "volume_status",
                "system_warning",
                "internet_access",
                "optional_available",
            }
        )
    assert set(coordinator.data) == expected_keys
    assert coordinator.update_interval.total_seconds() == 123
    client.__aenter__.assert_awaited_once()
    client.system_info.assert_awaited_once()
    client.system_status.assert_awaited_once()
    client.device_info.assert_awaited_once()
    client.system_version.assert_awaited_once()
    for method in (
        client.diagnostics,
        client.volume_status,
        client.system_warning,
        client.internet_access,
    ):
        if version == 5:
            method.assert_awaited_once()
        else:
            method.assert_not_awaited()
    await coordinator.async_shutdown()
    assert client.session.closed


async def test_v4_coordinator_fetches_supported_monitoring_data(
    hass, make_nas_client, v4_data
):
    client = make_nas_client(v4_data)
    entry = _entry(4)
    entry.add_to_hass(hass)
    coordinator = MyCloudDataUpdateCoordinator(hass, entry, client)

    await _run_first_update(coordinator)

    assert coordinator.data["device_info"]["model_number"] == "sq"
    assert coordinator.data["system_version"]["firmware"] == "04.06.00-111"
    assert coordinator.data["system_status"]["temperature"] == "good"
    assert coordinator.data["optional_available"]["system_version"] is True
    assert coordinator.data["optional_available"]["system_status"] is True
    assert coordinator.data["optional_available"]["internet_access"] is True
    assert coordinator.data["internet_access"] is True
    client.internet_access.assert_awaited_once()
    client.diagnostics.assert_not_awaited()
    client.volume_status.assert_not_awaited()
    client.reboot.assert_not_awaited()
    client.shutdown.assert_not_awaited()
    await coordinator.async_shutdown()


async def test_v4_optional_state_failure_does_not_block_device(
    hass, make_nas_client, v4_data
):
    client = make_nas_client(v4_data)
    client.system_status.side_effect = ValueError("malformed optional XML")
    client.internet_access.side_effect = ValueError("invalid connectivity")
    entry = _entry(4)
    entry.add_to_hass(hass)
    coordinator = MyCloudDataUpdateCoordinator(hass, entry, client)

    await _run_first_update(coordinator)

    assert coordinator.data["device_info"]["name"] == "NAS02"
    assert coordinator.data["system_status"] == {}
    assert coordinator.data["optional_available"]["system_status"] is False
    assert coordinator.data["internet_access"] is None
    assert coordinator.data["optional_available"]["internet_access"] is False
    await coordinator.async_shutdown()


async def test_v4_expired_session_is_reauthenticated_once(
    hass, make_nas_client, v4_data
):
    client = make_nas_client(v4_data)
    entry = _entry(4)
    entry.add_to_hass(hass)
    coordinator = MyCloudDataUpdateCoordinator(hass, entry, client)
    await _run_first_update(coordinator)
    client.system_info.side_effect = [
        InvalidLoginError("expired"),
        v4_data["system_info"],
    ]

    coordinator.async_set_updated_data(await coordinator._async_update_data())

    assert client.__aenter__.await_count == 2
    assert client.close.await_count == 1
    client.__aexit__.assert_not_awaited()
    await coordinator.async_shutdown()


async def test_coordinator_reauthenticates_once(hass, make_nas_client, nas_data):
    """An expired session is closed, reopened, and retried once."""
    client = make_nas_client()
    entry = _entry()
    entry.add_to_hass(hass)
    coordinator = MyCloudDataUpdateCoordinator(hass, entry, client)
    await _run_first_update(coordinator)
    client.system_info.side_effect = [RequestFailedError(403), nas_data["system_info"]]

    coordinator.async_set_updated_data(await coordinator._async_update_data())

    assert client.__aenter__.await_count == 2
    assert client.__aexit__.await_count == 1
    client.close.assert_not_awaited()
    assert coordinator.data["device_info"]["serial_number"] == "NAS-SERIAL-1"
    await coordinator.async_shutdown()


async def test_os5_initial_auth_error_keeps_historical_single_retry(
    hass, make_nas_client
):
    client = make_nas_client()
    client.system_info.side_effect = RequestFailedError(403)
    entry = _entry()
    entry.add_to_hass(hass)
    coordinator = MyCloudDataUpdateCoordinator(hass, entry, client)

    await coordinator._async_setup()
    with pytest.raises(ConfigEntryAuthFailed, match="rejected during reauthentication"):
        await coordinator._async_update_data()

    assert client.__aenter__.await_count == 2
    client.__aexit__.assert_awaited_once()
    client.close.assert_not_awaited()


@pytest.mark.parametrize(
    "error",
    [aiohttp.ClientConnectionError("offline"), RequestFailedError(503)],
)
async def test_coordinator_connection_errors_are_update_failed(
    hass, make_nas_client, error
):
    """Transport and HTTP failures receive coordinator retry semantics."""
    client = make_nas_client()
    client.system_info.side_effect = error
    entry = _entry()
    entry.add_to_hass(hass)
    coordinator = MyCloudDataUpdateCoordinator(hass, entry, client)

    await coordinator._async_setup()
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    await coordinator.async_shutdown()


async def test_setup_auth_failure_starts_reauth(hass, make_nas_client):
    """Invalid credentials do not leave a half-open entry or session."""
    client = make_nas_client()
    client.__aenter__.side_effect = InvalidLoginError("bad credentials")
    entry = _entry()
    entry.add_to_hass(hass)

    with patch("custom_components.mycloud.coordinator.nas_client", return_value=client):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == config_entries.SOURCE_REAUTH
        for flow in hass.config_entries.flow.async_progress()
    )
    client.__aexit__.assert_awaited_once()
    client.close.assert_not_awaited()


async def test_session_lifecycle_across_reload_and_unload(hass, make_nas_client):
    """Each setup owns one session and every replaced session is closed once."""
    first_client = make_nas_client()
    second_client = make_nas_client()
    entry = _entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.mycloud.coordinator.nas_client",
        side_effect=[first_client, second_client],
    ) as constructor:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        first_coordinator = entry.runtime_data

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        second_coordinator = entry.runtime_data

        assert first_coordinator is not second_coordinator
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert constructor.call_count == 2
    first_client.__aenter__.assert_awaited_once()
    first_client.__aexit__.assert_awaited_once()
    first_client.close.assert_not_awaited()
    second_client.__aenter__.assert_awaited_once()
    second_client.__aexit__.assert_awaited_once()
    second_client.close.assert_not_awaited()


async def test_home_assistant_stop_closes_session(hass, make_nas_client):
    client = make_nas_client()
    entry = _entry()
    entry.add_to_hass(hass)

    with patch("custom_components.mycloud.coordinator.nas_client", return_value=client):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await hass.async_stop()

    client.__aexit__.assert_awaited_once()
    client.close.assert_not_awaited()


async def test_concurrent_refreshes_do_not_create_parallel_logins(
    hass, make_nas_client
):
    """Coordinator refresh requests reuse the one authenticated session."""
    client = make_nas_client()
    entry = _entry()
    entry.add_to_hass(hass)
    coordinator = MyCloudDataUpdateCoordinator(hass, entry, client)
    await _run_first_update(coordinator)

    await asyncio.gather(*(coordinator.async_request_refresh() for _ in range(4)))

    client.__aenter__.assert_awaited_once()
    await coordinator.async_shutdown()


async def test_v4_concurrent_login_and_cleanup_are_each_executed_once(
    hass, make_nas_client
):
    client = make_nas_client()
    client.session.closed = True
    client.phpsessid = None
    entry = _entry(4)
    entry.add_to_hass(hass)
    coordinator = MyCloudDataUpdateCoordinator(hass, entry, client)

    await asyncio.gather(*(coordinator._async_login() for _ in range(4)))
    assert client.__aenter__.await_count == 1

    await asyncio.gather(*(coordinator._async_close_client() for _ in range(4)))
    client.close.assert_awaited_once()


async def test_reload_does_not_accumulate_update_listeners(hass, make_nas_client):
    """Only the current setup listener reacts to an options update."""
    first_client = make_nas_client()
    second_client = make_nas_client()
    entry = _entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.mycloud.coordinator.nas_client",
        side_effect=[first_client, second_client],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    with patch.object(hass.config_entries, "async_reload") as reload_mock:
        hass.config_entries.async_update_entry(entry, options={"update_interval": 321})
        await hass.async_block_till_done()

    reload_mock.assert_awaited_once_with(entry.entry_id)
