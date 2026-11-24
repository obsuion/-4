"""Bounded offline local proofs; no event or physical Sun qualification."""
import argparse
from contextlib import ExitStack
from dataclasses import fields, is_dataclass, replace
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from examples.m2_j2_segments_demo import block_network
from examples.m2_illumination_windows_demo import example_request as global_example
from ops_sim.v5 import orbit_j2_segments as b2, orbit_sun_intervals as b3
from ops_sim.v5.orbit_sun_windows_document import load_window_request
from ops_sim.v5.orbit_sun_local import LocalIlluminationPolicy, LocalIlluminationRequest, evaluate_local_illumination
from ops_sim.v5.orbit_sun_local_document import local_request_digest, load_local_request, save_local_request
from ops_sim.v5.sun_table import SunPositionSample


KINDS = ("illuminated","occulted","refinement","domain","negative","crossing","physical-A","physical-B")


def example_request(kind, reference=None):
    if kind not in KINDS:
        raise ValueError("unknown local example kind")
    if kind.startswith("physical-"):
        if reference is None:
            raise ValueError("physical example requires the unchanged accepted pilot input document")
        base = load_window_request(reference)
        if base.coast.enclosure_policy.step_seconds != 10 or base.end.elapsed_seconds-base.start.elapsed_seconds != 1800:
            raise ValueError("physical reference must be frozen1800/h10 input")
        policy = LocalIlluminationPolicy(3 if kind == "physical-A" else 7,6000,72000,6000,36000,3100000)
        resolution = 1.
    else:
        base = global_example("illuminated" if kind in ("negative","crossing") else kind)
        if kind in ("negative","crossing"):
            anchor = base.coast.trajectory.initial_state.position.instant.elapsed_seconds
            a,b = (anchor-9/64,anchor-3/64) if kind == "negative" else (anchor-9/64,anchor+7/64)
            table = replace(base.table,domain_seconds=(a,b),samples=(SunPositionSample(a,(100.,-1.,0.)),SunPositionSample(b,(100.,1.,0.))))
            base = replace(base,table=table,start=replace(base.start,elapsed_seconds=a),end=replace(base.end,elapsed_seconds=b))
        policy = LocalIlluminationPolicy(7,256,3072,256,20000,131072)
        resolution = base.requested_resolution_seconds
    return LocalIlluminationRequest(base.coast,base.table,base.start,base.end,resolution,policy)


def _wire(value):
    if type(value) is Fraction:
        return {"numerator_hex":hex(value.numerator),"denominator_hex":hex(value.denominator)}
    if type(value) is Decimal:
        return str(value)
    if is_dataclass(value):
        return {f.name:_wire(getattr(value,f.name)) for f in fields(value)}
    if type(value) in (list,tuple):
        return [_wire(x) for x in value]
    if type(value) is dict:
        return {k:_wire(v) for k,v in value.items()}
    return value


def summary(result):
    return {"request_digest":local_request_digest(result.request),
            **{f.name:_wire(getattr(result,f.name)) for f in fields(result) if f.name != "request"}}


def evaluate_timed(request, instrument=False):
    times = {"integration_seconds":0.,"geometry_seconds":0.}
    def timed(fn,stage):
        def call(*a,**k):
            t = perf_counter()
            try: return fn(*a,**k)
            finally: times[stage] += perf_counter()-t
        return call
    with ExitStack() as stack:
        if instrument:
            for owner,name,stage in ((b2,"_initial_box","integration_seconds"),(b2,"_validated_step","integration_seconds"),
                    (b3,"_shape_weights","geometry_seconds"),(b3,"_geometry_cell","geometry_seconds")):
                stack.enter_context(patch.object(owner,name,timed(getattr(owner,name),stage)))
        t = perf_counter();result = evaluate_local_illumination(request);elapsed = perf_counter()-t
    if instrument:
        times["orchestration_seconds"] = elapsed-times["integration_seconds"]-times["geometry_seconds"]
        if times["orchestration_seconds"] < 0:
            raise AssertionError("overlapping instrumentation")
    else:
        times = {"integration_seconds":None,"geometry_seconds":None,"orchestration_seconds":None}
    return result,{"evaluation_seconds":elapsed,"instrumented":instrument,**times}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kind",choices=KINDS,default="refinement");p.add_argument("--reference",type=Path)
    p.add_argument("--inputs",type=Path);p.add_argument("--expected-digest");p.add_argument("--write-inputs",type=Path)
    p.add_argument("--offline",action="store_true");p.add_argument("--instrument",action="store_true")
    a = p.parse_args()
    if a.inputs and a.write_inputs: p.error("choose reconstruction or exclusive creation")
    if a.expected_digest and not a.inputs: p.error("expected-digest requires inputs")
    if a.offline: block_network()
    t = perf_counter()
    q = load_local_request(a.inputs,expected_digest=a.expected_digest) if a.inputs else example_request(a.kind,a.reference)
    load = perf_counter()-t
    if a.write_inputs: save_local_request(a.write_inputs,q)
    result,timing = evaluate_timed(q,a.instrument)
    t = perf_counter();raw = json.dumps(summary(result),indent=2)
    serialize = perf_counter()-t
    print(json.dumps({"evidence":json.loads(raw),"timings":{**timing,"input_load_seconds":load,
        "serialization_seconds":serialize,"serialized_evidence_bytes":len(raw.encode('utf-8'))},
        "python_network_disabled":a.offline},indent=2))


if __name__ == "__main__":main()
