from dataclasses import replace
from fractions import Fraction as Q
import pytest
from examples.m3_general_earth_mission_demo import make_inputs
from examples.m3_spatial_constructor_mission_demo import make_inputs as old_inputs
from ops_sim.v5.environment_mission_3d import start_environment_mission
from ops_sim.v5.mission_general_geometry import (GeneralGeometryPolicy, admit_general_geometry_domain,
    evaluate_general_geometry)
from ops_sim.v5.mission_continuous_geometry import evaluate_continuous_geometry, ContinuousGeometryPolicy


def evaluate(state, entry=None, a=128, b=129, policy=None, **keywords):
    counts = {}
    def charge(name, value): counts[name] = counts.get(name, 0)+value
    result = evaluate_general_geometry(state.source_authority, state.inputs.environment,
        state.inputs.catalog[0] if entry is None else entry, Q(a), Q(b), policy or GeneralGeometryPolicy(),
        charge=charge, **keywords)
    return result, counts


@pytest.fixture(scope='module')
def south(): return start_environment_mission(make_inputs(case='south'))


def test_genuine_southern_whole_tube_surface_and_height(south):
    elevated, counts = evaluate(south)
    point = south.inputs.catalog[0].point
    entry = replace(south.inputs.catalog[0], point=replace(point,
        ellipsoidal_height_m=replace(point.ellipsoidal_height_m, value=0.)))
    surface, _ = evaluate(south, entry)
    assert elevated.status == surface.status == 'VISIBLE'
    assert elevated.original_anchor_seconds == surface.original_anchor_seconds == Q(128)
    assert all(c.los_quadratic_ABC[2] == (Q(0), Q(0)) for c in surface.cells)
    assert all(c.position_bounds_m == south.source_result.steps[c.source_step_id].tube.position_bounds_m for c in elevated.cells)
    assert elevated.cells[0].start_seconds == 128 and elevated.cells[-1].end_seconds == 129
    assert all(a.end_seconds == b.start_seconds for a, b in zip(elevated.cells, elevated.cells[1:]))
    assert counts['geometry_queries'] == 1 and counts['geometry_operations'] == elevated.operations


def test_negative_height_and_foreign_latitude_are_not_clear(south):
    p = south.inputs.catalog[0].point
    buried = replace(south.inputs.catalog[0], point=replace(p,
        ellipsoidal_height_m=replace(p.ellipsoidal_height_m, value=-100.)))
    result, _ = evaluate(south, buried)
    assert result.status == 'BLOCKED' and all(c.los_reason == 'GROUND_INSIDE' for c in result.cells)
    north = replace(south.inputs.catalog[0], point=replace(p,
        latitude_rad=replace(p.latitude_rad, value=-p.latitude_rad.value)))
    result, _ = evaluate(south, north)
    assert result.status == 'BLOCKED'


def test_refinement_does_not_clip_source_box(south):
    coarse, _ = evaluate(south, policy=GeneralGeometryPolicy(maximum_cell_seconds=Q(1)))
    fine, _ = evaluate(south, policy=GeneralGeometryPolicy(maximum_cell_seconds=Q(1, 4)))
    assert coarse.status == fine.status == 'VISIBLE' and len(fine.cells) > len(coarse.cells)
    assert {c.position_bounds_m for c in coarse.cells} == {c.position_bounds_m for c in fine.cells}
    assert coarse.source_signature == fine.source_signature and coarse.certificate_id != fine.certificate_id


def test_new_sphere_reduction_uses_actual_original_source():
    state = start_environment_mission(old_inputs())
    entry = state.inputs.catalog[0]
    general, _ = evaluate(state)
    old = evaluate_continuous_geometry(state.source_authority, state.inputs.environment, entry,
        Q(128), Q(129), ContinuousGeometryPolicy(), charge=lambda *args: None)
    assert general.status == old.status == 'VISIBLE'
    assert general.source_signature == old.source_signature
    for new, legacy in zip(general.cells, old.cells):
        assert new.position_bounds_m == legacy.position_bounds_m
        assert new.ground_position_bounds_m == legacy.ground_position_bounds_m
        assert new.slant_range_bounds_m == legacy.slant_range_bounds_m
        assert new.geocentric_off_nadir_cosine_bounds == legacy.off_nadir_cosine_bounds


def test_polar_genuine_source_no_longitude_division():
    state = start_environment_mission(make_inputs(case='pole'))
    result, _ = evaluate(state)
    assert result.status == 'VISIBLE' and result.point.latitude_rad.value > 1.5
    assert all(c.slant_range_bounds_m[0] > 0 for c in result.cells)


def test_query_refusal_retains_attempted_cost(south):
    costs = {}
    def charge(n, v): costs[n] = costs.get(n, 0)+v
    with pytest.raises(ValueError, match='QUOTA'):
        evaluate_general_geometry(south.source_authority, south.inputs.environment, south.inputs.catalog[0],
            Q(128), Q(129), GeneralGeometryPolicy(maximum_operations=1), charge=charge)
    assert costs['geometry_queries'] == 1 and costs['geometry_operations'] == 2


def test_source_frame_domain_and_exact_times(south):
    with pytest.raises(ValueError, match='acquired'):
        evaluate_general_geometry(south.source_result, south.inputs.environment, south.inputs.catalog[0],
            Q(128), Q(129), GeneralGeometryPolicy(), charge=lambda *args: None)
    with pytest.raises(ValueError, match='exact'):
        evaluate_general_geometry(south.source_authority, south.inputs.environment, south.inputs.catalog[0],
            128., Q(129), GeneralGeometryPolicy(), charge=lambda *args: None)
    foreign = replace(south.inputs.catalog[0], point=replace(south.inputs.catalog[0].point,
        ellipsoid=old_inputs().catalog[0].point.ellipsoid))
    with pytest.raises(ValueError, match='frame'):
        admit_general_geometry_domain(south.inputs.environment, foreign, GeneralGeometryPolicy())
    with pytest.raises(TypeError): replace(south.inputs, geometry_policy=ContinuousGeometryPolicy())
