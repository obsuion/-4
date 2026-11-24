# B47 common received-knowledge rolling controller candidate

Version `M5_ROLLING_MASS_CONSTRUCTION_V1`, explicit opt-in NOMINAL_LONG only.
This additive candidate reuses B46 rigid/lumped full tensor, net-torque actuator,
wire/EPS/thermal/custody leaves. Accepted fixed-program inputs/codecs are unchanged.
No flight, interval, event-time, day, optimality or general performance claim.

`RollingRoot` owns immutable declared world/design, actual original checkpoint,
release/contact schedule, initial authored estimate and finite policy/quotas.
`PlanningView` contains only released products, public model/contact declarations,
received observations/acks and issued command memory. It contains no checkpoint,
live context, scoring ledger, future requests or private packet queue. View IDs
exclude unreleased/root-private content. Body pose is a scalar-first homogeneous
Hamilton active body-to-model-inertial quaternion at its observation time.

Ideal mode explicitly observes all fields in `OBSERVED_FIELDS` at each boundary.
Delayed mode uses fixed finite boundary latency with observed/received times and
ordered immutable packets. Estimates before receipt are explicitly authored.
Delayed sensor/RF/noise realism is unqualified. Pending useful commands block
duplicates until an ack is received. Command completion clock is public; hidden
status, resource values and receipts remain in the queue until receipt.

Forecast seeds use received resources/pose/custody only; unused propulsion is
zero and legacy authority/mission fields are local empty placeholders. Observation
age is evolved by a paid HOLD. Forecast and actual state/custody are isolated.
Separate public orbital cache banks retain the original anchor/grid; forecast
branches reuse only the forecast bank. Every lookup and cache growth is charged.
Derived hardware is independently compiled/checked under paid ownership.

The bounded greedy heuristic orders held-camera and paid slew/capture/contact
suffixes and known backlog by declared priority/deadline, then takes the first
paid admissible suffix. Lower candidates are explicitly untried; no exhaustive
optimization or optimality claim. It screens declared MS sampling capability,
and uses real recovery HOLD when useful suffixes refuse. Declared
capacity is an optimistic screen, not RF or receipt truth. Every ordinary suffix
has two to four actions; only its first action is executed before replanning.
The final one-second safe standby is an explicit paid completion tail, without
inventing a zero-duration second forecast action. No-op/refusal memory and finite
decision quotas prevent an infinite zero-time loop. Budgets never imply success.

Each adaptive command binds immutable root, previous command, decision and view.
Actions are private transactions; refusals preserve actual resources/custody and
retain work. Assessment is outside the selector and uses actual records/receipts.
Input JSON has a fixed allowlist, types/fields/cardinality/depth/byte limits, no
callbacks, paths, arbitrary results or dynamic imports. Continuations bind their
external SHA/root, retain complete causal science and all ledgers, and privately
replay the root/decisions/forecast branches. Static conservative replay admission
occurs before provider/physics construction. Saved forecasts/tensors are compared
as evidence, never used as reconstruction authority. Prior and replay work remain
cumulative in the new versioned aggregate family; old per-invocation caps remain.

Forecast publication is narrowed to32MiB and128 retained cuts/action cells without
changing sampling, physics or actuator rules. Aggregate encoded output retains
the original256MiB default /512MiB ceiling. Capacity allowances are unallocated
room: their peak/events are retained, while encoder control and actual encoded
work remain cumulative. Fresh reconstruction recomputes everything, then permits
retention reuse only for a complete canonical SHA/length match to a prior bound
publication, once per hash in that replay. Unknown or mismatching content fails;
saved values never seed a predictor. Re-encoding bytes and reuse hits are counted
separately, and insufficient replay byte/control/physical quotas refuse pre-start.

The demonstration declares A priority/timing, B hot-payload radiative recovery,
and C delayed telemetry. Compact/outboard share world, requests, policy, station
availability/RF assumptions, wire material/section/slack and thermal rules. A
common authored housekeeping route passes the left battery bracket; lengths,
wire losses, added mass/COM/tensor are recomputed. This is not a collision/routing
solver, calibrated EPS allocation or hardware winner. Measured results and gates
are supplied externally with the review candidate; unexecuted cases are NOT_RUN.

Development history retains the initial6.25m fixture against6.5m hardware: those
receipts earned zero credit. The final common fixture requests exactly the
declared hardware reference spacing, with no hardware/physics/tolerance change.
This correction and the new capability screen require final-source re-execution.

# R1 causal-history clarification

Committed command lineage now stores the digest of the complete canonical
decision payload, including all tried forecasts and their nested work metadata.
The coordinator boundary includes that decision history, and guard/save reject
changed explanation, suffix, rejection, age or prediction before model work or
publication. First-action semantics are checked after generated action-ID
replacement. Cumulative paid ledger changes remain legitimate and are not used
as a scientific history fingerprint. This is an uncommitted review repair, not
acceptance or a new release. B48 command-informed estimation is explicitly
opt-in; received-only V1 defaults remain the reference method.
