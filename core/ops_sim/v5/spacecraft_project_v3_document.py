"""Closed input-only B66 codec. No import names, executable values or outputs."""
from dataclasses import fields, asdict
from hashlib import sha256
from math import isfinite
from .spacecraft_design import (DesignSpecification, DesignProvenance, BatteryModule,
    PVModule, ThermalPart, FunctionalPlant, BatteryPortPolicy, AssemblyDesign, ConstructionConfiguration,
    HarnessAugmentationInputs, ComponentAxisBinding, NetTorqueActuatorPolicy)
from .spacecraft_design import PayloadConfig, DownlinkTransmitterConfig, ComponentHeatRoutingConfig, PowerLoadBreakdown
from .spacecraft_project_v3 import SpacecraftProjectV3, METHOD
from .spacecraft_route_thermal import DesignSpecificationV2, RouteThermalDeclaration
from . import spacecraft_project_v2_document as legacy
from .spacecraft_project import ProjectLimits
from .design_repair import MissionRequirements
from .lifecycle_document import dumps_root, loads_root, canonical, _bounded
from .rolling_document import encode, admit, decode
from .rolling_physics import digest
from .experiment_codec import object_fields, parse_json

FORMAT = 'KAZEOSAT_SPACECRAFT_PROJECT_V3'
MAX_BYTES = 16*2**20
OWNERS = {c.__name__: c for c in (DesignSpecificationV2, RouteThermalDeclaration)}


def specification_data(value, *, input_codec=None):
    if type(value) in OWNERS.values():
        if input_codec is not None:input_codec.owner(type(value))
        result=dict(design_type=type(value).__name__,fields={f.name:specification_data(getattr(value,f.name),input_codec=input_codec)for f in fields(value)})
        if input_codec is not None:input_codec.owner(type(value))
        return result
    if type(value)is tuple:return dict(design_tuple=[specification_data(v,input_codec=input_codec)for v in value])
    return legacy.specification_data(value,input_codec=input_codec)


def _decode(value, depth=0, *, input_codec=None):
    if depth>64:raise ValueError('bounded V3 input depth')
    if type(value)is dict and set(value)=={'design_type','fields'} and type(value['design_type'])is str and value['design_type']in OWNERS:
        owner=OWNERS[value['design_type']]
        if input_codec is not None:input_codec.owner(owner)
        data=object_fields(value['fields'],tuple(f.name for f in fields(owner)))
        if owner is DesignSpecificationV2:
            arr=object_fields(data['route_thermal'],('design_tuple',))['design_tuple']
            if type(arr)is not list or len(arr)!=8:raise ValueError('preallocation eight-route coverage')
        result=owner(**{n:_decode(v,depth+1,input_codec=input_codec)for n,v in data.items()})
        if input_codec is not None:input_codec.owner(owner)
        return result
    if type(value)is dict and set(value)=={'design_tuple'}:
        arr=value['design_tuple']
        if type(arr)is not list or len(arr)>256:raise ValueError('bounded V3 tuple')
        return tuple(_decode(v,depth+1,input_codec=input_codec)for v in arr)
    return legacy._decode(value,depth,input_codec=input_codec)


def dumps_project(project):
    from .prepared_input_codec import PreparedInputCodec
    with PreparedInputCodec() as codec:
        return _dumps_project(project,codec)


def _dumps_project(project,codec):
    if type(project) is not SpacecraftProjectV3:
        raise TypeError('exact route-thermal project V3')
    project.__post_init__()
    codec.owner(SpacecraftProjectV3)
    inputs = dict(common=parse_json(dumps_root(project.common,input_codec=codec).decode()),
        specification=specification_data(project.specification,input_codec=codec), source_identity=project.source_identity,
        title=project.title, requirements=asdict(project.requirements), limits=asdict(project.limits), method=project.method)
    body = dict(format=FORMAT, version=3, inputs=inputs)
    body['digest'] = sha256(canonical(body).encode()).hexdigest()
    text = canonical(body)
    if len(text.encode()) > MAX_BYTES:
        raise ValueError('bounded general project bytes')
    return text


def loads_project(text, *, expected_identity=None, expected_source_identity=None, expected_reference_identity=None):
    from .prepared_input_codec import PreparedInputCodec
    with PreparedInputCodec() as codec:
        return _loads_project(text,expected_identity=expected_identity,
            expected_source_identity=expected_source_identity,
            expected_reference_identity=expected_reference_identity,input_codec=codec)


def _loads_project(text, *, expected_identity=None, expected_source_identity=None,
        expected_reference_identity=None,input_codec):
    if type(text) is not str or len(text.encode()) > MAX_BYTES:
        raise ValueError('bounded exact general project text')
    data = object_fields(parse_json(text), ('format', 'version', 'inputs', 'digest'))
    _bounded(data)
    if type(data['format']) is not str or data['format'] != FORMAT or type(data['version']) is not int or data['version'] != 3:
        raise ValueError('exact B68 project format/version')
    body = {n: data[n] for n in ('format', 'version', 'inputs')}
    if type(data['digest']) is not str or sha256(canonical(body).encode()).hexdigest() != data['digest']:
        raise ValueError('project content digest')
    i = object_fields(data['inputs'], ('common', 'specification', 'source_identity', 'title', 'requirements', 'limits', 'method'))
    # One scope spans common-root admission, design decode and the mandatory
    # constructor-normalized roundtrip. No capability escapes this invocation.
    from .lifecycle_document import _loads_root
    common = _loads_root(canonical(i['common']).encode(),input_codec=input_codec)
    spec = _decode(i['specification'],input_codec=input_codec)
    req = object_fields(i['requirements'], tuple(f.name for f in fields(MissionRequirements)))
    limits = object_fields(i['limits'], tuple(f.name for f in fields(ProjectLimits)))
    for owner in (SpacecraftProjectV3,MissionRequirements,ProjectLimits):input_codec.owner(owner)
    project = SpacecraftProjectV3(common, spec, i['source_identity'], i['title'], MissionRequirements(**req), ProjectLimits(**limits), i['method'])
    if expected_source_identity is not None and project.source_identity != expected_source_identity:
        raise ValueError('foreign source')
    if expected_reference_identity is not None and digest(project.reference) != expected_reference_identity:
        raise ValueError('foreign common mission template')
    encoded=_dumps_project(project,input_codec)
    if encoded != canonical(data):
        raise ValueError('noncanonical general project input')
    if expected_identity is not None and sha256(encoded.encode('utf8')).hexdigest() != expected_identity:
        raise ValueError('foreign project revision')
    return project
