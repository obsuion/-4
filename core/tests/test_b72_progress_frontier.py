"""B72 exact DATA, prepaid bounded snapshots and current native acceptance."""
from copy import deepcopy
from pathlib import Path
import json,sys
import pytest
from test_lifecycle_b65 import started_pair,build
from ops_sim.v5 import lifecycle_execution as le,lifecycle_job_prepared as jp
from ops_sim.v5.lifecycle_document import canonical
from ops_sim.v5.lifecycle_typed_platform import admit_typed_build

@pytest.mark.parametrize('resources',(False,True))
def test_exact_public_and_worker_forms_and_summary_fees(resources):
    state,_=started_pair();ctx=state.backend_context;before=ctx.native.native_entry_counts()
    actual=le.progress_frontier_projection(state,resources=resources)
    with ctx.transaction():expected=le._progress_projection(state,_resources=resources)
    assert canonical(actual)==canonical(expected)
    if resources:assert 'priority_score'not in actual[1]and 'priority_score_status'not in actual[1]
    assert before==ctx.native.native_entry_counts()


def test_nested_resource_totals_are_detached_from_progress_and_report():
    state,_=started_pair();raw_report=canonical(state.report.state);value,totals=le.progress_frontier_projection(state,resources=True)
    assert totals['battery_port']is not value['battery_port']['sampled_report']
    totals['battery_port']['B72_injected']=True
    assert 'B72_injected'not in value['battery_port']['sampled_report']and canonical(state.report.state)==raw_report


def test_prepaid_reservation_precedes_both_snapshot_encodings():
    state,_=started_pair();job=state.backend_context.job;old=sys.getprofile();seen=[];initial=job._work['control_units_reserved'];attempts=job._work['progress_frontiers']
    def trace(frame,event,arg):
        if event=='call'and frame.f_code is jp._data.__code__:
            seen.append((job._work['control_units_reserved'],job._work['progress_frontiers']))
    sys.setprofile(trace)
    try:le.progress_frontier_projection(state,resources=True)
    finally:sys.setprofile(old)
    assert len(seen)==2
    assert all(reserved>=initial+4096+32*64*2**20 and charged==attempts+1 for reserved,charged in seen)


def test_failed_local_reservation_never_encodes_or_publishes():
    state,_=started_pair();ctx=state.backend_context;old=sys.getprofile();encoded=[];attempted=[];published=[]
    def trace(frame,event,arg):
        if event=='call'and frame.f_code is jp._data.__code__:encoded.append(True)
        if event=='call'and frame.f_code is jp.PreparedJobRuntime._charge.__code__ and frame.f_locals.get('field')=='progress_frontiers':attempted.append(True)
    with ctx.transaction():
        ctx.job._work['control_units_reserved']=jp.MAX_CONTROL_UNITS-(4096+32*64*2**20)+1
        sys.setprofile(trace)
        try:
            with pytest.raises(ValueError):published.append(le._progress_projection(state,_fold=True))
        finally:sys.setprofile(old)
    assert attempted and not encoded and not published


def test_bounded_local_shape_admission_precedes_encoding_and_summary():
    state,_=started_pair();old=sys.getprofile();encoded=[];value={};cursor=value
    for _ in range(70):child={};cursor['nested']=child;cursor=child
    state.report.state['B72_invalid_nested']=value
    def trace(frame,event,arg):
        if event=='call'and frame.f_code is jp._data.__code__:encoded.append(True)
    sys.setprofile(trace)
    try:
        with pytest.raises(ValueError,match='bounded frontier DATA nodes/depth'):le.progress_frontier_projection(state)
    finally:sys.setprofile(old)
    assert not encoded


def test_fresh_actual_binary_loaded_and_forged_support_rejected():
    receipt=build();module=admit_typed_build(receipt);root=Path(__file__).resolve().parents[1]
    assert Path(module.__file__).resolve().is_relative_to(root)
    changed=deepcopy(receipt);name=next(iter(changed['support_sources']));changed['support_sources'][name]['sha256']='0'*64
    with pytest.raises(ValueError):admit_typed_build(changed)

@pytest.mark.parametrize('resources',(0,1,'false'))
def test_resources_flag_is_exact_boolean(resources):
    state,_=started_pair()
    with pytest.raises(TypeError):le.progress_frontier_projection(state,resources=resources)


def test_exact_current_producer_membership_includes_current_progress_closure():
    from ops_sim.v5.lifetime_source import B65_SOURCE_PATHS
    from ops_sim.v5.portable_job import source_manifest
    root=Path(__file__).resolve().parents[1]
    manifest=source_manifest(root)
    assert set(manifest)==set(B65_SOURCE_PATHS)
    assert len(B65_SOURCE_PATHS)==len(set(B65_SOURCE_PATHS))
    assert {'B71_PROGRESS_FRONTIER.md','tests/test_b71_progress_frontier.py','tests/test_b72_progress_frontier.py'}<=set(B65_SOURCE_PATHS)


@pytest.mark.parametrize('change',('missing-top','missing-job','boolean','unpaid-summary','excess-secondary'))
def test_returned_progress_schema_and_paid_counts_are_strict(monkeypatch,change):
    from test_lifecycle_typed_receipt import returned
    from test_lifetime_typed_portable import declared_contract
    from ops_sim.v5 import lifecycle_typed_receipt as owner
    contract,_,_=declared_contract(monkeypatch)
    # The legacy helper deliberately declares only a minimal B64 fixture.
    # Explicitly declare the new DATA-schema member and bind its exact bytes.
    from ops_sim.v5.portable_job import canonical as portable_canonical,digest
    marker=Path(__file__).resolve().parents[1]/'B71_PROGRESS_FRONTIER.md'
    contract['source_manifest']['B71_PROGRESS_FRONTIER.md']=dict(bytes=marker.stat().st_size,sha256=digest(marker.read_bytes()))
    contract['source_manifest_sha256']=digest(portable_canonical(contract['source_manifest']))
    assert 'B71_PROGRESS_FRONTIER.md'in contract['source_manifest']
    value=returned(contract)
    assert owner.admit_backend_receipt(value,contract)==value
    if change=='missing-top':del value['progress_summary_calls']
    elif change=='missing-job':del value['owned_job']['control']['progress_frontiers']
    elif change=='boolean':value['progress_frontiers_completed']=True
    elif change=='unpaid-summary':value['progress_summary_calls']=1
    else:value['progress_secondary_validations']=1
    with pytest.raises(ValueError):owner.admit_backend_receipt(value,contract)
