"""B59 source-owned terminal authority; never inferred from a journal/CSV.

Model-bound records are produced at the committed physical boundary. Application
records bind that state, the final native checkpoint and the immutable job.
UNKNOWN never grants an endpoint or continuation. Float invariants are MODEL,
not hardware power deficits. No arbitrary trial object is serialized.
"""
from copy import deepcopy
from .lifecycle_contract import integer,identity
FORMAT='B59_TYPED_TERMINAL_V1'
KINDS=('TARGET','RESOURCE_TIME','RESOURCE_OUTPUT','USER','PHYSICAL','MODEL','UNSUPPORTED','PROCESS_FAILURE','UNKNOWN')
FIELDS=('format','kind','code','stage','owner','clock','automatic_resume')

def make_terminal(kind,code,stage,owner,clock):
    t=dict(format=FORMAT,kind=kind,code=code,stage=stage,owner=owner,clock=clock,
           automatic_resume=kind in ('RESOURCE_TIME','RESOURCE_OUTPUT'))
    return admit_terminal(t)

def admit_terminal(t):
    if type(t)is not dict or set(t)!=set(FIELDS) or t['format']!=FORMAT or type(t['kind'])is not str or t['kind']not in KINDS:raise ValueError('typed terminal schema')
    for n in ('code','stage','owner'):
        if type(t[n])is not str or not 1<=len(t[n])<=400:raise ValueError('bounded terminal text')
    if t['clock']is not None:integer(t['clock'],'terminal clock')
    if t['kind']not in ('PROCESS_FAILURE','UNKNOWN') and t['clock']is None:raise ValueError('selected prefix clock required')
    if type(t['automatic_resume'])is not bool or t['automatic_resume']!=(t['kind']in ('RESOURCE_TIME','RESOURCE_OUTPUT')):raise ValueError('terminal continuation policy')
    return deepcopy(t)

def physical_terminal(outcome,clock):
    # Only the actual physical owner's returned refusal is admitted. This is a
    # fixed source-owned code-family mapping, never a user-selected class or an
    # event-string parser. Unknown refusal families fail closed as MODEL.
    if outcome.status!='refused':raise ValueError('actual refusal required')
    code=outcome.reason
    if type(code)is not str:raise ValueError('actual owner refusal code')
    if code.startswith(('BATTERY_PORT_DOMAIN_REFUSED:BATTERY_PORT_RETURNED_',
                        'BATTERY_PORT_DOMAIN_REFUSED:BATTERY_PORT_TRANSITION_',
                        'BATTERY_PORT_DOMAIN_REFUSED:BATTERY_PORT_FEASIBILITY_ROUNDING_',
                        'BATTERY_PORT_DOMAIN_REFUSED:BATTERY_PORT_SIMULTANEOUS_')):
        kind='MODEL'
    elif code.startswith(('UNSUPPORTED_','UNRESOLVED_','BATTERY_PORT_DOMAIN_REFUSED:',
                          'ACTION_EXCEEDS_BOUND_ENVIRONMENT','LIFECYCLE_LOCAL_')):
        kind='UNSUPPORTED'
    elif code.startswith(('B55_POWER_SERVICE_INTERRUPTED:','FULL_ELECTRICAL_SERVICE_UNAVAILABLE',
                          'OPERATING_TEMPERATURE_','B55_SURVIVAL_TEMPERATURE_',
                          'B55_POINT_ENERGY_RESERVE_UNAVAILABLE',
                          'B56_SOLAR_SLEW_AND_MINIMUM_HOLD_RESERVE_UNAVAILABLE')):
        kind='PHYSICAL'
    else:kind='MODEL'
    return make_terminal(kind,code,'ACTUAL_'+outcome.kind,'lifecycle_physics',clock)

def terminal_for_state(state,quota_stop,target):
    if state.terminal is not None:return admit_terminal(state.terminal)
    if state.clock>=target:
        if state.clock!=target or state.status not in ('ACTIVE','COMPLETE'):raise ValueError('unsupported target terminal')
        return make_terminal('TARGET','BOUND_TARGET_REACHED','COMMITTED_BOUNDARY','lifecycle_execution',state.clock)
    if state.status!='ACTIVE':return make_terminal('MODEL',state.status,'COMMITTED_BOUNDARY','lifecycle_execution',state.clock)
    mapping={'WORKER_LOCAL_SOFT_BUDGET_PAID_PREFIX':'RESOURCE_TIME',
             'PROSPECTIVE_OUTPUT_ADMISSION_BEFORE_NEXT_MODEL_TRANSITION':'RESOURCE_OUTPUT',
             'USER_COOPERATIVE_STOP_BEFORE_NEXT_MODEL_TRANSITION':'USER'}
    if quota_stop not in mapping:raise ValueError('unrecognized settled stop authority')
    return make_terminal(mapping[quota_stop],quota_stop,'BEFORE_NEXT_TRANSITION','lifecycle_application',state.clock)

def bind_terminal(t,job,checkpoint):
    t=admit_terminal(t)
    return dict(format='B59_BOUND_TERMINAL_V1',terminal=t,job_id=job['job_id'],root_identity=job['root_identity'],
                source_identity=job['source_identity'],runtime=job['runtime'],checkpoint_sha256=checkpoint['sha256'])

def admit_bound_terminal(value,job,result):
    fields=('format','terminal','job_id','root_identity','source_identity','runtime','checkpoint_sha256')
    if type(value)is not dict or set(value)!=set(fields) or value['format']!='B59_BOUND_TERMINAL_V1':raise ValueError('bound terminal schema')
    for n in ('job_id','root_identity','source_identity','runtime'):
        if value[n]!=job[n]:raise ValueError('terminal job binding: '+n)
    identity(value['checkpoint_sha256'])
    if value['checkpoint_sha256']!=result['checkpoint']['sha256']:raise ValueError('terminal native binding')
    t=admit_terminal(value['terminal'])
    for n in ('clock','actual_end_seconds','target_seconds'):integer(result[n],'terminal '+n)
    if t['clock']!=result['clock'] or result['actual_end_seconds']!=t['clock']:raise ValueError('terminal selected clock')
    if t['kind']=='TARGET':
        if t['clock']!=result['target_seconds'] or result['application_status']!='COMPLETED_WINDOW':raise ValueError('terminal target binding')
    elif t['kind'] in ('RESOURCE_TIME','RESOURCE_OUTPUT','USER'):
        app={'RESOURCE_TIME':'INCOMPLETE_BUDGET_STOP','RESOURCE_OUTPUT':'INCOMPLETE_APPLICATION_ADMISSION','USER':'INCOMPLETE_STOP'}[t['kind']]
        if result['status']!='ACTIVE' or result['application_status']!=app:raise ValueError('resumable terminal needs settled ACTIVE prefix')
    elif result['status']=='ACTIVE' or result['application_status']!='INCOMPLETE_MODEL_STATUS':raise ValueError('physical/model stop cannot be ACTIVE or completed')
    if result['reason']!=t['code']:raise ValueError('top-level terminal reason binding')
    return t


def admit_native_terminal(document,t,result):
    """Read only scalar maps from an already admitted fixed native graph.

    No materializer, physical model, replay or arbitrary payload class imports.
    The native state is the authority, not a last-event string or summary CSV.
    """
    graph=document['graph'];visits=0
    def scalar(token):
        nonlocal visits
        visits+=1
        if visits>128:raise ValueError('bounded terminal scalar traversal')
        if token[0]=='none' and len(token)==1:return None
        if token[0]=='str' and len(token)==2 and type(token[1])is str:return token[1]
        if token[0]=='bool' and len(token)==2 and type(token[1])is bool:return token[1]
        if token[0]=='int' and len(token)==2:return int(token[1])
        if token[0]=='ref':return {scalar(k):scalar(v) for k,v in mapping(token)}
        raise ValueError('terminal scalar token')
    def mapping(token):
        if token[0]!='ref':raise ValueError('native map reference')
        node=graph['nodes'][token[1]]
        if node[0]!='map':raise ValueError('native terminal map')
        # Return token pairs as a list: token lists themselves are unhashable.
        return node[1]
    def field(token,key):
        found=[v for k,v in mapping(token) if k==['str',key]]
        if len(found)!=1:raise ValueError('native terminal field '+key)
        return found[0]
    state=field(graph['value'],'state')
    status=scalar(field(state,'status'))
    token=field(state,'terminal')
    if token[0]=='none':native=None
    else:
        native={scalar(k):scalar(v) for k,v in mapping(token)}
        admit_terminal(native)
    if status!=result['status'] or document['bindings']['clock']!=t['clock']:raise ValueError('native terminal clock/status')
    if native is not None:
        if native!=t:raise ValueError('native typed boundary disagreement')
    elif t['kind'] not in ('TARGET','RESOURCE_TIME','RESOURCE_OUTPUT','USER'):
        if t['kind']!='MODEL' or t['code']!=status:raise ValueError('missing native model terminal')
    elif t['kind']!='TARGET' and status!='ACTIVE':raise ValueError('native resource cut is not ACTIVE')
    return t
