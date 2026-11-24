"""Version-7 fresh-process reproduction and independently rehashed false histories."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from examples.v5_ms_campaign_demo import build_demo_state, run
from ops_sim.v5.campaign_continuation import advance_campaign, campaign_summary, start_campaign
from ops_sim.v5.experiment_bundle import ExperimentBundle, create_bundle, experiment_input_digest
from ops_sim.v5.experiment_codec import canonical_content, content_digest, check_schema_coverage


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def partial():
    state, reason = run(build_demo_state(), stop_after=4)
    assert reason == 'requested-boundary-pause'
    assert state.memory.feedback.partial_transfers[0].transmitted_equivalent_bits == 40000000.
    return state


def test_real_fresh_process_restart_has_equal_decisions_custody_physics_and_credit(partial, tmp_path):
    saved, output = tmp_path/'campaign.json', tmp_path/'resumed.json'
    saved.write_text(create_bundle(partial, repository_root=ROOT).to_json(), encoding='utf-8')
    command = [sys.executable, '-B', '-c',
        "import sys; from examples import v5_ms_campaign_demo as d; "
        "d.build_demo_state=lambda **k: (_ for _ in ()).throw(AssertionError('fixture reconstruction forbidden')); "
        "raise SystemExit(d.main(['--resume',sys.argv[1],'--output',sys.argv[2]]))", str(saved), str(output)]
    result = subprocess.run(command, cwd=ROOT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'}, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout+result.stderr
    actual = json.loads(output.read_text(encoding='utf-8'))
    for key in ('execution_wall_seconds', 'timing_scope', 'stop_reason'):
        actual.pop(key)
    final, reason = run(partial)
    assert reason is None
    assert actual == json.loads(json.dumps(campaign_summary(final)))


@pytest.mark.parametrize('tamper', ['telemetry', 'timestamp', 'ack', 'plan', 'history', 'rejection'])
def test_rehashed_inconsistent_causal_evidence_is_rejected(partial, tamper):
    memory = partial.memory
    if tamper == 'telemetry':
        f = memory.initial_feedback
        memory = replace(memory, initial_feedback=replace(f, resources=replace(f.resources, battery_energy_wh=f.resources.battery_energy_wh-1)))
    elif tamper == 'timestamp':
        f = memory.initial_feedback
        memory = replace(memory, initial_feedback=replace(f, sampled_at_seconds=99, received_at_seconds=99))
    elif tamper == 'ack':
        d = memory.decisions[-1]
        memory = replace(memory, decisions=(*memory.decisions[:-1], replace(d, feedback=replace(d.feedback, services=()))))
    elif tamper == 'plan':
        d = memory.decisions[0]; a = d.plan.actions[0]
        memory = replace(memory, decisions=(replace(d, plan=replace(d.plan,
            actions=(replace(a, identity='op-b'), *d.plan.actions[1:]))), *memory.decisions[1:]))
    elif tamper == 'history':
        memory = replace(memory, decisions=memory.decisions[:-1])
    else:
        d = memory.decisions[0]
        memory = replace(memory, decisions=(replace(d, plan=replace(d.plan, rejected=(('op-a', 'invented'),))), *memory.decisions[1:]))
    payload = json.loads(create_bundle(partial, repository_root=ROOT).to_json())
    payload['memory'] = canonical_content(memory)
    payload['runtime_digest'] = content_digest('v5-continuation-state-v1', {k:payload[k] for k in ('input_digest', 'checkpoint', 'memory')})
    payload['bundle_digest'] = content_digest('v5-experiment-bundle-v1', {k:v for k,v in payload.items() if k != 'bundle_digest'})
    with pytest.raises(ValueError, match='replay'):
        ExperimentBundle.from_json(json.dumps(payload))


@pytest.mark.parametrize('change', ['release', 'policy', 'knowledge', 'forcing', 'contact', 'hardware', 'integration'])
def test_campaign_identity_binds_every_causal_input(partial, change):
    inputs, p = partial.context.inputs, partial.program
    if change == 'release':
        p = replace(p, requests=(*p.requests[:2], replace(p.requests[2], release_seconds=126)))
    elif change == 'policy':
        p = replace(p, policy=replace(p.policy, standby_poll_seconds=29))
    elif change == 'knowledge':
        p = replace(p, knowledge=replace(p.knowledge, rationale='A separately declared knowledge assumption.'))
    elif change == 'forcing':
        f = p.forcing[0]
        p = replace(p, forcing=(replace(f, standby=replace(f.standby, sunlit=True)), *p.forcing[1:]))
    elif change == 'contact':
        p = replace(p, contacts=(replace(p.contacts[0], start_time_seconds=141), *p.contacts[1:]))
    elif change == 'hardware':
        cfg = inputs.spacecraft_configuration
        inputs = replace(inputs, spacecraft_configuration=replace(cfg, label=cfg.label+' content identity'))
    else:
        p = replace(p, integration=replace(p.integration, subdivision_level=1))
    assert experiment_input_digest(inputs, p) != experiment_input_digest(partial.context.inputs, partial.program)


def test_schema_and_legacy_ground_knowledge_remain_unchanged(partial):
    from ops_sim.v5.checkpoint import CURRENT_CHECKPOINT_SCHEMA_VERSION
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5
    check_schema_coverage()
    origin = partial.program.initial_checkpoint
    current = __import__('ops_sim.v5.checkpoint', fromlist=['CheckpointState']).CheckpointState.from_context(partial.context)
    assert current.ground_knowledge == origin.ground_knowledge
    assert current.mission == origin.mission and current.controller == origin.controller
    assert len(partial.memory.decisions) == 4
