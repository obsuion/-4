"""Streaming independent conservation and paired numerical readiness checks.

No simulation is executed here. Integer custody and service time checks are
exact; binary64 energy ledgers use an explicit roundoff allowance. Refinement
screens are frozen in V5_CONTINUOUS_TRADE.md before pilot comparison.
"""

import argparse
from fractions import Fraction
import json
from math import fsum
from pathlib import Path

from ops_sim.v5.continuous_trade_io import verify_evidence
from ops_sim.v5.experiment_codec import decode_content


def events(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)["event"]


def audit_evidence(path, *, initial_energy_wh, capacity_wh, charge_efficiency=.9, discharge_efficiency=.9):
    count, digest = verify_evidence(path)
    cursor = 0
    acquired, progress, delivered, requests = {}, {}, {}, set()
    totals = {}
    credits = 0
    credit_weight = Fraction(0)
    last_energy = initial_energy_wh
    residuals = {"battery_wh": 0., "bus_wh": 0., "service_wh": 0.}
    substeps = 0
    rejections = []
    for event in events(path):
        if event["kind"] == "release":
            if event["at"] != cursor:
                raise ValueError("release is not at the observed physical boundary")
            for wire in event["requests"]:
                request = decode_content(wire)
                identity = request.product.request.request_id.value
                if identity in requests or request.release_seconds != cursor:
                    raise ValueError("repeated or unpublished request")
                requests.add(identity)
            continue
        if event["kind"] == "forecast-rejection":
            if event["at"] != cursor or event["request_id"] not in requests:
                raise ValueError("forecast rejection lacks current published knowledge")
            rejections.append((event["request_id"], event["reason"]))
            continue
        if event["start"] != cursor or event["end"] <= cursor:
            raise ValueError("physical event gap or repeated interval")
        cursor = event["end"]
        samples = event["samples"]
        if Fraction(*samples[0]["time"]) != event["start"] or Fraction(*samples[-1]["time"]) != cursor:
            raise ValueError("sample endpoints disagree with physical duration")
        if samples[0]["energy_wh"] != last_energy:
            raise ValueError("battery was reset or physical continuity lost")
        a = event["accounting"]
        substeps += a["numerical_substeps"]
        for key, value in a.items():
            totals.setdefault(key, []).append(value)
        end_energy = samples[-1]["energy_wh"]
        battery_residual = end_energy - last_energy - (
            charge_efficiency * a["charge_input_wh"] - a["discharge_output_wh"] / discharge_efficiency
            - a["unavailable_energy_wh"])
        bus_residual = a["generation_wh"] + a["discharge_output_wh"] - (
            a["served_load_wh"] + a["charge_input_wh"] + a["curtailed_generation_wh"])
        service_residual = a["requested_load_wh"] - a["served_load_wh"] - a["unmet_load_wh"]
        for key, value in (("battery_wh", battery_residual), ("bus_wh", bus_residual), ("service_wh", service_residual)):
            residuals[key] = max(residuals[key], abs(value))
        # This checks algebraic conservation only, not integration accuracy.
        # Each action has <=4096 parts, so 1e-9 Wh dominates binary64 summation
        # roundoff at the <=688 Wh battery scale by several orders of magnitude.
        if max(abs(battery_residual), abs(bus_residual), abs(service_residual)) > 1e-9:
            raise ValueError("action energy conservation exceeds 1e-9 Wh roundoff allowance")
        if any(not 0 <= sample["energy_wh"] <= capacity_wh for sample in samples):
            raise ValueError("sampled energy outside declared working capacity")
        last_energy = end_energy
        if event["kind"] == "imaging" and event["approved"]:
            record = decode_content(event["record"])
            rid = record.record_id.value
            if rid in acquired or record.imaging_request_id.value not in requests:
                raise ValueError("duplicate acquisition or unpublished request")
            if int(record.stored_equivalent_bits) != event["acquired_bits"]:
                raise ValueError("record sizing disagrees with integer acquisition")
            acquired[rid] = record
        for service in event.get("services", ()):
            rid = service["record_id"]
            if rid not in acquired or rid in delivered or service["before_bits"] != progress.get(rid, 0):
                raise ValueError("service has no live acquisition or incorrect prior partial bits")
            duration = Fraction(*service["end_offset"]) - Fraction(*service["start_offset"])
            if duration * event["bitrate_bps"] != service["transmitted_bits"]:
                raise ValueError("exact bits/rate/time conservation failed")
            after = service["before_bits"] + service["transmitted_bits"]
            if after != service["after_bits"] or after > acquired[rid].stored_equivalent_bits:
                raise ValueError("service progress exceeds acquired content")
            if service["completed"] != (after == acquired[rid].stored_equivalent_bits):
                raise ValueError("completion without complete receipt")
            if not service["completed"]:
                if service["credited"]:
                    raise ValueError("partial receipt credited")
                progress[rid] = after
                continue
            instant = Fraction(event["start"]) + Fraction(*service["end_offset"])
            if instant != Fraction(*service["completion"]):
                raise ValueError("completion time differs from actual service end")
            product = decode_content(service["product"])
            plan = decode_content(service["acquisition"])
            record = acquired[rid]
            eligible = (instant <= product.delivery_deadline_seconds
                and product.acquisition_start_seconds <= record.scheduled_start_seconds
                and record.scheduled_start_seconds + record.acquisition_duration_seconds <= product.acquisition_end_seconds
                and plan.request == product.request and plan.capture_group == product.capture_group
                and plan.sizing.footprint == product.footprint
                and plan.sizing.spacing_x_m <= product.maximum_spacing_x_m
                and plan.sizing.spacing_y_m <= product.maximum_spacing_y_m
                and set(product.required_channels) <= set(plan.sizing.captured_channels))
            if bool(eligible) != service["credited"]:
                raise ValueError("causal delivery eligibility disagrees with credit")
            credits += int(eligible)
            credit_weight += Fraction(product.request.priority_weight) * int(eligible)
            delivered[rid] = after
            progress.pop(rid, None)
    summed = {key: fsum(values) for key, values in totals.items()}
    global_residual = last_energy - initial_energy_wh - (
        charge_efficiency * summed.get("charge_input_wh", 0.)
        - summed.get("discharge_output_wh", 0.) / discharge_efficiency
        - summed.get("unavailable_energy_wh", 0.))
    # Linear worst-case accumulation of the per-action allowance is deliberately
    # loose; report actual residual, never use it as a geometric/thermal tolerance.
    bound = max(1, count) * 1e-9
    if abs(global_residual) > bound:
        raise ValueError("global energy residual exceeds accumulated roundoff allowance")
    return {"status": "passed", "seconds": cursor, "event_count": count, "event_digest": digest,
        "offered_products": len(requests), "acquired": len(acquired), "completed": len(delivered),
        "credited": credits, "weighted_credit": [credit_weight.numerator, credit_weight.denominator],
        "partial_records": len(progress), "onboard_records": len(acquired) - len(delivered),
        "acquired_bits": sum(int(r.stored_equivalent_bits) for r in acquired.values()),
        "transmitted_bits": sum(delivered.values()) + sum(progress.values()),
        "numerical_substeps": substeps, "accounting": summed,
        "maximum_action_residual_wh": residuals, "global_battery_residual_wh": global_residual,
        "global_roundoff_allowance_wh": bound, "rejections": rejections}


def _comparison_rows(path):
    signatures, samples = [], {}
    for event in events(path):
        if "samples" in event:
            for sample in event["samples"]:
                samples[Fraction(*sample["time"])] = sample
            signatures.append({key: event.get(key) for key in
                ("kind", "start", "end", "start_angle", "end_angle", "approved", "reasons", "request_id")})
            for service in event.get("services", ()):
                signatures.append({key: service[key] for key in
                    ("record_id", "request_id", "before_bits", "transmitted_bits", "after_bits", "completed",
                     "credited", "credit_reasons", "completion")})
        elif event["kind"] == "forecast-rejection":
            signatures.append(event)
    return signatures, samples


def compare_refinement(coarse_path, fine_path, *, capacity_wh):
    verify_evidence(coarse_path)
    verify_evidence(fine_path)
    coarse_actions, coarse = _comparison_rows(coarse_path)
    fine_actions, fine = _comparison_rows(fine_path)
    common = sorted(coarse.keys() & fine.keys())
    if not common or max(coarse) != max(fine):
        raise ValueError("refinement needs identical complete physical duration")
    energy = max(abs(coarse[t]["energy_wh"] - fine[t]["energy_wh"]) for t in common)
    thermal = {node: max(abs(coarse[t]["temperatures_k"][node] - fine[t]["temperatures_k"][node])
        for t in common) for node in coarse[common[0]]["temperatures_k"]}
    discrete = coarse_actions == fine_actions
    first = next((i for i, (a, b) in enumerate(zip(coarse_actions, fine_actions)) if a != b), None)
    if first is None and len(coarse_actions) != len(fine_actions):
        first = min(len(coarse_actions), len(fine_actions))
    scalar = energy <= capacity_wh * .001 and max(thermal.values()) <= .1
    return {"status": "pilot-screen-passed" if scalar and discrete else "unresolved-numerical-sensitivity",
        "common_samples": len(common), "coarse_samples": len(coarse), "fine_samples": len(fine),
        "max_common_sample_energy_difference_wh": energy,
        "energy_screen_wh": capacity_wh * .001, "max_common_sample_temperature_difference_k": thermal,
        "temperature_screen_k": .1, "exact_discrete_actions_reasons_completions": discrete,
        "first_different_discrete_index": first,
        "first_difference": None if first is None else {
            "coarse": coarse_actions[first] if first < len(coarse_actions) else None,
            "fine": fine_actions[first] if first < len(fine_actions) else None},
        "scalar_screens_pass": scalar, "scope": "this pilot only; no month-wide numerical qualification"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("events")
    p.add_argument("--capacity-wh", required=True, type=float)
    p.add_argument("--initial-energy-wh", type=float)
    p.add_argument("--fine-events")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = (compare_refinement(args.events, args.fine_events, capacity_wh=args.capacity_wh)
        if args.fine_events else audit_evidence(args.events, initial_energy_wh=args.initial_energy_wh,
            capacity_wh=args.capacity_wh))
    destination = Path(args.output)
    root = Path(__file__).resolve().parents[1]
    if destination.resolve() == root or root in destination.resolve().parents:
        raise ValueError("readiness evidence must be external")
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("accounting", "rejections")}, indent=2))


if __name__ == "__main__":
    main()
