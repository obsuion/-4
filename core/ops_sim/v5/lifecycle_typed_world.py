"""Admission DATA for the compiled current-world forcing closure.

This module makes no orbit, Sun, lighting or orientation query.  Numerical
work is performed only by the bound compiled owner.  The provider's evolving
same-role grid/tail/lighting caches and scientific ledgers remain its owners.
"""
from fractions import Fraction
from .harness_hardware import EffectiveAssemblyHardware
from .lifecycle_job_prepared import PreparedRoleState, _copy_owned
from .lifecycle_orbit import LifecycleOrbitProvider
from .lifecycle_physics import LifecyclePhysicalState, PendingLifecycleAction
from .lifecycle_prepared import _Seal, _exact_tree
from .lifecycle_world import AcquiredLifecycleWorld

METHOD = 'B64_COMPILED_CURRENT_WORLD_FORCING_V1'


def admit_world_plan(physical, hardware, pending):
    from .lifecycle_typed_context import TypedBackendContext
    if (type(physical) is not LifecyclePhysicalState or
            type(hardware) is not EffectiveAssemblyHardware or
            type(pending) is not PendingLifecycleAction or pending.kind not in ('HOLD_UNTIL', 'SOLAR_HOLD') or
            pending.slew is not None or pending.payload_w != 0):
        raise TypeError('B64 closed world requires stationary admitted HOLD or SOLAR_HOLD')
    context = physical.backend_context; role = physical.prepared_runtime
    if (type(context) is not TypedBackendContext or type(role) is not PreparedRoleState or
            context.job is not role._job or context._role(physical) is not role or
            hardware is not physical.harness.hardware):
        raise ValueError('B64 foreign compiled world physical/job/role/hardware')
    transaction = role.require_transaction()
    context.guard(context.root, context.model)
    source, provider = physical.source_authority, physical.nominal_provider
    if (type(source) is not AcquiredLifecycleWorld or type(provider) is not LifecycleOrbitProvider or
            source.provider is not provider or source.role != role.role or provider.role != role.role or
            source.environment is not physical.inputs.environment or
            provider.trajectory is not source.environment.trajectory or provider.failed):
        raise ValueError('B64 exact same-role current world/provider required')
    provider.validate(source.environment.trajectory)
    world = role.model.environment
    profiles = tuple(e.start_seconds for e in world.profile)
    profile_cuts = tuple(e.end_seconds for e in world.profile[:-1])
    table_cuts = () if world.sun_table is None else tuple(Fraction(s.elapsed_seconds) for s in world.sun_table.samples[1:-1])
    if (_exact_tree(source._profiles) != _exact_tree(profiles) or
            _exact_tree(source._profile_cuts) != _exact_tree(profile_cuts) or
            _exact_tree(source._table_cuts) != _exact_tree(table_cuts)):
        raise ValueError('B64 stale current-world index')
    if _exact_tree(provider.model) != _exact_tree(world.trajectory.gravity_model):
        raise ValueError('B64 foreign original gravity authority')
    # The wrapper's separately versioned ledger prepays these bounded reads and
    # copies.  This never substitutes for original world/orbit scientific fees.
    context.reserve_world_plan(profile_count=len(world.profile), node_count=len(role.baseline.nodes),
                               profile_cuts=len(profile_cuts), table_cuts=len(table_cuts))
    policy = _copy_owned(provider.policy)
    gravity = world.trajectory.gravity_model
    ids = tuple(n.node_id for n in role.baseline.nodes)
    profile_data = []
    load_names = ('base_bus_w', 'obc_w', 'adcs_w', 'payload_w', 'communications_w', 'thermal_control_w', 'propulsion_w')
    for entry in world.profile:
        by_id = {n.node_id: n for n in entry.nodes}
        profile_data.append(dict(loads=tuple(getattr(entry.loads, n) for n in load_names),
            nodes=tuple((by_id[n].sink_temperature_k, by_id[n].internal_dissipation_w,
                         by_id[n].illuminated_solar_w, by_id[n].absorbed_albedo_w,
                         by_id[n].absorbed_earth_ir_w) for n in ids)))
    return dict(method=METHOD, role=role, transaction=transaction, context=context,
        physical=physical, pending=pending, source=source, provider=provider, world=world, policy=policy,
        mu=gravity.gravitational_parameter_m3_s2.value, j2=gravity.j2.value,
        gravity_radius=gravity.reference_radius_m.value,
        frame=world.trajectory.initial_state.position.frame,
        epoch=world.trajectory.initial_state.position.instant.epoch,
        origin=world.trajectory.initial_state.position.instant.elapsed_seconds,
        profiles=profiles, profile_cuts=profile_cuts, table_cuts=table_cuts,
        profile_data=tuple(profile_data), node_ids=ids,
        camera=tuple(hardware.camera_body_axis), panel=tuple(hardware.panel_body_normal),
        quaternion=tuple(physical.attitude.quaternion),
        attitude_tree=_exact_tree(physical.attitude),
        routing=role.model.routing, provider_charge=provider._charge, world_charge=source._charge,
        external_seal=_Seal((provider.policy, hardware)),
        external_pins=(physical.inputs.model, source.environment, provider.trajectory, provider.policy,
                       provider.work, provider._grid_states, provider._tails, source._lighting,
                       source._profiles, source._profile_cuts, source._table_cuts,
                       provider._charge, source._charge))
