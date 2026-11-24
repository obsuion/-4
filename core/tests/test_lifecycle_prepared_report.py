"""Direct typed selected folds vs independently retained old wire projection."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as Q
import json

import pytest

from test_lifecycle_native_state import template, physical, arguments
from ops_sim.v5.construction_service import service_physical_substep
from ops_sim.v5.design_repair_study import _plain_output
from ops_sim.v5.integration_time import RationalSeconds
from ops_sim.v5.lifecycle_document import dumps_root
from ops_sim.v5.lifecycle_job_prepared import admit_job_root, prepare_job_runtime
from ops_sim.v5.lifecycle_physics import LifecycleActionOutcome
from ops_sim.v5.lifecycle_prepared_report import consume_prepared_part, consume_prepared_result
from ops_sim.v5.lifecycle_report import LifecycleReport, _part, unpack
from ops_sim.v5.long_mission import MissionPhysicalCut
from ops_sim.v5.long_mission_continuation import _scientific


def exact(value):
    return json.dumps(_scientific(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


@pytest.fixture
def job(template):
    raw = dumps_root(deepcopy(template.backend_context.root))
    root, token = admit_job_root(raw, 'd'*64)
    return prepare_job_runtime(token, root)


def row_for(physical):
    return LifecycleReport(physical.backend_context.root, physical.context,
        environment_ageing_state=physical.environment_ageing_state).state['current']


@pytest.mark.parametrize('duration', [Q(1), Q(1, 3), Q(1, 8)])
def test_complete_direct_selected_fold_exactly_matches_old_scientific_wire(physical, job, duration):
    row = deepcopy(row_for(physical)); args, kwargs = arguments(physical)
    args = (args[0], RationalSeconds.from_fraction(duration), *args[2:])
    kwargs['end_seconds'] = kwargs['start_seconds'] + duration
    part, _ = service_physical_substep(*args, **kwargs)
    expected = deepcopy(row); actual = deepcopy(row)
    _part(expected, _plain_output(_scientific(part)))
    with job.transaction(): consume_prepared_part(actual, part, job.actual)
    assert exact(actual) == exact(expected)
    assert unpack(actual['power_service']['mode_durations_seconds']['NORMAL']) == duration
    assert actual['battery_port']['last']['clock_seconds'] == {
        'numerator': part.port_state_after.clock_seconds.numerator,
        'denominator': part.port_state_after.clock_seconds.denominator}


def test_direct_fold_does_not_call_generic_scientific_encoder_or_decoder(physical, job, monkeypatch):
    row = deepcopy(row_for(physical)); args, kwargs = arguments(physical)
    part, _ = service_physical_substep(*args, **kwargs)
    import ops_sim.v5.long_mission_continuation as scientific
    import ops_sim.v5.design_repair_study as plain
    def forbidden(*args, **kwargs): raise AssertionError('generic whole-result tree used')
    monkeypatch.setattr(scientific, '_scientific', forbidden)
    monkeypatch.setattr(plain, '_plain_output', forbidden)
    with job.transaction(): consume_prepared_part(row, part, job.actual)
    assert row['physical_substeps'] == 1


def test_forecast_or_inactive_role_cannot_fold_actual_report(physical, job):
    row = deepcopy(row_for(physical)); before = exact(row)
    args, kwargs = arguments(physical); part, _ = service_physical_substep(*args, **kwargs)
    with pytest.raises(ValueError, match='requires external transaction'):
        consume_prepared_part(row, part, job.actual)
    with job.transaction():
        with pytest.raises(TypeError, match='ACTUAL'):
            consume_prepared_part(row, part, job.forecast)
    assert exact(row) == before


def test_unknown_result_is_refused_and_wrapper_attempt_is_not_refunded(physical, job):
    row = deepcopy(row_for(physical)); before = exact(row)
    with job.transaction():
        with pytest.raises(TypeError, match='selected physical result'):
            consume_prepared_part(row, object(), job.actual)
    assert exact(row) == before
    assert job.receipt()['control']['report_parts'] == 1


def test_selected_outcome_fold_orders_only_selected_parts_and_actuator_energy(physical, job):
    from ops_sim.v5.construction_contact import ConstructionContactEvaluation, ConstructionContactForcing
    row = deepcopy(row_for(physical)); args, kwargs = arguments(physical)
    part, _ = service_physical_substep(*args, **kwargs)
    # Genuine sequential selected support: current battery/thermal candidate
    # plus the first returned port history, never a duplicated 128..129 cut.
    second_kwargs = dict(kwargs, start_seconds=kwargs['start_seconds']+1,
                         end_seconds=kwargs['end_seconds']+1,
                         battery_port_state=part.port_state_after)
    second_part, _ = service_physical_substep(*args, **second_kwargs)
    t = Q(physical.context.simulation_time_seconds)
    cut = MissionPhysicalCut(t, t+1, (), 0., (0., 0., 1.), (0., 0., 1.),
                             0., 0., .1, 0., part, (1., 0., 0., 0.), None, Q(), Q())
    ignored = ConstructionContactEvaluation(0, 1, 1, True, False, (object(),), None, 0., 1)
    selected = ConstructionContactEvaluation(1, 1, 1, True, True, (second_part,), None, 0., 1)
    forcing = ConstructionContactForcing(None, (ignored, selected))
    outcome = LifecycleActionOutcome('synthetic-selected', 'HOLD_UNTIL', 'completed', None,
        int(t), int(t)+2, (), (cut,), (), None, None, physical.attitude, None, contact_forcing=(forcing,))
    expected = deepcopy(row)
    _part(expected, _plain_output(_scientific(part))); _part(expected, _plain_output(_scientific(second_part)))
    with job.transaction(): witnesses, actuator = consume_prepared_result(row, outcome, job.actual)
    assert witnesses == {}
    assert actuator == (Q(.1)/3600,)
    assert exact(row) == exact(expected)
    assert row['physical_substeps'] == 2


def test_late_fold_failure_does_not_publish_partial_report_state(physical, job):
    report = LifecycleReport(job.external_root, physical.context,
        environment_ageing_state=physical.environment_ageing_state)
    args, kwargs = arguments(physical); part, _ = service_physical_substep(*args, **kwargs)
    t = Q(physical.context.simulation_time_seconds)
    cut = MissionPhysicalCut(t, t+1, (), 0., (0., 0., 1.), (0., 0., 1.),
                             0., 0., 0., 0., part, (1., 0., 0., 0.), None, Q(), Q())
    outcome = LifecycleActionOutcome('synthetic-late-report-failure', 'HOLD_UNTIL', 'refused', 'SYNTHETIC_UNIT',
        int(t), int(t), (), (cut, replace(cut, part=object())), (), None, None, physical.attitude, None)
    before = exact(report.state)
    with job.transaction():
        with pytest.raises(TypeError, match='selected physical result'):
            report.consume(outcome, physical.context, 0, prepared_runtime=job.actual)
    assert exact(report.state) == before
    assert job.receipt()['control']['report_parts'] == 2
