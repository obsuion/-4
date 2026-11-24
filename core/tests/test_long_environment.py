from dataclasses import replace
from functools import lru_cache
from unittest.mock import patch
from fractions import Fraction as Q
import pytest
from copy import deepcopy
from examples.m3_long_mission_demo import make_inputs
from ops_sim.v5.long_environment import (NOMINAL,CONTINUOUS,AcquiredLongEnvironment)
from ops_sim.v5.long_nominal_provider import LongNominalProvider
from ops_sim.v5.long_mission import start_long_mission
from ops_sim.v5 import orbit_sun_zonotope_local_v2 as light

@lru_cache(maxsize=1)
def genuine():
    inputs=make_inputs(mode=CONTINUOUS,duration=600)
    state=start_long_mission(inputs)
    return inputs,state.source_result

def fresh(inputs=None):
    original,source=genuine();inputs=original if inputs is None else inputs
    # One genuine module-cached source for finite tests; all full input/ancestry
    # validation remains real. This reuse is not a fresh numerical evaluation.
    with patch.object(light,'evaluate_zonotope_local_illumination_v2',return_value=source):return start_long_mission(inputs)

def test_index_exact_closed_original_supports():
    state=fresh();a=state.source_authority
    selected=a.selected(Q(168),Q(188))
    assert selected and all(s.geometry_support_convention=='CLOSED' for _,s in selected)
    for _,s in selected:
        boundary=a.source.boundaries[s.parent_boundary_id]
        while boundary.id:
            step=a.steps[boundary.parent_step_id]
            boundary=a.source.boundaries[step.parent_boundary_id]
        assert boundary.set.time==128
    schedule=a.schedule(Q(168),Q(188))
    assert schedule.cells[0].start_seconds==168 and schedule.cells[-1].end_seconds==188
    assert all(x.end_seconds==y.start_seconds for x,y in zip(schedule.cells,schedule.cells[1:]))

def test_nominal_has_no_proof_and_full_table_binding():
    inputs=make_inputs(duration=600)
    provider=LongNominalProvider(inputs.environment.trajectory)
    a=AcquiredLongEnvironment(inputs.environment,provider)
    assert a.source is None and a.schedule(Q(128),Q(188)).cells
    with pytest.raises(ValueError,match='nominal cannot'):AcquiredLongEnvironment(inputs.environment,provider,genuine()[1])
    with pytest.raises(ValueError,match='nominal world'):replace(inputs.environment,source_request=genuine()[0].environment.source_request)
    with pytest.raises(ValueError):replace(inputs.environment,end_seconds=Q(86528))

def test_index_mutation_and_foreign_source_rejected():
    inputs,source=genuine()
    damaged=deepcopy(source);object.__setattr__(damaged,'coverage_complete',False)
    with pytest.raises(ValueError):AcquiredLongEnvironment(inputs.environment,LongNominalProvider(inputs.environment.trajectory),damaged)
    a=fresh().source_authority
    damaged=deepcopy(source);object.__setattr__(damaged,'reason','edited authoritative result');a.source=damaged
    with pytest.raises(ValueError,match='mutated'):a.guard()

def test_explicit_day_continuous_static_refusal():
    with pytest.raises(ValueError):make_inputs(mode=CONTINUOUS,duration=86400)
