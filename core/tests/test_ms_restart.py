"""Real version-6 JSON restart and replay validation of causal product evidence."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from examples.v5_ms_mission_demo import build_demo_state, summarize
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content, content_digest, check_schema_coverage
from ops_sim.v5.ms_continuation import MSMissionState, advance_ms_mission
from ops_sim.v5.ms_product import MSProductAssessment
from ops_sim.v5.contact_execution import ConsumedContacts

ROOT=Path(__file__).resolve().parents[1]


def advance(s,n):
    for _ in range(n):s=advance_ms_mission(s)
    return s


@pytest.fixture(scope="module")
def partial():return advance(build_demo_state(),3)


def test_fresh_process_keeps_partial_custody_attitude_consumed_and_credit(partial,tmp_path):
    saved=tmp_path/'saved.json';out=tmp_path/'resumed.json'
    saved.write_text(create_bundle(partial,repository_root=ROOT).to_json(),encoding='utf-8')
    cmd=[sys.executable,'-B','-c',
        "import sys; from pathlib import Path; from examples import v5_ms_mission_demo as d; "
        "d.build_demo_state=lambda *a,**k: (_ for _ in ()).throw(AssertionError('fixture rebuild forbidden')); "
        "d.main(['--resume',sys.argv[1],'--output',sys.argv[2]])",str(saved),str(out)]
    proc=subprocess.run(cmd,cwd=ROOT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
    assert proc.returncode==0,proc.stdout+proc.stderr
    expected=json.loads(json.dumps(summarize(advance(partial,2))))
    assert json.loads(out.read_text(encoding='utf-8'))==expected
    assert expected['metrics']['credited_products']==1
    assert partial.context.ground_data_delivery_state.partial_transfers[0].transmitted_equivalent_bits==40000000.
    assert len(partial.memory.consumed_contacts.contacts)==1 and partial.memory.acquisitions


@pytest.mark.parametrize("tamper", ["credit","consumed","association","outcome","previous"])
def test_reencoded_rehashed_false_causal_memory_rejected(partial,tamper):
    memory=partial.memory
    if tamper=='credit':memory=replace(memory,assessment=MSProductAssessment('credited',(),(memory.acquisitions[0].record.record_id,),Fraction(140)))
    if tamper=='consumed':memory=replace(memory,consumed_contacts=ConsumedContacts(()))
    if tamper=='association':memory=replace(memory,acquisitions=(replace(memory.acquisitions[0],plan=replace(memory.acquisitions[0].plan,capture_group='forged')),))
    if tamper=='outcome':memory=replace(memory,outcomes=memory.outcomes[:-1])
    if tamper=='previous':memory=replace(memory,previous_execution=partial.program.initial_attitude)
    payload=json.loads(create_bundle(partial,repository_root=ROOT).to_json())
    payload['memory']=canonical_content(memory)
    payload['runtime_digest']=content_digest('v5-continuation-state-v1',{k:payload[k] for k in ('input_digest','checkpoint','memory')})
    payload['bundle_digest']=content_digest('v5-experiment-bundle-v1',{k:v for k,v in payload.items() if k!='bundle_digest'})
    with pytest.raises(ValueError,match='replay'):
        ExperimentBundle.from_json(json.dumps(payload))


@pytest.mark.parametrize("which", ['deadline','spectral-provenance','initial-attitude','integration'])
def test_new_causal_inputs_change_identity(partial,which):
    p=partial.program
    if which=='deadline':q=replace(p,product=replace(p.product,delivery_deadline_seconds=230))
    if which=='initial-attitude':q=replace(p,initial_attitude=replace(p.initial_attitude,rationale='A different declared initial attitude provenance.'))
    if which=='integration':q=replace(p,integration=replace(p.integration,subdivision_level=3))
    if which=='spectral-provenance':
        a=p.actions[0];q=replace(p,actions=(replace(a,acquisition=replace(a.acquisition,capability_rationale='A different spectral assumption.')),*p.actions[1:]))
    assert experiment_input_digest(partial.context.inputs,p)!=experiment_input_digest(partial.context.inputs,q)
    b=create_bundle(partial,repository_root=ROOT)
    with pytest.raises(ValueError,match='program/forcing'):
        b.restore(repository_root=ROOT,expected_program=q)


def test_schema5_unchanged_and_work_history_gaps_reject():
    from ops_sim.v5.checkpoint import CURRENT_CHECKPOINT_SCHEMA_VERSION
    s=build_demo_state();p=s.program
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION==5
    check_schema_coverage()
    with pytest.raises(ValueError,match='version'):
        replace(p,version=5)
    with pytest.raises(ValueError,match='gaps'):
        replace(p,actions=(p.actions[0],*p.actions[2:]))
    with pytest.raises(ValueError,match='work'):
        replace(p,integration=replace(p.integration,subdivision_level=12))
    with pytest.raises(ValueError,match='producer'):
        replace(p,actions=(p.actions[2],))


def test_full_memory_required_and_failed_advance_preserves_input(partial):
    before=summarize(partial)
    forged=deepcopy(partial.memory);object.__setattr__(forged,'acquisitions',())
    with pytest.raises(ValueError,match='replay'):
        MSMissionState(partial.context,partial.program,forged)
    assert summarize(partial)==before
