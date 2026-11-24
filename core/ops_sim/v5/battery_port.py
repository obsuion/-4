"""B58 reduced pack Rint port. All default coefficients are ASSUMED.

Positive signed current discharges the chemical store; negative charges it.
SOC_proxy is Wh/current usable Wh, never measured Ah-SOC. No RC dynamics.
The regulated construction bus remains a different electrical port.
"""
from .lifecycle_fast import admit_policy

from dataclasses import asdict, dataclass, replace
from fractions import Fraction as Q
from hashlib import sha256
from math import exp, isfinite, nextafter, sqrt
import json

METHOD = 'B58_ASSUMED_ENERGY_SOC_RINT_PACK_V1'
SENSOR = 'ASSUMED_ONBOARD_EXACT_SAMPLED_BMS_RECEIVED_GROUND_ONLY'
PROVENANCE = 'ASSUMED_REDUCED_PACK_NOT_CELL_DATA_OR_FLIGHT_CALIBRATION'
MAX_WORK = 2**40


def requested_port_policy(value):
    """Named immutable new-input choice; never migrate advanced state."""
    if type(value)is not str or value not in ('LEGACY',METHOD):raise ValueError('explicit battery-port selection')
    return None if value=='LEGACY' else BatteryPortPolicy()


class BatteryPortDomainError(ValueError):
    """Undefined physical/domain input: no selected transition is published."""


class BatteryPortInvariantError(BatteryPortDomainError):
    """Returned-carrier/programming invariant; not hardware unavailability."""


def returned_real(*args):
    try:return real(*args)
    except BatteryPortDomainError as e:raise BatteryPortInvariantError('BATTERY_PORT_RETURNED_'+str(e)) from e


def real(value, name, lo=0., hi=1.e12):
    try: valid = type(value) in (int, float) and isfinite(value) and lo <= value <= hi
    except OverflowError: valid = False
    if not valid:
        raise BatteryPortDomainError('BATTERY_PORT_DOMAIN:'+name)
    return float(value)


@dataclass(frozen=True, slots=True)
class BatteryPortPolicy:
    ocv_curve: tuple = ((0., 26.), (.2, 28.), (.8, 32.), (1., 33.))
    ocv_temperature_v_per_k: float = -0.002
    reference_temperature_k: float = 298.15
    resistance_reference_ohm: float = 0.12
    resistance_temperature_per_k: float = 0.02
    resistance_low_soc_factor: float = 0.25
    initial_resistance_damage: float = 0.
    maximum_resistance_damage: float = 64.
    calendar_damage_per_second: float = 1.e-8
    cycling_damage_per_chemical_wh: float = 1.e-5
    ageing_temperature_per_k: float = 0.06931471805599453
    minimum_temperature_k: float = 230.
    maximum_temperature_k: float = 360.
    minimum_terminal_voltage_v: float = 22.
    maximum_terminal_voltage_v: float = 35.5
    maximum_discharge_current_a: float = 8.
    maximum_charge_current_a: float = 4.
    maximum_discharge_bus_w: float = 200.
    maximum_charge_bus_w: float = 120.
    converter_discharge_efficiency: float = .95
    converter_charge_efficiency: float = .95
    converter_heat_node: str = 'BUS'
    bms_sensor: str = SENSOR
    provenance: str = PROVENANCE
    method: str = METHOD

    def __post_init__(self):
        if type(self.ocv_curve) is not tuple or not 2 <= len(self.ocv_curve) <= 16:
            raise BatteryPortDomainError('BATTERY_PORT_OCV_CURVE')
        previous = -1.
        for pair in self.ocv_curve:
            if type(pair) is not tuple or len(pair) != 2 or any(type(x) is not float for x in pair):
                raise BatteryPortDomainError('BATTERY_PORT_OCV_POINT')
            s, v = pair
            real(s, 'OCV energy fraction', 0, 1); real(v, 'OCV volts', 1, 100)
            if s <= previous: raise BatteryPortDomainError('BATTERY_PORT_OCV_ORDER')
            previous = s
        if self.ocv_curve[0][0] != 0. or self.ocv_curve[-1][0] != 1.:
            raise BatteryPortDomainError('BATTERY_PORT_OCV_SUPPORT')
        for name in self.__dataclass_fields__:
            if name in ('ocv_curve','converter_heat_node','bms_sensor','provenance','method'): continue
            value = getattr(self, name)
            if type(value) is not float or not isfinite(value):
                raise BatteryPortDomainError('BATTERY_PORT_POLICY:'+name)
        real(self.ocv_temperature_v_per_k, 'OCV thermal slope', -.05, .05)
        for name in ('resistance_reference_ohm','resistance_temperature_per_k',
                     'resistance_low_soc_factor','initial_resistance_damage',
                     'maximum_resistance_damage','calendar_damage_per_second',
                     'cycling_damage_per_chemical_wh','ageing_temperature_per_k'):
            real(getattr(self,name),name,0,100)
        if not 200 <= self.minimum_temperature_k < self.reference_temperature_k < self.maximum_temperature_k <= 400:
            raise BatteryPortDomainError('BATTERY_PORT_TEMPERATURE_DOMAIN')
        if not 0 <= self.initial_resistance_damage <= self.maximum_resistance_damage <= 64:
            raise BatteryPortDomainError('BATTERY_PORT_DAMAGE_DOMAIN')
        if not 0 < self.minimum_terminal_voltage_v < self.maximum_terminal_voltage_v <= 100:
            raise BatteryPortDomainError('BATTERY_PORT_VOLTAGE_WINDOW')
        for name in ('maximum_discharge_current_a','maximum_charge_current_a',
                     'maximum_discharge_bus_w','maximum_charge_bus_w'):
            real(getattr(self,name),name,1.e-9,1.e6)
        for name in ('converter_discharge_efficiency','converter_charge_efficiency'):
            real(getattr(self,name),name,1.e-9,1.)
        if (type(self.converter_heat_node) is not str or self.converter_heat_node != 'BUS' or
                type(self.method) is not str or self.method != METHOD or
                type(self.provenance) is not str or self.provenance != PROVENANCE or
                type(self.bms_sensor) is not str or self.bms_sensor != SENSOR):
            raise BatteryPortDomainError('BATTERY_PORT_EXPLICIT_ASSUMPTIONS')

    @property
    def identity(self):
        self.__post_init__()
        return sha256(json.dumps(asdict(self),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BatteryPortState:
    clock_seconds: Q
    resistance_damage: float = 0.
    temperature_weighted_seconds: float = 0.
    chemical_throughput_wh: float = 0.
    ohmic_heat_wh: float = 0.
    converter_loss_wh: float = 0.
    selected_steps: int = 0
    last_voltage_v: float | None = None
    last_current_a: float | None = None
    last_resistance_ohm: float | None = None
    last_ocv_v: float | None = None
    last_support_start_seconds: Q | None = None

    def __post_init__(self):
        if type(self.clock_seconds) is not Q or self.clock_seconds < 0 or self.clock_seconds.denominator.bit_length() > 4096:
            raise BatteryPortDomainError('BATTERY_PORT_STATE_CLOCK')
        for name in ('resistance_damage','temperature_weighted_seconds','chemical_throughput_wh','ohmic_heat_wh','converter_loss_wh'):
            if type(getattr(self,name)) is not float: raise BatteryPortDomainError('BATTERY_PORT_STATE_TYPE')
            real(getattr(self,name),name)
        if type(self.selected_steps) is not int or not 0 <= self.selected_steps <= MAX_WORK:
            raise BatteryPortDomainError('BATTERY_PORT_STATE_STEPS')
        sample=(self.last_voltage_v,self.last_current_a,self.last_resistance_ohm,self.last_ocv_v,self.last_support_start_seconds)
        if self.selected_steps == 0:
            if any(x is not None for x in sample): raise BatteryPortDomainError('BATTERY_PORT_EMPTY_MEASUREMENT')
        else:
            for name in ('last_voltage_v','last_resistance_ohm','last_ocv_v'): real(getattr(self,name),name)
            real(self.last_current_a,'signed current',-1.e6,1.e6)
            if type(self.last_support_start_seconds) is not Q or not 0 <= self.last_support_start_seconds < self.clock_seconds:
                raise BatteryPortDomainError('BATTERY_PORT_MEASUREMENT_SUPPORT')


@dataclass(slots=True)
class BatteryPortWork:
    reserved: int = 0
    returned: int = 0
    refused: int = 0
    unknown: int = 0
    ageing_reserved: int = 0
    ageing_returned: int = 0
    ageing_refused: int = 0
    ageing_unknown: int = 0

    def validate(self):
        if any(type(getattr(self,n)) is not int or not 0 <= getattr(self,n) <= MAX_WORK for n in self.__dataclass_fields__):
            raise ValueError('BATTERY_PORT_WORK_TYPE_OR_QUOTA')
        if self.returned+self.refused+self.unknown > self.reserved or self.ageing_returned+self.ageing_refused+self.ageing_unknown > self.ageing_reserved:
            raise ValueError('BATTERY_PORT_WORK_BALANCE')

    def reserve(self, ageing=False):
        self.validate(); name='ageing_reserved' if ageing else 'reserved'
        if getattr(self,name) >= MAX_WORK: raise ValueError('BATTERY_PORT_WORK_QUOTA')
        setattr(self,name,getattr(self,name)+1)


@dataclass(frozen=True, slots=True)
class BatteryPortSolution:
    available: bool
    reason: str
    current_a: float
    terminal_voltage_v: float
    terminal_power_w: float
    discriminant_v2: float
    boundary: bool


def solve_port(voc, resistance, terminal_power, *, charging, current_limit, voltage_min, voltage_max):
    """Stable binary64 algebra; D<0 is unavailable, never rounded/clamped to 0.

    D==0 is admitted only if the exact returned current/voltage pass guards;
    it is marked boundary so the quiet integrator uses detailed fallback.
    """
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


@dataclass(frozen=True, slots=True)
class BatteryPortTransition:
    duration: object
    dt_seconds: float
    start_energy_wh: float
    end_energy_wh: float
    generation_w: float
    load_w: float
    served_load_w: float
    unmet_load_w: float
    charge_input_w: float
    discharge_output_w: float
    curtailed_generation_w: float
    conversion_loss_wh: float
    ohmic_heat_wh: float
    converter_loss_wh: float
    chemical_throughput_wh: float
    chemical_charge_w: float
    chemical_discharge_w: float
    ocv_v: float
    resistance_ohm: float
    current_a: float
    terminal_voltage_v: float
    discriminant_v2: float
    limiting_reason: str
    near_boundary: bool
    method: str = METHOD

    def __post_init__(self):
        from .integration_time import checked_duration
        if type(self.method) is not str or self.method!=METHOD or checked_duration(self.duration)!=self.dt_seconds:
            raise BatteryPortInvariantError('BATTERY_PORT_TRANSITION_IDENTITY')
        for name in ('dt_seconds','start_energy_wh','end_energy_wh','generation_w','load_w','served_load_w','unmet_load_w',
                     'charge_input_w','discharge_output_w','curtailed_generation_w','conversion_loss_wh','ohmic_heat_wh',
                     'converter_loss_wh','chemical_throughput_wh','chemical_charge_w','chemical_discharge_w','ocv_v','resistance_ohm','terminal_voltage_v'):
            returned_real(getattr(self,name),name)
        returned_real(self.current_a,'signed current',-1.e6,1.e6);returned_real(self.discriminant_v2,'returned D',0,1.e12)
        if type(self.near_boundary)is not bool or type(self.limiting_reason)is not str:
            raise BatteryPortInvariantError('BATTERY_PORT_TRANSITION_FLAGS')
        if self.charge_input_w and self.discharge_output_w:raise BatteryPortInvariantError('BATTERY_PORT_SIMULTANEOUS_FLOW')
        # Validate the producer's ordered binary64 operations. Addition is not
        # the inverse of subtraction under rounding (including partial service).
        # These identities have zero tolerance, in W and Wh respectively.
        charging=self.generation_w>=self.load_w
        needed=abs(self.generation_w-self.load_w)
        flow=self.charge_input_w if charging else self.discharge_output_w
        unmet=0. if charging else needed-flow
        curtail=needed-flow if charging else 0.
        current=abs(self.current_a)
        chemical=self.ocv_v*current
        delta=chemical*self.dt_seconds/3600
        end=self.start_energy_wh+delta if charging else self.start_energy_wh-delta
        heat=current*current*self.resistance_ohm
        expected_voltage=self.ocv_v+(current*self.resistance_ohm if charging else -current*self.resistance_ohm)
        if (self.chemical_throughput_wh!=delta or self.end_energy_wh!=end or
                self.chemical_charge_w!=(chemical if charging else 0.) or
                self.chemical_discharge_w!=(0. if charging else chemical) or
                self.ohmic_heat_wh!=heat*self.dt_seconds/3600 or
                self.terminal_voltage_v!=expected_voltage or
                (charging and self.current_a>0) or (not charging and self.current_a<0)):
            raise BatteryPortInvariantError('BATTERY_PORT_RETURNED_ENERGY_HEAT_SIGN')
        if (flow>needed or (charging and self.discharge_output_w!=0) or
                (not charging and self.charge_input_w!=0) or
                self.unmet_load_w!=unmet or self.served_load_w!=self.load_w-unmet or
                self.curtailed_generation_w!=curtail or
                self.conversion_loss_wh!=self.ohmic_heat_wh+self.converter_loss_wh):
            raise BatteryPortInvariantError('BATTERY_PORT_RETURNED_BALANCE')



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
