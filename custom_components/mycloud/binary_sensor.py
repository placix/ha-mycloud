"""Binary sensor platform for the My Cloud integration."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MyCloudDataUpdateCoordinator
from .entity import (
    disk_device_info,
    owned_entity_id,
    resolve_volume_unique_id,
    volume_device_info,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the existing My Cloud binary sensors."""
    async_add_entities(_build_binary_entities(hass, config_entry, legacy_only=False))


def legacy_sensor_entities(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> list[BinarySensorEntity]:
    """Return binary entities that must retain historical sensor-domain IDs."""
    return _build_binary_entities(hass, config_entry, legacy_only=True)


def _select_unique_id(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    legacy_unique_id: str,
    scoped_unique_id: str,
    *,
    legacy_only: bool,
) -> str | None:
    """Route one entity to its legacy or proper platform without mutation."""
    legacy_entity_id = owned_entity_id(hass, config_entry, "sensor", legacy_unique_id)
    binary_entity_id = owned_entity_id(
        hass, config_entry, "binary_sensor", legacy_unique_id
    ) or owned_entity_id(hass, config_entry, "binary_sensor", scoped_unique_id)

    if legacy_entity_id is not None and binary_entity_id is not None:
        _LOGGER.error(
            "Conflicting legacy and binary registry entries exist for a My Cloud "
            "entity; neither registration will be loaded automatically"
        )
        return None
    if legacy_only:
        return legacy_unique_id if legacy_entity_id is not None else None
    if legacy_entity_id is not None:
        return None
    return resolve_volume_unique_id(
        hass,
        config_entry,
        "binary_sensor",
        legacy_unique_id,
        scoped_unique_id,
    )


def _build_binary_entities(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    *,
    legacy_only: bool,
) -> list[BinarySensorEntity]:
    """Build current or non-destructive legacy binary entities."""
    coordinator: MyCloudDataUpdateCoordinator = config_entry.runtime_data
    data = coordinator.data
    device_data = data["device_info"]
    device_name = device_data["name"]
    serial_number = device_data["serial_number"]
    entities: list[BinarySensorEntity] = []

    for disk in data["system_info"]["disks"]:
        disk_name = f"{device_name} Disk {disk['name']}"
        disk_device = disk_device_info(hass, config_entry, data, disk)
        for entity_class, suffix in (
            (MyCloudDiskHealthySensor, "healthy"),
            (MyCloudDiskSleepSensor, "sleep"),
            (MyCloudDiskFailedSensor, "failed"),
            (MyCloudDiskOverTempSensor, "over_temp"),
        ):
            unique_id = f"{disk['sn']}_disk_{suffix}"
            selected_unique_id = _select_unique_id(
                hass,
                config_entry,
                unique_id,
                unique_id,
                legacy_only=legacy_only,
            )
            if selected_unique_id is not None:
                entities.append(
                    entity_class(coordinator, disk_device, disk["sn"], disk_name, disk)
                )

    for volume in data["system_info"]["volumes"]:
        volume_name = f"{device_name} {volume['label']}"
        volume_device = volume_device_info(hass, config_entry, data, volume)
        for entity_class, suffix in (
            (MyCloudVolumeMountedSensor, "mounted"),
            (MyCloudVolumeUnlockedSensor, "unlocked"),
            (MyCloudVolumeEncryptedSensor, "encrypted"),
        ):
            legacy_unique_id = f"{volume_name}_volume_{suffix}"
            unique_id = _select_unique_id(
                hass,
                config_entry,
                legacy_unique_id,
                f"{serial_number}_{volume['id']}_volume_{suffix}",
                legacy_only=legacy_only,
            )
            if unique_id is not None:
                entities.append(
                    entity_class(
                        coordinator, volume_device, volume_name, volume, unique_id
                    )
                )

    return entities


class MyCloudDiskBinarySensor(
    CoordinatorEntity[MyCloudDataUpdateCoordinator], BinarySensorEntity
):
    """Base class retaining existing disk binary-sensor identities."""

    def __init__(
        self,
        coordinator,
        device_info,
        serial_number,
        disk_name,
        disk,
        suffix,
        name,
        icon,
        field,
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = f"{serial_number}_disk_{suffix}"
        self._attr_name = f"{disk_name} {name}"
        self._attr_icon = icon
        self._disk_name = disk["name"]
        self._field = field

    @property
    def is_on(self):
        """Return the existing disk boolean value."""
        for disk in self.coordinator.data.get("system_info", {}).get("disks", []):
            if disk.get("name") == self._disk_name:
                return disk.get(self._field, False)
        return False


class MyCloudDiskHealthySensor(MyCloudDiskBinarySensor):
    def __init__(
        self, coordinator, device_info, serial_number, disk_name, disk
    ) -> None:
        super().__init__(
            coordinator,
            device_info,
            serial_number,
            disk_name,
            disk,
            "healthy",
            "Healthy",
            "mdi:shield-check",
            "healthy",
        )


class MyCloudDiskSleepSensor(MyCloudDiskBinarySensor):
    def __init__(
        self, coordinator, device_info, serial_number, disk_name, disk
    ) -> None:
        super().__init__(
            coordinator,
            device_info,
            serial_number,
            disk_name,
            disk,
            "sleep",
            "Sleeping",
            "mdi:sleep",
            "sleep",
        )


class MyCloudDiskFailedSensor(MyCloudDiskBinarySensor):
    def __init__(
        self, coordinator, device_info, serial_number, disk_name, disk
    ) -> None:
        super().__init__(
            coordinator,
            device_info,
            serial_number,
            disk_name,
            disk,
            "failed",
            "Failed",
            "mdi:alert",
            "failed",
        )


class MyCloudDiskOverTempSensor(MyCloudDiskBinarySensor):
    def __init__(
        self, coordinator, device_info, serial_number, disk_name, disk
    ) -> None:
        super().__init__(
            coordinator,
            device_info,
            serial_number,
            disk_name,
            disk,
            "over_temp",
            "Over Temperature",
            "mdi:thermometer-alert",
            "over_temp",
        )


class MyCloudVolumeBinarySensor(
    CoordinatorEntity[MyCloudDataUpdateCoordinator], BinarySensorEntity
):
    """Base for the existing volume binary sensors."""

    def __init__(
        self,
        coordinator,
        device_info,
        volume_name,
        volume,
        unique_id,
        name,
        icon,
        field,
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self._attr_unique_id = unique_id
        self._attr_name = f"{volume_name} {name}"
        self._attr_icon = icon
        self._volume_name = volume["name"]
        self._field = field

    @property
    def is_on(self):
        """Return the existing volume boolean value."""
        volumes = self.coordinator.data.get("system_info", {}).get("volumes", [])
        for volume in volumes:
            if volume.get("name") == self._volume_name:
                return volume.get(self._field, False)
        return False


class MyCloudVolumeMountedSensor(MyCloudVolumeBinarySensor):
    def __init__(
        self, coordinator, device_info, volume_name, volume, unique_id
    ) -> None:
        super().__init__(
            coordinator,
            device_info,
            volume_name,
            volume,
            unique_id,
            "Mounted",
            "mdi:folder-pound",
            "mounted",
        )


class MyCloudVolumeUnlockedSensor(MyCloudVolumeBinarySensor):
    def __init__(
        self, coordinator, device_info, volume_name, volume, unique_id
    ) -> None:
        super().__init__(
            coordinator,
            device_info,
            volume_name,
            volume,
            unique_id,
            "Unlocked",
            "mdi:lock-open",
            "unlocked",
        )


class MyCloudVolumeEncryptedSensor(MyCloudVolumeBinarySensor):
    def __init__(
        self, coordinator, device_info, volume_name, volume, unique_id
    ) -> None:
        super().__init__(
            coordinator,
            device_info,
            volume_name,
            volume,
            unique_id,
            "Encrypted",
            "mdi:lock",
            "encrypted",
        )
