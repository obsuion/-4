# YEAR-V5 optional isolated Cython generation

The two retained initial native builds ended with Zig reporting `clang exited
with code 5` and a missing serialized diagnostic. Their private Job cleanup
passed. The cause remains UNKNOWN: neither peak Job memory nor a limit-hit
notification was recorded. The aggregate Job limit was 1 GiB; the new generated
C is larger, and the original builder keeps the Cython compiler process and
its compilation context alive while Zig runs. This motivates a bounded change
in process overlap, rather than a claim that memory exhaustion is proved.

`lifecycle_typed_platform_build --isolate-cython --generation-seconds 180`
creates one finite generation child under the existing inherited private Job.
The parent does not import Cython in this mode. The child exits and is reaped
before the existing Zig invocation starts. Both generation and C compilation
belong to one paid build and its existing outer deadline; generation has its
own finite 1–240 second deadline. The 1 GiB Job limit and all ownership,
cleanup, mission admission, compiler flags and numerical policies remain
unchanged. The default builder path still generates C in-process.

The literal generation program is bound by the builder source hash. It uses
the same interpreter, admitted pinned wheel/tree/version, input `.pyx`, module
name, directives, output filename and normalization/token check. It inherits
the original parent's generation working directory and installs
the same socket/urllib audit-denial rule before the compiler import. Its exact
raw output bytes, input hash, runtime and package origin are checked before
the C compiler is admitted. This is not a new numerical method or scientific
entry. The generated C remains authoritative only after the ordinary treated-C,
compiler, receipt, load and zero-native-entry gates also pass.

`CYTHON-GENERATION-LAUNCH.json`, the child result, stdout/stderr and a final
envelope retain the command, source/control hashes, actual child exit, observed
wall time and failures. A timeout or bad result does not cause a retry or let
Zig run. Diagnostic streams above the declared 1 MiB per-stream cap refuse the
build and are retained. Success of this repair would show that this source
built under this process contract, not prove why an earlier compiler failed.

The third retained attempt stopped during generation: pinned Cython first
called `platform.uname()`, whose uncached local hostname operation emitted
`socket.gethostname` and was correctly blocked by the broad offline hook.
The repaired literal child primes only CPython's local `platform.uname` cache
before installing that unchanged hook. It performs no DNS lookup, connection,
scientific warmup or Cython import before the hook. Direct hostname, DNS,
connection and urllib events remain denied afterward. Synthetic cache/hook
tests cover that ordering without running a child or Cython. The original
three build charges and failures remain; any additional build needs separate
author budget authorization.
