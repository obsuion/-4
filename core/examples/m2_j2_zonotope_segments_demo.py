"""Offline short segment document runner; outputs are separate from inputs.

python -B examples/m2_j2_zonotope_segments_demo.py --input INPUT --output NEW_OUTPUT
The output is complete scientific data, not a loadable checkpoint/certificate.
"""
import argparse
from dataclasses import fields, is_dataclass
from decimal import Decimal
from enum import Enum
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import time

from ops_sim.v5.orbit_j2_zonotope_segments import evaluate_j2_zonotope_segments
from ops_sim.v5.orbit_j2_zonotope_segments_document import load_zonotope_segment_request


def scientific_value(value):
    """Full typed data; Decimal tuples and tuple/list distinction are exact."""
    if isinstance(value, Enum):
        return dict(enum_type=type(value).__module__+'.'+type(value).__qualname__,member=value.name)
    if type(value)is Decimal:
        t=value.as_tuple()
        return dict(decimal_tuple=dict(sign=t.sign,digits=list(t.digits),exponent=t.exponent))
    if type(value)is Fraction:
        return dict(fraction_numerator=str(value.numerator),fraction_denominator=str(value.denominator))
    if type(value)is float:return dict(float_hex=value.hex())
    if is_dataclass(value):
        return dict(record_type=type(value).__module__+'.'+type(value).__qualname__,
                    fields={f.name:scientific_value(getattr(value,f.name))for f in fields(value)})
    if type(value)is tuple:return dict(tuple=[scientific_value(v)for v in value])
    if type(value)is list:return dict(list=[scientific_value(v)for v in value])
    if type(value)is dict:return {k:scientific_value(v)for k,v in value.items()}
    if value is None or type(value)in (str,int,bool):return value
    raise TypeError('Unsupported scientific value or private ownership leak')


def scientific_bytes(value):
    return (json.dumps(scientific_value(value),sort_keys=True,ensure_ascii=False,
                       allow_nan=False,separators=(',',':'))+'\n').encode('utf-8')


def _offline():
    def deny(event,args):
        if event.startswith('socket.')or event=='urllib.Request':
            raise RuntimeError('offline example forbids network')
    sys.addaudithook(deny)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();_offline()
    req=load_zonotope_segment_request(args.input)  # Input-only; no F1 setup force.
    if Fraction(req.end.elapsed_seconds)-Fraction(req.trajectory.initial_state.position.instant.elapsed_seconds)>60:
        parser.error('this example permits only spans <=60 seconds')
    wall=time.perf_counter_ns();cpu=time.process_time_ns()
    result=evaluate_j2_zonotope_segments(req)
    cpu=time.process_time_ns()-cpu;wall=time.perf_counter_ns()-wall
    raw=scientific_bytes(result)
    with args.output.open('xb')as f:f.write(raw)
    print(json.dumps(dict(status=result.status,reason=result.reason,
                         scientific_SHA256=hashlib.sha256(raw).hexdigest(),
                         evaluator_wall_ns=wall,worker_CPU_ns=cpu,
                         document_loading_force_evaluations=0,
                         output=str(args.output)),ensure_ascii=False))


if __name__=='__main__':main()
