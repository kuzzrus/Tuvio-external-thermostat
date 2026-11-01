"""Config flow for Tuya External Thermostat."""

import math
from typing import Any, override

import voluptuous as vol
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.climate.const import ATTR_HVAC_MODES, HVACMode
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    ATTR_SUPPORTED_FEATURES,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntityFilterSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_ACTIVATION_HYSTERESIS,
    CONF_DEACTIVATION_HYSTERESIS,
    CONF_HVAC_MODES,
    CONF_SENSOR,
    CONF_TARGET_CLIMATE,
    DOMAIN,
    MAX_HYSTERESIS,
    MAX_TEMPERATURE,
    MIN_HYSTERESIS,
    MIN_TEMPERATURE,
    SETTING_DEFAULTS,
)
from .settings import sensor_from_entry, settings_from_entry, validate_settings


def _entity_selector(*, integration: str | None = None) -> EntitySelector:
    """Return a selector for supported Tuya climate entities."""
    entity_filter = EntityFilterSelectorConfig(domain="climate")
    if integration is not None:
        entity_filter["integration"] = integration
    return EntitySelector(EntitySelectorConfig(filter=entity_filter, multiple=False))


def _sensor_selector() -> EntitySelector:
    """Return a selector for temperature sensors."""
    return EntitySelector(
        EntitySelectorConfig(
            filter={"domain": "sensor", "device_class": "temperature"},
            multiple=False,
        )
    )


def _number_selector(key: str) -> NumberSelector:
    """Return the correct numeric selector for one setting."""
    hysteresis = key in (
        CONF_ACTIVATION_HYSTERESIS,
        CONF_DEACTIVATION_HYSTERESIS,
    )
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_HYSTERESIS if hysteresis else MIN_TEMPERATURE,
            max=MAX_HYSTERESIS if hysteresis else MAX_TEMPERATURE,
            step=0.1 if hysteresis else 0.5,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=UnitOfTemperature.CELSIUS,
        )
    )


def _settings_schema(defaults: dict[str, Any]) -> dict[vol.Marker, object]:
    """Return the shared settings part of a form schema."""
    return {
        vol.Required(key, default=defaults.get(key, default)): _number_selector(key)
        for key, default in SETTING_DEFAULTS.items()
    }


def _valid_sensor_state(state: State | None) -> bool:
    """Return whether a state contains a usable temperature."""
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return False
    try:
        value = float(state.state)
        if not math.isfinite(value):
            return False
        TemperatureConverter.convert(
            value,
            state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature.CELSIUS),
            UnitOfTemperature.CELSIUS,
        )
    except TypeError, ValueError:
        return False
    return True


class TuyaExternalThermostatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tuya External Thermostat."""

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        _config_entry: ConfigEntry,
    ) -> TuyaExternalThermostatOptionsFlow:
        """Return the options flow."""
        return TuyaExternalThermostatOptionsFlow()

    def _schema(self, defaults: dict[str, Any]) -> vol.Schema:
        """Build the user form schema."""
        climate_key: vol.Marker = vol.Required(CONF_TARGET_CLIMATE)
        sensor_key: vol.Marker = vol.Required(CONF_SENSOR)
        if CONF_TARGET_CLIMATE in defaults:
            climate_key = vol.Required(
                CONF_TARGET_CLIMATE, default=defaults[CONF_TARGET_CLIMATE]
            )
        if CONF_SENSOR in defaults:
            sensor_key = vol.Required(CONF_SENSOR, default=defaults[CONF_SENSOR])

        return vol.Schema(
            {
                vol.Required(
                    CONF_NAME,
                    default=defaults.get(CONF_NAME, "Tuya external thermostat"),
                ): TextSelector(TextSelectorConfig()),
                climate_key: _entity_selector(integration="tuya"),
                sensor_key: _sensor_selector(),
                **_settings_schema(defaults),
            }
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a thermostat from a Tuya climate and temperature sensor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            climate_entity_id = user_input[CONF_TARGET_CLIMATE]
            climate_state = self.hass.states.get(climate_entity_id)
            registry_entry = er.async_get(self.hass).async_get(climate_entity_id)

            if climate_state is None:
                errors[CONF_TARGET_CLIMATE] = "target_not_found"
            elif registry_entry is None or registry_entry.platform != "tuya":
                errors[CONF_TARGET_CLIMATE] = "target_not_tuya"
            elif not int(
                climate_state.attributes.get(ATTR_SUPPORTED_FEATURES, 0)
            ) & int(ClimateEntityFeature.TARGET_TEMPERATURE):
                errors[CONF_TARGET_CLIMATE] = "target_no_temperature"

            available_modes = (
                [
                    mode
                    for mode in (HVACMode.HEAT, HVACMode.COOL)
                    if mode.value in climate_state.attributes.get(ATTR_HVAC_MODES, [])
                ]
                if climate_state is not None
                else []
            )
            if climate_state is not None and not available_modes:
                errors[CONF_TARGET_CLIMATE] = "target_no_supported_mode"

            if not _valid_sensor_state(self.hass.states.get(user_input[CONF_SENSOR])):
                errors[CONF_SENSOR] = "sensor_unavailable"

            try:
                validate_settings(user_input)
            except ValueError:
                errors["base"] = "invalid_settings"

            if not errors:
                assert climate_state is not None
                await self.async_set_unique_id(climate_entity_id)
                self._abort_if_unique_id_configured()
                name = str(user_input[CONF_NAME]).strip()
                if not name:
                    name = str(
                        climate_state.attributes.get(
                            ATTR_FRIENDLY_NAME, "Tuya external thermostat"
                        )
                    )
                data = {
                    CONF_TARGET_CLIMATE: climate_entity_id,
                    CONF_SENSOR: user_input[CONF_SENSOR],
                    CONF_HVAC_MODES: [mode.value for mode in available_modes],
                }
                options = {key: float(user_input[key]) for key in SETTING_DEFAULTS}
                return self.async_create_entry(
                    title=name,
                    data=data,
                    options=options,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self._schema(user_input or {}),
            errors=errors,
        )


class TuyaExternalThermostatOptionsFlow(OptionsFlow):
    """Update an external thermostat without reloading it."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage thermostat options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _valid_sensor_state(self.hass.states.get(user_input[CONF_SENSOR])):
                errors[CONF_SENSOR] = "sensor_unavailable"
            try:
                validate_settings(user_input)
            except ValueError:
                errors["base"] = "invalid_settings"
            if not errors:
                return self.async_create_entry(data=user_input)

        defaults: dict[str, Any] = settings_from_entry(self.config_entry)
        defaults[CONF_SENSOR] = sensor_from_entry(self.config_entry)
        if user_input is not None:
            defaults.update(user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SENSOR, default=defaults[CONF_SENSOR]
                    ): _sensor_selector(),
                    **_settings_schema(defaults),
                }
            ),
            errors=errors,
        )
