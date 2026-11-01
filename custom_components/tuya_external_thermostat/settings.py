"""Stored settings for the Tuya external thermostat."""

from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_COOL_ACTIVE_TEMPERATURE,
    CONF_COOL_IDLE_TEMPERATURE,
    CONF_HEAT_ACTIVE_TEMPERATURE,
    CONF_HEAT_IDLE_TEMPERATURE,
    CONF_SENSOR,
    SETTING_DEFAULTS,
)


def settings_from_entry(entry: ConfigEntry) -> dict[str, float]:
    """Return all numeric settings with defaults applied."""
    return {
        key: float(entry.options.get(key, entry.data.get(key, default)))
        for key, default in SETTING_DEFAULTS.items()
    }


def sensor_from_entry(entry: ConfigEntry) -> str:
    """Return the selected external temperature sensor."""
    return str(entry.options.get(CONF_SENSOR, entry.data[CONF_SENSOR]))


def validate_settings(data: dict[str, Any]) -> None:
    """Validate the relation between active and idle setpoints."""
    values = {
        key: float(data.get(key, default)) for key, default in SETTING_DEFAULTS.items()
    }
    if (
        values[CONF_HEAT_ACTIVE_TEMPERATURE] <= values[CONF_HEAT_IDLE_TEMPERATURE]
        or values[CONF_COOL_ACTIVE_TEMPERATURE] >= values[CONF_COOL_IDLE_TEMPERATURE]
    ):
        raise ValueError("invalid_setpoint_order")
