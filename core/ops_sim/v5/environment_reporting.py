"""Bounded selected-only B61 report, no forecast extrema mixed into actual."""
from copy import deepcopy
from .environment_lifecycle import projection,validate_projection
from .experiment_codec import object_fields

def _runtime(root,prepared_runtime):
    if prepared_runtime is None:return None
    from .lifecycle_prepared import PreparedRuntime
    from .lifecycle_job_prepared import PreparedRoleState
    if type(prepared_runtime)not in (PreparedRuntime,PreparedRoleState) or prepared_runtime.role!='ACTUAL':raise TypeError('selected report requires exact ACTUAL runtime')
    if root is not prepared_runtime._external_root and root is not prepared_runtime.root:raise ValueError('B63 foreign prepared report root')
    if type(prepared_runtime)is PreparedRoleState:prepared_runtime.require_transaction()
    return prepared_runtime


def initial(root,history,*,prepared_runtime=None):
    prepared_runtime=_runtime(root,prepared_runtime)
    base=root.base.model.simulation_inputs.spacecraft_configuration.thermal.network
    v=projection(root.environment_ageing_policy,history,base,prepared_runtime=prepared_runtime)
    return dict(method='B61_SELECTED_ENVIRONMENT_REPORT_V1',initial=v,end=v,
        minimum_emissivity=dict(v['emissivity']),maximum_emissivity=dict(v['emissivity']),
        minimum_conductance_w_per_k=dict(v['conductance_w_per_k']),maximum_conductance_w_per_k=dict(v['conductance_w_per_k']))

def advance(data,root,before,after,*,prepared_runtime=None):
    prepared_runtime=_runtime(root,prepared_runtime)
    base=root.base.model.simulation_inputs.spacecraft_configuration.thermal.network
    b=projection(root.environment_ageing_policy,before,base,prepared_runtime=prepared_runtime);e=projection(root.environment_ageing_policy,after,base,prepared_runtime=prepared_runtime)
    if data['end']!=b:raise ValueError('B61 selected report support gap')
    d=deepcopy(data);d['end']=e
    # Each declared property is monotone in nonnegative calendar/exposure.
    # Endpoint extrema therefore cover this start-held property law, not T.
    for prefix,key in (('emissivity','emissivity'),('conductance_w_per_k','conductance_w_per_k')):
        for n,v in e[key].items():
            d['minimum_'+prefix][n]=min(d['minimum_'+prefix][n],v)
            d['maximum_'+prefix][n]=max(d['maximum_'+prefix][n],v)
    return d

def validate(data,root,start,end,*,prepared_runtime=None):
    prepared_runtime=_runtime(root,prepared_runtime)
    object_fields(data,('method','initial','end','minimum_emissivity','maximum_emissivity','minimum_conductance_w_per_k','maximum_conductance_w_per_k'))
    if data['method']!='B61_SELECTED_ENVIRONMENT_REPORT_V1':raise ValueError('B61 report method')
    a=validate_projection(data['initial'],root,start,prepared_runtime=prepared_runtime);b=validate_projection(data['end'],root,end,prepared_runtime=prepared_runtime)
    if b.pv_exposure_seconds<a.pv_exposure_seconds or b.thermal_exposure_seconds<a.thermal_exposure_seconds or b.selected_cuts<a.selected_cuts:raise ValueError('B61 report negative exposure')
    for n in ('emissivity','conductance_w_per_k'):
        lo=data['minimum_'+n];hi=data['maximum_'+n]
        if type(lo)is not dict or type(hi)is not dict or set(lo)!=set(data['initial'][n])or set(hi)!=set(lo):raise ValueError('B61 report property IDs')
        for key in lo:
            x=data['initial'][n][key];y=data['end'][n][key]
            if type(lo[key])not in (int,float)or type(hi[key])not in (int,float)or lo[key]!=min(x,y)or hi[key]!=max(x,y):raise ValueError('B61 report monotone property extrema')
    return data
