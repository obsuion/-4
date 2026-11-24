"""Pure component-wise bus-load composition for V5 spacecraft physics."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real


def _validate_nonnegative_power(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite power in W")
    try:
        finite = isfinite(value)
    except (OverflowError, TypeError):
        finite = False
    if not finite:
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


def _aggregation_value(name: str, value: Real) -> int | float:
    """Return a built-in scalar that cannot inherit fixed-width wrapping."""
    try:
        index_method = getattr(value, "__index__", None)
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise ValueError(
            f"{name} cannot be represented for load aggregation"
        ) from error
    if callable(index_method):
        try:
            integer_value = index_method()
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"{name} cannot be represented for load aggregation"
            ) from error
        if type(integer_value) is not int:
            raise ValueError(
                f"{name} exact integer must be a Python int"
            )
        try:
            is_exact_integer = bool(value == integer_value)
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"{name} cannot validate its exact integer representation"
            ) from error
        if is_exact_integer:
            return integer_value

    try:
        aggregate_value = float(value)
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{name} cannot be represented for load aggregation"
        ) from error
    if not isfinite(aggregate_value):
        raise ValueError(
            f"{name} cannot be represented as finite for load aggregation"
        )
    return aggregate_value


@dataclass(frozen=True, slots=True)
class PowerLoadBreakdown:
    """Transient ledger of explicit bus-side electrical demand in W.

    Base-bus demand excludes every load attributed to the other six named
    components. Generation and battery conversion losses are not loads in
    this ledger.
    """

    base_bus_w: float
    obc_w: float
    adcs_w: float
    payload_w: float
    communications_w: float
    thermal_control_w: float
    propulsion_w: float

    def __post_init__(self) -> None:
        for field_name, value in (
            ("base_bus_w", self.base_bus_w),
            ("obc_w", self.obc_w),
            ("adcs_w", self.adcs_w),
            ("payload_w", self.payload_w),
            ("communications_w", self.communications_w),
            ("thermal_control_w", self.thermal_control_w),
            ("propulsion_w", self.propulsion_w),
        ):
            _validate_nonnegative_power(field_name, value)
        _ = self.total_load_w

    @property
    def total_load_w(self) -> int | float:
        """Return the non-wrapping sum of requested bus-side contributions."""
        components = (
            ("base_bus_w", self.base_bus_w),
            ("obc_w", self.obc_w),
            ("adcs_w", self.adcs_w),
            ("payload_w", self.payload_w),
            ("communications_w", self.communications_w),
            ("thermal_control_w", self.thermal_control_w),
            ("propulsion_w", self.propulsion_w),
        )
        aggregate_values = tuple(
            _aggregation_value(name, value) for name, value in components
        )
        try:
            total_load_w = sum(aggregate_values)
        except ArithmeticError as error:
            raise ValueError(
                "total_load_w cannot be represented as finite"
            ) from error
        if isinstance(total_load_w, float) and not isfinite(total_load_w):
            raise ValueError("total_load_w must be finite")
        if total_load_w < 0:
            raise ValueError(
                "total_load_w must be greater than or equal to zero"
            )
        return total_load_w


def compose_power_load(
    *,
    base_bus_w: float,
    obc_w: float,
    adcs_w: float,
    payload_w: float,
    communications_w: float,
    thermal_control_w: float,
    propulsion_w: float,
) -> PowerLoadBreakdown:
    """Compose one pure load ledger from explicit component demands."""
    return PowerLoadBreakdown(
        base_bus_w,
        obc_w,
        adcs_w,
        payload_w,
        communications_w,
        thermal_control_w,
        propulsion_w,
    )


__all__ = [
    "PowerLoadBreakdown",
    "compose_power_load",
]
