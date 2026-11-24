"""B62 original-input derivation and explicit finite accounting admission.

A duration is not lived history or a certificate of numerical affordability.
All original physical fields are retained; accounting changes are a distinct
subsequent derivation, with an explicit named contract and before/after hashes.
"""
from dataclasses import dataclass,asdict,replace
from copy import deepcopy
from hashlib import sha256
from fractions import Fraction
import json
from .lifecycle_document import loads_root,dumps_root,canonical,FORMAT61
from .lifecycle_contract import MAX_DURATION,MONTH,integer

DERIVATION='B62_FRESH_V7_DURATION_DERIVATION_V1'
ACCOUNTING='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'

def digest(raw):return sha256(raw).hexdigest()

def _initial(raw):
    if type(raw)is not bytes or not 0<len(raw)<=8*2**20:raise ValueError('B62 bounded original input bytes')
    # BOM is transport only; never part of a digest/canonical owner document.
    canonical_raw=raw[3:]if raw.startswith(b'\xef\xbb\xbf')else raw
    root=loads_root(canonical_raw)
    document=json.loads(canonical_raw)
    if document['format']!=FORMAT61 or root.environment_ageing_policy is None:raise ValueError('B62 genuine B61 V7 input required')
    if dumps_root(root)!=canonical_raw:raise ValueError('B62 canonical owner roundtrip required')
    original_anchor=root.base.model.environment.trajectory.initial_state.position.instant.elapsed_seconds
    if Fraction(root.start_seconds)!=original_anchor:raise ValueError('B62 fresh original-anchor input, never advanced native')
    return root,document,canonical_raw

def derive_duration(raw,duration_seconds):
    integer(duration_seconds,'B62 duration',1,MAX_DURATION)
    old,document,original=_initial(raw)
    updated=deepcopy(document);updated['inputs']['duration_seconds']=duration_seconds
    body={k:updated[k]for k in ('format','version','inputs')};updated['digest']=digest(canonical(body).encode('utf8'))
    encoded=canonical(updated).encode('utf8');root=loads_root(encoded)
    if dumps_root(root)!=encoded:raise ValueError('B62 derived owner roundtrip')
    pre=deepcopy(document);post=deepcopy(updated)
    pre['inputs'].pop('duration_seconds');post['inputs'].pop('duration_seconds');pre.pop('digest');post.pop('digest')
    if pre!=post:raise ValueError('B62 duration changed nested physical authority')
    return root,encoded,dict(format=DERIVATION,original_raw_sha256=digest(raw),original_canonical_sha256=digest(original),original_root_identity=old.identity,derived_sha256=digest(encoded),derived_root_identity=root.identity,changed_fields=['inputs.duration_seconds','digest'],original_anchor_seconds=root.start_seconds,duration_seconds=duration_seconds,target_seconds=root.end_seconds,full_30day_buckets=duration_seconds//MONTH,terminal_bucket_seconds=duration_seconds%MONTH,initial_ageing='Original declared initial assumptions preserved; new horizon is not lived exposure',canonical_owner_roundtrip=True)


def physical_overrides(root):
    if root.policy.method!=ACCOUNTING:return {}
    # Only cumulative allowances change. Local action cells, RK4/quiet grids,
    # tolerances, retained state and all physical models remain unchanged.
    return dict(max_actions=2**42,max_physical_substeps=2**48,
        max_runtime_upstream_entries=2**42,max_runtime_entries=2**42,
        max_nominal_orbit_queries=2**40,max_point_geometry_queries=2**40,
        max_spatial_reserved_units=2**48,max_nominal_force_reserved=2**40,
        max_nominal_control_units=2**48,max_index_control_units=2**48,
        max_output_control_units=2**48,max_construction_line_calls=2**48,
        max_construction_compilations=2**42,max_construction_control_units=2**48,
        max_harness_compilations=2**42,max_harness_control_units=2**48)


def derive_accounting(raw):
    old,document,original=_initial(raw)
    if old.policy.method==ACCOUNTING:raise ValueError('B62 accounting already derived')
    quiet=old.policy.quiet_solver
    if quiet is None:raise ValueError('B62 explicit quiet numerical policy required')
    policy=replace(old.policy,method=ACCOUNTING,max_transitions=2**32,
        max_controller_decisions=2**32,max_control_units=2**52,
        max_forecast_transitions=2**48,
        quiet_solver=replace(quiet,max_total_leaf_calls=2**48))
    from .environment_ageing import ACCOUNTING_LAW
    environment=replace(old.environment_ageing_policy,method=ACCOUNTING_LAW,maximum_proposals=2**48)
    root=replace(old,policy=policy,environment_ageing_policy=environment)
    encoded=dumps_root(root)
    if dumps_root(loads_root(encoded))!=encoded:raise ValueError('B62 accounting owner roundtrip')
    # Test the exact field delta, including nested quiet policy. No numerical
    # value, initial exposure, provenance or physical coefficient is rewritten.
    pre=json.loads(original);post=json.loads(encoded)
    changes=[]
    def walk(a,b,path=''):
        if type(a)is dict and type(b)is dict and set(a)==set(b):
            for k in a:walk(a[k],b[k],path+'.'+k if path else k)
        elif a!=b:changes.append(path)
    walk(pre,post)
    allowed={'digest','inputs.policy.method','inputs.policy.max_transitions',
        'inputs.policy.max_controller_decisions','inputs.policy.max_control_units',
        'inputs.policy.max_forecast_transitions','inputs.policy.quiet_solver.max_total_leaf_calls',
        'inputs.environment_ageing_policy.method','inputs.environment_ageing_policy.maximum_proposals'}
    if set(changes)-allowed:raise ValueError('B62 unexpected accounting delta: '+repr(changes))
    return root,encoded,dict(format=ACCOUNTING,original_input_sha256=digest(raw),
        derived_input_sha256=digest(encoded),changed_fields=sorted(changes),
        physical_fields='UNCHANGED',quota_completion_proof=False,resource_plan=resource_plan(root))


def resource_plan(root):
    """Auditable finite reservations, explicitly conditional horizon screening.

    The integer-second frontier and one instant solar command per advancing
    transaction are a workload planning condition, not a proven lower bound on
    every future accepted action. Runtime guards remain authoritative.
    """
    if root.policy.method!=ACCOUNTING:raise ValueError('B62 accounting input required')
    from .lifecycle_physics import LifecyclePhysicsLimits
    from .lifecycle_orbit import LifecycleOrbitPolicy
    p=root.policy;d=root.duration_seconds;q=p.quiet_solver
    limits=LifecyclePhysicsLimits(max_interval_seconds=p.quiet_step_seconds,
        detailed_interval_seconds=p.detailed_step_seconds,
        contact_integration_level=p.contact_integration_level,
        max_active_products=p.active_requests,**physical_overrides(root))
    orbit=LifecycleOrbitPolicy(max_duration_seconds=d,max_queries=2**40,
        max_force_reservations=2**40,max_control_units=2**48)
    transitions=2*(d+root.offered_population+1)
    forecast=transitions*(2*((p.maximum_observation_age_seconds+p.detailed_step_seconds-1)//p.detailed_step_seconds)+4)
    # integrate_quiet_hold: each full/two-half trial reserves three leaves;
    # fallback at most max_selected_parts. Per-interval bounds are unchanged.
    leaves_per_interval=3*q.max_trials_per_interval+q.max_selected_parts
    rows=[('actual transitions',transitions,p.max_transitions),
        ('controller decisions',transitions,p.max_controller_decisions),
        ('top control minimum reservation',transitions*65536,p.max_control_units),
        ('forecast transitions',forecast,p.max_forecast_transitions),
        ('runtime entries (each role)',max(transitions,forecast),limits.max_runtime_entries),
        ('quiet leaves (each role)',max(transitions,forecast)*leaves_per_interval,q.max_total_leaf_calls),
        ('environment proposals (each role)',max(transitions,forecast)*leaves_per_interval,root.environment_ageing_policy.maximum_proposals),
        ('environment control (each role)',max(transitions,forecast)*leaves_per_interval*(256+64*(len(root.environment_ageing_policy.emissivity)+len(root.environment_ageing_policy.conductance))),2**64),
        ('original-grid nominal forces (each role)',4*((d+9)//10),orbit.max_force_reservations)]
    for name,needed,cap in rows:
        if needed>cap:raise ValueError('B62 conditional horizon reservation exceeds fixed cap: '+name)
    return dict(format='B62_SOURCE_DERIVED_LIFETIME_RESOURCE_PLAN_V1',root_identity=root.identity,
        duration_seconds=d,target_seconds=root.end_seconds,offered=root.offered_population,
        full_30day_buckets=d//MONTH,terminal_bucket_seconds=d%MONTH,
        accounting=ACCOUNTING,top_limits=asdict(p),physical_limits=asdict(limits),
        orbit_limits=asdict(orbit),environment_proposals=root.environment_ageing_policy.maximum_proposals,
        formulas=dict(transitions='2*(duration_seconds+offered+1)',forecast='transitions*(2*ceil(maximum_observation_age_seconds/detailed_step_seconds)+4)',
            leaves_per_interval='3*max_trials_per_interval+max_selected_parts',nominal_forces='4*ceil(duration_seconds/10)'),
        conditional_checks=[dict(name=n,reservation=v,cap=c,pass_=v<=c)for n,v,c in rows],
        conditional_assumptions=['At most one instantaneous solar transaction per integer-second advancing transaction.',
            'Forecast catchup advances by detailed_step_seconds except at most two boundary cuts, with at most one instantaneous solar transaction per advancing cut.'],
        unknown_terms=['Future physical/domain admissibility and workload cost growth.',
            'Detailed leaf spatial/construction/control cost and extra orbit tail queries; their finite runtime ledgers remain binding.'],
        quota_completion_proof=False,cpu_seconds='UNKNOWN',qualification='FINITE_CONDITIONAL_ADMISSION_NOT_HORIZON_OR_PHYSICAL_QUALIFICATION')
