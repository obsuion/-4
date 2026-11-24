"""Common deterministic paid suffix heuristic; execute only the first action."""
from dataclasses import dataclass, replace
from .long_mission import LongMissionAction as Action
from .rolling_forecast import PlanningView, forecast_suffix
from .rolling_physics import digest


@dataclass(frozen=True, slots=True)
class RollingDecision:
    decision_id: str
    view_identity: str
    knowledge_age_seconds: int
    selected_suffix: tuple
    explanation: str
    forecasts: tuple
    rejected: tuple


def build_candidates(view):
    """No future requests/acks and no design-name branches. Explicit capacity screen.

    Future declared service is an optimistic capacity screen, never an RF receipt
    promise. Actual sampled geometry/protection/custody decide each paid branch.
    """
    from .command_estimation import CommandPlanningView
    command=type(view) is CommandPlanningView
    if type(view) not in (PlanningView,CommandPlanningView): raise TypeError('public planning view required')
    view.__post_init__(); now=view.now_seconds; end=min(int(view.model.environment.end_seconds),now+view.policy.lookahead_seconds)
    known=view.knowledge; acquired=known.acquired_ids(); pending=known.pending()
    rank=lambda r:(-r.product.request.priority_weight,r.product.delivery_deadline_seconds,r.product.request.request_id.value)
    contacts=tuple(replace(c,start_seconds=max(now,c.start_seconds)) for c in view.contacts if now<c.end_seconds<=end)
    candidates=[]; rejected=[]
    prefix='f-'+view.identity[:16]
    def add(tag, actions):
        if 2<=len(actions)<=view.policy.suffix_actions:
            candidates.append((tag,tuple(actions)))
    def hold(tag,t): return Action(prefix+'-'+tag,'HOLD_UNTIL',until_seconds=t)
    def tx(tag,c): return Action(prefix+'-'+tag,'CONTACT',c.station_id,c.end_seconds-c.start_seconds)
    acknowledged_ids=known.acknowledged_ids()
    def repeated(first):
        return any(c.issued_at_seconds==now and (c.kind,c.point_id,c.product_id)==(first.kind,first.point_id,first.product_id)
                   for c in known.issued)
    for r in sorted(view.requests,key=rank):
        p=r.product; rid=p.request.request_id.value; target=p.request.target_id.value
        if rid in acquired or now+r.acquisition_duration_seconds>p.acquisition_end_seconds or any(c.product_id==rid for c in pending):
            rejected.append((rid,'ACQUIRED_PENDING_OR_WINDOW_EXPIRED'));continue
        if any(c.kind=='POINT' for c in pending) and (not command or not view.point_assumption_ready()):
            rejected.append((rid,'WAIT_FOR_RECEIVED_POSE_ACK'));continue
        from .ms_product import size_ms_grid
        optical=view.model.simulation_inputs.spacecraft_configuration.payload.optical_acquisition
        spacing=optical.multispectral_reference_sample_spacing_m.value
        if spacing>p.maximum_spacing_x_m or spacing>p.maximum_spacing_y_m:
            rejected.append((rid,'DECLARED_MS_SAMPLING_CAPABILITY_INSUFFICIENT'));continue
        bits=size_ms_grid(p.footprint,spacing,spacing,p.required_channels,int(optical.acquisition_bits_per_sample.value)).stored_bits
        eligible=tuple(c for c in contacts if c.start_seconds>=now+r.acquisition_duration_seconds and c.start_seconds<p.delivery_deadline_seconds)
        remaining=sum(int(x.stored_equivalent_bits) for x in known.observation.onboard_records)-sum(int(x.transmitted_equivalent_bits) for x in known.observation.partial_transfers)
        rate=int(view.model.simulation_inputs.spacecraft_configuration.communications.nominal_downlink_data_rate_bps.value)
        capacity=sum(rate*max(0,min(c.end_seconds,p.delivery_deadline_seconds)-c.start_seconds) for c in eligible)
        if not eligible or capacity<remaining+bits:
            rejected.append((rid,'DECLARED_CAPACITY_SCREEN'));continue
        for c in eligible[:2]:
            for point in (False,True):
                tag=rid+('-point' if point else '-held')+'-'+c.contact_id
                a=[]
                if point: a.append(Action(prefix+'-'+tag+'-point','POINT',target))
                if now<p.acquisition_start_seconds:
                    a.append(hold(tag+'-open',p.acquisition_start_seconds))
                a.append(Action(prefix+'-'+tag+'-image','CAPTURE',target,r.acquisition_duration_seconds,product_id=rid))
                # The paid trial validates whether the slew/acquisition actually fits.
                a.extend((hold(tag+'-wait',c.start_seconds),tx(tag+'-tx',c)))
                if a and not repeated(a[0]): add(tag,a)
    if known.observation.onboard_records and not any(c.kind=='CONTACT' for c in pending):
        for c in contacts[:2]:
            actions=([hold('backlog-wait-'+c.contact_id,c.start_seconds)] if c.start_seconds>now else [])+[tx('backlog-'+c.contact_id,c)]
            # An actual contact followed by real standby is a linked suffix too.
            if len(actions)==1 and c.end_seconds<end: actions.append(hold('post-contact-'+c.contact_id,min(end,c.end_seconds+view.policy.recovery_seconds)))
            if actions and not repeated(actions[0]): add('backlog-'+c.contact_id,actions)
    # Public event/poll boundaries only; private queue contents are not inspected.
    events=[now+view.policy.recovery_seconds,end]
    events += [p.product.acquisition_start_seconds for p in view.requests if p.product.acquisition_start_seconds>now]
    events += [c.start_seconds for c in contacts if c.start_seconds>now]
    events += [c.feedback_due_seconds for c in pending if c.feedback_due_seconds>now]
    # Once all released requests are acquired/expired and no pending useful work,
    # longer real HOLD reduces boundary overhead, still within 600s lookahead.
    idle=not pending and not known.observation.onboard_records and all(r.product.request.request_id.value in acquired or now>=r.product.acquisition_end_seconds for r in view.requests)
    stop=end-1 if idle and end-now>1 else min(t for t in events if now<t<=end)
    if stop>now:
        second=min(end,stop+1)
        if second==stop: # terminal one-action tail is explicit, not a fake suffix.
            rejected.append(('HOLD','TERMINAL_SINGLE_ACTION_TAIL'))
        else: add('recovery', (hold('recovery',stop),hold('recovery-linked',second)))
    if len(candidates)>view.policy.max_candidates:
        raise ValueError('B47_CANDIDATE_BOUND')
    return tuple(candidates),tuple(rejected)


def select_rolling(view,cache,work,quotas):
    from .command_estimation import CommandPlanningView
    if type(view) is CommandPlanningView:
        from .command_controller import select_command
        return select_command(view,cache,work,quotas)
    if type(view) is not PlanningView: raise TypeError('selector receives immutable view only')
    view.__post_init__(); candidates,rejected=build_candidates(view)
    forecasts=[]; admissible=[]
    weights={r.product.request.request_id.value:r.product.request.priority_weight for r in view.requests}
    deadlines={r.product.request.request_id.value:r.product.delivery_deadline_seconds for r in view.requests}
    already={d.record.record_id for d in view.knowledge.observation.delivery_acks}
    acquired=view.knowledge.acquired_ids()
    old_partial=sum(int(p.transmitted_equivalent_bits) for p in view.knowledge.observation.partial_transfers)
    def priority(item):
        tag,suffix=item
        captured=[weights.get(a.product_id,0) for a in suffix if a.kind=='CAPTURE']
        backlog=max((weights.get(r.imaging_request_id.value,0) for r in view.knowledge.observation.onboard_records),default=0)
        score=max(captured,default=backlog if any(a.kind=='CONTACT' for a in suffix) else 0)
        deadline=min((deadlines.get(a.product_id,2**40) for a in suffix if a.kind=='CAPTURE'),default=2**40)
        return (-score,deadline)
    candidates=tuple(sorted(candidates,key=priority))
    for tag,suffix in candidates:
        f=forecast_suffix(view,suffix,cache,work,quotas); forecasts.append((tag,f))
        if f.status!='admissible':
            rejected=(*rejected,(tag,f.reason));continue
        # Bounded greedy admission, not exhaustive optimization. All tried
        # higher-ranked suffixes have paid complete/refused evidence. Once a
        # feasible linked suffix is found, lower ranks remain explicitly untried.
        explanation='PAID_GREEDY_PRIORITY_DEADLINE_FIRST_FEASIBLE:'+tag
        return RollingDecision(digest((view.identity,tag,f.suffix)),view.identity,
            view.now_seconds-view.knowledge.observation.observed_at_seconds,f.suffix,explanation,
            tuple(forecasts),tuple(rejected))
    if not admissible:
        return RollingDecision(digest((view.identity,'NO_ADMISSIBLE_SUFFIX')),view.identity,
            view.now_seconds-view.knowledge.observation.observed_at_seconds,(),'NO_ADMISSIBLE_SUFFIX',tuple(forecasts),tuple(rejected))
