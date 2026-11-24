"""Short bounded offline window searches; no event or physical qualification."""
import argparse
from dataclasses import asdict, fields, replace
import json
from pathlib import Path
from time import perf_counter

from examples.m2_interval_illumination_demo import example_request as interval_example, summary as interval_summary, _wire
from examples.m2_j2_segments_demo import block_network
from ops_sim.v5.sun_table import SunPositionSample
from ops_sim.v5.orbit_sun_windows import (
    IlluminationSearchPolicy, IlluminationWindowRequest, evaluate_illumination_windows,
)
from ops_sim.v5.orbit_sun_windows_document import (
    window_request_digest, load_window_request, save_window_request,
)


KINDS = ("illuminated", "occulted", "refinement", "domain", "budget-failure",
         "upstream-failure", "numerical-limit", "external")


def example_request(kind):
    if kind not in KINDS:
        raise ValueError("unknown example kind")
    base = interval_example("ambiguous" if kind in ("refinement", "budget-failure", "numerical-limit")
                            else "illuminated" if kind == "domain" else kind)
    resolution = 1/512 if kind == "refinement" else 1/256
    policy = IlluminationSearchPolicy(8, 256, 256, 2048, 131072)
    if kind == "domain":
        base = replace(base, table=replace(base.table, samples=(
            replace(base.table.samples[0], position_m=(0., 1., 0.)),
            replace(base.table.samples[-1], position_m=(0., -1., 0.)))))
    if kind == "budget-failure":
        resolution = 2**-20
        policy = replace(policy, max_integration_steps=3)
    if kind == "numerical-limit":
        h = 2**-20
        start = base.start.elapsed_seconds
        table = replace(base.table, domain_seconds=(start, start+h), samples=(
            SunPositionSample(start, (-1., 16., 0.)),
            SunPositionSample(start+h, (-1., -16., 0.))))
        base = replace(base, table=table, end=replace(base.end, elapsed_seconds=start+h),
                       coast=replace(base.coast, enclosure_policy=replace(base.coast.enclosure_policy, step_seconds=h)))
        resolution = h/4
    return IlluminationWindowRequest(base.coast, base.table, base.start, base.end,
                                     resolution, policy)


def summary(result):
    output = {f.name: _wire(getattr(result, f.name)) for f in fields(result)
              if f.name not in ("request", "trials", "windows")}
    output["request_digest"] = window_request_digest(result.request)
    output["windows"] = None if result.windows is None else [_wire(asdict(w)) for w in result.windows]
    output["trials"] = [{"index": t.index, "input_digest": t.input_digest,
                          "enclosure_policy": asdict(t.request.coast.enclosure_policy),
                          "nominal_policy": asdict(t.request.coast.solver_config),
                          **{f.name: getattr(t, f.name) for f in fields(t)
                             if f.name not in ("index", "request", "input_digest", "evidence")},
                          "evidence": None if t.evidence is None else interval_summary(t.evidence)}
                         for t in result.trials]
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=KINDS, default="illuminated")
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--write-inputs", type=Path)
    parser.add_argument("--expected-digest")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.inputs and args.write_inputs:
        parser.error("choose reconstruction or exclusive creation")
    if args.expected_digest and not args.inputs:
        parser.error("expected-digest requires inputs")
    if args.offline:
        block_network()
    request = load_window_request(args.inputs, expected_digest=args.expected_digest) if args.inputs else example_request(args.kind)
    if args.write_inputs:
        save_window_request(args.write_inputs, request)
    start = perf_counter()
    result = evaluate_illumination_windows(request)
    elapsed = perf_counter()-start
    print(json.dumps({"evidence": summary(result), "evaluation_seconds": elapsed,
                      "python_network_disabled": args.offline}, indent=2))


if __name__ == "__main__":
    main()
