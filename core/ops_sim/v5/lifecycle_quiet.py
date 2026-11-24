"""B53 nominal quiet integration: paid Euler step doubling, selected fine path.

This owner contains no spacecraft physics. ``step`` calls the existing coupled
EPS/construction/thermal/ageing leaf once on private state. A macro proposal
compares one full step with two half steps; only the two-half path is selected.
The local estimate is not a rigorous enclosure or continuous protection proof.
"""
from dataclasses import dataclass, fields, replace
from fractions import Fraction as Q
from math import isfinite
from time import perf_counter_ns, process_time_ns

QUIET_METHOD = 'B53_PAID_QUIET_STEP_DOUBLING_V1'
SHORT_QUIET_METHOD = 'YEAR_V5_QUIET_SHORT_CIRCUIT_V1'
SHORT_BATTERY_QUIET_METHOD = 'YEAR_V5_PORT_QUIET_SHORT_CIRCUIT_V1'
SHORT_ENVIRONMENT_QUIET_METHOD = 'YEAR_V5_ENVIRONMENT_QUIET_SHORT_CIRCUIT_V1'
SHORT_QUIET_METHODS = (SHORT_QUIET_METHOD, SHORT_BATTERY_QUIET_METHOD, SHORT_ENVIRONMENT_QUIET_METHOD)


def _integer(value, name, low=0, high=2**48):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('quiet strict integer: '+name)


def _positive(value, name):
    try:admitted=type(value) in (int,float) and isfinite(value) and value>0
    except OverflowError:admitted=False
    if not admitted:raise ValueError('quiet positive finite value: '+name)


@dataclass(frozen=True, slots=True)
class QuietIntegrationPolicy:
    """Explicit local nominal error policy; every field participates in identity.

    Absolute tolerances have their named physical units. Relative tolerance and
    retention/damage are dimensionless. The selected two-half Euler trajectory
    has first-order local estimator |fine-full| (2**1-1 = 1).
    """
    minimum_macro_seconds: int = 4
    maximum_macro_seconds: int = 60
    detailed_seconds: int = 2
    absolute_energy_wh: float = 0.00002
    absolute_temperature_k: float = 0.002
    absolute_retention: float = 1.e-9
    relative_tolerance: float = 1.e-7
    guard_temperature_margin_k: float = 0.25
    guard_energy_margin_wh: float = 0.02
    max_trials_per_interval: int = 256
    max_selected_parts: int = 512
    max_total_leaf_calls: int = 2**34
    method: str = QUIET_METHOD

    def __post_init__(self):
        for name in ('minimum_macro_seconds', 'maximum_macro_seconds', 'detailed_seconds',
                     'max_trials_per_interval', 'max_selected_parts', 'max_total_leaf_calls'):
            _integer(getattr(self, name), name, 1)
        for name in ('absolute_energy_wh', 'absolute_temperature_k', 'absolute_retention',
                     'relative_tolerance', 'guard_temperature_margin_k', 'guard_energy_margin_wh'):
            _positive(getattr(self, name), name)
        if (type(self.method) is not str or self.method not in (QUIET_METHOD, SHORT_QUIET_METHOD) or
                not 2*self.detailed_seconds <= self.minimum_macro_seconds <=
                self.maximum_macro_seconds <= 120 or self.detailed_seconds > 2 or
                self.max_trials_per_interval > 4096 or self.max_selected_parts > 512):
            raise ValueError('unsupported finite quiet numerical policy')


BATTERY_QUIET_METHOD = 'B58_UNIT_AWARE_PORT_QUIET_V1'

@dataclass(frozen=True, slots=True)
class BatteryQuietIntegrationPolicy(QuietIntegrationPolicy):
    absolute_voltage_v: float = .01
    absolute_current_a: float = .001
    absolute_resistance_ohm: float = .00001
    absolute_resistance_damage: float = 1.e-8
    absolute_weighted_seconds: float = .01
    method: str = BATTERY_QUIET_METHOD
    def __post_init__(self):
        QuietIntegrationPolicy(**{f.name:(QUIET_METHOD if f.name=='method' else getattr(self,f.name)) for f in fields(QuietIntegrationPolicy)})
        if type(self.method)is not str or self.method not in (BATTERY_QUIET_METHOD, SHORT_BATTERY_QUIET_METHOD):raise ValueError('B58 quiet method')
        for name in ('absolute_voltage_v','absolute_current_a','absolute_resistance_ohm','absolute_resistance_damage','absolute_weighted_seconds'):_positive(getattr(self,name),name)

ENVIRONMENT_QUIET_METHOD='B61_UNIT_AWARE_ENVIRONMENT_QUIET_V1'
@dataclass(frozen=True,slots=True)
class EnvironmentQuietIntegrationPolicy(BatteryQuietIntegrationPolicy):
    absolute_exposure_seconds: float=.01
    absolute_emissivity: float=1.e-8
    absolute_conductance_w_per_k: float=1.e-7
    method: str=ENVIRONMENT_QUIET_METHOD
    def __post_init__(self):
        BatteryQuietIntegrationPolicy(**{f.name:(BATTERY_QUIET_METHOD if f.name=='method' else getattr(self,f.name))for f in fields(BatteryQuietIntegrationPolicy)})
        if type(self.method)is not str or self.method not in (ENVIRONMENT_QUIET_METHOD, SHORT_ENVIRONMENT_QUIET_METHOD):raise ValueError('B61 quiet equation version')
        for n in ('absolute_exposure_seconds','absolute_emissivity','absolute_conductance_w_per_k'):_positive(getattr(self,n),n)

@dataclass(frozen=True, slots=True)
class QuietControllerState:
    clock_seconds: Q
    next_step_seconds: int
    last_step_seconds: Q = Q(0)
    last_error_norm: float = 0.
    phase: str = 'INITIAL'
    method: str = QUIET_METHOD

    def validate(self, policy, *, clock=None):
        policy.__post_init__()
        if (type(self.clock_seconds) is not Q or self.clock_seconds < 0 or
                type(self.last_step_seconds) is not Q or self.last_step_seconds < 0):
            raise ValueError('quiet exact clocks required')
        _integer(self.next_step_seconds, 'next proposal', policy.minimum_macro_seconds,
                 policy.maximum_macro_seconds)
        if (type(self.last_error_norm) not in (int, float) or not isfinite(self.last_error_norm) or
                self.last_error_norm < 0 or self.last_step_seconds > policy.maximum_macro_seconds or
                type(self.phase) is not str or
                self.phase not in ('INITIAL', 'ACCEPTED', 'DETAILED_FALLBACK', 'DETAILED_ACTION') or
                type(self.method) is not str or self.method != policy.method or
                clock is not None and self.clock_seconds != Q(clock)):
            raise ValueError('invalid/stale quiet controller')


@dataclass(slots=True)
class QuietWork:
    """Cumulative, nonrefundable actual OR forecast work, never both aliases."""
    proposed_macros: int = 0
    accepted_macros: int = 0
    rejected_macros: int = 0
    reserved_leaf_calls: int = 0
    returned_leaf_calls: int = 0
    refused_leaf_calls: int = 0
    unknown_leaf_calls: int = 0
    full_trial_calls: int = 0
    half_trial_calls: int = 0
    detailed_fallback_calls: int = 0
    selected_parts: int = 0
    selected_seconds: Q = Q(0)
    committed_parts: int = 0
    committed_seconds: Q = Q(0)
    maximum_accepted_error_norm: float = 0.
    selected_step_le_1: int = 0
    selected_step_le_2: int = 0
    selected_step_le_4: int = 0
    selected_step_le_8: int = 0
    selected_step_le_16: int = 0
    selected_step_le_32: int = 0
    selected_step_gt_32: int = 0

    def validate(self, policy):
        for field in fields(QuietWork):
            if field.name not in ('selected_seconds', 'committed_seconds', 'maximum_accepted_error_norm'):
                _integer(getattr(self, field.name), field.name)
        if any(type(x) is not Q or x < 0 for x in (self.selected_seconds, self.committed_seconds)):
            raise ValueError('quiet selected duration must be exact/nonnegative')
        if (type(self.maximum_accepted_error_norm) not in (int, float) or
                not isfinite(self.maximum_accepted_error_norm) or not 0 <= self.maximum_accepted_error_norm <= 1):
            raise ValueError('quiet accepted local error record outside admission')
        if (self.reserved_leaf_calls > policy.max_total_leaf_calls or
                self.returned_leaf_calls+self.refused_leaf_calls+self.unknown_leaf_calls != self.reserved_leaf_calls or
                self.full_trial_calls+self.half_trial_calls+self.detailed_fallback_calls != self.reserved_leaf_calls or
                self.accepted_macros+self.rejected_macros > self.proposed_macros or
                self.committed_parts > self.selected_parts or self.committed_seconds > self.selected_seconds or
                sum(getattr(self, f.name) for f in fields(self) if f.name.startswith('selected_step_')) != self.selected_parts):
            raise ValueError('quiet work accounting mismatch')

    def reserve(self, kind, policy):
        if type(kind) is not str or kind not in ('full_trial', 'half_trial', 'detailed_fallback'):
            raise ValueError('strict quiet reservation kind required')
        self.validate(policy)
        if self.reserved_leaf_calls >= policy.max_total_leaf_calls:
            raise ValueError('QUIET_CUMULATIVE_LEAF_QUOTA')
        self.reserved_leaf_calls += 1
        setattr(self, kind+'_calls', getattr(self, kind+'_calls')+1)

    def select(self, duration):
        self.selected_parts += 1
        self.selected_seconds += duration
        for bound in (1, 2, 4, 8, 16, 32):
            if duration <= bound:
                name = 'selected_step_le_'+str(bound)
                break
        else: name = 'selected_step_gt_32'
        setattr(self, name, getattr(self, name)+1)


@dataclass(slots=True)
class ShortCircuitQuietWork(QuietWork):
    """V5 deterministic work, with no charge for unperformed half trials.

    The distinct fixed graph record and explicit policy method are persistent.
    Clock measurements are deliberately NOT persistent scientific work.
    """
    first_half_calls: int = 0
    second_half_calls: int = 0
    skipped_half_trial_calls: int = 0
    early_full_near: int = 0
    early_first_near: int = 0
    early_first_regime: int = 0
    full_near_guard: int = 0
    first_near_guard: int = 0
    second_near_guard: int = 0
    full_first_regime_mismatch: int = 0
    full_second_regime_mismatch: int = 0
    first_second_regime_mismatch: int = 0
    norm_evaluations: int = 0
    norm_rejections: int = 0
    norm_not_evaluated_early: int = 0
    minimum_macro_proposals: int = 0
    shortened_boundary_proposals: int = 0
    below_minimum_fallbacks: int = 0
    minimum_macro_fallbacks: int = 0

    def validate(self, policy):
        QuietWork.validate(self, policy)
        if type(policy.method) is not str or policy.method not in SHORT_QUIET_METHODS:
            raise ValueError('V5 work requires explicit short-circuit policy')
        for field in fields(ShortCircuitQuietWork):
            if field.name not in QuietWork.__dataclass_fields__:
                _integer(getattr(self, field.name), field.name)
        if (self.first_half_calls+self.second_half_calls != self.half_trial_calls or
                self.second_half_calls > self.first_half_calls or
                self.skipped_half_trial_calls != 2*self.early_full_near+self.early_first_near+self.early_first_regime or
                self.norm_not_evaluated_early != self.early_full_near+self.early_first_near+self.early_first_regime or
                self.norm_rejections > self.norm_evaluations):
            raise ValueError('V5 performed/skipped quiet accounting mismatch')

    def performed(self, stage):
        if stage == 'first':self.first_half_calls += 1
        elif stage == 'second':self.second_half_calls += 1
        elif stage not in ('full', 'detailed'):raise ValueError('V5 exact quiet stage')

    def early(self, reason):
        if reason == 'full_near':self.early_full_near += 1; skipped = 2
        elif reason == 'first_near':self.early_first_near += 1; skipped = 1
        elif reason == 'first_regime':self.early_first_regime += 1; skipped = 1
        else:raise ValueError('V5 exact early rejection reason')
        self.skipped_half_trial_calls += skipped
        self.norm_not_evaluated_early += 1


def is_short_circuit_policy(policy):
    return type(policy) in (QuietIntegrationPolicy, BatteryQuietIntegrationPolicy, EnvironmentQuietIntegrationPolicy) and policy.method in SHORT_QUIET_METHODS


def short_circuit_policy(policy):
    """Explicit opt-in; every physical/numerical field except method is retained."""
    if type(policy) not in (QuietIntegrationPolicy, BatteryQuietIntegrationPolicy, EnvironmentQuietIntegrationPolicy):
        raise TypeError('exact supported quiet policy required')
    policy.__post_init__()
    method = {QuietIntegrationPolicy:SHORT_QUIET_METHOD,
        BatteryQuietIntegrationPolicy:SHORT_BATTERY_QUIET_METHOD,
        EnvironmentQuietIntegrationPolicy:SHORT_ENVIRONMENT_QUIET_METHOD}[type(policy)]
    return replace(policy, method=method)


def quiet_work_type(policy):
    policy.__post_init__()
    return ShortCircuitQuietWork if is_short_circuit_policy(policy) else QuietWork


def quiet_work_for(policy):
    return quiet_work_type(policy)()


@dataclass(frozen=True, slots=True)
class QuietSample:
    state_values: tuple
    integrals: tuple
    regime: tuple
    near_guard: bool = False

    def __post_init__(self):
        for values in (self.state_values, self.integrals):
            if type(values) is not tuple or not values or len(values) > 128:
                raise ValueError('bounded quiet metric vector required')
            keys = []
            for key, value in values:
                if (type(key) is not str or not key or len(key) > 200 or
                        type(value) not in (int, float) or not isfinite(value)):
                    raise ValueError('finite named quiet metric required')
                keys.append(key)
            if len(set(keys)) != len(keys): raise ValueError('duplicate quiet metric')
        if (type(self.regime) is not tuple or len(self.regime) > 32 or
                any(type(x) not in (str, int, bool) for x in self.regime) or type(self.near_guard) is not bool):
            raise ValueError('bounded exact quiet regime required')


@dataclass(frozen=True, slots=True)
class QuietTrial:
    context: object
    cut: object
    sample: QuietSample


@dataclass(frozen=True, slots=True)
class QuietIntegrationResult:
    context: object
    cuts: tuple
    controller: QuietControllerState
    maximum_accepted_error_norm: float


class QuietTrialRefusal(Exception):
    """Known paid physical refusal; rejected proposals are not actual state."""
    def __init__(self, original):
        super().__init__(str(original)); self.original = original


def _scale(name, policy):
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


_REASON_LIMIT_V5 = 2**63-1
_REASON_ROLES_V5 = ('ACTUAL', 'FORECAST', 'REFERENCE')
_REASONS_V5 = {role:dict(counts={},dominant_components={},known_refusals={},saturated=False) for role in _REASON_ROLES_V5}


def _reason_v5(role, name, count=1):
    """Bounded nonauthoritative aggregate; saturation never changes physics."""
    if role not in _REASON_ROLES_V5:role = 'REFERENCE'
    row = _REASONS_V5[role]
    if type(name) is not str or len(name)>240 or type(count) is not int or count<0:
        row['saturated']=True;return
    values=row['counts']
    if name not in values and len(values)>=128:row['saturated']=True;return
    result=values.get(name,0)+count
    if result>_REASON_LIMIT_V5:row['saturated']=True;result=_REASON_LIMIT_V5
    values[name]=result


def _reason_named_v5(role, field, name):
    if role not in _REASON_ROLES_V5:role='REFERENCE'
    row=_REASONS_V5[role];values=row[field]
    if type(name) is not str or not name or len(name)>240 or name not in values and len(values)>=256:
        row['saturated']=True;return
    result=values.get(name,0)+1
    if result>_REASON_LIMIT_V5:row['saturated']=True;result=_REASON_LIMIT_V5
    values[name]=result


def _reason_begin_v5(role, kind):
    _reason_v5(role, kind+'_performed')
    return perf_counter_ns(),process_time_ns()


def _reason_end_v5(role, kind, before, outcome):
    _reason_v5(role,kind+'_wall_ns',max(0,perf_counter_ns()-before[0]))
    _reason_v5(role,kind+'_worker_CPU_ns',max(0,process_time_ns()-before[1]))
    _reason_v5(role,kind+'_'+outcome)


def _reason_sample_v5(role, stage, sample, work):
    near = sample.near_guard if type(sample) is QuietSample else sample['near_guard']
    if near:
        _reason_v5(role,stage+'_near_guard')
        if type(work) is ShortCircuitQuietWork:setattr(work,stage+'_near_guard',getattr(work,stage+'_near_guard')+1)
    if type(sample) is dict:
        for reason in sample.get('near_reasons',()):_reason_v5(role,stage+'_near_reason:'+reason)
        regime=sample['regime']
        if len(regime)==12:
            if regime[2]:_reason_v5(role,stage+'_context_curtailment_present')
            _reason_v5(role,stage+'_context_mode:'+regime[6])
            _reason_v5(role,stage+'_context_allocation_reason:'+regime[9])


def _reason_regime_v5(role, left, right, left_sample, right_sample, work):
    a=left_sample.regime if type(left_sample) is QuietSample else left_sample['regime']
    b=right_sample.regime if type(right_sample) is QuietSample else right_sample['regime']
    mismatch=a!=b
    if mismatch:
        name=left+'_'+right+'_regime_mismatch';_reason_v5(role,name)
        if type(work) is ShortCircuitQuietWork:setattr(work,name,getattr(work,name)+1)
    return mismatch


def quiet_reason_counts_v5():
    """Read-only process totals, not checkpoint work or execution permission.

    At most3 roles,128 scalar keys and256 component/refusal keys per role;
    names<=240 characters and counters<=2**63-1 bound the export below2MiB.
    Costs are per performed leaf kind; nested costs are not additive.
    """
    return dict(format='YEAR_V5_QUIET_REASON_AGGREGATES_V1',scope='PROCESS_LOCAL_DIAGNOSTIC_NOT_SCIENTIFIC_WORK',
        roles={role:dict(counts=dict(sorted(row['counts'].items())),dominant_components=dict(sorted(row['dominant_components'].items())),
            known_refusals=dict(sorted(row['known_refusals'].items())),saturated=row['saturated'])for role,row in _REASONS_V5.items()},
        priority='full_near > first_near > first_regime for early rejection; measured reason flags may overlap',
        timing_boundary='After performed-leaf reservation/stage accounting through returned-sample validation; excludes clone, reservation and macro-decision work. Performed leaf calls are sequential, not total worker cost.',
        context_curtailment='Presence in a measured sample is not attribution of near_guard or rejection cause.',
        skipped_error_norm='NOT_MEASURED',maximum_export_bytes=2*2**20,reset_available=False)


def _quiet_initial_metrics_v5(initial_values, policy):
    if type(initial_values) is not tuple or not initial_values or len(initial_values)>128:
        raise ValueError('bounded complete quiet initial metric vector required')
    keys=[]
    for name,value in initial_values:
        if type(name) is not str or not name or len(name)>200 or type(value) not in (int,float) or not isfinite(value):
            raise ValueError('finite exact initial quiet metric required')
        _positive(_scale(name,policy),'initial metric unit')
        keys.append(name)
    if len(set(keys))!=len(keys):raise ValueError('duplicate initial quiet metric')
    return tuple(keys)


def _quiet_complete_sample_v5(initial_values, sample, policy, integral_names=None):
    """Pre-skip mandatory full schema/order/units; never evaluate a missing leaf."""
    names=_quiet_initial_metrics_v5(initial_values,policy)
    if type(sample) is QuietSample:
        sample.__post_init__();states=sample.state_values;integrals=sample.integrals
    elif type(sample) is dict:
        QuietSample(sample['state_values'],sample['integrals'],sample['regime'],sample['near_guard']).__post_init__()
        states=sample['state_values'];integrals=sample['integrals']
    else:raise TypeError('exact complete quiet sample required')
    if tuple(k for k,v in states)!=names or integral_names is not None and tuple(k for k,v in integrals)!=integral_names:
        raise ValueError('quiet metric authority/order changed before short-circuit')
    for name,value in (*states,*integrals):_positive(_scale(name,policy),'sample metric unit')
    return tuple(k for k,v in integrals)


def quiet_error_norm(initial_values, full, first_half, second_half, policy, *, reason_role='REFERENCE'):
    """Infinity norm over every physical state and every selected-path integral."""
    for sample in (full, first_half, second_half): sample.__post_init__()
    start = dict(initial_values)
    if (tuple(k for k, _ in full.state_values) != tuple(start) or
            tuple(k for k, _ in full.state_values) != tuple(k for k, _ in second_half.state_values) or
            tuple(k for k, _ in first_half.state_values) != tuple(start) or
            tuple(k for k, _ in full.integrals) != tuple(k for k, _ in first_half.integrals) or
            tuple(k for k, _ in full.integrals) != tuple(k for k, _ in second_half.integrals)):
        raise ValueError('quiet metric authority/order changed')
    errors = []; names=[]
    for (name, coarse), (_, fine) in zip(full.state_values, second_half.state_values):
        scale = _scale(name, policy)+policy.relative_tolerance*max(abs(start[name]), abs(coarse), abs(fine))
        errors.append(abs(fine-coarse)/scale)
        names.append('STATE:'+name)
    for (name, coarse), (_, h1), (_, h2) in zip(full.integrals, first_half.integrals, second_half.integrals):
        fine = h1+h2
        scale = _scale(name, policy)+policy.relative_tolerance*max(abs(coarse), abs(fine))
        errors.append(abs(fine-coarse)/scale)
        names.append('INTEGRAL:'+name)
    result = max(errors)
    if not isfinite(result): raise ValueError('quiet nonfinite error norm')
    _reason_v5(reason_role,'norm_evaluations')
    if result>1:
        _reason_v5(reason_role,'error_norm_above_one')
        _reason_named_v5(reason_role,'dominant_components',names[errors.index(result)])
    return result


def integrate_quiet_hold(context, start, end, *, policy, controller, work,
                         clone_context, state_values, step, reason_role='REFERENCE'):
    """One bounded interval. V5 rejects only after complete performed samples.

    Callback owner retains all initial physical/schema checks. This owner adds
    initial metric/order/unit checks before any V5 early rejection. It does not
    claim equivalence of errors in halves that the new method does not perform.
    """
    if (type(policy) not in (QuietIntegrationPolicy, BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy)
            or type(controller) is not QuietControllerState or type(work) is not quiet_work_type(policy)):
        raise TypeError('explicit matching quiet policy/controller/work required')
    short=is_short_circuit_policy(policy)
    start, end = Q(start), Q(end)
    controller.validate(policy, clock=start); work.validate(policy)
    if end <= start or end-start > 120: raise ValueError('bounded advancing quiet interval required')
    selected = []; current = context; clock = start; proposal = controller.next_step_seconds
    attempts = 0; max_error = 0.; last_error = controller.last_error_norm
    last_step = Q(0); phase = controller.phase

    def call(origin, left, right, kind, stage):
        work.reserve(kind, policy)
        if short:work.performed(stage)
        before=_reason_begin_v5(reason_role,kind);outcome='unexpected_error'
        try:
            try: result = step(origin, left, right)
            except QuietTrialRefusal as error:
                work.refused_leaf_calls += 1;outcome='known_refusal'
                _reason_named_v5(reason_role,'known_refusals',getattr(error.original,'reason',type(error.original).__name__))
                raise
            except BaseException:
                work.unknown_leaf_calls += 1
                raise
            work.returned_leaf_calls += 1
            if type(result) is not QuietTrial or type(result.sample) is not QuietSample:
                raise TypeError('exact complete quiet trial required')
            result.sample.__post_init__();outcome='returned'
            return result
        finally:_reason_end_v5(reason_role,kind,before,outcome)

    while clock < end:
        remaining = end-clock;h = min(Q(proposal), remaining)
        if h<proposal:
            _reason_v5(reason_role,'shortened_boundary_proposals')
            if short:work.shortened_boundary_proposals+=1
        if h < policy.minimum_macro_seconds:
            _reason_v5(reason_role,'below_minimum_fallbacks')
            if short:work.below_minimum_fallbacks+=1
            h = min(remaining, Q(policy.detailed_seconds))
            trial = call(clone_context(current), clock, clock+h, 'detailed_fallback','detailed')
            selected.append(trial.cut); work.select(h)
            current = trial.context; clock += h; last_step = h; phase = 'DETAILED_FALLBACK'
        else:
            attempts += 1
            if attempts > policy.max_trials_per_interval:raise ValueError('QUIET_LOCAL_TRIAL_QUOTA')
            work.proposed_macros += 1
            if h==policy.minimum_macro_seconds:
                _reason_v5(reason_role,'minimum_macro_proposals')
                if short:work.minimum_macro_proposals+=1
            initial = state_values(current)
            if short:_quiet_initial_metrics_v5(initial,policy)
            try:
                full = call(clone_context(current), clock, clock+h, 'full_trial','full')
                _reason_sample_v5(reason_role,'full',full.sample,work)
                if short:integral_names=_quiet_complete_sample_v5(initial,full.sample,policy)
                if short and full.sample.near_guard:
                    work.early('full_near');_reason_v5(reason_role,'early_full_near');_reason_v5(reason_role,'skipped_half_trials',2)
                    admissible=False
                else:
                    first = call(clone_context(current), clock, clock+h/2, 'half_trial','first')
                    if short:_quiet_complete_sample_v5(initial,first.sample,policy,integral_names)
                    _reason_sample_v5(reason_role,'first',first.sample,work)
                    mismatch=_reason_regime_v5(reason_role,'full','first',full.sample,first.sample,work)
                    if short and (first.sample.near_guard or mismatch):
                        why='first_near'if first.sample.near_guard else'first_regime'
                        work.early(why);_reason_v5(reason_role,'early_'+why);_reason_v5(reason_role,'skipped_half_trials')
                        admissible=False
                    else:
                        second = call(first.context, clock+h/2, clock+h, 'half_trial','second')
                        if short:_quiet_complete_sample_v5(initial,second.sample,policy,integral_names)
                        _reason_sample_v5(reason_role,'second',second.sample,work)
                        _reason_regime_v5(reason_role,'full','second',full.sample,second.sample,work)
                        _reason_regime_v5(reason_role,'first','second',first.sample,second.sample,work)
                        error = quiet_error_norm(initial, full.sample, first.sample, second.sample, policy,reason_role=reason_role)
                        if short:work.norm_evaluations+=1;work.norm_rejections+=int(error>1.)
                        admissible = (full.sample.regime == first.sample.regime == second.sample.regime and
                            not any(x.near_guard for x in (full.sample, first.sample, second.sample)) and error <= 1.)
            except QuietTrialRefusal:
                work.rejected_macros += 1
                if h <= policy.minimum_macro_seconds:
                    proposal = policy.minimum_macro_seconds;h = min(remaining, Q(policy.detailed_seconds))
                    _reason_v5(reason_role,'minimum_macro_fallbacks')
                    if short:work.minimum_macro_fallbacks+=1
                    trial = call(clone_context(current), clock, clock+h, 'detailed_fallback','detailed')
                    selected.append(trial.cut); work.select(h)
                    current = trial.context; clock += h; last_step = h; phase = 'DETAILED_FALLBACK'
                else: proposal = max(policy.minimum_macro_seconds, int(h)//2)
                if len(selected) > policy.max_selected_parts:raise ValueError('QUIET_SELECTED_EVIDENCE_QUOTA')
                continue
            if not admissible:
                work.rejected_macros += 1
                if h > policy.minimum_macro_seconds:
                    proposal = max(policy.minimum_macro_seconds, int(h)//2);continue
                _reason_v5(reason_role,'minimum_macro_fallbacks')
                if short:work.minimum_macro_fallbacks+=1
                trial = call(clone_context(current), clock, clock+min(remaining,Q(policy.detailed_seconds)), 'detailed_fallback','detailed')
                duration = min(remaining, Q(policy.detailed_seconds));selected.append(trial.cut); work.select(duration)
                current = trial.context; clock += duration; last_step = duration; phase = 'DETAILED_FALLBACK';proposal=policy.minimum_macro_seconds
            else:
                work.accepted_macros += 1;selected.extend((first.cut,second.cut));work.select(h/2);work.select(h/2)
                current=second.context;clock+=h;last_step=h;last_error=error;max_error=max(max_error,error);phase='ACCEPTED'
                work.maximum_accepted_error_norm=max(work.maximum_accepted_error_norm,error)
                if error<=.25:proposal=min(policy.maximum_macro_seconds,max(proposal,int(h)*2))
        if len(selected)>policy.max_selected_parts:raise ValueError('QUIET_SELECTED_EVIDENCE_QUOTA')
    next_controller=QuietControllerState(end,proposal,last_step,last_error,phase,policy.method)
    next_controller.validate(policy,clock=end);work.validate(policy)
    return QuietIntegrationResult(current,tuple(selected),next_controller,max_error)
