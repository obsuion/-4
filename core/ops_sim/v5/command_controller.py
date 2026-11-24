"""Versioned B48 consumer of paid estimates, retaining known-custody guards."""
from dataclasses import dataclass
from .command_estimation import CommandPlanningView, forecast_command_suffix, CONTROLLER
from .rolling_controller import RollingDecision, build_candidates
from .rolling_physics import digest
from .long_mission import LongMissionAction


@dataclass(frozen=True, slots=True)
class CommandDecision(RollingDecision):
    controller_method: str = CONTROLLER
    estimate_identity: str = ''
    assumption: str = 'UNCONFIRMED_COMMAND_FOLLOWING_NO_CERTIFIED_ERROR_BOUND'


def select_command(view,cache,work,quotas):
    if type(view) is not CommandPlanningView:raise TypeError('exact command view')
    view.__post_init__();candidates,rejected=build_candidates(view)
    weights={r.product.request.request_id.value:r.product.request.priority_weight for r in view.requests}
    deadlines={r.product.request.request_id.value:r.product.delivery_deadline_seconds for r in view.requests}
    def rank(item):
        _,suffix=item
        captured=[weights.get(a.product_id,0) for a in suffix if a.kind=='CAPTURE']
        backlog=max((weights.get(r.imaging_request_id.value,0) for r in view.knowledge.observation.onboard_records),default=0)
        return (-max(captured,default=backlog if any(a.kind=='CONTACT' for a in suffix) else 0),
            min((deadlines.get(a.product_id,2**40) for a in suffix if a.kind=='CAPTURE'),default=2**40))
    forecasts=[]
    for tag,suffix in sorted(candidates,key=rank):
        f=forecast_command_suffix(view,suffix,cache,work,quotas);forecasts.append((tag,f))
        if f.status!='admissible':rejected=(*rejected,(tag,f.reason));continue
        return CommandDecision(digest((CONTROLLER,view.identity,tag,f.suffix)),view.identity,
            view.now_seconds-view.knowledge.observation.observed_at_seconds,f.suffix,
            'B48_PAID_GREEDY_COMMAND_ESTIMATE:'+tag,tuple(forecasts),tuple(rejected),CONTROLLER,digest(f.estimate),view.estimation.assumption)
    unsupported=any(f.estimate.status=='UNSUPPORTED' for _,f in forecasts)
    end=min(int(view.model.environment.end_seconds),view.now_seconds+view.policy.recovery_seconds)
    if unsupported and end-view.now_seconds>=2 and not any(c.kind=='HOLD_UNTIL' and c.issued_at_seconds==view.now_seconds for c in view.knowledge.issued):
        due=[c.feedback_due_seconds for c in view.knowledge.pending() if view.now_seconds<c.feedback_due_seconds<end]
        stop=min(due) if due else end-1
        if stop>=end:stop=end-1
        if stop>view.now_seconds:
            suffix=(LongMissionAction('unsupported-wait-'+view.identity[:16],'HOLD_UNTIL',until_seconds=stop),
                LongMissionAction('unsupported-wait-tail-'+view.identity[:16],'HOLD_UNTIL',until_seconds=end))
            return CommandDecision(digest((CONTROLLER,view.identity,'UNSUPPORTED_WAIT')),view.identity,
                view.now_seconds-view.knowledge.observation.observed_at_seconds,suffix,
                'B48_UNSUPPORTED_ESTIMATE_PAID_WAIT_NO_FORECAST_CERTIFICATE',tuple(forecasts),tuple(rejected))
    return CommandDecision(digest((CONTROLLER,view.identity,'NO_ADMISSIBLE')),view.identity,
        view.now_seconds-view.knowledge.observation.observed_at_seconds,(),'B48_NO_ADMISSIBLE_SUFFIX',tuple(forecasts),tuple(rejected))
