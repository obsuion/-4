# CAMPAIGN: run management and recovery

This is the public, testable run-management layer taken from the accepted **D1** completion snapshot. It shows how the application schedules independent designs, records intent before spawning a worker, reserves shared resources, handles a stop and reconciles a recorded result after a crash. The satellite operator and scientific models live in CORE, not here. This package is not a full copy of the D2 runner or a way to resume the private Windows stores.

Read these files in order:

| Question | Source |
|---|---|
| How does the scheduler keep at most the allowed number of designs running? | [scheduler.py](kaze_study/scheduler.py) |
| What gets committed before launch, after a stop, and after a recovered receipt? | [state.py](kaze_study/state.py), [settlement.py](kaze_study/settlement.py) |
| How are designs queued and how are CPU, RAM and disk reserved? | [project_queue.py](kaze_study/project_queue.py), [resources.py](kaze_study/resources.py) |
| How does the runner distinguish a valid reply from truncated output or an ambiguous failure? | [engine_adapter.py](kaze_study/engine_adapter.py), [process.py](kaze_study/process.py) |
| How is a mission credit distinguished from an inferred acquisition or delivery count? | [ninety_metrics.py](kaze_study/ninety_metrics.py) |

## Run a crash/recovery check

From this directory, using Python 3.12, no third-party packages:

```text
python -B -m unittest discover -s tests -p "test_*.py"
```

The suite runs 26 original test methods plus one public-packaging check. For example, the state suite records a dispatch intent, deliberately withholds the receipt, and checks that restarting cannot silently dispatch the job a second time. All dispatch evidence in these tests is synthetic and all state is temporary; the measured D1/D2 outcomes in the repository came from separate, accepted science runs.

## Snapshot and release boundary

The D1 completion archive is pinned by its SHA-256 in [source-map.json](source-map.json). Its source manifest contained 519 entries across the private operator environment, tests and tools. The public selection here contains 30 of those tracked entries. Twenty-nine are exact byte copies. In `projects.py`, a hardcoded workstation fixture location was replaced by a path relative to this package; that legacy compiler fixture is deliberately absent. The additional `ninety_owned_aux.py` packaging adapter supports only ordinary fixture accounting and **refuses** the original private DIRECT90D administrative mode. Its test and hash are identified separately. No original science or mission output is rewritten.

Production orchestration also requires version-specific add-ons, a registered compiler, Windows native owners, and live stores with their original grants. Those are not part of this slice. The supported execution path here is the test command above.
