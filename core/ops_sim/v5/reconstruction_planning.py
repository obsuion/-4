"""Sound static replay reservations from immutable input/program, never results.

Contact work counts captures (records), forcing partitions, both wait/tx
predictions and idle. Selected tx reuses the paid prediction; no second charge.
"""
from dataclasses import dataclass
from math import ceil
from .long_environment import CONTINUOUS

METHOD='INPUT_DERIVED_CONTACT_RECORD_PARTITION_REPLAY_BOUND_V2'


@dataclass(frozen=True,slots=True)
class ReconstructionPlan:
    runtime: dict
    construction: dict
    action_bounds: tuple
    method: str=METHOD


def plan_reconstruction(inputs,cursor):
    if type(cursor) is not int or not 0<=cursor<=len(inputs.actions):raise ValueError('bounded replay cursor')
    e=inputs.environment;l=inputs.limits;span=e.end_seconds-e.start_seconds
    profiles=len(e.profile)-1;table=len(e.table.samples)-2
    support_endpoints=0
    if e.mode==CONTINUOUS:
        # Overlay output is charged geometry cells; source-record admission also
        # bounds retained pieces. Two endpoints per possible retained support.
        support_endpoints=2*min(2*e.source_request.policy.max_geometry_cells,e.max_source_records)
    def structural_cuts(duration):
        lighting=0 if e.mode==CONTINUOUS else ceil(duration/e.lighting_step_seconds)+1
        return profiles+table+support_endpoints+lighting
    rows=[];records=0;noncontact=contact_reserved=contact_proposals=contacts=points=orientations=0
    for action in inputs.actions[:cursor]:
        before=records
        if action.kind=='CONTACT':
            # Whole contact can move at most duration; use all possibly crossed
            # profile/table/support boundaries, not a packet's selected graph.
            segments=min(8192,1+structural_cuts(action.duration_seconds))
            n=2**l.contact_integration_level
            reserved=segments*n*(2*before+1)
            # Each completed record disappears; each forcing boundary can
            # split at most one still-partial record. A denied attempt stops
            # the whole atomic contact, so it cannot be retried in all cells.
            attempts=0 if before==0 else before+segments-1
            proposals=n*(2*attempts+segments)
            contact_reserved+=reserved;contact_proposals+=proposals;contacts+=segments
            orientations+=segments
            points+=ceil(action.duration_seconds/inputs.sampling.maximum_interval_seconds)+1
            rows.append(dict(action=action.action_id,kind=action.kind,possible_records=before,forcing_segments=segments,
                integration_substeps=n,physical_reservations=reserved,physical_proposals=proposals))
        else:
            duration=120 if action.kind=='POINT' else action.duration_seconds if action.kind=='CAPTURE' else max(0,action.until_seconds-e.start_seconds)
            duration=min(duration,span)
            extra=4 if action.kind=='POINT' else 0
            parts=min(l.max_action_cells,ceil(duration/l.max_interval_seconds)+structural_cuts(duration)+extra)
            noncontact+=parts;orientations+=parts
            if action.kind=='POINT':points+=1
            elif action.kind=='CAPTURE':
                records+=1;orientations+=1
                points+=ceil(duration/inputs.sampling.maximum_interval_seconds)+1
            rows.append(dict(action=action.action_id,kind=action.kind,possible_records=before,physical_partitions=parts))
    queries=sum(a.kind in ('CAPTURE','CONTACT') for a in inputs.actions[:cursor]) if e.mode==CONTINUOUS else 0
    nominal_lighting_queries=0 if e.mode==CONTINUOUS else ceil(span/e.lighting_step_seconds)
    runtime=dict(runtime_entries=1,upstream_entries=int(e.mode==CONTINUOUS),
        physical_reserved_calls=noncontact+contact_reserved,
        nominal_force_reserved=inputs.nominal_policy.max_force_reservations,
        nominal_control_units=inputs.nominal_policy.max_control_units,index_control_units=e.max_index_control_units,
        spatial_reserved_units=65536+cursor*65536+sum(a.kind=='POINT' for a in inputs.actions[:cursor])*(65536+2048)+128*orientations,
        nominal_orbit_queries=orientations+points+nominal_lighting_queries,
        point_geometry_queries=points,geometry_queries=queries,
        geometry_operations=queries*inputs.geometry_policy.maximum_operations,
        geometry_control_units=queries*inputs.geometry_policy.maximum_control_units,
        output_control_units=(cursor+2)*(8*2**20+(l.max_document_bytes+63)//64))
    construction=dict(line_calls_reserved=8*(noncontact+contact_proposals),compilation_calls=cursor+2,control_units=(cursor+2)*32768)
    return ReconstructionPlan(runtime,construction,tuple(rows))


def admit_runtime(plan,inputs,work):
    l=inputs.limits;work.validate(l)
    caps=dict(output_control_units=l.max_output_control_units,runtime_entries=l.max_runtime_entries,
        upstream_entries=l.max_runtime_upstream_entries,physical_reserved_calls=l.max_physical_substeps,
        nominal_force_reserved=l.max_nominal_force_reserved,nominal_control_units=l.max_nominal_control_units,
        index_control_units=l.max_index_control_units,spatial_reserved_units=l.max_spatial_reserved_units,
        nominal_orbit_queries=l.max_nominal_orbit_queries,point_geometry_queries=l.max_point_geometry_queries,
        geometry_queries=l.max_geometry_queries,geometry_operations=l.max_geometry_operations,geometry_control_units=l.max_geometry_control_units)
    for field,count in plan.runtime.items():
        if getattr(work,field)+count>caps[field]:raise ValueError('RECONSTRUCTION_ADMISSION:'+field)


def admit_construction(plan,inputs,work):
    limits=inputs.limits;work.validate(limits)
    caps=dict(line_calls_reserved=limits.max_line_calls,compilation_calls=limits.max_compilations,control_units=limits.max_control_units)
    for field,count in plan.construction.items():
        if getattr(work,field)+count>caps[field]:raise ValueError('CONSTRUCTION_RECONSTRUCTION_ADMISSION:'+field)
