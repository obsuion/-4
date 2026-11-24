# Simulation core
This directory contains source from the frozen October DIRECT90D CREATE-R2 baseline. Source and test files listed in [PUBLIC-SOURCE-SHA256SUMS.txt](PUBLIC-SOURCE-SHA256SUMS.txt) preserve their original bytes. The accepted 90-day D1 and D2 experiments were separate, later campaigns; this source snapshot does not reconstitute their complete Windows runtime. Read the repository's results and provenance notes before comparing versions.

## How to follow a request through the code

1. [Declared designs](NINETY_DAY_DESIGNS.md) explains the battery/panel choices and which physical parameters they change. [ninety_day_designs.py](ops_sim/v5/ninety_day_designs.py) authors the spacecraft; [lifecycle_contract.py](ops_sim/v5/lifecycle_contract.py) constructs the request and its deadline.
2. In [lifecycle_execution.py](ops_sim/v5/lifecycle_execution.py), the operator receives past observations and chooses its next action. [lifecycle_world.py](ops_sim/v5/lifecycle_world.py) computes the geometry, and [lifecycle_physics.py](ops_sim/v5/lifecycle_physics.py) determines whether a commanded action actually proceeds.
3. [ms_product.py](ops_sim/v5/ms_product.py) checks that the required product was acquired and completely delivered before the deadline. Completion of a pointing manoeuvre alone is insufficient.
4. [NINETY_DAY_V6.md](NINETY_DAY_V6.md) describes the original production preparation contract and why offered requests and delivered products have different counts. [KAZEOSAT_PUBLIC_SPEC.md](KAZEOSAT_PUBLIC_SPEC.md) distinguishes public spacecraft references from simplified model assumptions. These are historical model documents: some refer to private reports or runtime evidence that are not necessary for the small examples.

## Run an independent check of one radio contact
From this directory:
  
    python -B -m examples.v5_contact_execution_demo --references --output contact-reference.json

This original example runs the model and checks its output against separate rational arithmetic. Over a synthetic ten-second contact, 18 bits use six seconds of transmitter time; the other four seconds are idle. Eleven comparisons cover energy and three thermal nodes. No parallel campaign, native compilation or long scientific run is required. The output path is yours to choose.

## What's in this snapshot?
The upstream archive SHA-256 is `5ffddb9022c25e6a51917a12f9ebe25829a818fafbb6e7b5c8868ed5a849712b`. Both original file manifests agreed on all 923 entries. The 908 originals included here were matched to them individually. On systems with sha256sum, verify with `sha256sum -c PUBLIC-SOURCE-SHA256SUMS.txt` from this folder.

The snapshot includes all Python modules under ops_sim, the original Python examples, scientific model documents, test source, and the native C, Cython and build code. It omits the two machine-specific compiled extensions, their two machine-specific build records, three historical fixture files that embed local paths, and eight repository/handoff/audit files including the old README. A new README and checksum list are the only additions in this directory. The legacy requirements file retains the original Windows environment freeze; it is not a minimal dependency list for the short example. The complete historical native/Windows test suite has not been certified on this distribution: some tests intentionally require the omitted records or the original runtime.
