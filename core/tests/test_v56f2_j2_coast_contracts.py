"""F2 authoritative graph, exact time grid, and bounded work contracts."""

import ast
from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
import inspect
from pathlib import Path

import pytest

from ops_sim.v5 import orbit_j2 as coast
from ops_sim.v5 import orbit_j2_gravity as gravity
from ops_sim.v5.frames import CartesianPosition, CartesianState, CartesianVelocity
from ops_sim.v5.orbit_config import FrameKind, GeometryInstant, TTEpoch
from test_v56f1_j2_gravity_contracts import (
    FRAME_PARAMETER_PATHS, PARAMETER_TEXT_PATHS, TextTrap, change_path, forge,
    make_model, make_position, poison_text,
)


def trajectory(r=(2, 0, 0), v=(0, 2, 0), *, t0=32.125, j2=0, mu=8, rg=1):
    p = make_position(r)
    p = replace(p, instant=GeometryInstant(p.instant.epoch, t0))
    state = CartesianState(p, CartesianVelocity(p.frame, p.instant, v))
    return coast.J2CartesianTrajectory(state, make_model(mu, j2, rg))


def at(t, elapsed):
    return GeometryInstant(t.initial_state.position.instant.epoch, elapsed)


def evaluate(t, elapsed, h=0.125, maximum=10000):
    # A valid independent request must not reject a forged initial graph first.
    request = GeometryInstant(make_position().instant.epoch, elapsed)
    return coast.evaluate_j2_cartesian_state(t, request, coast.J2RK4SolverConfig(h, maximum))


def test_public_api_required_fields_frozen_slots_and_no_hidden_authority():
    assert coast.__all__ == ['J2CartesianTrajectory', 'J2RK4SolverConfig', 'evaluate_j2_cartesian_state']
    assert [f.name for f in fields(coast.J2CartesianTrajectory)] == ['initial_state', 'gravity_model']
    assert [f.name for f in fields(coast.J2RK4SolverConfig)] == ['step_seconds', 'max_steps']
    for owner in (coast.J2CartesianTrajectory, coast.J2RK4SolverConfig):
        assert all(p.default is inspect.Parameter.empty for p in inspect.signature(owner).parameters.values())
    t, c = trajectory(), coast.J2RK4SolverConfig(1, 2)
    for obj, field in ((t, 'initial_state'), (c, 'step_seconds')):
        assert not hasattr(obj, '__dict__')
        with pytest.raises(FrozenInstanceError):
            setattr(obj, field, getattr(obj, field))
    assert t.__hash__ is None
    assert replace(t) == t and replace(t) is not t
    assert replace(c) == c
    with pytest.raises(ValueError):
        replace(c, step_seconds=0)
    with pytest.raises(ValueError):
        replace(t, initial_state=change_path(t.initial_state, 'position.components_m', (0, 0, 0)))


@pytest.mark.parametrize('step', [True, 0, -1, float('inf'), float('-inf'), float('nan'), '1', 2**53+1, Fraction(1, 2**2000)])
def test_invalid_step(step):
    with pytest.raises((ValueError, TypeError)):
        coast.J2RK4SolverConfig(step, 1)


@pytest.mark.parametrize('maximum', [True, 0, -1, 1.0, '1', None])
def test_invalid_exact_max_steps(maximum):
    with pytest.raises((ValueError, TypeError)):
        coast.J2RK4SolverConfig(1, maximum)


def test_numerical_normalization_and_no_b1_work_or_horizon_limit():
    assert coast.J2RK4SolverConfig(Fraction(1, 8), 2**100).step_seconds == 0.125
    t = trajectory(t0=-2**40)
    # Work count is exact and may be huge; zero duration still requires no step.
    assert evaluate(t, -2**40, 2**-1074, 1) == t.initial_state


@pytest.mark.parametrize('r,v', [((0.5, 0, 0), (0, 0, 0)), ((2, 0, 0), (100, 0, 0)),
                                ((2, 0, 0), (0, 100, 0)), ((2, 0, 0), (-1, 0, 0))])
def test_no_ellipse_pericentre_or_eo_admission(r, v):
    t = trajectory(r, v)
    assert evaluate(t, 32.125) == t.initial_state


@pytest.mark.parametrize('sign', [1, -1])
def test_canonical_prefix_exact_work_and_no_force_before_exhaustion(monkeypatch, sign):
    t = trajectory(t0=0)
    trace, forces = [], []
    original_force = coast._gravity
    def force(*args):
        forces.append(args)
        return original_force(*args)
    def step(model, anchor, r, v, delta):
        trace.append((r, v, delta))
        return r, v
    monkeypatch.setattr(coast, '_gravity', force)
    monkeypatch.setattr(coast, '_rk4_step', step)
    evaluate(t, sign*20, 10, 2)
    prefix = trace.copy()
    assert [x[2] for x in trace] == [sign*10]*2
    trace.clear()
    evaluate(t, sign*25, 10, 3)
    assert trace[:2] == prefix
    assert [x[2] for x in trace] == [sign*10, sign*10, sign*5]
    trace.clear(); forces.clear()
    with pytest.raises(ValueError, match='max_steps'):
        evaluate(t, sign*25, 10, 2)
    assert trace == forces == []
    with pytest.raises(ValueError, match='max_steps'):
        evaluate(t, sign*30, 10, 2)
    assert trace == forces == []
    evaluate(t, 0, 10, 1)
    assert trace == [] and len(forces) == 1


def test_actual_full_step_states_are_identical_across_different_endpoints(monkeypatch):
    t = trajectory()
    original, traces = coast._rk4_step, []
    def record(*args):
        result = original(*args)
        traces.append((args[2:], result))
        return result
    monkeypatch.setattr(coast, '_rk4_step', record)
    evaluate(t, 32.625, 0.25)
    prefix = traces.copy()
    traces.clear()
    evaluate(t, 32.75, 0.25)
    assert traces[:2] == prefix and [x[0][-1] for x in traces] == [0.25, 0.25, 0.125]


@pytest.mark.parametrize('sign', [1, -1])
def test_unrepresentable_exact_remainder_rejects_without_force(monkeypatch, sign):
    t = trajectory(t0=-sign*2**-53)
    def forbidden(*args):
        raise AssertionError('force ran before endpoint admission')
    monkeypatch.setattr(coast, '_gravity', forbidden)
    with pytest.raises(ValueError, match='exactly representable'):
        evaluate(t, sign, 2, 1)


def test_float_decimal_grid_has_real_extra_remainder_step(monkeypatch):
    t = trajectory(t0=0)
    with pytest.raises(ValueError, match='max_steps'):
        evaluate(t, 3*0.1, 0.1, 3)
    deltas = []
    monkeypatch.setattr(coast, '_rk4_step', lambda model, anchor, r, v, d: (deltas.append(d) or (r, v)))
    evaluate(t, 3*0.1, 0.1, 4)
    assert deltas[:3] == [0.1]*3
    assert len(deltas) == 4
    assert Fraction(deltas[3]) == Fraction(3*0.1)-3*Fraction(0.1)


def test_requested_instant_is_reconstructed_retained_and_epoch_is_reference_identity():
    t = trajectory()
    requested = at(t, 32.625)
    result = coast.evaluate_j2_cartesian_state(t, requested, coast.J2RK4SolverConfig(0.125, 4))
    assert result.position.instant == result.velocity.instant == requested
    assert result.position.instant is not requested
    assert result.position.frame == t.initial_state.position.frame
    epoch = requested.epoch
    equivalent_date = GeometryInstant(TTEpoch(epoch.julian_day, epoch.fractional_day+0.25), requested.elapsed_seconds-21600)
    with pytest.raises(ValueError, match='same TT reference'):
        coast.evaluate_j2_cartesian_state(t, equivalent_date, coast.J2RK4SolverConfig(1, 100000))


@pytest.mark.parametrize('side', ['position', 'velocity'])
@pytest.mark.parametrize('parameter_path', FRAME_PARAMETER_PATHS)
@pytest.mark.parametrize('text_path', PARAMETER_TEXT_PATHS)
@pytest.mark.parametrize('bad', [TextTrap('unequal'), '\ud800'], ids=['hostile', 'surrogate'])
def test_both_complete_frame_metadata_preflight(side, parameter_path, text_path, bad):
    t = trajectory()
    part = getattr(t.initial_state, side)
    scalar = part
    for component in parameter_path.split('.'):
        scalar = getattr(scalar, component)
    part = change_path(part, parameter_path, poison_text(scalar, text_path, bad))
    state = forge(t.initial_state, **{side: part})
    with pytest.raises((TypeError, ValueError)):
        coast.J2CartesianTrajectory(state, t.gravity_model)
    with pytest.raises((TypeError, ValueError)):
        evaluate(forge(t, initial_state=state), 32.125)


@pytest.mark.parametrize('side', ['position', 'velocity'])
@pytest.mark.parametrize('path,bad', [
    ('frame.ellipsoid.name', TextTrap('wrong')),
    ('frame.ellipsoid.name', '\ud800'),
    ('frame.kind', 'MODEL_INERTIAL'),
    ('frame.rotation.epoch.julian_day', True),
    ('instant.epoch.julian_day', True),
    ('instant.epoch.fractional_day', 1),
    ('instant.elapsed_seconds', float('inf')),
], ids=['hostile-name', 'surrogate-name', 'kind', 'rotation-epoch', 'epoch', 'fraction', 'elapsed'])
def test_forged_frame_instant_graphs(side, path, bad):
    t = trajectory()
    state = forge(t.initial_state, **{side: change_path(getattr(t.initial_state, side), path, bad)})
    with pytest.raises((TypeError, ValueError)):
        evaluate(forge(t, initial_state=state), 32.125)


@pytest.mark.parametrize('side,field', [('position', 'components_m'), ('velocity', 'components_m_per_s')])
@pytest.mark.parametrize('bad', [(float('nan'), 0, 0), (float('inf'), 0, 0), (True, 0, 0), [1, 2, 3], (1, 2)])
def test_forged_components(side, field, bad):
    t = trajectory()
    broken = change_path(t, 'initial_state.'+side+'.'+field, bad)
    with pytest.raises((TypeError, ValueError)):
        evaluate(broken, 32.125)


@pytest.mark.parametrize('name', ['gravitational_parameter_m3_s2', 'j2', 'reference_radius_m'])
@pytest.mark.parametrize('path', PARAMETER_TEXT_PATHS)
def test_gravity_metadata_rebuilt_even_at_zero_span(name, path):
    t = trajectory()
    model = forge(t.gravity_model, **{name: poison_text(getattr(t.gravity_model, name), path, TextTrap('bad'))})
    with pytest.raises(TypeError):
        evaluate(forge(t, gravity_model=model), 32.125)


@pytest.mark.parametrize('path,bad', [
    ('initial_state', None), ('initial_state.position', None), ('initial_state.velocity', None),
    ('gravity_model', None), ('gravity_model.j2.value', float('nan')),
    ('gravity_model.reference_radius_m.value', 0),
    ('gravity_model.gravitational_parameter_m3_s2.provenance.units', 'bad'),
    ('initial_state.velocity.instant.elapsed_seconds', 1),
    ('initial_state.velocity.frame.rotation.initial_phase_rad.value', 1),
], ids=['state','position','velocity','model','j2','radius','units','instant-mismatch','frame-mismatch'])
def test_invalid_nested_authority_reconstructed(path, bad):
    with pytest.raises((TypeError, ValueError)):
        evaluate(change_path(trajectory(), path, bad), 32.125)


def test_wrong_exact_types_and_subclasses():
    t, c = trajectory(), coast.J2RK4SolverConfig(1, 1)
    for owner, original in ((coast.J2CartesianTrajectory, t), (coast.J2RK4SolverConfig, c),
                            (GeometryInstant, at(t, 32.125)), (CartesianState, t.initial_state),
                            (CartesianPosition, t.initial_state.position),
                            (CartesianVelocity, t.initial_state.velocity),
                            (gravity.J2GravityModel, t.gravity_model)):
        subclass = type('Subclass', (owner,), {})
        bad = subclass(**{f.name: getattr(original, f.name) for f in fields(original) if f.init})
        args = [t, at(t, 32.125), c]
        if owner is coast.J2CartesianTrajectory: args[0] = bad
        elif owner is coast.J2RK4SolverConfig: args[2] = bad
        elif owner is GeometryInstant: args[1] = bad
        else:
            path = {CartesianState:'initial_state', CartesianPosition:'initial_state.position',
                    CartesianVelocity:'initial_state.velocity', gravity.J2GravityModel:'gravity_model'}[owner]
            args[0] = change_path(t, path, bad)
        with pytest.raises(TypeError):
            coast.evaluate_j2_cartesian_state(*args)


@pytest.mark.parametrize('field,bad', [('step_seconds', 0), ('step_seconds', float('nan')), ('max_steps', True), ('max_steps', -1)])
def test_forged_solver_rejected_even_zero_duration(field, bad):
    t = trajectory()
    with pytest.raises((TypeError, ValueError)):
        coast.evaluate_j2_cartesian_state(t, at(t, 32.125), forge(coast.J2RK4SolverConfig(1, 2), **{field: bad}))


def test_earth_fixed_and_wrong_exact_requested_types_reject():
    t = trajectory()
    frame = replace(t.initial_state.position.frame, kind=FrameKind.EARTH_FIXED)
    state = CartesianState(replace(t.initial_state.position, frame=frame), replace(t.initial_state.velocity, frame=frame))
    with pytest.raises(ValueError, match='MODEL_INERTIAL'):
        coast.J2CartesianTrajectory(state, t.gravity_model)
    for bad in (None, 0, t.initial_state.position.instant.epoch):
        with pytest.raises(TypeError):
            coast.evaluate_j2_cartesian_state(t, bad, coast.J2RK4SolverConfig(1, 1))


def test_f1_stage_force_is_exact_public_f1_force_and_cost_is_four_per_step(monkeypatch):
    t = trajectory(j2=11/32)
    original, seen = coast._gravity, []
    def check(model, position):
        assert type(model) is gravity.J2GravityModel and type(position) is CartesianPosition
        result = original(model, position)
        public = gravity.evaluate_j2_gravity(model, position)
        assert result[:3] == (public.acceleration_x_m_per_s2, public.acceleration_y_m_per_s2, public.acceleration_z_m_per_s2)
        seen.append(position)
        return result
    monkeypatch.setattr(coast, '_gravity', check)
    evaluate(t, 32.4375, 0.125, 3)
    assert len(seen) == 1+4*3
    assert all(p.instant == t.initial_state.position.instant for p in seen)


def test_ast_dependencies_no_mutable_state_or_extra_public_symbols():
    source = Path(coast.__file__).read_text(encoding='utf-8')
    tree = ast.parse(source)
    allowed = {'__future__', 'dataclasses', 'fractions', 'math', 'frames', 'orbit_config', 'orbit_j2_gravity'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(n.name in allowed for n in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module in allowed
        assert not isinstance(node, (ast.Global, ast.Nonlocal))
    definitions = {n.name for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and not n.name.startswith('_')}
    assert definitions == set(coast.__all__)
    assert [n.targets[0].id for n in tree.body if isinstance(n, ast.Assign)] == ['__all__']
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {'evaluate_two_body_state', 'open', 'lru_cache', 'cache', 'uuid4', 'eval', 'exec', '__import__'}
