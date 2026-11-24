"""B64 selected-result fold: direct typed records, no scientific wire trees.

The exact Fraction sums, binary64 subtraction/fsum order and selected-only
accounting mirror lifecycle_report.  The caller owns an atomic report clone;
this helper grants neither custody nor physical progress by itself.
"""
from dataclasses import fields
from fractions import Fraction as Q
from math import fsum

from .battery_port import BatteryPortState
from .battery_port_construction import PortConstructionPhysicalResult, PortServiceDiagnostic
from .construction_physics import ConstructionPhysicalResult
from .construction_service import ConstructionServiceDiagnostic
from .integration_time import DyadicDuration, RationalSeconds
from .lifecycle_job_prepared import PreparedRoleState
from .power_loads import PowerLoadBreakdown

METHOD = 'B64_TYPED_SELECTED_RESULT_FOLD_V1'
_LOADS = ('base_bus_w', 'obc_w', 'adcs_w', 'payload_w', 'communications_w',
          'thermal_control_w', 'propulsion_w')


def _duration(value):
    if type(value) is RationalSeconds:
        value.__post_init__()
        result = Q(value.numerator, value.denominator)
    elif type(value) is DyadicDuration:
        value.__post_init__()
        result = Q(value.numerator_seconds, 2**value.subdivision_level)
    else: raise TypeError('B64 report exact selected duration')
    if result <= 0: raise ValueError('B64 positive selected duration')
    return result


def _port(target, battery, state):
    from .battery_port_reporting import EXTREMA, SUMS
    if battery.method != 'B58_ASSUMED_ENERGY_SOC_RINT_PACK_V1' or type(state) is not BatteryPortState:
        raise ValueError('B64 selected port report identity')
    values = (battery.terminal_voltage_v, battery.terminal_voltage_v,
              abs(battery.current_a), battery.resistance_ohm, battery.resistance_ohm)
    for name, value in zip(EXTREMA, values):
        target[name] = value if target[name] is None else (min if name.startswith('minimum') else max)(target[name], value)
    for name in SUMS: target[name] += getattr(battery, name)
    target['selected_steps'] += 1
    # This small required public endpoint DATA is materialized, not a model tree.
    last = {f.name: getattr(state, f.name) for f in fields(BatteryPortState)}
    for name in ('clock_seconds', 'last_support_start_seconds'):
        value = last[name]
        if type(value) is Q: last[name] = dict(numerator=value.numerator, denominator=value.denominator)
    target['last'] = last


def _service(row, part, battery, rec, physical_dt, nodes):
    from .lifecycle_report import SERVICE_MODES, SERVICE_AUDIT_SUMS, pack, unpack
    service = part.service
    if type(service) not in (PortServiceDiagnostic, ConstructionServiceDiagnostic) or service.service_mode not in SERVICE_MODES:
        raise ValueError('B64 report requires returned selected service diagnostic')
    dt = _duration(battery.duration)
    start, end = Q(service.start_seconds), Q(service.end_seconds)
    if end - start != dt: raise ValueError('selected service/physical duration differs')
    mode = service.service_mode; target = row['power_service']
    target['mode_durations_seconds'][mode] = pack(unpack(target['mode_durations_seconds'][mode]) + dt)
    def total(loads):
        if type(loads) is not PowerLoadBreakdown: raise TypeError('B64 exact receiving component powers')
        return sum((Q(getattr(loads, name)) for name in _LOADS), Q())
    desired = total(service.desired_loads); commanded = total(service.commanded_loads); served = total(service.served_loads)
    essential = sum((Q(getattr(service.commanded_loads, name)) - Q(getattr(service.served_loads, name))
                     for name in ('base_bus_w', 'obc_w')), Q())
    values = dict(desired_normal_load_wh=desired*dt/3600, commanded_load_wh=commanded*dt/3600,
                  served_receiving_load_wh=served*dt/3600, commanded_shed_demand_wh=(desired-commanded)*dt/3600,
                  essential_unserved_wh=essential*dt/3600)
    for name, value in values.items():
        target['receiving_energy_wh'][name] = pack(unpack(target['receiving_energy_wh'][name]) + value)
    if mode == 'RECOVERY' and service.essential_fully_served:
        target['boot_work_seconds'] = pack(unpack(target['boot_work_seconds']) + dt)
    epoch = Q(target['audit_epoch_seconds']); day = int((start-epoch)//86400)
    audit = target['energy_audit']; matches = [item for item in audit if (item['day_index'], item['mode']) == (day, mode)]
    energy_sums = {name: Q() for name in SERVICE_AUDIT_SUMS}
    for name, key in (('generation_wh','generation_w'), ('requested_load_wh','load_w'),
                      ('unmet_load_wh','unmet_load_w'), ('charge_input_wh','charge_input_w'),
                      ('discharge_output_wh','discharge_output_w'), ('curtailed_generation_wh','curtailed_generation_w')):
        energy_sums[name] = Q(getattr(battery, key))*physical_dt/3600
    energy_sums['served_load_wh'] = Q(battery.load_w-battery.unmet_load_w)*physical_dt/3600
    energy_sums['wire_loss_wh'] = (Q(part.electrical.pv_wire_loss_w)+Q(part.electrical.receiving_wire_loss_w))*physical_dt/3600
    energy_sums['conversion_loss_wh'] = Q(battery.conversion_loss_wh)
    energy_sums['capacity_clip_wh'] = Q(rec.unavailable_energy_wh)
    minimum = min(battery.start_energy_wh, rec.authoritative_end_energy_wh)
    maximum_t = {n.node_id.value: max(n.start_temperature_k, n.end_temperature_k) for n in nodes}
    minimum_t = {n.node_id.value: min(n.start_temperature_k, n.end_temperature_k) for n in nodes}
    if not matches:
        if len(audit) >= 160: raise ValueError('B55_MONTH_DAY_MODE_AUDIT_CAPACITY')
        audit.append(dict(day_index=day, mode=mode, first_seconds=pack(start), last_seconds=pack(end), covered_seconds=pack(dt),
            support_contiguous=True, crosses_day_boundary=end > epoch+(day+1)*86400,
            start_energy_wh=battery.start_energy_wh, end_energy_wh=rec.authoritative_end_energy_wh, minimum_energy_wh=minimum,
            stored_delta_wh=pack(Q(rec.authoritative_end_energy_wh)-Q(battery.start_energy_wh)),
            sums={name: pack(value) for name, value in energy_sums.items()},
            receiving_energy_wh={name: pack(value) for name, value in values.items()},
            maximum_temperature_k=maximum_t, minimum_temperature_k=minimum_t))
    else:
        item = matches[0]
        if start < unpack(item['last_seconds']): raise ValueError('overlapping selected audit support')
        item['support_contiguous'] &= start == unpack(item['last_seconds'])
        item['crosses_day_boundary'] |= end > epoch+(day+1)*86400
        item['last_seconds'] = pack(end); item['covered_seconds'] = pack(unpack(item['covered_seconds'])+dt)
        item['end_energy_wh'] = rec.authoritative_end_energy_wh; item['minimum_energy_wh'] = min(item['minimum_energy_wh'], minimum)
        item['stored_delta_wh'] = pack(unpack(item['stored_delta_wh'])+Q(rec.authoritative_end_energy_wh)-Q(battery.start_energy_wh))
        for name, value in energy_sums.items(): item['sums'][name] = pack(unpack(item['sums'][name])+value)
        for name, value in values.items(): item['receiving_energy_wh'][name] = pack(unpack(item['receiving_energy_wh'][name])+value)
        for key in maximum_t:
            item['maximum_temperature_k'][key] = max(item['maximum_temperature_k'][key], maximum_t[key])
            item['minimum_temperature_k'][key] = min(item['minimum_temperature_k'][key], minimum_t[key])


def consume_prepared_part(row, part, runtime):
    """Fold one selected old typed record; no whole-output encode/decode."""
    from .lifecycle_report import _add
    if type(runtime) is not PreparedRoleState or runtime.role != 'ACTUAL':
        raise TypeError('B64 report exact ACTUAL role')
    runtime.require_transaction()
    runtime._job._charge(32, 'report_parts')
    return _consume_selected_part(row,part)


def _consume_selected_part(row,part):
    """Read one exact returned part; the caller owns the atomic report clone."""
    from .lifecycle_report import _add
    if type(part) not in (ConstructionPhysicalResult, PortConstructionPhysicalResult):
        raise TypeError('B64 exact selected physical result')
    p = part.physical; b = p.eps_result.battery; dt = Q(b.dt_seconds)
    rec = p.battery_capacity_reconciliation_result; authoritative = rec.authoritative_end_energy_wh
    row['minimum_energy_wh'] = min(row['minimum_energy_wh'], b.start_energy_wh, authoritative)
    row['end_energy_wh'] = authoritative
    nodes = p.thermal_coupling_result.thermal_result.node_transitions
    if {n.node_id.value for n in nodes} != set(row['maximum_temperature_k']):
        raise ValueError('physical/report thermal node sets differ')
    for n in nodes:
        key = n.node_id.value
        row['maximum_temperature_k'][key] = max(row['maximum_temperature_k'][key], n.start_temperature_k, n.end_temperature_k)
        row['minimum_temperature_k'][key] = min(row['minimum_temperature_k'][key], n.start_temperature_k, n.end_temperature_k)
    for name, source in (('generation_wh','generation_w'), ('requested_load_wh','load_w'),
            ('unmet_load_wh','unmet_load_w'), ('charge_input_wh','charge_input_w'),
            ('discharge_output_wh','discharge_output_w'), ('curtailed_generation_wh','curtailed_generation_w')):
        _add(row, name, Q(getattr(b, source))*dt/3600)
    _add(row, 'served_load_wh', Q(b.load_w-b.unmet_load_w)*dt/3600)
    _add(row, 'wire_loss_wh', (Q(part.electrical.pv_wire_loss_w)+Q(part.electrical.receiving_wire_loss_w))*dt/3600)
    _add(row, 'throughput_wh', p.battery_degradation_result.throughput_increment_wh)
    _add(row, 'conversion_loss_wh', b.conversion_loss_wh)
    _add(row, 'capacity_clip_wh', rec.unavailable_energy_wh)
    for name in ('calendar_damage', 'cycling_damage'): _add(row, name, getattr(p.battery_degradation_result, name))
    if p.solar_degradation_result is not None: _add(row, 'solar_retention_loss', p.solar_degradation_result.retention_loss)
    for ledger in p.thermal_coupling_result.node_heat_ledgers:
        _add(row, 'internal_heat_wh', Q(ledger.internal_dissipation_w)*dt/3600)
        _add(row, 'external_heat_wh', Q(fsum((ledger.absorbed_solar_w, ledger.absorbed_albedo_w, ledger.absorbed_earth_ir_w)))*dt/3600)
    cap = p.eps_capability_result.battery_usable_capacity_wh; endcap = rec.end_usable_capacity_wh
    first = b.start_energy_wh/cap; last = authoritative/endcap
    row['minimum_soc'] = min(row['minimum_soc'], first, last); row['end_soc'] = last
    if 'battery_port' in row: _port(row['battery_port'], b, part.port_state_after)
    if 'power_service' in row: _service(row, part, b, rec, dt, nodes)
    row['physical_substeps'] += 1


def consume_prepared_result(row, outcome, runtime):
    """Fold selected parts; return exact completing witnesses and actuator sums."""
    if type(runtime) is not PreparedRoleState or runtime.role != 'ACTUAL':
        raise TypeError('B64 report exact ACTUAL role')
    runtime.require_transaction()
    return _consume_selected_result(row,outcome,runtime)


def consume_selected_result(row,outcome):
    """B67 direct REFERENCE fold, without serializing the whole physical tree.

    This grants no prepared-role authority or cached physical result. Exact
    result types, selected-only traversal and rational addition order are the
    same as the prepared branch. No scientific work counters are changed.
    """
    return _consume_selected_result(row,outcome,None)


def _consume_selected_result(row,outcome,runtime):
    from .lifecycle_physics import LifecycleActionOutcome
    from .contact_execution import ContactOutcome, RecordService
    from .lifecycle_service_contact import ServiceContactOutcome
    from .construction_contact import ConstructionContactForcing, ConstructionContactEvaluation
    from .long_mission import MissionPhysicalCut
    if type(outcome) is not LifecycleActionOutcome:
        raise TypeError('B64 exact returned lifecycle outcome')
    if any(type(items) is not tuple for items in (outcome.cuts, outcome.contact_forcing, outcome.contact_outcomes)):
        raise TypeError('B64 exact selected result sequences')
    completing = {}
    for contact in outcome.contact_outcomes:
        if type(contact) not in (ContactOutcome, ServiceContactOutcome):
            raise TypeError('B64 exact returned contact outcome')
        for service in contact.services:
            if type(service) is not RecordService: raise TypeError('B64 exact returned record service')
            if service.completed:
                record = service.record; rid = record.record_id.value
                if rid in completing: raise ValueError('duplicate actual completing service')
                offset = service.end_offset
                completing[rid] = (record.imaging_request_id.value,
                    Q(contact.contact.start_time_seconds)+Q(offset.numerator, offset.denominator),
                    record.stored_equivalent_bits)
    count = 0
    for cut in outcome.cuts:
        if type(cut) is not MissionPhysicalCut: raise TypeError('B64 exact returned physical cut')
        if runtime is None:_consume_selected_part(row,cut.part)
        else:consume_prepared_part(row,cut.part,runtime)
        count += 1
    for forcing in outcome.contact_forcing:
        if type(forcing) is not ConstructionContactForcing: raise TypeError('B64 exact returned contact forcing')
        for evaluation in forcing.evaluations:
            if type(evaluation) is not ConstructionContactEvaluation or type(evaluation.selected) is not bool:
                raise TypeError('B64 exact returned contact evaluation')
            if evaluation.selected:
                for part in evaluation.parts:
                    if runtime is None:_consume_selected_part(row,part)
                    else:consume_prepared_part(row,part,runtime)
                    count += 1
    if outcome.end_seconds > outcome.start_seconds and not count:
        raise ValueError('covered physical interval lacks returned actual substeps')
    # Preserve per-cut exact addition order in the caller's existing report.
    actuator = tuple(Q(cut.actuator_draw_w)*(Q(cut.end_seconds)-Q(cut.start_seconds))/3600
                     for cut in outcome.cuts)
    return completing, actuator
