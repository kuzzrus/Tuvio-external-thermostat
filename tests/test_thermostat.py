"""Tests for the hysteresis control rules."""

import pytest

from custom_components.tuya_external_thermostat.thermostat import should_run


@pytest.mark.parametrize(
    ("current", "was_running", "expected"),
    [
        (19.4, False, True),
        (19.5, False, True),
        (20.0, False, False),
        (20.0, True, True),
        (20.5, True, False),
        (20.6, True, False),
    ],
)
def test_heat_hysteresis(current: float, *, was_running: bool, expected: bool) -> None:
    """Heat uses separate activation and deactivation limits."""
    assert should_run("heat", current, 20.0, 0.5, 0.5, was_running) is expected


@pytest.mark.parametrize(
    ("current", "was_running", "expected"),
    [
        (20.6, False, True),
        (20.5, False, True),
        (20.0, False, False),
        (20.0, True, True),
        (19.5, True, False),
        (19.4, True, False),
    ],
)
def test_cool_hysteresis(current: float, *, was_running: bool, expected: bool) -> None:
    """Cooling mirrors the heat control rules."""
    assert should_run("cool", current, 20.0, 0.5, 0.5, was_running) is expected


def test_split_hysteresis() -> None:
    """Activation and deactivation offsets are independent."""
    assert should_run("cool", 20.4, 20.0, 0.3, 0.8, False)
    assert should_run("cool", 19.5, 20.0, 0.3, 0.8, True)
    assert not should_run("cool", 19.2, 20.0, 0.3, 0.8, True)
