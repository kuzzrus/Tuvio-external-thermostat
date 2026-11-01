"""Live number settings for Tuya External Thermostat."""

import math
from typing import override

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ACTIVATION_HYSTERESIS,
    CONF_COOL_ACTIVE_TEMPERATURE,
    CONF_COOL_IDLE_TEMPERATURE,
    CONF_DEACTIVATION_HYSTERESIS,
    CONF_HEAT_ACTIVE_TEMPERATURE,
    CONF_HEAT_IDLE_TEMPERATURE,
    DOMAIN,
    MAX_HYSTERESIS,
    MAX_TEMPERATURE,
    MIN_HYSTERESIS,
    MIN_TEMPERATURE,
    SETTING_DEFAULTS,
    settings_updated_signal,
)
from .entity import device_info_for_entry
from .settings import settings_from_entry, validate_settings


class ThermostatNumberDescription(NumberEntityDescription, frozen_or_thawed=True):
    """Describe one stored thermostat setting."""

    config_key: str


THERMOSTAT_NUMBERS: tuple[ThermostatNumberDescription, ...] = (
    ThermostatNumberDescription(
        key="activation_hysteresis",
        translation_key="activation_hysteresis",
        config_key=CONF_ACTIVATION_HYSTERESIS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=MIN_HYSTERESIS,
        native_max_value=MAX_HYSTERESIS,
        native_step=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ThermostatNumberDescription(
        key="deactivation_hysteresis",
        translation_key="deactivation_hysteresis",
        config_key=CONF_DEACTIVATION_HYSTERESIS,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=MIN_HYSTERESIS,
        native_max_value=MAX_HYSTERESIS,
        native_step=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ThermostatNumberDescription(
        key="heat_active_temperature",
        translation_key="heat_active_temperature",
        config_key=CONF_HEAT_ACTIVE_TEMPERATURE,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=MIN_TEMPERATURE,
        native_max_value=MAX_TEMPERATURE,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ThermostatNumberDescription(
        key="heat_idle_temperature",
        translation_key="heat_idle_temperature",
        config_key=CONF_HEAT_IDLE_TEMPERATURE,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=MIN_TEMPERATURE,
        native_max_value=MAX_TEMPERATURE,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ThermostatNumberDescription(
        key="cool_active_temperature",
        translation_key="cool_active_temperature",
        config_key=CONF_COOL_ACTIVE_TEMPERATURE,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=MIN_TEMPERATURE,
        native_max_value=MAX_TEMPERATURE,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ThermostatNumberDescription(
        key="cool_idle_temperature",
        translation_key="cool_idle_temperature",
        config_key=CONF_COOL_IDLE_TEMPERATURE,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=MIN_TEMPERATURE,
        native_max_value=MAX_TEMPERATURE,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all live thermostat settings."""
    device_info = device_info_for_entry(hass, entry)
    async_add_entities(
        [
            ThermostatNumber(entry, device_info, description)
            for description in THERMOSTAT_NUMBERS
        ]
    )


class ThermostatNumber(NumberEntity):
    """Store one live external thermostat setting."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    entity_description: ThermostatNumberDescription

    def __init__(
        self,
        entry: ConfigEntry,
        device_info: DeviceInfo,
        description: ThermostatNumberDescription,
    ) -> None:
        """Initialize a setting entity."""
        self._entry = entry
        self._attr_device_info = device_info
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to changes from the options flow and sibling numbers."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                settings_updated_signal(self._entry.entry_id),
                self._handle_settings_updated,
            )
        )

    @callback
    def _handle_settings_updated(self) -> None:
        """Publish a changed stored value."""
        self.async_write_ha_state()

    def _value(self, key: str) -> float:
        """Return one current setting."""
        return settings_from_entry(self._entry)[key]

    @property
    @override
    def native_value(self) -> float:
        """Return the stored value."""
        return self._value(self.entity_description.config_key)

    @property
    @override
    def native_min_value(self) -> float:
        """Keep paired active and idle setpoints in a valid order."""
        key = self.entity_description.config_key
        if key == CONF_HEAT_ACTIVE_TEMPERATURE:
            return self._value(CONF_HEAT_IDLE_TEMPERATURE) + 0.5
        if key == CONF_COOL_IDLE_TEMPERATURE:
            return self._value(CONF_COOL_ACTIVE_TEMPERATURE) + 0.5
        return super().native_min_value

    @property
    @override
    def native_max_value(self) -> float:
        """Keep paired active and idle setpoints in a valid order."""
        key = self.entity_description.config_key
        if key == CONF_HEAT_IDLE_TEMPERATURE:
            return self._value(CONF_HEAT_ACTIVE_TEMPERATURE) - 0.5
        if key == CONF_COOL_ACTIVE_TEMPERATURE:
            return self._value(CONF_COOL_IDLE_TEMPERATURE) - 0.5
        return super().native_max_value

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Save and apply a setting without reloading the integration."""
        step = float(self.entity_description.native_step or 1.0)
        if (
            value < self.native_min_value
            or value > self.native_max_value
            or not math.isclose(value / step, round(value / step), abs_tol=1e-6)
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_thermostat_setting",
            )

        options = dict(self._entry.options)
        options[self.entity_description.config_key] = float(value)
        candidate = {
            key: float(options.get(key, default))
            for key, default in SETTING_DEFAULTS.items()
        }
        try:
            validate_settings(candidate)
        except ValueError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_thermostat_setting",
            ) from err

        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()
