"""Strict saved-DATA reader regression; these fixtures grant no execution."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from ops_sim.v5.lifecycle_typed_receipt import admit_backend_receipt
from ops_sim.v5.lifetime_typed_portable import admit_execution_contract_data_v3

@pytest.fixture
def saved():
    return json.loads((Path(__file__).parent/'fixtures/b69_returned_control.json').read_bytes())

def test_actual_saved_b69_receipt_shape_is_admitted_without_activation(saved,monkeypatch):
    value=saved['receipt'];contract=saved['contract']
    from ops_sim.v5 import lifecycle_backend
    def forbidden(*a,**k):raise AssertionError('saved-DATA reader attempted runtime/source/native activation')
    monkeypatch.setattr(Path,'read_bytes',forbidden)
    monkeypatch.setattr(lifecycle_backend,'runtime_binding',forbidden)
    assert admit_backend_receipt(value,contract)==value
    assert saved['provenance']['kind']=='DERIVED_SAVED_DATA_READER_FIXTURE_NOT_EXECUTION'

@pytest.mark.parametrize('path,new',[
    (('owned_job','method'),'B64_OWNED_PREPARED_JOB_V1'),
    (('owned_job','preparation','method'),'B64_OWNED_PREPARED_JOB_V1'),
    (('owned_job','control','method'),'B64_JOB_PREPARATION_CONTROL_V1'),
    (('owned_job','roles','FORECAST','method'),'B64_OWNED_PREPARED_JOB_V1'),
    (('owned_job','exact_guard','method'),'PYTHON_EXACT_REFERENCE_FALLBACK'),
    (('owned_job','exact_guard','counters'),{}),
    (('owned_job','roles','ACTUAL','cache_entries'),9),
    (('owned_job','control','transaction_attempts'),True),
])
def test_b69_method_domain_field_and_accounting_substitution_refused(saved,path,new):
    value=deepcopy(saved['receipt']);target=value
    for k in path[:-1]:target=target[k]
    target[path[-1]]=new
    with pytest.raises(ValueError):admit_backend_receipt(value,saved['contract'])

def test_new_fields_are_required_and_closed(saved):
    for kind in ('missing','extra','guard-extra'):
        value=deepcopy(saved['receipt'])
        if kind=='missing':del value['owned_job']['exact_guard']
        elif kind=='extra':value['owned_job']['native_pointer']=123
        else:value['owned_job']['exact_guard']['plans']=100
        with pytest.raises(ValueError):admit_backend_receipt(value,saved['contract'])

def test_old_preparation_tag_cannot_describe_new_compiled_source(saved):
    contract=deepcopy(saved['contract']);contract['job_preparation']='B64_OWNED_PREPARED_JOB_V1'
    with pytest.raises(ValueError):admit_execution_contract_data_v3(contract)
