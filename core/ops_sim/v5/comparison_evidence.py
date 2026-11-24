"""Exact study scoring and declared engineering screens (not flight validation)."""

from fractions import Fraction
from math import isfinite


def weighted_score(requests, priorities):
    if len(requests) != len(priorities) or {r["request_id"] for r in requests} != set(priorities):
        raise ValueError("score requires every common request exactly once")
    weights = {k: Fraction(v) for k,v in priorities.items()}
    if any(v <= 0 for v in weights.values()):
        raise ValueError("positive request priorities required")
    if any(type(r["credited_products"]) is not int or r["credited_products"] not in (0,1) for r in requests):
        raise ValueError("only complete product credit is scored")
    denominator = sum(weights.values())
    numerator = sum(weights[r["request_id"]]*r["credited_products"] for r in requests)
    return {"earned_priority": str(numerator), "total_priority": str(denominator),
            "exact_score": str(numerator/denominator), "score": float(numerator/denominator)}


def qualify_pair(coarse, fine, capacity_wh, *, energy_fraction=.001, temperature_k=.1):
    """Compare matching physical boundaries; no index alignment or interpolation.

    Missing/incomplete cases or missing common final boundary fail closed.
    Different action sequences and exact completion times are reported separately.
    """
    for value in (capacity_wh,energy_fraction,temperature_k):
        if type(value) not in (float,int) or not isfinite(value) or value <= 0:
            raise ValueError("finite positive screen quantities required")
    reasons = []
    if any(r.get("status") != "completed-horizon" for r in (coarse,fine)):
        reasons.append("incomplete-run")
    def credits(r): return {x["request_id"]: x["credited_products"] for x in r.get("requests",[])}
    same_credit = bool(credits(coarse)) and credits(coarse) == credits(fine)
    if not same_credit: reasons.append("per-request-credit-difference-or-missing")
    def by_time(r):
        points = r.get("physical_samples",r.get("boundaries",[]))
        out = {Fraction(str(x["seconds"])):x for x in points}
        if len(out) != len(points): raise ValueError("duplicate physical boundary")
        return out
    a,b = by_time(coarse),by_time(fine)
    common = sorted(a.keys() & b.keys())
    if len(common) < 2 or not a or not b or max(a) != max(b):
        reasons.append("missing-common-final-boundary")
    energy,temperature = 0.,0.
    for t in common:
        if set(a[t]["temperatures_k"]) != set(b[t]["temperatures_k"]):
            reasons.append("temperature-node-mismatch")
            continue
        values = [a[t]["energy_wh"],b[t]["energy_wh"],*a[t]["temperatures_k"].values(),*b[t]["temperatures_k"].values()]
        if any(type(x) not in (int,float) or not isfinite(x) for x in values):
            reasons.append("nonfinite-resource-evidence")
            continue
        energy = max(energy,abs(a[t]["energy_wh"]-b[t]["energy_wh"]))
        temperature = max(temperature,*(abs(a[t]["temperatures_k"][n]-b[t]["temperatures_k"][n]) for n in a[t]["temperatures_k"]))
    if energy > capacity_wh*energy_fraction: reasons.append("battery-energy-screen-exceeded")
    if temperature > temperature_k: reasons.append("temperature-screen-exceeded")
    completion = lambda r: {x["request_id"]:x.get("exact_completion_seconds") for x in r.get("requests",[])}
    return dict(qualified=not reasons,reasons=sorted(set(reasons)),same_per_request_credit=same_credit,
        common_times_seconds=[str(t) for t in common],coarse_boundary_count=len(a),fine_boundary_count=len(b),
        max_energy_difference_wh=energy,energy_bound_wh=capacity_wh*energy_fraction,
        max_temperature_difference_k=temperature,temperature_bound_k=temperature_k,
        actions_equal=coarse.get("selected_actions")==fine.get("selected_actions"),
        completion_times_equal=completion(coarse)==completion(fine),
        coarse_completion=completion(coarse),fine_completion=completion(fine))
