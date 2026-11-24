"""Strict input-only B40 documents; no callbacks, results or numerical launch."""
from dataclasses import fields
from hashlib import sha256
import json
from pathlib import Path
from .experiment_codec import canonical_content, decode_content, object_fields, parse_json
from .environment_forcing_document import (environment_forcing_to_json, environment_forcing_from_json,
                                          _bounded_tree)
from .assembly_document import dumps_assembly_document, loads_assembly_document
from .mission_environment import CatalogPoint, SamplingPolicy
from .mission_general_geometry import GeneralGeometryPolicy, MODE
from .assembly_attitude import ComponentAxisBinding
from .assembly_attitude_3d import NetTorqueActuatorPolicy as ActuatorPolicy
from .environment_mission_3d import EnvironmentMissionInputs3D, MissionAction, MissionLimits
from .orbit_geometry import GroundPointDefinition
from .orbit_visibility import GroundVisibilityPolicy
from .checkpoint import CheckpointState

FORMAT='B43_GENERAL_EARTH_MISSION_INPUT_V4'
_NEW=(ComponentAxisBinding,ActuatorPolicy,MissionAction,MissionLimits,SamplingPolicy,CatalogPoint,
      GroundPointDefinition,GroundVisibilityPolicy,GeneralGeometryPolicy)
_NEW_MAP={c.__name__:c for c in _NEW}
_FIELDS=tuple(f.name for f in fields(EnvironmentMissionInputs3D))
# Deliberately immutable-input families only; no query/result/trajectory decoder.
_OLD_PREFIXES=('ops_sim.v5.ids.',)
_OLD_EXACT=('ops_sim.v5.adcs_config.AgilePointingConfig', 'ops_sim.v5.adcs_config.BoresightSlewTimeAnchor', 'ops_sim.v5.configuration.ADCSConfig', 'ops_sim.v5.configuration.BatteryConfig', 'ops_sim.v5.configuration.CommunicationsConfig', 'ops_sim.v5.configuration.DegradationConfig', 'ops_sim.v5.configuration.EPSConfig', 'ops_sim.v5.configuration.OBCConfig', 'ops_sim.v5.configuration.PayloadConfig', 'ops_sim.v5.configuration.PayloadFamily', 'ops_sim.v5.configuration.PayloadMode', 'ops_sim.v5.configuration.PropulsionConfig', 'ops_sim.v5.configuration.SolarArrayConfig', 'ops_sim.v5.configuration.SpacecraftConfiguration', 'ops_sim.v5.configuration.StorageConfig', 'ops_sim.v5.configuration.ThermalConfig', 'ops_sim.v5.context.SimulationInputs', 'ops_sim.v5.coupled_downlink.DownlinkTransmitterConfig', 'ops_sim.v5.degradation_config.BatteryAgeingModelConfig', 'ops_sim.v5.manifest.ModelManifest', 'ops_sim.v5.ms_product.MSFootprint', 'ops_sim.v5.ms_product.MSProductSpec', 'ops_sim.v5.observation.ImagingRequest', 'ops_sim.v5.operational_protection.ProtectionPolicy', 'ops_sim.v5.orbit_config.FrameDefinition', 'ops_sim.v5.orbit_config.FrameKind', 'ops_sim.v5.orbit_config.GeometryInstant', 'ops_sim.v5.orbit_config.ReferenceEllipsoid', 'ops_sim.v5.orbit_config.TTEpoch', 'ops_sim.v5.orbit_config.UniformRotationDefinition', 'ops_sim.v5.parameters.ScalarParameter', 'ops_sim.v5.payload_config.OpticalAcquisitionConfig', 'ops_sim.v5.provenance.ParameterProvenance', 'ops_sim.v5.provenance.ProvenanceClass', 'ops_sim.v5.provenance.ProvenanceStatus', 'ops_sim.v5.run_config.EnvironmentConfig', 'ops_sim.v5.run_config.FlightRulesConfig', 'ops_sim.v5.run_config.NumericalConfig', 'ops_sim.v5.run_config.ScenarioConfig', 'ops_sim.v5.thermal_config.ThermalLinkConfig', 'ops_sim.v5.thermal_config.ThermalNetworkConfig', 'ops_sim.v5.thermal_config.ThermalNodeConfig', 'ops_sim.v5.thermal_routing.ComponentHeatRoute', 'ops_sim.v5.thermal_routing.ComponentHeatRoutingConfig', 'ops_sim.v5.thermal_routing.ElectricalLoadComponent', 'ops_sim.v5.world.CommonWorld')


def _admit_wire(v):
    if type(v) is not dict:raise ValueError('typed wire input required')
    kind=v.get('kind')
    if kind in ('record','enum'):
        typ=v.get('type')
        if type(typ) is not str or not (typ in _OLD_EXACT or typ.startswith(_OLD_PREFIXES)):
            raise ValueError('unsafe/non-input record type: '+str(typ))
        if kind=='record':
            object_fields(v,('kind','type','fields'))
            if type(v['fields']) is not dict:raise ValueError('record fields required')
            for x in v['fields'].values():_admit_wire(x)
        else:object_fields(v,('kind','type','member'))
    elif kind in ('tuple','list','map'):
        object_fields(v,('kind','items'))
        if type(v['items']) is not list:raise ValueError('typed items required')
        for x in v['items']:
            if kind=='map':
                if type(x) is not list or len(x)!=2 or type(x[0]) is not str:raise ValueError('map pair required')
                x=x[1]
            _admit_wire(x)
    elif kind in ('none','str','int','float','bool','fraction'):
        # Existing primitive decoder performs exact kinds/fields/domain validation.
        decode_content(v)
    else:raise ValueError('unsupported executable/wire kind')


def _encode(value):
    if type(value) in _NEW:
        return dict(input_type=type(value).__name__,fields={f.name:_encode(getattr(value,f.name)) for f in fields(value)})
    if type(value) is tuple:return dict(input_tuple=[_encode(x) for x in value])
    return dict(typed=canonical_content(value))


def _predecode(node):
    if type(node) is not dict:raise ValueError('input node object required')
    if set(node)=={'input_type','fields'}:
        name=node['input_type']
        if type(name) is not str or name not in _NEW_MAP:raise ValueError('unknown input class')
        owner=_NEW_MAP[name];values=object_fields(node['fields'],tuple(f.name for f in fields(owner)))
        for x in values.values():_predecode(x)
    elif set(node)=={'input_tuple'}:
        if type(node['input_tuple']) is not list or len(node['input_tuple'])>256:raise ValueError('bounded input tuple required')
        for x in node['input_tuple']:_predecode(x)
    elif set(node)=={'typed'}:_admit_wire(node['typed'])
    else:raise ValueError('unsafe/unknown input node fields')


def _decode(node):
    if 'input_type' in node:
        cls=_NEW_MAP[node['input_type']]
        return cls(**{n:_decode(v) for n,v in node['fields'].items()})
    if 'input_tuple' in node:return tuple(_decode(x) for x in node['input_tuple'])
    return decode_content(node['typed'])


def input_data(inputs):
    # Input-only serialization, never stores provider results/attitude cache.
    if type(inputs) is not EnvironmentMissionInputs3D:raise TypeError('mission inputs required')
    if inputs.geometry_mode!=MODE:raise ValueError('V4 requires explicit general geometry mode')
    return {f.name:(inputs.initial_checkpoint.to_dict() if f.name=='initial_checkpoint' else
        json.loads(environment_forcing_to_json(inputs.environment)) if f.name=='environment' else
        json.loads(dumps_assembly_document(inputs.assembly)) if f.name=='assembly' else
        _encode(getattr(inputs,f.name))) for f in fields(inputs)}


def canonical_json(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def mission_input_digest(inputs):
    return sha256(canonical_json(dict(domain=FORMAT,inputs=input_data(inputs))).encode()).hexdigest()


def mission_inputs_to_json(inputs):
    data=input_data(inputs)
    return canonical_json(dict(format=FORMAT,version=4,inputs=data,
        digest=sha256(canonical_json(dict(domain=FORMAT,inputs=data)).encode()).hexdigest()))


def mission_inputs_from_json(text,*,expected_digest=None):
    if type(text) is not str or len(text.encode('utf-8'))>16*2**20:raise ValueError('bounded input document required')
    p=object_fields(parse_json(text),('format','version','inputs','digest'));_bounded_tree(p)
    if type(p['version']) is not int or p['version']!=4 or p['format']!=FORMAT:raise ValueError('unsupported mission format')
    d=object_fields(p['inputs'],_FIELDS)
    for n,v in d.items():
        if n not in ('initial_checkpoint','environment','assembly'):_predecode(v)
    digest=sha256(canonical_json(dict(domain=FORMAT,inputs=d)).encode()).hexdigest()
    if type(p['digest']) is not str or p['digest']!=digest or (expected_digest is not None and expected_digest!=digest):
        raise ValueError('mission input binding mismatch')
    # All our schemas admitted before constructing any nested physical input.
    values={n:_decode(v) for n,v in d.items() if n not in ('initial_checkpoint','environment','assembly')}
    values['initial_checkpoint']=CheckpointState.from_dict(d['initial_checkpoint'])
    values['environment']=environment_forcing_from_json(canonical_json(d['environment']))
    values['assembly']=loads_assembly_document(canonical_json(d['assembly']))
    result=EnvironmentMissionInputs3D(**values)
    if mission_inputs_to_json(result)!=canonical_json(p):raise ValueError('noncanonical mission inputs')
    return result


def save_mission_inputs(path,inputs):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:f.write(mission_inputs_to_json(inputs)+'\n')


def load_mission_inputs(path,*,expected_digest=None):
    p=Path(path)
    if p.stat().st_size>16*2**20:raise ValueError('document size exceeded')
    return mission_inputs_from_json(p.read_text(encoding='utf-8'),expected_digest=expected_digest)
