# <img src="images/icon.png" alt="WD My Cloud App Icon" width="100"> ha-mycloud

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=J-shw&repository=ha-mycloud&category=Integration)

Home Assistant integration for Western Digital My Cloud NAS devices.

This integration is powered by the [wdnas-client](https://github.com/J-shw/wdnas_client) Python library, which handles all communication with the NAS.

---

## Features
- **System Status**: Monitor CPU and memory usage of your My Cloud device.
- **Device Information**: See key details like serial number, name, and firmware version.
- **Disk Information**: See key details about disks, including their health status.
- **Volume Information**: View all volumes size, encryption status and more.

---

## Installation

### HACS (Recommended)
1. Add this repository in HACS.
2. Search for "WD My Cloud" and install the integration.
3. Restart Home Assistant.

### Manual
1. Copy the `custom_components/mycloud` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

---

## Configuration

> [!IMPORTANT]  
> The Admin account can only be active in one place at a time (either the NAS Web UI or this integration).

1.  Go to **Settings** > **Devices & Services**.
2.  Click **Add Integration** and search for "**WD My Cloud**".
3.  Enter your device's **IP address** or **hostname** (e.g., `192.168.1.10` or `wdmycloud`). Do **not** include `http://` or `https://`.
4.  Enter your username and password (Must be an **admin** account)
5. Select NAS software version (Currently 2 or 5 are supported)

---

## Supported Devices & Contributing

This integration currently supports V2 and V5 firmware. You can see a list of tested models in the client library's documentation:

* **[View Known Supported Models](https://github.com/J-shw/wdnas_client/blob/dev/docs/SUPPORTED_MODELS.md)**

**Want to add your device?**

If your model isn't on the list, or if you have a different firmware version, I'd love to add support for it. Please **[open a GitHub Issue](https://github.com/placix/ha-mycloud/issues/new?template=new_device_request.md)** and we can work together to get it added.

---

## Example
<img alt="Screenshot of integration use in Home Assistant" src="https://github.com/user-attachments/assets/0b93e3d9-71ba-4386-93f2-75c210a65656" />

---

## Entities

This integration provides the following entities. `[disk_name]` and `[volume_name]` will be replaced by the actual names found on your device.

### Sensors
* **CPU Usage**: `sensor.wd_my_cloud_cpu_usage`
* **Memory Usage**: `sensor.wd_my_cloud_memory_usage`
* **Total Storage**: `sensor.wd_my_cloud_total_storage`
* **Used Storage**: `sensor.wd_my_cloud_used_storage`
* **Unused Storage**: `sensor.wd_my_cloud_unused_storage`
* **Disk Temperature**: `sensor.wd_my_cloud_disk_[disk_name]_temperature`
* **Disk Size**: `sensor.wd_my_cloud_disk_[disk_name]_size`
* **Volume Size**: `sensor.wd_my_cloud_volume_[volume_name]_size`

WD OS 5 additionally provides diagnostic sensors for process count, cached and
buffered memory (reported by the NAS in KiB), system warning, RAID state and
mode per RAID volume, and file-system type per storage volume.

### Binary Sensors
* **Disk Healthy**: `binary_sensor.wd_my_cloud_disk_[disk_name]_healthy`
* **Disk Sleeping**: `binary_sensor.wd_my_cloud_disk_[disk_name]_sleeping`
* **Disk Failed**: `binary_sensor.wd_my_cloud_disk_[disk_name]_failed`
* **Disk Over Temperature**: `binary_sensor.wd_my_cloud_disk_[disk_name]_over_temperature`
* **Volume Mounted**: `binary_sensor.wd_my_cloud_volume_[volume_name]_mounted`
* **Volume Unlocked**: `binary_sensor.wd_my_cloud_volume_[volume_name]_unlocked`
* **Volume Encrypted**: `binary_sensor.wd_my_cloud_volume_[volume_name]_encrypted`

WD OS 5 additionally provides system-overtemperature (`problem`),
NAS-reported internet connectivity, and a RAID-problem binary sensor per RAID
volume. `degraded` and `damaged` are problems. Active maintenance states such as
`resync`, `resync5`, `recovery`, `migrate`, `reshape`, and `expansion` remain
visible but are not reported as failures. Unknown states remain unknown.

---

## Architecture and compatibility

Each config entry owns one authenticated `wdnas_client` session and one shared
`DataUpdateCoordinator`. The coordinator supplies both the `sensor` and
`binary_sensor` platforms, so entities do not issue independent NAS requests.
The default 600-second polling interval and configurable minimum of 30 seconds
remain unchanged.

Existing system and disk unique IDs remain unchanged. Existing registered volume
unique IDs and device identifiers are detected and retained. New volume entities
are scoped with the NAS serial number and volume ID, preventing collisions when
multiple NAS devices use the same local volume ID. Their registry IDs are not
written to logs.

OS 5 monitoring uses the same session. Optional monitoring endpoints are
isolated and rate-limited: diagnostics, warnings, and internet status are read
at most every 10 minutes, while volume metadata is read at most hourly. A
failure only makes the dependent entities unavailable and does not discard core
system data. OS 2 entries never call these endpoints or create their entities.

No process list is requested. Process count comes from `system_status()`. Raw
RAID UUIDs, disk serials, device and mount paths, usernames, commands, cookies,
and credentials are not exposed as entity attributes or written by the
integration. `volume_status().percentage` is intentionally not treated as
storage utilization, and its `free_size` is not mixed with values from another
endpoint.

Older releases loaded binary entities through the sensor platform. Home
Assistant does not support changing an entity-registry domain atomically. For
existing entries, the integration therefore continues serving those entities at
their registered `sensor.*` IDs without deleting or recreating registry data.
New installations register them correctly under `binary_sensor.*`. A future
domain migration must be explicit and user-approved.

Authentication is checked during new config flows. Connection, timeout,
unsupported-version, duplicate-device, and reauthentication paths are handled
separately. Existing config entries keep their original data keys and continue
to load without migration.

Disk and volume topology is discovered when the config entry is loaded. A reload
is currently required before newly attached disks or newly created volumes are
registered. This also applies to newly appearing OS 5 RAID volumes and to an
optional topology endpoint that was unavailable during initial setup. The legacy client exposes general HTTP failures without a structured
status code, so authentication fallback handling still recognizes status 401/403
from that exception text.

## Development and tests

Tests are offline and use mocked NAS responses:

```powershell
python -m pip install -r requirements_test.txt
python -m pytest
```

To test an unpublished `wdnas_client` checkout, use a separate Home Assistant
venv or container. Install the client there in editable mode and prevent Home
Assistant from replacing it with the public package:

```powershell
python -m pip install -e .\wdnas_client
hass --skip-pip-packages wdnas-client -c C:\path\to\isolated-ha-config
```

Confirm `wdnas_client.__file__` before testing. Do not use this workflow in a
production Home Assistant installation. Phase 2 was developed and tested with
the exact client commit
`4e6389f753efdd942a1a919c065861bce18f9ca9`; export or check out that commit for
the controlled live test.
