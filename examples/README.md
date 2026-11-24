# Calculate the first delivery

From the project root, run either of the following in a terminal:

```text
python -B examples/first_delivery.py D1
python -B examples/first_delivery.py D2
```

Uses Python 3.12 and its standard library. No package installation, native build, disk checkpoint, network or 90-day job is needed. The `-B` flag keeps the checkout free of Python bytecode files.

The example loads the unmodified constructor input for the selected design, starts the Python reference model at clock 128 seconds, and asks the engine to advance one transition at a time. It checks the index, operation, time interval, request ID, status, partial transfer and credited record(s) against the first 14 transitions in the archived D1 and D2 production journals. Both designs have the same outcome on this first request; their full missions differ. This is a prefix check on those fields, not a claim of identical complete checkpoints between execution backends.

Expected output includes:

```text
POINT    128 to 136 s: completed
CAPTURE  137 to 141 s: completed
CONTACT  from 368 s
DELIVER  b53-common-study-0: 12288 bits at clock 380.288 s (+252.288 s since release)
Matched all 14 recorded transitions on the selected event fields; stopped at clock 382 s.
```

The 12,288 bits represent a modeled multispectral product, not a real image file. Delivery can finish *within* a numerical transition: here the engine reports a delivery at 380.288 s while the transition ends at 382 s. No sleep time is simulated on the laptop. The numeric times shown above refer to the model clock.

`inputs/D1_BALANCED.json` and `inputs/D2_LIGHT.json` come from the original prepared P64 roots; their byte-level digests are listed in the example. `first-delivery.reference.json` contains the agreed event projection from the two 90-day logs. SHA-256 of those original archives:

- D1-90D-EVENTS.zip: `e604c1695ee26b7c38f5906f184947a7b573467ee266ed6aab2b938ea49b540e`
- D2-90D-EVENTS.zip: `d051381fe005d603cc535350948de3f25f440e1a40126e0b6a13087728e6aa49`
