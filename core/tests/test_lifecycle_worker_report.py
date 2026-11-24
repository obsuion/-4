"""Genuine terminal report boundary; no mission advance or timing evidence."""
from ops_sim.v5.lifecycle_application import _worker_report_summary
from ops_sim.v5.lifecycle_execution import start_lifecycle
from ops_sim.v5.lifecycle_state import guard_lifecycle
from test_lifecycle_typed_context import started, encoded
from lifetime_support import root_for
import pytest


def test_typed_worker_report_opens_and_closes_its_exact_current_job_boundary():
    state,_,_,_=started();ctx=state.backend_context
    assert ctx.job._active is None
    before=ctx.native.native_entry_counts()
    with pytest.raises(ValueError,match='transaction'):
        state.report.summary(prepared_runtime=state.physical.prepared_runtime)
    returned=_worker_report_summary(state)
    assert ctx.job._active is None
    with ctx.transaction():expected=state.report.summary(prepared_runtime=state.physical.prepared_runtime)
    assert encoded(returned)==encoded(expected)
    assert ctx.native.native_entry_counts()==before
    guard_lifecycle(state)


def test_reference_worker_report_remains_the_original_unprepared_operation():
    state=start_lifecycle(root_for(60))
    assert state.backend_context is None
    assert encoded(_worker_report_summary(state))==encoded(state.report.summary(prepared_runtime=state.physical.prepared_runtime))
