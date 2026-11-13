"""Tests for commands sent to the physical Tuya climate entity."""

from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

import pytest
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.device_registry import DeviceInfo

from custom_components.tuya_external_thermostat.climate import (
    TuyaExternalThermostat,
)
from custom_components.tuya_external_thermostat.const import (
    CONF_HVAC_MODES,
    CONF_SENSOR,
    CONF_TARGET_CLIMATE,
    DOMAIN,
)

TARGET = "climate.tuvio"
SENSOR = "sensor.room_temperature"


def _entry() -> ConfigEntry:
    """Create a minimal config entry for an entity test."""
    now = datetime.now(UTC)
    return ConfigEntry(
        created_at=now,
        data={
            CONF_TARGET_CLIMATE: TARGET,
            CONF_SENSOR: SENSOR,
            CONF_HVAC_MODES: [HVACMode.HEAT, HVACMode.COOL],
        },
        disabled_by=None,
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        entry_id="test-entry",
        minor_version=1,
        modified_at=now,
        options={},
        pref_disable_new_entities=False,
        pref_disable_polling=False,
        source="user",
        subentries_data=(),
        title="Guest room",
        unique_id=TARGET,
        version=1,
    )


@pytest.mark.asyncio
async def test_cooling_sends_active_setpoint(tmp_path: Any) -> None:
    """A hot room selects cooling mode and the active cooling setpoint."""
    hass = HomeAssistant(str(tmp_path))
    calls: list[tuple[str, dict[str, Any]]] = []

    async def record_call(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    hass.services.async_register("climate", SERVICE_SET_HVAC_MODE, record_call)
    hass.services.async_register("climate", SERVICE_SET_TEMPERATURE, record_call)
    hass.states.async_set(TARGET, HVACMode.OFF, {ATTR_TEMPERATURE: 22.0})

    entity = TuyaExternalThermostat(
        _entry(), DeviceInfo(identifiers={(DOMAIN, "test-entry")})
    )
    entity.hass = hass
    entity.async_write_ha_state = lambda: None
    entity._attr_hvac_mode = HVACMode.COOL
    entity._attr_current_temperature = 27.0
    entity._attr_target_temperature = 24.0

    await entity._async_control()

    assert calls == [
        (
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: TARGET, ATTR_HVAC_MODE: HVACMode.COOL.value},
        ),
        (
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: TARGET, ATTR_TEMPERATURE: 16.0},
        ),
    ]
    hass.stop()


@pytest.mark.asyncio
async def test_cooling_returns_to_idle_setpoint(tmp_path: Any) -> None:
    """A cool room keeps cooling mode but sends the idle setpoint."""
    hass = HomeAssistant(str(tmp_path))
    calls: list[tuple[str, dict[str, Any]]] = []

    async def record_call(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    hass.services.async_register("climate", SERVICE_SET_HVAC_MODE, record_call)
    hass.services.async_register("climate", SERVICE_SET_TEMPERATURE, record_call)
    hass.states.async_set(TARGET, HVACMode.COOL, {ATTR_TEMPERATURE: 16.0})

    entity = TuyaExternalThermostat(
        _entry(), DeviceInfo(identifiers={(DOMAIN, "test-entry")})
    )
    entity.hass = hass
    entity.async_write_ha_state = lambda: None
    entity._attr_hvac_mode = HVACMode.COOL
    entity._attr_current_temperature = 23.5
    entity._attr_target_temperature = 24.0
    entity._running = True

    await entity._async_control()

    assert calls == [
        (
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: TARGET, ATTR_TEMPERATURE: 30.0},
        )
    ]
    hass.stop()


@pytest.mark.asyncio
async def test_turning_off_releases_control_without_turning_off_target(
    tmp_path: Any,
) -> None:
    """Turning off the helper leaves the physical Tuya unit untouched."""
    hass = HomeAssistant(str(tmp_path))
    calls: list[tuple[str, dict[str, Any]]] = []

    async def record_call(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    hass.services.async_register("climate", SERVICE_SET_HVAC_MODE, record_call)
    hass.services.async_register("climate", SERVICE_SET_TEMPERATURE, record_call)
    hass.states.async_set(TARGET, HVACMode.COOL, {ATTR_TEMPERATURE: 16.0})

    entity = TuyaExternalThermostat(
        _entry(), DeviceInfo(identifiers={(DOMAIN, "test-entry")})
    )
    entity.hass = hass
    entity.async_write_ha_state = lambda: None
    entity._attr_hvac_mode = HVACMode.COOL
    entity._attr_current_temperature = 27.0

    await entity.async_turn_off()

    assert entity.hvac_mode == HVACMode.OFF
    assert hass.states[TARGET].state == HVACMode.COOL
    assert calls == []
    hass.stop()


@pytest.mark.asyncio
async def test_turning_off_is_allowed_when_target_is_unavailable(tmp_path: Any) -> None:
    """Releasing control does not depend on Tuya or sensor availability."""
    hass = HomeAssistant(str(tmp_path))
    entity = TuyaExternalThermostat(
        _entry(), DeviceInfo(identifiers={(DOMAIN, "test-entry")})
    )
    entity.hass = hass
    entity.async_write_ha_state = lambda: None
    entity._attr_hvac_mode = HVACMode.HEAT
    entity._attr_current_temperature = None

    await entity.async_turn_off()

    assert entity.hvac_mode == HVACMode.OFF
    hass.stop()
