"""Shared entity and registry helpers for My Cloud."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


def main_device_info(data: dict) -> DeviceInfo:
    """Build the existing main NAS device information."""
    device = data["device_info"]
    version = data["system_version"]
    return DeviceInfo(
        identifiers={(DOMAIN, device["serial_number"])},
        name=device["name"],
        manufacturer="Western Digital",
        model=device["description"],
        sw_version=version["firmware"],
    )


def _parent_device_link(
    hass: HomeAssistant, config_entry: ConfigEntry, data: dict
) -> dict[str, object]:
    """Return a parent link supported by both older and current HA releases."""
    identifier = (DOMAIN, data["device_info"]["serial_number"])
    if "via_device_id" not in getattr(DeviceInfo, "__annotations__", {}):
        return {"via_device": identifier}

    registry = dr.async_get(hass)
    parent = registry.async_get_device_by_identifier(identifier, config_entry.entry_id)
    if parent is None:
        parent = registry.async_get_or_create(
            config_entry_id=config_entry.entry_id, **main_device_info(data)
        )
    return {"via_device_id": parent.id}


def disk_device_info(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    data: dict,
    disk: dict,
) -> DeviceInfo:
    """Build the existing child device information for a disk."""
    device = data["device_info"]
    version = data["system_version"]
    return DeviceInfo(
        identifiers={(DOMAIN, disk["sn"])},
        name=f"{device['name']} Disk {disk['name']}",
        manufacturer="Western Digital",
        model=disk["model"],
        sw_version=version["firmware"],
        hw_version=disk["rev"],
        **_parent_device_link(hass, config_entry, data),
    )


def volume_device_info(
    hass: HomeAssistant, config_entry: ConfigEntry, data: dict, volume: dict
) -> DeviceInfo:
    """Keep an existing legacy volume device ID or create a collision-safe one."""
    device = data["device_info"]
    legacy_identifier = (DOMAIN, str(volume["id"]))
    registry = dr.async_get(hass)
    if get_owned_device := getattr(registry, "async_get_device_by_identifier", None):
        existing = get_owned_device(legacy_identifier, config_entry.entry_id)
    else:
        existing = registry.async_get_device(identifiers={legacy_identifier})

    if existing is not None and config_entry.entry_id in existing.config_entries:
        identifier = legacy_identifier
    else:
        identifier = (
            DOMAIN,
            f"{device['serial_number']}_{volume['id']}",
        )

    return DeviceInfo(
        identifiers={identifier},
        name=f"{device['name']} {volume['label']}",
        manufacturer="Western Digital",
        model="Storage Volume",
        **_parent_device_link(hass, config_entry, data),
    )


def resolve_volume_unique_id(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    platform: str,
    legacy_unique_id: str,
    scoped_unique_id: str,
) -> str:
    """Preserve an owned legacy ID and scope all new/colliding volume IDs."""
    if owned_entity_id(hass, config_entry, platform, legacy_unique_id) is not None:
        return legacy_unique_id
    return scoped_unique_id


def owned_entity_id(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    platform: str,
    unique_id: str,
) -> str | None:
    """Return an entity ID only when this config entry owns the registration."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
    if entity_id is not None:
        existing = registry.async_get(entity_id)
        if existing is not None and existing.config_entry_id == config_entry.entry_id:
            return entity_id
    return None
