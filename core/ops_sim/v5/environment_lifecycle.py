"""B61 selected physical transactions and received-only derived reporting."""
from dataclasses import dataclass,replace,asdict
from fractions import Fraction as Q
from .environment_ageing import (initial_state,guard,retention,propose,state_metrics,EnvironmentAgeingWork,digest)
from .environment_thermal import effective_network

def _guard_history(policy,history,baseline,clock,prepared):
    from .lifecycle_job_prepared import PreparedRoleState
    if type(prepared)is PreparedRoleState:
        prepared.guard_environment_history(policy,history,baseline,clock)
        return prepared
    guard(policy,history,baseline,clock)
    return None


def prepare_cut(physical,context,history,left,right,forcing):
    p=physical.inputs.environment_ageing_policy
    if p is None:return None,None
    baseline=context.inputs.spacecraft_configuration.thermal.network
    prepared=getattr(physical,'prepared_runtime',None)
    role=_guard_history(p,history,baseline,left,prepared)
    if context.spacecraft_state.degradation.solar.generation_retention!=retention(p,history):raise ValueError('B61 physical PV state/provenance mismatch')
    nxt=propose(p,history,baseline,Q(left),Q(right),forcing.sunlit,forcing.incidence_angle_deg,physical.environment_ageing_work,prepared_runtime=role)
    prepared=getattr(physical,'prepared_runtime',None)
    binding=(effective_network(p,history,baseline) if prepared is None else prepared.effective_environment(p,history,baseline),p,history)
    physical.environment_ageing_work.effective_networks+=1
    return binding,nxt

def commit_cut(context,policy,history):
    if policy is not None:context.spacecraft_state.degradation.solar.generation_retention=retention(policy,history)

def metrics(physical,context,history):
    if physical.inputs.environment_ageing_policy is None:return ()
    prepared=getattr(physical,'prepared_runtime',None)
    if prepared is not None:return prepared.environment_metrics(physical.inputs.environment_ageing_policy,history,context.inputs.spacecraft_configuration.thermal.network)
    return state_metrics(physical.inputs.environment_ageing_policy,history,context.inputs.spacecraft_configuration.thermal.network)

def _projection_data(policy,history,network,solar_retention,policy_identity,state_identity,network_identity):
    """Output shape shared by reference and prepared immutable realizations."""
    return dict(method=policy.method,assumption=policy.assumption,clock_seconds=str(history.clock_seconds),calendar_seconds=str(history.calendar_seconds),
        pv_exposure_seconds=history.pv_exposure_seconds,thermal_exposure_seconds=history.thermal_exposure_seconds,
        reference_solar_retention=history.reference_solar_retention,pv_retention=solar_retention,baseline_network_identity=history.baseline_network_identity,effective_network_identity=network_identity,
        policy_identity=policy_identity,state_identity=state_identity,selected_cuts=history.selected_cuts,
        emissivity={n.node_id.value:n.emissivity.value for n in network.nodes},conductance_w_per_k={l.link_id.value:l.conductance_w_per_k.value for l in network.links},
        exposure_scope='MIDPOINT_ADMITTED_INCIDENCE_START_HELD_POSE_EFFECTIVE_ILLUMINATION_SECONDS_NOT_RADIATION_DOSE',
        thermal_scope='PRESCRIBED_EXTERNAL_HEAT_ALPHA_UNMODELED_FIXED_C_AREA_MASS_THRESHOLDS')


def projection(policy,history,baseline,*,prepared_runtime=None):
    if history is None:return None
    if prepared_runtime is not None:
        from .lifecycle_prepared import PreparedRuntime
        from .lifecycle_job_prepared import PreparedRoleState
        if type(prepared_runtime)not in (PreparedRuntime,PreparedRoleState):raise TypeError('exact prepared projection runtime')
        return prepared_runtime.environment_projection(policy,history,baseline)
    guard(policy,history,baseline)
    e=effective_network(policy,history,baseline)
    solar=retention(policy,history);network_identity=digest(e.network)
    policy_identity=policy.identity;state_identity=digest(history)
    return _projection_data(policy,history,e.network,solar,policy_identity,state_identity,network_identity)

@dataclass(slots=True)
class EnvironmentPrivate:
    context: object
    history: object


def validate_projection(value,root,clock=None,*,prepared_runtime=None):
    from .environment_ageing import EnvironmentAgeingState
    from .lifecycle_document import canonical
    if type(value)is not dict:raise TypeError('B61 exact saved projection')
    try:
        state=EnvironmentAgeingState(Q(value['clock_seconds']),Q(value['calendar_seconds']),value['pv_exposure_seconds'],value['thermal_exposure_seconds'],value['reference_solar_retention'],value['policy_identity'],value['baseline_network_identity'],value['selected_cuts'])
    except (KeyError,TypeError,ValueError,ZeroDivisionError)as e:raise ValueError('B61 saved state shape')from e
    network=root.base.model.simulation_inputs.spacecraft_configuration.thermal.network
    expected=projection(root.environment_ageing_policy,state,network,prepared_runtime=prepared_runtime)
    if canonical(value)!=canonical(expected)or clock is not None and state.clock_seconds!=Q(clock):raise ValueError('B61 saved projection type/provenance/clock')
    if state.calendar_seconds!=Q(root.environment_ageing_policy.initial_calendar_seconds)+state.clock_seconds-root.start_seconds:raise ValueError('B61 saved elapsed calendar')
    return state

def validate_progress(value,root,clock):
    from .experiment_codec import object_fields
    from .environment_ageing import EnvironmentAgeingWork
    from dataclasses import fields
    object_fields(value,('actual','received','estimated','estimated_source','observed_at_seconds','actual_work','forecast_work'))
    validate_projection(value['actual'],root,clock)
    observed=value['observed_at_seconds']
    if type(observed)is not int or not root.start_seconds<=observed<=clock:raise ValueError('B61 received timestamp')
    validate_projection(value['received'],root,observed)
    if value['estimated']is not None:
        s=validate_projection(value['estimated'],root)
        origin=object_fields(value['estimated_source'],('state','received_at_seconds'))
        previous=validate_projection(origin['state'],root)
        received=Q(origin['received_at_seconds'])
        if type(origin['received_at_seconds'])is not str or str(received)!=origin['received_at_seconds']or not previous.clock_seconds<=received<=previous.clock_seconds+120 or received>clock or not previous.clock_seconds<=s.clock_seconds<=clock:raise ValueError('B61 last-paid forecast origin timestamp')
        if s.calendar_seconds<previous.calendar_seconds or s.pv_exposure_seconds<previous.pv_exposure_seconds or s.thermal_exposure_seconds<previous.thermal_exposure_seconds:raise ValueError('B61 negative forecast exposure from received origin')
    elif value['estimated_source']is not None:raise ValueError('B61 source without last-paid estimate')
    for key in ('actual_work','forecast_work'):
        data=object_fields(value[key],tuple(f.name for f in fields(EnvironmentAgeingWork)))
        EnvironmentAgeingWork(**data).validate(root.environment_ageing_policy)


@dataclass(frozen=True,slots=True)
class EnvironmentSolarTransition:
    start_generation_retention: float
    retention_loss: float
    end_generation_retention: float
    policy_identity: str
    before_state_identity: str
    after_state_identity: str
    def __post_init__(self):
        from .environment_ageing import finite
        finite(self.start_generation_retention,'PV transition start',1.e-24,1.)
        finite(self.end_generation_retention,'PV transition end',1.e-24,self.start_generation_retention)
        if type(self.retention_loss)not in (int,float)or self.retention_loss!=self.start_generation_retention-self.end_generation_retention:raise ValueError('B61 solar loss identity')
        for v in (self.policy_identity,self.before_state_identity,self.after_state_identity):
            if type(v)is not str or len(v)!=64 or any(c not in '0123456789abcdef'for c in v):raise ValueError('B61 solar transition provenance')

@dataclass(frozen=True,slots=True)
class EnvironmentCoupledResult:
    # Same explicit six physical result interfaces. Original pure leaves are
    # retained by identity; only the versioned PV transition has a new owner.
    eps_result: object
    thermal_coupling_result: object
    battery_degradation_result: object
    solar_degradation_result: EnvironmentSolarTransition
    eps_capability_result: object
    battery_capacity_reconciliation_result: object

def complete_cut(context,policy,before,after,part):
    if policy is None:return part
    if part.solar_degradation_result is not None:raise ValueError('B61 duplicate PV ageing owner')
    tr=EnvironmentSolarTransition(retention(policy,before),retention(policy,before)-retention(policy,after),retention(policy,after),policy.identity,digest(before),digest(after))
    if context.spacecraft_state.degradation.solar.generation_retention!=tr.start_generation_retention:raise ValueError('B61 start-held PV property')
    base=part.physical
    result=replace(part,physical=EnvironmentCoupledResult(base.eps_result,base.thermal_coupling_result,base.battery_degradation_result,tr,base.eps_capability_result,base.battery_capacity_reconciliation_result))
    commit_cut(context,policy,after)
    return result
