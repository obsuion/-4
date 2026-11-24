"""B63 single-root INPUT admission; no numerical, execution or checkpoint grant.

User TASK.txt lines 2/32/183/203 authorize this profile-supported prepared
closure extension; the coordinator issued GO after the proposal. The frozen
experiment codec/registry and construction/harness/long documents stay intact.

Only redundant global schema scans move to transaction entry/finally-exit.
Typed leaves retain ORIGINAL _encode/_decode and constructor-normalization
round trips. Closed legacy adapters retain the original wire and caps.
All seals/counters belong to this invocation, never a global mutable cache.
"""
from dataclasses import fields
from enum import EnumMeta
import json

from . import experiment_codec as typed
from . import _experiment_types as registry
from . import metadata_codec as metadata
from . import long_mission_document as long_doc
from . import construction_document as construction_doc
from . import harness_document as mass_doc

METHOD = 'B63_INVOCATION_LOCAL_INPUT_CODEC_V1'
MAX_NODES = 2**19
MAX_DEPTH = 64
MAX_OPERATIONS = 2**24
FROZEN_ADAPTER_SOURCE_BINDINGS = (
    ('ops_sim/v5/long_mission_document.py', '75a6f7b863039fb6d840121cc85384ccd032c087e721ad3618848c931ebc3d0e'),
    ('ops_sim/v5/construction_document.py', '0ea53070e7e933fd31442eb20a17e2e72c4aa57dc93c57031a1f16c232b76450'),
    ('ops_sim/v5/harness_document.py', '34a84ff354ae58657e1b3133330b7dedeaf2a97d39b2b504bd90fe3736e9a35d'),
)
_ENCODE = typed._encode
_DECODE = typed._decode
_CHECK = typed.check_schema_coverage
_OBJECT = typed.object_fields
_ENCODE_REFERENCE=typed._encode_reference
_DECODE_REFERENCE=typed._decode_reference
_SCHEMA_REFERENCE=typed._check_schema_coverage_reference
_META_CLASS=metadata._Scope
_META_NAMES=metadata._NAMES
_META_ACTIVE=metadata._ACTIVE
_META_BINDINGS=tuple((owner,name,getattr(owner,name),getattr(getattr(owner,name),'__code__',None))
    for owner,name in [(metadata,n)for n in ('canonical_encode','canonical_decode','canonical_schema','owner_signature','scientific','metadata_scope','admitted_metadata_scope')]
    +[(_META_CLASS,n)for n in ('__init__','check','__copy__','__deepcopy__','__reduce_ex__')]
    +[(metadata.metadata_scope,'__wrapped__'),(metadata.admitted_metadata_scope,'__wrapped__')])



def _function_signature(value, retained=None):
    defaults = getattr(value, '__defaults__', None)
    keywords = getattr(value, '__kwdefaults__', None)
    code = getattr(value, '__code__', None)
    if retained is not None:
        retained.extend((value, code, defaults, keywords))
        if type(defaults) is tuple:retained.extend(defaults)
        if type(keywords) is dict:
            for key, item in keywords.items():retained.extend((key, item))
    return (id(value), id(code),
            id(defaults), tuple(id(x) for x in defaults) if type(defaults) is tuple else (),
            id(keywords), tuple((n, id(x)) for n, x in keywords.items()) if type(keywords) is dict else ())


def _owner_signature(owner, retained=None):
    if retained is None:
        from .metadata_codec import owner_signature
        compiled=owner_signature(owner)
        if compiled is not None:return compiled
    constructors = tuple((name, _function_signature(getattr(owner, name, None), retained))
                         for name in ('__init__', '__new__', '__post_init__', '__setattr__', '__getattribute__'))
    common = (id(owner), owner.__module__, owner.__name__, tuple(id(x) for x in owner.__mro__), constructors)
    if retained is not None:retained.extend((owner, owner.__mro__, *owner.__mro__))
    if isinstance(owner, EnumMeta):
        if retained is not None:
            for name, member in owner.__members__.items():retained.extend((name, member))
        return common + (tuple((n, id(m)) for n, m in owner.__members__.items()),)
    if retained is not None:
        retained.append(owner.__dataclass_fields__)
        for name, field in owner.__dataclass_fields__.items():retained.extend((name, field))
        for field in fields(owner):
            retained.extend((field, field.name, field.type, field.default, field.default_factory,
                             field.init, field.repr, field.hash, field.compare, field.kw_only,
                             field.metadata, getattr(field, '_field_type', None)))
            for key, value in field.metadata.items():retained.extend((key, value))
    field_data = tuple((id(f), f.name, id(f.type), id(f.default), id(f.default_factory),
                        id(f.init), id(f.repr), id(f.hash), id(f.compare), id(f.kw_only),
                        id(f.metadata), tuple((id(k), id(v)) for k, v in f.metadata.items()),
                        id(getattr(f, '_field_type', None))) for f in fields(owner))
    params = getattr(owner, '__dataclass_params__', None)
    if retained is not None:
        retained.append(params)
        retained.extend(getattr(params, n, None) for n in
                        ('init', 'repr', 'eq', 'order', 'unsafe_hash', 'frozen', 'match_args', 'kw_only', 'slots', 'weakref_slot'))
    return common + (id(owner.__dataclass_fields__),
                     tuple((n, id(f)) for n, f in owner.__dataclass_fields__.items()), field_data,
                     id(params), tuple((n, id(getattr(params, n, None))) for n in
                                       ('init', 'repr', 'eq', 'order', 'unsafe_hash', 'frozen', 'match_args', 'kw_only', 'slots', 'weakref_slot')))


class PreparedInputCodec:
    """Fresh exact, single-use capability owned by one loads_root call."""
    __slots__ = ('_phase', '_seal', '_owners', '_functions', '_counters', '_secondary', '_retained')

    def __init__(self):
        self._phase = 'NEW'
        self._seal = self._owners = self._functions = None
        self._counters = dict(full_schema_scans=0, full_owner_checks=0, used_owner_checks=0,
                              typed_roundtrips=0, adapter_nodes=0, typed_guard_nodes=0,
                              operational_checks=0)
        self._secondary = []
        # Strong entry references make identity seals immune to free/id reuse.
        # Never grow this collection on per-leaf/per-used checks.
        self._retained = []

    def _charge(self, key, amount=1):
        self._counters[key] += amount
        self._counters['operational_checks'] += amount
        if self._counters['operational_checks'] > MAX_OPERATIONS:
            raise ValueError('B63 bounded input codec operational work')

    def receipt(self):
        return dict(format=METHOD, phase=self._phase, counters=dict(self._counters),
                    secondary_errors=list(self._secondary),
                    scope='INPUT_ADMISSION_OPERATIONAL_CHECKS_NOT_SCIENTIFIC_WORK')

    def __enter__(self):
        if type(self) is not PreparedInputCodec or self._phase != 'NEW':
            raise ValueError('B63 exact single-use input codec required')
        self._phase = 'ENTERING'
        try:
            self._seal, self._owners, self._functions = self._full_snapshot()
        except BaseException:
            self._phase = 'FAILED_ENTRY'
            raise
        self._phase = 'ACTIVE'
        return self

    def __exit__(self, exception_type, exception, traceback):
        if self._phase != 'ACTIVE':
            raise ValueError('B63 input codec transaction state')
        try:
            seal, owners, functions = self._full_snapshot()
            if (seal != self._seal or functions != self._functions or set(owners) != set(self._owners) or
                    any(owners[o] != self._owners[o] for o in owners)):
                raise ValueError('B63 input codec schema/registry/constructor drift')
        except BaseException as secondary:
            self._phase = 'FAILED_EXIT'
            if exception is None:
                raise
            try:
                detail = str(secondary)[:1024]
            except BaseException:
                detail = '<secondary error text unavailable>'
            note = type(secondary).__name__ + ': ' + detail
            self._secondary.append(note)
            try:
                exception.add_note('B63 input codec exit check also failed: ' + note)
            except BaseException:
                # Error annotation itself must never replace the primary.
                self._secondary.append('primary exception annotation unavailable')
            return False  # Preserve ORIGINAL primary type and traceback.
        self._phase = 'FAILED_BODY' if exception is not None else 'CLOSED'
        return False

    def require_active(self):
        if type(self) is not PreparedInputCodec or self._phase != 'ACTIVE':
            raise ValueError('B63 active exact input codec capability required')

    def _full_snapshot(self):
        from . import rolling_document as rolling_doc
        from .command_estimation import CommandRollingRoot, EstimationPolicy
        from .lifecycle_contract import LifecycleRoot, LifecyclePolicy, LifecycleScenario
        from .sun_table import SunPositionSample, SunTableProvenance
        from . import spacecraft_project_v2_document as project_doc
        from .spacecraft_project_v2 import SpacecraftProjectV2
        from . import spacecraft_project_v3_document as route_doc
        from .spacecraft_project_v3 import SpacecraftProjectV3
        from .spacecraft_project import ProjectLimits
        from .design_repair import MissionRequirements
        retained = self._retained if self._phase == 'ENTERING' else None
        self._charge('full_schema_scans')
        if (typed._encode is not _ENCODE or typed._decode is not _DECODE or
                typed.check_schema_coverage is not _CHECK or typed.object_fields is not _OBJECT or
                typed._encode_reference is not _ENCODE_REFERENCE or typed._decode_reference is not _DECODE_REFERENCE or
                typed._check_schema_coverage_reference is not _SCHEMA_REFERENCE or
                typed.RECORD_FIELDS is not registry.RECORD_FIELDS or typed.ENUM_TYPES is not registry.ENUM_TYPES):
            raise ValueError('B63 original typed codec/registry binding')
        if type(typed.RECORD_FIELDS) is not dict or type(typed.ENUM_TYPES) is not tuple:
            raise ValueError('B63 exact canonical registries')
        if retained is not None:
            retained.extend((typed.RECORD_FIELDS, typed.ENUM_TYPES, typed._RECORDS, typed._ENUMS,
                             long_doc._NEW, long_doc._NEW_MAP, construction_doc.OWNERS,
                             construction_doc.MAP, mass_doc.MAP, rolling_doc.NEW, rolling_doc.MAP,
                             rolling_doc.ENUMS, long_doc._OLD_EXACT, long_doc._OLD_PREFIXES))
            for owner, names in typed.RECORD_FIELDS.items():retained.extend((owner, names, *names))
        if (metadata._Scope is not _META_CLASS or metadata._NAMES is not _META_NAMES or metadata._ACTIVE is not _META_ACTIVE or
                any(getattr(owner,name)is not fn or getattr(fn,'__code__',None)is not code for owner,name,fn,code in _META_BINDINGS)):
            raise ValueError('YEAR-V2 metadata helper origin binding drift')
        _CHECK()  # Includes every unused pinned owner at entry and exit.
        if type(typed._RECORDS) is not dict or type(typed._ENUMS) is not dict:
            raise ValueError('B63 exact canonical decoder registries')
        records = {o.__module__ + '.' + o.__name__: o for o in typed.RECORD_FIELDS}
        enums = {o.__module__ + '.' + o.__name__: o for o in typed.ENUM_TYPES}
        if (len(records) != len(typed.RECORD_FIELDS) or len(enums) != len(typed.ENUM_TYPES) or
                set(records) != set(typed._RECORDS) or set(enums) != set(typed._ENUMS) or
                any(typed._RECORDS[n] is not o for n, o in records.items()) or
                any(typed._ENUMS[n] is not o for n, o in enums.items())):
            raise ValueError('B63 canonical registry owner drift')
        declarations = (tuple(long_doc._NEW), tuple(construction_doc.OWNERS), tuple(mass_doc.MAP.values()),
                        tuple(rolling_doc.NEW), tuple(rolling_doc.ENUMS.values()),
                        (CommandRollingRoot, EstimationPolicy, LifecycleRoot, LifecyclePolicy, LifecycleScenario,
                         long_doc.SunPositionTable, SunPositionSample, SunTableProvenance,
                         long_doc.light.ZonotopeLocalIlluminationRequestV2,
                         long_doc.source_doc.ZonotopeLocalIlluminationPolicyV2,
                         long_doc.source_doc.J2ZonotopeSegmentRequest, rolling_doc.AssemblyDesign))
        for sequence, mapping in ((declarations[0], long_doc._NEW_MAP),
                                  (declarations[1], construction_doc.MAP), (declarations[2], mass_doc.MAP),
                                  (declarations[3], rolling_doc.MAP), (declarations[4], rolling_doc.ENUMS)):
            if (type(mapping) is not dict or len(sequence) != len(mapping) or
                    set(mapping) != {o.__name__ for o in sequence} or
                    any(mapping[o.__name__] is not o for o in sequence)):
                raise ValueError('B63 closed adapter registry drift')
        owners = {}
        for owner in (*records.values(), *enums.values(), *(o for seq in declarations for o in seq),
                *project_doc.OWNERS.values(),*route_doc.OWNERS.values(),SpacecraftProjectV2,SpacecraftProjectV3,ProjectLimits,MissionRequirements):
            if owner not in owners:
                self._charge('full_owner_checks')
                owners[owner] = _owner_signature(owner, retained)
        functions = tuple((n, _function_signature(getattr(typed, n), retained)) for n in
                          ('_encode', '_decode', '_integer', '_text', 'object_fields', 'check_schema_coverage',
                           '_encode_reference','_decode_reference','_check_schema_coverage_reference'))
        functions += tuple(('metadata:'+str(i),_function_signature(fn,retained))for i,(owner,name,fn,code)in enumerate(_META_BINDINGS))
        functions += tuple(('general_project:'+n,_function_signature(getattr(project_doc,n),retained))
            for n in ('specification_data','_decode','dumps_project','_dumps_project','loads_project','_loads_project'))
        functions += tuple(('route_project:'+n,_function_signature(getattr(route_doc,n),retained))
            for n in ('specification_data','_decode','dumps_project','_dumps_project','loads_project','_loads_project'))
        functions += tuple(('route_property:'+o.__name__+':'+n,_function_signature(getattr(o,n).fget,retained))
            for o,n in ((route_doc.DesignSpecificationV2,'identity'),(route_doc.DesignSpecificationV2,'declaration_identity'),
                         (SpacecraftProjectV3,'identity'),(SpacecraftProjectV3,'comparison_identity')))
        seal = (id(typed.RECORD_FIELDS), tuple((id(o), id(names), tuple(names)) for o, names in typed.RECORD_FIELDS.items()),
                id(typed.ENUM_TYPES), tuple(id(o) for o in typed.ENUM_TYPES),
                id(typed._RECORDS), tuple((n, id(o)) for n, o in typed._RECORDS.items()),
                id(typed._ENUMS), tuple((n, id(o)) for n, o in typed._ENUMS.items()),
                id(long_doc._NEW), id(long_doc._NEW_MAP), id(construction_doc.OWNERS),
                id(construction_doc.MAP), id(mass_doc.MAP),
                id(rolling_doc.NEW), id(rolling_doc.MAP), id(rolling_doc.ENUMS),
                id(long_doc._OLD_EXACT), tuple(long_doc._OLD_EXACT),
                id(long_doc._OLD_PREFIXES), tuple(long_doc._OLD_PREFIXES),
                tuple(tuple(id(o) for o in seq) for seq in declarations),
                id(project_doc.OWNERS),tuple((n,id(o))for n,o in project_doc.OWNERS.items()),
                id(project_doc.EXISTING),tuple(id(o)for o in project_doc.EXISTING))
        return seal, owners, functions

    def owner(self, owner):
        self.require_active()
        self._charge('used_owner_checks')
        if owner not in self._owners or _owner_signature(owner) != self._owners[owner]:
            raise ValueError('B63 used input owner metadata/constructor drift')

    def _node(self, depth):
        self.require_active()
        self._charge('adapter_nodes')
        if depth > MAX_DEPTH:
            raise ValueError('B63 bounded prepared input graph')

    def _guard_typed(self, value, wire=False):
        todo = [(value, 0)]
        visited = 0
        while todo:
            v, depth = todo.pop()
            self._charge('typed_guard_nodes')
            visited += 1
            if depth > MAX_DEPTH or visited > MAX_NODES:
                raise ValueError('B63 bounded typed input graph')
            if wire:
                if type(v) is not dict:
                    continue  # The original decoder retains its exact error.
                if any(type(key) is not str for key in v):
                    continue  # Do not add hostile key equality before decode.
                kind = v.get('kind')
                if type(kind) is not str:
                    continue  # Original decoder rejects before kind equality.
                if kind in ('record', 'enum') and type(v.get('type')) is str:
                    owners = typed._RECORDS if kind == 'record' else typed._ENUMS
                    owner = owners.get(v['type'])
                    if owner is not None:
                        self.owner(owner)
                    if kind == 'record' and type(v.get('fields')) is dict:
                        todo.extend((x, depth+1) for x in v['fields'].values())
                elif kind in ('tuple', 'list', 'map') and type(v.get('items')) is list:
                    if kind == 'map':
                        todo.extend((x[1], depth+1) for x in v['items'] if type(x) is list and len(x) == 2)
                    else:
                        todo.extend((x, depth+1) for x in v['items'])
            else:
                owner = type(v)
                if owner in typed.RECORD_FIELDS:
                    self.owner(owner)
                    todo.extend((getattr(v, n), depth+1) for n in typed.RECORD_FIELDS[owner])
                elif owner in typed.ENUM_TYPES:
                    self.owner(owner)
                elif owner in (tuple, list):
                    todo.extend((x, depth+1) for x in v)
                elif owner is dict:
                    todo.extend((x, depth+1) for x in v.values())

    def canonical_content(self, value):
        self.require_active()
        self._charge('typed_roundtrips')
        self._guard_typed(value)
        encoded = _ENCODE(value)
        self._guard_typed(encoded, True)
        decoded = _DECODE(encoded)
        self._guard_typed(decoded)
        if _ENCODE(decoded) != encoded:
            raise ValueError('input graph is not in its constructor-normalized representation')
        self._guard_typed(value)
        return encoded

    def decode_content(self, value):
        self.require_active()
        self._charge('typed_roundtrips')
        self._guard_typed(value, True)
        decoded = _DECODE(value)
        self._guard_typed(decoded)
        if _ENCODE(decoded) != value:
            raise ValueError('noncanonical content')
        self._guard_typed(value, True)
        return decoded

    def _wire(self, value, depth):
        self._node(depth)
        if type(value) is not dict:
            raise ValueError('typed wire input required')
        kind = value.get('kind')
        if kind in ('record', 'enum'):
            typ = value.get('type')
            if type(typ) is not str or not (typ in long_doc._OLD_EXACT or typ.startswith(long_doc._OLD_PREFIXES)):
                raise ValueError('unsafe/non-input record type: ' + str(typ))
            if kind == 'record':
                _OBJECT(value, ('kind', 'type', 'fields'))
                if type(value['fields']) is not dict:
                    raise ValueError('record fields required')
                for x in value['fields'].values():
                    self._wire(x, depth+1)
            else:
                _OBJECT(value, ('kind', 'type', 'member'))
        elif kind in ('tuple', 'list', 'map'):
            _OBJECT(value, ('kind', 'items'))
            if type(value['items']) is not list:
                raise ValueError('typed items required')
            for x in value['items']:
                if kind == 'map':
                    if type(x) is not list or len(x) != 2 or type(x[0]) is not str:
                        raise ValueError('map pair required')
                    x = x[1]
                self._wire(x, depth+1)
        elif kind in ('none', 'str', 'int', 'float', 'bool', 'fraction'):
            self.decode_content(value)
        else:
            raise ValueError('unsupported executable/wire kind')

    def long_encode(self, value, depth=0):
        self._node(depth)
        if type(value) is long_doc.SunPositionTable:
            self.owner(type(value))
            result = dict(sun_table=self.long_encode(long_doc._table_map(value), depth+1))
            self.owner(type(value))
            return result
        if type(value) is long_doc.light.ZonotopeLocalIlluminationRequestV2:
            self.owner(type(value))
            result = dict(continuous_request=json.loads(long_doc.source_doc.zonotope_local_request_to_json_v2(value)))
            self.owner(type(value))
            return result
        if type(value) in long_doc._NEW:
            self.owner(type(value))
            result = dict(input_type=type(value).__name__, fields={f.name: self.long_encode(getattr(value, f.name), depth+1) for f in fields(value)})
            self.owner(type(value))
            return result
        if type(value) is dict:
            return dict(input_map={n: self.long_encode(x, depth+1) for n, x in value.items()})
        if type(value) is tuple:
            return dict(input_tuple=[self.long_encode(x, depth+1) for x in value])
        return dict(typed=self.canonical_content(value))

    def long_admit(self, node, depth=0):
        self._node(depth)
        if type(node) is not dict:
            raise ValueError('input node object required')
        if set(node) == {'sun_table'}:
            self.long_admit(node['sun_table'], depth+1)
        elif set(node) == {'continuous_request'}:
            p = _OBJECT(node['continuous_request'], ('format', 'version', 'canonical_version', 'inputs', 'digest'))
            long_doc.source_doc._admit(p['inputs'])
        elif set(node) == {'input_map'}:
            if type(node['input_map']) is not dict or len(node['input_map']) > 64:
                raise ValueError('bounded input map')
            for x in node['input_map'].values():
                self.long_admit(x, depth+1)
        elif set(node) == {'input_type', 'fields'}:
            name = node['input_type']
            if type(name) is not str or name not in long_doc._NEW_MAP:
                raise ValueError('unknown input class')
            owner = long_doc._NEW_MAP[name]
            self.owner(owner)
            values = _OBJECT(node['fields'], tuple(f.name for f in fields(owner)))
            for x in values.values():
                self.long_admit(x, depth+1)
            self.owner(owner)
        elif set(node) == {'input_tuple'}:
            if type(node['input_tuple']) is not list or len(node['input_tuple']) > 256:
                raise ValueError('bounded input tuple required')
            for x in node['input_tuple']:
                self.long_admit(x, depth+1)
        elif set(node) == {'typed'}:
            self._wire(node['typed'], depth+1)
        else:
            raise ValueError('unsafe/unknown input node fields')

    def long_decode(self, node, depth=0):
        self._node(depth)
        if 'sun_table' in node:
            self.owner(long_doc.SunPositionTable)
            result = long_doc._read_table(self.long_decode(node['sun_table'], depth+1))
            self.owner(long_doc.SunPositionTable)
            return result
        if 'continuous_request' in node:
            self.owner(long_doc.light.ZonotopeLocalIlluminationRequestV2)
            result = long_doc.source_doc.zonotope_local_request_from_json_v2(long_doc.canonical_json(node['continuous_request']))
            self.owner(long_doc.light.ZonotopeLocalIlluminationRequestV2)
            return result
        if 'input_map' in node:
            return {n: self.long_decode(x, depth+1) for n, x in node['input_map'].items()}
        if 'input_type' in node:
            owner = long_doc._NEW_MAP[node['input_type']]
            self.owner(owner)
            result = owner(**{n: self.long_decode(v, depth+1) for n, v in node['fields'].items()})
            self.owner(owner)
            return result
        if 'input_tuple' in node:
            return tuple(self.long_decode(x, depth+1) for x in node['input_tuple'])
        return self.decode_content(node['typed'])

    def construction_encode(self, value, depth=0):
        self._node(depth)
        if type(value) in construction_doc.OWNERS:
            self.owner(type(value))
            result = dict(construction_type=type(value).__name__, fields={f.name: self.construction_encode(getattr(value, f.name), depth+1) for f in fields(value)})
            self.owner(type(value))
            return result
        if type(value) is tuple:
            return dict(construction_tuple=[self.construction_encode(x, depth+1) for x in value])
        return dict(legacy_input=self.long_encode(value, depth+1))

    def construction_admit(self, value, depth=0):
        self._node(depth)
        if type(value) is not dict:
            raise ValueError('strict construction input object')
        if set(value) == {'construction_type', 'fields'}:
            name = value['construction_type']
            if type(name) is not str or name not in construction_doc.MAP:
                raise ValueError('unsafe construction type')
            owner = construction_doc.MAP[name]
            self.owner(owner)
            data = _OBJECT(value['fields'], tuple(f.name for f in fields(owner)))
            if name == 'ConstructionConfiguration':
                for field, cap in (('ports', 64), ('lines', 64), ('receiving', 7), ('thermal_bindings', 32)):
                    sequence = _OBJECT(data[field], ('construction_tuple',))['construction_tuple']
                    if type(sequence) is not list or len(sequence) > cap:
                        raise ValueError('predecode construction cap:' + field)
                network = _OBJECT(data['thermal_network'], ('legacy_input',))['legacy_input']
                network = _OBJECT(network, ('typed',))['typed']
                network = _OBJECT(network, ('kind', 'type', 'fields'))
                if network['kind'] != 'record' or network['type'] != 'ops_sim.v5.thermal_config.ThermalNetworkConfig':
                    raise ValueError('fixed thermal network input required')
                for field, cap in (('nodes', 64), ('links', 256)):
                    sequence = _OBJECT(network['fields'][field], ('kind', 'items'))
                    if sequence['kind'] != 'tuple' or type(sequence['items']) is not list or len(sequence['items']) > cap:
                        raise ValueError('predecode thermal graph cap:' + field)
            elif name == 'LineConnection':
                waypoints = _OBJECT(data['waypoints_body_m'], ('construction_tuple',))['construction_tuple']
                if type(waypoints) is not list or len(waypoints) > 64:
                    raise ValueError('predecode route waypoint cap')
            for x in data.values():
                self.construction_admit(x, depth+1)
            self.owner(owner)
        elif set(value) == {'construction_tuple'}:
            if type(value['construction_tuple']) is not list or len(value['construction_tuple']) > 256:
                raise ValueError('bounded construction tuple')
            for x in value['construction_tuple']:
                self.construction_admit(x, depth+1)
        elif set(value) == {'legacy_input'}:
            self.long_admit(value['legacy_input'], depth+1)
        else:
            raise ValueError('unknown executable construction input')

    def construction_decode(self, value, depth=0):
        self._node(depth)
        if 'construction_type' in value:
            owner = construction_doc.MAP[value['construction_type']]
            self.owner(owner)
            result = owner(**{n: self.construction_decode(x, depth+1) for n, x in value['fields'].items()})
            self.owner(owner)
            return result
        if 'construction_tuple' in value:
            return tuple(self.construction_decode(x, depth+1) for x in value['construction_tuple'])
        return self.long_decode(value['legacy_input'], depth+1)

    def mass_encode(self, value, depth=0):
        self._node(depth)
        if type(value) in mass_doc.MAP.values():
            self.owner(type(value))
            result = dict(mass_type=type(value).__name__, fields={f.name: self.mass_encode(getattr(value, f.name), depth+1) for f in fields(value)})
            self.owner(type(value))
            return result
        if type(value) is tuple:
            return dict(mass_tuple=[self.mass_encode(x, depth+1) for x in value])
        return dict(primitive_input=self.construction_encode(value, depth+1))

    def mass_admit(self, value, depth=0):
        self._node(depth)
        if type(value) is not dict:
            raise ValueError('strict mass input object required')
        if set(value) == {'mass_type', 'fields'}:
            name = value['mass_type']
            if type(name) is not str or name not in mass_doc.MAP:
                raise ValueError('unsafe/non-input mass type')
            owner = mass_doc.MAP[name]
            self.owner(owner)
            data = _OBJECT(value['fields'], tuple(f.name for f in fields(owner)))
            if name == 'HarnessAugmentationInputs':
                values = _OBJECT(data['routes'], ('mass_tuple',))['mass_tuple']
                if type(values) is not list or len(values) != 8:
                    raise ValueError('predecode exact eight mass routes')
            elif name == 'RouteMassDistribution':
                values = _OBJECT(data['connector_points'], ('mass_tuple',))['mass_tuple']
                if type(values) is not list or len(values) > 2048:
                    raise ValueError('predecode connector cap')
            for x in data.values():
                self.mass_admit(x, depth+1)
            self.owner(owner)
        elif set(value) == {'mass_tuple'}:
            if type(value['mass_tuple']) is not list or len(value['mass_tuple']) > 2048:
                raise ValueError('bounded mass tuple')
            for x in value['mass_tuple']:
                self.mass_admit(x, depth+1)
        elif set(value) == {'primitive_input'}:
            self.construction_admit(value['primitive_input'], depth+1)
        else:
            raise ValueError('unknown executable mass fields')

    def mass_decode(self, value, depth=0):
        self._node(depth)
        if 'mass_type' in value:
            owner = mass_doc.MAP[value['mass_type']]
            self.owner(owner)
            result = owner(**{n: self.mass_decode(x, depth+1) for n, x in value['fields'].items()})
            self.owner(owner)
            return result
        if 'mass_tuple' in value:
            return tuple(self.mass_decode(x, depth+1) for x in value['mass_tuple'])
        return self.construction_decode(value['primitive_input'], depth+1)


def require_scope(value):
    if type(value) is not PreparedInputCodec:
        raise TypeError('B63 exact input codec required')
    value.require_active()
    return value
