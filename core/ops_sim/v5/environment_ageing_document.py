"""Exact bounded JSON policy fields. No executable or arbitrary graph owners."""
from dataclasses import fields,asdict
from .environment_ageing import EnvironmentAgeingPolicy,EmissivityAgeing,ConductanceAgeing
from .experiment_codec import object_fields

def to_data(p):
    if type(p)is not EnvironmentAgeingPolicy:raise TypeError('B61 exact policy')
    p.__post_init__();return asdict(p)

def from_data(data):
    object_fields(data,tuple(f.name for f in fields(EnvironmentAgeingPolicy)))
    d=dict(data)
    for n,owner,cap in (('emissivity',EmissivityAgeing,16),('conductance',ConductanceAgeing,32)):
        a=d[n]
        if type(a)is not list or len(a)>cap:raise ValueError('B61 bounded property array')
        d[n]=tuple(owner(**object_fields(v,tuple(f.name for f in fields(owner))))for v in a)
    return EnvironmentAgeingPolicy(**d)


def requested_policy(value,network):
    if type(value)is str and value=='LEGACY':return None
    if type(value)is dict:return from_data(value)
    if type(value)is not str or value not in ('B61_ASSUMED_V1','B61_ACCELERATED_ASSUMED_V1'):raise ValueError('B61 explicit ageing selection')
    rate=1.e-10 if value=='B61_ASSUMED_V1'else 1.e-6
    return EnvironmentAgeingPolicy(pv_floor_fraction=.7,pv_calendar_rate_per_second=rate/10.,pv_exposure_rate_per_second=rate,
        emissivity=tuple(sorted((EmissivityAgeing(n.node_id.value,.3,rate/10.,rate)for n in network.nodes),key=lambda x:x.node_id)),
        conductance=tuple(sorted((ConductanceAgeing(l.link_id.value,l.conductance_w_per_k.value*.7,rate/10.,rate)for l in network.links),key=lambda x:x.link_id)),
        assumption='ASSUMED_NOT_CALIBRATED'if value=='B61_ASSUMED_V1'else'SYNTHETIC_ACCELERATED_ASSUMED')
