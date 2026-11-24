# Data behind the D1/D2 comparison

Run this from the repository root with Python 3.10 or later; no external packages are needed:

    python results/verify.py

It checks the 8,640 paired request IDs, release cadence, credits and times, the geometry-screen population, and the median temperature differences. It checks the included tables, not a new 90-day mission.

| File | Contents and units |
| --- | --- |
| `requests_paired.csv` | Row per scheduled request, in order (0–8639). `release_clock` and `*_credit_time` are **absolute model seconds**, the latter encoded as a fraction; subtract release to get elapsed time. Actions count linked event records and can include partial operations. Event indices are zero-based; blank means no action or credit in that field. |
| `geometry_screen.csv` | Nominal geometry on a one-second grid, angles in degrees, offsets in seconds from the request's release. The off-nadir limit is applied at exposure start, matching v1. Blank means no qualifying sample. `joint_geometry_candidate=1` expresses geometric opportunity, not guaranteed acquisition or delivery. |
| `daily_states.csv` | Exact battery energy (Wh) and three node temperatures (°C) on recorded model-day boundaries. Blank means no exact sample existed; nothing was interpolated. |
| `event_summary.json` | Counters from the original event streams, classified outcomes and D1–D2 transitions. `requests_per_30d` is the number of **credited** requests per consecutive 30-day block. |
| `energy_summary.json` | Recorded power service mode durations, solar holding and charging time, temperature summaries, and sparse-sample statistics. A sparse minimum is not the cumulative minimum. |

## Provenance

The [findings](../docs/findings.md) describe accepted D1 and D2 simulations. These tables are derived extracts; the whole workstation, original writeable stores and native event archives are not needed for the quick verification. The request outcomes derive from the actual event streams; the geometry table is a separate calculation of what would be geometrically possible on those orbits.

| Original event export (not bundled) | Records | SHA-256 |
| --- | ---: | --- |
| D1-90D-EVENTS.zip | 209,417 | `e604c1695ee26b7c38f5906f184947a7b573467ee266ed6aab2b938ea49b540e` |
| D2-90D-EVENTS.zip | 209,215 | `d051381fe005d603cc535350948de3f25f440e1a40126e0b6a13087728e6aa49` |

If you already have both original event exports, you can regenerate the paired request table with Python 3.10+:

    python results/rebuild_requests.py D1-90D-EVENTS.zip D2-90D-EVENTS.zip output

This validates archive member hashes, event sequence and continuous model time, request identities, credit and expiry balances. It writes a new table and a detailed summary in `output/`. The optional independent geometry screen requires NumPy:

    python results/screen_geometry.py --d1 D1-90D-EVENTS.zip --d2 D2-90D-EVENTS.zip --out output/geometry.csv
