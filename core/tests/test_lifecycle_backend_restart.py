"""No prefix execution is needed to reconstruct a new prepared backend."""
import json
from hashlib import sha256
import pytest
from lifetime_support import root_for
from ops_sim.v5.lifecycle_execution import start_lifecycle
from ops_sim.v5.lifecycle_checkpoint import checkpoint_bytes,make_bindings,restore_checkpoint,admit_checkpoint
from ops_sim.v5.lifecycle_backend import current_source_binding
from ops_sim.v5.lifecycle_document import canonical

def test_prepared_checkpoint_direct_reconstruction_no_prefix(monkeypatch):
    root=root_for(60)
    state=start_lifecycle(root,backend='PREPARED_PYTHON',source_binding=current_source_binding())
    bindings=make_bindings(root,state.clock);raw=checkpoint_bytes(state,bindings)
    doc=json.loads(raw)
    assert doc['format']=='B63_PREPARED_EXPOSURE_EXECUTION_CHECKPOINT_V1'
    import ops_sim.v5.lifecycle_execution as execution
    def forbidden(*a,**k):raise AssertionError('prefix execution forbidden during RESTORE')
    monkeypatch.setattr(execution,'start_lifecycle',forbidden);monkeypatch.setattr(execution,'step_lifecycle',forbidden)
    restored,proof=restore_checkpoint(raw,root,sha256(raw).hexdigest(),bindings)
    assert restored.clock==state.clock and proof['materializer']=='EXPLICIT_KNOWN_OWNER_DATA_ONLY_NO_START_OR_PREFIX_REPLAY'
    assert restored.backend_context.actual is not restored.backend_context.forecast
    assert restored.backend_context.actual.snapshot()['cache_entries']==0
    assert restored.backend_context.selection=='PREPARED_PYTHON'
    assert restored.physical.context.spacecraft_state==state.physical.context.spacecraft_state

def test_legacy_v8_does_not_silently_admit_backend_field():
    root=root_for(60);state=start_lifecycle(root);bindings=make_bindings(root,state.clock)
    raw=checkpoint_bytes(state,bindings);doc=json.loads(raw)
    assert doc['format']=='B61_EXPOSURE_THERMAL_CHECKPOINT_V8'
    doc['backend']={};altered=canonical(doc).encode()
    with pytest.raises(ValueError):admit_checkpoint(altered,root,sha256(altered).hexdigest(),bindings)


def test_native_direct_restore_has_independent_private_counter_zero():
    from lifetime_support import SOURCE
    root=root_for(60)
    build=json.loads((SOURCE/'ops_sim/v5/lifecycle_native_build_receipt.json').read_bytes())
    state=start_lifecycle(root,backend='PREPARED_NATIVE',source_binding=current_source_binding(),backend_build=build)
    bindings=make_bindings(root,state.clock);raw=checkpoint_bytes(state,bindings)
    restored,proof=restore_checkpoint(raw,root,sha256(raw).hexdigest(),bindings)
    monitor=proof['native_entry_monitor']
    assert monitor['format']=='B63_NATIVE_RESTORE_ZERO_V1'
    assert monitor['total_delta']==0 and len(monitor['delta'])==17
    assert all(v==0 for v in monitor['delta'].values())
    assert monitor['before']==monitor['after']
    assert monitor['build_sha256']==sha256(canonical(build).encode()).hexdigest()
    assert restored.backend_context.selection=='PREPARED_NATIVE'


def test_native_restore_proof_rejects_even_one_owner_entry():
    from copy import deepcopy
    from lifetime_support import SOURCE
    from ops_sim.v5.lifecycle_backend import admit_native_build,native_restore_proof
    build=json.loads((SOURCE/'ops_sim/v5/lifecycle_native_build_receipt.json').read_bytes())
    before=admit_native_build(build).native_entry_counts();after=deepcopy(before)
    after['counts']['solve_port']+=1;after['total']+=1
    with pytest.raises(ValueError,match='during direct restore'):
        native_restore_proof(before,after,build,current_source_binding())


@pytest.fixture(scope='module')
def prepared_restore_packet():
    root=root_for(60)
    state=start_lifecycle(root,backend='PREPARED_PYTHON',source_binding=current_source_binding())
    bindings=make_bindings(root,state.clock);raw=checkpoint_bytes(state,bindings)
    return root,raw,sha256(raw).hexdigest(),bindings


def _prepare_restore(packet):
    from ops_sim.v5.lifecycle_checkpoint import prepare_checkpoint_restore
    root,raw,digest,bindings=packet
    return prepare_checkpoint_restore(raw,root,digest,bindings)


def test_paid_preparation_transfers_exact_model_without_restore_gravity(monkeypatch,prepared_restore_packet):
    import ops_sim.v5.orbit_j2_gravity as gravity
    import ops_sim.v5.lifecycle_execution as execution
    root,raw,digest,bindings=prepared_restore_packet
    token=_prepare_restore(prepared_restore_packet)
    model=token._data['model'];context=token._context
    assert context.actual is not context.forecast
    assert context.actual.snapshot()['cache_entries']==context.forecast.snapshot()['cache_entries']==0
    def forbidden(*args,**kwargs):raise AssertionError('numerical/start/prefix call in direct RESTORE')
    monkeypatch.setattr(gravity,'_gravity',forbidden)
    monkeypatch.setattr(execution,'start_lifecycle',forbidden)
    monkeypatch.setattr(execution,'step_lifecycle',forbidden)
    restored,proof=restore_checkpoint(raw,root,digest,bindings,prepared=token)
    assert restored.model is model and restored.backend_context is context
    assert proof['preparation']['phase']=='CONSUMED'
    assert proof['preparation']['work']['take_attempts']==proof['preparation']['work']['take_completed']==1
    assert proof['validation_control_units']==proof['preparation']['logical_control_units']<=proof['validation_control_reserved_units']
    assert restored.backend_context.actual.snapshot()['cache_entries']==0
    assert token._data is token._codec is token._seal is None
    with pytest.raises(ValueError,match='single-use'):
        restore_checkpoint(raw,root,digest,bindings,prepared=token)


@pytest.mark.parametrize('change',['PID','root','checkpoint','bindings','data-pointer','model-edge','record','context-used','token-copy'])
def test_prepared_restore_refuses_foreign_or_mutated_local_owner(monkeypatch,prepared_restore_packet,change):
    from copy import copy,deepcopy
    import ops_sim.v5.lifecycle_checkpoint as owner
    root,raw,digest,bindings=prepared_restore_packet
    token=_prepare_restore(prepared_restore_packet)
    if change=='PID':
        pid=owner.os.getpid();monkeypatch.setattr(owner.os,'getpid',lambda:pid+1)
    if change=='root':root=deepcopy(root)
    if change=='checkpoint':digest='f'*64
    if change=='bindings':bindings=dict(bindings,clock=bindings['clock']+1)
    if change=='data-pointer':token._data=dict(token._data)
    if change=='model-edge':token._data['physical']=dict(token._data['physical'])
    if change=='record':token._data['work'].transitions_completed+=1
    if change=='context-used':token._context.leaf_entries+=1
    if change=='token-copy':token=copy(token)
    with pytest.raises(ValueError):restore_checkpoint(raw,root,digest,bindings,prepared=token)
    assert token.receipt()['phase']=='FAILED'
    assert token.receipt()['work']['take_attempts']==1
    assert token.receipt()['work']['take_completed']==0
    assert token.receipt()['logical_control_units']<=token.receipt()['control_reserved_units']


def test_prepared_restore_rechecks_current_raw_bytes(prepared_restore_packet):
    root,raw,digest,bindings=prepared_restore_packet
    token=_prepare_restore(prepared_restore_packet)
    with pytest.raises(ValueError,match='external SHA'):
        restore_checkpoint(raw+b' ',root,digest,bindings,prepared=token)
    assert token.receipt()['phase']=='FAILED'
    assert token.receipt()['work']['take_attempts']==1
    assert token.receipt()['work']['take_completed']==0


def test_prepared_restore_does_not_bypass_existing_state_guard(monkeypatch,prepared_restore_packet):
    import ops_sim.v5.lifecycle_checkpoint as owner
    root,raw,digest,bindings=prepared_restore_packet
    token=_prepare_restore(prepared_restore_packet)
    def refuse(*args,**kwargs):raise ValueError('original active-state guard failure')
    monkeypatch.setattr(owner,'guard_lifecycle',refuse)
    with pytest.raises(ValueError,match='original active-state guard failure'):
        restore_checkpoint(raw,root,digest,bindings,prepared=token)
    assert token.receipt()['phase']=='FAILED'
    assert token.receipt()['work']['take_completed']==1


def test_prepared_restore_requires_exact_capability(prepared_restore_packet):
    root,raw,digest,bindings=prepared_restore_packet
    with pytest.raises(TypeError,match='exact local'):
        restore_checkpoint(raw,root,digest,bindings,prepared=True)
