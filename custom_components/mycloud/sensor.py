"""Sensor platform for the My Cloud integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .binary_sensor import legacy_sensor_entities
from .coordinator import MyCloudDataUpdateCoordinator
from .entity import (
    disk_device_info,
    main_device_info,
    resolve_volume_unique_id,
    volume_device_info,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the existing My Cloud sensors from coordinator data."""
    coordinator: MyCloudDataUpdateCoordinator = config_entry.runtime_data
    data = coordinator.data
    device_data = data["device_info"]
    serial_number = device_data["serial_number"]
    device_name = device_data["name"]
    device = main_device_info(data)

    entities: list[SensorEntity] = [
        MyCloudCPUSensor(coordinator, device, serial_number, device_name),
        MyCloudMemorySensor(coordinator, device, serial_number, device_name),
        MyCloudTotalStorageSensor(coordinator, device, serial_number, device_name),
        MyCloudUsedStorageSensor(coordinator, device, serial_number, device_name),
        MyCloudUnusedStorageSensor(coordinator, device, serial_number, device_name),
    ]

    for disk in data["system_info"]["disks"]:
        disk_name = f"{device_name} Disk {disk['name']}"
        disk_device = disk_device_info(hass, config_entry, data, disk)
        entities.extend(
            (
                MyCloudDiskTempSensor(
                    coordinator, disk_device, disk["sn"], disk_name, disk
                ),
                MyCloudDiskSizeSensor(
                    coordinator, disk_device, disk["sn"], disk_name, disk
                ),
            )
        )

    for volume in data["system_info"]["volumes"]:
        volume_name = f"{device_name} {volume['label']}"
        legacy_unique_id = f"{volume['id']}_volume_size"
        unique_id = resolve_volume_unique_id(
            hass,
            config_entry,
            "sensor",
            legacy_unique_id,
            f"{serial_number}_{legacy_unique_id}",
        )
        entities.append(
            MyCloudVolumeSizeSensor(
                coordinator,
                volume_device_info(hass, config_entry, data, volume),
                volume_name,
                volume,
                unique_id,
            )
        )

    entities.extend(legacy_sensor_entities(hass, config_entry))
    async_add_entities(entities)


class MyCloudSensorBase(CoordinatorEntity[MyCloudDataUpdateCoordinator], SensorEntity):
    """Base class retaining the existing system entity identity."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: MyCloudDataUpdateCoordinator,
        device_info: DeviceInfo,
        serial_number: str,
        device_name: str,
        key: str,
        name: str,
        unit: str | None = None,
        device_class: SensorDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = f"{serial_number}_{key}"
        self._attr_name = f"{device_name} {name}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class


class MyCloudCPUSensor(MyCloudSensorBase):
    """Existing CPU usage sensor."""

    _attr_icon = "mdi:cpu-64-bit"

    def __init__(self, coordinator, device_info, serial_number, device_name) -> None:
        super().__init__(
            coordinator,
            device_info,
            serial_number,
            device_name,
            "cpu_usage",
            "CPU Usage",
            unit="%",
        )

    @property
    def native_value(self):
        """Return CPU usage."""
        return self.coordinator.data["system_status"]["cpu"]


class MyCloudMemorySensor(MyCloudSensorBase):
    """Existing memory usage sensor."""

    _attr_icon = "mdi:memory"

    def __init__(self, coordinator, device_info, serial_number, device_name) -> None:
        super().__init__(
            coordinator,
            device_info,
            serial_number,
            device_name,
            "memory_usage",
            "Memory Usage",
            unit="%",
        )

    @property
    def native_value(self):
        """Return the existing memory calculation unchanged."""
        memory = self.coordinator.data["system_status"]["memory"]
        total = memory["total"]
        if total > 0:
            return round(((total - memory["unused"]) / total) * 100, 2)
        return None


class MyCloudStorageSensor(
    CoordinatorEntity[MyCloudDataUpdateCoordinator], SensorEntity
):
    """Base for existing system storage sensors."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.TERABYTES

    def __init__(
        self, coordinator, device_info, serial_number, device_name, key, name, icon
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = f"{serial_number}_{key}"
        self._attr_name = f"{device_name} {name}"
        self._attr_icon = icon
        self._size_key = key.removesuffix("_storage")

    @property
    def native_value(self):
        """Return the existing storage value."""
        return int(self.coordinator.data["system_info"]["size"][self._size_key])


class MyCloudTotalStorageSensor(MyCloudStorageSensor):
    def __init__(self, coordinator, device_info, serial_number, device_name) -> None:
        super().__init__(
            coordinator,
            device_info,
            serial_number,
            device_name,
            "total_storage",
            "Total Storage",
            "mdi:database",
        )


class MyCloudUsedStorageSensor(MyCloudStorageSensor):
    def __init__(self, coordinator, device_info, serial_number, device_name) -> None:
        super().__init__(
            coordinator,
            device_info,
            serial_number,
            device_name,
            "used_storage",
            "Used Storage",
            "mdi:database-minus",
        )


class MyCloudUnusedStorageSensor(MyCloudStorageSensor):
    def __init__(self, coordinator, device_info, serial_number, device_name) -> None:
        super().__init__(
            coordinator,
            device_info,
            serial_number,
            device_name,
            "unused_storage",
            "Unused Storage",
            "mdi:database-plus",
        )


class MyCloudDiskTempSensor(
    CoordinatorEntity[MyCloudDataUpdateCoordinator], SensorEntity
):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer"

    def __init__(
        self, coordinator, device_info, serial_number, disk_name, disk
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = f"{serial_number}_disk_temp"
        self._attr_name = f"{disk_name} Temperature"
        self._disk_name = disk["name"]

    @property
    def native_value(self):
        """Return disk temperature, or unknown for malformed optional data."""
        for disk in self.coordinator.data.get("system_info", {}).get("disks", []):
            if disk.get("name") == self._disk_name:
                try:
                    return float(disk.get("temp"))
                except (TypeError, ValueError):
                    return None
        return None


class MyCloudDiskSizeSensor(
    CoordinatorEntity[MyCloudDataUpdateCoordinator], SensorEntity
):
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.TERABYTES
    _attr_icon = "mdi:harddisk"

    def __init__(
        self, coordinator, device_info, serial_number, disk_name, disk
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = f"{serial_number}_disk_size"
        self._attr_name = f"{disk_name} Size"
        self._disk_name = disk["name"]

    @property
    def native_value(self):
        """Return disk size."""
        for disk in self.coordinator.data.get("system_info", {}).get("disks", []):
            if disk.get("name") == self._disk_name:
                try:
                    return int(disk.get("size"))
                except (TypeError, ValueError):
                    return None
        return None


class MyCloudVolumeSizeSensor(
    CoordinatorEntity[MyCloudDataUpdateCoordinator], SensorEntity
):
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfInformation.BYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.TERABYTES
    _attr_icon = "mdi:harddisk"

    def __init__(
        self, coordinator, device_info, volume_name, volume, unique_id
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = unique_id
        self._attr_name = f"{volume_name} Size"
        self._volume_id = volume["id"]

    @property
    def native_value(self):
        """Return volume size."""
        volumes = self.coordinator.data.get("system_info", {}).get("volumes", [])
        for volume in volumes:
            if volume.get("id") == self._volume_id:
                try:
                    return int(volume.get("size"))
                except (TypeError, ValueError):
                    return None
        return None
