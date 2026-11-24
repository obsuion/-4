"""Incremental actual-event aggregates; no planner forecast grants credit.

Fixed 30-day buckets are not Gregorian months. The short demonstration places
an existing physical boundary at a report boundary; it does not simulate a month.
"""
from copy import deepcopy
from fractions import Fraction as Q
from .rolling_physics import digest
from .long_mission_continuation import _scientific
from .design_repair_study import _plain_output
from .ms_product import assess_ms_product
from .rolling_cache import canonical_size

METHOD='B51_INCREMENTAL_RETURNED_STATE_REPORT_V1'
PERIOD=2592000
DEMO_OFFSET=2591800
SUMS=('generation_wh','requested_load_wh','served_load_wh','unmet_load_wh','wire_loss_wh',
    'actuator_energy_wh','throughput_wh','conversion_loss_wh')

def pack(q):return [str(q.numerator),str(q.denominator)]
def unpack(q):return Q(int(q[0]),int(q[1]))
def add(row,name,value):row['sums'][name]=pack(unpack(row['sums'][name])+Q(value))

class MissionReport:
    def __init__(self,root,*,offset_seconds=DEMO_OFFSET,period_seconds=PERIOD,state=None,start_context=None,start_cursor=0):
        if type(offset_seconds) is not int or type(period_seconds) is not int or not 1<=period_seconds<=PERIOD:raise ValueError('report exact fixed bucket policy')
        self.root=root;self.offset=offset_seconds;self.period=period_seconds
        if state is not None:
            from .mission_report_document import validate_state
            validate_state(state)
            if state['root_identity']!=digest(root) or state['offset_seconds']!=self.offset or state['period_seconds']!=self.period:raise ValueError('report root/calendar binding')
            self._validate_root_events(state)
            self.state=deepcopy(state);return
        context=root.initial_checkpoint.restore(root.model.simulation_inputs) if start_context is None else start_context
        clock=context.simulation_time_seconds
        if type(start_cursor) is not int or not 0<=start_cursor<=64 or context.inputs!=root.model.simulation_inputs:raise ValueError('report actual starting boundary')
        self.state=dict(method=METHOD,root_identity=digest(root),offset_seconds=self.offset,period_seconds=self.period,
            start_seconds=clock,end_seconds=clock,cursor=0,base_cursor=start_cursor,seen_actions=[],seen_receipts=[],seen_offered=[],seen_expired=[],
            sealed=[],current=self._row(clock,context),control_units=0,control_reserved_units=0,detail_bytes=0,status='ACTIVE')
        self._offered(clock)
        from .mission_report_document import validate_state
        validate_state(self.state)
    def _validate_root_events(self,state):
        """Check declared metadata only; reports never reconstruct physics."""
        requests={r.product.request.request_id.value:r for r in self.root.requests}
        denominator=sum(r.product.request.priority_weight for r in self.root.requests)
        rows=state['sealed']+([] if state['current'] is None else [state['current']])
        expected_offered={rid for rid,r in requests.items() if state['start_seconds']<=r.release_seconds<=state['end_seconds']}
        if set(state['seen_offered'])!=expected_offered:raise ValueError('report root offered request scope')
        for row in rows:
            if row['priority_denominator']!=denominator:raise ValueError('report root denominator scope')
            for event in row['offered']:
                rid=event['id'];request=requests.get(rid)
                if request is None or event['priority']!=request.product.request.priority_weight or self.bucket(request.release_seconds)!=row['bucket'] or not row['start_seconds']<=request.release_seconds<=row['end_seconds']:raise ValueError('report root offered metadata')
            for event in row['credits']:
                request=requests.get(event['request_id']);completion=unpack(event['completion_time'])
                if request is None or event['priority']!=request.product.request.priority_weight or not request.product.acquisition_start_seconds<=completion<=request.product.delivery_deadline_seconds:raise ValueError('report root credit metadata')
            for rid in row['expired']:
                request=requests.get(rid)
                if request is None or not state['start_seconds']<=request.product.delivery_deadline_seconds<=row['end_seconds']:raise ValueError('report root expiry metadata')
    def bucket(self,t):return int((Q(t)+self.offset)//self.period)
    def _row(self,t,context):
        s=context.spacecraft_state
        return dict(bucket=self.bucket(t),start_seconds=t,end_seconds=t,seal=None,
            offered=[],credits=[],expired=[],actions=0,refused_actions=0,executed_point_seconds=0,
            minimum_energy_wh=s.battery.energy_wh,end_energy_wh=s.battery.energy_wh,
            maximum_temperature_k={n.node_id.value:n.temperature_k for n in s.thermal.node_states},
            sums={k:pack(Q(0)) for k in SUMS},wear_start=_plain_output(_scientific(s.degradation)),
            wear_end=_plain_output(_scientific(s.degradation)),
            soc=dict(minimum_returned=None,end_returned=None,scope='DERIVED_RETURNED_ENERGY_OVER_RETURNED_CAPACITY_NOT_CONTINUOUS'),
            delivered_useful_bits=0,credits_count=0,priority_numerator=0,
            priority_denominator=sum(r.product.request.priority_weight for r in self.root.requests))
    def _offered(self,clock,state=None):
        d=self.state if state is None else state
        row=d['current']
        for r in self.root.requests:
            rid=r.product.request.request_id.value
            if d['start_seconds']<=r.release_seconds<=clock and rid not in d['seen_offered']:
                if self.bucket(max(d['start_seconds'],r.release_seconds))!=row['bucket']:raise ValueError('offered event requires report boundary')
                row['offered'].append(dict(id=rid,priority=r.product.request.priority_weight))
                d['seen_offered'].append(rid)
    def _part(self,row,part):
        battery=part['physical']['eps_result']['battery'];dt=battery['dt_seconds']
        row['minimum_energy_wh']=min(row['minimum_energy_wh'],battery['start_energy_wh'],battery['end_energy_wh'])
        row['end_energy_wh']=battery['end_energy_wh']
        for n in part['physical']['thermal_coupling_result']['thermal_result']['node_transitions']:
            key=n['node_id']['value'];row['maximum_temperature_k'][key]=max(row['maximum_temperature_k'][key],n['start_temperature_k'],n['end_temperature_k'])
        for name,source in (('generation_wh','generation_w'),('requested_load_wh','load_w'),('unmet_load_wh','unmet_load_w')):
            add(row,name,Q(battery[source])*Q(dt)/3600)
        add(row,'served_load_wh',Q(battery['load_w']-battery['unmet_load_w'])*Q(dt)/3600)
        add(row,'wire_loss_wh',Q(part['electrical']['pv_wire_loss_w']+part['electrical']['receiving_wire_loss_w'])*Q(dt)/3600)
        add(row,'conversion_loss_wh',battery['conversion_loss_wh'])
        add(row,'throughput_wh',part['physical']['battery_degradation_result']['throughput_increment_wh'])
        cap=part['physical']['eps_capability_result']['battery_usable_capacity_wh']
        endcap=part['physical']['battery_capacity_reconciliation_result']['end_usable_capacity_wh']
        start_soc=battery['start_energy_wh']/cap
        end_soc=part['physical']['battery_capacity_reconciliation_result']['authoritative_end_energy_wh']/endcap
        old=row['soc']['minimum_returned'];row['soc']['minimum_returned']=min(start_soc,end_soc) if old is None else min(old,start_soc,end_soc)
        row['soc']['end_returned']=end_soc
    def consume(self,state):
        """Publish one fully admitted boundary, or preserve the previous report.

        Physical work and its paid ledger belong to the caller and are never
        rolled back here.  All report edits use a detached candidate, including
        late product/calendar/quota checks; external references to the published
        state therefore remain untouched on failure.
        """
        from .mission_report_document import validate_state
        validate_state(self.state)
        candidate=deepcopy(self.state)
        detail=self._consume_staged(state,candidate)
        validate_state(candidate)
        self._validate_root_events(candidate)
        self.state=candidate
        return detail
    def _consume_staged(self,state,d):
        if digest(state.root)!=d['root_identity'] or state.physical.cursor!=d['base_cursor']+d['cursor']+1:raise ValueError('report cursor/root; prefix cannot be reconsumed')
        o=state.physical.outcomes[-1];row=d['current']
        if o.action_id in d['seen_actions'] or o.start_seconds!=d['end_seconds']:raise ValueError('report action continuity/dedup')
        boundary=(row['bucket']+1)*self.period-self.offset
        if o.start_seconds<boundary<o.end_seconds:raise ValueError('NEEDS_REPORT_BOUNDARY_SUBSTEP')
        if o.status=='refused' and o.kind=='POINT' and (o.start_seconds!=o.end_seconds or o.cuts):raise ValueError('refused POINT has no executed contribution')
        if d['control_reserved_units']+2**20>2**30:raise ValueError('report prospective control admission')
        d['control_reserved_units']+=2**20
        plain=_plain_output(_scientific(o))
        parts=[c['part'] for c in plain['cuts']]
        for forcing in plain['contact_forcing']:
            for evaluation in forcing['evaluations']:
                if evaluation['selected']:parts.extend(evaluation['parts'])
        for part in parts:self._part(row,part)
        for c in plain['cuts']:add(row,'actuator_energy_wh',Q(c['actuator_draw_w'])*Q(c['end_seconds']-c['start_seconds'])/3600)
        row['actions']+=1;row['refused_actions']+=int(o.status!='completed')
        if o.kind=='POINT' and o.status=='completed':row['executed_point_seconds']+=o.end_seconds-o.start_seconds
        all_contacts=tuple(c for x in state.physical.outcomes for c in x.contact_outcomes)
        next_row=None
        for r in self.root.requests:
            rid=r.product.request.request_id.value
            a=assess_ms_product(r.product,state.physical.acquisitions,state.physical.context.ground_data_delivery_state,all_contacts,o.end_seconds)
            if a.status=='credited' and a.completion_time_seconds>=d['start_seconds'] and rid not in d['seen_receipts']:
                credit_row=row
                if self.bucket(a.completion_time_seconds)!=row['bucket']:
                    if a.completion_time_seconds!=boundary or o.end_seconds!=boundary:raise ValueError('fractional receipt requires matching report bucket')
                    if next_row is None:next_row=self._row(boundary,state.physical.context)
                    credit_row=next_row
                credit=dict(request_id=rid,record_ids=[i.value for i in a.credited_record_ids],
                    completion_time=pack(a.completion_time_seconds),priority=r.product.request.priority_weight,
                    useful_bits=sum(e.record.stored_equivalent_bits for e in state.physical.acquisitions if e.record.record_id in a.credited_record_ids))
                credit_row['credits'].append(credit);credit_row['credits_count']+=1
                credit_row['delivered_useful_bits']+=credit['useful_bits'];credit_row['priority_numerator']+=credit['priority']
                d['seen_receipts'].append(rid)
            if a.status=='expired' and r.product.delivery_deadline_seconds>=d['start_seconds'] and rid not in d['seen_expired']:
                row['expired'].append(rid);d['seen_expired'].append(rid)
        s=state.physical.context.spacecraft_state
        row['minimum_energy_wh']=min(row['minimum_energy_wh'],s.battery.energy_wh);row['end_energy_wh']=s.battery.energy_wh
        row['wear_end']=_plain_output(_scientific(s.degradation));row['end_seconds']=o.end_seconds
        d['end_seconds']=o.end_seconds;d['cursor']+=1;d['seen_actions'].append(o.action_id)
        # Release exactly at a boundary belongs to the following half-open bucket.
        if o.end_seconds==boundary:
            row['seal']='MONTH_BOUNDARY';d['sealed'].append(row);d['current']=next_row or self._row(o.end_seconds,state.physical.context)
        self._offered(o.end_seconds,d)
        d['control_units']+=len(parts)*128+len(all_contacts)*16+len(self.root.requests)*128+1024
        if d['control_units']>2**30 or len(d['sealed'])>180 or len(d['seen_actions'])>64:raise ValueError('report control/record quota')
        canonical_size(d,2**20)
        detail=dict(action_id=o.action_id,kind=o.kind,status=o.status,reason=o.reason,start=o.start_seconds,end=o.end_seconds,
            returned_parts=len(parts),received_credit_scope='ACTUAL_CUSTODY_ONLY',refused_POINT_executed_seconds=0 if o.status=='refused' and o.kind=='POINT' else None)
        return detail
    def finish(self):
        if self.state['status']!='ACTIVE':raise ValueError('report already sealed')
        from .mission_report_document import validate_state,validate_summary
        validate_state(self.state)
        candidate=deepcopy(self.state);row=candidate['current'];row['seal']='PARTIAL_TERMINAL'
        if not candidate['sealed'] or row['end_seconds']>row['start_seconds'] or row['actions'] or row['credits'] or row['offered'] or row['expired']:candidate['sealed'].append(row)
        candidate['current']=None;candidate['status']='COMPLETE'
        validate_state(candidate);result=self._summary(candidate);validate_summary(result)
        self.state=candidate
        return result
    def summary(self):
        from .mission_report_document import validate_state,validate_summary
        validate_state(self.state);result=self._summary(self.state);validate_summary(result)
        return result
    def _summary(self,d):
        rows=d['sealed']+([] if d['current'] is None else [d['current']])
        denominator=sum(r.product.request.priority_weight for r in self.root.requests)
        numerator=sum(c['priority'] for row in rows for c in row['credits'])
        return dict(method=METHOD,root_identity=d['root_identity'],status=d['status'],start_seconds=d['start_seconds'],end_seconds=d['end_seconds'],
            month_semantics='FIXED_30_DAY_BUCKET_NOT_GREGORIAN',epoch_offset_seconds=self.offset,period_seconds=self.period,
            coverage='SHORT_SYNTHETIC_DEMO_NOT_MONTH_PHYSICAL_SIMULATION',rows=deepcopy(rows),
            totals=dict(offered=sum(len(r['offered']) for r in rows),credits=sum(len(r['credits']) for r in rows),
                useful_bits=sum(c['useful_bits'] for r in rows for c in r['credits']),priority_numerator=numerator,
                priority_denominator=denominator,priority_score=numerator/denominator,
                refused_actions=sum(r['refused_actions'] for r in rows),expired_requests=sum(len(r['expired']) for r in rows),
                executed_point_seconds=sum(r['executed_point_seconds'] for r in rows),
                minimum_energy_wh=min(r['minimum_energy_wh'] for r in rows),end_energy_wh=rows[-1]['end_energy_wh'],
                maximum_temperature_k={k:max(r['maximum_temperature_k'][k] for r in rows) for k in rows[0]['maximum_temperature_k']},
                sums={k:pack(sum((unpack(r['sums'][k]) for r in rows),Q())) for k in SUMS}),
            extrema_scope='RETURNED_STATES_NOT_CONTINUOUS_EXTREMA',control_units=d['control_units'],
            control_reserved_units=d['control_reserved_units'],
            coordinator_history='FULL_SHORT_PREFIX_RETAINED_SEPARATELY')
