"""Shared entity helpers for Tuya External Thermostat."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_TARGET_CLIMATE, DOMAIN


def device_info_for_entry(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    """Build a helper device linked to the selected Tuya air conditioner."""
    via_device: tuple[str, str] | None = None
    entity_entry = er.async_get(hass).async_get(entry.data[CONF_TARGET_CLIMATE])
    if entity_entry is not None and entity_entry.device_id is not None:
        device_entry = dr.async_get(hass).async_get(entity_entry.device_id)
        if device_entry is not None and device_entry.identifiers:
            via_device = sorted(device_entry.identifiers)[0]

    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Tuvio",
        model="External thermostat for Tuya",
        name=entry.title,
    )
    if via_device is not None:
        device_info["via_device"] = via_device
    return device_info
