"""Strict optional V5 authority, fixed native graph and direct continuation."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.lifecycle_contract import LifecycleRoot,LifecyclePolicy
from ops_sim.v5.lifecycle_quiet import QuietIntegrationPolicy
from ops_sim.v5.lifecycle_service import PowerServicePolicy
from ops_sim.v5.solar_attitude import EnergyAttitudePolicy
from ops_sim.v5.lifecycle_document import dumps_root,loads_root,canonical,FORMAT56
from ops_sim.v5.lifecycle_execution import start_lifecycle,step_lifecycle,scientific_projection
from ops_sim.v5.lifecycle_checkpoint import make_bindings,checkpoint_bytes,restore_checkpoint

def root(solar=True):
    return LifecycleRoot(make_inputs(wire='nominal'),600,policy=LifecyclePolicy(quiet_solver=QuietIntegrationPolicy()),service_policy=PowerServicePolicy(),energy_attitude_policy=EnergyAttitudePolicy() if solar else None)

def test_explicit_version_and_none_legacy_wire():
    old=root(False);new=replace(old,energy_attitude_policy=EnergyAttitudePolicy())
    assert 'energy_attitude_policy' not in json.loads(dumps_root(old))['inputs']
    d=json.loads(dumps_root(new));assert d['format']==FORMAT56 and d['version']==5
    assert old.identity!=new.identity and dumps_root(loads_root(dumps_root(new)))==dumps_root(new)

@pytest.mark.parametrize('field',['method','unknown','entry_usable_fraction'])
def test_changed_policy_fields_rejected_or_new_immutable_root(field):
    r=root();d=json.loads(dumps_root(r));p=d['inputs']['energy_attitude_policy']
    if field=='method':p[field]='invented'
    elif field=='unknown':p[field]=1
    else:p[field]=True
    d['digest']=sha256(canonical({k:d[k] for k in ('format','version','inputs')}).encode()).hexdigest()
    with pytest.raises((TypeError,ValueError)):loads_root(canonical(d).encode())

def test_native_charge_hold_direct_restore_full_science_and_future():
    r=root();s=start_lifecycle(r)
    # Default energy may stay MISSION initially. Use real steps, never an edited
    # advanced graph; this checks both optional state and future equality.
    s,_,_=step_lifecycle(s);bindings=make_bindings(r,s.clock);raw=checkpoint_bytes(s,bindings)
    restored,proof=restore_checkpoint(raw,r,sha256(raw).hexdigest(),bindings)
    assert scientific_projection(restored)==scientific_projection(s)
    assert restored.physical.context is not s.physical.context
    assert restored.actual_world is not restored.forecast_world
    a,_,_=step_lifecycle(s);b,_,_=step_lifecycle(restored)
    assert scientific_projection(a)==scientific_projection(b)
    with pytest.raises((TypeError,ValueError)):
        restore_checkpoint(raw,replace(r,energy_attitude_policy=replace(r.energy_attitude_policy,exit_usable_fraction=.8)),sha256(raw).hexdigest(),bindings)
