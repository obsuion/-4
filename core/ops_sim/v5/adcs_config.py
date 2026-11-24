"""Immutable Level-1 agile-ADCS maneuver configuration for V5."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real

from .ids import ADCSSlewAnchorId, ParameterId
from .parameters import ScalarParameter


_STRAIGHT_ANGLE_DEGREES = 180
_RIGHT_ANGLE_DEGREES = _STRAIGHT_ANGLE_DEGREES / 2


def _normalized_real(name: str, value: object) -> int | float:
    """Return an admitted finite Real as a safe built-in scalar."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real finite number")
    try:
        finite = bool(isfinite(value))
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} must be finite") from error
    if not finite:
        raise ValueError(f"{name} must be finite")

    try:
        normalized = int(value) if isinstance(value, Integral) else float(value)
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if type(normalized) not in {int, float}:
        raise ValueError(f"{name} must normalize to a built-in number")
    try:
        normalized_finite = bool(isfinite(normalized))
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(
            f"{name} cannot be represented as a finite number"
        ) from error
    if not normalized_finite:
        raise ValueError(f"{name} cannot be represented as a finite number")
    return normalized


def _validate_parameter(
    field_name: str,
    parameter: object,
    *,
    parameter_id: str,
    units: str,
) -> int | float:
    if type(parameter) is not ScalarParameter:
        raise TypeError(f"{field_name} must be a ScalarParameter")
    ScalarParameter(parameter.value, parameter.provenance)
    if (
        type(parameter.parameter_id) is not ParameterId
        or parameter.parameter_id.value != parameter_id
    ):
        raise ValueError(
            f"{field_name} must use ParameterId {parameter_id!r}"
        )
    if parameter.units != units:
        raise ValueError(f"{field_name} must use units {units!r}")
    return _normalized_real(field_name, parameter.value)


@dataclass(frozen=True, slots=True)
class BoresightSlewTimeAnchor:
    """One configuration-owned boresight-separation and elapsed-time anchor."""

    anchor_id: ADCSSlewAnchorId
    angular_separation_deg: ScalarParameter
    slew_elapsed_time_seconds: ScalarParameter

    def __post_init__(self) -> None:
        if type(self.anchor_id) is not ADCSSlewAnchorId:
            raise TypeError("anchor_id must be an ADCSSlewAnchorId")
        ADCSSlewAnchorId(self.anchor_id.value)
        parameter_prefix = f"adcs.slew-envelope.{self.anchor_id.value}"
        angle = _validate_parameter(
            "angular_separation_deg",
            self.angular_separation_deg,
            parameter_id=f"{parameter_prefix}.angular-separation",
            units="deg",
        )
        elapsed_time = _validate_parameter(
            "slew_elapsed_time_seconds",
            self.slew_elapsed_time_seconds,
            parameter_id=f"{parameter_prefix}.elapsed-time",
            units="s",
        )
        if angle < 0:
            raise ValueError(
                "angular_separation_deg must be greater than or equal to zero"
            )
        if angle > _STRAIGHT_ANGLE_DEGREES:
            raise ValueError(
                "angular_separation_deg must be less than or equal to a "
                "straight angle"
            )
        if elapsed_time < 0:
            raise ValueError(
                "slew_elapsed_time_seconds must be greater than or equal to zero"
            )
        if angle != 0 and elapsed_time == 0:
            raise ValueError(
                "a nonzero angular separation requires positive elapsed time"
            )


@dataclass(frozen=True, slots=True)
class AgilePointingConfig:
    """Own a Level-1 boresight viewing limit and slew-time anchor envelope."""

    maximum_view_angle_from_nadir_deg: ScalarParameter
    post_slew_settling_time_seconds: ScalarParameter
    slew_time_anchors: tuple[BoresightSlewTimeAnchor, ...]

    def __post_init__(self) -> None:
        maximum_view_angle = _validate_parameter(
            "maximum_view_angle_from_nadir_deg",
            self.maximum_view_angle_from_nadir_deg,
            parameter_id="adcs.pointing.maximum-view-angle-from-nadir",
            units="deg",
        )
        settling_time = _validate_parameter(
            "post_slew_settling_time_seconds",
            self.post_slew_settling_time_seconds,
            parameter_id="adcs.pointing.post-slew-settling-time",
            units="s",
        )
        if maximum_view_angle <= 0 or maximum_view_angle >= _RIGHT_ANGLE_DEGREES:
            raise ValueError(
                "maximum_view_angle_from_nadir_deg must be greater than zero "
                "and less than a right angle"
            )
        if settling_time < 0:
            raise ValueError(
                "post_slew_settling_time_seconds must be greater than or "
                "equal to zero"
            )
        if type(self.slew_time_anchors) is not tuple:
            raise TypeError("slew_time_anchors must be a tuple")
        if len(self.slew_time_anchors) < 2:
            raise ValueError("slew_time_anchors must contain at least two anchors")
        if not all(
            type(anchor) is BoresightSlewTimeAnchor
            for anchor in self.slew_time_anchors
        ):
            raise TypeError(
                "slew_time_anchors must contain only BoresightSlewTimeAnchor "
                "values"
            )

        for anchor in self.slew_time_anchors:
            BoresightSlewTimeAnchor(
                anchor.anchor_id,
                anchor.angular_separation_deg,
                anchor.slew_elapsed_time_seconds,
            )
        if len({anchor.anchor_id for anchor in self.slew_time_anchors}) != len(
            self.slew_time_anchors
        ):
            raise ValueError("slew_time_anchors must use unique anchor IDs")

        first_anchor = self.slew_time_anchors[0]
        first_angle = _normalized_real(
            "first anchor angular separation",
            first_anchor.angular_separation_deg.value,
        )
        first_time = _normalized_real(
            "first anchor elapsed time",
            first_anchor.slew_elapsed_time_seconds.value,
        )
        if first_angle != 0 or first_time != 0:
            raise ValueError("the first slew-time anchor must be exactly 0 deg / 0 s")

        previous_angle = first_angle
        previous_time = first_time
        for anchor in self.slew_time_anchors[1:]:
            angle = _normalized_real(
                "slew-time anchor angular separation",
                anchor.angular_separation_deg.value,
            )
            elapsed_time = _normalized_real(
                "slew-time anchor elapsed time",
                anchor.slew_elapsed_time_seconds.value,
            )
            if angle <= previous_angle:
                raise ValueError(
                    "slew-time anchor angular separations must be strictly "
                    "increasing"
                )
            if elapsed_time < previous_time:
                raise ValueError(
                    "slew-time anchor elapsed times must be nondecreasing"
                )
            previous_angle = angle
            previous_time = elapsed_time


__all__ = ["AgilePointingConfig", "BoresightSlewTimeAnchor"]
