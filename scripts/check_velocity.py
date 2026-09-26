#!/usr/bin/env python3
"""Simple validator for linear and angular velocity commands.

The script compares commanded and measured velocities and reports whether the
measured values stay within configured tolerances.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VelocityCheckResult:
    command_linear: float
    command_angular: float
    measured_linear: float
    measured_angular: float
    linear_error: float
    angular_error: float
    linear_tolerance: float
    angular_tolerance: float
    ok: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "command_linear": self.command_linear,
            "command_angular": self.command_angular,
            "measured_linear": self.measured_linear,
            "measured_angular": self.measured_angular,
            "linear_error": self.linear_error,
            "angular_error": self.angular_error,
            "linear_tolerance": self.linear_tolerance,
            "angular_tolerance": self.angular_tolerance,
            "ok": self.ok,
        }


def _validate_number(name: str, value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


def check_velocity(
    command_linear: float,
    command_angular: float,
    measured_linear: float,
    measured_angular: float,
    linear_tolerance: float = 0.02,
    angular_tolerance: float = 0.08,
) -> VelocityCheckResult:
    """Return whether measured motion matches the requested motion.

    The comparison is performed as absolute error: |measured - command|.
    """

    cmd_linear = _validate_number("command_linear", command_linear)
    cmd_angular = _validate_number("command_angular", command_angular)
    meas_linear = _validate_number("measured_linear", measured_linear)
    meas_angular = _validate_number("measured_angular", measured_angular)
    lin_tol = _validate_number("linear_tolerance", linear_tolerance)
    ang_tol = _validate_number("angular_tolerance", angular_tolerance)

    if lin_tol < 0.0 or ang_tol < 0.0:
        raise ValueError("tolerances must be non-negative")

    linear_error = abs(meas_linear - cmd_linear)
    angular_error = abs(meas_angular - cmd_angular)
    return VelocityCheckResult(
        command_linear=cmd_linear,
        command_angular=cmd_angular,
        measured_linear=meas_linear,
        measured_angular=meas_angular,
        linear_error=linear_error,
        angular_error=angular_error,
        linear_tolerance=lin_tol,
        angular_tolerance=ang_tol,
        ok=linear_error <= lin_tol and angular_error <= ang_tol,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check commanded vs measured linear/angular velocity.")
    parser.add_argument("--linear", type=float, default=0.0, help="commanded linear speed [m/s]")
    parser.add_argument("--angular", type=float, default=0.0, help="commanded angular speed [rad/s]")
    parser.add_argument("--measured-linear", type=float, default=0.0, help="measured linear speed [m/s]")
    parser.add_argument("--measured-angular", type=float, default=0.0, help="measured angular speed [rad/s]")
    parser.add_argument("--linear-tolerance", type=float, default=0.02, help="allowed absolute linear error [m/s]")
    parser.add_argument("--angular-tolerance", type=float, default=0.08, help="allowed absolute angular error [rad/s]")
    parser.add_argument("--json", action="store_true", help="print JSON summary instead of plain text")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        result = check_velocity(
            command_linear=args.linear,
            command_angular=args.angular,
            measured_linear=args.measured_linear,
            measured_angular=args.measured_angular,
            linear_tolerance=args.linear_tolerance,
            angular_tolerance=args.angular_tolerance,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 2

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False))
    else:
        status = "PASS" if result.ok else "FAIL"
        print(
            f"{status} linear_error={result.linear_error:.6f} angular_error={result.angular_error:.6f} "
            f"(tol linear={result.linear_tolerance:.6f}, angular={result.angular_tolerance:.6f})"
        )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
