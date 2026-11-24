"""Pure common-frame boresight geometry and Level-1 transition timing."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, hypot, isfinite
from numbers import Integral, Real

from .adcs_config import AgilePointingConfig
from .ids import ADCSBoresightFrameId, ADCSSlewAnchorId


_STRAIGHT_ANGLE_DEGREES = 180


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


def _normalized_nonnegative_real(name: str, value: object) -> int | float:
    normalized = _normalized_real(name, value)
    if normalized < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return normalized


def _checked_sum(name: str, *values: object) -> int | float:
    """Add finite values using ordinary built-in arithmetic."""
    total: int | float = 0
    for index, value in enumerate(values):
        addend = _normalized_real(f"{name} addend {index}", value)
        try:
            total = total + addend
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"{name} cannot be represented as finite"
            ) from error
        total = _normalized_real(name, total)
    return total


def _checked_difference(
    name: str,
    minuend: object,
    subtrahend: object,
) -> int | float:
    """Subtract finite values using ordinary built-in arithmetic."""
    left = _normalized_real(f"{name} minuend", minuend)
    right = _normalized_real(f"{name} subtrahend", subtrahend)
    try:
        difference = left - right
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    return _normalized_real(name, difference)


def _checked_product(name: str, *values: object) -> int | float:
    """Multiply finite values and reject nonzero representational underflow."""
    product: int | float = 1
    for index, value in enumerate(values):
        factor = _normalized_real(f"{name} factor {index}", value)
        prior_product = product
        try:
            product = product * factor
        except (
            AttributeError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError(
                f"{name} cannot be represented as finite"
            ) from error
        product = _normalized_real(name, product)
        if prior_product != 0 and factor != 0 and product == 0:
            raise ValueError(f"{name} cannot represent a nonzero product")
    return product


def _checked_bounded_product(
    name: str,
    left: object,
    right: object,
) -> int | float:
    """Multiply normalized-vector components and retain finite underflow."""
    left_value = _normalized_real(f"{name} left factor", left)
    right_value = _normalized_real(f"{name} right factor", right)
    try:
        product = left_value * right_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    return _normalized_real(name, product)


def _checked_quotient(
    name: str,
    numerator: object,
    denominator: object,
) -> int | float:
    """Divide finite values and reject nonzero representational underflow."""
    numerator_value = _normalized_real(f"{name} numerator", numerator)
    denominator_value = _normalized_real(f"{name} denominator", denominator)
    if denominator_value == 0:
        raise ValueError(f"{name} denominator must not be zero")
    try:
        quotient = numerator_value / denominator_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    normalized = _normalized_real(name, quotient)
    if numerator_value != 0 and normalized == 0:
        raise ValueError(f"{name} cannot represent a nonzero quotient")
    return normalized


@dataclass(frozen=True, slots=True)
class CommonFrameBoresightDirection:
    """One nonzero boresight direction in a caller-identified common frame."""

    frame_id: ADCSBoresightFrameId
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if type(self.frame_id) is not ADCSBoresightFrameId:
            raise TypeError("frame_id must be an ADCSBoresightFrameId")
        ADCSBoresightFrameId(self.frame_id.value)
        x = _normalized_real("x", self.x)
        y = _normalized_real("y", self.y)
        z = _normalized_real("z", self.z)
        if x == 0 and y == 0 and z == 0:
            raise ValueError("boresight direction vector must be nonzero")


@dataclass(frozen=True, slots=True)
class BoresightAngularSeparationResult:
    """Transient angular separation of two common-frame boresights."""

    angular_separation_deg: float

    def __post_init__(self) -> None:
        angle = _normalized_real(
            "angular_separation_deg",
            self.angular_separation_deg,
        )
        if angle < 0 or angle > _STRAIGHT_ANGLE_DEGREES:
            raise ValueError(
                "angular_separation_deg must be between zero and a straight "
                "angle"
            )


@dataclass(frozen=True, slots=True)
class BoresightTransitionResult:
    """Transient Level-1 slew interpolation and settling-time ledger."""

    angular_separation_deg: float
    lower_anchor_id: ADCSSlewAnchorId
    upper_anchor_id: ADCSSlewAnchorId
    interpolation_fraction: float
    slew_elapsed_time_seconds: float
    settling_time_seconds: float
    total_transition_time_seconds: float

    def __post_init__(self) -> None:
        angle = _normalized_real(
            "angular_separation_deg",
            self.angular_separation_deg,
        )
        if angle < 0 or angle > _STRAIGHT_ANGLE_DEGREES:
            raise ValueError(
                "angular_separation_deg must be between zero and a straight "
                "angle"
            )
        if type(self.lower_anchor_id) is not ADCSSlewAnchorId:
            raise TypeError("lower_anchor_id must be an ADCSSlewAnchorId")
        if type(self.upper_anchor_id) is not ADCSSlewAnchorId:
            raise TypeError("upper_anchor_id must be an ADCSSlewAnchorId")
        ADCSSlewAnchorId(self.lower_anchor_id.value)
        ADCSSlewAnchorId(self.upper_anchor_id.value)

        fraction = _normalized_nonnegative_real(
            "interpolation_fraction",
            self.interpolation_fraction,
        )
        if fraction > 1:
            raise ValueError(
                "interpolation_fraction must be less than or equal to one"
            )
        if self.lower_anchor_id == self.upper_anchor_id:
            if fraction != 0:
                raise ValueError(
                    "equal anchor IDs require zero interpolation_fraction"
                )
        elif fraction <= 0 or fraction >= 1:
            raise ValueError(
                "distinct anchor IDs require interpolation_fraction strictly "
                "between zero and one"
            )

        slew_time = _normalized_nonnegative_real(
            "slew_elapsed_time_seconds",
            self.slew_elapsed_time_seconds,
        )
        settling_time = _normalized_nonnegative_real(
            "settling_time_seconds",
            self.settling_time_seconds,
        )
        total_time = _normalized_nonnegative_real(
            "total_transition_time_seconds",
            self.total_transition_time_seconds,
        )
        expected_total = _checked_sum(
            "total_transition_time_seconds",
            slew_time,
            settling_time,
        )
        if total_time != expected_total:
            raise ValueError(
                "total_transition_time_seconds must equal slew elapsed time "
                "plus settling time"
            )
        if angle == 0 and (
            self.lower_anchor_id != self.upper_anchor_id
            or fraction != 0
            or slew_time != 0
            or settling_time != 0
            or total_time != 0
        ):
            raise ValueError(
                "zero angular separation requires one anchor and zero times"
            )


def _unit_components(
    direction: CommonFrameBoresightDirection,
) -> tuple[int | float, int | float, int | float]:
    """Return robustly normalized built-in components without mutation."""
    components = (
        _normalized_real("x", direction.x),
        _normalized_real("y", direction.y),
        _normalized_real("z", direction.z),
    )
    scale = max(abs(component) for component in components)
    if scale == 0:
        raise ValueError("boresight direction vector must be nonzero")
    try:
        scaled_components = tuple(component / scale for component in components)
        magnitude = hypot(*scaled_components)
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            "boresight direction cannot be normalized safely"
        ) from error
    magnitude = _normalized_real("boresight direction magnitude", magnitude)
    if magnitude <= 0:
        raise ValueError("boresight direction magnitude must be positive")
    return tuple(
        _checked_quotient(
            "normalized boresight component",
            component,
            magnitude,
        )
        for component in scaled_components
    )


def compute_boresight_angular_separation(
    start: CommonFrameBoresightDirection,
    end: CommonFrameBoresightDirection,
) -> BoresightAngularSeparationResult:
    """Compute pure angular separation for two directions in one frame."""
    if type(start) is not CommonFrameBoresightDirection:
        raise TypeError("start must be a CommonFrameBoresightDirection")
    if type(end) is not CommonFrameBoresightDirection:
        raise TypeError("end must be a CommonFrameBoresightDirection")
    CommonFrameBoresightDirection(start.frame_id, start.x, start.y, start.z)
    CommonFrameBoresightDirection(end.frame_id, end.x, end.y, end.z)
    if start.frame_id != end.frame_id:
        raise ValueError("start and end boresights must use the same frame_id")

    start_x, start_y, start_z = _unit_components(start)
    end_x, end_y, end_z = _unit_components(end)
    cross_x = _checked_difference(
        "boresight cross-product x",
        _checked_bounded_product(
            "boresight cross-product x",
            start_y,
            end_z,
        ),
        _checked_bounded_product(
            "boresight cross-product x",
            start_z,
            end_y,
        ),
    )
    cross_y = _checked_difference(
        "boresight cross-product y",
        _checked_bounded_product(
            "boresight cross-product y",
            start_z,
            end_x,
        ),
        _checked_bounded_product(
            "boresight cross-product y",
            start_x,
            end_z,
        ),
    )
    cross_z = _checked_difference(
        "boresight cross-product z",
        _checked_bounded_product(
            "boresight cross-product z",
            start_x,
            end_y,
        ),
        _checked_bounded_product(
            "boresight cross-product z",
            start_y,
            end_x,
        ),
    )
    try:
        cross_norm = hypot(cross_x, cross_y, cross_z)
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            "boresight cross-product norm cannot be represented as finite"
        ) from error
    cross_norm = _normalized_nonnegative_real(
        "boresight cross-product norm",
        cross_norm,
    )
    dot = _checked_sum(
        "boresight dot product",
        _checked_bounded_product(
            "boresight dot product",
            start_x,
            end_x,
        ),
        _checked_bounded_product(
            "boresight dot product",
            start_y,
            end_y,
        ),
        _checked_bounded_product(
            "boresight dot product",
            start_z,
            end_z,
        ),
    )
    try:
        angle = degrees(atan2(cross_norm, dot))
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            "angular separation cannot be represented as finite"
        ) from error
    angle = _normalized_real("angular_separation_deg", angle)
    return BoresightAngularSeparationResult(angle)


def compute_boresight_transition(
    config: AgilePointingConfig,
    start: CommonFrameBoresightDirection,
    end: CommonFrameBoresightDirection,
) -> BoresightTransitionResult:
    """Compute pure piecewise-linear C1 envelope and settling timing."""
    if type(config) is not AgilePointingConfig:
        raise TypeError("config must be an AgilePointingConfig")
    if type(start) is not CommonFrameBoresightDirection:
        raise TypeError("start must be a CommonFrameBoresightDirection")
    if type(end) is not CommonFrameBoresightDirection:
        raise TypeError("end must be a CommonFrameBoresightDirection")
    AgilePointingConfig(
        config.maximum_view_angle_from_nadir_deg,
        config.post_slew_settling_time_seconds,
        config.slew_time_anchors,
    )

    separation = compute_boresight_angular_separation(start, end)
    angle = _normalized_nonnegative_real(
        "angular_separation_deg",
        separation.angular_separation_deg,
    )
    anchors = config.slew_time_anchors
    first_anchor = anchors[0]
    if angle == 0:
        return BoresightTransitionResult(
            angle,
            first_anchor.anchor_id,
            first_anchor.anchor_id,
            0.0,
            0.0,
            0.0,
            0.0,
        )

    last_angle = _normalized_real(
        "last anchor angular separation",
        anchors[-1].angular_separation_deg.value,
    )
    if angle > last_angle:
        raise ValueError(
            "angular separation exceeds the configured slew-time envelope"
        )

    settling_time = _normalized_nonnegative_real(
        "settling_time_seconds",
        config.post_slew_settling_time_seconds.value,
    )
    for anchor in anchors[1:]:
        anchor_angle = _normalized_real(
            "slew-time anchor angular separation",
            anchor.angular_separation_deg.value,
        )
        if angle == anchor_angle:
            slew_time = _normalized_nonnegative_real(
                "slew_elapsed_time_seconds",
                anchor.slew_elapsed_time_seconds.value,
            )
            total_time = _checked_sum(
                "total_transition_time_seconds",
                slew_time,
                settling_time,
            )
            return BoresightTransitionResult(
                angle,
                anchor.anchor_id,
                anchor.anchor_id,
                0.0,
                slew_time,
                settling_time,
                total_time,
            )

    for lower_anchor, upper_anchor in zip(anchors, anchors[1:]):
        lower_angle = _normalized_real(
            "lower anchor angular separation",
            lower_anchor.angular_separation_deg.value,
        )
        upper_angle = _normalized_real(
            "upper anchor angular separation",
            upper_anchor.angular_separation_deg.value,
        )
        if not lower_angle < angle < upper_angle:
            continue
        interval_angle = _checked_difference(
            "anchor angular-separation interval",
            upper_angle,
            lower_angle,
        )
        angle_above_lower = _checked_difference(
            "angular separation above lower anchor",
            angle,
            lower_angle,
        )
        fraction = _checked_quotient(
            "interpolation_fraction",
            angle_above_lower,
            interval_angle,
        )
        lower_time = _normalized_nonnegative_real(
            "lower anchor elapsed time",
            lower_anchor.slew_elapsed_time_seconds.value,
        )
        upper_time = _normalized_nonnegative_real(
            "upper anchor elapsed time",
            upper_anchor.slew_elapsed_time_seconds.value,
        )
        time_interval = _checked_difference(
            "anchor elapsed-time interval",
            upper_time,
            lower_time,
        )
        interpolated_increment = _checked_product(
            "interpolated elapsed-time increment",
            fraction,
            time_interval,
        )
        slew_time = _checked_sum(
            "slew_elapsed_time_seconds",
            lower_time,
            interpolated_increment,
        )
        total_time = _checked_sum(
            "total_transition_time_seconds",
            slew_time,
            settling_time,
        )
        return BoresightTransitionResult(
            angle,
            lower_anchor.anchor_id,
            upper_anchor.anchor_id,
            fraction,
            slew_time,
            settling_time,
            total_time,
        )

    raise ValueError(
        "angular separation cannot be located in the slew-time envelope"
    )


__all__ = [
    "BoresightAngularSeparationResult",
    "BoresightTransitionResult",
    "CommonFrameBoresightDirection",
    "compute_boresight_angular_separation",
    "compute_boresight_transition",
]
