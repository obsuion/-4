# B65 explicit native execution

This kit contains executable build, load, prepared job, ACTUAL/FORECAST/quiet,
checkpoint, result and typed server routes. Linux execution has not been
qualified by a Windows build. Each design requires its own bound acceptance.
No script installs an OS, rents a server or promotes a short pilot to LONG.

## Linux build on an already available target

Use normal-GIL CPython **3.14.7**, Linux **x86_64**, the pinned engine runtime
requirements and development headers from that exact interpreter. GCC12..16
is a declared admission domain; the actual full version, executable hash,
linker path/version/hash, headers, flags and command are retained in the receipt.
Neither GCC nor the Linux wheel was executed on the Windows author machine.

Provide Cython3.2.4's exact cp314 manylinux x86_64 wheel, SHA-256
`90f43be4eaa6afd58ce20d970bb1657a3627c44e1760630b82aa256ba74b4acb`.
Its URL is recorded in `native-build-lock.json`, taken from the existing official
PyPI response. Unpack the wheel into a fresh task-local directory with the
standard library; the builder verifies every extracted file against the wheel.
Use a fresh external full source copy. Build output names must not exist.

```sh
PYTHONDONTWRITEBYTECODE=1 python3.14 -B -m ops_sim.v5.lifecycle_typed_platform_build \
  --compiler /usr/bin/gcc --cython /external/cython-unpacked \
  --cython-wheel /external/wheels/cython-3.2.4-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl \
  --evidence /external/build-evidence --compiler-seconds 180
python3.14 -B kit/freeze_native_source.py --source /external/engine \
  --output /external/final-source.json
python3.14 -B kit/serverctl.py --engine /external/engine doctor
python3.14 -B kit/serverctl.py --engine /external/engine typed-capability \
  --build /external/engine/ops_sim/v5/lifecycle_typed65_build_receipt.json
```

The builder itself must run within an owned finite build process. It performs
no numerical owner entry. Strict load checks ELF64/x86_64, actual CPython ABI,
source/generated/include/support bytes, ExtensionFileLoader origin, compiled
callables, capabilities and balanced monotone numerical-entry DATA. Missing
compiler, headers, dependencies or ABI returns a refusal. A `.pyd` is never
renamed into a `.so`. Finalize membership only before freezing a new engine;
never rewrite membership or retag a checkpoint in an existing store.

## Production CLI and server adapter

Use a canonical initial input compiled once for the final engine. `prepare`
does not accept an advanced checkpoint as a new input. Use the actual version-2
lifetime policy. Select `LINUX_PRODUCTION` on Linux. The finite PILOT authority
is at most86400 simulated seconds, eight primary segments, two diagnostics and
240 execution seconds per segment; existing resource guards remain binding.

```sh
python3.14 -B m8_lifetime_campaign_cli.py prepare --input /external/initial.json \
  --store /external/pilot --policy /external/policy.json \
  --backend B65_TYPED_EXECUTION_V2 \
  --build ops_sim/v5/lifecycle_typed65_build_receipt.json --execution-mode PILOT
python3.14 -B m8_lifetime_campaign_cli.py admit --store /external/pilot
python3.14 -B m8_lifetime_campaign_cli.py chain-run --store /external/pilot
python3.14 -B m8_lifetime_campaign_cli.py status --store /external/pilot
python3.14 -B m8_lifetime_campaign_cli.py stop --store /external/pilot
python3.14 -B m8_lifetime_campaign_cli.py resume --store /external/pilot
python3.14 -B m8_lifetime_campaign_cli.py export-result --store /external/pilot \
  --output /external/pilot.exports/result.zip
```

`kit/serverctl.py plan` supports the same explicit backend/build through a new
`B65_TYPED_SERVER_PLAN_V3` family. It preserves original input, exact derivation,
source/runtime/build/permission identity and refuses backend-family substitution.
`run/resume/status/stop/export-result/diagnostic` consume the exact frozen plan.
The read-only result is `B65_READ_ONLY_TYPED_LIFETIME_RESULT_V4`; native dispatch
rights remain false. B63/B64 readers and their strict format families remain.

## Genuine LONG acceptance producer

Collect real target process-protocol receipts (`serverctl qualify-protocol`),
one complete Python-reference day, an uninterrupted native day and a substantive
fresh native continuation day on the SAME engine/runtime/input domain. Preserve
the original-call restore watch and zero native-entry proof. A pending CONTACT
with partial transmitted bits is the preferred substantive stop. Missing or
failed evidence never becomes an approval flag. The producer recomputes the
existing target day/protocol gate, full canonical scientific equality, native
build/domain bindings and zero-prefix monitor:

```sh
python3.14 -B -m kit.typed_acceptance --native-store /external/native-day \
  --python-reference-store /external/reference-day \
  --legacy-day-evidence /external/genuine-day-references.json \
  --output /external/typed-acceptance
```

Only after this succeeds may a newly prepared matching LONG store reference
`/external/typed-acceptance/acceptance.json`. Different hardware, world, workload,
controller, numerical policy, source or build requires new acceptance. Windows
checkpoints do not migrate to Linux. No15-year qualification or flight validation
is implied. Campaign code owns parallel independent designs; one design's
months remain causally sequential.
