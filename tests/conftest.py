"""Shared offline fixtures for My Cloud tests."""

from __future__ import annotations

import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_socket

pytest_plugins = ["pytest_homeassistant_custom_component"]


if sys.platform == "win32":

    def _disable_remote_sockets(*, allow_unix_socket=False):
        """Keep Windows event-loop sockets available while blocking remote hosts."""
        pytest_socket.enable_socket()
        pytest_socket.socket_allow_hosts(["127.0.0.1", "::1", "localhost"])

    pytest_socket.disable_socket = _disable_remote_sockets


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the integration from custom_components."""
    yield


@pytest.fixture
def nas_data():
    """Return representative data shared by OS 2 and OS 5 methods."""
    return {
        "system_info": {
            "disks": [
                {
                    "id": "disk1",
                    "name": "Disk_1",
                    "sn": "DISK-SERIAL-1",
                    "model": "WD40EFRX",
                    "rev": "1.0",
                    "size": 4_000_000_000_000,
                    "temp": 34,
                    "healthy": True,
                    "sleep": False,
                    "failed": False,
                    "over_temp": False,
                }
            ],
            "volumes": [
                {
                    "id": "1",
                    "name": "Volume_1",
                    "label": "Volume 1",
                    "size": 4_000_000_000_000,
                    "mounted": True,
                    "unlocked": True,
                    "encrypted": False,
                }
            ],
            "size": {
                "total": 4_000_000_000_000,
                "used": 1_000_000_000_000,
                "unused": 3_000_000_000_000,
            },
        },
        "system_status": {
            "cpu": 12,
            "memory": {"total": 1024, "unused": 256, "simple": "1 GB"},
        },
        "device_info": {
            "serial_number": "NAS-SERIAL-1",
            "name": "Test NAS",
            "description": "WD My Cloud Mirror",
        },
        "system_version": {"firmware": "5.33.102"},
    }


@pytest.fixture
def make_nas_client(nas_data):
    """Build a fully asynchronous NAS client mock."""

    def _make(data=None):
        values = deepcopy(data or nas_data)
        session = SimpleNamespace(closed=False)
        client = MagicMock()
        client.session = session

        async def _enter():
            session.closed = False
            return client

        async def _exit(*_args):
            session.closed = True

        client.__aenter__ = AsyncMock(side_effect=_enter)
        client.__aexit__ = AsyncMock(side_effect=_exit)
        client.system_info = AsyncMock(return_value=values["system_info"])
        client.system_status = AsyncMock(return_value=values["system_status"])
        client.device_info = AsyncMock(return_value=values["device_info"])
        client.system_version = AsyncMock(return_value=values["system_version"])
        return client

    return _make
