"""Prepared input admission differential/ownership tests, not a speed claim."""
from copy import copy, deepcopy
from dataclasses import fields
from fractions import Fraction
from pathlib import Path
import traceback
import weakref

import pytest

from ops_sim.v5 import experiment_codec as legacy
from ops_sim.v5 import prepared_input_codec as prepared
from ops_sim.v5 import long_mission_document as long_doc
from ops_sim.v5 import construction_document as construction_doc
from ops_sim.v5 import harness_document as mass_doc
from ops_sim.v5.ids import ParameterId, SourceRecordId
from ops_sim.v5.orbit_config import TTEpoch


@pytest.mark.parametrize('value', [None, False, True, 0, -(2**200), 2**200,
    0.0, -0.0, 1.5, Fraction(-2, 3), '', 'e\u0301', '\u00e9', '\U0001f680',
    (1, 1.0, False), [1, (2,)], {'z': -0.0, 'a': Fraction(1, 3)},
    ParameterId('prepared-input'), TTEpoch(2451545, 0.0)])
def test_original_typed_bytes_and_constructor_roundtrips(value):
    expected = legacy.canonical_content(value)
    scope = prepared.PreparedInputCodec()
    with scope:
        assert scope.canonical_content(value) == expected
        actual = scope.decode_content(deepcopy(expected))
        assert legacy._encode(actual) == expected
    receipt = scope.receipt()
    assert receipt['phase'] == 'CLOSED'
    assert receipt['counters']['full_schema_scans'] == 2
    assert receipt['counters']['typed_roundtrips'] == 2
    assert receipt['secondary_errors'] == []


@pytest.mark.parametrize('payload', [
    {'kind': 'int', 'value': '+1'}, {'kind': 'int', 'value': '01'},
    {'kind': 'int', 'value': '-0'}, {'kind': 'int', 'value': 1},
    {'kind': 'bool', 'value': 1}, {'kind': 'none', 'value': None},
    {'kind': 'float', 'value': 'nan'}, {'kind': 'float', 'value': '1.0'},
    {'kind': 'str', 'value': '\ud800'},
    {'kind': 'fraction', 'numerator': '2', 'denominator': '4'},
    {'kind': 'fraction', 'numerator': '1', 'denominator': '-3'},
    {'kind': 'map', 'items': [['z', {'kind': 'none'}], ['a', {'kind': 'none'}]]},
    {'kind': 'map', 'items': [['a', {'kind': 'none'}], ['a', {'kind': 'none'}]]},
    {'kind': 'record', 'type': 'builtins.eval', 'fields': {}},
    {'kind': 'record', 'type': 'ops_sim.v5.ids.ParameterId', 'fields': {'value': {'kind': 'str', 'value': ' bad'}}},
    {'kind': 'enum', 'type': 'ops_sim.v5.state.OperationalMode', 'member': '__missing__'},
    {'kind': 'unknown'},
])
def test_malformed_typed_leaf_preserves_original_rejection(payload):
    with pytest.raises(Exception) as expected:
        legacy.decode_content(deepcopy(payload))
    scope = prepared.PreparedInputCodec()
    with pytest.raises(type(expected.value)):
        with scope:
            scope.decode_content(deepcopy(payload))
    assert scope.receipt()['phase'] == 'FAILED_BODY'
    assert scope.receipt()['counters']['full_schema_scans'] == 2


def test_constructor_normalization_is_not_removed():
    # Forge a pre-normalized object: the original constructor turns int 0 into
    # float 0.0. Both codecs must reject this different canonical type.
    value = object.__new__(TTEpoch)
    object.__setattr__(value, 'julian_day', 2451545)
    object.__setattr__(value, 'fractional_day', 0)
    with pytest.raises(ValueError, match='constructor-normalized'):
        legacy.canonical_content(value)
    with pytest.raises(ValueError, match='constructor-normalized'):
        with prepared.PreparedInputCodec() as scope:
            scope.canonical_content(value)


@pytest.mark.parametrize('value', [float('inf'), float('-inf'), float('nan'), '\ud800'])
def test_invalid_runtime_primitive_is_not_repaired(value):
    with pytest.raises(Exception) as expected:
        legacy.canonical_content(value)
    with pytest.raises(type(expected.value)):
        with prepared.PreparedInputCodec() as scope:
            scope.canonical_content(value)


def test_exact_text_and_integer_subclasses_remain_rejected():
    class Text(str):
        pass
    class Integer(int):
        pass
    for value in (Text('x'), Integer(1), {'key': Integer(2)}):
        with pytest.raises(TypeError):
            legacy.canonical_content(value)
        with pytest.raises(TypeError):
            with prepared.PreparedInputCodec() as scope:
                scope.canonical_content(value)
    for payload in ({'kind': 'str', 'value': Text('x')}, {'kind': 'int', 'value': Text('1')}):
        with pytest.raises(TypeError):
            legacy.decode_content(payload)
        with pytest.raises(TypeError):
            with prepared.PreparedInputCodec() as scope:
                scope.decode_content(payload)


def test_hostile_wire_kind_is_rejected_before_equality():
    class HostileText(str):
        def __eq__(self, other):
            raise AssertionError('kind equality must not run')
        __hash__ = str.__hash__
    class HostileObject:
        def __eq__(self, other):
            raise AssertionError('kind equality must not run')
    for kind in (HostileText('none'), HostileObject()):
        for payload in ({'kind': kind}, {'kind': 'tuple', 'items': [{'kind': kind}]}):
            with pytest.raises(TypeError):
                legacy.decode_content(payload)
            with pytest.raises(TypeError):
                with prepared.PreparedInputCodec() as scope:
                    scope.decode_content(payload)


def test_full_root_input_boundary_matches_frozen_strict_reader():
    from ops_sim.v5.lifecycle_document import loads_root, dumps_root
    raw = (Path(__file__).parent/'fixtures/lifetime_v7_initial.json').read_bytes()
    reference = loads_root(raw)
    scope = prepared.PreparedInputCodec()
    actual = loads_root(raw, input_codec=scope)
    assert dumps_root(actual) == dumps_root(reference) == raw
    assert scope.receipt()['phase'] == 'CLOSED'
    assert scope.receipt()['counters']['full_schema_scans'] == 2
    assert scope.receipt()['counters']['typed_roundtrips'] > 0


@pytest.mark.parametrize('name,value', [
    ('long', (ParameterId('x'), None, 1.0, Fraction(1, 3))),
    ('construction', construction_doc.ConstructionLimits()),
    ('mass', mass_doc.HarnessMassPolicy()),
])
def test_closed_frozen_adapters_preserve_full_wire(name, value):
    encode = getattr(long_doc if name == 'long' else construction_doc if name == 'construction' else mass_doc,
                     '_encode' if name == 'long' else 'encode')
    admit = getattr(long_doc if name == 'long' else construction_doc if name == 'construction' else mass_doc,
                    '_predecode' if name == 'long' else 'admit')
    decode = getattr(long_doc if name == 'long' else construction_doc if name == 'construction' else mass_doc,
                     '_decode' if name == 'long' else 'decode')
    expected = encode(value)
    admit(expected)
    with prepared.PreparedInputCodec() as scope:
        assert getattr(scope, name+'_encode')(value) == expected
        getattr(scope, name+'_admit')(deepcopy(expected))
        result = getattr(scope, name+'_decode')(deepcopy(expected))
        assert encode(result) == encode(decode(expected)) == expected


@pytest.mark.parametrize('name,payload', [
    ('long', {'input_tuple': [{'typed': {'kind': 'none'}}]*257}),
    ('construction', {'construction_tuple': []}),
    ('mass', {'mass_tuple': []}),
])
def test_closed_preallocation_caps(name, payload):
    if name == 'construction':payload['construction_tuple'] = [{}]*257
    if name == 'mass':payload['mass_tuple'] = [{}]*2049
    with pytest.raises(ValueError):
        with prepared.PreparedInputCodec() as scope:
            getattr(scope, name+'_admit')(payload)


def test_unused_schema_drift_is_rejected_on_entry(monkeypatch):
    # The payload does not use SourceRecordId at all.
    field = fields(SourceRecordId)[0]
    monkeypatch.setattr(field, 'init', False)
    scope = prepared.PreparedInputCodec()
    with pytest.raises(ValueError, match='unreviewed canonical field schema'):
        with scope:
            pytest.fail('body was reached')
    assert scope.receipt()['phase'] == 'FAILED_ENTRY'


def test_unused_metadata_drift_is_rejected_before_return(monkeypatch):
    scope = prepared.PreparedInputCodec()
    with pytest.raises(ValueError, match='schema/registry/constructor drift'):
        with scope:
            scope.canonical_content(17)
            monkeypatch.setattr(fields(SourceRecordId)[0], 'repr', False)
    assert scope.receipt()['phase'] == 'FAILED_EXIT'


def test_equal_registry_replacement_is_still_drift(monkeypatch):
    with pytest.raises(ValueError, match='schema/registry/constructor drift'):
        with prepared.PreparedInputCodec() as scope:
            scope.canonical_content(1)
            monkeypatch.setattr(legacy, '_RECORDS', dict(legacy._RECORDS))


def test_equal_field_replacement_is_caught_at_used_owner(monkeypatch):
    value = ParameterId('x')
    scope = prepared.PreparedInputCodec()
    with pytest.raises(ValueError, match='used input owner'):
        with scope:
            mapping = ParameterId.__dataclass_fields__
            monkeypatch.setitem(mapping, 'value', copy(mapping['value']))
            scope.canonical_content(value)
    assert scope.receipt()['secondary_errors']  # Exit independently saw drift.


def test_entry_seal_retains_replaced_objects_and_does_not_grow_per_leaf(monkeypatch):
    class Marker:
        pass
    field = fields(SourceRecordId)[0]
    marker = Marker()
    reference = weakref.ref(marker)
    monkeypatch.setattr(field, 'default', marker)
    scope = prepared.PreparedInputCodec()
    with pytest.raises(ValueError, match='schema/registry/constructor drift'):
        with scope:
            retained_count = len(scope._retained)
            scope.canonical_content(1)
            scope.canonical_content(2)
            assert len(scope._retained) == retained_count
            monkeypatch.setattr(field, 'default', Marker())
            del marker
            assert reference() is not None
    assert reference() is not None  # Receipt's scope still owns the old seal.


def test_primary_constructor_exception_and_traceback_survive_exit_drift(monkeypatch):
    class PrimaryError(ValueError):
        pass
    original = ParameterId.__post_init__
    def raising_constructor(self):
        original(self)
        monkeypatch.setattr(fields(SourceRecordId)[0], 'repr', False)
        raise PrimaryError('original constructor failed')
    # This explicitly injected constructor is sealed as the invocation's owner;
    # it demonstrates preserving a later original failure, not a bypass.
    monkeypatch.setattr(ParameterId, '__post_init__', raising_constructor)
    scope = prepared.PreparedInputCodec()
    payload = {'kind': 'record', 'type': 'ops_sim.v5.ids.ParameterId',
               'fields': {'value': {'kind': 'str', 'value': 'x'}}}
    with pytest.raises(PrimaryError, match='original constructor failed') as actual:
        with scope:
            scope.decode_content(payload)
    assert 'raising_constructor' in [f.name for f in traceback.extract_tb(actual.value.__traceback__)]
    assert scope.receipt()['phase'] == 'FAILED_EXIT'
    assert len(scope.receipt()['secondary_errors']) == 1
    assert any('exit check also failed' in n for n in actual.value.__notes__)


def test_exact_single_use_capability_and_no_global_leak():
    scope = prepared.PreparedInputCodec()
    with pytest.raises(ValueError, match='active exact'):
        scope.canonical_content(1)
    with scope:
        scope.canonical_content(1)
    with pytest.raises(ValueError, match='single-use'):
        with scope:
            pass
    with pytest.raises(ValueError, match='active exact'):
        scope.decode_content({'kind': 'none'})
    fresh = prepared.PreparedInputCodec()
    assert fresh.receipt()['counters']['typed_roundtrips'] == 0
    with fresh:
        assert fresh.decode_content({'kind': 'none'}) is None


def test_duck_type_and_subclass_do_not_grant_admission():
    from ops_sim.v5.lifecycle_document import loads_root
    class Derived(prepared.PreparedInputCodec):
        pass
    for fake in (True, object(), Derived()):
        with pytest.raises(TypeError, match='exact input codec'):
            loads_root(b'{}', input_codec=fake)


def test_counter_attempts_are_retained_and_receipt_is_detached(monkeypatch):
    scope = prepared.PreparedInputCodec()
    with pytest.raises(ValueError, match='operational work'):
        with scope:
            monkeypatch.setattr(prepared, 'MAX_OPERATIONS', scope.receipt()['counters']['operational_checks'])
            scope.decode_content({'kind': 'none'})
    saved = scope.receipt()
    assert saved['counters']['typed_roundtrips'] == 1
    saved['counters']['typed_roundtrips'] = 0
    assert scope.receipt()['counters']['typed_roundtrips'] == 1


def test_prepared_depth_guard_is_finite():
    node = {'typed': {'kind': 'none'}}
    for _ in range(prepared.MAX_DEPTH+1):
        node = {'input_tuple': [node]}
    with pytest.raises(ValueError, match='bounded prepared input'):
        with prepared.PreparedInputCodec() as scope:
            scope.long_admit(node)
