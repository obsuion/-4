"""Explicit short direct-window policy and measured restore call evidence."""
from functools import wraps
from .project_intents import validate_intent,DIRECT

def validate_window(intent,clock):
    validate_intent(intent)
    if intent['method']!=DIRECT or type(clock) is not int or not clock<intent['window_end_seconds']<=728:
        raise ValueError('supported committed snapshot/window domain')
    return intent['window_end_seconds']

def returned_detail(outcome,context):
    """Verbose actual returned parts, excluding unselected/rejected trials."""
    selected=[('executed_cut',c.part) for c in outcome.cuts]
    for forcing in outcome.contact_forcing:
        for evaluation in forcing.evaluations:
            if evaluation.selected:selected.extend(('selected_contact_part',p) for p in evaluation.parts)
    if len(selected)>16384:raise ValueError('verbose returned-part bound')
    parts=[]
    for index,(origin,part) in enumerate(selected):
        p=part.physical;b=p.eps_result.battery
        parts.append(dict(index=index,origin=origin,duration=dict(numerator=b.duration.numerator,denominator=b.duration.denominator),
            battery_start_wh=b.start_energy_wh,battery_end_wh=b.end_energy_wh,
            authoritative_end_wh=p.battery_capacity_reconciliation_result.authoritative_end_energy_wh,
            generation_w=b.generation_w,requested_load_w=b.load_w,unmet_load_w=b.unmet_load_w,
            wire_loss_w=part.electrical.pv_wire_loss_w+part.electrical.receiving_wire_loss_w,
            temperatures=[dict(node_id=n.node_id.value,start_k=n.start_temperature_k,end_k=n.end_temperature_k)
                for n in p.thermal_coupling_result.thermal_result.node_transitions]))
    delivery=context.ground_data_delivery_state
    return dict(scope='ACTUAL_RETURNED_PARTS_NOT_FORECAST_OR_CONTINUOUS_EXTREMA',parts=parts,
        partial_transfers=[dict(record_id=p.record_id.value,transmitted_bits=p.transmitted_equivalent_bits) for p in delivery.partial_transfers],
        completed_record_ids=[p.record.record_id.value for p in delivery.completed_deliveries])

class RestoreWatch:
    """Task-local invocation instrumentation, originals forwarded exactly once.

    Counts apply only to restoration. Future planner propagation from received
    observations is paid suffix work and is not hidden restore-prefix work.
    """
    def __init__(self,worker_namespace=None):self.worker_namespace=worker_namespace
    def __enter__(self):
        from . import rolling_execution as coordinator,rolling_physics as physical,long_nominal_provider as orbit
        from . import rolling_forecast as forecast,command_estimation as estimate,command_controller as controller
        from . import orbit_j2 as kernel,orbit_j2_gravity as gravity,orbit_geometry as geometry,orbit_visibility as visibility
        self.saved=[];self.counts={}
        bindings=((coordinator,'start_rolling'),(coordinator,'step_rolling'),
            (physical,'start_physical'),(physical,'advance_physical'),
            (orbit,'_rk4_step'),(orbit,'_gravity'),(orbit.LongNominalProvider,'query'),
            (coordinator,'start_physical'),(coordinator,'advance_physical'),
            (forecast,'start_physical'),(forecast,'advance_physical'),(forecast,'forecast_suffix'),
            (estimate,'start_physical'),(estimate,'advance_physical'),(estimate,'forecast_command_suffix'),
            (controller,'select_command'),(kernel,'_rk4_step'),(kernel,'_gravity'),(gravity,'_gravity'),
            (geometry,'evaluate_ground_point_geometry'),(visibility,'evaluate_ground_point_geometry'),(visibility,'evaluate_ground_visibility'))
        for owner,name in bindings:
            key=owner.__name__+'.'+name;original=getattr(owner,name);self.counts[key]=0
            def wrapper(*args,_key=key,_original=original,**kwargs):
                self.counts[_key]+=1;return _original(*args,**kwargs)
            self.saved.append((owner,name,original));setattr(owner,name,wraps(original)(wrapper))
        self.namespace_saved=[]
        if self.worker_namespace is not None:
            for name in ('start_rolling','step_rolling'):
                original=self.worker_namespace[name];key='actual_worker_namespace.'+name;self.counts[key]=0
                def wrapper(*args,_key=key,_original=original,**kwargs):
                    self.counts[_key]+=1;return _original(*args,**kwargs)
                self.namespace_saved.append((name,original));self.worker_namespace[name]=wraps(original)(wrapper)
        return self
    def __exit__(self,*args):
        for owner,name,original in reversed(self.saved):setattr(owner,name,original)
        for name,original in self.namespace_saved:self.worker_namespace[name]=original
        return False
    def proof(self):
        if any(self.counts.values()):raise ValueError('direct restoration executed prior numerical/rolling work')
        return dict(phase='DIRECT_RESTORE_ONLY',instrumented_calls=dict(self.counts),
            prefix_actual_calls=0,prefix_forecast_calls=0,prefix_force_calls=0,
            distinction='SUFFIX_FORECASTS_MAY_PAY_COMMAND_ESTIMATION_FROM_OLDER_RECEIVED_OBSERVATIONS')
