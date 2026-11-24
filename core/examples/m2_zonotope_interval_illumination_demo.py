"""Short offline input-only runner. Outputs are derived data, never checkpoints.

python -B -m examples.m2_zonotope_interval_illumination_demo --input INPUT --output NEW
Six source-bound inputs and replay evidence are supplied in the review package.
"""
import argparse
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
import json
from pathlib import Path
import sys

from ops_sim.v5.orbit_sun_zonotope_intervals import evaluate_zonotope_interval_illumination
from ops_sim.v5.orbit_sun_zonotope_intervals_document import load_zonotope_interval_request


def scientific_value(v):
    if isinstance(v, Enum):
        return dict(enum_type=type(v).__module__+"."+type(v).__qualname__, member=v.name)
    if type(v) is Decimal:
        t = v.as_tuple()
        return dict(decimal_tuple=dict(sign=t.sign, digits=list(t.digits), exponent=t.exponent))
    if type(v) is Fraction:
        return dict(numerator_hex=hex(v.numerator), denominator_hex=hex(v.denominator))
    if type(v) is float:
        return dict(float_hex=v.hex())
    if is_dataclass(v):
        return dict(record_type=type(v).__module__+"."+type(v).__qualname__,
                    fields={f.name:scientific_value(getattr(v,f.name)) for f in fields(v)})
    if type(v) in (tuple,list):
        return {"tuple" if type(v) is tuple else "list":[scientific_value(x) for x in v]}
    if type(v) is dict:
        return {k:scientific_value(x) for k,x in v.items()}
    if v is None or type(v) in (str,int,bool):
        return v
    raise TypeError("unsupported scientific output/private authority")


def scientific_bytes(v):
    return (json.dumps(scientific_value(v), sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(",",":"))+"\n").encode("utf-8")


def main():
    def offline(event, args):
        if event.startswith("socket.") or event == "urllib.Request":
            raise RuntimeError("offline example")
    sys.addaudithook(offline)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-digest")
    args = parser.parse_args()
    request = load_zonotope_interval_request(args.input, expected_digest=args.expected_digest)
    if request.segment.end.elapsed_seconds-request.segment.trajectory.initial_state.position.instant.elapsed_seconds > 30:
        raise ValueError("short example horizon exceeds 30 seconds")
    result = evaluate_zonotope_interval_illumination(request)
    with args.output.open("xb") as stream:
        stream.write(scientific_bytes(result))


if __name__ == "__main__":
    main()
