"""B41 supported synthetic continuous cases, not flight qualification."""
from dataclasses import replace
from fractions import Fraction as Q
from math import tau
from .m3_constructor_mission_demo import make_inputs
from ops_sim.v5.mission_continuous_geometry import MODE,ContinuousGeometryPolicy
from ops_sim.v5.environment_mission import MissionAction


def make_continuous_inputs(case='positive'):
    d=make_inputs()
    if case not in ('positive','rotating-contact','endpoint-trap'):raise ValueError('unknown bounded case')
    if case!='positive':
        q=d.environment.source_request;old=q.segment.trajectory.initial_state;f=old.position.frame
        rate=1e-5 if case=='rotating-contact' else tau/64
        rotation=replace(f.rotation,angular_velocity_rad_per_s=replace(f.rotation.angular_velocity_rad_per_s,value=rate))
        f=replace(f,rotation=rotation)
        state=replace(old,position=replace(old.position,frame=f),velocity=replace(old.velocity,frame=f))
        q=replace(q,segment=replace(q.segment,trajectory=replace(q.segment.trajectory,initial_state=state)),table=replace(q.table,frame=f))
        actions=(MissionAction('wait','HOLD_UNTIL',until_seconds=168),MissionAction('contact','CONTACT','station',20)) if case=='rotating-contact' else (MissionAction('trap','CONTACT','station',64),)
        d=replace(d,environment=replace(d.environment,source_request=q),actions=actions)
    return replace(d,geometry_mode=MODE,geometry_policy=ContinuousGeometryPolicy())


def main():
    import argparse
    from pathlib import Path
    from .m3_constructor_mission_demo import run
    from ops_sim.v5.environment_mission_document import load_mission_inputs
    from ops_sim.v5.environment_mission_continuation import scientific_bytes
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();s=run(load_mission_inputs(args.input))
    with Path(args.output).open('xb') as f:f.write(scientific_bytes(s))


if __name__=='__main__':main()