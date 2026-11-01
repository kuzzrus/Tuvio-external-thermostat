"""Tests for thermostat setting validation."""

import pytest

from custom_components.tuya_external_thermostat.const import (
    CONF_COOL_ACTIVE_TEMPERATURE,
    CONF_COOL_IDLE_TEMPERATURE,
    CONF_HEAT_ACTIVE_TEMPERATURE,
    CONF_HEAT_IDLE_TEMPERATURE,
)
from custom_components.tuya_external_thermostat.settings import validate_settings


def test_default_settings_are_valid() -> None:
    """The Gree-compatible defaults form valid active and idle pairs."""
    validate_settings({})


@pytest.mark.parametrize(
    "settings",
    [
        {
            CONF_HEAT_ACTIVE_TEMPERATURE: 20.0,
            CONF_HEAT_IDLE_TEMPERATURE: 20.0,
        },
        {
            CONF_HEAT_ACTIVE_TEMPERATURE: 19.5,
            CONF_HEAT_IDLE_TEMPERATURE: 20.0,
        },
        {
            CONF_COOL_ACTIVE_TEMPERATURE: 20.0,
            CONF_COOL_IDLE_TEMPERATURE: 20.0,
        },
        {
            CONF_COOL_ACTIVE_TEMPERATURE: 20.5,
            CONF_COOL_IDLE_TEMPERATURE: 20.0,
        },
    ],
)
def test_invalid_setpoint_order(settings: dict[str, float]) -> None:
    """Active and idle setpoints cannot cross."""
    with pytest.raises(ValueError, match="invalid_setpoint_order"):
        validate_settings(settings)
