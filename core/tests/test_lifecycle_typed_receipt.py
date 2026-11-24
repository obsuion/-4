"""Returned DATA validation only; fixtures are not execution capabilities."""
from copy import deepcopy
from pathlib import Path

import pytest

from ops_sim.v5 import lifecycle_typed_receipt as owner,lifecycle_backend
from test_lifetime_typed_portable import declared_contract


def returned(contract):
    binding=contract['backend_binding']
    codec=dict(format='B63_INVOCATION_LOCAL_INPUT_CODEC_V1',phase='CLOSED',
        counters={name:0 for name in owner.CODEC_WORK},secondary_errors=[],
        scope='INPUT_ADMISSION_OPERATIONAL_CHECKS_NOT_SCIENTIFIC_WORK')
    codec['counters'].update(full_schema_scans=2,operational_checks=2)
    preparation=dict(method=owner.JOB_METHOD,phase='CONSUMED',raw_sha256=contract['input_sha256'],raw_bytes=1,
        source_binding=contract['source_manifest_sha256'],build_sha256=binding['build_sha256'],input_codec=codec,
        raw_admissions=1,model_build_attempts=1,model_build_completed=1,static_copy_attempts=1,static_copy_completed=1,
        control_units_reserved=1+2*2**19,scope='PROCESS_LOCAL_ADMISSION_DATA_NOT_AUTHORITY')
    control=dict(method=owner.CONTROL_METHOD,**{name:0 for name in owner.JOB_WORK})
    control.update(control_units_reserved=preparation['control_units_reserved'],static_preparations=1)
    roles={role:dict(method=owner.JOB_METHOD,role=role,source_binding=contract['source_manifest_sha256'],
        root_identity=contract['root_identity'],model_identity='d'*64,cache_entries=0,cache_limit=8,
        **{name:0 for name in owner.ROLE_WORK},scope='ROLE_LOCAL_OPERATIONAL_DATA_NOT_SCIENTIFIC_WORK')for role in ('ACTUAL','FORECAST')}
    job=dict(method=owner.JOB_METHOD,source_binding=contract['source_manifest_sha256'],root_identity=contract['root_identity'],
        model_identity='d'*64,raw_sha256=contract['input_sha256'],build_sha256=binding['build_sha256'],preparation=preparation,
        control=control,roles=roles,secondary_errors=[],scope='PAID_CURRENT_JOB_PREPARATION_NOT_SCIENTIFIC_WORK_OR_RESTART_AUTHORITY')
    value=dict(format=owner.FORMAT,method=owner.METHOD,selection=binding['selection'],source_binding=contract['source_manifest_sha256'],
        runtime=deepcopy(contract['native_build']['runtime']),build_sha256=binding['build_sha256'],capability_sha256=binding['capability_sha256'],
        **{name:0 for name in owner.TOP_WORK},owned_job=job,
        quiet_scope='CALLBACK_FREE' if binding['selection']==owner.FULL else 'EXPLICIT_LEGACY_QUIET_CONTROL_H05_INCOMPLETE',
        scope='OPERATIONAL_EXECUTION_NOT_PHYSICAL_MODEL_WORK')
    if 'B71_PROGRESS_FRONTIER.md'in contract['source_manifest']:
        value.update({name:0 for name in owner.PROGRESS_TOP_WORK})
        control['progress_frontiers']=0
    value.update(attempted=1,completed=1,boundaries=1)
    return value


@pytest.mark.parametrize('quiet',(True,False))
def test_detached_returned_receipt_is_strict_portable_data_without_activation(monkeypatch,quiet):
    contract,_,_=declared_contract(monkeypatch,quiet=quiet);value=returned(contract)
    def forbidden(*a,**k):raise AssertionError('returned DATA attempted file/native/runtime activation')
    monkeypatch.setattr(Path,'read_bytes',forbidden)
    monkeypatch.setattr(lifecycle_backend,'runtime_binding',forbidden)
    admitted=owner.admit_backend_receipt(value,contract)
    assert admitted==value and admitted is not value
    admitted['owned_job']['roles']['ACTUAL']['cache_entries']=8
    assert value['owned_job']['roles']['ACTUAL']['cache_entries']==0


@pytest.mark.parametrize('path,changed',[
    (('format',),'B63_BACKEND_EXECUTION_RECEIPT_V1'),
    (('selection',),owner.SUPPORT),
    (('runtime','machine'),'ARM64'),
    (('source_binding',),'f'*64),
    (('build_sha256',),'f'*64),
    (('quiet_scope',),'CALLBACK_FREE_WITH_FALLBACK'),
    (('attempted',),True),
    (('completed',),0),
    (('boundaries',),0),
    (('world_preparations',),1),
    (('owned_job','raw_sha256'),'f'*64),
    (('owned_job','preparation','phase'),'ADMITTED'),
    (('owned_job','preparation','raw_admissions'),2),
    (('owned_job','preparation','model_build_completed'),0),
    (('owned_job','preparation','control_units_reserved'),1),
    (('owned_job','preparation','input_codec','phase'),'ACTIVE'),
    (('owned_job','preparation','input_codec','counters','operational_checks'),3),
    (('owned_job','control','static_preparations'),2),
    (('owned_job','control','transaction_completed'),1),
    (('owned_job','roles','FORECAST','role'),'ACTUAL'),
    (('owned_job','roles','ACTUAL','cache_limit'),128),
    (('owned_job','roles','ACTUAL','cache_entries'),9),
    (('owned_job','roles','ACTUAL','coefficient_realizations'),1),
    (('owned_job','roles','ACTUAL','requests'),1.0),
])
def test_changed_returned_schema_binding_and_accounting_fail(monkeypatch,path,changed):
    contract,_,_=declared_contract(monkeypatch);value=returned(contract);target=value
    for key in path[:-1]:target=target[key]
    target[path[-1]]=changed
    with pytest.raises(ValueError):owner.admit_backend_receipt(value,contract)


def test_prepaid_static_failure_cost_is_retained_not_dropped(monkeypatch):
    contract,_,_=declared_contract(monkeypatch);value=returned(contract)
    # A failed indexed preparation may retain a prepaid reservation without
    # completing a static package. It is operational work, not physical work.
    value['typed_static_control_units']=6400
    assert owner.admit_backend_receipt(value,contract)['typed_static_control_units']==6400
    value['static_preparations']=1
    assert owner.admit_backend_receipt(value,contract)['static_preparations']==1
    value['typed_static_control_units']=0
    with pytest.raises(ValueError,match='prepaid indexed-static'):owner.admit_backend_receipt(value,contract)


def test_all_operational_cost_domains_survive_detached_validation(monkeypatch):
    contract,_,_=declared_contract(monkeypatch);value=returned(contract)
    value.update(typed_static_control_units=6400,static_preparations=1,world_preparation_control_units=1000,world_preparations=1)
    control=value['owned_job']['control'];control.update(transaction_attempts=2,transaction_completed=1,
        transaction_failed=1,transaction_exits=2,control_units_reserved=control['control_units_reserved']+4096)
    value['owned_job']['secondary_errors']=['Recorded exit-check error']
    result=owner.admit_backend_receipt(value,contract)
    assert result==value
    assert result['typed_static_control_units']==6400 and result['world_preparation_control_units']==1000
    assert result['owned_job']['control']['control_units_reserved']==control['control_units_reserved']


def test_extra_or_missing_cost_fields_are_not_ignored(monkeypatch):
    contract,_,_=declared_contract(monkeypatch);value=returned(contract)
    del value['typed_static_control_units']
    with pytest.raises(ValueError,match='exact'):owner.admit_backend_receipt(value,contract)
    value=returned(contract);value['physical_fee_deduction']=0
    with pytest.raises(ValueError,match='exact'):owner.admit_backend_receipt(value,contract)


def test_parent_dispatch_uses_only_explicit_new_receipt_format(monkeypatch):
    import ops_sim.v5.lifecycle_typed_receipt as module
    calls=[]
    monkeypatch.setattr(module,'admit_backend_receipt',lambda *a:calls.append(a)or {'DATA_SPY':True})
    value={'format':module.FORMAT};contract={'NOT_AN_AUTHORITY':'ROUTING_TEST_ONLY'}
    assert lifecycle_backend.admit_backend_receipt(value,contract)=={'DATA_SPY':True}
    assert calls==[(value,contract)]
