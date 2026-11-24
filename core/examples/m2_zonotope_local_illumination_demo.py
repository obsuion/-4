"""Short offline local-refinement runner; derived outputs are never checkpoints.

python -B -m examples.m2_zonotope_local_illumination_demo --input INPUT --output NEW
No long horizon or dispatch integration is authorized by this example.
"""
import argparse
from pathlib import Path
import sys
from examples.m2_zonotope_interval_illumination_demo import scientific_bytes, scientific_value
from ops_sim.v5.orbit_sun_zonotope_local import evaluate_zonotope_local_illumination
from ops_sim.v5.orbit_sun_zonotope_local_document import load_zonotope_local_request


def main():
    def offline(event,args):
        if event.startswith("socket.") or event=="urllib.Request":raise RuntimeError("offline example")
    sys.addaudithook(offline)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--expected-digest")
    a=p.parse_args()
    q=load_zonotope_local_request(a.input,expected_digest=a.expected_digest)
    if q.segment.end.elapsed_seconds-q.segment.trajectory.initial_state.position.instant.elapsed_seconds>30:
        raise ValueError("short example horizon exceeds 30 seconds")
    r=evaluate_zonotope_local_illumination(q)
    with a.output.open("xb") as f:f.write(scientific_bytes(r))


if __name__=="__main__":main()
