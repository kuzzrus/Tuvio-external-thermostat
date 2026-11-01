"""External-sensor climate entity for a Tuya air conditioner."""

import asyncio
import logging
import math
from collections.abc import Callable
from typing import Any, cast, override

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
)
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate.const import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    CONF_ACTIVATION_HYSTERESIS,
    CONF_COOL_ACTIVE_TEMPERATURE,
    CONF_COOL_IDLE_TEMPERATURE,
    CONF_DEACTIVATION_HYSTERESIS,
    CONF_HEAT_ACTIVE_TEMPERATURE,
    CONF_HEAT_IDLE_TEMPERATURE,
    CONF_HVAC_MODES,
    CONF_TARGET_CLIMATE,
    DEFAULT_TARGET_TEMPERATURE,
    DOMAIN,
    MAX_TEMPERATURE,
    MIN_TEMPERATURE,
    settings_updated_signal,
)
from .entity import device_info_for_entry
from .settings import sensor_from_entry, settings_from_entry
from .thermostat import ThermostatMode, should_run

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the virtual thermostat."""
    async_add_entities(
        [TuyaExternalThermostat(entry, device_info_for_entry(hass, entry))]
    )


class TuyaExternalThermostat(ClimateEntity, RestoreEntity):
    """Control a Tuya climate entity from an external temperature sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TEMPERATURE
    _attr_max_temp = MAX_TEMPERATURE
    _attr_target_temperature_step = 0.5
    _attr_translation_key = "external_thermostat"

    def __init__(self, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        """Initialize the thermostat."""
        self._entry = entry
        self._attr_device_info = device_info
        self._attr_unique_id = f"{entry.entry_id}_external_thermostat"
        self._target_entity_id = str(entry.data[CONF_TARGET_CLIMATE])
        self._sensor_entity_id = sensor_from_entry(entry)
        self._attr_hvac_modes = [HVACMode.OFF] + [
            HVACMode(mode) for mode in entry.data[CONF_HVAC_MODES]
        ]
        self._attr_hvac_mode = HVACMode.OFF
        self._last_hvac_mode = next(
            mode for mode in self._attr_hvac_modes if mode != HVACMode.OFF
        )
        self._attr_hvac_action = HVACAction.OFF
        self._attr_current_temperature: float | None = None
        self._attr_target_temperature = DEFAULT_TARGET_TEMPERATURE
        self._running = False
        self._control_lock = asyncio.Lock()
        self._sensor_unsub: Callable[[], None] | None = None
        self._target_unsub: Callable[[], None] | None = None
        self._settings_unsub: Callable[[], None] | None = None

    @property
    @override
    def available(self) -> bool:
        """Return whether the Tuya device and external sensor are available."""
        return self._target_available and self._attr_current_temperature is not None

    @property
    def _target_available(self) -> bool:
        """Return whether the controlled climate entity is available."""
        state = self.hass.states.get(self._target_entity_id)
        return state is not None and state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Restore state and subscribe to the source entities."""
        await super().async_added_to_hass()
        self._target_unsub = async_track_state_change_event(
            self.hass,
            [self._target_entity_id],
            self._async_target_changed,
        )
        self._subscribe_sensor()
        self._settings_unsub = async_dispatcher_connect(
            self.hass,
            settings_updated_signal(self._entry.entry_id),
            self._handle_settings_updated,
        )

        self._update_sensor(self.hass.states.get(self._sensor_entity_id))
        await self._async_restore_state()
        self._running = self._infer_running()
        self._update_hvac_action()

        if self._attr_hvac_mode != HVACMode.OFF and self.available:
            await self._async_control_logged("start")

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Remove state and settings listeners."""
        for unsubscribe in (
            self._sensor_unsub,
            self._target_unsub,
            self._settings_unsub,
        ):
            if unsubscribe is not None:
                unsubscribe()
        await super().async_will_remove_from_hass()

    def _subscribe_sensor(self) -> None:
        """Subscribe to the currently selected temperature sensor."""
        if self._sensor_unsub is not None:
            self._sensor_unsub()
        self._sensor_unsub = async_track_state_change_event(
            self.hass,
            [self._sensor_entity_id],
            self._async_sensor_changed,
        )

    async def _async_restore_state(self) -> None:
        """Restore the virtual target temperature and HVAC mode."""
        last_state = await self.async_get_last_state()
        if last_state is None:
            return

        target = last_state.attributes.get(ATTR_TEMPERATURE)
        if isinstance(target, int | float) and math.isfinite(target):
            self._attr_target_temperature = TemperatureConverter.convert(
                float(target),
                self.hass.config.units.temperature_unit,
                UnitOfTemperature.CELSIUS,
            )

        try:
            mode = HVACMode(last_state.state)
        except ValueError:
            return
        if mode in self._attr_hvac_modes:
            self._attr_hvac_mode = mode
            if mode != HVACMode.OFF:
                self._last_hvac_mode = mode

    async def _async_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle an external sensor update."""
        self._update_sensor(event.data.get("new_state"))
        if self._attr_hvac_mode != HVACMode.OFF and self.available:
            await self._async_control_logged("sensor update")
        self.async_write_ha_state()

    async def _async_target_changed(self, _event: Event[EventStateChangedData]) -> None:
        """Reapply control when the physical Tuya entity changes."""
        if self._attr_hvac_mode != HVACMode.OFF and self.available:
            await self._async_control_logged("Tuya state update")
        self.async_write_ha_state()

    @callback
    def _handle_settings_updated(self) -> None:
        """Schedule control after an option or number entity changes."""
        self.hass.async_create_task(self._async_settings_updated())

    async def _async_settings_updated(self) -> None:
        """Apply live setting and sensor changes."""
        sensor_entity_id = sensor_from_entry(self._entry)
        if sensor_entity_id != self._sensor_entity_id:
            self._sensor_entity_id = sensor_entity_id
            self._subscribe_sensor()
            self._update_sensor(self.hass.states.get(sensor_entity_id))
        if self._attr_hvac_mode != HVACMode.OFF and self.available:
            await self._async_control_logged("settings update")
        self.async_write_ha_state()

    @callback
    def _update_sensor(self, state: State | None) -> None:
        """Store an external sensor value in Celsius."""
        self._attr_current_temperature = None
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        try:
            value = float(state.state)
            if not math.isfinite(value):
                raise ValueError("temperature is not finite")
            self._attr_current_temperature = TemperatureConverter.convert(
                value,
                state.attributes.get(
                    ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature.CELSIUS
                ),
                UnitOfTemperature.CELSIUS,
            )
        except (TypeError, ValueError) as err:
            _LOGGER.error(
                "Unable to read external temperature sensor %s: %s",
                self._sensor_entity_id,
                err,
            )

    def _settings(self) -> dict[str, float]:
        """Return the current live settings."""
        return settings_from_entry(self._entry)

    def _control_setpoints(self) -> tuple[float, float]:
        """Return active and idle setpoints for the selected mode."""
        settings = self._settings()
        if self._attr_hvac_mode == HVACMode.HEAT:
            return (
                settings[CONF_HEAT_ACTIVE_TEMPERATURE],
                settings[CONF_HEAT_IDLE_TEMPERATURE],
            )
        return (
            settings[CONF_COOL_ACTIVE_TEMPERATURE],
            settings[CONF_COOL_IDLE_TEMPERATURE],
        )

    def _target_setpoint_celsius(self, state: State) -> float | None:
        """Return the physical target setpoint in Celsius."""
        value = state.attributes.get(ATTR_TEMPERATURE)
        if not isinstance(value, int | float) or not math.isfinite(value):
            return None
        return TemperatureConverter.convert(
            float(value),
            self.hass.config.units.temperature_unit,
            UnitOfTemperature.CELSIUS,
        )

    def _infer_running(self) -> bool:
        """Infer the dead-band state from the Tuya climate entity."""
        if self._attr_hvac_mode not in (HVACMode.HEAT, HVACMode.COOL):
            return False
        state = self.hass.states.get(self._target_entity_id)
        if state is None or state.state != self._attr_hvac_mode.value:
            return False
        current_setpoint = self._target_setpoint_celsius(state)
        if current_setpoint is None:
            return False
        active_setpoint, idle_setpoint = self._control_setpoints()
        return abs(current_setpoint - active_setpoint) <= abs(
            current_setpoint - idle_setpoint
        )

    def _update_hvac_action(self) -> None:
        """Update the action shown by Home Assistant."""
        if self._attr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_action = HVACAction.OFF
        elif not self._running:
            self._attr_hvac_action = HVACAction.IDLE
        elif self._attr_hvac_mode == HVACMode.HEAT:
            self._attr_hvac_action = HVACAction.HEATING
        else:
            self._attr_hvac_action = HVACAction.COOLING

    async def _async_control_logged(self, reason: str) -> None:
        """Run control without leaking callback errors."""
        try:
            await self._async_control()
        except Exception:
            _LOGGER.exception(
                "Failed to control %s after %s",
                self._target_entity_id,
                reason,
            )

    async def _async_control(self) -> None:
        """Select and send the physical Tuya setpoint."""
        async with self._control_lock:
            if self._attr_hvac_mode not in (HVACMode.HEAT, HVACMode.COOL):
                return
            if (
                self._attr_current_temperature is None
                or self._attr_target_temperature is None
                or not self._target_available
            ):
                return

            settings = self._settings()
            self._running = should_run(
                cast(ThermostatMode, self._attr_hvac_mode.value),
                self._attr_current_temperature,
                self._attr_target_temperature,
                settings[CONF_ACTIVATION_HYSTERESIS],
                settings[CONF_DEACTIVATION_HYSTERESIS],
                self._running,
            )
            self._update_hvac_action()
            active_setpoint, idle_setpoint = self._control_setpoints()
            await self._async_apply_target_setpoint(
                active_setpoint if self._running else idle_setpoint
            )
            self.async_write_ha_state()

    async def _async_apply_target_setpoint(self, setpoint_c: float) -> None:
        """Apply mode and setpoint to the physical Tuya climate entity."""
        state = self.hass.states.get(self._target_entity_id)
        if state is None:
            return

        desired_mode = cast(HVACMode, self._attr_hvac_mode)
        mode_changed = state.state != desired_mode.value
        current_setpoint = self._target_setpoint_celsius(state)
        temperature_changed = current_setpoint is None or not math.isclose(
            current_setpoint, setpoint_c, abs_tol=0.1
        )

        if mode_changed:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_HVAC_MODE,
                {
                    ATTR_ENTITY_ID: self._target_entity_id,
                    ATTR_HVAC_MODE: desired_mode.value,
                },
                blocking=True,
            )
        if mode_changed or temperature_changed:
            service_temperature = TemperatureConverter.convert(
                setpoint_c,
                UnitOfTemperature.CELSIUS,
                self.hass.config.units.temperature_unit,
            )
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
                {
                    ATTR_ENTITY_ID: self._target_entity_id,
                    ATTR_TEMPERATURE: service_temperature,
                },
                blocking=True,
            )

    async def _async_turn_target_off(self) -> None:
        """Turn the physical Tuya climate entity off once."""
        state = self.hass.states.get(self._target_entity_id)
        if state is None or state.state == HVACMode.OFF:
            return
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {
                ATTR_ENTITY_ID: self._target_entity_id,
                ATTR_HVAC_MODE: HVACMode.OFF,
            },
            blocking=True,
        )

    def _ensure_available(self, *, require_sensor: bool = True) -> None:
        """Raise a translated error when control is unavailable."""
        if not self._target_available or (
            require_sensor and self._attr_current_temperature is None
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="entity_unavailable",
            )

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the virtual room target temperature."""
        temperature: float | None = kwargs.get(ATTR_TEMPERATURE)
        requested_mode = kwargs.get(ATTR_HVAC_MODE)
        if temperature is None and requested_mode is None:
            return

        hvac_mode = HVACMode(requested_mode) if requested_mode is not None else None
        self._ensure_available(require_sensor=hvac_mode != HVACMode.OFF)
        if temperature is not None:
            self._attr_target_temperature = float(temperature)
        if hvac_mode is not None:
            await self.async_set_hvac_mode(hvac_mode)
            return
        if self._attr_hvac_mode != HVACMode.OFF:
            try:
                await self._async_control()
            except Exception as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="control_failed",
                ) from err
        self.async_write_ha_state()

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the virtual thermostat mode."""
        if hvac_mode not in self._attr_hvac_modes:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unsupported_hvac_mode",
            )
        self._ensure_available(require_sensor=hvac_mode != HVACMode.OFF)

        try:
            if hvac_mode == HVACMode.OFF:
                self._attr_hvac_mode = HVACMode.OFF
                self._running = False
                self._update_hvac_action()
                await self._async_turn_target_off()
            else:
                self._attr_hvac_mode = hvac_mode
                self._last_hvac_mode = hvac_mode
                self._running = self._infer_running()
                await self._async_control()
        except Exception as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="control_failed",
            ) from err
        self.async_write_ha_state()

    @override
    async def async_turn_on(self) -> None:
        """Turn on with the last selected heat or cool mode."""
        await self.async_set_hvac_mode(self._last_hvac_mode)

    @override
    async def async_turn_off(self) -> None:
        """Turn off the virtual thermostat and Tuya air conditioner."""
        await self.async_set_hvac_mode(HVACMode.OFF)
