# B48 command-informed rolling estimate, version 1

This is an opt-in synthetic engineering method, not calibrated state knowledge,
an interval attitude certificate, a flight result or a full Version M release.
Accepted B46 owners and all 534 accepted files remain unchanged. B47 reference
inputs/default policy retain received-only semantics, with the R1 history repair.

## Three information categories

`ReceivedObservation` retains observed/received times, packet provenance and
actual received status/resources/custody. `CommandIntent` binds an issued action
to its public model, selected paid predicted profile, expected completion time
and expected pose. `EstimatedCommandState` is an explicitly unconfirmed model
result from a fresh owned forecast invocation, never a replacement observation.
No private root checkpoint, future packet, actual evaluation/credit ledger or
actual cache bank enters `CommandPlanningView`.

`B48_PAID_COMMAND_FOLLOWING_ESTIMATE_V1` assumes command following without a
certified error bound. From the last received sample it redoes outstanding
issued actions using the accepted full effective hardware tensor, paid M3
profile, original-anchor NOMINAL_LONG orbit/lighting and EPS/thermal leaves.
Catch-up and suffix share their own physical invocation; all estimator branches
and additional compile/control reservations remain cumulative in `CommandWork`.
Counts are at most 512 invocations, 4096 command propagations and eight outstanding
propagation intents per branch, within unchanged finite old physical/output caps.

Unreceived POINT completion can support a labelled capture forecast after its
expected settled time. Pending CAPTURE/CONTACT still block duplicate requests or
transfers. Only received records/partial bits drive backlog selection. Predicted
receipt/credit never becomes known receipt/credit. Real CAPTURE/CONTACT consumes
actual geometry/pose/records/power/protection and remains the hard authority.

Each received command ack is reconciled by ID, returned status, expected versus
observed boundary time and exact same-runtime pose spelling. Contradiction drops
acknowledged intent propagation and rebases from the received sample. Exact pose
equality is a deterministic model check, not a sensor-error claim. Unsupported
time rebasing or unsettled intent yields an explicit unsupported estimate. A
bounded positive paid standby wait may await public feedback, without a forecast
certificate; its actual consumer can still refuse. It cannot authorize pointing,
capture or delivery. No zero-time retry loop is permitted.

## Binding and restart

R1 stores a full canonical committed decision digest in command lineage and
includes decisions, nested forecast work, intents, reconciliations and typed
diagnosis in the coordinator boundary. The selected first action must equal the
committed action after action-ID replacement. Mutable cumulative paid ledgers are
excluded from this scientific fingerprint, so legitimate guard/output work does
not stale the boundary. Save rejects changed history before publication or replay.

`M5_COMMAND_ESTIMATION_INPUT_V1` and its distinct causal-continuation format admit
only an exact B47 reference root, exact estimation policy and fixed method IDs.
Derived estimates/diagnoses/cached tensors/paths/callbacks are not physics input.
Fresh reconstruction statically admits physical, forecast, estimator, harness,
construction, control and canonical reencoding work before source/model work. It
replays from the original root, ordering every observation/intent/decision/action,
and requires complete canonical scientific equality. Prior work is retained;
only recomputed byte-identical publications can reuse retention.

Run `python -B -m examples.m5_command_mission_demo --output-directory <external>
--checkpoint-on-pending`. `--resume`, packet SHA and root ID require explicit
external bindings. A pending acquisition ack is a substantive boundary even
when no partial downlink is yet known. The CLI writes observed, commanded and
estimated causal history, actual assessment, paid work and output-only diagnosis.

Original C uses 40-second boundary latency. The new method does not change that
latency, FOV, material, target, deadline, station/RF declaration or protection.
Measured outcomes belong to the source-bound external evidence, including all
failures; no outcome is promised by this contract. Continuous dispatch, dynamic
FDIR/actuator plant, sensor fusion and physical/long-duration qualification remain
open. Combined qualification remains UNRESOLVED; historical B7 cause UNKNOWN.
