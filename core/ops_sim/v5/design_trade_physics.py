"""Small, explicit physical reductions for the bounded Task 05E study.

There are no catalog defaults here. Boxes are rigid, axis aligned, and measured
in one body frame. Slews are ideal one-axis bang/coast/bang, with no disturbance,
cross-axis dynamics, flexible appendages, or regenerative braking. Electrical
lines include both conductors and the explicitly counted series connectors.
These reductions are engineering assumptions, not flight qualification.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import fsum, isfinite, sqrt


def _real(value: object, name: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise TypeError(f"{name} must be a built-in int or float")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not isfinite(result) or (result <= 0 if positive else result < 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return result


def _finite(value: float, name: str) -> float:
    if not isfinite(value):
        raise ValueError(f"{name} is not representable as a finite float")
    return value


def _vector(value: object, name: str, *, nonnegative: bool) -> tuple[float, float, float]:
    if type(value) is not tuple or len(value) != 3:
        raise TypeError(f"{name} must be an exact three-element tuple")
    output = []
    for item in value:
        if type(item) not in (int, float):
            raise TypeError(f"{name} coordinates must be built-in numbers")
        try:
            number = float(item)
        except OverflowError as exc:
            raise ValueError(f"{name} coordinates must be finite") from exc
        if not isfinite(number) or (nonnegative and number < 0):
            raise ValueError(f"invalid {name} coordinate")
        output.append(number)
    return tuple(output)


@dataclass(frozen=True, slots=True)
class BoxMassComponent:
    """One component counted once; zero sizes allow point-mass reference cases."""

    name: str
    mass_kg: float
    size_m: tuple[float, float, float]
    center_m: tuple[float, float, float]

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("component name must be a nonempty built-in string")
        object.__setattr__(self, "mass_kg", _real(self.mass_kg, "mass_kg", positive=True))
        object.__setattr__(self, "size_m", _vector(self.size_m, "size_m", nonnegative=True))
        object.__setattr__(self, "center_m", _vector(self.center_m, "center_m", nonnegative=False))


@dataclass(frozen=True, slots=True)
class MassProperties:
    """Inertia is about the y axis through the assembled center of mass."""

    total_mass_kg: float
    center_m: tuple[float, float, float]
    inertia_y_kg_m2: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "total_mass_kg", _real(self.total_mass_kg, "total_mass_kg", positive=True))
        object.__setattr__(self, "center_m", _vector(self.center_m, "center_m", nonnegative=False))
        object.__setattr__(self, "inertia_y_kg_m2", _real(self.inertia_y_kg_m2, "inertia_y_kg_m2"))


def mass_properties_y(components: tuple[BoxMassComponent, ...]) -> MassProperties:
    """Sum m, m*r, and m*(dx²+dz²)/12 + m*(offset_x²+offset_z²)."""
    if type(components) is not tuple or not components:
        raise TypeError("components must be a nonempty exact tuple")
    admitted = []
    for component in components:
        if type(component) is not BoxMassComponent:
            raise TypeError("components require exact BoxMassComponent values")
        admitted.append(BoxMassComponent(component.name, component.mass_kg,
                                         component.size_m, component.center_m))
    if len({component.name for component in admitted}) != len(admitted):
        raise ValueError("component names must be unique to expose double counting")
    try:
        mass = _finite(fsum(c.mass_kg for c in admitted), "total mass")
        center = tuple(_finite(fsum(c.mass_kg * c.center_m[i] for c in admitted) / mass,
                               "center of mass") for i in range(3))
        inertia = fsum(c.mass_kg * ((c.size_m[0] ** 2 + c.size_m[2] ** 2) / 12
                                   + (c.center_m[0] - center[0]) ** 2
                                   + (c.center_m[2] - center[2]) ** 2) for c in admitted)
    except OverflowError as exc:
        raise ValueError("mass properties exceed the finite arithmetic domain") from exc
    return MassProperties(mass, center, _finite(inertia, "assembled inertia"))


@dataclass(frozen=True, slots=True)
class SlewProfile:
    """Ideal minimum-time rest-to-rest rotation with torque/rate/momentum caps.

    Angle is a nonnegative magnitude in radians. The caller owns its signed
    body-axis direction. Query time is elapsed physical seconds; the final rest
    state is held for any extra execution duration. Settling is a separate phase.
    """

    angle_rad: float
    inertia_kg_m2: float
    torque_nm: float
    max_rate_rad_s: float
    momentum_nms: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "angle_rad", _real(self.angle_rad, "angle_rad"))
        for name in ("inertia_kg_m2", "torque_nm", "max_rate_rad_s", "momentum_nms"):
            object.__setattr__(self, name, _real(getattr(self, name), name, positive=True))
        if not isfinite(self.alpha_rad_s2) or self.alpha_rad_s2 <= 0:
            raise ValueError("angular acceleration is outside the finite positive domain")
        if not isfinite(self.rate_cap_rad_s) or self.rate_cap_rad_s <= 0:
            raise ValueError("rate cap is outside the finite positive domain")
        if self.angle_rad:
            for name in ("acceleration_s", "duration_s", "peak_rate_rad_s", "mechanical_energy_j"):
                if not isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                    raise ValueError(f"{name} is outside the finite positive domain")

    @property
    def alpha_rad_s2(self) -> float:
        return self.torque_nm / self.inertia_kg_m2

    @property
    def rate_cap_rad_s(self) -> float:
        return min(self.max_rate_rad_s, self.momentum_nms / self.inertia_kg_m2)

    @property
    def triangular(self) -> bool:
        return self.angle_rad <= self.rate_cap_rad_s * (self.rate_cap_rad_s / self.alpha_rad_s2)

    @property
    def acceleration_s(self) -> float:
        if self.angle_rad == 0:
            return 0.0
        if self.triangular:
            return sqrt(self.angle_rad / self.alpha_rad_s2)
        return self.rate_cap_rad_s / self.alpha_rad_s2

    @property
    def peak_rate_rad_s(self) -> float:
        if self.triangular:
            return self.alpha_rad_s2 * self.acceleration_s
        return self.rate_cap_rad_s

    @property
    def coast_s(self) -> float:
        if self.triangular:
            return 0.0
        return self.angle_rad / self.rate_cap_rad_s - self.acceleration_s

    @property
    def duration_s(self) -> float:
        return 2 * self.acceleration_s + self.coast_s

    @property
    def mechanical_energy_j(self) -> float:
        """Positive drive work; braking is dissipative and earns no energy credit."""
        return 0.5 * self.inertia_kg_m2 * self.peak_rate_rad_s ** 2

    @property
    def braking_heat_j(self) -> float:
        return self.mechanical_energy_j

    @property
    def absolute_mechanical_work_j(self) -> float:
        return 2 * self.mechanical_energy_j

    def angle_at(self, elapsed_s: float) -> float:
        t = _real(elapsed_s, "elapsed_s")
        if t >= self.duration_s:
            return self.angle_rad
        if t < self.acceleration_s:
            return 0.5 * self.alpha_rad_s2 * t * t
        if t < self.acceleration_s + self.coast_s:
            return self.peak_rate_rad_s * (t - 0.5 * self.acceleration_s)
        remaining = self.duration_s - t
        return self.angle_rad - 0.5 * self.alpha_rad_s2 * remaining * remaining

    def angle_fraction(self, elapsed_s: float) -> float:
        angle = self.angle_at(elapsed_s)
        return angle / self.angle_rad if self.angle_rad else 1.0

    def omega_at(self, elapsed_s: float) -> float:
        t = _real(elapsed_s, "elapsed_s")
        if t >= self.duration_s:
            return 0.0
        if t < self.acceleration_s:
            return self.alpha_rad_s2 * t
        if t < self.acceleration_s + self.coast_s:
            return self.peak_rate_rad_s
        return self.alpha_rad_s2 * (self.duration_s - t)

    def acceleration_at(self, elapsed_s: float) -> float:
        t = _real(elapsed_s, "elapsed_s")
        if t >= self.duration_s:
            return 0.0
        if t < self.acceleration_s:
            return self.alpha_rad_s2
        if t < self.acceleration_s + self.coast_s:
            return 0.0
        return -self.alpha_rad_s2

    def torque_abs_at(self, elapsed_s: float) -> float:
        return abs(self.acceleration_at(elapsed_s)) * self.inertia_kg_m2

    def cumulative_drive_work_j(self, elapsed_s: float) -> float:
        t = _real(elapsed_s, "elapsed_s")
        omega = self.alpha_rad_s2 * min(t, self.acceleration_s)
        return 0.5 * self.inertia_kg_m2 * omega * omega

    def cumulative_brake_heat_j(self, elapsed_s: float) -> float:
        t = _real(elapsed_s, "elapsed_s")
        if t <= self.acceleration_s + self.coast_s:
            return 0.0
        return self.mechanical_energy_j - 0.5 * self.inertia_kg_m2 * self.omega_at(t) ** 2


@dataclass(frozen=True, slots=True)
class WireSpec:
    """External two-conductor route; connector_count counts all series contacts.

    Connector resistance and mass are per counted connector. Current and drop
    limits are declared installation assumptions, not an ampacity standard.
    Integrated catalog harnesses must not be included again in this route.
    """

    one_way_length_m: float
    cross_section_m2: float
    resistivity_ohm_m: float
    density_kg_m3: float
    connector_resistance_ohm: float
    connector_count: int
    connector_mass_kg: float
    current_limit_a: float
    max_drop_v: float

    def __post_init__(self) -> None:
        for name in ("one_way_length_m", "connector_resistance_ohm", "connector_mass_kg", "max_drop_v"):
            object.__setattr__(self, name, _real(getattr(self, name), name))
        for name in ("cross_section_m2", "resistivity_ohm_m", "density_kg_m3", "current_limit_a"):
            object.__setattr__(self, name, _real(getattr(self, name), name, positive=True))
        if type(self.connector_count) is not int or self.connector_count < 0:
            raise ValueError("connector_count must be a nonnegative built-in integer")
        for name in ("resistance_ohm", "conductor_mass_kg", "connector_total_mass_kg", "harness_mass_kg"):
            _finite(getattr(self, name), name)

    @property
    def loop_length_m(self) -> float:
        return 2 * self.one_way_length_m

    @property
    def resistance_ohm(self) -> float:
        return (self.resistivity_ohm_m * self.loop_length_m / self.cross_section_m2
                + self.connector_count * self.connector_resistance_ohm)

    @property
    def conductor_mass_kg(self) -> float:
        return self.density_kg_m3 * self.loop_length_m * self.cross_section_m2

    @property
    def connector_total_mass_kg(self) -> float:
        return self.connector_count * self.connector_mass_kg

    @property
    def harness_mass_kg(self) -> float:
        return self.conductor_mass_kg + self.connector_total_mass_kg


class ElectricalLimitError(ValueError):
    """A requested operating point is inadmissible, rather than power-clamped."""


@dataclass(frozen=True, slots=True)
class ElectricalLineResult:
    current_a: float
    voltage_drop_v: float
    loss_w: float
    source_power_w: float
    delivered_power_w: float
    load_voltage_v: float
    resistance_ohm: float
    harness_mass_kg: float

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _real(getattr(self, name), name))


def _wire(spec: WireSpec) -> WireSpec:
    if type(spec) is not WireSpec:
        raise TypeError("spec must be an exact WireSpec")
    return replace(spec)


def _line_result(spec: WireSpec, voltage: float, current: float,
                 source: float, delivered: float) -> ElectricalLineResult:
    drop = _finite(current * spec.resistance_ohm, "voltage drop")
    loss = _finite(current * drop, "wire loss")
    if current > spec.current_limit_a:
        raise ElectricalLimitError("wire current limit exceeded")
    if drop > spec.max_drop_v:
        raise ElectricalLimitError("wire voltage-drop limit exceeded")
    if drop >= voltage:
        raise ElectricalLimitError("receiving voltage is nonpositive")
    return ElectricalLineResult(current, drop, loss, source, delivered,
                                voltage - drop, spec.resistance_ohm, spec.harness_mass_kg)


def constant_power_load(spec: WireSpec, source_voltage_v: float,
                        load_power_w: float) -> ElectricalLineResult:
    """Stable low-current root of P_load = I*(V_source-I*R).

    The rationalized root 2P/(V+sqrt(V²-4RP)) avoids subtraction cancellation.
    The saddle-node boundary and collapsed branch reject. No efficiency or
    battery loss belongs here; existing EPS conversion losses remain separate.
    """
    spec = _wire(spec)
    voltage = _real(source_voltage_v, "source_voltage_v", positive=True)
    power = _real(load_power_w, "load_power_w")
    if power == 0 or spec.resistance_ohm == 0:
        current = power / voltage
    else:
        discriminant = _finite(voltage * voltage - 4 * spec.resistance_ohm * power,
                               "circuit discriminant")
        if discriminant <= 0:
            raise ElectricalLimitError("constant-power circuit has no stable low-current root")
        current = _finite(2 * power / (voltage + sqrt(discriminant)), "line current")
    loss = _finite(current * current * spec.resistance_ohm, "wire loss")
    return _line_result(spec, voltage, current, _finite(power + loss, "source power"), power)


def generated_power_line(spec: WireSpec, source_voltage_v: float,
                         generated_power_w: float) -> ElectricalLineResult:
    """Fixed source-side voltage/current approximation: I=P_source/V_source.

    Delivered power is P_source-I²R. This is neither MPPT characterization nor
    a claim of catalog array/regulator compatibility.
    """
    spec = _wire(spec)
    voltage = _real(source_voltage_v, "source_voltage_v", positive=True)
    power = _real(generated_power_w, "generated_power_w")
    current = _finite(power / voltage, "line current")
    loss = _finite(current * current * spec.resistance_ohm, "wire loss")
    return _line_result(spec, voltage, current, power, power - loss)


def select_wire_size(template: WireSpec, cross_sections_m2: tuple[float, ...],
                     source_voltage_v: float, peak_power_w: float, *,
                     generated: bool = False) -> WireSpec:
    """Select the smallest admitted section from one common declared gauge set."""
    template = _wire(template)
    if type(generated) is not bool:
        raise TypeError("generated must be a built-in bool")
    if type(cross_sections_m2) is not tuple or not cross_sections_m2:
        raise TypeError("cross_sections_m2 must be a nonempty exact tuple")
    gauges = tuple(_real(x, "cross section", positive=True) for x in cross_sections_m2)
    if len(set(gauges)) != len(gauges):
        raise ValueError("gauge set must contain unique cross sections")
    voltage = _real(source_voltage_v, "source_voltage_v", positive=True)
    power = _real(peak_power_w, "peak_power_w")
    evaluate = generated_power_line if generated else constant_power_load
    for area in sorted(gauges):
        candidate = replace(template, cross_section_m2=area)
        try:
            evaluate(candidate, voltage, power)
        except ElectricalLimitError:
            continue
        return candidate
    raise ElectricalLimitError("no declared wire gauge admits the operating point")
