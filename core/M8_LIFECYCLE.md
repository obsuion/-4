# B52 chronological lifecycle contract

This candidate adds a separate chronological consumer for the accepted static
assembly, nominal environment, paid attitude, electrical/thermal, acquisition,
delivery and degradation owners. Its method is
`B52_CHRONOLOGICAL_NOMINAL_ACK_GATED_V1`. It does not change the B48/B51 method,
turn a short saved mission into a longer one, or certify long-horizon physics.

This document describes implemented contracts. It contains no newly measured
mission or test result. The final review evidence must identify the exact
candidate, commands, attempts, completed horizons and unresolved gates.

## Immutable authority, units and frames

`LifecycleRoot` binds the original `CommandRollingRoot`, duration, numerical
policy, recurring scenario and Sun authority. A new manifest is derived only at
the original initial state. Advanced-state continuation retains that same long
manifest, root identity, original orbit anchor and numerical grids.

Chronological action times and calendar cuts use exact relative seconds; retained
substep boundaries use canonical rational seconds. Original Cartesian orbit
authority remains in metres and metres/second, bound to its declared TT epoch
and model inertial frame. Attitude uses the accepted `BodyAttitude3D` quaternion
and named body/inertial frames. Assembly directions, mounts and tensor data keep
their accepted conventions. Earth-fixed target/station conversion and uniform
Earth rotation remain owned by the declared frame authority. No new UTC/TDB,
Earth-orientation, precession or manoeuvre model is supplied by B52.

Electrical powers are W, energy is Wh, mass is kg, inertia is kg m², thermal
temperatures are K, and angles follow the accepted owner API (geometry rad/deg
fields remain explicitly named). Saved rational sums preserve returned binary64
values exactly; this is accounting precision, not a physical error bound.

## Chronological state and ownership

`start_lifecycle(root)` creates the initial context. Each
`step_lifecycle(state)` advances one bounded physical transaction and returns
the next state, an actual event and an optional sealed calendar row. It carries
current physical state, pending action/custody, active requests, received
knowledge, issued unconfirmed intents, bounded orbit/lighting windows, report
frontiers and cumulative paid work. It does not retain an ever-growing array of
all previous actions, forecasts, orbit states or returned physical parts.

Actual and forecast paths own separate mutable contexts, providers, world
caches and work ledgers. The controller uses the explicitly known initial state
and subsequently received observations. Resource telemetry has an original-grid
cadence (default 120 s); command and first partial-action feedback create
additional packets. Default receipt latency is 40 s. A command is not treated as
confirmed merely because its forecast completed. Pending intents gate another
issued command until their actual feedback is received. Forecast catch-up is
paid and does not grant actual delivery credit.

The default scenario releases one immutable MS request every 900 s, with a
180 s acquisition window, 4 s capture, declared service at release+240 s for
120 s, and deadline at release+600 s. The input admits only occurrences with a
complete declared deadline window inside the root. Request identities derive
from the explicit namespace and monotone ordinal; no daily state reset occurs.

Expired or credited products may retire only after reported disposition and the
relevant command-feedback frontier. Active custody, partial transfers and
unacknowledged effects remain pinned. Retiring an obsolete record does not
refund any numerical, controller, construction or model work.

## Nominal orbit, light and physical execution

The orbit owner uses the accepted Cartesian J2 force and RK4 arithmetic on the
fixed 10 s grid anchored at the original trajectory time. Only a complete
original-grid state can seed subsequent full steps. A queried remainder is an
exact-key derived result and cannot become a new propagation origin. Bounded
window eviction is allowed only behind the earliest-needed received/forecast
watermark; an unsupported old query refuses instead of silently reanchoring.

`REDUCED_ASSUMED_ANNUAL_V1` declares a circular synthetic Sun: constant distance,
annual phase and fixed obliquity in the model frame. Its coefficients are
ASSUMED scenario inputs, not an ephemeris accuracy statement. Alternatively,
`BOUND_SHORT_TABLE_V1` requires the supplied accepted offline Sun table to cover
the whole root domain. A short table is never clamped or periodically repeated.
The first authored forcing-profile entry is explicitly extended over the new
nominal domain; B52 does not infer a long seasonal profile from an old short
sequence. Existing routing, thermal-node and heat-input authorities remain
visible in the bound inputs.

Lighting is evaluated at original-anchor cell midpoints and held within each
cell (default 60 s), with cuts at the lighting/profile/table boundaries. Geometry
and classifications are NOMINAL sampled values. They are not continuous eclipse
or contact certificates and do not establish event-time accuracy.

The default quiet dispatch interval is 60 s, but it is not a 60 s thermal or
protection step. `quiet_step_limit` conservatively falls back to the admitted
detailed maximum, default 2 s; source/event cuts can shorten it further. No
wide-step nonlinear thermal or threshold-safety bound is claimed. The finer
policy changes the explicitly bound detailed maximum to 1 s and contact level
to 3; it defines a different numerical experiment, not a silent optimization.

POINT/CAPTURE/CONTACT/HOLD use the construction-aware accepted leaves. Paid
POINT includes actuator demand, wire losses and physical resource evolution.
EPS charge/discharge, capacity reconciliation, protection, thermal coupling and
the existing declared ageing laws are evaluated on actual returned substeps.
The static full tensor is not a claim of unconstrained flight attitude dynamics.
Uniform cuboids, ideal regulated routing, lumped thermal nodes, declared
optics/loads and reduced forcing remain model limitations.

Contact geometry is evaluated by the actual contact owner; a declared service
interval alone cannot create receipt. Service availability/rate and transmitter
properties remain authored assumptions. Piecewise actual execution preserves
partial bits and electrical/thermal/protection refusals. Only actual completed
acquisition records and delivery receipts can satisfy the MS product owner and
receive deadline credit. Forecast temperatures, rejected trials and incomplete
transfers are not presented as actual delivery or executed extrema.

## Calendar reports, accounting and bounded retention

Default calendar rows are fixed 2,592,000 s buckets, not civil Gregorian months.
Their offset is explicit (default -128 s). Boundary credits follow the report
owner's half-open bucket convention and separately count prior-bucket/carry-in
credits. The current row and cumulative sealed totals stay in working state;
completed rows go to `months.jsonl`. A bounded row hash chain binds their order.
Reports include actual offers/credits, weighted numerator and denominator,
expirations/refused actions, energy/SOC/temperature returned extrema, energy and
heat ledgers, degradation endpoints and actual substep counts.

Summary totals, row bounds, cursor/frontiers, thermal-node sets and counting
identities have strict data-only admission. A summary is not a checkpoint.
The B51 reporting repair separately validates its original unchanged method and
saved positive report; malformed reports fail before published report mutation.

The default maximum duration is 15 Julian years (`15 * 31,557,600 s`). At the
default anchor/calendar this admits 183 fixed monthly rows. Admission counts a
finite population and orbit-grid upper bound only. It proves neither affordable
runtime nor completed coverage. All local/global model and output quotas remain
finite; reaching a quota returns or preserves an incomplete supported prefix.

The application pins source/assets, runtime, root/input SHA-256, method and grid
identity. It admits at most four jobs per root and one owned lifecycle worker
across its workspace. Native working/checkpoint bytes are capped at 64 MiB;
job output reservation is explicit (default 128 MiB, distinct from observed
bytes), with the root and workspace caps also enforced. A worker measures its
own Windows working set, records an unavailable reason when unsupported, and
checks the declared 768 MiB target before another transition. This is a measured
guard, not a process-wide memory reservation or a proof against transient peaks.

All actual scientific events are journalled. Large UI current-state publication
is gated before construction/encoding, at opportunistic wrapper boundaries
with a one-second minimum wall interval and forced critical publications. Policy
omissions are counted separately; this is not a heartbeat guarantee while an
individual kernel runs. Journal saturation, schema/sequence errors and invalid
ownership are failures, not permission to omit scientific events silently.

Monthly, first substantive pending-contact and terminal checkpoints are
protected. Only the last two replaceable WORKING checkpoint publications are
retained; an explicit retirement record records deletion and hashes. This
retention never deletes historical review artifacts or refunds paid counters.

## Direct continuation, diagnostic loupe and Stop

A native checkpoint persists current authoritative state and bounded causal
dependencies. It is pinned by exact bytes, source/runtime/root/method/grid and
clock. Data-only restore materializes that graph; it does not numerically
reconstruct the historical orbit, thermal, action or delivery prefix. Trusted
binding is not a standalone physical reachability proof for arbitrary data.

Checkpoint encoding, publication, admission and restore-validation work have a
separate cumulative application sidecar, linked to the native checkpoint hash.
Identical native bytes published twice still retain the later sidecar's spent
charges. Native model reservations and completed calls remain separate from
wrapper accounting, wall time and actual worker CPU.

MAIN resume keeps the original immutable horizon. A loupe is a separately named
normal or verbose suffix from a retained checkpoint. Its end is the first
supported committed boundary at or after the requested end; both requested and
actual end are reported. It does not interpolate or retag a shorter root to fake
equality. Carry-in credits are separately identified; the diagnostic report is
never added to MAIN totals. Verbose detail saves actual returned physical parts
and pose, not full historical state per transition. Same-environment exact
equality, when tested, compares complete scientific projections at the same
supported boundary; encoding/publication charges remain separate.

Stop writes an immutable job-owned request. Before another model transition,
the worker can save a paid-prefix checkpoint and publish `INCOMPLETE_STOP`.
The parent allows at most one second of cooperative grace inside the original
execution deadline and the existing bounded cleanup allowance. If forced Stop,
deadline, telemetry error or unexplained child exit prevents a validated paid
prefix, native work after the last checkpoint is UNKNOWN. MAIN continuation
from that interrupted job refuses pending review. An explicit diagnostic suffix
is a separate experiment and does not claim exact total spent work. A caught
error requires its validated latest failure paid-prefix authority for MAIN.
No process is controlled merely by a recorded PID, and no job auto-retries.

## Краткое руководство пользователя

1. Откройте локальное приложение с внешним каталогом проекта:
   `python -B -m examples.m8_workbench --project-directory <новый_каталог>`.
   Конкретный исходный код и Python должны совпадать с сохранёнными bindings.
2. Создайте проект, примените изменения и пересчитайте сборку. Long root создаётся
   только из текущей применённой revision и её оплаченного preview.
3. В блоке B52 выберите горизонт, численную политику, период запросов и Sun model.
   Нажмите «Зафиксировать long root». Изменение поля создаёт draft; старый root
   не переписывается. Значения 24 часа или 30 суток в списке ещё не означают,
   что такой расчёт выполнен.
4. Укажите wall budget отдельно от физических секунд и начните миссию.
   Повторная отправка того же durable intent возвращает тот же job. Новое
   намеренное действие разрешается после reconciliation; повторное открытие
   страницы само не запускает расчёт.
5. Для Stop используйте кнопку текущего owned job. Дождитесь сохранения префикса
   и завершения cleanup. Если paid suffix отмечен UNKNOWN, приложение не выдаёт
   старый checkpoint за точный MAIN restart.
6. Выберите retained checkpoint для Direct resume или отдельной лупы. MAIN
   продолжает исходный root. Лупа показывает свой фактический интервал и свои
   carry-in credits; её результат не прибавляется к основной миссии.
7. После settled cleanup экспортируйте pinned результат. ZIP содержит root/input,
   журналы, retained checkpoints/sidecars и ограниченную parent lineage с
   SHA-256 manifest. Сводка на странице сама по себе не является restart-файлом.

CLI-путь использует те же production store/runner:
`python -B -m examples.m8_lifecycle --store <внешний_каталог> <команда>`.
Команды `create`, `start`, `resume`, `diagnostic`, `report`, `export` требуют
явных immutable входов/намерений; `--help` задаёт точные аргументы. Read-only
открытие сохранённого store не запускает модель и не восстанавливает ownership
по PID. Исторический store с другим source/runtime не мигрируется молча.

## Qualification boundary

Each actual horizon, refinement, restart/Stop/UI check and source-bound test
gate must be reported with its own command/result and any failed attempts.
Input admission, successful execution, sampled returned extrema and exact
same-environment accounting are distinct evidence. None alone proves continuous
safety, eclipse/contact event-time accuracy, physical/flight calibration,
15-year affordability, full-M2 completion or full Version M completion.
Combined qualification remains UNRESOLVED.
