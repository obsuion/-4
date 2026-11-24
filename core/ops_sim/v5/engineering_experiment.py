"""Bounded two-root engineering interventions; immutable hardware per run.

The comparison is output-only. Diagnosis or a forecast is never fed back as an
actual physics grant. A prudent forecast refusal may avoid an actual failure.
"""
from dataclasses import dataclass,replace,asdict
from .command_estimation import CommandRollingRoot
from .rolling_contract import RollingRoot,integer
from .rolling_physics import digest

METHOD='M6_TWO_ROOT_CONTROLLED_INTERVENTION_V1'


def actual_metrics(state):
    """Native returned physical parts and causal product assessment only."""
    from .ms_product import assess_ms_product
    p=state.physical;parts=[]
    for o in p.outcomes:
        parts.extend(c.part for c in o.cuts)
        for forcing in o.contact_forcing:
            for e in forcing.evaluations:
                if e.selected:parts.extend(e.parts)
    initial=state.root.initial_checkpoint.restore(state.root.model.simulation_inputs)
    assessments=tuple(assess_ms_product(r.product,p.acquisitions,p.context.ground_data_delivery_state,
        tuple(c for o in p.outcomes for c in o.contact_outcomes),p.context.simulation_time_seconds) for r in state.root.requests)
    weighted=sum(r.product.request.priority_weight for r,a in zip(state.root.requests,assessments) if a.status=='credited')
    temperatures={n.node_id.value:max([n.temperature_k]+[t.end_temperature_k for part in parts
        for t in part.thermal_coupling_result.thermal_result.node_transitions if t.node_id==n.node_id])
        for n in initial.spacecraft_state.thermal.node_states}
    return dict(status=state.status,clock=p.context.simulation_time_seconds,decisions=len(state.decisions),forecasts=state.work.forecast_invocations,
        acquired=len(p.acquisitions),receipts=len(p.context.ground_data_delivery_state.completed_deliveries),
        credited_products=sum(a.status=='credited' for a in assessments),
        priority_weighted_delivery_score=weighted/sum(r.product.request.priority_weight for r in state.root.requests),
        minimum_energy_wh=min([initial.spacecraft_state.battery.energy_wh]+[x.eps_result.battery.end_energy_wh for x in parts]),
        final_energy_wh=p.context.spacecraft_state.battery.energy_wh,
        wire_loss_wh=sum((x.electrical.pv_wire_loss_w+x.electrical.receiving_wire_loss_w)*x.eps_result.battery.dt_seconds/3600 for x in parts),
        unmet_load_wh=sum(x.eps_result.battery.unmet_load_w*x.eps_result.battery.dt_seconds/3600 for x in parts),
        maximum_temperature_k=temperatures,mass_properties=asdict(p.harness.hardware.mass_properties),
        added_harness_mass_kg=str(p.harness.hardware.augmentation.added_mass_exact_kg),
        actions=[dict(id=o.action_id,kind=o.kind,status=o.status,reason=o.reason,start=o.start_seconds,end=o.end_seconds,
            slew_seconds=None if o.slew is None else o.slew.duration_seconds) for o in p.outcomes])


@dataclass(frozen=True, slots=True)
class ExperimentContract:
    experiment_id: str
    baseline: object
    intervention: object
    hypothesis: str
    max_cases: int = 2
    max_total_decisions: int = 64
    max_total_forecasts: int = 512
    max_output_bytes: int = 256*2**20
    method: str = METHOD

    def __post_init__(self):
        from .assembly import _identity
        _identity(self.experiment_id,'experiment')
        if type(self.method) is not str or self.method!=METHOD or type(self.hypothesis) is not str or self.hypothesis not in ('COMMAND_ESTIMATION','PAYLOAD_WIRE_CROSS_SECTION','ASSEMBLY_PLACEMENT'):raise ValueError('bounded intervention identity')
        for n,cap in (('max_cases',2),('max_total_decisions',64),('max_total_forecasts',512),('max_output_bytes',256*2**20)):integer(getattr(self,n),n,1,cap)
        for root in (self.baseline,self.intervention):
            if type(root) not in (RollingRoot,CommandRollingRoot):raise TypeError('exact immutable root')
            root.__post_init__()
        if self.max_cases!=2 or any(r.policy.max_candidates>self.max_total_forecasts for r in (self.baseline,self.intervention)):raise ValueError('experiment prospective boundary admission')
        a,b=self.baseline,self.intervention
        # Every mission/world/information/priority rule remains common.
        for n in ('initial_checkpoint','initial_quaternion','requests','contacts','knowledge_mode','initial_estimate','policy','quotas'):
            if getattr(a,n)!=getattr(b,n):raise ValueError('INTERVENTION_CHANGED_COMMON_MISSION:'+n)
        if self.hypothesis=='COMMAND_ESTIMATION':
            if type(a) is not RollingRoot or type(b) is not CommandRollingRoot or b.reference!=a:raise ValueError('exact reference-to-opt-in policy intervention')
        else:
            if type(a) is not CommandRollingRoot or type(b) is not CommandRollingRoot or a.estimation!=b.estimation or a.controller_method!=b.controller_method:raise ValueError('same new common controller required')
            # B48-R2: meaningful declared edits plus exactly recomputed M1/M4
            # dependencies. A supplied digest is never a substitute for them.
            from .design_repair import validate_intervention
            validate_intervention(a,b,self.hypothesis)


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    method: str
    experiment_identity: str
    hypothesis: str
    baseline_root_identity: str
    intervention_root_identity: str
    baseline_scientific_identity: str
    intervention_scientific_identity: str
    differences: tuple
    interpretation: str


def compare_experiment(contract,baseline,intervention):
    if type(contract) is not ExperimentContract:raise TypeError('exact experiment contract')
    contract.__post_init__()
    from .rolling_execution import guard_rolling,paid_scientific_bytes
    for state,root in ((baseline,contract.baseline),(intervention,contract.intervention)):
        guard_rolling(state)
        if state.root!=root:raise ValueError('experiment foreign actual run')
    if sum(len(s.decisions) for s in (baseline,intervention))>contract.max_total_decisions or sum(s.work.forecast_invocations for s in (baseline,intervention))>contract.max_total_forecasts:raise ValueError('experiment returned total budget')
    # No selection call receives these assessments.
    a,b=actual_metrics(baseline),actual_metrics(intervention)
    fields=('status','clock','decisions','forecasts','acquired','receipts','credited_products','priority_weighted_delivery_score',
        'minimum_energy_wh','final_energy_wh','wire_loss_wh','unmet_load_wh','maximum_temperature_k','mass_properties','added_harness_mass_kg','actions')
    rows=tuple((n,a[n],b[n]) for n in fields)
    from hashlib import sha256
    # Hashing/export pays encoder/control work again; only canonical retention
    # can reuse exact bytes. No whole-history serialization is a free forecast.
    ids=tuple(sha256(paid_scientific_bytes(s)).hexdigest() for s in (baseline,intervention))
    result=ExperimentResult(METHOD,digest(contract),contract.hypothesis,baseline.root_identity,intervention.root_identity,
        *ids,rows,
        'Synthetic model-bound paired result. Resources must be interpreted with useful output; more final battery with no acquired product is not a hardware winner. Forecast avoidance is distinct from actual execution failure.')
    from .rolling_cache import canonical_size
    from .long_mission_continuation import _scientific
    canonical_size(_scientific(result),min(contract.max_output_bytes,2**20))
    from .rolling_cache import paid_publication
    paid_publication(result,baseline.work,baseline.root.quotas,min(contract.max_output_bytes,2**20))
    return result


def execute_experiment(contract):
    """Exactly two separately admitted actual roots; no mid-flight replacement."""
    contract.__post_init__()
    from .rolling_execution import start_rolling,step_rolling
    states=[];decisions=forecasts=0
    for root in (contract.baseline,contract.intervention):
        state=start_rolling(root)
        while state.status=='ACTIVE':
            # Reserve one complete candidate boundary BEFORE selection/model work.
            if decisions+1>contract.max_total_decisions or forecasts+root.policy.max_candidates>contract.max_total_forecasts:raise ValueError('EXPERIMENT_BOUNDARY_BUDGET_ADMISSION')
            before=state.work.forecast_invocations
            state=step_rolling(state);decisions+=1
            forecasts+=state.work.forecast_invocations-before
        states.append(state)
    states=tuple(states)
    return states,compare_experiment(contract,*states)
