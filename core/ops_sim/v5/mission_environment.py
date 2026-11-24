"""Bounded point geometry consumed by the opt-in nominal mission coordinator.

NOMINAL_SAMPLED is never a continuous visibility or RF certificate. Exact
requested times and explicitly rounded binary64 evaluation instants coexist.
Every nominal orbit query starts at the original immutable authority.
"""
from dataclasses import dataclass
from fractions import Fraction as Q
from math import ceil, isfinite, ulp

from .orbit_geometry import GroundPointDefinition, evaluate_ground_point_geometry
from .orbit_visibility import GroundVisibilityPolicy, evaluate_ground_visibility, GroundVisibilityStatus
from .orbit_config import GeometryInstant
from .orbit_j2 import J2CartesianTrajectory, J2RK4SolverConfig, evaluate_j2_cartesian_state
from .orbit_sun_zonotope_local_v2 import ZonotopeLocalIlluminationRequestV2, _request
from .ids import GroundTargetId, GroundStationId
from .frames import CartesianState
from .environment_forcing import _type, _text, _integer

MODE = 'NOMINAL_SAMPLED_J2_POINT_GRID_V1'


@dataclass(frozen=True, slots=True)
class CatalogPoint:
    point: GroundPointDefinition
    visibility_policy: GroundVisibilityPolicy
    station_available: bool
    rf_admitted: bool
    nominal_rate_bps: int
    service_assumption: str

    def __post_init__(self):
        _type(self.point, GroundPointDefinition, 'point')
        GroundPointDefinition(self.point.point_id,self.point.ellipsoid,self.point.latitude_rad,
                              self.point.longitude_rad,self.point.ellipsoidal_height_m)
        _type(self.visibility_policy,GroundVisibilityPolicy,'visibility policy')
        GroundVisibilityPolicy(self.visibility_policy.minimum_elevation_rad)
        _type(self.station_available,bool,'availability');_type(self.rf_admitted,bool,'RF admission')
        _integer(self.nominal_rate_bps,'nominal bitrate')
        if not 0<=self.nominal_rate_bps<=2**40:raise ValueError('bitrate outside bounded domain')
        _text(self.service_assumption,'service assumptions')
        if type(self.point.point_id) is GroundTargetId and (self.station_available or self.rf_admitted or self.nominal_rate_bps):
            raise ValueError('target cannot declare station service')
        if type(self.point.point_id) is GroundStationId and self.nominal_rate_bps<=0:
            raise ValueError('station requires an explicit positive nominal rate')


@dataclass(frozen=True, slots=True)
class SamplingPolicy:
    maximum_interval_seconds: int = 2
    maximum_points: int = 16
    maximum_timestamps: int = 256
    nominal_step_seconds: float = 2.0
    nominal_max_steps: int = 64
    mode: str = MODE

    def __post_init__(self):
        for n,limit in (('maximum_interval_seconds',120),('maximum_points',16),
                        ('maximum_timestamps',256),('nominal_max_steps',256)):
            _integer(getattr(self,n),n)
            if not 1<=getattr(self,n)<=limit:raise ValueError('sampling bound exceeded: '+n)
        _type(self.nominal_step_seconds,float,'nominal step')
        J2RK4SolverConfig(self.nominal_step_seconds,self.nominal_max_steps)
        if type(self.mode) is not str or self.mode!=MODE:raise ValueError('unsupported sampling mode/family')


@dataclass(frozen=True, slots=True)
class MissionPointObservation:
    point_id: GroundTargetId | GroundStationId
    requested_seconds: Q
    evaluated_instant: GeometryInstant
    rounding_seconds: Q
    geometry: object
    visibility: object
    station_available: bool
    rf_admitted: bool
    nominal_rate_bps: int
    service_assumption: str
    mode: str = MODE

    @property
    def direction(self):return self.geometry.spacecraft_to_ground
    @property
    def range_m(self):return self.geometry.slant_range_m
    @property
    def off_nadir_rad(self):return self.geometry.off_nadir_rad
    @property
    def elevation_rad(self):return self.geometry.elevation_rad
    @property
    def visible(self):return self.visibility.status is GroundVisibilityStatus.VISIBLE
    @property
    def serviceable_nominal(self):
        return type(self.point_id) is GroundStationId and self.visible and self.station_available and self.rf_admitted


def query_point_state(source_request, entry, state, *, requested_seconds=None):
    """Simultaneous typed state adapter; no propagation or hidden service claim."""
    q=_request(source_request);_type(entry,CatalogPoint,'catalog entry');entry.__post_init__()
    _type(state,CartesianState,'Cartesian state')
    origin=q.segment.trajectory.initial_state.position
    t=state.position.instant
    if state.position.frame!=origin.frame or state.velocity.frame!=origin.frame or t.epoch!=origin.instant.epoch:
        raise ValueError('foreign frame/epoch')
    if not origin.instant.elapsed_seconds<=t.elapsed_seconds<=q.segment.end.elapsed_seconds:
        raise ValueError('point state outside source domain')
    requested=Q(t.elapsed_seconds) if requested_seconds is None else _type(requested_seconds,Q,'requested time')
    rounding=Q(t.elapsed_seconds)-requested
    if abs(rounding)>Q(ulp(t.elapsed_seconds))/2:raise ValueError('undeclared sample-time rounding')
    if entry.point.ellipsoid!=origin.frame.ellipsoid:raise ValueError('foreign point ellipsoid')
    g=evaluate_ground_point_geometry(entry.point,state)
    v=evaluate_ground_visibility(entry.point,state,entry.visibility_policy)
    return MissionPointObservation(entry.point.point_id,requested,t,rounding,g,v,
        entry.station_available,entry.rf_admitted,entry.nominal_rate_bps,entry.service_assumption)


def sample_catalog(source_request, catalog, times, policy, *, charge=None):
    """Deterministic finite batch; charge is coordinator-owned runtime bookkeeping."""
    q=_request(source_request);_type(policy,SamplingPolicy,'sampling policy');policy.__post_init__()
    _type(catalog,tuple,'catalog');_type(times,tuple,'sample times')
    if not 1<=len(catalog)<=policy.maximum_points or not 1<=len(times)<=policy.maximum_timestamps:
        raise ValueError('batch sampling admission exceeded')
    for p in catalog:_type(p,CatalogPoint,'catalog point');p.__post_init__()
    if len({(type(p.point.point_id),p.point.point_id.value) for p in catalog})!=len(catalog):raise ValueError('duplicate catalog ID')
    if any(type(t) is not Q for t in times) or tuple(sorted(set(times)))!=times:raise ValueError('ordered distinct exact timestamps required')
    origin=Q(q.segment.trajectory.initial_state.position.instant.elapsed_seconds);end=Q(q.segment.end.elapsed_seconds)
    if times[0]<origin or times[-1]>end:raise ValueError('sampling outside source domain')
    solver=J2RK4SolverConfig(policy.nominal_step_seconds,policy.nominal_max_steps)
    ordered=sorted(catalog,key=lambda p:(type(p.point.point_id).__name__,p.point.point_id.canonical))
    results=[]
    for t in times:
        instant=GeometryInstant(q.segment.end.epoch,float(t))
        # Explicit nominal conversion, not authority/time-grid rounding.
        if abs(Q(instant.elapsed_seconds)-t)>Q(ulp(instant.elapsed_seconds))/2:
            raise ValueError('sample instant cannot satisfy declared rounding policy')
        if charge is not None:charge('nominal_orbit_queries',1)
        state=evaluate_j2_cartesian_state(q.segment.trajectory,instant,solver)
        for p in ordered:
            if charge is not None:charge('point_geometry_queries',1)
            results.append(query_point_state(q,p,state,requested_seconds=t))
    return tuple(results)


def sample_interval(source_request,entry,start,end,policy,*,charge=None):
    _type(start,Q,'start');_type(end,Q,'end')
    if start>end:raise ValueError('backward interval')
    count=max(1,ceil((end-start)/policy.maximum_interval_seconds))
    times=tuple(start+(end-start)*Q(i,count) for i in range(count+1)) if end>start else (start,)
    return sample_catalog(source_request,(entry,),times,policy,charge=charge)
