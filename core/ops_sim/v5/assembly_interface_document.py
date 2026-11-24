"""Strict version-1 static interfaces bound to an exact M1-B assembly document."""

import hashlib
import hmac
from pathlib import Path

from .assembly import MassCoverage
from .assembly_document import _array, _number, _vector, _vector_json
from .assembly_interfaces import (
    AssemblyInterfaces, ElectricalPort, HarnessMassDeclaration, LineConnection,
    OperatingPoint, ThermalBinding, WireProperties, _digest, validate_binding,
)
from .experiment_codec import CANONICAL_VERSION, canonical_content, decode_content, json_text, object_fields, parse_json


INTERFACE_VERSION = 1
INTERFACE_FORMAT = 'M1_ASSEMBLY_INTERFACES'
_DOMAIN = b'M1-ASSEMBLY-INTERFACES\0v1\0'
_UNITS = {'length': 'm', 'area': 'm^2', 'resistivity': 'ohm*m', 'density': 'kg/m^3',
          'resistance': 'ohm', 'mass': 'kg', 'current': 'A', 'voltage': 'V', 'power': 'W'}
_WIRE_FIELDS = ('cross_section_m2', 'resistivity_ohm_m', 'density_kg_m3',
                'connector_resistance_ohm', 'connector_count', 'connector_mass_kg', 'current_limit_a', 'max_drop_v')
_LINE_FIELDS = ('line_id', 'source_port_id', 'load_port_id', 'waypoints_body_m', 'slack_m',
                'wire', 'operating_point', 'mass', 'wire_loss_node_id')
_ROOT_FIELDS = ('format', 'version', 'thermal_codec_version', 'units', 'assembly_digest',
                'body_frame_id', 'ports', 'lines', 'thermal_bindings', 'thermal_network',
                'thermal_boundaries', 'supply_assumption', 'supply_rationale')


def _line_payload(line):
    point, mass = line.operating_point, line.mass
    return {'line_id': line.line_id, 'source_port_id': line.source_port_id,
            'load_port_id': line.load_port_id,
            'waypoints_body_m': [_vector_json(v) for v in line.waypoints_body_m],
            'slack_m': line.slack_m.hex(),
            'wire': {name: getattr(line.wire, name) if name == 'connector_count'
                     else getattr(line.wire, name).hex() for name in _WIRE_FIELDS},
            'operating_point': {'mode': point.mode, 'source_voltage_v': point.source_voltage_v.hex(),
                                'power_w': point.power_w.hex()},
            'mass': {'status': mass.status, 'coverage': None if mass.coverage is None
                     else [list(p) for p in mass.coverage.paths],
                     'included_instance_id': mass.included_instance_id},
            'wire_loss_node_id': line.wire_loss_node_id}


def dumps_interface_document(design, interfaces: AssemblyInterfaces) -> str:
    _, value = validate_binding(design, interfaces)
    if CANONICAL_VERSION != 1:
        raise ValueError('unreviewed embedded thermal codec version')
    return json_text({'format': INTERFACE_FORMAT, 'version': INTERFACE_VERSION,
        'thermal_codec_version': 1, 'units': dict(_UNITS),
        'assembly_digest': value.assembly_digest, 'body_frame_id': value.body_frame_id,
        'ports': [{'port_id': p.port_id, 'instance_id': p.instance_id,
                   'local_frame_id': p.local_frame_id, 'position_local_m': _vector_json(p.position_local_m),
                   'role': p.role} for p in value.ports],
        'lines': [_line_payload(l) for l in value.lines],
        'thermal_bindings': [{'instance_id': b.instance_id, 'node_id': b.node_id,
                              'lumping_group': b.lumping_group} for b in value.thermal_bindings],
        'thermal_network': None if value.thermal_network is None else canonical_content(value.thermal_network),
        'thermal_boundaries': None if value.thermal_boundaries is None else canonical_content(value.thermal_boundaries),
        'supply_assumption': value.supply_assumption, 'supply_rationale': value.supply_rationale})


def interface_document_digest(design, interfaces: AssemblyInterfaces) -> str:
    return hashlib.sha256(_DOMAIN + dumps_interface_document(design, interfaces).encode('utf-8')).hexdigest()


def _port(value):
    p = object_fields(value, ('port_id', 'instance_id', 'local_frame_id', 'position_local_m', 'role'))
    return ElectricalPort(p['port_id'], p['instance_id'], p['local_frame_id'], _vector(p['position_local_m']), p['role'])


def _line(value):
    l = object_fields(value, _LINE_FIELDS)
    w = object_fields(l['wire'], _WIRE_FIELDS)
    wire = WireProperties(**{name: w[name] if name == 'connector_count' else _number(w[name]) for name in _WIRE_FIELDS})
    p = object_fields(l['operating_point'], ('mode', 'source_voltage_v', 'power_w'))
    point = OperatingPoint(p['mode'], _number(p['source_voltage_v']), _number(p['power_w']))
    m = object_fields(l['mass'], ('status', 'coverage', 'included_instance_id'))
    coverage = None if m['coverage'] is None else MassCoverage(tuple(tuple(_array(p)) for p in _array(m['coverage'])))
    mass = HarnessMassDeclaration(m['status'], coverage, m['included_instance_id'])
    return LineConnection(l['line_id'], l['source_port_id'], l['load_port_id'],
        tuple(_vector(v) for v in _array(l['waypoints_body_m'])), _number(l['slack_m']),
        wire, point, mass, l['wire_loss_node_id'])


def _binding(value):
    b = object_fields(value, ('instance_id', 'node_id', 'lumping_group'))
    return ThermalBinding(b['instance_id'], b['node_id'], b['lumping_group'])


def loads_interface_document(text, design, *, expected_digest=None) -> AssemblyInterfaces:
    d = object_fields(parse_json(text), _ROOT_FIELDS)
    for name in ('version', 'thermal_codec_version'):
        if type(d[name]) is not int:
            raise TypeError('document versions must be exact integers')
    if d['format'] != INTERFACE_FORMAT or d['version'] != 1 or d['thermal_codec_version'] != 1 or CANONICAL_VERSION != 1:
        raise ValueError('unsupported interface format/version/thermal codec')
    if object_fields(d['units'], _UNITS) != _UNITS:
        raise ValueError('unsupported interface units')
    result = AssemblyInterfaces(d['assembly_digest'], d['body_frame_id'],
        tuple(_port(p) for p in _array(d['ports'])), tuple(_line(l) for l in _array(d['lines'])),
        tuple(_binding(b) for b in _array(d['thermal_bindings'])),
        None if d['thermal_network'] is None else decode_content(d['thermal_network']),
        None if d['thermal_boundaries'] is None else decode_content(d['thermal_boundaries']),
        d['supply_assumption'], d['supply_rationale'])
    _, result = validate_binding(design, result)
    if expected_digest is not None:
        _digest(expected_digest)
        if not hmac.compare_digest(interface_document_digest(design, result), expected_digest):
            raise ValueError('interface document digest mismatch')
    return result


def save_interface_document(design, interfaces, path: str | Path) -> None:
    encoded = dumps_interface_document(design, interfaces).encode('utf-8')
    with Path(path).open('xb') as handle:
        handle.write(encoded)


def load_interface_document(path: str | Path, design, *, expected_digest=None) -> AssemblyInterfaces:
    return loads_interface_document(Path(path).read_bytes().decode('utf-8', errors='strict'),
                                    design, expected_digest=expected_digest)
