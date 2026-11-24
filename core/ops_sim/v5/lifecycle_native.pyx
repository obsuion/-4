# cython: language_level=3, infer_types=False, annotation_typing=False
# cython: binding=True, cdivision=False, overflowcheck=True
"""B63 compiled Python-object coupled physical owner.

Function bodies below are copied from the explicitly hashed B62 owners, with
local helper names, an explicit prepared environment adapter and a separately
versioned monotone operational entry monitor. The monitor is not model work.
There are no C float/int substitutions, C libm calls or arithmetic reassociation:
math.fsum/math libm and arbitrary Python int/Fraction operations remain exact
runtime calls. Original record/exception constructors retain module identity.
This module does not change caps, trial schedules, fees or state commit order.
Compilation is not proof of speedup; receipts/equality gates remain mandatory.
"""
from dataclasses import fields, replace
from fractions import Fraction
from fractions import Fraction as Q
from math import fsum, isfinite, exp, nextafter, sqrt
from numbers import Integral, Real
import sys
import os
from .lifecycle_fast import admit_policy
from .construction_coupling import ConstructionCompilation
from .construction_physics import BranchOperatingResult, ConstructionPhysicalResult
from .construction_service import (ConstructionServicePolicy, ConstructionServiceWork,
    ConstructionServiceDomainRefusal, ConstructionServiceElectricalRefusal,
    _FIELDS, _ESSENTIAL, _PRIORITY, _MODES, _MAX_TRIALS, _loads, _nonnegative, _service_interval)
from .design_trade_physics import ElectricalLimitError, ElectricalLineResult, WireSpec
from .solar import SolarGenerationResult, compute_solar_generation
from .eps_capability import compute_eps_capability, compute_battery_capacity_reconciliation
from .integration_time import RationalSeconds, DyadicDuration, checked_duration, validate_substep_seconds
from .power_loads import PowerLoadBreakdown
from .thermal_routing import (ElectricalLoadComponent, ServedComponentPower,
    ServedPowerLedger, compose_routed_internal_heat_sources, compute_routed_internal_heat)
from .thermal_coupling import ThermalNodeHeatLedger, EPSThermalSubstepResult
from .thermal import (ThermalAppliedHeatInputs, ThermalNodeAppliedHeatInput,
    ThermalIntervalInputs, ThermalLinkHeatFlow, ThermalNodeTransition,
    ThermalIntervalResult, ThermalSubstepResult)
from .thermal_config import ThermalNetworkConfig
from .ids import ThermalLinkId, ThermalNodeId
from .degradation import (BatteryThroughputIncrement, BatteryDegradationSubstepInput,
    BatteryDegradationIntervalInput, BatteryDegradationTransition,
    BatteryDegradationSubstepTransition, SolarDegradationForcingInput, SolarDegradationTransition)
from .configuration import BatteryConfig
from .degradation_config import BatteryAgeingModelConfig
from .state import (BatteryState, ThermalState, ThermalNodeState,
    BatteryDegradationState, SolarDegradationState)
from .battery_port import (BatteryPortPolicy, BatteryPortState, BatteryPortWork,
    BatteryPortTransition, BatteryPortSolution, BatteryPortDomainError, BatteryPortInvariantError)
from .battery_port_construction import (PortEPSResult, PortConstructionEPSResult,
    PortCoupledResult, PortConstructionPhysicalResult, PortServiceDiagnostic,
    PortServiceFailureDiagnostic)
from .lifecycle_quiet import (QuietIntegrationPolicy, BatteryQuietIntegrationPolicy,
    EnvironmentQuietIntegrationPolicy, QuietControllerState, QuietWork,
    QuietTrial, QuietSample, QuietIntegrationResult, QuietTrialRefusal)

_STEFAN_BOLTZMANN_W_PER_M2_K4 = 5.670374419e-8
_SECONDS_PER_HOUR = 3600.0
_MOLAR_GAS_CONSTANT_J_PER_MOL_K = 8.31446261815324
NATIVE_METHOD = 'B63_PREPARED_NATIVE_V1'


cdef object _native_entry_method = 'B63_COMPILED_NUMERICAL_ENTRY_MONITOR_V1'
cdef object _native_entry_limit = 2**56
cdef object _native_entry_names = (
    'constant_power_load', 'generated_power_line', 'solve_port', 'ocv_resistance',
    'battery_port_transition', '_transition', 'advance_port_state',
    'compute_thermal_substep_transition', '_thermal_compute_thermal_interval_transition',
    'compute_battery_degradation_substep', '_damage_compute_battery_degradation',
    'compute_explicit_solar_degradation_transition', 'evaluate_port_eps',
    'service_port_substep', 'complete_port_cut', 'quiet_error_norm', 'integrate_quiet_hold',
)
cdef object _native_entry_counters = {name: 0 for name in _native_entry_names}
cdef object _native_entry_total = 0
cdef object _native_entry_exhausted = False


cdef void _native_enter(object name) except *:
    """GIL-held, private PyLong counters; no public reset/mutation entry.

    Every accepted owner entry is charged before its own guards and survives
    owner exceptions. A saturated monitor refuses BEFORE further owner work,
    retains the saturated counts/flag and never rolls them back or wraps them.
    These operational counters neither replace nor refund scientific fees.
    """
    global _native_entry_total, _native_entry_exhausted
    cdef object previous
    cdef object next_count
    cdef object next_total
    if type(name) is not str or name not in _native_entry_counters:
        raise RuntimeError('B63_NATIVE_ENTRY_UNKNOWN_OWNER')
    previous = _native_entry_counters[name]
    if previous >= _native_entry_limit or _native_entry_total >= _native_entry_limit:
        _native_entry_exhausted = True
        raise RuntimeError('B63_NATIVE_ENTRY_COUNTER_LIMIT')
    # Allocate both Python integers before publishing either update. All
    # names/values are private builtins, under the extension's required GIL.
    next_count = previous + 1
    next_total = _native_entry_total + 1
    _native_entry_counters[name] = next_count
    _native_entry_total = next_total


def native_entry_counts():
    """Detached read-only operational DATA; actual build binding is external.

    It contains no state/checkpoint/cache and cannot reset or grant execution.
    The source SHA and extension SHA in the build receipt bind this declared
    monitor schema and the runtime/module ABI fields, not a filesystem path.
    """
    counts = dict(_native_entry_counters)
    if (set(counts) != set(_native_entry_names) or
            any(type(value) is not int or not 0 <= value <= _native_entry_limit for value in counts.values()) or
            type(_native_entry_total) is not int or not 0 <= _native_entry_total <= _native_entry_limit or
            sum(counts.values()) != _native_entry_total or type(_native_entry_exhausted) is not bool):
        raise RuntimeError('B63_NATIVE_ENTRY_MONITOR_INTEGRITY')
    return dict(format='B63_MONOTONE_NATIVE_ENTRY_COUNTS_V1', method=_native_entry_method,
        limit=_native_entry_limit, total=_native_entry_total, counts=counts,
        exhausted=_native_entry_exhausted, gil_held=True, reset_available=False,
        python_implementation=sys.implementation.name,
        python_cache_tag=sys.implementation.cache_tag, python_version=sys.version,
        platform=sys.platform, module_basename=os.path.basename(__file__),
        source_binding='ACTUAL_EXTENSION_AND_SOURCE_BUILD_RECEIPT_REQUIRED',
        scope='OPERATIONAL_ENTRY_ATTEMPTS_NOT_SCIENTIFIC_WORK_OR_DYNAMIC_STATE')


REFERENCE_SOURCE_SHA256 = (
    ('battery_port_construction.py', '737e566063c7478bf68bbc684ec980ed5cf724d24a87495f8002b8612103b079'),
    ('battery_port.py', 'a25069e593090627d862e71a1e8d9421861dcdf0ba417f5288197d967e5224d6'),
    ('design_trade_physics.py', '646f028e773adb67ab954e392119bff92c6e4e1444f0173ae6f7f5f94fd07eaa'),
    ('thermal.py', '556637cdf8911c6534748bf6c90190dd384083e7867d42d654496b15e58cfb72'),
    ('degradation.py', '66a1171721e538f8e7e18e878bbd4b559d3a610e81d2908d4b0f1107767a6027'),
    ('lifecycle_quiet.py', '86362f4984b55eb81bd2c65264f4ee2d9e17123c61846c59f286dd8c533da1fa'),
)

def _wire_real(value: object, name: str, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise TypeError(f"{name} must be a built-in int or float")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not isfinite(result) or (result <= 0 if positive else result < 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return result


def _wire_finite(value: float, name: str) -> float:
    if not isfinite(value):
        raise ValueError(f"{name} is not representable as a finite float")
    return value


def _wire_wire(spec: WireSpec) -> WireSpec:
    if type(spec) is not WireSpec:
        raise TypeError("spec must be an exact WireSpec")
    return replace(spec)


def _wire_line_result(spec: WireSpec, voltage: float, current: float,
                 source: float, delivered: float) -> ElectricalLineResult:
    drop = _wire_finite(current * spec.resistance_ohm, "voltage drop")
    loss = _wire_finite(current * drop, "wire loss")
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
    _native_enter('constant_power_load')
    spec = _wire_wire(spec)
    voltage = _wire_real(source_voltage_v, "source_voltage_v", positive=True)
    power = _wire_real(load_power_w, "load_power_w")
    if power == 0 or spec.resistance_ohm == 0:
        current = power / voltage
    else:
        discriminant = _wire_finite(voltage * voltage - 4 * spec.resistance_ohm * power,
                               "circuit discriminant")
        if discriminant <= 0:
            raise ElectricalLimitError("constant-power circuit has no stable low-current root")
        current = _wire_finite(2 * power / (voltage + sqrt(discriminant)), "line current")
    loss = _wire_finite(current * current * spec.resistance_ohm, "wire loss")
    return _wire_line_result(spec, voltage, current, _wire_finite(power + loss, "source power"), power)


def generated_power_line(spec: WireSpec, source_voltage_v: float,
                         generated_power_w: float) -> ElectricalLineResult:
    """Fixed source-side voltage/current approximation: I=P_source/V_source.

    Delivered power is P_source-I²R. This is neither MPPT characterization nor
    a claim of catalog array/regulator compatibility.
    """
    _native_enter('generated_power_line')
    spec = _wire_wire(spec)
    voltage = _wire_real(source_voltage_v, "source_voltage_v", positive=True)
    power = _wire_real(generated_power_w, "generated_power_w")
    current = _wire_finite(power / voltage, "line current")
    loss = _wire_finite(current * current * spec.resistance_ohm, "wire loss")
    return _wire_line_result(spec, voltage, current, power, power - loss)


def real(value, name, lo=0., hi=1.e12):
    try: valid = type(value) in (int, float) and isfinite(value) and lo <= value <= hi
    except OverflowError: valid = False
    if not valid:
        raise BatteryPortDomainError('BATTERY_PORT_DOMAIN:'+name)
    return float(value)


def solve_port(voc, resistance, terminal_power, *, charging, current_limit, voltage_min, voltage_max):
    """Stable binary64 algebra; D<0 is unavailable, never rounded/clamped to 0.

    D==0 is admitted only if the exact returned current/voltage pass guards;
    it is marked boundary so the quiet integrator uses detailed fallback.
    """
    _native_enter('solve_port')
    voc=real(voc,'Voc',1.e-12,1.e6);r=real(resistance,'R');p=real(terminal_power,'Pterminal')
    real(current_limit,'I limit',1.e-12);real(voltage_min,'V min',1.e-12);real(voltage_max,'V max',voltage_min)
    if type(charging) is not bool: raise TypeError('exact charge/discharge selector')
    d=voc*voc+(4*r*p if charging else -4*r*p)
    if not isfinite(d): raise BatteryPortDomainError('BATTERY_PORT_DISCRIMINANT_OVERFLOW')
    if d < 0: return BatteryPortSolution(False,'NEGATIVE_DISCRIMINANT',0.,voc,0.,d,True)
    current=p/voc if r==0 else 2*p/(voc+sqrt(d))
    vt=voc+(current*r if charging else -current*r)
    if not isfinite(current) or not isfinite(vt): raise BatteryPortDomainError('BATTERY_PORT_SOLUTION_OVERFLOW')
    reason=('CURRENT_LIMIT' if current>current_limit else 'VOLTAGE_WINDOW' if not voltage_min<=vt<=voltage_max else 'AVAILABLE')
    return BatteryPortSolution(reason=='AVAILABLE',reason,-current if charging else current,vt,p,d,d==0)


def ocv_resistance(policy, state, energy_wh, usable_wh, temperature_k):
    _native_enter('ocv_resistance')
    if type(policy) is not BatteryPortPolicy or type(state) is not BatteryPortState:
        raise TypeError('exact battery port policy/state')
    admit_policy(policy); state.__post_init__()
    cap=real(usable_wh,'usable Wh',1.e-12);e=real(energy_wh,'stored Wh',0,cap)
    t=real(temperature_k,'temperature K',policy.minimum_temperature_k,policy.maximum_temperature_k)
    if state.resistance_damage>policy.maximum_resistance_damage:raise BatteryPortDomainError('BATTERY_PORT_DAMAGE_DOMAIN')
    s=e/cap
    for (a,va),(b,vb) in zip(policy.ocv_curve,policy.ocv_curve[1:]):
        if s<=b:
            voc=va+(vb-va)*((s-a)/(b-a));break
    voc+=policy.ocv_temperature_v_per_k*(t-policy.reference_temperature_k)
    exponent=policy.resistance_temperature_per_k*(policy.reference_temperature_k-t)
    if abs(exponent)>32:raise BatteryPortDomainError('BATTERY_PORT_EXPONENT_DOMAIN')
    resistance=policy.resistance_reference_ohm*(1+state.resistance_damage)*(1+policy.resistance_low_soc_factor*(1-s)**2)*exp(exponent)
    return real(voc,'derived Voc',1.e-12,100),real(resistance,'derived R',0,100),s


def battery_port_transition(policy, state, *, energy_wh, usable_wh, temperature_k,
                            generation_w, load_w, duration, charge_bus_limit_w,
                            discharge_bus_limit_w, work):
    """Prospective V/I/chemical-energy limits, plus existing bus-power limits.

    Up to eight nextafter reductions are directed feasibility corrections to
    the proposed power BEFORE publication. No negative discriminant is hidden.
    ``conversion_loss_wh`` is the compatibility TOTAL irreversible loss; the
    separate Ohmic/converter fields are authoritative and are routed once.
    This is deliberately not BatterySubstepTransition or a fixed-eta result.
    """
    _native_enter('battery_port_transition')
    if type(work)is not BatteryPortWork:raise TypeError('exact nonrefundable port work')
    work.reserve()
    try:
        result=_transition(policy,state,energy_wh,usable_wh,temperature_k,generation_w,load_w,
                           duration,charge_bus_limit_w,discharge_bus_limit_w)
    except BatteryPortDomainError:
        work.refused+=1;raise
    except BaseException:
        work.unknown+=1;raise
    work.returned+=1;return result


def _transition(policy,state,e,cap,t,gen,load,duration,charge_limit,discharge_limit):
    _native_enter('_transition')
    from .integration_time import checked_duration
    dt=checked_duration(duration);gen=real(gen,'generation W');load=real(load,'load W')
    charge_limit=real(charge_limit,'legacy charge bus W');discharge_limit=real(discharge_limit,'legacy discharge bus W')
    voc,r,s=ocv_resistance(policy,state,e,cap,t)
    charging=gen>=load;needed=abs(gen-load);eta=policy.converter_charge_efficiency if charging else policy.converter_discharge_efficiency
    ilim=policy.maximum_charge_current_a if charging else policy.maximum_discharge_current_a
    chemical_limit=((cap-e)if charging else e)*3600/dt
    imax=min(ilim,chemical_limit/voc)
    in_window=policy.minimum_terminal_voltage_v<=voc<=policy.maximum_terminal_voltage_v
    if not in_window:imax=0.
    if r:
        imax=min(imax,(policy.maximum_terminal_voltage_v-voc)/r if charging else
                 min(voc/(2*r),(voc-policy.minimum_terminal_voltage_v)/r)) if in_window else 0.
    terminal_cap=imax*(voc+(imax*r if charging else -imax*r))
    bus_cap=terminal_cap/eta if charging else terminal_cap*eta
    cap_w=min(charge_limit,policy.maximum_charge_bus_w)if charging else min(discharge_limit,policy.maximum_discharge_bus_w)
    proposed=min(needed,cap_w,bus_cap)
    reason='AVAILABLE'if proposed==needed else 'CURRENT_VOLTAGE_OR_ENERGY_LIMIT'
    # At no flow the converter may be disconnected outside its input window;
    # PV still feeds a separate ideal regulated bus, and passive heat continues.
    for attempt in range(9):
        pterminal=proposed*eta if charging else proposed/eta
        solution=solve_port(voc,r,pterminal,charging=charging,current_limit=ilim,
            voltage_min=policy.minimum_terminal_voltage_v if proposed else min(voc,policy.minimum_terminal_voltage_v),
            voltage_max=policy.maximum_terminal_voltage_v if proposed else max(voc,policy.maximum_terminal_voltage_v))
        current=abs(solution.current_a);chemical=voc*current;delta=chemical*dt/3600
        end=e+delta if charging else e-delta
        if solution.available and 0<=end<=cap:break
        if attempt==8:raise BatteryPortDomainError('BATTERY_PORT_FEASIBILITY_ROUNDING_UNAVAILABLE')
        proposed=nextafter(proposed,0.);reason='DIRECTED_FEASIBILITY_ROUNDING'
    heat=current*current*r
    conv=(proposed-pterminal)if charging else(pterminal-proposed)
    ohm_wh=heat*dt/3600;conv_wh=conv*dt/3600
    # Publish the nonnegative residual directly. (gen + (load-gen)) can
    # round one ULP above load; subtracting that sum fabricates negative unmet.
    # proposed <= needed is prospective admission, not a post-hoc energy clamp.
    unmet=0. if charging else needed-proposed
    served=load-unmet
    near=(solution.boundary or proposed<needed or (proposed>0 and
          min(solution.terminal_voltage_v-policy.minimum_terminal_voltage_v,
              policy.maximum_terminal_voltage_v-solution.terminal_voltage_v)<.2) or ilim-current<.05)
    result=BatteryPortTransition(duration,dt,float(e),end,gen,load,served,unmet,
        proposed if charging else 0.,0. if charging else proposed,needed-proposed if charging else 0.,
        ohm_wh+conv_wh,ohm_wh,conv_wh,delta,chemical if charging else 0.,0. if charging else chemical,
        voc,r,solution.current_a,solution.terminal_voltage_v,solution.discriminant_v2,reason,near)
    return result


def advance_port_state(policy, state, transition, *, start, end, representative_temperature_k, work):
    """History of ONE private coupled cut. Caller publishes only selected cuts."""
    _native_enter('advance_port_state')
    if type(state)is not BatteryPortState or type(transition)is not BatteryPortTransition or type(work)is not BatteryPortWork:
        raise TypeError('exact port history families')
    state.__post_init__();transition.__post_init__()
    duration=transition.duration
    exact_duration=(duration.fraction if hasattr(duration,'fraction') else
                    Q(duration.numerator_seconds,1<<duration.subdivision_level))
    if type(start)is not Q or type(end)is not Q or state.clock_seconds!=start or end-start!=exact_duration:
        raise BatteryPortDomainError('BATTERY_PORT_HISTORY_SUPPORT')
    work.reserve(ageing=True)
    try:
        t=real(representative_temperature_k,'ageing K',policy.minimum_temperature_k,policy.maximum_temperature_k)
        exponent=policy.ageing_temperature_per_k*(t-policy.reference_temperature_k)
        if abs(exponent)>32:raise BatteryPortDomainError('BATTERY_PORT_AGEING_EXPONENT_DOMAIN')
        acceleration=exp(exponent);dt=transition.dt_seconds
        damage=state.resistance_damage+acceleration*(policy.calendar_damage_per_second*dt+
                  policy.cycling_damage_per_chemical_wh*transition.chemical_throughput_wh)
        if not isfinite(damage)or damage>policy.maximum_resistance_damage:
            raise BatteryPortDomainError('BATTERY_PORT_ACCUMULATED_DAMAGE_DOMAIN')
        result=replace(state,clock_seconds=end,resistance_damage=damage,
            temperature_weighted_seconds=state.temperature_weighted_seconds+acceleration*dt,
            chemical_throughput_wh=state.chemical_throughput_wh+transition.chemical_throughput_wh,
            ohmic_heat_wh=state.ohmic_heat_wh+transition.ohmic_heat_wh,
            converter_loss_wh=state.converter_loss_wh+transition.converter_loss_wh,
            selected_steps=state.selected_steps+1,last_voltage_v=transition.terminal_voltage_v,
            last_current_a=transition.current_a,last_resistance_ohm=transition.resistance_ohm,
            last_ocv_v=transition.ocv_v,last_support_start_seconds=start)
    except BatteryPortDomainError:
        work.ageing_refused+=1;raise
    except BaseException:
        work.ageing_unknown+=1;raise
    work.ageing_returned+=1;return result


def _thermal_normalized_real(name: str, value: object) -> int | float:
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


def _thermal_validate_positive_real(name: str, value: object) -> None:
    normalized = _thermal_normalized_real(name, value)
    if normalized <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _thermal_validate_finite_real(name: str, value: object) -> None:
    _thermal_normalized_real(name, value)


def _thermal_checked_sum(name: str, left: object, right: object) -> int | float:
    left_value = _thermal_normalized_real(f"{name} left operand", left)
    right_value = _thermal_normalized_real(f"{name} right operand", right)
    try:
        value = left_value + right_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    return _thermal_normalized_real(name, value)


def _thermal_checked_difference(
    name: str,
    minuend: object,
    subtrahend: object,
) -> int | float:
    minuend_value = _thermal_normalized_real(f"{name} minuend", minuend)
    subtrahend_value = _thermal_normalized_real(f"{name} subtrahend", subtrahend)
    try:
        value = minuend_value - subtrahend_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    return _thermal_normalized_real(name, value)


def _thermal_checked_product(name: str, *values: object) -> int | float:
    product: int | float = 1
    for index, value in enumerate(values):
        factor = _thermal_normalized_real(f"{name} factor {index}", value)
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
        product = _thermal_normalized_real(name, product)
        if prior_product != 0 and factor != 0 and product == 0:
            raise ValueError(f"{name} cannot represent a nonzero product")
    return product


def _thermal_checked_quotient(
    name: str,
    numerator: object,
    denominator: object,
) -> int | float:
    numerator_value = _thermal_normalized_real(f"{name} numerator", numerator)
    denominator_value = _thermal_normalized_real(f"{name} denominator", denominator)
    if denominator_value == 0:
        raise ValueError(f"{name} denominator must not be zero")
    try:
        value = numerator_value / denominator_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    normalized = _thermal_normalized_real(name, value)
    if numerator_value != 0 and normalized == 0:
        raise ValueError(f"{name} cannot represent a nonzero quotient")
    return normalized


def _thermal_checked_fourth_power(name: str, value: object) -> int | float:
    base = _thermal_normalized_real(name, value)
    try:
        fourth_power = base**4
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(
            f"{name} fourth power cannot be represented as finite"
        ) from error
    normalized = _thermal_normalized_real(f"{name} fourth power", fourth_power)
    if base != 0 and normalized == 0:
        raise ValueError(
            f"{name} fourth power cannot represent a positive value"
        )
    return normalized


def compute_thermal_substep_transition(state, config, inputs, applied_heat_inputs=None, *, duration):
    """Same simultaneous Euler equations over an explicit internal duration."""
    _native_enter('compute_thermal_substep_transition')
    if applied_heat_inputs is not None and type(applied_heat_inputs) is not ThermalAppliedHeatInputs:
        raise TypeError("applied_heat_inputs must be ThermalAppliedHeatInputs or None")
    return _thermal_compute_thermal_interval_transition(state, config, inputs, applied_heat_inputs,
        dt_seconds=checked_duration(duration), _duration=duration)


def _thermal_compute_thermal_interval_transition(
    state: ThermalState,
    config: ThermalNetworkConfig,
    inputs: ThermalIntervalInputs,
    applied_heat_inputs: ThermalAppliedHeatInputs | None,
    *,
    dt_seconds: int | float,
    _duration: DyadicDuration | None = None,
) -> ThermalIntervalResult:
    """Evaluate the shared simultaneous conduction/radiation/Euler core."""
    _native_enter('_thermal_compute_thermal_interval_transition')
    if type(state) is not ThermalState:
        raise TypeError("state must be a ThermalState")
    if type(config) is not ThermalNetworkConfig:
        raise TypeError("config must be a ThermalNetworkConfig")
    if type(inputs) is not ThermalIntervalInputs:
        raise TypeError("inputs must be a ThermalIntervalInputs")
    if _duration is None:
        if type(dt_seconds) is not int:
            raise TypeError("dt_seconds must be an integer")
        if dt_seconds <= 0:
            raise ValueError("dt_seconds must be greater than zero")
    else:
        validate_substep_seconds(dt_seconds, _duration)

    try:
        ThermalState(state.node_states)
        ThermalNetworkConfig(
            config.nodes,
            config.links,
            config.bus_node_id,
            config.battery_node_id,
            config.payload_node_id,
        )
        ThermalIntervalInputs(inputs.node_boundaries)
        if applied_heat_inputs is not None:
            ThermalAppliedHeatInputs(applied_heat_inputs.node_heat_inputs)
    except (TypeError, ValueError):
        raise
    except (AttributeError, ArithmeticError) as error:
        raise ValueError("thermal inputs cannot be evaluated safely") from error

    configured_node_ids = {node.node_id for node in config.nodes}
    runtime_node_ids = {
        node_state.node_id for node_state in state.node_states
    }
    boundary_node_ids = {
        boundary.node_id for boundary in inputs.node_boundaries
    }
    if runtime_node_ids != configured_node_ids:
        raise ValueError(
            "runtime thermal node IDs must exactly match configured node IDs"
        )
    if boundary_node_ids != configured_node_ids:
        raise ValueError(
            "thermal boundary node IDs must exactly match configured node IDs"
        )

    if applied_heat_inputs is None:
        applied_heat_into_by_id: dict[ThermalNodeId, int | float] = {
            node.node_id: 0 for node in config.nodes
        }
    else:
        applied_heat_node_ids = {
            heat_input.node_id
            for heat_input in applied_heat_inputs.node_heat_inputs
        }
        if applied_heat_node_ids != configured_node_ids:
            raise ValueError(
                "applied-heat node IDs must exactly match configured node IDs"
            )
        applied_heat_into_by_id = {
            heat_input.node_id: _thermal_normalized_real(
                f"applied heat for {heat_input.node_id.canonical}",
                heat_input.applied_heat_into_w,
            )
            for heat_input in applied_heat_inputs.node_heat_inputs
        }

    start_temperature_by_id = {
        node_state.node_id: _thermal_normalized_real(
            f"start temperature for {node_state.node_id.canonical}",
            node_state.temperature_k,
        )
        for node_state in state.node_states
    }
    sink_temperature_by_id = {
        boundary.node_id: _thermal_normalized_real(
            f"radiative sink temperature for {boundary.node_id.canonical}",
            boundary.radiative_sink_temperature_k,
        )
        for boundary in inputs.node_boundaries
    }
    conductive_heat_into_by_id: dict[ThermalNodeId, int | float] = {
        node.node_id: 0 for node in config.nodes
    }

    link_heat_flows = []
    for link in config.links:
        temperature_difference_k = _thermal_checked_difference(
            f"temperature difference for {link.link_id.canonical}",
            start_temperature_by_id[link.node_a_id],
            start_temperature_by_id[link.node_b_id],
        )
        heat_flow_a_to_b_w = _thermal_checked_product(
            f"conductive heat flow for {link.link_id.canonical}",
            link.conductance_w_per_k.value,
            temperature_difference_k,
        )
        conductive_heat_into_by_id[link.node_a_id] = _thermal_checked_difference(
            f"conductive heat into {link.node_a_id.canonical}",
            conductive_heat_into_by_id[link.node_a_id],
            heat_flow_a_to_b_w,
        )
        conductive_heat_into_by_id[link.node_b_id] = _thermal_checked_sum(
            f"conductive heat into {link.node_b_id.canonical}",
            conductive_heat_into_by_id[link.node_b_id],
            heat_flow_a_to_b_w,
        )
        link_heat_flows.append(
            ThermalLinkHeatFlow(
                link.link_id,
                link.node_a_id,
                link.node_b_id,
                heat_flow_a_to_b_w,
            )
        )

    node_transitions = []
    for node in config.nodes:
        node_id = node.node_id
        start_temperature_k = start_temperature_by_id[node_id]
        sink_temperature_k = sink_temperature_by_id[node_id]
        sink_fourth_power = _thermal_checked_fourth_power(
            f"radiative sink temperature for {node_id.canonical}",
            sink_temperature_k,
        )
        node_fourth_power = _thermal_checked_fourth_power(
            f"node temperature for {node_id.canonical}",
            start_temperature_k,
        )
        fourth_power_difference = _thermal_checked_difference(
            f"radiative fourth-power difference for {node_id.canonical}",
            sink_fourth_power,
            node_fourth_power,
        )
        radiative_heat_into_w = _thermal_checked_product(
            f"radiative heat into {node_id.canonical}",
            node.emissivity.value,
            _STEFAN_BOLTZMANN_W_PER_M2_K4,
            node.radiating_area_m2.value,
            fourth_power_difference,
        )
        conductive_heat_into_w = conductive_heat_into_by_id[node_id]
        applied_heat_into_w = applied_heat_into_by_id[node_id]
        exchange_heat_into_w = _thermal_checked_sum(
            f"net heat into {node_id.canonical}",
            conductive_heat_into_w,
            radiative_heat_into_w,
        )
        net_heat_into_w = _thermal_checked_sum(
            f"net heat into {node_id.canonical}",
            exchange_heat_into_w,
            applied_heat_into_w,
        )
        thermal_energy_change_j = _thermal_checked_product(
            f"thermal energy change for {node_id.canonical}",
            net_heat_into_w,
            dt_seconds,
        )
        temperature_change_k = _thermal_checked_quotient(
            f"temperature change for {node_id.canonical}",
            thermal_energy_change_j,
            node.heat_capacity_j_per_k.value,
        )
        end_temperature_k = _thermal_checked_sum(
            f"end temperature for {node_id.canonical}",
            start_temperature_k,
            temperature_change_k,
        )
        if end_temperature_k <= 0:
            raise ValueError(
                f"end temperature for {node_id.canonical} must be greater "
                "than zero"
            )
        node_transitions.append(
            ThermalNodeTransition(
                node_id,
                start_temperature_k,
                end_temperature_k,
                conductive_heat_into_w,
                radiative_heat_into_w,
                applied_heat_into_w,
                net_heat_into_w,
                thermal_energy_change_j,
            )
        )

    result_type = ThermalIntervalResult if _duration is None else ThermalSubstepResult
    extra = {} if _duration is None else {"duration": _duration}
    return result_type(
        tuple(node_transitions),
        tuple(link_heat_flows),
        dt_seconds,
        **extra,
    )


def _damage_normalized_real(name: str, value: object) -> int | float:
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


def _damage_normalized_nonnegative_real(name: str, value: object) -> int | float:
    normalized = _damage_normalized_real(name, value)
    if normalized < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return normalized


def _damage_normalized_positive_real(name: str, value: object) -> int | float:
    normalized = _damage_normalized_real(name, value)
    if normalized <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return normalized


def _damage_validated_positive_seconds(value: object) -> int:
    if type(value) is not int:
        raise TypeError("dt_seconds must be an integer")
    if value <= 0:
        raise ValueError("dt_seconds must be greater than zero")
    return value


def _damage_checked_sum(name: str, *values: object) -> int | float:
    """Add finite values using ordinary built-in arithmetic."""
    total: int | float = 0
    for index, value in enumerate(values):
        addend = _damage_normalized_real(f"{name} addend {index}", value)
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
        total = _damage_normalized_real(name, total)
    return total


def _damage_checked_difference(
    name: str,
    minuend: object,
    subtrahend: object,
) -> int | float:
    minuend_value = _damage_normalized_real(f"{name} minuend", minuend)
    subtrahend_value = _damage_normalized_real(f"{name} subtrahend", subtrahend)
    try:
        difference = minuend_value - subtrahend_value
    except (
        AttributeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError(f"{name} cannot be represented as finite") from error
    return _damage_normalized_real(name, difference)


def _damage_checked_product(name: str, *values: object) -> int | float:
    product: int | float = 1
    for index, value in enumerate(values):
        factor = _damage_normalized_real(f"{name} factor {index}", value)
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
        product = _damage_normalized_real(name, product)
        if prior_product != 0 and factor != 0 and product == 0:
            raise ValueError(f"{name} cannot represent a nonzero product")
    return product


def _damage_checked_quotient(
    name: str,
    numerator: object,
    denominator: object,
) -> int | float:
    numerator_value = _damage_normalized_real(f"{name} numerator", numerator)
    denominator_value = _damage_normalized_real(f"{name} denominator", denominator)
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
    normalized = _damage_normalized_real(name, quotient)
    if numerator_value != 0 and normalized == 0:
        raise ValueError(f"{name} cannot represent a nonzero quotient")
    return normalized


def _damage_temperature_acceleration(
    temperature_k: object,
    reference_temperature_k: object,
    activation_energy_j_per_mol: object,
) -> int | float:
    """Return a normalized Arrhenius temperature-acceleration factor."""
    temperature = _damage_normalized_positive_real("temperature_k", temperature_k)
    reference = _damage_normalized_positive_real(
        "reference_temperature_k",
        reference_temperature_k,
    )
    activation_energy = _damage_normalized_nonnegative_real(
        "activation_energy_j_per_mol",
        activation_energy_j_per_mol,
    )
    if activation_energy == 0 or temperature == reference:
        return 1.0

    inverse_temperature = _damage_checked_quotient(
        "inverse temperature",
        1.0,
        temperature,
    )
    inverse_reference = _damage_checked_quotient(
        "inverse reference temperature",
        1.0,
        reference,
    )
    inverse_difference = _damage_checked_difference(
        "inverse-temperature difference",
        inverse_temperature,
        inverse_reference,
    )
    activation_ratio = _damage_checked_quotient(
        "activation-energy ratio",
        activation_energy,
        _MOLAR_GAS_CONSTANT_J_PER_MOL_K,
    )
    exponent_magnitude = _damage_checked_product(
        "Arrhenius exponent",
        activation_ratio,
        inverse_difference,
    )
    exponent = _damage_checked_product(
        "Arrhenius exponent",
        -1.0,
        exponent_magnitude,
    )
    try:
        acceleration = exp(exponent)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(
            "temperature acceleration cannot be represented as finite"
        ) from error
    acceleration = _damage_normalized_real(
        "temperature acceleration",
        acceleration,
    )
    if acceleration <= 0:
        raise ValueError(
            "temperature acceleration cannot be represented as positive"
        )
    return acceleration


def compute_battery_degradation_substep(state, battery_config, ageing_config, interval_input):
    _native_enter('compute_battery_degradation_substep')
    if type(interval_input) is not BatteryDegradationSubstepInput:
        raise TypeError("interval_input must be BatteryDegradationSubstepInput")
    interval_input.__post_init__()
    return _damage_compute_battery_degradation(state, battery_config, ageing_config,
        interval_input, _duration=interval_input.duration)


def _damage_compute_battery_degradation(state, battery_config, ageing_config, interval_input, _duration=None):
    _native_enter('_damage_compute_battery_degradation')
    if type(state) is not BatteryDegradationState:
        raise TypeError("state must be a BatteryDegradationState")
    if type(battery_config) is not BatteryConfig:
        raise TypeError("battery_config must be a BatteryConfig")
    if type(ageing_config) is not BatteryAgeingModelConfig:
        raise TypeError("ageing_config must be a BatteryAgeingModelConfig")
    input_type = BatteryDegradationIntervalInput if _duration is None else BatteryDegradationSubstepInput
    if type(interval_input) is not input_type:
        raise TypeError(
            "interval_input must be a BatteryDegradationIntervalInput"
        )

    BatteryDegradationState(
        state.usable_capacity_retention,
        state.cumulative_energy_throughput_wh,
    )
    interval_input.__post_init__()
    start_retention = _damage_normalized_positive_real(
        "start_usable_capacity_retention",
        state.usable_capacity_retention,
    )
    start_throughput = _damage_normalized_nonnegative_real(
        "start_cumulative_energy_throughput_wh",
        state.cumulative_energy_throughput_wh,
    )
    temperature = _damage_normalized_positive_real(
        "representative_temperature_k",
        interval_input.battery_temperature_k,
    )
    increment = _damage_normalized_nonnegative_real(
        "throughput_increment_wh",
        interval_input.throughput_increment.total_energy_throughput_wh,
    )
    dt_seconds = (_damage_validated_positive_seconds(interval_input.dt_seconds) if _duration is None
                  else checked_duration(_duration))
    reference_temperature = _damage_normalized_positive_real(
        "reference_temperature_k",
        ageing_config.reference_temperature_k.value,
    )
    calendar_acceleration = _damage_temperature_acceleration(
        temperature,
        reference_temperature,
        ageing_config.calendar_activation_energy_j_per_mol.value,
    )
    cycling_acceleration = _damage_temperature_acceleration(
        temperature,
        reference_temperature,
        ageing_config.cycling_activation_energy_j_per_mol.value,
    )
    calendar_damage = _damage_checked_product(
        "calendar_damage",
        ageing_config.calendar_damage_rate_per_second_at_reference.value,
        calendar_acceleration,
        dt_seconds,
    )
    nominal_energy_wh = _damage_normalized_positive_real(
        "nominal_energy_wh",
        battery_config.nominal_energy_wh.value,
    )
    normalized_throughput = _damage_checked_quotient(
        "normalized_energy_throughput",
        increment,
        nominal_energy_wh,
    )
    cycling_damage = _damage_checked_product(
        "cycling_damage",
        ageing_config
        .cycling_damage_per_normalized_energy_throughput_at_reference.value,
        cycling_acceleration,
        normalized_throughput,
    )
    total_damage = _damage_checked_sum(
        "total_damage",
        calendar_damage,
        cycling_damage,
    )
    end_retention = _damage_checked_difference(
        "end_usable_capacity_retention",
        start_retention,
        total_damage,
    )
    if end_retention <= 0:
        raise ValueError(
            "battery degradation candidate retention must be greater than zero"
        )
    end_throughput = _damage_checked_sum(
        "end_cumulative_energy_throughput_wh",
        start_throughput,
        increment,
    )
    result_type = BatteryDegradationTransition if _duration is None else BatteryDegradationSubstepTransition
    extra = {} if _duration is None else {"duration": _duration}
    return result_type(
        start_retention,
        end_retention,
        start_throughput,
        increment,
        end_throughput,
        temperature,
        calendar_acceleration,
        cycling_acceleration,
        calendar_damage,
        cycling_damage,
        total_damage,
        dt_seconds,
        **extra,
    )


def compute_explicit_solar_degradation_transition(
    state: SolarDegradationState,
    forcing: SolarDegradationForcingInput,
) -> SolarDegradationTransition:
    """Apply one explicit solar retention loss without a hidden time law."""
    _native_enter('compute_explicit_solar_degradation_transition')
    if type(state) is not SolarDegradationState:
        raise TypeError("state must be a SolarDegradationState")
    if type(forcing) is not SolarDegradationForcingInput:
        raise TypeError(
            "forcing must be a SolarDegradationForcingInput"
        )
    SolarDegradationState(state.generation_retention)
    SolarDegradationForcingInput(forcing.retention_loss)
    start = _damage_normalized_positive_real(
        "start_generation_retention",
        state.generation_retention,
    )
    loss = _damage_normalized_nonnegative_real(
        "retention_loss",
        forcing.retention_loss,
    )
    end = _damage_checked_difference("end_generation_retention", start, loss)
    if end <= 0:
        raise ValueError(
            "solar degradation candidate retention must be greater than zero"
        )
    return SolarDegradationTransition(start, loss, end)


def evaluate_port_eps(state,config,inputs,duration,compilation,capability,*,port_policy,port_state,port_work,work=None,limits=None):
    _native_enter('evaluate_port_eps')
    if type(compilation) is not ConstructionCompilation:raise TypeError('compiled construction required')
    c=compilation.configuration;loads=inputs.load_breakdown
    if work is not None:work.reserve_lines(8,limits)
    def line_call(function,*args):
        try:value=function(*args)
        except ElectricalLimitError:
            if work is not None:work.line_calls_refused+=1
            raise
        except BaseException:
            if work is not None:work.line_work_unknown+=1
            raise
        if work is not None:work.line_calls_returned+=1
        return value
    loads.__post_init__()
    if any(type(getattr(loads,f.name)) not in (int,float) for f in fields(loads)):raise TypeError('built-in finite power fields required')
    source=compute_solar_generation(config.solar_array,sunlit=inputs.sunlit,
        incidence_angle_deg=inputs.incidence_angle_deg,nominal_generation_capability_w=capability.solar_nominal_generation_capability_w)
    byid={b.line_id:b for b in compilation.branches};results=[]
    pv=byid[c.pv_line_id]
    generated=line_call(generated_power_line,pv.wire,c.pv_source_voltage_v,source.generation_w)
    results.append(BranchOperatingResult(pv.line_id,'PV',generated,pv.heat_node_id))
    load_results=[]
    for binding in c.receiving:
        branch=byid[binding.line_id]
        demand=getattr(loads,binding.component.value.replace('-','_')+'_w')
        op=line_call(constant_power_load,branch.wire,c.bus_voltage_v,demand)
        results.append(BranchOperatingResult(branch.line_id,binding.component.value,op,branch.heat_node_id))
        load_results.append(op)
    current=fsum(r.current_a for r in load_results)
    if not isfinite(current) or current>c.bus_current_limit_a:raise ElectricalLimitError('aggregate regulated bus current limit exceeded')
    source_load=fsum(r.source_power_w for r in load_results)
    network=compilation.configuration.thermal_network
    temperature=next(n.temperature_k for n in state.thermal.node_states if n.node_id==network.battery_node_id)
    battery=battery_port_transition(port_policy,port_state,energy_wh=state.battery.energy_wh,
        usable_wh=capability.battery_usable_capacity_wh,temperature_k=temperature,
        generation_w=generated.delivered_power_w,load_w=source_load,duration=duration,
        charge_bus_limit_w=config.battery.max_charge_input_power_w.value,
        discharge_bus_limit_w=config.battery.max_discharge_output_power_w.value,work=port_work)
    return PortConstructionEPSResult(compilation.configuration_digest,source,loads,tuple(results),
        source.generation_w,generated.delivered_power_w,loads.total_load_w,source_load,
        generated.loss_w,fsum(r.loss_w for r in load_results),battery,battery.unmet_load_w==0)


def service_port_substep(candidate, duration, forcing, eps_inputs, policy,
        solar, *, compilation, service_policy, service_mode, service_work,
        work=None, limits=None, standby=False, internal_heat_adjustments_w=None,
        start_seconds=None, end_seconds=None, battery_port_policy=None, battery_port_state=None, battery_port_work=None,environment_binding=None,prepared_runtime=None):
    """Commit one selected private physical proposal, including OFF evolution.

    The caller owns atomic publication, operating/survival domain decisions,
    mode hysteresis, action eligibility, clock and attitude.  Full feasible
    NORMAL operation follows the unchanged electrical and coupled primitives.
    In a deficit, branch priority and bisection are applied to RECEIVING W;
    each proposal recomputes actual nonlinear line current/loss and battery
    conversion.  The greatest tested feasible lower point is retained.  Zero
    representable service is an explicit unavailable result, not a function
    grant.  No trial thermal state or trial heat is published.
    """
    _native_enter('service_port_substep')
    if type(compilation) is not ConstructionCompilation:
        raise TypeError('compiled construction required')
    if type(service_policy) is not ConstructionServicePolicy:
        raise TypeError('exact ConstructionServicePolicy required')
    admit_policy(service_policy)
    if type(service_work) is not ConstructionServiceWork:
        raise TypeError('exact ConstructionServiceWork required')
    service_work.validate()
    if type(service_mode) is not str or service_mode not in _MODES:
        raise ValueError('known construction service mode required')
    seconds = checked_duration(duration)
    start = Fraction(candidate.simulation_time_seconds if start_seconds is None else start_seconds)
    exact_duration = (duration.fraction if type(duration) is RationalSeconds else
                      Fraction(duration.numerator_seconds, 1 << duration.subdivision_level))
    end = start + exact_duration if end_seconds is None else Fraction(end_seconds)
    if end <= start or end-start != exact_duration:
        raise ValueError('exact inner service interval must match duration')
    cfg = candidate.inputs.spacecraft_configuration
    state = candidate.spacecraft_state
    if (cfg.thermal.network != compilation.configuration.thermal_network or
            forcing.thermal_inputs != compilation.configuration.thermal_boundaries):
        raise ValueError('stale thermal construction binding')
    desired = _loads(eps_inputs.load_breakdown)
    if fsum(getattr(desired, name) for name in _ESSENTIAL) <= 0:
        raise ValueError('positive authored essential demand required')
    commanded = desired if service_mode == 'NORMAL' else replace(desired,
        **{name: 0. for name in _FIELDS if name not in _ESSENTIAL})
    capability = compute_eps_capability(cfg.eps, state.degradation)
    entry_trials = service_work.allocation_trials

    def trial(loads, *, bisect=False):
        if service_work.allocation_trials-entry_trials >= _MAX_TRIALS:
            raise ValueError('CONSTRUCTION_SERVICE_LOCAL_TRIAL_QUOTA')
        service_work.reserve(bisection=bisect)
        try:
            result = evaluate_port_eps(state, cfg.eps,
                replace(eps_inputs, load_breakdown=loads), duration,
                compilation, capability, port_policy=battery_port_policy, port_state=battery_port_state, port_work=battery_port_work, work=work, limits=limits)
        except ElectricalLimitError:
            service_work.eps_calls_refused += 1
            raise
        except BaseException:
            service_work.eps_work_unknown += 1
            raise
        service_work.eps_calls_returned += 1
        return result

    initial_wire_refusal = None
    try:
        full = trial(commanded)
    except ElectricalLimitError as error:
        full = None
        initial_wire_refusal = str(error)
    if full is not None and full.fully_served:
        selected = full
        served = commanded
    else:
        # A zero load proposal still evaluates current-attitude PV, PV cable
        # heat and battery charging.  It can itself refuse an invalid PV line.
        served = PowerLoadBreakdown(*(0. for _ in _FIELDS))
        try:
            selected = trial(served)
        except ElectricalLimitError as error:
            failure = PortServiceFailureDiagnostic(service_mode, start, end,
                desired, commanded, full, str(error), service_work.allocation_trials-entry_trials)
            raise ConstructionServiceElectricalRefusal(str(error), failure) from error
        if not selected.fully_served:
            raise ValueError('zero receiving load failed EPS admission')
        available = not (selected.delivered_generation_w == 0 and state.battery.energy_wh == 0)
        # Bisection probes are a FIXED 32-level receiving-W grid.  Its smallest
        # positive tested power for a positive component is requested/2**32.
        # Source W is at least receiving W on every admitted resistive branch.
        # If the returned full-demand battery proposal cannot supply even the
        # smallest such probe, all positive grid points are proved infeasible.
        # Retain the zero-allocation proposal AND its small positive energy;
        # never snap energy to zero or spend an unrouted numerical residue.
        quanta = tuple(getattr(commanded, name)/(2**service_policy.max_bisections)
                       for name in _FIELDS if getattr(commanded, name) > 0)
        below_grid = (full is not None and quanta and min(quanta) > 0 and
                      full.battery.served_load_w < min(quanta))
        if below_grid: available = False
        if available:
            for name in _PRIORITY:
                requested = getattr(commanded, name)
                if requested == 0:
                    continue
                try:
                    attempt = trial(replace(served, **{name: requested}))
                except ElectricalLimitError:
                    attempt = None
                if attempt is not None and attempt.fully_served:
                    selected = attempt
                    served = replace(served, **{name: requested})
                    continue
                low, high = 0., requested
                best = getattr(served, name)
                for _ in range(service_policy.max_bisections):
                    midpoint = low + (high-low)/2
                    if midpoint == low or midpoint == high:
                        break
                    try:
                        attempt = trial(replace(served, **{name: midpoint}), bisect=True)
                    except ElectricalLimitError:
                        attempt = None
                    if attempt is not None and attempt.fully_served:
                        low = midpoint
                        best = midpoint
                        selected = attempt
                    else:
                        high = midpoint
                served = replace(served, **{name: best})

    essential_unserved = fsum(getattr(commanded, n)-getattr(served, n) for n in _ESSENTIAL)
    essential_full = all(getattr(commanded, n) == getattr(served, n) for n in _ESSENTIAL)
    full_service = all(getattr(commanded, n) == getattr(served, n) for n in _FIELDS)
    radio = (service_mode == 'NORMAL' and essential_full and
             commanded.communications_w == served.communications_w)
    reason = ('FULL_COMMANDED_SERVICE' if full_service else
              'ESSENTIAL_SERVICE_UNAVAILABLE' if not essential_full else 'NONESSENTIAL_SERVICE_UNAVAILABLE')
    diagnostic = PortServiceDiagnostic(service_mode, start, end,
        desired, commanded, served, desired.total_load_w, commanded.total_load_w,
        served.total_load_w, fsum(getattr(desired, n)-getattr(commanded, n) for n in _FIELDS),
        essential_unserved, essential_full, essential_full, radio, full_service,
        full, selected, service_work.allocation_trials-entry_trials,
        initial_wire_refusal, reason)
    ledger = ServedPowerLedger(tuple(ServedComponentPower(component,
        getattr(commanded, component.value.replace('-', '_')+'_w'),
        getattr(served, component.value.replace('-', '_')+'_w')) for component in ElectricalLoadComponent))
    routed = compute_routed_internal_heat(commanded, ledger, forcing.routing_config, cfg.thermal.network)
    sources = compose_routed_internal_heat_sources(routed, forcing.external_heat_sources)
    wire = {n.node_id: fsum(b.electrical.loss_w for b in selected.branches
        if b.heat_node_id == n.node_id.value) for n in cfg.thermal.network.nodes}
    adjustments = {} if internal_heat_adjustments_w is None else dict(internal_heat_adjustments_w)
    if (len(adjustments) != (0 if internal_heat_adjustments_w is None else len(internal_heat_adjustments_w)) or
            not set(adjustments) <= set(wire)):
        raise ValueError('unique known mechanical heat destination required')
    if any(value != 0 for value in adjustments.values()) and (
            service_mode != 'NORMAL' or not diagnostic.full_commanded_service):
        raise ConstructionServiceDomainRefusal(
            'UNSUPPORTED_UNPOWERED_MECHANICAL_TRANSITION', diagnostic)
    changed = []
    for node in sources.node_sources:
        value = node.internal_dissipation_w+wire[node.node_id]+adjustments.get(node.node_id, 0.)
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError('finite nonnegative combined heat required')
        changed.append(replace(node, internal_dissipation_w=value))
    sources = replace(sources, node_sources=tuple(changed))
    carrier = selected.integration_carrier()
    thermal, physical, next_port = complete_port_cut(candidate, duration, forcing,
        sources, carrier, capability, solar, battery_port_policy, battery_port_state,
        battery_port_work, start, end,environment_binding=environment_binding,prepared_runtime=prepared_runtime)
    service_work.selected_coupled_calls += 1
    received = tuple((n.node_id, n.applied_heat_into_w) for n in routed.node_internal_heat_w)
    return PortConstructionPhysicalResult(physical, selected, received,
        tuple(wire.items()), tuple(adjustments.items()), diagnostic, next_port), carrier


def complete_port_cut(candidate,duration,forcing,sources,carrier,capability,solar,port_policy,port_state,port_work,start,end,*,environment_binding=None,prepared_runtime=None):
    """Pure accepted thermal/capacity leaves, then atomic private publication.
    Per-node battery_conversion_heat_w denotes explicit irreversible port
    heat: Ohmic at BATTERY, residual converter at BUS, each exactly once.
    """
    _native_enter('complete_port_cut')
    cfg=candidate.inputs.spacecraft_configuration;state=candidate.spacecraft_state
    network=cfg.thermal.network;b=carrier.battery;dt=checked_duration(duration)
    if type(port_policy)is not BatteryPortPolicy or type(port_state)is not BatteryPortState:raise TypeError('bound port policy/history')
    ledgers=[]
    for node in sources.node_sources:
        irreversible=b.ohmic_heat_wh*3600/dt if node.node_id==network.battery_node_id else 0.
        if node.node_id==network.bus_node_id:irreversible+=b.converter_loss_wh*3600/dt
        values=(node.internal_dissipation_w,node.absorbed_solar_w,node.absorbed_albedo_w,node.absorbed_earth_ir_w,irreversible)
        total=0
        for value in values:total+=value
        ledgers.append(ThermalNodeHeatLedger(node.node_id,*values,total))
    if prepared_runtime is None:
        from .environment_thermal import thermal_network
        effective=thermal_network(environment_binding,network)
    else:
        from .lifecycle_prepared import PreparedRuntime
        if type(prepared_runtime) is not PreparedRuntime:
            raise TypeError('B63 exact private prepared runtime')
        effective=prepared_runtime.validate_environment_binding(environment_binding,network)
    result=compute_thermal_substep_transition(state.thermal,effective,forcing.thermal_inputs,
        ThermalAppliedHeatInputs(tuple(ThermalNodeAppliedHeatInput(n.node_id,n.total_applied_heat_w) for n in ledgers)),duration=duration)
    thermal=EPSThermalSubstepResult(tuple(ledgers),result);byid={n.node_id:n for n in result.node_transitions}
    initial=next(n.temperature_k for n in state.thermal.node_states if n.node_id==network.battery_node_id)
    representative=initial+(byid[network.battery_node_id].end_temperature_k-initial)/2
    charge=b.chemical_charge_w*dt/3600;discharge=b.chemical_discharge_w*dt/3600
    throughput=BatteryThroughputIncrement(charge,discharge,charge+discharge)
    degradation=compute_battery_degradation_substep(state.degradation.battery,cfg.eps.battery,
        cfg.degradation.battery_ageing_model,BatteryDegradationSubstepInput(representative,throughput,dt,duration))
    solar_result=None if solar is None else compute_explicit_solar_degradation_transition(state.degradation.solar,solar)
    reconciliation=compute_battery_capacity_reconciliation(b.end_energy_wh,cfg.eps.battery,degradation.end_usable_capacity_retention)
    next_port=advance_port_state(port_policy,port_state,b,start=start,end=end,representative_temperature_k=representative,work=port_work)
    BatteryState(reconciliation.authoritative_end_energy_wh)
    for n in state.thermal.node_states:ThermalNodeState(n.node_id,byid[n.node_id].end_temperature_k)
    BatteryDegradationState(degradation.end_usable_capacity_retention,degradation.end_cumulative_energy_throughput_wh)
    if solar_result is not None:SolarDegradationState(solar_result.end_generation_retention)
    physical=PortCoupledResult(carrier,thermal,degradation,solar_result,capability,reconciliation)
    state.battery.energy_wh=reconciliation.authoritative_end_energy_wh
    for n in state.thermal.node_states:n.temperature_k=byid[n.node_id].end_temperature_k
    state.degradation.battery.usable_capacity_retention=degradation.end_usable_capacity_retention
    state.degradation.battery.cumulative_energy_throughput_wh=degradation.end_cumulative_energy_throughput_wh
    if solar_result is not None:state.degradation.solar.generation_retention=solar_result.end_generation_retention
    return thermal,physical,next_port


def _quiet_scale(name, policy):
    if type(policy)is EnvironmentQuietIntegrationPolicy:
        if name in ('environment_calendar_seconds','environment_pv_exposure_seconds','environment_thermal_exposure_seconds'):return policy.absolute_exposure_seconds
        if name=='environment_pv_retention':return policy.absolute_retention
        if name.startswith('environment_epsilon:'):return policy.absolute_emissivity
        if name.startswith('environment_conductance:'):return policy.absolute_conductance_w_per_k
        if name.startswith('environment_'):raise ValueError('unknown environment metric units')
    if type(policy) in (BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy):
        units={'port_voltage_v':policy.absolute_voltage_v,'port_ocv_v':policy.absolute_voltage_v,
            'port_current_a':policy.absolute_current_a,'port_resistance_ohm':policy.absolute_resistance_ohm,
            'port_resistance_damage':policy.absolute_resistance_damage,'port_weighted_seconds':policy.absolute_weighted_seconds}
        if name in units:return units[name]
        if name.startswith('port_') and not name.endswith('_wh'):raise ValueError('unknown port metric units')
    if name.startswith('temperature:'): return policy.absolute_temperature_k
    if 'retention' in name or name in ('calendar_damage', 'cycling_damage'):
        return policy.absolute_retention
    return policy.absolute_energy_wh


def quiet_error_norm(initial_values, full, first_half, second_half, policy):
    """Infinity norm over every physical state and every selected-path integral."""
    _native_enter('quiet_error_norm')
    for sample in (full, first_half, second_half): sample.__post_init__()
    start = dict(initial_values)
    if (tuple(k for k, _ in full.state_values) != tuple(start) or
            tuple(k for k, _ in full.state_values) != tuple(k for k, _ in second_half.state_values) or
            tuple(k for k, _ in first_half.state_values) != tuple(start) or
            tuple(k for k, _ in full.integrals) != tuple(k for k, _ in first_half.integrals) or
            tuple(k for k, _ in full.integrals) != tuple(k for k, _ in second_half.integrals)):
        raise ValueError('quiet metric authority/order changed')
    errors = []
    for (name, coarse), (_, fine) in zip(full.state_values, second_half.state_values):
        scale = _quiet_scale(name, policy)+policy.relative_tolerance*max(abs(start[name]), abs(coarse), abs(fine))
        errors.append(abs(fine-coarse)/scale)
    for (name, coarse), (_, h1), (_, h2) in zip(full.integrals, first_half.integrals, second_half.integrals):
        fine = h1+h2
        scale = _quiet_scale(name, policy)+policy.relative_tolerance*max(abs(coarse), abs(fine))
        errors.append(abs(fine-coarse)/scale)
    result = max(errors)
    if not isfinite(result): raise ValueError('quiet nonfinite error norm')
    return result


def integrate_quiet_hold(context, start, end, *, policy, controller, work,
                         clone_context, state_values, step):
    """Integrate ONE already bounded constant-support interval transactionally.

    Boundary ownership is the caller's: end cannot pass any command/ACK,
    telemetry, profile, lighting, mission or report cut. The step callback must
    retain every reservation even when this function rejects its private state.
    """
    _native_enter('integrate_quiet_hold')
    if type(policy) not in (QuietIntegrationPolicy, BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy) or type(controller) is not QuietControllerState or type(work) is not QuietWork:
        raise TypeError('explicit quiet policy/controller/work required')
    start, end = Q(start), Q(end)
    controller.validate(policy, clock=start); work.validate(policy)
    if end <= start or end-start > 120: raise ValueError('bounded advancing quiet interval required')
    selected = []; current = context; clock = start; proposal = controller.next_step_seconds
    attempts = 0; max_error = 0.; last_error = controller.last_error_norm
    last_step = Q(0); phase = controller.phase

    def call(origin, left, right, kind):
        work.reserve(kind, policy)
        try: result = step(origin, left, right)
        except QuietTrialRefusal:
            work.refused_leaf_calls += 1
            raise
        except BaseException:
            work.unknown_leaf_calls += 1
            raise
        work.returned_leaf_calls += 1
        if type(result) is not QuietTrial or type(result.sample) is not QuietSample:
            raise TypeError('exact complete quiet trial required')
        result.sample.__post_init__()
        return result

    while clock < end:
        remaining = end-clock
        h = min(Q(proposal), remaining)
        if h < policy.minimum_macro_seconds:
            h = min(remaining, Q(policy.detailed_seconds))
            trial = call(clone_context(current), clock, clock+h, 'detailed_fallback')
            selected.append(trial.cut); work.select(h)
            current = trial.context; clock += h; last_step = h; phase = 'DETAILED_FALLBACK'
        else:
            attempts += 1
            if attempts > policy.max_trials_per_interval:
                raise ValueError('QUIET_LOCAL_TRIAL_QUOTA')
            work.proposed_macros += 1
            initial = state_values(current)
            try:
                full = call(clone_context(current), clock, clock+h, 'full_trial')
                first = call(clone_context(current), clock, clock+h/2, 'half_trial')
                second = call(first.context, clock+h/2, clock+h, 'half_trial')
                error = quiet_error_norm(initial, full.sample, first.sample, second.sample, policy)
                admissible = (full.sample.regime == first.sample.regime == second.sample.regime and
                    not any(x.near_guard for x in (full.sample, first.sample, second.sample)) and error <= 1.)
            except QuietTrialRefusal:
                work.rejected_macros += 1
                if h <= policy.minimum_macro_seconds:
                    proposal = policy.minimum_macro_seconds
                    h = min(remaining, Q(policy.detailed_seconds))
                    trial = call(clone_context(current), clock, clock+h, 'detailed_fallback')
                    selected.append(trial.cut); work.select(h)
                    current = trial.context; clock += h; last_step = h; phase = 'DETAILED_FALLBACK'
                else: proposal = max(policy.minimum_macro_seconds, int(h)//2)
                if len(selected) > policy.max_selected_parts:
                    raise ValueError('QUIET_SELECTED_EVIDENCE_QUOTA')
                continue
            if not admissible:
                work.rejected_macros += 1
                if h > policy.minimum_macro_seconds:
                    proposal = max(policy.minimum_macro_seconds, int(h)//2)
                    continue
                trial = call(clone_context(current), clock, clock+min(remaining, Q(policy.detailed_seconds)), 'detailed_fallback')
                duration = min(remaining, Q(policy.detailed_seconds))
                selected.append(trial.cut); work.select(duration)
                current = trial.context; clock += duration; last_step = duration; phase = 'DETAILED_FALLBACK'
                proposal = policy.minimum_macro_seconds
            else:
                work.accepted_macros += 1
                selected.extend((first.cut, second.cut)); work.select(h/2); work.select(h/2)
                current = second.context; clock += h; last_step = h
                last_error = error; max_error = max(max_error, error); phase = 'ACCEPTED'
                work.maximum_accepted_error_norm = max(work.maximum_accepted_error_norm, error)
                # A shortened boundary does not ratchet the next free proposal down.
                if error <= .25: proposal = min(policy.maximum_macro_seconds, max(proposal, int(h)*2))
        if len(selected) > policy.max_selected_parts: raise ValueError('QUIET_SELECTED_EVIDENCE_QUOTA')
    next_controller = QuietControllerState(end, proposal, last_step, last_error, phase, policy.method)
    next_controller.validate(policy, clock=end); work.validate(policy)
    return QuietIntegrationResult(current, tuple(selected), next_controller, max_error)


def native_capability():
    """Compiled owner capability DATA, not build/qualification authority."""
    values = (float('1e16'), float('-1e16'), float('1.0'))
    screen = dict(ordered_addition=((values[0]+values[1])+values[2]) == 1.,
        actual_fsum=fsum((values[0],values[2],values[1])) == 1.,
        arbitrary_integer=((2**257+19)*7) == ((2**257)*7+133),
        exact_fraction=Q(3,7)+Q(4,7) == Q(1),
        signed_zero=(-0.).hex() == '-0x0.0p+0',
        subnormal=nextafter(0.,1.) > 0.)
    return dict(method=NATIVE_METHOD, ordered_python_object_arithmetic=True,
        canary=all(screen.values()), capability_screen=screen,
        python_implementation=sys.implementation.name,
        python_cache_tag=sys.implementation.cache_tag, python_version=sys.version,
        platform=sys.platform, module_basename=os.path.basename(__file__),
        arithmetic='PYTHON_OBJECT_ORDERED_BINARY64_CAPI_V1',
        exact_integer_and_fraction=True, direct_c_libm=False, actual_math_fsum=True,
        entry_monitor=dict(method=_native_entry_method, limit=_native_entry_limit,
            names=tuple(_native_entry_names), gil_held=True, reset_available=False,
            scope='OPERATIONAL_ENTRY_ATTEMPTS_NOT_SCIENTIFIC_WORK_OR_DYNAMIC_STATE'),
        coupled_owner=('allocation_and_bisection','construction_line_kernels',
            'port_current_voltage_energy_heat','simultaneous_thermal',
            'capacity_resistance_ageing','guarded_private_commit',
            'quiet_full_and_sequential_two_half_schedule'),
        service_modes=tuple(_MODES), reference_sources=dict(REFERENCE_SOURCE_SHA256),
        changes_scientific_work=False, speedup='UNPROVEN',
        scope='REQUIRES_BOUND_BUILD_RUNTIME_SOURCE_AND_FULL_SCIENTIFIC_EQUALITY')
