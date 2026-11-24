"""F4 identity, strict portable inputs and frozen legacy encodings."""

from dataclasses import fields, replace
import hashlib
import inspect
import json
import math

import pytest

from examples.v5_experiment_bundle_demo import build_demo_state
from examples.v5_j2_bundle_demo import build_j2_demo_state
from ops_sim.v5.context import SimulationInputs, with_coast_orbit, with_j2_coast_orbit
from ops_sim.v5.experiment_codec import canonical_content, check_schema_coverage, decode_content, json_text
from ops_sim.v5.ids import ModelManifestId, SourceRecordId, WorldEventId
from ops_sim.v5.orbit_binding import COAST_BINDING_VERSION, COAST_REPRESENTATION_VERSION
from ops_sim.v5.orbit_j2_binding import (
    J2CoastOrbitInputs, J2_MANIFEST_PREFIX, derive_j2_coast_manifest_id, j2_coast_binding_payload,
)
from ops_sim.v5.provenance import ProvenanceClass, ProvenanceStatus, SensitivityRange
from test_v56b1_two_body_contracts import _forge
from test_v56b2_checkpoint_binding import _coast


@pytest.fixture
def bound():
    return build_j2_demo_state().context.inputs


def identity(inputs, coast=None):
    return derive_j2_coast_manifest_id(inputs.coast_orbit if coast is None else coast,
                                     inputs.model_manifest, inputs.numerical_config, inputs.common_world)


def test_frozen_binding_and_reconstruction(bound):
    coast = bound.coast_orbit
    expected = J2_MANIFEST_PREFIX + 'c8c58093cd88e1ec8c26c9b5143de2a5af8dbb3292a7f75ce12bb7ba892acb53'
    assert identity(bound).value == expected
    payload = j2_coast_binding_payload(coast, bound.model_manifest, bound.numerical_config, bound.common_world)
    # Independently apply the published JSON/hash recipe, not the ID helper.
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == expected.removeprefix(J2_MANIFEST_PREFIX)
    assert 'manifest_id' not in payload['manifest']
    assert payload['binding_version'] == 1
    portable = coast.to_dict()
    assert portable['fields']['policy_version'] == {'kind': 'int', 'value': '1'}
    assert portable['fields']['trajectory']['fields']['gravity_model']['fields']['j2']['fields']['value'] == {
        'kind': 'float', 'value': '0x1.0000000000000p-10'}
    rebuilt = J2CoastOrbitInputs.from_json(coast.to_json())
    assert rebuilt == coast and rebuilt is not coast
    assert rebuilt.trajectory is not coast.trajectory
    assert rebuilt.to_json() == coast.to_json()
    assert with_j2_coast_orbit(bound, rebuilt) == bound
    renamed = replace(bound.model_manifest, manifest_id=ModelManifestId('previous-label'))
    assert derive_j2_coast_manifest_id(coast, renamed, bound.numerical_config, bound.common_world) == identity(bound)
    with pytest.raises(AttributeError):
        coast.policy_version = 2


@pytest.mark.parametrize('coast_enabled,expected,size', [
    (False, 'f53c3b023acdbe893f0d185edca287983dda57ec9870ab339a4a6ed4a07b2bd4', 59718),
    (True, 'c4130157c982fd334bd2217fc2faf4fd573deb0896fe1e44f17bc0a2bbb2438d', 69945),
])
def test_pre_edit_legacy_canonical_input_bytes(coast_enabled, expected, size):
    # Frozen from clean ff4e26c before any Task 06B edits, retained externally.
    inputs = build_demo_state().context.inputs
    if coast_enabled:
        inputs = with_coast_orbit(inputs, _coast())
    raw = json_text(canonical_content(inputs)).encode('utf-8')
    assert len(raw) == size and hashlib.sha256(raw).hexdigest() == expected
    assert COAST_BINDING_VERSION == COAST_REPRESENTATION_VERSION == 1
    assert len(fields(SimulationInputs)) == 8
    parameters = inspect.signature(SimulationInputs).parameters
    assert [n for n, p in parameters.items() if p.kind is p.KEYWORD_ONLY] == ['coast_orbit']


_VALID_CHANGES = [
    ('solver_config.step_seconds', 5.), ('solver_config.max_steps', 257),
    ('enclosure_policy.step_seconds', 5.), ('enclosure_policy.max_steps', 257),
    ('enclosure_policy.min_radius_m', 5900000.), ('enclosure_policy.precision_digits', 51),
    ('enclosure_policy.max_picard_iterations', 13),
    ('trajectory.gravity_model.gravitational_parameter_m3_s2.value', 4.01e14),
    ('trajectory.gravity_model.j2.value', -1/1024),
    ('trajectory.gravity_model.reference_radius_m.value', 6400001.),
    ('trajectory.gravity_model.j2.provenance.rationale', 'Changed same-ID rationale'),
    ('trajectory.gravity_model.j2.provenance.derivation', 'Additional derivation metadata'),
    ('trajectory.gravity_model.j2.provenance.source_ids', (SourceRecordId('synthetic-a'), SourceRecordId('synthetic-b'))),
    ('trajectory.gravity_model.j2.provenance.status', ProvenanceStatus.TO_VERIFY),
    ('trajectory.gravity_model.j2.provenance.sensitivity_range', SensitivityRange(-.01, .01)),
    ('trajectory.initial_state.position.components_m', (7000001., 100000., 200000.)),
    ('trajectory.initial_state.velocity.components_m_per_s', (-101., 6000., 4500.)),
]


@pytest.mark.parametrize('path,value', _VALID_CHANGES, ids=[p for p, _ in _VALID_CHANGES])
def test_same_id_changes_are_bound_and_stale_rejected(bound, path, value):
    changed = replace(_forge(bound.coast_orbit, path, value))
    assert identity(bound, changed) != identity(bound)
    with pytest.raises(ValueError, match='J2 coast binding identity mismatch'):
        replace(bound, coast_orbit=changed)
    assert J2CoastOrbitInputs.from_json(changed.to_json()) == changed


@pytest.mark.parametrize('path,value', [
    ('instant.elapsed_seconds', 129.),
    ('instant.epoch.julian_day', 2451546), ('instant.epoch.fractional_day', .25),
    ('frame.ellipsoid.name', 'Synthetic alternative shape'),
    ('frame.ellipsoid.equatorial_radius_m.value', 2.),
    ('frame.ellipsoid.flattening.value', .25),
    ('frame.rotation.initial_phase_rad.value', .5),
    ('frame.rotation.angular_velocity_rad_per_s.value', -.125),
    ('frame.rotation.epoch.julian_day', 2451546),
    ('frame.rotation.epoch.fractional_day', .25),
])
def test_complete_frame_epoch_and_original_anchor_are_bound(bound, path, value):
    coast = bound.coast_orbit
    for side in ('position', 'velocity'):
        coast = _forge(coast, 'trajectory.initial_state.' + side + '.' + path, value)
    if '.epoch.' in path:
        # Changing only one declared epoch is invalid, before any binding work.
        with pytest.raises(ValueError, match='epoch differs'):
            replace(coast)
        other = ('frame.rotation.epoch.' if path.startswith('instant.') else 'instant.epoch.') + path.rsplit('.', 1)[1]
        for side in ('position', 'velocity'):
            coast = _forge(coast, 'trajectory.initial_state.' + side + '.' + other, value)
    coast = replace(coast)
    assert identity(bound, coast) != identity(bound)
    with pytest.raises(ValueError, match='binding identity mismatch'):
        replace(bound, coast_orbit=coast)


def test_complete_metadata_order_unicode_and_bounds(bound):
    coast = bound.coast_orbit
    p = coast.trajectory.gravity_model.j2.provenance
    first = _forge(coast, 'trajectory.gravity_model.j2.provenance', replace(p,
        classification=ProvenanceClass.LITERATURE_VALUE,
        source_ids=(SourceRecordId('first'), SourceRecordId('second')),
        sensitivity_range=SensitivityRange(-.01, .01), derivation='Exact Unicode: \u00e9'))
    first = replace(first)
    for path, value in (
        ('source_ids', tuple(reversed(first.trajectory.gravity_model.j2.provenance.source_ids))),
        ('sensitivity_range.lower', -.02), ('sensitivity_range.upper', .02),
        ('derivation', 'Exact Unicode: e\u0301'),
    ):
        changed = replace(_forge(first, 'trajectory.gravity_model.j2.provenance.' + path, value))
        assert identity(bound, changed) != identity(bound, first)
        assert J2CoastOrbitInputs.from_json(changed.to_json()) == changed


@pytest.mark.parametrize('field', ['representation_version', 'binding_version', 'policy_version', 'model'])
@pytest.mark.parametrize('wrong_type', [False, True])
def test_unknown_or_forged_versions_rejected(bound, field, wrong_type):
    value = True if wrong_type else ('unknown' if field == 'model' else 2)
    with pytest.raises((ValueError, TypeError)):
        identity(bound, _forge(bound.coast_orbit, field, value))
    payload = bound.coast_orbit.to_dict()
    payload['fields'][field] = canonical_content(value)
    with pytest.raises((ValueError, TypeError)):
        J2CoastOrbitInputs.from_dict(payload)


@pytest.mark.parametrize('field', ['timestep_seconds', 'geometry_sample_seconds', 'checkpoint_interval_seconds'])
def test_numerical_binding_context(bound, field):
    changes = {'timestep_seconds': 1, 'geometry_sample_seconds': 2, 'checkpoint_interval_seconds': 46}
    n = replace(bound.numerical_config, **{field: changes[field]})
    assert derive_j2_coast_manifest_id(bound.coast_orbit, bound.model_manifest, n, bound.common_world) != identity(bound)
    with pytest.raises(ValueError, match='binding identity mismatch'):
        replace(bound, numerical_config=n)


def test_world_and_manifest_scope(bound):
    for w in (replace(bound.common_world, horizon_seconds=bound.common_world.horizon_seconds+1),
              replace(bound.common_world, event_ids=(WorldEventId('a'), WorldEventId('b'))),
              replace(bound.common_world, event_ids=(WorldEventId('b'), WorldEventId('a')))):
        assert derive_j2_coast_manifest_id(bound.coast_orbit, bound.model_manifest, bound.numerical_config, w) != identity(bound)
        with pytest.raises(ValueError, match='binding identity mismatch'):
            replace(bound, common_world=w)
    for name in ('schema_version', 'spacecraft_configuration_id', 'environment_id', 'flight_rules_id', 'controller_id'):
        old = getattr(bound.model_manifest, name)
        new = old+1 if type(old) is int else type(old)(old.value+'-other')
        m = replace(bound.model_manifest, **{name: new})
        assert derive_j2_coast_manifest_id(bound.coast_orbit, m, bound.numerical_config, bound.common_world) != identity(bound)


@pytest.mark.parametrize('number', ['0x1p+0', '1.0', 'nan', 'inf', '-inf', '0x1p+99999', '0x1.0000000000000p+0 '])
def test_noncanonical_float_encodings_rejected(bound, number):
    payload = bound.coast_orbit.to_dict()
    payload['fields']['solver_config']['fields']['step_seconds']['value'] = number
    with pytest.raises((ValueError, TypeError, OverflowError)):
        J2CoastOrbitInputs.from_dict(payload)


@pytest.mark.parametrize('kind', ['missing', 'extra', 'unknown-type', 'bool-int', 'noncanonical-int', 'signed-zero', 'surrogate', 'result'])
def test_strict_structure_and_no_derived_authority(bound, kind):
    payload = bound.coast_orbit.to_dict()
    if kind == 'missing':
        del payload['fields']['policy_version']
    elif kind == 'extra':
        payload['fields']['saved_enclosure_status'] = canonical_content('enclosed')
    elif kind == 'unknown-type':
        payload['type'] = 'os.system'
    elif kind == 'result':
        payload['type'] = 'ops_sim.v5.orbit_j2_enclosure.J2EnclosureResult'
    elif kind in ('bool-int', 'noncanonical-int'):
        payload['fields']['policy_version'] = {'kind': 'bool', 'value': True} if kind == 'bool-int' else {'kind': 'int', 'value': '01'}
    elif kind == 'signed-zero':
        # Physical owners normalize zero; wire decoding must reject that drift.
        v = payload['fields']['trajectory']['fields']['initial_state']['fields']['position']['fields']['components_m']['items']
        v[1] = {'kind': 'float', 'value': '-0x0.0p+0'}
    else:
        payload['fields']['trajectory']['fields']['gravity_model']['fields']['j2']['fields']['provenance']['fields']['rationale']['value'] = '\ud800'
    with pytest.raises((ValueError, TypeError, UnicodeError)):
        J2CoastOrbitInputs.from_dict(payload)


@pytest.mark.parametrize('text', ['{"kind":"record","kind":"record"}', '{"x":{"value":1,"value":1}}', '{"x":NaN}'])
def test_json_boundary_rejects_duplicate_keys_and_nonfinite_constants(text):
    with pytest.raises((ValueError, TypeError)):
        J2CoastOrbitInputs.from_json(text)


class HostileText(str):
    def __eq__(self, other):
        raise AssertionError('caller equality invoked')

    __hash__ = str.__hash__


class HostileFloat(float):
    def __eq__(self, other):
        raise AssertionError('caller numeric equality invoked')


@pytest.mark.parametrize('path,value', [
    ('model', HostileText('v56f-static-axis-cartesian-j2')),
    ('trajectory.gravity_model.j2.provenance.rationale', HostileText('hostile')),
    ('trajectory.gravity_model.j2.value', HostileFloat(1/1024)),
    ('enclosure_policy.step_seconds', HostileFloat(10)),
    ('trajectory.gravity_model.j2.provenance.units', '\ud800'),
    ('trajectory.gravity_model.j2.value', math.nan),
    ('enclosure_policy.max_steps', True),
    ('trajectory.gravity_model.j2.provenance.units', 'm'),
], ids=['model-text', 'metadata-text', 'gravity-float', 'policy-float', 'surrogate', 'nan', 'bool', 'wrong-units'])
def test_hostile_and_forged_owners_reject_without_text_or_numeric_hooks(bound, path, value):
    with pytest.raises((TypeError, ValueError, UnicodeError)):
        identity(bound, _forge(bound.coast_orbit, path, value))


def test_codec_remains_closed_and_preserves_plain_signed_zero(bound):
    from ops_sim.v5._experiment_types import RECORD_FIELDS
    from ops_sim.v5.orbit_j2_enclosure import J2EnclosureResult

    check_schema_coverage()
    assert J2EnclosureResult not in RECORD_FIELDS
    assert math.copysign(1, decode_content(canonical_content(-0.))) == -1
    for payload in (canonical_content(_coast()), {'kind': 'none'}):
        with pytest.raises(TypeError):
            J2CoastOrbitInputs.from_dict(payload)
    with pytest.raises(TypeError):
        with_coast_orbit(bound, bound.coast_orbit)
    with pytest.raises(TypeError):
        with_j2_coast_orbit(bound, _coast())


def test_binding_scope_is_separate_from_full_experiment_digest(bound):
    from ops_sim.v5.experiment_bundle import experiment_input_digest

    state = build_j2_demo_state()
    hardware = bound.spacecraft_configuration
    battery = hardware.eps.battery
    changed = replace(bound, spacecraft_configuration=replace(hardware, eps=replace(hardware.eps,
        battery=replace(battery, discharge_efficiency=replace(battery.discharge_efficiency, value=.45)))))
    assert identity(changed) == identity(bound)
    assert experiment_input_digest(changed, state.program) != experiment_input_digest(bound, state.program)


@pytest.mark.parametrize('owner', ['trajectory', 'solver_config', 'enclosure_policy'])
def test_nested_owner_subclasses_not_admitted(bound, owner):
    old = getattr(bound.coast_orbit, owner)
    subclass = type('UnexpectedOwner', (type(old),), {})
    supplied = subclass(**{f.name: getattr(old, f.name) for f in fields(old)})
    with pytest.raises(TypeError):
        replace(bound.coast_orbit, **{owner: supplied})
