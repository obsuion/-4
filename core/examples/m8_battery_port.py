"""Explicit ASSUMED B58 root creation; no advanced checkpoint retagging."""
from dataclasses import replace
from examples.m5_command_mission_demo import make_inputs as base_inputs
from ops_sim.v5.checkpoint import CheckpointState
from ops_sim.v5.lifecycle_contract import LifecycleRoot,LifecyclePolicy
from ops_sim.v5.lifecycle_service import PowerServicePolicy
from ops_sim.v5.solar_attitude import EnergyAttitudePolicy
from ops_sim.v5.lifecycle_quiet import BatteryQuietIntegrationPolicy
from ops_sim.v5.battery_port import BatteryPortPolicy

def make_inputs(*,duration=7200,energy=45.,initial_resistance_damage=0.,integration='ADAPTIVE'):
    base=base_inputs('compact',wire='nominal')
    context=base.initial_checkpoint.restore(base.model.simulation_inputs)
    context.spacecraft_state.battery.energy_wh=energy
    base=replace(base,reference=replace(base.reference,initial_checkpoint=CheckpointState.from_context(context)))
    if integration not in ('ADAPTIVE','DETAILED','FINER'):raise ValueError('explicit B58 integration')
    policy=LifecyclePolicy(quiet_solver=BatteryQuietIntegrationPolicy() if integration=='ADAPTIVE' else None,
        detailed_step_seconds=1 if integration=='FINER' else 2,
        quiet_step_seconds=30 if integration=='FINER' else 60,
        contact_integration_level=3 if integration=='FINER' else 2)
    return LifecycleRoot(base,duration,policy=policy,service_policy=PowerServicePolicy(),
        energy_attitude_policy=EnergyAttitudePolicy(),battery_port_policy=BatteryPortPolicy(initial_resistance_damage=initial_resistance_damage))
