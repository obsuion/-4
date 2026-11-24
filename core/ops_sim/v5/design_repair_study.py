"""Consumed finite actual M7 study. Forecasts and cached evidence grant no physics."""
from dataclasses import dataclass, field, asdict, fields
from fractions import Fraction
from hashlib import sha256
from math import isfinite
from pathlib import Path
import json, traceback
from .design_repair import (DesignRepairSpec, ConstructorLedger, compile_catalogue,
    source_identity, hash_identity, propose_repairs, rebuild_model)
from .rolling_physics import digest
from .rolling_execution import start_rolling, step_rolling, paid_scientific_bytes, work_projection
from .command_document import inputs_to_json as root_to_json
from .long_mission_document import canonical_json
from .long_mission_continuation import _bounded_tree, _scientific
from .experiment_codec import parse_json, object_fields
from .rolling_cache import canonical_size
from .rolling_contract import integer

METHOD = 'M7_ACTUAL_FINITE_STUDY_V2'
CASE_FORMAT = 'M7_EXTERNALLY_BOUND_ACTUAL_CASE_EVIDENCE_V2'
METRICS_METHOD = 'M7_EXECUTED_POINT_BOUNDARY_METRICS_V2'
MEASURED = ('forecast_invocations', 'forecast_physical_reserved', 'actual_physical_reserved',
    'harness_compiles', 'construction_line_reserved', 'nominal_force_reserved',
    'control_reserved', 'publication_reencoded_bytes', 'decisions', 'reconstructions')


@dataclass(slots=True)
class StudyWork:
    constructor: ConstructorLedger = field(default_factory=ConstructorLedger)
    actual_starts: int = 0
    reconstructions: int = 0
    decision_attempts: int = 0
    cache_reuses: int = 0
    cached_scientific_bytes_read: int = 0
    metadata_reserved_bytes: int = 0
    retained_case_bytes: int = 0
    control_reserved: int = 0
    case_ceiling_reservations: dict = field(default_factory=dict)
    measured_old_work: dict = field(default_factory=lambda: {n: 0 for n in MEASURED})

    def validate(self, spec):
        lim = spec.limits; self.constructor.validate()
        if self.constructor.maximum_compiles != lim.max_constructor_compiles:
            raise ValueError('foreign constructor budget')
        caps = dict(actual_starts=lim.max_actual_starts, reconstructions=lim.max_reconstructions,
            decision_attempts=lim.max_decision_attempts, cache_reuses=128,
            cached_scientific_bytes_read=128*512*2**20,
            metadata_reserved_bytes=lim.max_metadata_bytes, retained_case_bytes=lim.max_retained_case_bytes,
            control_reserved=lim.max_control_reserved)
        for n, cap in caps.items(): integer(getattr(self, n), n, 0, cap)
        if type(self.case_ceiling_reservations) is not dict or type(self.measured_old_work) is not dict or set(self.measured_old_work) != set(MEASURED):
            raise ValueError('strict cumulative study work')
        expected = ceiling_for(spec.reference)
        if set(self.case_ceiling_reservations) - set(expected):
            raise ValueError('unknown ceiling owner')
        count = self.actual_starts + self.reconstructions
        for n, q in expected.items():
            value = self.case_ceiling_reservations.get(n, 0)
            if type(value) is not int or value != count * q:
                raise ValueError('reset or altered per-case ceiling history')
        for n, v in self.measured_old_work.items(): integer(v, n, 0, 10*2**48)
        for n in ('forecast_invocations', 'forecast_physical_reserved', 'actual_physical_reserved',
                  'harness_compiles', 'construction_line_reserved', 'nominal_force_reserved', 'control_reserved'):
            if self.measured_old_work[n] > self.case_ceiling_reservations.get(n, 0):
                raise ValueError('measured old work exceeds reserved ceilings')
        if self.measured_old_work['publication_reencoded_bytes'] > lim.max_reencoded_bytes:
            raise ValueError('study reencoding limit')

    def reserve_case(self, spec, *, reconstruction=False):
        """Reserve one complete unchanged root ceiling before start/reconstruction.

        Unknown failed work keeps its whole ceiling reservation. It is not
        converted into a fabricated completed operation count or refunded.
        """
        self.validate(spec)
        name = 'reconstructions' if reconstruction else 'actual_starts'
        cap = spec.limits.max_reconstructions if reconstruction else spec.limits.max_actual_starts
        if getattr(self, name) >= cap: raise ValueError('M7_CASE_OR_RECONSTRUCTION_ADMISSION')
        if self.retained_case_bytes + spec.reference.model.limits.max_document_bytes > spec.limits.max_retained_case_bytes:
            raise ValueError('M7_CASE_OUTPUT_CAPACITY_ADMISSION')
        additions = ceiling_for(spec.reference)
        count = self.actual_starts + self.reconstructions + 1
        if count > spec.limits.max_actual_starts + spec.limits.max_reconstructions:
            raise ValueError('finite invocation ceilings')
        if self.control_reserved + additions['control_reserved'] > spec.limits.max_control_reserved:
            raise ValueError('M7_CONTROL_ADMISSION')
        setattr(self, name, getattr(self, name) + 1)
        self.control_reserved += additions['control_reserved']
        for n, v in additions.items(): self.case_ceiling_reservations[n] = self.case_ceiling_reservations.get(n, 0) + v
        self.validate(spec)


def ceiling_for(root):
    # Ten separately admitted roots/replays, each with unchanged root ceilings.
    # These are conservative reservations, not counts extrapolated from timings.
    return {n: getattr(root.quotas, 'max_' + n) for n in (
        'forecast_invocations', 'forecast_physical_reserved', 'actual_physical_reserved',
        'harness_compiles', 'construction_line_reserved', 'nominal_force_reserved', 'control_reserved')}


@dataclass(slots=True)
class StudyState:
    spec: DesignRepairSpec
    catalogue: tuple
    work: StudyWork
    cases: tuple = ()
    proposals: tuple = ()
    active_index: int | None = None
    active: object = None
    active_proposal: object = None
    active_measured: dict = field(default_factory=lambda: {n: 0 for n in MEASURED})
    selected_variant: str | None = None
    status: str = 'PARTIAL'


def start_study(spec, *, work=None):
    if type(spec) is not DesignRepairSpec: raise TypeError('exact repair input')
    spec.__post_init__()
    if spec.source_identity != source_identity(): raise ValueError('ACTUAL_SOURCE_BINDING_MISMATCH')
    w = StudyWork(constructor=ConstructorLedger(spec.limits.max_constructor_compiles)) if work is None else work
    if type(w) is not StudyWork: raise TypeError('exact study ledger')
    w.validate(spec)
    count = len(spec.placements) * len(spec.payload_areas_m2)
    if w.constructor.compiles + count > w.constructor.maximum_compiles:
        raise ValueError('M7_COMPLETE_CATALOGUE_CONSTRUCTION_ADMISSION')
    cat = compile_catalogue(spec, w.constructor)
    return StudyState(spec, cat, w)


def _observe(state):
    if state.active is None: return
    now = asdict(state.active.work)
    for n in MEASURED:
        v = now[n]; old = state.active_measured[n]
        if type(v) is not int or v < old: raise ValueError('OLD_CASE_LEDGER_RESET')
        state.work.measured_old_work[n] += v - old
        state.active_measured[n] = v
    state.work.validate(state.spec)


def begin_case(state, index):
    if state.active is not None or type(index) is not int or index != len(state.cases) or not 0 <= index < len(state.catalogue):
        raise ValueError('exact next catalogue case required')
    state.work.reserve_case(state.spec)
    state.active_index = index
    state.active_proposal=proposal_consumption(state,state.catalogue[index])
    try:
        # Consume the frozen edit through a fresh paid numeric construction at
        # the actual case boundary. No hardware or physical cache crosses runs.
        v=state.catalogue[index]
        model,construction,hardware=rebuild_model(state.spec.reference,v.manifest.placement,
            v.manifest.payload_area_m2,state.work.constructor)
        from dataclasses import replace
        root=replace(state.spec.reference,reference=replace(state.spec.reference.reference,model=model))
        if digest(root)!=v.manifest.candidate_root_identity or construction!=v.construction or hardware!=v.hardware:
            raise ValueError('FROZEN_VARIANT_RECONSTRUCTION_MISMATCH')
        state.active = start_rolling(root)
    finally:
        _observe(state)
    return state


def step_case(state):
    if state.active is None or state.active.status != 'ACTIVE': raise ValueError('active actual case required')
    if state.work.decision_attempts >= state.spec.limits.max_decision_attempts:
        raise ValueError('M7_COMPLETE_DECISION_BOUNDARY_ADMISSION')
    state.active.work.validate(state.active.root.quotas)
    # The entire unchanged invocation was prepaid by reserve_case. This boundary
    # additionally reserves its attempt; old forecasts/physical guards remain.
    state.work.decision_attempts += 1
    try:
        state.active = step_rolling(state.active)
    finally:
        _observe(state)
    return state


def _plain_output(v, depth=0):
    """Read-only output projection. No imported types or physical seed decoder."""
    if depth > 64: raise ValueError('output depth')
    if type(v) is list: return [_plain_output(x, depth+1) for x in v]
    if type(v) is not dict:
        if type(v) not in (int, float, bool, str, type(None)): raise ValueError('output scalar')
        if type(v) is float and not isfinite(v): raise ValueError('finite output')
        return v
    if 'float_hex' in v:
        object_fields(v, ('float_hex',)); x = v['float_hex']
        if type(x) is not str: raise ValueError('output float spelling')
        f = float.fromhex(x)
        if not isfinite(f) or f.hex() != x: raise ValueError('canonical finite output float')
        return f
    if 'numerator_hex' in v or 'denominator_hex' in v:
        object_fields(v, ('numerator_hex', 'denominator_hex'))
        if any(type(v[n]) is not str or len(v[n]) > 2048 for n in v): raise ValueError('bounded fraction output')
        return Fraction(int(v['numerator_hex'], 16), int(v['denominator_hex'], 16))
    if 'tuple' in v or 'list' in v:
        key = 'tuple' if 'tuple' in v else 'list'; object_fields(v, (key,))
        if type(v[key]) is not list: raise ValueError('output sequence')
        return [_plain_output(x, depth+1) for x in v[key]]
    if 'record_type' in v or 'fields' in v:
        object_fields(v, ('record_type', 'fields'))
        if type(v['record_type']) is not str or not v['record_type'].startswith('ops_sim.v5.') or type(v['fields']) is not dict:
            raise ValueError('fixed project output record namespace')
        return {n: _plain_output(x, depth+1) for n, x in v['fields'].items()}
    if 'enum_type' in v:
        object_fields(v, ('enum_type', 'member'))
        if type(v['enum_type']) is not str or not v['enum_type'].startswith('ops_sim.v5.') or type(v['member']) is not str:
            raise ValueError('output enum')
        return v['member']
    if 'decimal_tuple' in v:
        # Metrics do not use Decimal results; retain their exact output DATA.
        object_fields(v, ('decimal_tuple',)); object_fields(v['decimal_tuple'], ('sign', 'digits', 'exponent'))
        return v
    return {n: _plain_output(x, depth+1) for n, x in v.items()}


def executed_point_seconds(outcome):
    """Returned committed boundaries grant time; a retained plan grants none.

    B48 POINT is atomic: refused returns start=end and no executed cuts. No
    partial-POINT execution contract is inferred from retained trial metadata.
    """
    if outcome['kind'] != 'POINT':
        return 0
    if outcome['status'] == 'refused':
        if outcome['start_seconds'] != outcome['end_seconds'] or outcome['cuts']:
            raise ValueError('refused POINT contradicts atomic rollback semantics')
        return 0
    if outcome['status'] != 'completed':
        raise ValueError('unsupported POINT execution status')
    start, end = outcome['start_seconds'], outcome['end_seconds']
    if end < start:
        raise ValueError('reversed actual POINT boundary')
    cursor = start
    for cut in outcome['cuts']:
        if cut['start_seconds'] != cursor or cut['end_seconds'] < cursor:
            raise ValueError('noncontiguous returned POINT cuts')
        cursor = cut['end_seconds']
    if cursor != end:
        raise ValueError('actual POINT boundary lacks returned executed cuts')
    return end-start


def metrics_from_science(raw, root, *, expected_scientific_sha256):
    hash_identity(expected_scientific_sha256)
    if type(raw) is not bytes or len(raw) > root.model.limits.max_document_bytes or sha256(raw).hexdigest() != expected_scientific_sha256:
        raise ValueError('external complete actual scientific binding')
    d = parse_json(raw.decode()); _bounded_tree(d)
    keys = ('api', 'root_identity', 'status', 'checkpoint', 'attitude', 'outcomes', 'acquisitions', 'consumed_contacts',
        'effective_hardware', 'construction', 'knowledge', 'queued', 'decisions', 'command_lineage', 'assessments',
        'nominal_model_identity', 'illumination_rule', 'command_intents', 'reconciliations', 'diagnosis', 'estimation_method', 'controller_method')
    object_fields(d, keys)
    if canonical_json(d).encode() != raw or d['root_identity'] != digest(root) or d['api'] != root.api:
        raise ValueError('canonical same-root scientific output required')
    p = _plain_output(d)
    cp = p['checkpoint']; parts = []
    for o in p['outcomes']:
        parts.extend(c['part'] for c in o['cuts'])
        for f in o['contact_forcing']:
            for e in f['evaluations']:
                if e['selected']: parts.extend(e['parts'])
    initial = root.initial_checkpoint.restore(root.model.simulation_inputs)
    assessments = p['assessments']
    if len(assessments) != len(root.requests): raise ValueError('assessment population')
    credited = [i for i, a in enumerate(assessments) if a['status'] == 'credited']
    delivered = cp['ground_data_delivery']['completed_deliveries']
    if len(credited) > len(delivered) or any(a['completion_time_seconds'] is None or a['completion_time_seconds'] > root.requests[i].product.delivery_deadline_seconds for i, a in enumerate(assessments) if i in credited):
        raise ValueError('actual receipt/deadline credit inconsistency')
    temperatures = {n.node_id.value: max([n.temperature_k] + [t['end_temperature_k'] for part in parts
        for t in part['physical']['thermal_coupling_result']['thermal_result']['node_transitions'] if t['node_id']['value'] == n.node_id.value])
        for n in initial.spacecraft_state.thermal.node_states}
    violations = [n.node_id.value for n in root.model.configuration.thermal_network.nodes
        if temperatures[n.node_id.value] > n.operating_max_temperature_k.value]
    actions = [dict(id=o['action_id'], kind=o['kind'], status=o['status'], reason=o['reason'], start=o['start_seconds'], end=o['end_seconds'],
        planned_slew_seconds=None if o['slew'] is None else o['slew']['duration_seconds'],
        executed_slew_seconds=executed_point_seconds(o)) for o in p['outcomes']]
    properties = p['effective_hardware']['augmentation']['effective_mass_properties']
    return dict(reporting_method=METRICS_METHOD,status=p['status'], clock=cp['simulation_time_seconds'], acquired=len(p['acquisitions']), receipts=len(delivered),
        credited_products=len(credited), priority_weighted_delivery_score=sum(root.requests[i].product.request.priority_weight for i in credited)/sum(r.product.request.priority_weight for r in root.requests),
        deadline_results=[dict(request_id=r.product.request.request_id.value, status=a['status'], completion_time_seconds=_scientific(a['completion_time_seconds']), deadline_seconds=r.product.delivery_deadline_seconds, reasons=a['reasons']) for r, a in zip(root.requests, assessments)],
        minimum_energy_wh=min([initial.spacecraft_state.battery.energy_wh]+[x['physical']['eps_result']['battery']['end_energy_wh'] for x in parts]),
        final_energy_wh=cp['spacecraft']['battery_energy_wh'],
        wire_loss_wh=sum((x['electrical']['pv_wire_loss_w']+x['electrical']['receiving_wire_loss_w'])*x['physical']['eps_result']['battery']['dt_seconds']/3600 for x in parts),
        unmet_load_wh=sum(x['physical']['eps_result']['battery']['unmet_load_w']*x['physical']['eps_result']['battery']['dt_seconds']/3600 for x in parts),
        actual_full_service_shortfalls=sum(not x['electrical']['fully_served'] for x in parts),
        maximum_temperature_k=temperatures, returned_temperature_violations=violations,
        actual_refusals=sum(a['status'] != 'completed' for a in actions), rejected_requests=sum(a['status'] != 'credited' for a in assessments),
        actual_slew_seconds=sum(executed_point_seconds(o) for o in p['outcomes']),
        actuator_energy_wh=sum(c['actuator_draw_w']*float(c['end_seconds']-c['start_seconds'])/3600 for o in p['outcomes'] for c in o['cuts']),
        mass_properties=properties, added_harness_mass_kg=str(p['effective_hardware']['augmentation']['added_mass_exact_kg']),
        actions=actions)


def publish_metadata(state, path, value):
    """Precharged encoding/retention. Reservations stay spent, never refunded."""
    size = canonical_size(value, state.spec.limits.max_metadata_bytes)
    reserve = size + 256
    if state.work.metadata_reserved_bytes + reserve > state.spec.limits.max_metadata_bytes:
        raise ValueError('M7_METADATA_BEFORE_ENCODING')
    if state.work.control_reserved + 2**20 > state.spec.limits.max_control_reserved:
        raise ValueError('M7_METADATA_CONTROL_ADMISSION')
    state.work.metadata_reserved_bytes += reserve; state.work.control_reserved += 2**20
    raw = canonical_json(value).encode()
    if len(raw) != size: raise ValueError('metadata size consistency')
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f: f.write(raw)
    return sha256(raw).hexdigest()


def finish_case(state, directory):
    """Durable full result BEFORE clearing active state or entering another root."""
    if state.active is None or state.active.status == 'ACTIVE': raise ValueError('terminal actual case required')
    v = state.catalogue[state.active_index]; out = Path(directory)/'cases'/f'{v.index:02d}'
    out.mkdir(parents=True, exist_ok=True)
    if (out/'science.json').exists(): raise ValueError('never overwrite prior case evidence')
    if state.work.retained_case_bytes + v.root.model.limits.max_document_bytes > state.spec.limits.max_retained_case_bytes:
        raise ValueError('M7_SCIENTIFIC_PUBLICATION_ADMISSION')
    # Old paid encoding remains inside its original per-run ledger.
    raw = paid_scientific_bytes(state.active); _observe(state)
    state.work.retained_case_bytes += len(raw)
    h = sha256(raw).hexdigest()
    with (out/'science.json').open('xb') as f: f.write(raw)
    metrics = metrics_from_science(raw, v.root, expected_scientific_sha256=h)
    if metrics['mass_properties'] != _plain_output(_scientific(v.hardware.mass_properties)):
        raise ValueError('returned hardware differs from consumed constructor')
    record = dict(format=CASE_FORMAT, index=v.index, variant_identity=v.manifest.variant_identity,
        root_identity=digest(v.root), source_identity=state.spec.source_identity, terminal=state.active.status,
        scientific_sha256=h, scientific_bytes=len(raw), metrics=metrics,
        manifest=asdict(v.manifest), proposal_consumption=state.active_proposal,work=work_projection(state.active))
    publish_metadata(state, out/'case.json', record)
    publish_metadata(state, out/'root.json', parse_json(root_to_json(v.root)))
    if v.manifest.kind == 'BASELINE_IDENTITY': state.proposals = propose_repairs(state.spec, state.catalogue, state.active.diagnosis)
    state.cases = (*state.cases, record)
    state.active = None; state.active_index = None; state.active_proposal=None;state.active_measured = {n: 0 for n in MEASURED}
    finalize_selection(state)
    return record


def record_case_failure(state, directory, error):
    """Failure data is durable; no physical/credit row is invented."""
    if state.active_index is None: raise ValueError('case admission needed for failure row')
    v = state.catalogue[state.active_index]; _observe(state)
    record = dict(format=CASE_FORMAT, index=v.index, variant_identity=v.manifest.variant_identity,
        root_identity=digest(v.root), source_identity=state.spec.source_identity, terminal='FAILED',
        scientific_sha256=None, scientific_bytes=0, metrics=None, manifest=asdict(v.manifest),proposal_consumption=state.active_proposal or proposal_consumption(state,v),
        work=None if state.active is None else work_projection(state.active),
        failure=dict(type=type(error).__name__, reason=str(error), traceback=traceback.format_exc(),
                     physical_coverage='NOT_ESTABLISHED_BY_FAILURE'))
    publish_metadata(state, Path(directory)/'cases'/f'{v.index:02d}'/'case.json', record)
    state.cases=(*state.cases, record); state.active=None; state.active_index=None;state.active_proposal=None
    state.active_measured={n:0 for n in MEASURED}; finalize_selection(state)
    return record


def feasibility(spec, record):
    m = record['metrics']; reasons=[]
    if record['terminal'] != 'COMPLETE' or m is None: return False, ('INCOMPLETE_OR_FAILED_ACTUAL_CASE',)
    if record.get('manifest',{}).get('kind')=='BASELINE_IDENTITY':reasons.append('BASELINE_IDENTITY_IS_NOT_A_REPAIR')
    req=spec.requirements
    if m['clock'] != int(spec.reference.model.environment.end_seconds): reasons.append('INCOMPLETE_HORIZON')
    if m['credited_products'] < req.minimum_credited_products: reasons.append('REQUIRED_ACTUAL_PRODUCT_OUTPUT')
    if m['priority_weighted_delivery_score'] < req.minimum_priority_score: reasons.append('REQUIRED_ACTUAL_PRIORITY_SCORE')
    if m['unmet_load_wh'] > req.maximum_unmet_load_wh: reasons.append('RETURNED_UNMET_LOAD')
    if m['actual_full_service_shortfalls']: reasons.append('RETURNED_FULL_ELECTRICAL_SERVICE')
    if m['actual_refusals'] > req.maximum_actual_refusals: reasons.append('RETURNED_ACTION_REFUSAL')
    if m['returned_temperature_violations']: reasons.append('RETURNED_TEMPERATURE_PROTECTION')
    return not reasons, tuple(reasons)


def tradeoff_table(state):
    base_mass = next(v.hardware.mass_properties.total_mass_kg for v in state.catalogue if v.manifest.kind == 'BASELINE_IDENTITY')
    rows=[]
    for record in state.cases:
        feasible, reasons=feasibility(state.spec,record); m=record['metrics']
        rows.append(dict(variant_identity=record['variant_identity'], index=record['index'], terminal=record['terminal'], feasible=feasible, reasons=list(reasons),
            credited_products=None if m is None else m['credited_products'], priority_score=None if m is None else m['priority_weighted_delivery_score'],
            added_mass_kg=None if m is None else m['mass_properties']['total_mass_kg']-base_mass,
            actuator_and_wire_energy_wh=None if m is None else m['actuator_energy_wh']+m['wire_loss_wh']))
    for row in rows:
        row['pareto_admissible_completed']=row['feasible'] and not any(other['feasible'] and other['variant_identity']!=row['variant_identity'] and
            other['added_mass_kg'] <= row['added_mass_kg'] and other['actuator_and_wire_energy_wh'] <= row['actuator_and_wire_energy_wh'] and
            (other['added_mass_kg'] < row['added_mass_kg'] or other['actuator_and_wire_energy_wh'] < row['actuator_and_wire_energy_wh']) for other in rows)
    return rows


def finalize_selection(state):
    rows=tradeoff_table(state); eligible=[r for r in rows if r['feasible']]
    state.selected_variant=None if not eligible else min(eligible,key=lambda r:(r['added_mass_kg'],r['actuator_and_wire_energy_wh'],r['variant_identity']))['variant_identity']
    state.status='PARTIAL' if len(state.cases)<len(state.catalogue) else 'FAILED' if any(r['terminal']!='COMPLETE' for r in state.cases) else 'NO_FEASIBLE_REPAIR' if state.selected_variant is None else 'SUCCESS'


def scientific_study(state):
    """Exact same-runtime science. Additional work/reuse is reported separately."""
    return dict(method=METHOD, specification_identity=state.spec.identity, source_identity=state.spec.source_identity,
        catalogue=[asdict(v.manifest) for v in state.catalogue],
        cases=[{n:r[n] for n in ('index','variant_identity','root_identity','source_identity','terminal','scientific_sha256','scientific_bytes','metrics','manifest','proposal_consumption')} for r in state.cases],
        proposals=_scientific(state.proposals), tradeoff=tradeoff_table(state), selected_variant=state.selected_variant,
        status=state.status, interpretation='Best among these admitted completed variants under the declared synthetic model; no global optimum or flight qualification.',
        pareto_dimensions=dict(added_mass_kg='MINIMIZE',actuator_and_wire_energy_wh='MINIMIZE',eligibility='ACTUAL_REQUIREMENTS_FIRST'))


def proposal_consumption(state,variant):
    matched=tuple(p.proposal_identity for p in state.proposals if variant.manifest.variant_identity in p.candidate_variant_ids)
    return dict(proposal_ids=list(matched),role='BASELINE_REFERENCE' if variant.manifest.kind=='BASELINE_IDENTITY' else
        'DIAGNOSIS_BOUND_ADMISSIBLE_EDIT' if matched else 'DECLARED_PLACEMENT_CONTROL' if variant.manifest.kind=='ASSEMBLY_PLACEMENT' else
        'DECLARED_EXPLORATORY_EDIT_WITHOUT_ESTABLISHED_CAUSE',
        grant='NONE_ACTUAL_MISSION_REQUIRED',base_scientific_sha256=state.cases[0]['scientific_sha256'] if state.cases else None)


def export_study(state, directory, label):
    out=Path(directory)
    h=publish_metadata(state,out/(label+'.science.json'),scientific_study(state))
    publish_metadata(state,out/(label+'.work.json'),asdict(state.work))
    if state.selected_variant is not None:
        v=next(v for v in state.catalogue if v.manifest.variant_identity==state.selected_variant)
        publish_metadata(state,out/(label+'.selected.root.json'),parse_json(root_to_json(v.root)))
    return h
