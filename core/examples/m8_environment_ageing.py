"""B61 explicit synthetic sensitivity; no calibrated lifetime equivalence."""
from dataclasses import replace
from examples.m8_battery_port import make_inputs as port_inputs
from ops_sim.v5.environment_ageing import EnvironmentAgeingPolicy,EmissivityAgeing,ConductanceAgeing
from ops_sim.v5.lifecycle_quiet import EnvironmentQuietIntegrationPolicy

def add_ageing(root,*,rate=1.e-6,thermal_rate=1.e-6,initial_calendar_seconds=0):
    network=root.base.model.simulation_inputs.spacecraft_configuration.thermal.network
    policy=EnvironmentAgeingPolicy(pv_floor_fraction=.7,pv_calendar_rate_per_second=rate/10.,pv_exposure_rate_per_second=rate,
        emissivity=tuple(sorted((EmissivityAgeing(n.node_id.value,.3,thermal_rate/10.,thermal_rate)for n in network.nodes),key=lambda x:x.node_id)),
        conductance=tuple(sorted((ConductanceAgeing(l.link_id.value,l.conductance_w_per_k.value*.7,thermal_rate/10.,thermal_rate)for l in network.links),key=lambda x:x.link_id)),
        initial_calendar_seconds=initial_calendar_seconds,assumption='SYNTHETIC_ACCELERATED_ASSUMED')
    quiet=None if root.policy.quiet_solver is None else EnvironmentQuietIntegrationPolicy()
    return replace(root,environment_ageing_policy=policy,policy=replace(root.policy,quiet_solver=quiet))

def make_inputs(*,duration=7200,energy=80.,rate=1.e-6,thermal_rate=1.e-6,integration='ADAPTIVE'):
    return add_ageing(port_inputs(duration=duration,energy=energy,integration=integration),rate=rate,thermal_rate=thermal_rate)
