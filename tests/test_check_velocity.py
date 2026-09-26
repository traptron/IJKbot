import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_velocity import check_velocity, VelocityCheckResult


def test_check_velocity_accepts_small_error():
    result = check_velocity(
        command_linear=0.10,
        command_angular=0.50,
        measured_linear=0.099,
        measured_angular=0.51,
        linear_tolerance=0.02,
        angular_tolerance=0.08,
    )
    assert isinstance(result, VelocityCheckResult)
    assert result.ok is True
    assert result.linear_error == pytest.approx(0.001)
    assert result.angular_error == pytest.approx(0.01)


def test_check_velocity_rejects_large_error():
    result = check_velocity(
        command_linear=0.10,
        command_angular=0.50,
        measured_linear=0.05,
        measured_angular=0.90,
        linear_tolerance=0.02,
        angular_tolerance=0.08,
    )
    assert result.ok is False
    assert result.linear_error == pytest.approx(0.05)
    assert result.angular_error == pytest.approx(0.40)


def test_check_velocity_handles_zero_case():
    result = check_velocity(0.0, 0.0, 0.0, 0.0)
    assert result.ok is True
    assert result.linear_error == pytest.approx(0.0)
    assert result.angular_error == pytest.approx(0.0)


def test_check_velocity_rejects_nan_or_inf():
    with pytest.raises(ValueError):
        check_velocity(0.1, math.nan, 0.1, 0.0)

    with pytest.raises(ValueError):
        check_velocity(0.1, 0.0, math.inf, 0.0)
