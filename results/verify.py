"""Recalculate the published comparison from the included tables (Python 3.10+)."""
import csv
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent


def rows(name):
    with (HERE / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def check(value, message):
    if not value:
        raise ValueError(message)


def main():
    paired = rows("requests_paired.csv")
    geometry = rows("geometry_screen.csv")
    daily = rows("daily_states.csv")
    summary = json.loads((HERE / "event_summary.json").read_text(encoding="utf-8"))
    energy = json.loads((HERE / "energy_summary.json").read_text(encoding="utf-8"))
    check(len(paired) == len(geometry) == 8640, "row counts")
    for i, (a, g) in enumerate(zip(paired, geometry)):
        check(int(a["ordinal"]) == int(g["request_ordinal"]) == i, "ordinal")
        check(a["request_id"] == f"b53-common-study-{i}", "request id")
        check(int(a["release_clock"]) == int(g["release_clock_s"]) == 128 + 900*i, "cadence")

    for design in ("D1", "D2"):
        counts = Counter(r[f"{design}_category"] for r in paired)
        credited = [r for r in paired if r[f"{design}_category"] == "CREDIT"]
        expected = summary[design]
        check(dict(counts) == expected["request_groups"], f"{design} outcomes")
        check(len(credited) + expected["expiry_counter"] == len(paired), "offer balance")
        monthly = [sum(30*i < int(r["model_day"]) <= 30*(i+1) for r in credited) for i in range(3)]
        check(monthly == expected["requests_per_30d"], "30-day periods")
        for r in credited:
            check(Fraction(r[f"{design}_credit_time"]) - int(r["release_clock"]) == Fraction("252.288"), "completion")
            check(int(r[f"{design}_credit_bits"]) == 12288, "product size")
        print(f"{design}: {len(credited)}/{len(paired)} credited; 30-day counts {monthly}")

    only_d1 = [r["ordinal"] for r in paired if r["D1_category"] == "CREDIT" and r["D2_category"] != "CREDIT"]
    only_d2 = [r["ordinal"] for r in paired if r["D1_category"] != "CREDIT" and r["D2_category"] == "CREDIT"]
    check(only_d1 == ["6394"] and not only_d2, "paired credit identities")
    counts = (sum(g["first_visible_offset_s"] != "" for g in geometry),
              sum(g["first_view_start_offset_s"] != "" for g in geometry),
              sum(int(g["joint_geometry_candidate"]) for g in geometry))
    check(counts == (538, 86, 85), "geometry screen counts")
    print(f"Visibility / exposure / exposure-and-contact candidates: {counts}")

    for node in ("battery", "bus", "payload"):
        k = f"{node}_degC"
        diffs = [float(r["D2_"+k]) - float(r["D1_"+k]) for r in daily
                 if int(r["model_day"]) > 0 and r["D1_"+k] and r["D2_"+k]]
        check(len(diffs) == 70 and min(diffs) > 0, "common daily states")
        ref = energy["paired_temperature_difference_D2_minus_D1_degC"][node]["median"]
        check(abs(median(diffs) - ref) < 1e-9, "temperature delta")
        print(f"Median D2 minus D1 {node} temperature at {len(diffs)} shared day ends: {median(diffs):+.2f} C")


if __name__ == "__main__":
    main()
