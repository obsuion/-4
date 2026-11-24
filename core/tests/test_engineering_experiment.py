from dataclasses import replace
import pytest
from examples.m5_command_mission_demo import make_inputs
from ops_sim.v5.engineering_experiment import ExperimentContract


def test_single_area_intervention_admits_other_inputs_exact():
    a,b=make_inputs(wire='weakness'),make_inputs(wire='repair')
    c=ExperimentContract('wire',a,b,'PAYLOAD_WIRE_CROSS_SECTION')
    assert c.max_cases==2 and a.requests==b.requests
    assert c.max_total_decisions==64 and c.max_total_forecasts==512
    assert a.model.augmentation.construction_digest!=b.model.augmentation.construction_digest


@pytest.mark.parametrize('field',['environment','protection','contacts','latency','FOV'])
def test_intervention_rejects_changed_common_rules(field):
    a,b=make_inputs(wire='weakness'),make_inputs(wire='repair')
    if field=='contacts':b=replace(b,reference=replace(b.reference,contacts=b.contacts[:-1]))
    if field=='latency':b=replace(b,reference=replace(b.reference,knowledge_mode=replace(b.knowledge_mode,latency_seconds=20)))
    if field=='FOV':b=replace(b,reference=replace(b.reference,model=replace(b.model,camera_half_fov_rad=b.model.camera_half_fov_rad*2)))
    if field=='protection':b=replace(b,reference=replace(b.reference,model=replace(b.model,protection=replace(b.model.protection,rationale=b.model.protection.rationale+' changed hypothesis'))))
    if field=='environment':b=replace(b,reference=replace(b.reference,model=replace(b.model,solar_retention_loss_per_second=.001)))
    with pytest.raises((ValueError,TypeError)):ExperimentContract('bad',a,b,'PAYLOAD_WIRE_CROSS_SECTION')


def test_policy_only_intervention_binds_exact_reference():
    b=make_inputs();ExperimentContract('estimation',b.reference,b,'COMMAND_ESTIMATION')
    with pytest.raises(ValueError):ExperimentContract('bad',make_inputs('outboard').reference,b,'COMMAND_ESTIMATION')


def test_wire_only_cannot_claim_placement():
    a,b=make_inputs(wire='weakness'),make_inputs(wire='repair')
    assert a.model.assembly==b.model.assembly
    with pytest.raises(ValueError,match='placement-only'):
        ExperimentContract('mislabel',a,b,'ASSEMBLY_PLACEMENT')


@pytest.mark.parametrize('hypothesis',['ASSEMBLY_PLACEMENT','PAYLOAD_WIRE_CROSS_SECTION'])
def test_no_op_is_not_a_repair(hypothesis):
    a=make_inputs()
    with pytest.raises(ValueError,match='NO_OP'):
        ExperimentContract('no-op',a,a,hypothesis)


def test_legitimate_two_battery_placement_and_recomputed_dependents():
    a,b=make_inputs('compact'),make_inputs('outboard')
    ExperimentContract('placement',a,b,'ASSEMBLY_PLACEMENT')
    assert a.model.configuration.assembly_digest!=b.model.configuration.assembly_digest
    assert a.model.augmentation.construction_digest!=b.model.augmentation.construction_digest


def test_combined_edit_cannot_claim_placement_or_wire_only():
    a,b=make_inputs('compact',wire='weakness'),make_inputs('outboard',wire='repair')
    for h in ('ASSEMBLY_PLACEMENT','PAYLOAD_WIRE_CROSS_SECTION'):
        with pytest.raises(ValueError):ExperimentContract('mixed',a,b,h)


def test_placement_rejects_rewritten_connector_material_and_slack():
    a,b=make_inputs('compact'),make_inputs('outboard')
    cfg=b.model.configuration
    line=next(l for l in cfg.lines if l.line_id=='payload-line')
    for changed in (replace(line,wire=replace(line.wire,density_kg_m3=line.wire.density_kg_m3*2)),
                    replace(line,wire=replace(line.wire,connector_mass_kg=line.wire.connector_mass_kg*2)),
                    replace(line,slack_m=line.slack_m+.001)):
        model=replace(b.model,configuration=replace(cfg,lines=tuple(changed if l.line_id==line.line_id else l for l in cfg.lines)))
        bad=replace(b,reference=replace(b.reference,model=model))
        with pytest.raises(ValueError):ExperimentContract('rewrite',a,bad,'ASSEMBLY_PLACEMENT')
