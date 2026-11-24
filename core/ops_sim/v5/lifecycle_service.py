"""B55 explicit outer recovery contract; not a lifecycle integration adapter.

All thresholds and functional dependencies are reduced ASSUMED inputs.  This
owner selects sampled modes and accounts selected support; it evaluates no EPS,
thermal, orbit or attitude physics.  A caller must commit its coupled physical
transaction before committing these returned immutable records.  No helper can
retag a checkpoint, issue an ACK, alter attitude, grant power or create custody.
"""
from dataclasses import asdict, dataclass, replace
from fractions import Fraction as Q
from hashlib import sha256
import json
import math

POWER_SERVICE_METHOD = 'B55_CONSTRUCTION_RECOVERY_POLICY_V1'
POWER_SERVICE_API = 'B55_SELECTED_POWER_SERVICE_STATE_V1'
LEGACY = 'LEGACY'
MODES = ('NORMAL', 'SAFE', 'POWER_OFF', 'RECOVERY')
REASONS = ('INITIAL_NOMINAL', 'NORMAL_LOW_ENERGY',
    'ESSENTIAL_SERVICE_UNAVAILABLE', 'RECOVERY_RESERVE_READY',
    'BOOT_RESERVE_LOST', 'BOOT_COMPLETED')


def _integer(value, label, low=0, high=2**48):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('exact bounded service integer: '+label)
    return value


def _rational(value, label, *, positive=False):
    if type(value) is not Q or value < 0 or positive and value == 0:
        raise ValueError('exact nonnegative service seconds/energy: '+label)
    if max(abs(value.numerator).bit_length(), value.denominator.bit_length()) > 4096:
        raise ValueError('bounded service rational: '+label)
    return value


def _real(value, label, *, positive=False):
    if (type(value) not in (int, float) or not math.isfinite(value) or
            value < 0 or positive and value == 0):
        raise ValueError('finite nonnegative service physical value: '+label)
    return value


def _power(value,label):
    """Receiving W may be exact sums of admitted binary component values.

    Never round an exact component sum back to binary64 solely for accounting.
    The physical EPS/wire owners still receive their original float components.
    """
    if type(value) is Q:return _rational(value,label)
    return Q(_real(value,label))

def _pack(value):
    q = _rational(value, 'projection')
    return [str(q.numerator), str(q.denominator)]


@dataclass(frozen=True, slots=True)
class PowerServicePolicy:
    """Sampled current-capacity hysteresis, independent of inner wire solver.

    NORMAL housekeeping and hardware loads are unchanged.  SAFE/OFF/RECOVERY
    demand/load selection remains the construction-aware physical owner's work.
    The declared aggregate positive housekeeping includes OBC and low-rate
    NORMAL telemetry; no separate zero-watt OBC proves an unpowered computer.
    There is no voltage brownout model.  Stationary ideal/no-disturbance pose
    and nonvolatile custody are assumptions, never attitude or data resets.
    """
    low_usable_capacity_fraction: float = 0.10
    high_usable_capacity_fraction: float = 0.30
    minimum_dwell_seconds: int = 60
    boot_duration_seconds: int = 120
    point_reserve_fraction: float = 0.05
    contact_service_chunk_seconds: int = 1
    stationary_domain: str = 'RESTED_IDEAL_NO_DISTURBANCE_NO_ATTITUDE_RESET'
    storage_rule: str = 'NONVOLATILE_CUSTODY_NO_REBOOT_ERASURE'
    functional_rule: str = 'POSITIVE_AGGREGATE_HOUSEKEEPING_INCLUDES_OBC_AND_NORMAL_TM'
    source_role: str = 'ASSUMED_REDUCED_OPERATIONAL_POLICY_NOT_FLIGHT_CALIBRATION'
    method: str = POWER_SERVICE_METHOD

    def __post_init__(self):
        for name in ('low_usable_capacity_fraction', 'high_usable_capacity_fraction',
                     'point_reserve_fraction'):
            value = getattr(self, name)
            if type(value) is not float or not math.isfinite(value):
                raise ValueError('exact finite floating service policy fraction')
        if not (0 < self.point_reserve_fraction < self.low_usable_capacity_fraction <
                self.high_usable_capacity_fraction < 1):
            raise ValueError('ordered positive current-capacity recovery fractions')
        _integer(self.minimum_dwell_seconds, 'minimum dwell', 1, 3600)
        _integer(self.boot_duration_seconds, 'boot duration', 1, 3600)
        if type(self.contact_service_chunk_seconds) is not int or self.contact_service_chunk_seconds!=1:
            raise ValueError('fixed B55 one-second contact service chunk')
        expected = {
            'stationary_domain': 'RESTED_IDEAL_NO_DISTURBANCE_NO_ATTITUDE_RESET',
            'storage_rule': 'NONVOLATILE_CUSTODY_NO_REBOOT_ERASURE',
            'functional_rule': 'POSITIVE_AGGREGATE_HOUSEKEEPING_INCLUDES_OBC_AND_NORMAL_TM',
            'source_role': 'ASSUMED_REDUCED_OPERATIONAL_POLICY_NOT_FLIGHT_CALIBRATION',
            'method': POWER_SERVICE_METHOD}
        if any(type(getattr(self, name)) is not str or getattr(self, name) != value
               for name, value in expected.items()):
            raise ValueError('explicit fixed recovery policy assumptions/identity')

    @property
    def identity(self):
        self.__post_init__()
        raw = json.dumps(asdict(self), sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
        return sha256(raw).hexdigest()


def requested_service_policy(selector):
    """Explicit CREATE selector only; never a migration of an existing root."""
    if type(selector) is not str:
        raise TypeError('exact named power service policy selector')
    if selector == LEGACY:
        return None
    if selector == POWER_SERVICE_METHOD:
        return PowerServicePolicy()
    raise ValueError('unknown power service policy selector')


@dataclass(frozen=True, slots=True)
class PowerServiceState:
    clock_seconds: Q
    entered_at_seconds: Q
    mode: str = 'NORMAL'
    last_reason: str = 'INITIAL_NOMINAL'
    boot_progress_seconds: Q = Q(0)
    transition_count: int = 0
    essential_serviceable: bool = True
    communications_serviceable: bool = True
    tx_fully_served: bool = False

    def __post_init__(self):
        _rational(self.clock_seconds, 'clock')
        _rational(self.entered_at_seconds, 'mode enter clock')
        _rational(self.boot_progress_seconds, 'boot progress')
        if self.entered_at_seconds > self.clock_seconds:
            raise ValueError('future service mode entry')
        if type(self.mode) is not str or self.mode not in MODES:
            raise ValueError('explicit service mode')
        if type(self.last_reason) is not str or self.last_reason not in REASONS:
            raise ValueError('explicit service transition reason')
        _integer(self.transition_count, 'mode transitions')
        if type(self.essential_serviceable) is not bool or type(self.communications_serviceable) is not bool:
            raise TypeError('exact functional service flags')
        if self.communications_serviceable and (self.mode != 'NORMAL' or not self.essential_serviceable):
            raise ValueError('unpowered/degraded mode cannot transmit observations')
        if type(self.tx_fully_served) is not bool:
            raise TypeError('exact per-cut high-rate TX grant')
        if self.tx_fully_served and (self.mode != 'NORMAL' or not self.essential_serviceable):
            raise ValueError('high-rate TX requires NORMAL essential electrical service')
        if self.mode != 'RECOVERY' and self.boot_progress_seconds:
            raise ValueError('boot work belongs only to RECOVERY')
        if self.boot_progress_seconds > self.clock_seconds-self.entered_at_seconds:
            raise ValueError('boot progress exceeds actual recovery support')


    @property
    def low_rate_telemetry_serviceable(self):
        # Aggregate positive housekeeping powers only low-rate protocol service.
        # This does not grant the separately demanded high-rate CONTACT branch.
        return self.communications_serviceable


def initial_service_state(clock_seconds):
    return PowerServiceState(_rational(clock_seconds, 'initial clock'), clock_seconds)


@dataclass(frozen=True, slots=True)
class PowerServiceDecision:
    state: PowerServiceState
    previous_mode: str
    transitioned: bool
    supported: bool
    reason: str

    def __post_init__(self):
        if type(self.state) is not PowerServiceState:
            raise TypeError('exact service decision state')
        self.state.__post_init__()
        if type(self.previous_mode) is not str or self.previous_mode not in MODES:
            raise ValueError('service decision previous mode')
        if type(self.transitioned) is not bool or type(self.supported) is not bool:
            raise TypeError('exact service decision flags')
        if self.transitioned != (self.previous_mode != self.state.mode):
            raise ValueError('service decision transition identity')
        if type(self.reason) is not str or self.reason not in (*REASONS, 'UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY'):
            raise ValueError('explicit service decision cause')
        if not self.supported and self.transitioned:
            raise ValueError('unsupported domain cannot commit a mode transition')


def select_service_mode(policy, state, *, clock_seconds, energy_wh,
                        usable_capacity_wh, stationary):
    """One zero-time sampled decision; no iteration and no physical mutation.

    Energy uses CURRENT usable capacity.  An insufficient essential service flag
    originates only from the prior accepted coupled transaction.  A proposed
    degraded transition outside the rested domain is rejected with the original
    state intact; the caller must preserve its pending POINT and paid prefix.
    """
    if type(policy) is not PowerServicePolicy or type(state) is not PowerServiceState:
        raise TypeError('exact recovery policy and state')
    policy.__post_init__(); state.__post_init__()
    if _rational(clock_seconds, 'decision clock') != state.clock_seconds:
        raise ValueError('stale service decision clock')
    _real(energy_wh, 'battery energy'); _real(usable_capacity_wh, 'current usable capacity', positive=True)
    if energy_wh > usable_capacity_wh:
        raise ValueError('battery energy exceeds current usable capacity')
    if type(stationary) is not bool:
        raise TypeError('exact declared stationary-domain admission')
    mode = state.mode; reason = state.last_reason
    low = Q(policy.low_usable_capacity_fraction)*Q(usable_capacity_wh)
    high = Q(policy.high_usable_capacity_fraction)*Q(usable_capacity_wh)
    dwell = clock_seconds-state.entered_at_seconds
    if mode == 'NORMAL':
        if not state.essential_serviceable:
            mode, reason = 'POWER_OFF', 'ESSENTIAL_SERVICE_UNAVAILABLE'
        elif Q(energy_wh) <= low:
            mode, reason = 'SAFE', 'NORMAL_LOW_ENERGY'
    elif mode in ('SAFE', 'POWER_OFF'):
        if not state.essential_serviceable:
            mode, reason = 'POWER_OFF', 'ESSENTIAL_SERVICE_UNAVAILABLE'
        elif Q(energy_wh) >= high and dwell >= policy.minimum_dwell_seconds:
            mode, reason = 'RECOVERY', 'RECOVERY_RESERVE_READY'
    else:
        if not state.essential_serviceable:
            mode, reason = 'POWER_OFF', 'ESSENTIAL_SERVICE_UNAVAILABLE'
        elif Q(energy_wh) <= low:
            mode, reason = 'SAFE', 'BOOT_RESERVE_LOST'
        elif state.boot_progress_seconds >= policy.boot_duration_seconds and dwell >= policy.minimum_dwell_seconds:
            mode, reason = 'NORMAL', 'BOOT_COMPLETED'
    changed = mode != state.mode
    if (mode != 'NORMAL' or state.mode != 'NORMAL') and not stationary:
        return PowerServiceDecision(state, state.mode, False, False,
                                    'UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY')
    chosen = state if not changed else replace(state, mode=mode,
        entered_at_seconds=clock_seconds, last_reason=reason, boot_progress_seconds=Q(),
        transition_count=state.transition_count+1,
        communications_serviceable=(mode == 'NORMAL' and state.essential_serviceable), tx_fully_served=False)
    return PowerServiceDecision(chosen, state.mode, changed, True, reason)


@dataclass(frozen=True, slots=True)
class PowerServiceWork:
    normal_seconds: Q = Q(0)
    safe_seconds: Q = Q(0)
    power_off_seconds: Q = Q(0)
    recovery_seconds: Q = Q(0)
    desired_normal_load_wh: Q = Q(0)
    commanded_load_wh: Q = Q(0)
    served_receiving_load_wh: Q = Q(0)
    commanded_shed_demand_wh: Q = Q(0)
    essential_unserved_wh: Q = Q(0)
    boot_work_seconds: Q = Q(0)
    selected_steps: int = 0
    transitions: int = 0
    service_interruptions: int = 0
    transition_reasons: tuple = ()
    initial_clock_seconds: Q | None = None
    through_seconds: Q | None = None
    initial_transition_count: int = 0

    def __post_init__(self):
        for name in ('normal_seconds', 'safe_seconds', 'power_off_seconds', 'recovery_seconds',
                     'desired_normal_load_wh', 'commanded_load_wh', 'served_receiving_load_wh',
                     'commanded_shed_demand_wh', 'essential_unserved_wh', 'boot_work_seconds'):
            _rational(getattr(self, name), name)
        for name in ('selected_steps', 'transitions', 'service_interruptions'):
            _integer(getattr(self, name), name)
        if self.served_receiving_load_wh > self.commanded_load_wh or self.commanded_load_wh > self.desired_normal_load_wh:
            raise ValueError('desired/commanded/served receiving-power scopes')
        if self.commanded_shed_demand_wh != self.desired_normal_load_wh-self.commanded_load_wh:
            raise ValueError('exact commanded shed accounting')
        if self.essential_unserved_wh > self.commanded_load_wh-self.served_receiving_load_wh:
            raise ValueError('essential deficit exceeds receiving load deficit')
        if self.boot_work_seconds > self.recovery_seconds:
            raise ValueError('boot work exceeds selected recovery support')
        if type(self.transition_reasons) is not tuple or len(self.transition_reasons) > len(REASONS):
            raise ValueError('bounded transition reason counts')
        names = []
        for item in self.transition_reasons:
            if type(item) is not tuple or len(item) != 2 or type(item[0]) is not str or item[0] not in REASONS:
                raise ValueError('exact named transition count')
            names.append(item[0]); _integer(item[1], 'reason count', 1)
        if names != sorted(set(names)) or sum(n for _, n in self.transition_reasons) != self.transitions:
            raise ValueError('canonical transition reason/count balance')
        _integer(self.initial_transition_count, 'service ledger transition base')
        if self.initial_clock_seconds is None or self.through_seconds is None:
            if self.initial_clock_seconds is not None or self.through_seconds is not None or self.selected_steps or self.covered_seconds or self.transitions:
                raise ValueError('empty service ledger requires an unbound empty frontier')
        else:
            _rational(self.initial_clock_seconds, 'ledger initial clock')
            _rational(self.through_seconds, 'ledger through clock')
            if self.through_seconds-self.initial_clock_seconds != self.covered_seconds or (self.selected_steps == 0) != (self.covered_seconds == 0):
                raise ValueError('service ledger support/frontier balance')

    @property
    def covered_seconds(self):
        return self.normal_seconds+self.safe_seconds+self.power_off_seconds+self.recovery_seconds


def fresh_service_work(state):
    if type(state) is not PowerServiceState:
        raise TypeError('exact received service state')
    state.__post_init__()
    return PowerServiceWork(initial_clock_seconds=state.clock_seconds,
        through_seconds=state.clock_seconds, initial_transition_count=state.transition_count)


def commit_service_step(policy, decision, work, *, duration_seconds,
                        desired_normal_load_w, commanded_load_w, served_receiving_load_w,
                        essential_unserved_w, essential_fully_served, tx_fully_served=False):
    """Account ONE accepted coupled interval; rejected/private trials are absent.

    Power fields share the component receiving-power scope in watts. Exact
    Fraction sums of binary component values are accepted without re-rounding.  They do
    not replace EPS source-side demand, conversion or wire-loss ledgers.  The
    caller must already have selected and committed physical support; this
    pure helper itself supplies no energy and never advances world/thermal.
    """
    if type(policy) is not PowerServicePolicy or type(decision) is not PowerServiceDecision or type(work) is not PowerServiceWork:
        raise TypeError('exact service accounting inputs')
    policy.__post_init__(); decision.__post_init__(); work.__post_init__()
    if not decision.supported:
        raise ValueError('cannot account unsupported moving recovery')
    if work.through_seconds is not None and work.through_seconds != decision.state.clock_seconds:
        raise ValueError('stale service decision/work frontier')
    dt = _rational(duration_seconds, 'accepted duration', positive=True)
    if type(tx_fully_served) is not bool:
        raise TypeError('exact per-cut high-rate transmitter full-service flag')
    if type(essential_fully_served) is not bool:
        raise TypeError('exact essential full-service result')
    values = tuple(_power(v, label) for v, label in (
        (desired_normal_load_w, 'desired receiving W'), (commanded_load_w, 'commanded receiving W'),
        (served_receiving_load_w, 'served receiving W'), (essential_unserved_w, 'essential unserved W')))
    desired, commanded, served, unmet = values
    if commanded<=0:raise ValueError('positive authored essential commanded receiving demand required')
    if not served <= commanded <= desired or unmet > commanded-served:
        raise ValueError('selected receiving load/service balance')
    if essential_fully_served != (unmet == 0):
        raise ValueError('functional service differs from essential deficit')
    state = decision.state
    expected_transitions = work.initial_transition_count+work.transitions+int(decision.transitioned)
    if state.transition_count != expected_transitions:
        raise ValueError('service decision/work transition frontier')
    if tx_fully_served and (state.mode != 'NORMAL' or not essential_fully_served):
        raise ValueError('high-rate TX cannot be granted by degraded/partial essential service')
    boot = dt if state.mode == 'RECOVERY' and essential_fully_served else Q()
    advanced = replace(state, clock_seconds=state.clock_seconds+dt,
        boot_progress_seconds=state.boot_progress_seconds+boot if state.mode == 'RECOVERY' else Q(),
        essential_serviceable=essential_fully_served,
        communications_serviceable=(state.mode == 'NORMAL' and essential_fully_served),
        tx_fully_served=tx_fully_served)
    names = dict(work.transition_reasons)
    if decision.transitioned:
        names[state.last_reason] = names.get(state.last_reason, 0)+1
    time_field = {'NORMAL': 'normal_seconds', 'SAFE': 'safe_seconds',
                  'POWER_OFF': 'power_off_seconds', 'RECOVERY': 'recovery_seconds'}[state.mode]
    updates = {time_field: getattr(work, time_field)+dt}
    result = replace(work, **updates,
        desired_normal_load_wh=work.desired_normal_load_wh+desired*dt/3600,
        commanded_load_wh=work.commanded_load_wh+commanded*dt/3600,
        served_receiving_load_wh=work.served_receiving_load_wh+served*dt/3600,
        commanded_shed_demand_wh=work.commanded_shed_demand_wh+(desired-commanded)*dt/3600,
        essential_unserved_wh=work.essential_unserved_wh+unmet*dt/3600,
        boot_work_seconds=work.boot_work_seconds+boot,
        selected_steps=work.selected_steps+1, transitions=work.transitions+int(decision.transitioned),
        service_interruptions=work.service_interruptions+int(state.essential_serviceable and not essential_fully_served),
        transition_reasons=tuple(sorted(names.items())),
        initial_clock_seconds=(state.clock_seconds if work.initial_clock_seconds is None else work.initial_clock_seconds),
        through_seconds=advanced.clock_seconds)
    return advanced, result


def service_projection(policy, state, work, *, original_start_seconds):
    if type(policy) is not PowerServicePolicy or type(state) is not PowerServiceState or type(work) is not PowerServiceWork:
        raise TypeError('exact selected service projection')
    policy.__post_init__(); state.__post_init__(); work.__post_init__()
    start = _rational(original_start_seconds, 'original start')
    if ((work.initial_clock_seconds is not None and work.initial_clock_seconds != start) or
            (work.through_seconds is not None and work.through_seconds != state.clock_seconds) or
            work.covered_seconds != state.clock_seconds-start or work.initial_transition_count+work.transitions != state.transition_count):
        raise ValueError('selected mode duration/transition prefix balance')
    return dict(api=POWER_SERVICE_API, policy_identity=policy.identity, mode=state.mode,
        clock_seconds=_pack(state.clock_seconds), entered_at_seconds=_pack(state.entered_at_seconds),
        last_reason=state.last_reason, boot_progress_seconds=_pack(state.boot_progress_seconds),
        essential_serviceable=state.essential_serviceable, communications_serviceable=state.communications_serviceable,
        low_rate_telemetry_serviceable=state.low_rate_telemetry_serviceable, tx_fully_served=state.tx_fully_served,
        mode_durations_seconds={mode: _pack(getattr(work, field)) for mode, field in (
            ('NORMAL', 'normal_seconds'), ('SAFE', 'safe_seconds'),
            ('POWER_OFF', 'power_off_seconds'), ('RECOVERY', 'recovery_seconds'))},
        receiving_energy_wh={name: _pack(getattr(work, name)) for name in (
            'desired_normal_load_wh', 'commanded_load_wh', 'served_receiving_load_wh',
            'commanded_shed_demand_wh', 'essential_unserved_wh')},
        boot_work_seconds=_pack(work.boot_work_seconds), selected_steps=work.selected_steps,
        transitions=work.transitions, service_interruptions=work.service_interruptions,
        transition_reasons=[list(item) for item in work.transition_reasons])