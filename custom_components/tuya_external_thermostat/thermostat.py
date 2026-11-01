"""Control rules shared by the Tuya external thermostat."""

from typing import Literal

type ThermostatMode = Literal["cool", "heat"]


def should_run(
    mode: ThermostatMode,
    current_temperature: float,
    target_temperature: float,
    activation_hysteresis: float,
    deactivation_hysteresis: float,
    was_running: bool,
) -> bool:
    """Return whether the air conditioner should use its active setpoint.

    The previous state is kept between the activation and deactivation limits.
    """
    if mode == "heat":
        if current_temperature <= target_temperature - activation_hysteresis:
            return True
        if current_temperature >= target_temperature + deactivation_hysteresis:
            return False
    else:
        if current_temperature >= target_temperature + activation_hysteresis:
            return True
        if current_temperature <= target_temperature - deactivation_hysteresis:
            return False

    return was_running
