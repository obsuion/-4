"""B52 bounded actual-month accounting with data-only strict admission.

Only the current row, cumulative sealed totals and a bounded boundary-event
handoff stay in working state.  Completed rows belong to the external stream.
All extrema are RETURNED/SAMPLED.  Exact rational sums preserve the returned
binary64 values; they do not certify the underlying physical approximation.
"""
from copy import deepcopy
from fractions import Fraction as Q
from hashlib import sha256
import math
from .lifecycle_contract import MONTH, METHOD55, canonical, integer, identity
from .solar_lifecycle import solar_report_blank,solar_report_combine,solar_report_delta,validate_solar_report

from .battery_port_reporting import (port_report_blank,port_report_part,port_report_combine,validate_port_report)

REPORT_METHOD = 'B52_STREAMED_ACTUAL_MONTH_ROWS_V1'
SUMS = ('generation_wh', 'requested_load_wh', 'served_load_wh', 'unmet_load_wh',
        'charge_input_wh', 'discharge_output_wh', 'curtailed_generation_wh',
        'wire_loss_wh', 'actuator_energy_wh', 'throughput_wh', 'conversion_loss_wh',
        'capacity_clip_wh', 'calendar_damage', 'cycling_damage',
        'solar_retention_loss', 'internal_heat_wh', 'external_heat_wh')
COUNTS = ('offered', 'credits', 'carry_in_credits', 'prior_bucket_credits', 'nonlocal_offer_credits',
          'expired', 'refused_actions', 'completed_actions', 'transitions',
          'executed_point_seconds', 'useful_bits', 'physical_substeps')
WEAR = ('battery_retention', 'solar_retention', 'throughput_wh')
TOTAL_FIELDS = set(COUNTS) | {'priority_numerator', 'priority_denominator',
    'start_energy_wh', 'minimum_energy_wh', 'end_energy_wh', 'start_soc',
    'minimum_soc', 'end_soc', 'maximum_temperature_k', 'minimum_temperature_k',
    'sums', 'wear_start', 'wear_end'}
ROW_FIELDS = TOTAL_FIELDS | {'bucket', 'start_seconds', 'end_seconds', 'seal'}
STATE_FIELDS = {'method', 'root_identity', 'scope', 'start_seconds', 'end_seconds',
    'next_transition', 'transition_base', 'offered_frontier', 'offer_base_frontier',
    'receipt_count', 'sealed_count', 'sealed_end_seconds', 'row_chain',
    'sealed_totals', 'current', 'status', 'pending_boundary_credits',
    'pending_boundary_expired'}
CREDIT_FIELDS = {'request_id', 'record_ids', 'priority', 'useful_bits',
                 'completion_time', 'released_at_seconds'}


SERVICE_REPORT_METHOD = 'B55_SELECTED_SERVICE_MODE_AND_RECEIVING_ENERGY_V1'
SERVICE_MODES = ('NORMAL','SAFE','POWER_OFF','RECOVERY')
SERVICE_RECEIVING = ('desired_normal_load_wh','commanded_load_wh','served_receiving_load_wh',
    'commanded_shed_demand_wh','essential_unserved_wh')
SERVICE_AUDIT_SUMS = ('generation_wh','requested_load_wh','served_load_wh','unmet_load_wh',
    'charge_input_wh','discharge_output_wh','curtailed_generation_wh','wire_loss_wh',
    'conversion_loss_wh','capacity_clip_wh')
SERVICE_BASE_FIELDS = {'method','mode_durations_seconds','mode_transitions','service_interruptions',
    'boot_work_seconds','selected_steps','receiving_energy_wh','transition_reasons','interrupted_actions','service_denied_actions'}
SERVICE_AUDIT_FIELDS = {'day_index','mode','first_seconds','last_seconds','covered_seconds',
    'support_contiguous','crosses_day_boundary','start_energy_wh','end_energy_wh','minimum_energy_wh',
    'stored_delta_wh','sums','receiving_energy_wh','maximum_temperature_k','minimum_temperature_k'}


def _service_row(*, row):
    from .lifecycle_service import REASONS
    result=dict(method=SERVICE_REPORT_METHOD,mode_durations_seconds={mode:pack(0) for mode in SERVICE_MODES},
        mode_transitions=0,service_interruptions=0,boot_work_seconds=pack(0),selected_steps=0,interrupted_actions=0,service_denied_actions=0,
        receiving_energy_wh={name:pack(0) for name in SERVICE_RECEIVING},
        transition_reasons={name:0 for name in REASONS})
    if row:result.update(energy_audit=[],audit_epoch_seconds=None)
    return result


def _combine_service(rows):
    result=_service_row(row=False)
    for row in rows:
        source=row['power_service']
        for mode in SERVICE_MODES:
            result['mode_durations_seconds'][mode]=pack(unpack(result['mode_durations_seconds'][mode])+unpack(source['mode_durations_seconds'][mode]))
        for name in ('mode_transitions','service_interruptions','selected_steps','interrupted_actions','service_denied_actions'):
            result[name]+=source[name]
        result['boot_work_seconds']=pack(unpack(result['boot_work_seconds'])+unpack(source['boot_work_seconds']))
        for name in SERVICE_RECEIVING:
            result['receiving_energy_wh'][name]=pack(unpack(result['receiving_energy_wh'][name])+unpack(source['receiving_energy_wh'][name]))
        for name,count in source['transition_reasons'].items():result['transition_reasons'][name]+=count
    return result


def _service_part(row,part,battery,rec,physical_dt,nodes):
    """Bounded per-day/mode groups of selected support, never a timestep cut."""
    service=part.get('service')
    if type(service) is not dict or service.get('service_mode') not in SERVICE_MODES:
        raise ValueError('new service report requires returned selected construction diagnostic')
    # Physical EPS/heat sums retain the accepted binary64 dt_seconds equations.
    # Selected service support is the owner's exact duration, which can be a
    # non-dyadic final CONTACT fraction. Q(float(dt)) is not that support.
    duration=battery.get('duration')
    if type(duration) is not dict:raise ValueError('selected service requires exact battery duration')
    if set(duration)=={'numerator','denominator'}:
        numerator,denominator=duration['numerator'],duration['denominator']
        if type(numerator) is not int or type(denominator) is not int or numerator<=0 or denominator<=0:
            raise ValueError('positive exact rational service duration')
        dt=Q(numerator,denominator)
    elif set(duration)=={'numerator_seconds','subdivision_level'}:
        numerator,level=duration['numerator_seconds'],duration['subdivision_level']
        if type(numerator) is not int or type(level) is not int or numerator<=0 or not 0<=level<=12:
            raise ValueError('positive bounded dyadic service duration')
        dt=Q(numerator,2**level)
    else:raise ValueError('unsupported exact service duration fields')
    def rational(value):
        if type(value) is dict and set(value)=={'numerator','denominator'}:
            return Q(value['numerator'],value['denominator'])
        return Q(value)
    start=rational(service['start_seconds']);end=rational(service['end_seconds'])
    if end-start!=dt:raise ValueError('selected service/physical duration differs')
    mode=service['service_mode'];target=row['power_service']
    target['mode_durations_seconds'][mode]=pack(unpack(target['mode_durations_seconds'][mode])+dt)
    def component_total(name):
        loads=service[name]
        if type(loads) is not dict:raise ValueError('source-owned component receiving powers required')
        return sum((Q(value) for value in loads.values()),Q())
    desired=component_total('desired_loads');commanded=component_total('commanded_loads');served=component_total('served_loads')
    essential=sum((Q(service['commanded_loads'][name])-Q(service['served_loads'][name]) for name in ('base_bus_w','obc_w')),Q())
    values=dict(desired_normal_load_wh=desired*dt/3600,commanded_load_wh=commanded*dt/3600,
        served_receiving_load_wh=served*dt/3600,commanded_shed_demand_wh=(desired-commanded)*dt/3600,
        essential_unserved_wh=essential*dt/3600)
    for name,value in values.items():target['receiving_energy_wh'][name]=pack(unpack(target['receiving_energy_wh'][name])+value)
    if mode=='RECOVERY' and service['essential_fully_served']:
        target['boot_work_seconds']=pack(unpack(target['boot_work_seconds'])+dt)
    epoch=Q(target['audit_epoch_seconds']);day=int((start-epoch)//86400)
    audit=target['energy_audit'];matches=[item for item in audit if (item['day_index'],item['mode'])==(day,mode)]
    energy_sums={name:Q() for name in SERVICE_AUDIT_SUMS}
    for name,key in (('generation_wh','generation_w'),('requested_load_wh','load_w'),
        ('unmet_load_wh','unmet_load_w'),('charge_input_wh','charge_input_w'),
        ('discharge_output_wh','discharge_output_w'),('curtailed_generation_wh','curtailed_generation_w')):
        energy_sums[name]=Q(battery[key])*physical_dt/3600
    energy_sums['served_load_wh']=Q(battery['load_w']-battery['unmet_load_w'])*physical_dt/3600
    energy_sums['wire_loss_wh']=(Q(part['electrical']['pv_wire_loss_w'])+Q(part['electrical']['receiving_wire_loss_w']))*physical_dt/3600
    energy_sums['conversion_loss_wh']=Q(battery['conversion_loss_wh'])
    energy_sums['capacity_clip_wh']=Q(rec['unavailable_energy_wh'])
    minimum=min(battery['start_energy_wh'],rec['authoritative_end_energy_wh'])
    maximum_t={n['node_id']['value']:max(n['start_temperature_k'],n['end_temperature_k']) for n in nodes}
    minimum_t={n['node_id']['value']:min(n['start_temperature_k'],n['end_temperature_k']) for n in nodes}
    if not matches:
        if len(audit)>=160:raise ValueError('B55_MONTH_DAY_MODE_AUDIT_CAPACITY')
        item=dict(day_index=day,mode=mode,first_seconds=pack(start),last_seconds=pack(end),covered_seconds=pack(dt),
            support_contiguous=True,crosses_day_boundary=end>epoch+(day+1)*86400,
            start_energy_wh=battery['start_energy_wh'],end_energy_wh=rec['authoritative_end_energy_wh'],minimum_energy_wh=minimum,
            stored_delta_wh=pack(Q(rec['authoritative_end_energy_wh'])-Q(battery['start_energy_wh'])),
            sums={name:pack(value) for name,value in energy_sums.items()},
            receiving_energy_wh={name:pack(value) for name,value in values.items()},
            maximum_temperature_k=maximum_t,minimum_temperature_k=minimum_t)
        audit.append(item)
    else:
        item=matches[0]
        if start<unpack(item['last_seconds']):raise ValueError('overlapping selected audit support')
        item['support_contiguous'] &= start==unpack(item['last_seconds'])
        item['crosses_day_boundary'] |= end>epoch+(day+1)*86400
        item['last_seconds']=pack(end);item['covered_seconds']=pack(unpack(item['covered_seconds'])+dt)
        item['end_energy_wh']=rec['authoritative_end_energy_wh'];item['minimum_energy_wh']=min(item['minimum_energy_wh'],minimum)
        item['stored_delta_wh']=pack(unpack(item['stored_delta_wh'])+Q(rec['authoritative_end_energy_wh'])-Q(battery['start_energy_wh']))
        for name,value in energy_sums.items():item['sums'][name]=pack(unpack(item['sums'][name])+value)
        for name,value in values.items():item['receiving_energy_wh'][name]=pack(unpack(item['receiving_energy_wh'][name])+value)
        for key in maximum_t:
            item['maximum_temperature_k'][key]=max(item['maximum_temperature_k'][key],maximum_t[key])
            item['minimum_temperature_k'][key]=min(item['minimum_temperature_k'][key],minimum_t[key])


def _service_work_delta(row,outcome):
    from .lifecycle_service import PowerServiceWork
    before=getattr(outcome,'service_work_before',None);after=getattr(outcome,'service_work_after',None)
    if type(before) is not PowerServiceWork or type(after) is not PowerServiceWork:
        raise ValueError('selected service report requires before/after immutable work snapshots')
    before.__post_init__();after.__post_init__()
    target=row['power_service']
    for name,source in (('mode_transitions','transitions'),('service_interruptions','service_interruptions'),('selected_steps','selected_steps')):
        value=getattr(after,source)-getattr(before,source)
        if value<0:raise ValueError('selected service work regressed')
        target[name]+=value
    old=dict(before.transition_reasons);new=dict(after.transition_reasons)
    for reason in target['transition_reasons']:
        delta=new.get(reason,0)-old.get(reason,0)
        if delta<0:raise ValueError('selected mode cause count regressed')
        target['transition_reasons'][reason]+=delta
    if after.covered_seconds-before.covered_seconds!=outcome.end_seconds-outcome.start_seconds:
        raise ValueError('service work/actual outcome support differs')
def _fields(value, expected, label):
    if type(value) is not dict or set(value) != expected:
        raise ValueError('exact lifecycle '+label+' fields required')


def _finite(value, label, low=0., high=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < low or (high is not None and value > high):
        raise ValueError('finite lifecycle '+label+' required')
    return value


def pack(value):
    if type(value) not in (int, float, Q) or type(value) is float and not math.isfinite(value):
        raise ValueError('finite exact lifecycle report value')
    q = Q(value)
    result = [str(q.numerator), str(q.denominator)]
    if any(len(x) > 1235 for x in result): raise ValueError('report rational size')
    return result


def unpack(value):
    if type(value) is not list or len(value) != 2 or any(type(x) is not str or len(x) > 1235 for x in value):
        raise ValueError('lifecycle report rational')
    q = Q(int(value[0]), int(value[1]))
    if pack(q) != value: raise ValueError('report rational spelling')
    return q


def _add(row, name, value):
    row['sums'][name] = pack(unpack(row['sums'][name])+Q(value))


def _wear(context):
    d = context.spacecraft_state.degradation
    return dict(battery_retention=d.battery.usable_capacity_retention,
                solar_retention=d.solar.generation_retention,
                throughput_wh=d.battery.cumulative_energy_throughput_wh)


def _temps(context):
    return {n.node_id.value: n.temperature_k for n in context.spacecraft_state.thermal.node_states}


def _soc(context):
    from .eps_capability import compute_eps_capability
    c = compute_eps_capability(context.inputs.spacecraft_configuration.eps,
                               context.spacecraft_state.degradation)
    return context.spacecraft_state.battery.energy_wh/c.battery_usable_capacity_wh


def _row(root, time, context):
    energy = context.spacecraft_state.battery.energy_wh; soc = _soc(context)
    result=dict(bucket=(time+root.policy.month_epoch_offset_seconds)//root.policy.month_period_seconds,
        start_seconds=time, end_seconds=time, seal=None, **{n: 0 for n in COUNTS},
        priority_numerator=pack(0), priority_denominator=pack(0),
        start_energy_wh=energy, minimum_energy_wh=energy, end_energy_wh=energy,
        start_soc=soc, minimum_soc=soc, end_soc=soc,
        maximum_temperature_k=_temps(context), minimum_temperature_k=_temps(context),
        sums={n: pack(0) for n in SUMS}, wear_start=_wear(context), wear_end=_wear(context))
    if root.method==METHOD55:
        result['power_service']=_service_row(row=True)
        result['power_service']['audit_epoch_seconds']=root.start_seconds
    if root.battery_port_policy is not None:result['battery_port']=port_report_blank(root.battery_port_policy)
    if root.energy_attitude_policy is not None:result['solar_attitude']=solar_report_blank(root.energy_attitude_policy)
    return result


def combine(rows):
    if not rows: raise ValueError('report needs explicit initial coverage')
    keys = set(rows[0]['maximum_temperature_k'])
    if any(set(r['maximum_temperature_k']) != keys or set(r['minimum_temperature_k']) != keys for r in rows):
        raise ValueError('report thermal node sets differ')
    result=dict(**{n: sum(r[n] for r in rows) for n in COUNTS},
        priority_numerator=pack(sum((unpack(r['priority_numerator']) for r in rows), Q())),
        priority_denominator=pack(sum((unpack(r['priority_denominator']) for r in rows), Q())),
        start_energy_wh=rows[0]['start_energy_wh'],
        minimum_energy_wh=min(r['minimum_energy_wh'] for r in rows), end_energy_wh=rows[-1]['end_energy_wh'],
        start_soc=rows[0]['start_soc'], minimum_soc=min(r['minimum_soc'] for r in rows), end_soc=rows[-1]['end_soc'],
        maximum_temperature_k={k: max(r['maximum_temperature_k'][k] for r in rows) for k in keys},
        minimum_temperature_k={k: min(r['minimum_temperature_k'][k] for r in rows) for k in keys},
        sums={n: pack(sum((unpack(r['sums'][n]) for r in rows), Q())) for n in SUMS},
        wear_start=deepcopy(rows[0]['wear_start']), wear_end=deepcopy(rows[-1]['wear_end']))
    if 'battery_port' in rows[0]:result['battery_port']=port_report_combine([r['battery_port']for r in rows])
    if 'power_service' in rows[0]:result['power_service']=_combine_service(rows)
    if 'solar_attitude' in rows[0]:result['solar_attitude']=solar_report_combine([r['solar_attitude'] for r in rows])
    return result


def _part(row, part):
    p = part['physical']; b = p['eps_result']['battery']; dt = Q(b['dt_seconds'])
    rec = p['battery_capacity_reconciliation_result']; authoritative = rec['authoritative_end_energy_wh']
    row['minimum_energy_wh'] = min(row['minimum_energy_wh'], b['start_energy_wh'], authoritative)
    row['end_energy_wh'] = authoritative
    nodes = p['thermal_coupling_result']['thermal_result']['node_transitions']
    if {n['node_id']['value'] for n in nodes} != set(row['maximum_temperature_k']):
        raise ValueError('physical/report thermal node sets differ')
    for n in nodes:
        key = n['node_id']['value']
        row['maximum_temperature_k'][key] = max(row['maximum_temperature_k'][key], n['start_temperature_k'], n['end_temperature_k'])
        row['minimum_temperature_k'][key] = min(row['minimum_temperature_k'][key], n['start_temperature_k'], n['end_temperature_k'])
    for name, source in (('generation_wh', 'generation_w'), ('requested_load_wh', 'load_w'),
            ('unmet_load_wh', 'unmet_load_w'), ('charge_input_wh', 'charge_input_w'),
            ('discharge_output_wh', 'discharge_output_w'), ('curtailed_generation_wh', 'curtailed_generation_w')):
        _add(row, name, Q(b[source])*dt/3600)
    # The accepted property's float subtraction is authoritative; do not replace
    # it with a different exact-rational subtraction of its input floats.
    _add(row, 'served_load_wh', Q(b['load_w']-b['unmet_load_w'])*dt/3600)
    _add(row, 'wire_loss_wh', (Q(part['electrical']['pv_wire_loss_w'])+Q(part['electrical']['receiving_wire_loss_w']))*dt/3600)
    _add(row, 'throughput_wh', p['battery_degradation_result']['throughput_increment_wh'])
    _add(row, 'conversion_loss_wh', b['conversion_loss_wh'])
    _add(row, 'capacity_clip_wh', rec['unavailable_energy_wh'])
    for name in ('calendar_damage', 'cycling_damage'): _add(row, name, p['battery_degradation_result'][name])
    if p['solar_degradation_result'] is not None:
        _add(row, 'solar_retention_loss', p['solar_degradation_result']['retention_loss'])
    for ledger in p['thermal_coupling_result']['node_heat_ledgers']:
        _add(row, 'internal_heat_wh', Q(ledger['internal_dissipation_w'])*dt/3600)
        _add(row, 'external_heat_wh', Q(math.fsum((ledger['absorbed_solar_w'], ledger['absorbed_albedo_w'], ledger['absorbed_earth_ir_w'])))*dt/3600)
    cap = p['eps_capability_result']['battery_usable_capacity_wh']; endcap = rec['end_usable_capacity_wh']
    first = b['start_energy_wh']/cap; last = authoritative/endcap
    row['minimum_soc'] = min(row['minimum_soc'], first, last); row['end_soc'] = last
    if 'battery_port' in row:port_report_part(row['battery_port'],b,part['port_state_after'])
    if 'power_service' in row:_service_part(row,part,b,rec,dt,nodes)
    row['physical_substeps'] += 1


class LifecycleReport:
    def __init__(self, root, context, *, state=None, window=False,
                 offered_frontier=None, transition_frontier=0,environment_ageing_state=None,prepared_runtime=None):
        self.root = root
        template = root.base.requests[root.scenario.request_index].product
        self._expected_weight = Q(template.request.priority_weight)
        from .ms_product import size_ms_grid, REQUIRED_MS_CHANNELS
        optical = root.base.model.simulation_inputs.spacecraft_configuration.payload.optical_acquisition
        spacing = optical.multispectral_reference_sample_spacing_m.value
        self._expected_bits = size_ms_grid(template.footprint, spacing, spacing,
            REQUIRED_MS_CHANNELS, int(optical.acquisition_bits_per_sample.value)).stored_bits
        if type(window) is not bool: raise ValueError('explicit report scope')
        if state is None:
            t = context.simulation_time_seconds
            if not window and t != root.start_seconds: raise ValueError('main report requires original initial boundary')
            if offered_frontier is None:
                # Strictly earlier releases only. At an equal-time event the
                # coordinator supplies its saved frontier explicitly.
                offered_frontier = (min(root.offered_population, max(0,
                    (t-root.start_seconds+root.scenario.cadence_seconds-1)//root.scenario.cadence_seconds)) if window else 0)
            integer(offered_frontier, 'report offer base', 0, root.offered_population)
            integer(transition_frontier, 'report transition base')
            self.state = dict(method=REPORT_METHOD, root_identity=root.identity,
                scope='WINDOW' if window else 'MAIN', start_seconds=t, end_seconds=t,
                next_transition=transition_frontier, transition_base=transition_frontier,
                offered_frontier=offered_frontier, offer_base_frontier=offered_frontier,
                receipt_count=0, sealed_count=0, sealed_end_seconds=t, row_chain='0'*64,
                sealed_totals=None, current=_row(root, t, context), status='ACTIVE',
                pending_boundary_credits=[], pending_boundary_expired=0)
            if root.environment_ageing_policy is not None:
                from .environment_reporting import initial
                if environment_ageing_state is None:raise ValueError('B61 explicit report history at actual clock')
                self.state['environment_ageing']=initial(root,environment_ageing_state,prepared_runtime=prepared_runtime)
                from . import lifetime_reporting as lifetime
                if lifetime.enabled(root):self.state['lifetime_environment']=lifetime.initial(root,environment_ageing_state,prepared_runtime=prepared_runtime)
        else: self.state = deepcopy(state)
        self.validate(prepared_runtime=prepared_runtime)
        if self.state['end_seconds'] != context.simulation_time_seconds:
            raise ValueError('report/context completed boundary differs')
        rows = [v for v in (self.state['sealed_totals'], self.state['current']) if v is not None]
        current = rows[-1]
        if (current['end_energy_wh'] != context.spacecraft_state.battery.energy_wh or
                current['wear_end'] != _wear(context) or
                any(not current['minimum_temperature_k'][k] <= v <= current['maximum_temperature_k'][k] for k, v in _temps(context).items())):
            raise ValueError('report endpoint differs from actual context')

    @property
    def boundary(self):
        if self.state['current'] is None: return self.state['end_seconds']
        return (self.state['current']['bucket']+1)*self.root.policy.month_period_seconds-self.root.policy.month_epoch_offset_seconds

    def offer(self, ordinal, weight, *, prepared_runtime=None):
        self.validate(prepared_runtime=prepared_runtime); integer(ordinal, 'offer ordinal', 0, self.root.offered_population-1)
        _finite(weight, 'request weight')
        if weight <= 0 or Q(weight) != self._expected_weight:
            raise ValueError('offered weight differs from immutable scenario')
        d = deepcopy(self.state); row = d['current']
        if row is None or ordinal != d['offered_frontier']: raise ValueError('offer frontier duplicate/gap')
        if self.root.start_seconds+ordinal*self.root.scenario.cadence_seconds > d['end_seconds']:
            raise ValueError('future unreleased request cannot enter actual report')
        if row['end_seconds'] == self.boundary: raise ValueError('seal calendar boundary before new release')
        row['offered'] += 1; row['priority_denominator'] = pack(unpack(row['priority_denominator'])+Q(weight))
        d['offered_frontier'] += 1; self._validate(d,prepared_runtime=prepared_runtime); self.state = d

    def _credit(self, credit, d, a, b):
        if type(credit) is not dict: raise ValueError('strict report credit record')
        if set(credit) != CREDIT_FIELDS: raise ValueError('exact report credit fields')
        c = deepcopy(credit)
        if type(c['request_id']) is not str or not 1 <= len(c['request_id']) <= 256:
            raise ValueError('strict credit request identity')
        if (type(c['record_ids']) is not list or len(c['record_ids']) != 1 or
                any(type(value) is not str or not 1 <= len(value) <= 256 for value in c['record_ids'])):
            raise ValueError('one complete MS record identity required')
        _finite(c['priority'], 'credit priority')
        if c['priority'] <= 0: raise ValueError('positive credit priority')
        if Q(c['priority']) != self._expected_weight: raise ValueError('credit priority differs from scenario')
        integer(c['useful_bits'], 'useful bits', 1, 2**40)
        if c['useful_bits'] != self._expected_bits: raise ValueError('credit bits differ from immutable MS sizing')
        integer(c['released_at_seconds'], 'credit release', self.root.start_seconds, self.root.end_seconds)
        prefix = self.root.scenario.namespace+'-'
        if not c['request_id'].startswith(prefix): raise ValueError('foreign lifecycle request identity')
        suffix = c['request_id'][len(prefix):]
        if not suffix.isascii() or not suffix.isdigit() or str(int(suffix)) != suffix:
            raise ValueError('noncanonical lifecycle occurrence identity')
        index = int(suffix)
        if not 0 <= index < d['offered_frontier'] or index >= self.root.offered_population:
            raise ValueError('unoffered lifecycle request credit')
        if c['released_at_seconds'] != self.root.start_seconds+index*self.root.scenario.cadence_seconds:
            raise ValueError('credit release differs from immutable scenario')
        when = unpack(c['completion_time'])
        if not a <= when <= b or c['released_at_seconds'] > when: raise ValueError('receipt outside actual transition')
        if when > c['released_at_seconds']+self.root.scenario.deadline_offset_seconds:
            raise ValueError('late receipt cannot earn on-time product credit')
        if d['scope'] == 'MAIN' and c['released_at_seconds'] < d['start_seconds']: raise ValueError('foreign main-report release')
        return c

    def _assign_credit(self, row, credit, d):
        row['credits'] += 1; row['useful_bits'] += credit['useful_bits']
        row['priority_numerator'] = pack(unpack(row['priority_numerator'])+Q(credit['priority']))
        scope_carry = credit['released_at_seconds'] < d['start_seconds']
        bucket_start = row['bucket']*self.root.policy.month_period_seconds-self.root.policy.month_epoch_offset_seconds
        prior_bucket = credit['released_at_seconds'] < bucket_start
        row['carry_in_credits'] += int(scope_carry)
        row['prior_bucket_credits'] += int(prior_bucket)
        row['nonlocal_offer_credits'] += int(scope_carry or prior_bucket)
        d['receipt_count'] += 1

    def consume(self, outcome, context, transition, *, credits=(), expired=0,lifetime_work=None,prepared_runtime=None):
        """Atomic one-transition fold. Private rejected predictions never count."""
        self.validate(prepared_runtime=prepared_runtime); integer(transition, 'transition ordinal'); integer(expired, 'expired count')
        if type(credits) not in (tuple, list) or len(credits) > self.root.policy.active_requests:
            raise ValueError('bounded actual credit batch required')
        d = deepcopy(self.state); row = d['current']; a = outcome.start_seconds; b = outcome.end_seconds
        integer(a, 'outcome start'); integer(b, 'outcome end')
        if row is None or d['pending_boundary_credits'] or d['pending_boundary_expired']:
            raise ValueError('seal pending calendar events before next transition')
        if transition != d['next_transition'] or a != d['end_seconds'] or not a <= b <= self.boundary or b != context.simulation_time_seconds:
            raise ValueError('report transition frontier/interval')
        if outcome.status not in ('partial', 'completed', 'refused') or outcome.kind not in (('POINT','CAPTURE','CONTACT','HOLD_UNTIL','SOLAR_POINT','SOLAR_HOLD') if self.root.energy_attitude_policy is not None else ('POINT', 'CAPTURE', 'CONTACT', 'HOLD_UNTIL')):
            raise ValueError('strict lifecycle outcome classification')
        if outcome.status == 'refused' and self.root.method!=METHOD55 and (a != b or outcome.cuts or outcome.contact_outcomes or outcome.contact_forcing):
            raise ValueError('refusal contains published actual physical progress')
        from .lifecycle_job_prepared import PreparedRoleState
        prepared_actuator = None
        if type(prepared_runtime) is PreparedRoleState:
            from .lifecycle_prepared_report import consume_prepared_result
            completing, prepared_actuator = consume_prepared_result(row, outcome, prepared_runtime)
        elif self.root.method==METHOD55 and self.root.battery_port_policy is not None:
            from .lifecycle_prepared_report import consume_selected_result
            completing, prepared_actuator = consume_selected_result(row,outcome)
        else:
            from .long_mission_continuation import _scientific
            from .design_repair_study import _plain_output
            plain = _plain_output(_scientific(outcome))
            completing = {}
            for contact in plain['contact_outcomes']:
                for service in contact['services']:
                    if service['completed']:
                        record = service['record']; rid = record['record_id']['value']
                        if rid in completing: raise ValueError('duplicate actual completing service')
                        offset = service['end_offset']
                        completing[rid] = (record['imaging_request_id']['value'],
                            Q(contact['contact']['start_time_seconds'])+Q(offset['numerator'], offset['denominator']),
                            record['stored_equivalent_bits'])
            parts = [cut['part'] for cut in plain['cuts']]
            for forcing in plain['contact_forcing']:
                for evaluation in forcing['evaluations']:
                    if evaluation['selected']: parts.extend(evaluation['parts'])
            if b > a and not parts:
                raise ValueError('covered physical interval lacks returned actual substeps')
            for part in parts: _part(row, part)
        if self.root.method==METHOD55:
            _service_work_delta(row,outcome)
        if self.root.energy_attitude_policy is not None:solar_report_delta(row['solar_attitude'],outcome)
        if self.root.method==METHOD55:
            if outcome.status=='refused' and outcome.kind!='HOLD_UNTIL' and type(outcome.reason) is str:
                if outcome.reason.startswith('B55_POWER_SERVICE_INTERRUPTED'):
                    row['power_service']['interrupted_actions']+=1
                elif outcome.reason.startswith(('B55_','UNSUPPORTED_MOVING_ATTITUDE_POWER_RECOVERY')):
                    row['power_service']['service_denied_actions']+=1
        if prepared_actuator is None:
            for cut in plain['cuts']:
                _add(row, 'actuator_energy_wh', Q(cut['actuator_draw_w'])*(Q(cut['end_seconds'])-Q(cut['start_seconds']))/3600)
        else:
            for value in prepared_actuator: _add(row, 'actuator_energy_wh', value)
        row['transitions'] += 1; row['completed_actions'] += int(outcome.status == 'completed')
        row['refused_actions'] += int(outcome.status == 'refused')
        if outcome.kind == 'POINT' and outcome.status != 'refused': row['executed_point_seconds'] += b-a
        if b == self.boundary: d['pending_boundary_expired'] = expired
        else: row['expired'] += expired
        seen = set(); carry = []
        for credit in credits:
            c = self._credit(credit, d, a, b)
            if c['request_id'] in seen: raise ValueError('duplicate request credit in transition')
            seen.add(c['request_id'])
            matching = [(rid, item) for rid, item in completing.items()
                        if item[0] == c['request_id'] and rid in c['record_ids']]
            if len(matching) != 1 or matching[0][1][1] != unpack(c['completion_time']) or matching[0][1][2] != c['useful_bits']:
                raise ValueError('credit does not match exact actual completing service')
            deliveries = {item.record.record_id.value: item for item in context.ground_data_delivery_state.completed_deliveries}
            delivery = deliveries.get(matching[0][0])
            if delivery is None or delivery.record.imaging_request_id.value != c['request_id'] or delivery.record.stored_equivalent_bits != c['useful_bits']:
                raise ValueError('credit lacks matching actual completed custody')
            if unpack(c['completion_time']) == self.boundary: carry.append(c)
            else: self._assign_credit(row, c, d)
        d['pending_boundary_credits'] = deepcopy(carry)
        s = context.spacecraft_state
        row['minimum_energy_wh'] = min(row['minimum_energy_wh'], s.battery.energy_wh); row['end_energy_wh'] = s.battery.energy_wh
        soc = _soc(context); row['minimum_soc'] = min(row['minimum_soc'], soc); row['end_soc'] = soc
        temperatures = _temps(context)
        if set(temperatures) != set(row['maximum_temperature_k']): raise ValueError('context/report thermal node sets differ')
        for key, value in temperatures.items():
            row['maximum_temperature_k'][key] = max(row['maximum_temperature_k'][key], value)
            row['minimum_temperature_k'][key] = min(row['minimum_temperature_k'][key], value)
        if self.root.environment_ageing_policy is not None:
            from .environment_reporting import advance
            d['environment_ageing']=advance(d['environment_ageing'],self.root,outcome.environment_ageing_state_before,outcome.environment_ageing_state_after,prepared_runtime=prepared_runtime)
            from . import lifetime_reporting as lifetime
            if lifetime.enabled(self.root):
                if lifetime_work is None:raise ValueError('B62 actual report requires paid counter snapshot')
                d['lifetime_environment']=lifetime.advance(d['lifetime_environment'],self.root,outcome.environment_ageing_state_before,outcome.environment_ageing_state_after,lifetime_work,prepared_runtime=prepared_runtime)
        row['wear_end'] = _wear(context); row['end_seconds'] = b; d['end_seconds'] = b; d['next_transition'] += 1
        self._validate(d,prepared_runtime=prepared_runtime); self.state = d
        return carry

    def seal(self, context, *, terminal=False, carry=(), prepared_runtime=None):
        self.validate(prepared_runtime=prepared_runtime)
        if type(terminal) is not bool or type(carry) not in (tuple, list): raise ValueError('strict seal request')
        d = deepcopy(self.state); row = d['current']
        if row is None: raise ValueError('report already sealed')
        if context.simulation_time_seconds != d['end_seconds']: raise ValueError('seal context boundary')
        if list(carry) != d['pending_boundary_credits']: raise ValueError('boundary credits dropped, duplicated or replaced')
        at_boundary = row['end_seconds'] == self.boundary
        if not terminal and not at_boundary: raise ValueError('seal only actual calendar boundary')
        handoff = bool(carry or d['pending_boundary_expired'])
        # At a terminal calendar endpoint events belong to the next half-open
        # bucket. First return the covered row, then a second seal returns one
        # explicit zero-duration ENDPOINT_EVENT_TAIL. No new physics is implied.
        final = terminal and not (at_boundary and handoff)
        row['seal'] = ('ENDPOINT_EVENT_TAIL' if final and row['start_seconds'] == row['end_seconds'] and
                       (row['credits'] or row['expired']) else 'MONTH_BOUNDARY' if at_boundary else 'PARTIAL_TERMINAL')
        result = deepcopy(row)
        if self.root.policy.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1':
            from .lifetime_reporting import rows as environment_rows
            candidates=environment_rows(d['lifetime_environment'])
            matching=[x for x in candidates if x['start_seconds']==row['start_seconds']and x['end_seconds']==row['end_seconds']]
            if not matching and row['start_seconds']!=row['end_seconds']:raise ValueError('B62 monthly environment support missing')
            result['lifetime_environment']=None if not matching else matching[0]
        d['sealed_totals'] = combine([row] if d['sealed_totals'] is None else [d['sealed_totals'], row])
        d['sealed_count'] += 1; d['sealed_end_seconds'] = row['end_seconds']
        d['row_chain'] = sha256((d['row_chain']+canonical(row)).encode()).hexdigest()
        d['current'] = None if final else _row(self.root, row['end_seconds'], context)
        if not final:
            for credit in carry: self._assign_credit(d['current'], credit, d)
            d['current']['expired'] += d['pending_boundary_expired']
        d['pending_boundary_credits'] = []; d['pending_boundary_expired'] = 0
        if final: d['status'] = 'COMPLETE'
        self._validate(d,prepared_runtime=prepared_runtime); self.state = d
        return result

    def seal_partial_terminal(self, context, *, prepared_runtime=None):
        """Seal the real current prefix on an incomplete B55 stop, once."""
        if self.root.method!=METHOD55:raise ValueError('partial terminal service row requires B55')
        self.validate(prepared_runtime=prepared_runtime);current=self.state['current']
        if current is None:return None
        nonempty=current['end_seconds']>current['start_seconds'] or any(current[name] for name in COUNTS)
        if nonempty:
            result=self.seal(context,terminal=True,carry=self.state['pending_boundary_credits'],prepared_runtime=prepared_runtime)
        else:
            # The previous covered row was already sealed at this exact cut.
            # Do not publish another empty endpoint merely to announce failure.
            if self.state['sealed_totals'] is None:raise ValueError('empty uncomputed prefix has no terminal physical row')
            result=None;self.state['current']=None
        self.state['status']='PARTIAL_TERMINAL';self.validate(prepared_runtime=prepared_runtime)
        return result

    def _validate_service(self, data, *, is_row, row):
        from .lifecycle_service import REASONS
        _fields(data,SERVICE_BASE_FIELDS|({'energy_audit','audit_epoch_seconds'} if is_row else set()),'service aggregate')
        if type(data['method']) is not str or data['method']!=SERVICE_REPORT_METHOD:raise ValueError('selected service report method')
        _fields(data['mode_durations_seconds'],set(SERVICE_MODES),'selected mode durations')
        for value in data['mode_durations_seconds'].values():
            if unpack(value)<0:raise ValueError('negative selected mode duration')
        covered=sum((unpack(v) for v in data['mode_durations_seconds'].values()),Q())
        if is_row and covered!=row['end_seconds']-row['start_seconds']:raise ValueError('mode durations do not cover actual row prefix')
        for name in ('mode_transitions','service_interruptions','selected_steps','interrupted_actions','service_denied_actions'):integer(data[name],name,0,2**48)
        if data['interrupted_actions']+data['service_denied_actions']>row['refused_actions']:raise ValueError('service action dispositions exceed actual refusals')
        if data['selected_steps']!=row['physical_substeps']:raise ValueError('selected mode/physical substep counts differ')
        if not 0<=unpack(data['boot_work_seconds'])<=unpack(data['mode_durations_seconds']['RECOVERY']):raise ValueError('boot work outside accepted recovery support')
        _fields(data['receiving_energy_wh'],set(SERVICE_RECEIVING),'receiving-power energy')
        energy={name:unpack(value) for name,value in data['receiving_energy_wh'].items()}
        if any(v<0 for v in energy.values()) or not energy['served_receiving_load_wh']<=energy['commanded_load_wh']<=energy['desired_normal_load_wh']:raise ValueError('receiving demand/service balance')
        if energy['commanded_shed_demand_wh']!=energy['desired_normal_load_wh']-energy['commanded_load_wh']:raise ValueError('receiving shed demand balance')
        if energy['essential_unserved_wh']>energy['commanded_load_wh']-energy['served_receiving_load_wh']:raise ValueError('essential receiving deficit balance')
        _fields(data['transition_reasons'],set(REASONS),'mode reason counts')
        for value in data['transition_reasons'].values():integer(value,'mode reason count',0,2**48)
        if sum(data['transition_reasons'].values())!=data['mode_transitions']:raise ValueError('mode transition reason balance')
        if is_row:
            if type(data['audit_epoch_seconds']) is not int or data['audit_epoch_seconds']!=self.root.start_seconds:raise ValueError('original-root energy audit day epoch')
            audit=data['energy_audit']
            if type(audit) is not list or len(audit)>160:raise ValueError('bounded actual day/mode audit')
            keys=[];audit_duration=Q();audit_modes={mode:Q() for mode in SERVICE_MODES};audit_receiving={name:Q() for name in SERVICE_RECEIVING};audit_sums={name:Q() for name in SERVICE_AUDIT_SUMS}
            for item in audit:
                _fields(item,SERVICE_AUDIT_FIELDS,'selected energy audit row')
                integer(item['day_index'],'supported day group',0,2**40)
                if type(item['mode']) is not str or item['mode'] not in SERVICE_MODES:raise ValueError('selected audit mode')
                key=(item['day_index'],item['mode'])
                if key in keys:raise ValueError('duplicate supported day/mode audit')
                keys.append(key)
                first,last,dt=map(unpack,(item['first_seconds'],item['last_seconds'],item['covered_seconds']))
                if not row['start_seconds']<=first<last<=row['end_seconds'] or not 0<dt<=last-first or (first-self.root.start_seconds)//86400!=item['day_index']:raise ValueError('selected audit actual support')
                if type(item['support_contiguous']) is not bool or type(item['crosses_day_boundary']) is not bool:raise TypeError('exact selected audit support flags')
                if item['support_contiguous'] and dt!=last-first:raise ValueError('contiguous audit duration mismatch')
                if item['crosses_day_boundary']!=(last>self.root.start_seconds+(item['day_index']+1)*86400):raise ValueError('audit day crossing classification')
                audit_duration+=dt;audit_modes[item['mode']]+=dt
                for name in ('start_energy_wh','end_energy_wh','minimum_energy_wh'):_finite(item[name],name)
                if item['minimum_energy_wh']>min(item['start_energy_wh'],item['end_energy_wh']):raise ValueError('selected audit energy minimum')
                unpack(item['stored_delta_wh'])
                _fields(item['sums'],set(SERVICE_AUDIT_SUMS),'selected audit energy sums')
                _fields(item['receiving_energy_wh'],set(SERVICE_RECEIVING),'selected audit receiving sums')
                for name in SERVICE_AUDIT_SUMS:
                    value=unpack(item['sums'][name])
                    if value<0:raise ValueError('negative selected audit energy')
                    audit_sums[name]+=value
                for name in SERVICE_RECEIVING:
                    value=unpack(item['receiving_energy_wh'][name])
                    if value<0:raise ValueError('negative selected audit receiving energy')
                    audit_receiving[name]+=value
                for name in ('maximum_temperature_k','minimum_temperature_k'):
                    _fields(item[name],set(row[name]),'selected audit thermal nodes')
                    for value in item[name].values():
                        if _finite(value,'selected thermal sample')<=0:raise ValueError('positive selected thermal sample')
                if any(item['minimum_temperature_k'][key]>item['maximum_temperature_k'][key] for key in item['maximum_temperature_k']):raise ValueError('selected audit thermal extrema')
            if any(audit_modes[mode]!=unpack(data['mode_durations_seconds'][mode]) for mode in SERVICE_MODES):raise ValueError('selected audit/mode duration distribution differs')
            if audit_duration!=covered or audit_receiving!=energy:raise ValueError('selected audit/row support or receiving sums differ')
            if any(audit_sums[name]!=unpack(row['sums'][name]) for name in SERVICE_AUDIT_SUMS):raise ValueError('selected audit/EPS row sums differ')
    def _validate_totals(self, row, *, is_row):
        expected=(ROW_FIELDS if is_row else TOTAL_FIELDS) | ({'battery_port'} if self.root.battery_port_policy is not None else set()) | ({'power_service'} if self.root.method==METHOD55 else set()) | ({'solar_attitude'} if self.root.energy_attitude_policy is not None else set())
        if is_row and self.root.policy.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'and 'lifetime_environment'in row:expected=expected|{'lifetime_environment'}
        _fields(row, expected, 'row' if is_row else 'totals')
        if self.root.method==METHOD55:self._validate_service(row['power_service'],is_row=is_row,row=row)
        if self.root.energy_attitude_policy is not None:validate_solar_report(row['solar_attitude'],self.root.energy_attitude_policy)
        if self.root.battery_port_policy is not None:validate_port_report(row['battery_port'],self.root.battery_port_policy)
        for name in COUNTS: integer(row[name], name, 0, 2**48)
        if row['completed_actions']+row['refused_actions'] > row['transitions']:
            raise ValueError('logical action counts exceed transitions')
        if max(row['carry_in_credits'], row['prior_bucket_credits']) > row['credits']:
            raise ValueError('carry-in count exceeds actual credit')
        if not max(row['carry_in_credits'], row['prior_bucket_credits']) <= row['nonlocal_offer_credits'] <= min(row['credits'], row['carry_in_credits']+row['prior_bucket_credits']):
            raise ValueError('carry-in/prior-bucket union count')
        num = unpack(row['priority_numerator']); den = unpack(row['priority_denominator'])
        if num < 0 or den < 0 or (row['offered'] == 0) != (den == 0) or (row['credits'] == 0) != (num == 0):
            raise ValueError('priority/count consistency')
        if den != row['offered']*self._expected_weight or num != row['credits']*self._expected_weight:
            raise ValueError('priority totals differ from immutable offered/credited population')
        if (row['credits'] == 0) != (row['useful_bits'] == 0): raise ValueError('credit/useful-bit consistency')
        if row['useful_bits'] != row['credits']*self._expected_bits:
            raise ValueError('useful-bit total differs from immutable MS product population')
        if row['credits']-row['nonlocal_offer_credits'] > row['offered']:
            raise ValueError('unoffered same-bucket credit')
        _fields(row['sums'], set(SUMS), 'sum')
        for name in SUMS:
            if unpack(row['sums'][name]) < 0: raise ValueError('negative report resource sum')
        for name in ('start_energy_wh', 'minimum_energy_wh', 'end_energy_wh'): _finite(row[name], name)
        if row['minimum_energy_wh'] > min(row['start_energy_wh'], row['end_energy_wh']): raise ValueError('report energy extrema')
        for name in ('start_soc', 'minimum_soc', 'end_soc'): _finite(row[name], name, 0., 1.)
        if row['minimum_soc'] > min(row['start_soc'], row['end_soc']): raise ValueError('report SOC extrema')
        nodes = {n.node_id.value for n in self.root.base.model.simulation_inputs.spacecraft_configuration.thermal.network.nodes}
        for name in ('maximum_temperature_k', 'minimum_temperature_k'):
            _fields(row[name], nodes, 'thermal extrema')
            for value in row[name].values():
                _finite(value, 'temperature', 0.)
                if value == 0: raise ValueError('positive thermal sample required')
        if any(row['minimum_temperature_k'][key] > row['maximum_temperature_k'][key] for key in nodes): raise ValueError('report thermal extrema')
        for name in ('wear_start', 'wear_end'):
            _fields(row[name], set(WEAR), 'wear')
            _finite(row[name]['battery_retention'], 'battery retention', 0., 1.)
            _finite(row[name]['solar_retention'], 'solar retention', 0., 1.)
            _finite(row[name]['throughput_wh'], 'throughput')
        if (row['wear_end']['battery_retention'] > row['wear_start']['battery_retention'] or
                row['wear_end']['solar_retention'] > row['wear_start']['solar_retention'] or
                row['wear_end']['throughput_wh'] < row['wear_start']['throughput_wh']):
            raise ValueError('report wear reverses actual evolution')
        if is_row:
            integer(row['bucket'], 'bucket', -2**40, 2**40)
            integer(row['start_seconds'], 'row start', self.root.start_seconds, self.root.end_seconds)
            integer(row['end_seconds'], 'row end', row['start_seconds'], self.root.end_seconds)
            p = self.root.policy
            start = row['bucket']*p.month_period_seconds-p.month_epoch_offset_seconds
            end = start+p.month_period_seconds
            if not start <= row['start_seconds'] <= row['end_seconds'] <= end: raise ValueError('row/bucket coverage')
            if row['seal'] not in (None, 'MONTH_BOUNDARY', 'PARTIAL_TERMINAL', 'ENDPOINT_EVENT_TAIL'): raise ValueError('row seal')
            if row['seal'] == 'MONTH_BOUNDARY' and row['end_seconds'] != end: raise ValueError('premature month seal')
            if row['seal'] == 'ENDPOINT_EVENT_TAIL' and (row['start_seconds'] != row['end_seconds'] or not(row['credits'] or row['expired'])):
                raise ValueError('endpoint event tail requires an actual zero-duration event')

    def _validate(self, data,*,prepared_runtime=None):
        _fields(data, STATE_FIELDS|({'lifetime_environment'}if self.root.policy.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'else set())|({'environment_ageing'}if self.root.environment_ageing_policy is not None else set()), 'state')
        if self.root.environment_ageing_policy is not None:
            from .environment_reporting import validate
            validate(data['environment_ageing'],self.root,data['start_seconds'],data['end_seconds'],prepared_runtime=prepared_runtime)
            from . import lifetime_reporting as lifetime
            if lifetime.enabled(self.root):lifetime.validate(data['lifetime_environment'],self.root,data['end_seconds'],prepared_runtime=prepared_runtime)
        if data['method'] != REPORT_METHOD or data['root_identity'] != self.root.identity: raise ValueError('report binding')
        identity(data['row_chain'])
        integer(data['start_seconds'], 'covered start', self.root.start_seconds, self.root.end_seconds)
        integer(data['end_seconds'], 'covered end', data['start_seconds'], self.root.end_seconds)
        for name in ('next_transition', 'transition_base', 'offered_frontier', 'offer_base_frontier', 'receipt_count', 'sealed_count', 'sealed_end_seconds', 'pending_boundary_expired'):
            integer(data[name], name, 0, 2**48)
        if data['scope'] not in ('MAIN', 'WINDOW') or data['status'] not in (('ACTIVE','COMPLETE','PARTIAL_TERMINAL') if self.root.method==METHOD55 else ('ACTIVE','COMPLETE')):
            raise ValueError('report scope/status')
        if data['scope'] == 'MAIN' and (data['start_seconds'] != self.root.start_seconds or data['offer_base_frontier'] or data['transition_base']):
            raise ValueError('main report cannot rebase its event frontiers')
        if not data['offer_base_frontier'] <= data['offered_frontier'] <= self.root.offered_population:
            raise ValueError('report offered frontier')
        if data['next_transition'] < data['transition_base'] or data['sealed_count'] > self.root.month_rows+1:
            raise ValueError('report frontier/capacity')
        if (data['status'] == 'ACTIVE') != (data['current'] is not None): raise ValueError('report current/status')
        if (data['sealed_count'] == 0) != (data['sealed_totals'] is None): raise ValueError('report sealed aggregate/count')
        if data['sealed_count'] == 0 and (data['row_chain'] != '0'*64 or data['sealed_end_seconds'] != data['start_seconds']):
            raise ValueError('report initial stream frontier')
        if data['sealed_count'] and data['row_chain'] == '0'*64:
            raise ValueError('sealed stream has initial digest')
        if not data['start_seconds'] <= data['sealed_end_seconds'] <= data['end_seconds']: raise ValueError('sealed coverage frontier')
        rows = []
        if data['sealed_totals'] is not None:
            self._validate_totals(data['sealed_totals'], is_row=False); rows.append(data['sealed_totals'])
        if data['current'] is not None:
            current = data['current']; self._validate_totals(current, is_row=True); rows.append(current)
            if current['seal'] is not None or current['start_seconds'] != data['sealed_end_seconds'] or current['end_seconds'] != data['end_seconds']:
                raise ValueError('current/sealed contiguous coverage')
            if data['sealed_totals'] is not None:
                old = data['sealed_totals']
                if old['end_energy_wh'] != current['start_energy_wh'] or old['end_soc'] != current['start_soc'] or old['wear_end'] != current['wear_start']:
                    raise ValueError('state discontinuity at sealed row boundary')
        elif data['sealed_end_seconds'] != data['end_seconds']: raise ValueError('terminal covered frontier')
        totals = combine(rows)
        if (totals['offered'] != data['offered_frontier']-data['offer_base_frontier'] or
                totals['transitions'] != data['next_transition']-data['transition_base'] or
                totals['credits'] != data['receipt_count']):
            raise ValueError('report aggregate/frontier mismatch')
        if data['scope'] == 'MAIN' and (totals['carry_in_credits'] or totals['credits']+totals['expired']+data['pending_boundary_expired'] > totals['offered']):
            raise ValueError('main disposition exceeds offered request population')
        due = min(data['offered_frontier'], max(0,
            (data['end_seconds']-self.root.start_seconds-self.root.scenario.deadline_offset_seconds)//self.root.scenario.cadence_seconds+1))
        if totals['expired']+data['pending_boundary_expired'] > due:
            raise ValueError('expired count precedes immutable request deadlines')
        pending = data['pending_boundary_credits']
        if type(pending) is not list or len(pending) > self.root.policy.active_requests: raise ValueError('bounded boundary receipts')
        seen = set()
        for credit in pending:
            c = self._credit(credit, data, data['end_seconds'], data['end_seconds'])
            if c['request_id'] in seen: raise ValueError('duplicate pending boundary credit')
            seen.add(c['request_id'])
        if data['scope'] == 'MAIN' and totals['credits']+totals['expired']+len(pending)+data['pending_boundary_expired'] > totals['offered']:
            raise ValueError('main dispositions and boundary events exceed actual offered population')
        if pending or data['pending_boundary_expired']:
            if data['current'] is None or data['current']['end_seconds'] != (data['current']['bucket']+1)*self.root.policy.month_period_seconds-self.root.policy.month_epoch_offset_seconds:
                raise ValueError('pending boundary event at nonboundary')
        if totals['credits']+len(pending) > (data['offered_frontier'] if data['scope'] == 'MAIN' else self.root.offered_population):
            raise ValueError('credit population exceeds admitted offers')
        if data['scope'] == 'MAIN' and unpack(totals['priority_numerator'])+sum((Q(c['priority']) for c in pending), Q()) > unpack(totals['priority_denominator']):
            raise ValueError('credited priority exceeds cumulative actual offers')
        return data

    def validate(self,*,prepared_runtime=None): return self._validate(self.state,prepared_runtime=prepared_runtime)

    def summary(self,*,prepared_runtime=None):
        self.validate(prepared_runtime=prepared_runtime); data = self.state
        totals = combine([v for v in (data['sealed_totals'], data['current']) if v is not None])
        den = unpack(totals['priority_denominator']); num = unpack(totals['priority_numerator'])
        unavailable = not den or (data['scope'] == 'WINDOW' and totals['carry_in_credits'] > 0)
        totals['priority_score'] = None if unavailable else float(num/den)
        totals['priority_score_status'] = ('UNAVAILABLE_CARRY_IN_SCOPE' if data['scope'] == 'WINDOW' and totals['carry_in_credits'] else 'UNAVAILABLE_NO_OFFERS' if not den else 'AVAILABLE')
        return dict(method=REPORT_METHOD, root_identity=data['root_identity'], scope=data['scope'], status=data['status'],
            start_seconds=data['start_seconds'], end_seconds=data['end_seconds'],
            requested_end_seconds=self.root.end_seconds,
            coverage_status='FULL_REQUESTED_HORIZON' if data['scope'] == 'MAIN' and data['end_seconds'] == self.root.end_seconds else 'ACTUAL_COVERED_PREFIX_OR_WINDOW',
            calendar='FIXED_30_DAY_BUCKET_V1_NOT_GREGORIAN' if self.root.policy.month_period_seconds == MONTH else 'SYNTHETIC_UNIT_BUCKET_NOT_MONTH_PHYSICS',
            epoch_offset_seconds=self.root.policy.month_epoch_offset_seconds, period_seconds=self.root.policy.month_period_seconds,
            sealed_count=data['sealed_count'], row_chain=data['row_chain'], totals=totals,
            pending_boundary_credit_count=len(data['pending_boundary_credits']), pending_boundary_expired=data['pending_boundary_expired'],
            extrema_scope='RETURNED_SAMPLED_NOT_CONTINUOUS',
            priority_scope='CUMULATIVE_ACTUALLY_OFFERED_WEIGHTS_NOT_AVERAGE_MONTH_RATIOS',
            monthly_priority_scope='CURRENT_BUCKET_OFFERS_WITH_EXPLICIT_PRIOR_BUCKET_CREDITS',**({'lifetime_environment':deepcopy(data['lifetime_environment'])}if self.root.policy.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'else {}),**({'environment_ageing':deepcopy(data['environment_ageing'])}if self.root.environment_ageing_policy is not None else {}))


SUMMARY_FIELDS = {'method','root_identity','scope','status','start_seconds','end_seconds',
    'requested_end_seconds','coverage_status','calendar','epoch_offset_seconds','period_seconds',
    'sealed_count','row_chain','totals','pending_boundary_credit_count','pending_boundary_expired',
    'extrema_scope','priority_scope','monthly_priority_scope'}


def _summary_checker(root):
    checker=object.__new__(LifecycleReport);checker.root=root
    product=root.base.requests[root.scenario.request_index].product
    checker._expected_weight=Q(product.request.priority_weight)
    optical=root.base.model.simulation_inputs.spacecraft_configuration.payload.optical_acquisition
    spacing=Q(optical.multispectral_reference_sample_spacing_m.value)
    # Same published exact ceil convention; no acquisition/geometry owner call.
    checker._expected_bits=math.ceil(Q(product.footprint.width_m)/spacing)*math.ceil(Q(product.footprint.length_m)/spacing)*len(product.required_channels)*int(optical.acquisition_bits_per_sample.value)
    return checker


def validate_report_summary(root,value,expected_clock,window=False):
    """Strict B55 saved-report admission, with NO context/physics reconstruction.

    Root hardware and its integer MS sizing convention have already received
    immutable input admission. This checks data arithmetic and source-fixed
    schemas, not independent physical reachability or a successful mission.
    """
    if root.method!=METHOD55:raise ValueError('versioned service summary validation requires B55 root')
    if type(window) is not bool:raise TypeError('exact report summary window flag')
    integer(expected_clock,'expected saved report clock',root.start_seconds,root.end_seconds)
    _fields(value,SUMMARY_FIELDS|({'lifetime_environment'}if root.policy.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'else set())|({'environment_ageing'}if root.environment_ageing_policy is not None else set()),'saved summary')
    if root.environment_ageing_policy is not None:
        from .environment_reporting import validate
        validate(value['environment_ageing'],root,value['start_seconds'],expected_clock)
        from . import lifetime_reporting as lifetime
        if lifetime.enabled(root):lifetime.validate(value['lifetime_environment'],root,expected_clock)
    identity(value['root_identity'])
    if type(value['method']) is not str or value['method']!=REPORT_METHOD or value['root_identity']!=root.identity:
        raise ValueError('saved report method/root binding')
    if type(value['scope']) is not str or value['scope']!=('WINDOW' if window else 'MAIN'):
        raise ValueError('saved report scope binding')
    if type(value['status']) is not str or value['status'] not in ('ACTIVE','COMPLETE','PARTIAL_TERMINAL'):
        raise ValueError('saved report status')
    start=integer(value['start_seconds'],'saved report start',root.start_seconds,expected_clock)
    if not window and start!=root.start_seconds:raise ValueError('main saved report cannot rebase prefix')
    if type(value['end_seconds']) is not int or value['end_seconds']!=expected_clock:
        raise ValueError('saved report actual endpoint')
    if type(value['requested_end_seconds']) is not int or value['requested_end_seconds']!=root.end_seconds:
        raise ValueError('saved report requested horizon')
    expected=dict(coverage_status='FULL_REQUESTED_HORIZON' if not window and expected_clock==root.end_seconds else 'ACTUAL_COVERED_PREFIX_OR_WINDOW',
        calendar='FIXED_30_DAY_BUCKET_V1_NOT_GREGORIAN' if root.policy.month_period_seconds==MONTH else 'SYNTHETIC_UNIT_BUCKET_NOT_MONTH_PHYSICS',
        extrema_scope='RETURNED_SAMPLED_NOT_CONTINUOUS',
        priority_scope='CUMULATIVE_ACTUALLY_OFFERED_WEIGHTS_NOT_AVERAGE_MONTH_RATIOS',
        monthly_priority_scope='CURRENT_BUCKET_OFFERS_WITH_EXPLICIT_PRIOR_BUCKET_CREDITS')
    if any(type(value[name]) is not str or value[name]!=text for name,text in expected.items()):
        raise ValueError('saved report coverage/calendar/arithmetic scope')
    for name,expected_value in (('epoch_offset_seconds',root.policy.month_epoch_offset_seconds),('period_seconds',root.policy.month_period_seconds)):
        if type(value[name]) is not int or value[name]!=expected_value:raise ValueError('saved report calendar input binding')
    count=integer(value['sealed_count'],'saved sealed count',0,root.month_rows+1);identity(value['row_chain'])
    if (count==0)!=(value['row_chain']=='0'*64):raise ValueError('saved report seal/hash frontier')
    pending=integer(value['pending_boundary_credit_count'],'saved pending credits',0,root.policy.active_requests)
    expired_pending=integer(value['pending_boundary_expired'],'saved pending expiry',0,root.policy.active_requests)
    totals=value['totals']
    _fields(totals,TOTAL_FIELDS|{'power_service','priority_score','priority_score_status'}|({'solar_attitude'} if root.energy_attitude_policy is not None else set())|({'battery_port'} if root.battery_port_policy is not None else set()),'saved summary totals')
    body={name:item for name,item in totals.items() if name not in ('priority_score','priority_score_status')}
    checker=_summary_checker(root)
    checker._validate_totals(body,is_row=False)
    durations=body['power_service']['mode_durations_seconds']
    if sum((unpack(item) for item in durations.values()),Q())!=expected_clock-start:
        raise ValueError('saved selected modes do not cover report prefix/window')
    if not window:
        initial=root.base.initial_checkpoint.spacecraft
        if body['start_energy_wh']!=initial.battery_energy_wh:
            raise ValueError('saved main report changed original battery energy')
        if body['carry_in_credits']:raise ValueError('main saved report imported window carry credits')
        if body['credits']+body['expired']+pending+expired_pending>body['offered']:
            raise ValueError('saved main disposition exceeds actual offered population')
        offered_max=min(root.offered_population,max(0,(expected_clock-root.start_seconds)//root.scenario.cadence_seconds+1))
        offered_min=min(root.offered_population,max(0,math.ceil(Q(expected_clock-root.start_seconds,root.scenario.cadence_seconds))))
        if not offered_min<=body['offered']<=offered_max:
            raise ValueError('saved report offered population/clock inconsistency')
        expiry_max=min(body['offered'],max(0,(expected_clock-root.start_seconds-root.scenario.deadline_offset_seconds)//root.scenario.cadence_seconds+1))
        if body['expired']+expired_pending>expiry_max:raise ValueError('saved expiry precedes immutable deadlines')
    den=unpack(body['priority_denominator']);num=unpack(body['priority_numerator'])
    unavailable=not den or window and body['carry_in_credits']>0
    status=('UNAVAILABLE_CARRY_IN_SCOPE' if window and body['carry_in_credits'] else 'UNAVAILABLE_NO_OFFERS' if not den else 'AVAILABLE')
    if type(totals['priority_score_status']) is not str or totals['priority_score_status']!=status:
        raise ValueError('saved priority score scope')
    score=totals['priority_score']
    if unavailable:
        if score is not None:raise ValueError('unavailable saved score must remain null')
    elif type(score) is not float or not math.isfinite(score) or score.hex()!=float(num/den).hex():
        raise ValueError('saved score differs from exact offered-weight ratio')
    return value

def validate_partial_report_row(root,value,expected_clock):
    """Validate a copied stop/failure view; this grants no continuation state."""
    if root.method!=METHOD55:raise ValueError('versioned service partial row requires B55 root')
    integer(expected_clock,'expected partial row endpoint',root.start_seconds,root.end_seconds)
    _fields(value,ROW_FIELDS|({'lifetime_environment'}if root.policy.method=='B62_LIFETIME_CUMULATIVE_ACCOUNTING_V1'else set())|{'power_service'}|({'solar_attitude'} if root.energy_attitude_policy is not None else set())|({'battery_port'} if root.battery_port_policy is not None else set()),'saved partial terminal row')
    _summary_checker(root)._validate_totals(value,is_row=True)
    if value['end_seconds']!=expected_clock:raise ValueError('partial row/covered native endpoint mismatch')
    if type(value['seal']) is not str or value['seal'] not in ('PARTIAL_TERMINAL','ENDPOINT_EVENT_TAIL'):
        raise ValueError('explicit partial terminal/event-tail classification required')
    if value['start_seconds']==value['end_seconds'] and not any(value[name] for name in COUNTS):
        raise ValueError('uncomputed empty endpoint is not a terminal row')
    return value
