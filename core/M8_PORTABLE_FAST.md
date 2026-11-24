# B60 portable execution candidate

The default remains REFERENCE_B59. B60_SEALED_STATIC_V1 is a separately bound
execution contract: the original physical root, policies, step partitions,
guarded arithmetic and numerical call ledgers are unchanged. It memoizes only
complete immutable policy admission and immutable authority hashes. Every hit
checks reachable frozen field identities and Fraction internals. No physical,
forecast, packet, pose, battery or thermal result is cached. Cache ownership is
process-local (at most128 entries and64MiB), rebuilt and separately counted on
restart; never native continuation authority. Actual and forecast dynamic
owners remain separate. Physical guards continue on every dynamic operation.

REFERENCE/FAST comparisons freeze the full existing scientific projection and
every selected event, with no physical exclusions. Additional B60 cache/work,
source/runtime and process-publication receipts are outside that historical
scientific projection and compared separately, never described as old calls.
FAST restart/loupe requires full canonical scientific equality, no exclusions.

Portable packages contain immutable initial input, complete source hashes,
requirements, fixed intent, finite resource contract and a fixed entrypoint.
Prepare/admit/inspect never dispatch. Native is generated only in a new local
source/runtime-bound store; copying a result bundle grants no native execution
rights. No Windows virtual environment is copied to Linux. Dependency versions
are declared in requirements.txt; no automatic installer/network is invoked.

Example: SOURCE is the verified extracted source directory; WORK is a NEW
external working directory. Keep the input, package and stores OUTSIDE SOURCE.
On Windows use the equivalent absolute backslash paths. No command installs,
uploads or dispatches during preparation/admission/result inspection.

```
python -B /absolute/SOURCE/m8_portable_job_cli.py prepare --input /absolute/WORK/initial.json --output /absolute/WORK/job.zip --key aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
python -B /absolute/SOURCE/m8_portable_job_cli.py admit /absolute/WORK/job.zip
python -B /absolute/SOURCE/m8_portable_job_cli.py run /absolute/WORK/job.zip --store /absolute/WORK/new-store
python -B /absolute/SOURCE/m8_portable_job_cli.py status --store /absolute/WORK/new-store
python -B /absolute/SOURCE/m8_portable_job_cli.py stop --store /absolute/WORK/new-store --job JOB_ID
python -B /absolute/SOURCE/m8_portable_job_cli.py resume --store /absolute/WORK/new-store --job JOB_ID --key bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
python -B /absolute/SOURCE/m8_portable_job_cli.py export-result --store /absolute/WORK/new-store --output /absolute/WORK/result.zip
python -B /absolute/SOURCE/m8_portable_job_cli.py inspect-result /absolute/WORK/result.zip
```

A transferred package is first checked against its externally supplied SHA-256
and its strict manifest. Extract its source into a new SOURCE directory, retain
the package itself outside SOURCE, admit it with that source, then start a new
store from initial input. Never copy a Windows virtual environment or import an
advanced Windows native as Linux state. See the external reproduce protocol for
this candidate's exact Windows commands and the finite Linux acceptance script.

The Linux adapter uses shell=False, start_new_session and a token/PPID/group
handshake before the fixed worker imports models. It supports cooperative fixed
descendants remaining in that session; it is NOT Windows Job/cgroup security
isolation. Escape or unavailable identity is UNKNOWN. Reopen never reacquires
ownership from a PID. Group CPU is UNAVAILABLE; worker CPU is worker-reported.
Linux current/peak RSS comes from /proc/self/status, kB converted to bytes.
No process-global limits, signals by names, or unrelated process control.

Primary references: Python3.14 subprocess.Popen (start_new_session/process_group
and preexec_fn warning), os.killpg, resource.getrusage (scope differs from
worker CPU). https://docs.python.org/3.14/library/subprocess.html
https://docs.python.org/3.14/library/os.html
https://docs.python.org/3.14/library/resource.html

30-day admission is not a year/15-year execution proof. The named eight-primary
plan refuses year and15-Julian-year horizons pending lifetime work, control,
disk and segment proofs. It reports fixed30-day partial buckets explicitly;
there are no monthly root resets or extrapolated long-campaign totals.

Combined qualification UNRESOLVED; B7 cause UNKNOWN; historical preservation
FAIL_UNEXPLAINED_NO_EXCEPTION and UI_INCOMPLETE are not closed by this candidate.


Every portable job additionally pins its exact strategy/work contract in a
bounded immutable4KiB sidecar. New dispatch and direct continuation require all
parent pins to match. Removing the store contract cannot downgrade an existing
portable job to reference, and an unpinned legacy native cannot acquire this
contract. This is persistent immutable experiment metadata, not evolved physical
state; schema5 and the accepted port native wire remain unchanged. The4KiB is
reserved inside the original128MiB job, along with the32KiB backend receipt and
16KiB static-work receipt. Raw-output portable status/ledger publication reserves
8MiB inside that same cap; streamed publication quotas remain unchanged.


Admission checks all30 exact source-pinned installed distributions before a
portable run, without installs or imports of those distributions. The preserved
requirements file is BOM UTF-16; its raw bytes are unchanged. Missing/version-
mismatched dependencies refuse admission. Read-only result inspection requires
only the standard library and does not perform science dependency admission.
Actual producer Python/platform/interpreter and all observed versions are saved;
no equality is promised across different runtimes.

Package and stored-worker admission share exact canonical metadata validation.
Boolean/integer and float/integer coercions are rejected for derived horizon,
limits and runtime requirements. Valid scientific inputs, arithmetic and
execution partitions are unchanged. Direct transferred jobs require the same
producer Python major/minor; different runtimes do not gain native rights.

Classic single-disk ZIP directory admission bounds counts and16MiB directory
bytes before ZipFile constructs member metadata. Producer packages need no
comments, SFX or ZIP64. Job/view JSON uses the existing manifest byte cap
before payload reads. Immutable package bytes are required throughout admission.
