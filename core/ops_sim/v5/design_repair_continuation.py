"""Strict external evidence reuse plus paid B48 in-progress reconstruction.

Expected packet/source/spec/output hashes are supplied OUTSIDE the payload.
An authenticated filesystem is not claimed. Completed data is a cache of
previous executions; it never seeds a spacecraft or creates independent work.
"""
from dataclasses import asdict, fields
from hashlib import sha256
from pathlib import Path
from .design_repair import ConstructorLedger, RepairProposal, hash_identity
from .design_repair_document import inputs_to_json, inputs_from_json
from .design_repair_study import (StudyWork, start_study, CASE_FORMAT, MEASURED,
    metrics_from_science, finalize_selection, publish_metadata, _observe)
from .rolling_document import save_continuation as save_rolling, restore_continuation as restore_rolling
from .long_mission_document import canonical_json
from .experiment_codec import object_fields, parse_json
from .long_mission_continuation import _bounded_tree
from .rolling_physics import digest
from .command_estimation import CommandWork

FORMAT = 'M7_STUDY_EXTERNAL_EVIDENCE_AND_PAID_CAUSAL_CONTINUATION_V1'
CASE_FIELDS = ('format','index','variant_identity','root_identity','source_identity','terminal',
    'scientific_sha256','scientific_bytes','metrics','manifest','proposal_consumption','work')


def case_binding(record):
    return dict(index=record['index'], case_sha256=sha256(canonical_json(record).encode()).hexdigest(),
        scientific_sha256=record['scientific_sha256'], root_identity=record['root_identity'],
        variant_identity=record['variant_identity'], source_identity=record['source_identity'])


def save_study(path, state, *, rolling_packet_path=None):
    state.work.validate(state.spec)
    progress=None
    if state.active is not None:
        if rolling_packet_path is None: raise ValueError('paid active continuation path required')
        if state.work.retained_case_bytes + state.active.root.model.limits.max_document_bytes > state.spec.limits.max_retained_case_bytes:
            raise ValueError('M7_ACTIVE_PACKET_RETENTION_ADMISSION')
        h=save_rolling(rolling_packet_path,state.active); _observe(state)
        state.work.retained_case_bytes += Path(rolling_packet_path).stat().st_size
        progress=dict(index=state.active_index, rolling_packet_sha256=h, root_identity=state.active.root_identity,
            completed_decisions=len(state.active.decisions), clock=state.active.physical.context.simulation_time_seconds,
            pending_command_kinds=[c.kind for c in state.active.knowledge.pending()],
            actual_partial_bits=[p.transmitted_equivalent_bits for p in state.active.physical.context.ground_data_delivery_state.partial_transfers],proposal_consumption=state.active_proposal)
    data=dict(format=FORMAT,version=1,specification_identity=state.spec.identity,source_identity=state.spec.source_identity,
        inputs=parse_json(inputs_to_json(state.spec)),catalogue=[asdict(v.manifest) for v in state.catalogue],
        completed=[case_binding(r) for r in state.cases],in_progress=progress,
        work=asdict(state.work),active_measured=state.active_measured,
        proposals=[asdict(p) for p in state.proposals],selected_variant=state.selected_variant,status=state.status,
        trust='EXTERNAL_SHA256_BOUND_COMPLETED_CACHE_AND_ORIGINAL_ROOT_PAID_B48_REPLAY')
    # Reserve before encoding. Capture the reservation in the packet: no hidden
    # reset when a fresh process loads it. Exact byte reserve includes digit growth.
    from .rolling_cache import canonical_size
    reserve=canonical_size(data,state.spec.limits.max_metadata_bytes)+256
    if state.work.metadata_reserved_bytes+reserve>state.spec.limits.max_metadata_bytes:
        raise ValueError('M7_STUDY_PACKET_PUBLICATION_ADMISSION')
    if state.work.control_reserved+2**20>state.spec.limits.max_control_reserved:
        raise ValueError('M7_STUDY_PACKET_CONTROL_ADMISSION')
    state.work.metadata_reserved_bytes+=reserve;state.work.control_reserved+=2**20
    data['work']=asdict(state.work);raw=canonical_json(data).encode()
    if len(raw)>reserve:raise ValueError('study packet growth exceeded reservation')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(raw)
    return sha256(raw).hexdigest()


def _old_work(data,root):
    d=object_fields(data,('aggregate','actual_runtime','actual_construction','actual_harness','actual_public_cache','forecast_public_cache'))
    w=object_fields(d['aggregate'],tuple(f.name for f in fields(CommandWork)))
    w=dict(w)
    if type(w['publication_reuse_seen']) is not list:raise ValueError('strict old reuse membership')
    w['publication_reuse_seen']=tuple(w['publication_reuse_seen'])
    work=CommandWork(**w);work.validate(root.quotas)
    return work


def load_case_evidence(state,index,directory,*,expected_case_sha256,expected_scientific_sha256):
    """Decode metrics from complete externally pinned science, no owner replay."""
    hash_identity(expected_case_sha256)
    v=state.catalogue[index];out=Path(directory)
    if (out/'case.json').stat().st_size>state.spec.limits.max_metadata_bytes:
        raise ValueError('case metadata read cap')
    raw=(out/'case.json').read_bytes()
    if sha256(raw).hexdigest()!=expected_case_sha256:raise ValueError('EXTERNAL_CASE_BINDING')
    r=parse_json(raw.decode());_bounded_tree(r)
    failure=r.get('terminal')=='FAILED'
    object_fields(r,(*CASE_FIELDS,'failure') if failure else CASE_FIELDS)
    if canonical_json(r).encode()!=raw or r['format']!=CASE_FORMAT or type(r['index']) is not int or r['index']!=index:
        raise ValueError('canonical case schema/index')
    if r['variant_identity']!=v.manifest.variant_identity or r['root_identity']!=digest(v.root) or r['source_identity']!=state.spec.source_identity or canonical_json(r['manifest'])!=canonical_json(asdict(v.manifest)):
        raise ValueError('case catalogue/root/source/manifest substitution')
    if failure:
        if expected_scientific_sha256 is not None or r['scientific_sha256'] is not None or r['metrics'] is not None or r['scientific_bytes']!=0:
            raise ValueError('failed case cannot manufacture metrics')
        object_fields(r['failure'],('type','reason','traceback','physical_coverage'))
    else:
        hash_identity(expected_scientific_sha256)
        science=out/'science.json'
        if science.stat().st_size!=r['scientific_bytes'] or science.stat().st_size>v.root.model.limits.max_document_bytes or r['scientific_sha256']!=expected_scientific_sha256:
            raise ValueError('scientific file cap/binding')
        if state.work.cache_reuses>=128 or state.work.cached_scientific_bytes_read+science.stat().st_size>128*512*2**20:
            raise ValueError('cache read admission')
        # Decoding/validation is paid by the study, never called free physics.
        if state.work.control_reserved+32*2**20>state.spec.limits.max_control_reserved:
            raise ValueError('M7_CACHE_VALIDATION_CONTROL_ADMISSION')
        state.work.control_reserved+=32*2**20
        body=science.read_bytes()
        metrics=metrics_from_science(body,v.root,expected_scientific_sha256=expected_scientific_sha256)
        from .design_repair_study import _plain_output
        from .long_mission_continuation import _scientific
        if metrics['mass_properties']!=_plain_output(_scientific(v.hardware.mass_properties)):
            raise ValueError('cached returned hardware differs from derived constructor')
        if canonical_json(metrics)!=canonical_json(r['metrics']) or metrics['status']!=r['terminal']:
            raise ValueError('DERIVED_CASE_METRICS_MISMATCH')
        from .command_document import inputs_from_json as root_from_json
        loaded=root_from_json((out/'root.json').read_text(encoding='utf-8'))
        if digest(loaded)!=digest(v.root):raise ValueError('cached original input substitution')
        state.work.cache_reuses+=1;state.work.cached_scientific_bytes_read+=len(body)
    if r['work'] is not None:_old_work(r['work'],v.root)
    object_fields(r['proposal_consumption'],('proposal_ids','role','grant','base_scientific_sha256'))
    if r['proposal_consumption']['grant']!='NONE_ACTUAL_MISSION_REQUIRED':raise ValueError('proposal cannot grant physics')
    return r


def reuse_completed_case(state,index,directory,*,expected_case_sha256,expected_scientific_sha256):
    if state.active is not None or index!=len(state.cases):raise ValueError('ordered complete evidence reuse')
    record=load_case_evidence(state,index,directory,expected_case_sha256=expected_case_sha256,expected_scientific_sha256=expected_scientific_sha256)
    # This reservation preserves the actual historical run's costs. There is no
    # new actual start; external launch inventory distinguishes cached history.
    state.work.reserve_case(state.spec)
    if record['work'] is not None:
        paid=_old_work(record['work'],state.catalogue[index].root)
        for n in MEASURED:state.work.measured_old_work[n]+=getattr(paid,n)
    state.cases=(*state.cases,record);state.work.validate(state.spec);finalize_selection(state)
    return record


def restore_study(path,*,expected_packet_sha256,expected_spec_identity,expected_source_identity,
                  completed_outputs,active_packet=None,expected_active_packet_sha256=None):
    for h in (expected_packet_sha256,expected_spec_identity,expected_source_identity):hash_identity(h)
    p=Path(path)
    if p.stat().st_size>16*2**20:raise ValueError('study packet cap')
    raw=p.read_bytes()
    if sha256(raw).hexdigest()!=expected_packet_sha256:raise ValueError('EXTERNAL_STUDY_PACKET_BINDING')
    d=object_fields(parse_json(raw.decode()),('format','version','specification_identity','source_identity','inputs','catalogue','completed',
        'in_progress','work','active_measured','proposals','selected_variant','status','trust'));_bounded_tree(d)
    if canonical_json(d).encode()!=raw or d['format']!=FORMAT or type(d['version']) is not int or d['version']!=1:
        raise ValueError('strict study continuation format')
    if d['trust']!='EXTERNAL_SHA256_BOUND_COMPLETED_CACHE_AND_ORIGINAL_ROOT_PAID_B48_REPLAY':raise ValueError('unsafe study trust boundary')
    if d['specification_identity']!=expected_spec_identity or d['source_identity']!=expected_source_identity:
        raise ValueError('external study authority binding')
    spec=inputs_from_json(canonical_json(d['inputs']),expected_spec_identity=expected_spec_identity,expected_source_identity=expected_source_identity)
    if type(d['completed']) is not list or len(d['completed'])>spec.limits.max_catalogue_roots or type(completed_outputs) is not dict or set(completed_outputs)!=set(range(len(d['completed']))):
        raise ValueError('complete external output binding set required')
    wf=object_fields(d['work'],tuple(f.name for f in fields(StudyWork)))
    cf=object_fields(wf['constructor'],tuple(f.name for f in fields(ConstructorLedger)))
    work=StudyWork(**{**wf,'constructor':ConstructorLedger(**cf)})
    state=start_study(spec,work=work)
    if canonical_json(d['catalogue'])!=canonical_json([asdict(v.manifest) for v in state.catalogue]):
        raise ValueError('CATALOGUE_OR_EDIT_MANIFEST_MUTATION')
    minimum={n:0 for n in MEASURED}
    for index,binding in enumerate(d['completed']):
        object_fields(binding,('index','case_sha256','scientific_sha256','root_identity','variant_identity','source_identity'))
        ext=object_fields(completed_outputs[index],('directory','case_sha256','scientific_sha256'))
        if ext['case_sha256']!=binding['case_sha256'] or ext['scientific_sha256']!=binding['scientific_sha256']:
            raise ValueError('external output differs from checkpoint binding')
        record=load_case_evidence(state,index,ext['directory'],expected_case_sha256=ext['case_sha256'],expected_scientific_sha256=ext['scientific_sha256'])
        if case_binding(record)!=binding:raise ValueError('complete saved case identity')
        state.cases=(*state.cases,record)
        if record['work'] is not None:
            paid=_old_work(record['work'],state.catalogue[index].root)
            for n in MEASURED:minimum[n]+=getattr(paid,n)
    if type(d['proposals']) is not list or len(d['proposals'])>64:raise ValueError('proposal output bound')
    props=[]
    for x in d['proposals']:
        f=object_fields(x,tuple(v.name for v in fields(RepairProposal)))
        f=dict(f);f['candidate_variant_ids']=tuple(f['candidate_variant_ids']);f['edited_fields']=tuple(f['edited_fields'])
        prop=RepairProposal(**f)
        if prop.status!='PROPOSAL_ONLY_NO_EXECUTION_GRANT' or any(v not in {v.manifest.variant_identity for v in state.catalogue} for v in prop.candidate_variant_ids):
            raise ValueError('proposal authority substitution')
        props.append(prop)
    state.proposals=tuple(props);finalize_selection(state)
    if state.selected_variant!=d['selected_variant'] or state.status!=d['status']:
        raise ValueError('saved selection/state mismatch')
    measured=object_fields(d['active_measured'],MEASURED)
    if any(type(v) is not int or v<0 for v in measured.values()):raise ValueError('strict active paid prefix counters')
    progress=d['in_progress'];proof=None
    expected_starts=len(state.cases)+(progress is not None)
    if state.work.actual_starts<expected_starts or any(state.work.measured_old_work[n]<minimum[n]+measured[n] for n in MEASURED):
        raise ValueError('reset accumulated historical work')
    if progress is not None:
        object_fields(progress,('index','rolling_packet_sha256','root_identity','completed_decisions','clock','pending_command_kinds','actual_partial_bits','proposal_consumption'))
        if type(progress['index']) is not int or progress['index']!=len(state.cases) or not 0<=progress['index']<len(state.catalogue):
            raise ValueError('exact in-progress catalogue cursor')
        if active_packet is None or expected_active_packet_sha256!=progress['rolling_packet_sha256']:
            raise ValueError('external active packet binding required')
        hash_identity(expected_active_packet_sha256)
        v=state.catalogue[progress['index']]
        if progress['root_identity']!=digest(v.root):raise ValueError('active root substitution')
        from .design_repair_study import proposal_consumption
        state.active_proposal=proposal_consumption(state,v)
        if state.active_proposal!=progress['proposal_consumption']:raise ValueError('active proposal substitution')
        state.work.reserve_case(spec,reconstruction=True)
        state.active_index=v.index;state.active_measured=dict(measured)
        state.active,proof=restore_rolling(active_packet,expected_packet_sha256=expected_active_packet_sha256,expected_root_identity=digest(v.root))
        if len(state.active.decisions)!=progress['completed_decisions'] or state.active.physical.context.simulation_time_seconds!=progress['clock'] or [c.kind for c in state.active.knowledge.pending()]!=progress['pending_command_kinds'] or [p.transmitted_equivalent_bits for p in state.active.physical.context.ground_data_delivery_state.partial_transfers]!=progress['actual_partial_bits']:
            raise ValueError('substantive replay boundary mismatch')
        _observe(state)
    elif any(measured.values()) or active_packet is not None:
        raise ValueError('no fabricated active prefix')
    state.work.validate(spec)
    return state,dict(trust=d['trust'],completed_cases_reused=len(state.cases),new_completed_case_physics=0,paid_active_reconstruction=proof)
