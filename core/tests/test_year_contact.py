"""YEAR-V3 CONTACT scope and dynamic admission regression."""
from copy import copy,deepcopy
from dataclasses import replace
from fractions import Fraction as Q
from pathlib import Path
import json,pickle
import pytest
from lifetime_support import root_for
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.lifecycle_execution import start_lifecycle
from ops_sim.v5.lifecycle_job_prepared import admit_job_root
from ops_sim.v5.lifecycle_backend import current_source_binding
from ops_sim.v5.lifecycle_typed_context import TypedContactBinding
from ops_sim.v5.lifecycle_physics import _forcing
from ops_sim.v5.contact_execution import (ContactPlan,ConsumedContacts,validate_contact_plan,
    _validate_contact_plan,_prepare_contact,_ContactPreparation,_CONTACT_KEY,_bind_contact_cut)
from ops_sim.v5.integration_time import IntegrationPolicy
from ops_sim.v5.coupled_downlink import CoupledDownlinkInputs
from ops_sim.v5.operational_protection import StandbyInputs
from ops_sim.v5.communications import ServiceableGroundContact
from ops_sim.v5.ids import GroundContactId,GroundStationId,AcquisitionDataRecordId
from ops_sim.v5.experiment_codec import canonical_content


def started():
    source=Path(__file__).resolve().parents[1]
    build=json.loads((source/'ops_sim/v5/lifecycle_typed65_build_receipt.json').read_bytes())
    binding=current_source_binding();raw=dumps_root(root_for(600))
    root,token=admit_job_root(raw,binding,build_binding=build)
    return start_lifecycle(root,backend=build['execution_domain'],source_binding=binding,
        backend_build=build,job_admission=token)


def arguments(physical):
    f,_,_,_,_=_forcing(physical,physical.harness.hardware,Q(128),Q(129),physical.attitude.quaternion)
    tx=CoupledDownlinkInputs(physical.inputs.transmitter,f.loads,f.sunlit,f.incidence_angle_deg,
        physical.inputs.routing,f.thermal_inputs,f.external_heat_sources,None)
    idle=StandbyInputs(f.loads,f.sunlit,f.incidence_angle_deg,f.routing_config,
        f.thermal_inputs,f.external_heat_sources,None,'YEAR-V3 current forcing')
    contact=ServiceableGroundContact(GroundContactId('year3.cut'),GroundStationId('year3.station'),128,129)
    return ContactPlan(contact,(),tx,idle),ConsumedContacts(()),physical.inputs.protection,IntegrationPolicy(2)


def test_operation_local_admission_matches_full_public_contract_and_closes():
    state=started();ctx=state.backend_context;physical=state.physical
    with ctx.transaction():
        plan,consumed,policy,integration=arguments(physical)
        binding=TypedContactBinding(physical)
        token=_prepare_contact(binding,physical.context,policy,integration)
        expected=validate_contact_plan(physical.context,plan,consumed,policy,integration)
        actual=_validate_contact_plan(physical.context,plan,consumed,policy,integration,token)
        assert canonical_content(actual)==canonical_content(expected)
        token.close()
        with pytest.raises(ValueError,match='stale'):
            _validate_contact_plan(physical.context,plan,consumed,policy,integration,token)


@pytest.mark.parametrize('mutation',['clock','records','consumed','partial','forcing','policy','integration','foreign_inputs'])
def test_preparation_never_grants_dynamic_cut_admission(mutation):
    state=started();ctx=state.backend_context;p=state.physical
    with ctx.transaction():
        plan,consumed,policy,integration=arguments(p)
        token=_prepare_contact(TypedContactBinding(p),p.context,policy,integration)
        candidate=deepcopy(p.context,{id(p.context.inputs):p.context.inputs})
        _bind_contact_cut(token,candidate)
        if mutation=='clock':candidate.simulation_time_seconds=129
        elif mutation=='records':plan=replace(plan,record_ids=(AcquisitionDataRecordId('absent'),))
        elif mutation=='consumed':consumed=ConsumedContacts((plan.contact,))
        elif mutation=='partial':
            # An invalid boolean dynamic state must fail the retained schema roundtrip.
            candidate.spacecraft_state.battery.energy_wh=True
        elif mutation=='forcing':plan=replace(plan,idle_inputs=replace(plan.idle_inputs,sunlit=not plan.idle_inputs.sunlit))
        elif mutation=='policy':policy=replace(policy,rationale=policy.rationale+' changed')
        elif mutation=='integration':integration=IntegrationPolicy(1)
        else:candidate.inputs=deepcopy(candidate.inputs)
        with pytest.raises((ValueError,TypeError)):
            _validate_contact_plan(candidate,plan,consumed,policy,integration,token)
        token.close()


def test_callback_epoch_restart_and_forecast_are_not_shared_capabilities():
    state=started();ctx=state.backend_context;p=state.physical
    with ctx.transaction():
        plan,consumed,policy,integration=arguments(p)
        token=_prepare_contact(TypedContactBinding(p),p.context,policy,integration)
        ctx.job._validation.callback_begin()
        with pytest.raises(ValueError,match='stale'):
            token.check(p.context,policy,integration)
        ctx.job._validation.callback_end()
        with pytest.raises(ValueError,match='stale'):
            token.check(p.context,policy,integration)
        for fn in (copy,deepcopy,pickle.dumps):
            with pytest.raises(TypeError):fn(token)
        token.close()
    with ctx.transaction():
        with pytest.raises(ValueError,match='stale'):token.check(p.context,policy,integration)
        fresh=_prepare_contact(TypedContactBinding(p),p.context,policy,integration)
        assert fresh is not token
        fresh.check(p.context,policy,integration);fresh.close()


def test_factory_cannot_be_constructed_with_foreign_key_or_outside_transaction():
    state=started();ctx=state.backend_context;p=state.physical
    with pytest.raises(ValueError):TypedContactBinding(p)
    with ctx.transaction():
        plan,consumed,policy,integration=arguments(p);binding=TypedContactBinding(p)
        with pytest.raises(ValueError,match='factory'):
            _ContactPreparation(binding,p.context,policy,integration,object())


def test_actual_and_forecast_have_distinct_preparations_and_mutable_state():
    from ops_sim.v5.lifecycle_execution import _estimate
    state=started();ctx=state.backend_context;p=state.physical
    with ctx.transaction():
        forecast=_estimate(state)
        assert forecast.prepared_runtime is ctx.forecast and p.prepared_runtime is ctx.actual
        assert forecast.context is not p.context
        assert forecast.context.spacecraft_state is not p.context.spacecraft_state
        plan,consumed,policy,integration=arguments(p)
        actual=_prepare_contact(TypedContactBinding(p),p.context,policy,integration)
        other=_prepare_contact(TypedContactBinding(forecast),forecast.context,policy,integration)
        assert actual is not other and actual.binding.runtime is not other.binding.runtime
        with pytest.raises(ValueError,match='foreign'):
            actual.check(forecast.context,policy,integration)
        with pytest.raises(ValueError,match='foreign'):
            other.check(p.context,policy,integration)
        actual.close();other.close()
