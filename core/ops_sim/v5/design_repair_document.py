"""Strict input-only finite repair specification; no scores or executable data."""
from dataclasses import asdict, fields
from hashlib import sha256
from .design_repair import DesignRepairSpec, MissionRequirements, StudyLimits
from .command_document import inputs_to_json as root_to_json, inputs_from_json as root_from_json
from .experiment_codec import object_fields, parse_json
from .long_mission_document import canonical_json
from .long_mission_continuation import _bounded_tree

FORMAT = 'M7_FINITE_DESIGN_REPAIR_INPUT_V1'
MAX_INPUT_BYTES = 16 * 2**20


def inputs_to_json(spec):
    if type(spec) is not DesignRepairSpec:
        raise TypeError('exact finite repair specification')
    spec.__post_init__()
    inputs = dict(reference=parse_json(root_to_json(spec.reference)), source_identity=spec.source_identity,
        placements=list(spec.placements), payload_areas_hex=[x.hex() for x in spec.payload_areas_m2],
        requirements=asdict(spec.requirements), limits=asdict(spec.limits),
        selection_rule=spec.selection_rule, method=spec.method)
    body = dict(format=FORMAT, version=1, inputs=inputs)
    body['digest'] = sha256(canonical_json(body).encode()).hexdigest()
    text = canonical_json(body)
    if len(text.encode()) > MAX_INPUT_BYTES:
        raise ValueError('finite repair input byte cap')
    return text


def inputs_from_json(text, *, expected_spec_identity=None, expected_source_identity=None):
    if type(text) is not str or len(text.encode()) > MAX_INPUT_BYTES:
        raise ValueError('bounded input text')
    d = object_fields(parse_json(text), ('format', 'version', 'inputs', 'digest')); _bounded_tree(d)
    if type(d['format']) is not str or d['format'] != FORMAT or type(d['version']) is not int or d['version'] != 1:
        raise ValueError('strict finite repair format')
    body = {n: d[n] for n in ('format', 'version', 'inputs')}
    if type(d['digest']) is not str or sha256(canonical_json(body).encode()).hexdigest() != d['digest']:
        raise ValueError('repair document digest')
    i = object_fields(d['inputs'], ('reference', 'source_identity', 'placements', 'payload_areas_hex', 'requirements', 'limits', 'selection_rule', 'method'))
    if type(i['placements']) is not list or not 1 <= len(i['placements']) <= 2:
        raise ValueError('finite placement array')
    if type(i['payload_areas_hex']) is not list or not 1 <= len(i['payload_areas_hex']) <= 4:
        raise ValueError('finite area array')
    areas = []
    for v in i['payload_areas_hex']:
        if type(v) is not str or len(v) > 32:
            raise ValueError('exact area hex')
        f = float.fromhex(v)
        if f.hex() != v:
            raise ValueError('noncanonical area hex')
        areas.append(f)
    req = object_fields(i['requirements'], tuple(f.name for f in fields(MissionRequirements)))
    limits = object_fields(i['limits'], tuple(f.name for f in fields(StudyLimits)))
    spec = DesignRepairSpec(root_from_json(canonical_json(i['reference'])), i['source_identity'],
        tuple(i['placements']), tuple(areas), MissionRequirements(**req), StudyLimits(**limits), i['selection_rule'], i['method'])
    if expected_spec_identity is not None and spec.identity != expected_spec_identity or expected_source_identity is not None and spec.source_identity != expected_source_identity:
        raise ValueError('external specification/source binding')
    if inputs_to_json(spec) != canonical_json(d):
        raise ValueError('noncanonical finite input')
    return spec
