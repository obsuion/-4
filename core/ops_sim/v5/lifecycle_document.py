"""Strict versioned B52 immutable inputs; no advanced state in an input file."""
from dataclasses import asdict, fields
from hashlib import sha256
import json

from .lifecycle_contract import LifecycleRoot, LifecyclePolicy, LifecycleScenario, METHOD53, METHOD55, identity
from .command_document import inputs_from_json
from .experiment_codec import parse_json, object_fields, _encode as _typed_data, check_schema_coverage
from .rolling_document import NEW as _ROLLING_INPUT_TYPES, ENUMS as _OBSERVED_ENUMS
from .construction_document import OWNERS as _CONSTRUCTION_INPUT_TYPES
from .harness_document import MAP as _MASS_INPUT_TYPES
from .long_mission_document import _NEW as _LONG_INPUT_TYPES
from .assembly_choices import AssemblyDesign
from .harness_mass import HarnessAugmentationInputs
from .checkpoint import CheckpointState
from .sun_table import SunPositionTable
from .sun_table_document import PROVENANCE_FIELDS

FORMAT = 'B52_FINITE_LIFECYCLE_INPUT_V1'
FORMAT53 = 'B53_FINITE_QUIET_LIFECYCLE_INPUT_V2'
FORMAT55 = 'B55_FINITE_POWER_SERVICE_LIFECYCLE_INPUT_V3'
FORMAT55_SUN = 'B55_POWER_SERVICE_EXPLICIT_REDUCED_SUN_INPUT_V4'
FORMAT56 = 'B56_EXPLICIT_ENERGY_ATTITUDE_INPUT_V5'
FORMAT58 = 'B58_EXPLICIT_BATTERY_PORT_INPUT_V6'
FORMAT61 = 'B61_EXPLICIT_ENVIRONMENT_AGEING_INPUT_V7'
MAX_ROOT_BYTES = 8*2**20


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def _bounded(value):
    count = 0
    todo = [(value, 0)]
    while todo:
        item, depth = todo.pop()
        count += 1
        if count > 2**19 or depth > 64:
            raise ValueError('bounded lifecycle input graph required')
        if type(item) is dict:
            if len(item) > 65536 or any(type(k) is not str or len(k) > 1024 for k in item):
                raise ValueError('bounded lifecycle input object required')
            todo.extend((v, depth+1) for v in item.values())
        elif type(item) is list:
            if len(item) > 65536:
                raise ValueError('bounded lifecycle input array required')
            todo.extend((v, depth+1) for v in item)
        elif type(item) is str:
            if len(item.encode('utf-8')) > 2**20:
                raise ValueError('bounded lifecycle input text required')
        elif item is not None and type(item) not in (int, float, bool):
            raise TypeError('JSON lifecycle input data required')


def _assembly_data(design):
    """Read the already admitted immutable assembly; do not reconstruct it."""
    def vector(value):
        return [x.hex() for x in value]
    def box(value):
        return None if value is None else dict(lower_m=vector(value.lower_m), upper_m=vector(value.upper_m))
    def pose(value):
        return dict(mount_id=value.mount_id, choice_id=value.choice_id,
            body_frame_id=value.body_frame_id, local_frame_id=value.local_frame_id,
            origin_body_m=vector(value.origin_body_m),
            rotation_body_from_local=[vector(row) for row in value.rotation_body_from_local],
            occupied_slots=list(value.occupied_slots))
    return dict(format='M1_ASSEMBLY_DOCUMENT', version=1,
        units=dict(mass='kg', length='m', inertia='kg*m^2', rotation='dimensionless'),
        body_frame_id=design.body_frame_id, clearance_m=design.clearance_m.hex(),
        definitions=[dict(definition_id=d.definition_id, local_frame_id=d.local_frame_id,
            mass_kg=d.mass_kg.hex(), size_m=vector(d.size_m), center_local_m=vector(d.center_local_m),
            mass_distribution=d.mass_distribution) for d in design.definitions],
        instances=[dict(instance_id=i.instance_id, definition_id=i.definition_id,
            mass_coverage=None if i.mass_coverage is None else [list(p) for p in i.mass_coverage.paths])
            for i in design.instances],
        choices=[dict(choice_id=c.choice_id, definition_id=c.definition_id,
            allowed_instance_ids=list(c.allowed_instance_ids), pose=pose(c.pose), envelope=box(c.envelope),
            allowed_region_id=c.allowed_region_id, exclusive=c.exclusive) for c in design.choices],
        selections=[dict(instance_id=s.instance_id, choice_id=s.choice_id) for s in design.selections],
        allowed_regions=[dict(region_id=r.region_id, box=box(r.box)) for r in design.allowed_regions],
        reserved_regions=[dict(region_id=r.region_id, box=box(r.box)) for r in design.reserved_regions])


def _long_data(value):
    """The accepted B44 input wire, with no decode/constructor round trip.

    Admission of a fresh document stays with the accepted strict reader below.
    Re-emitting a known immutable root during checkpoint binding is data work;
    in particular it must not reconstruct J2CartesianTrajectory and call gravity.
    """
    owner = type(value)
    if owner is SunPositionTable:
        table = dict(epoch=value.epoch, frame=value.frame, domain_seconds=value.domain_seconds,
            interpolation=value.interpolation,
            samples=tuple(dict(elapsed_seconds=s.elapsed_seconds, position_m=s.position_m) for s in value.samples),
            provenance={name: getattr(value.provenance, name) for name in PROVENANCE_FIELDS})
        return dict(sun_table=_long_data(table))
    if owner in _LONG_INPUT_TYPES:
        return dict(input_type=owner.__name__, fields={f.name: _long_data(getattr(value, f.name)) for f in fields(value)})
    if owner is dict:
        return dict(input_map={n: _long_data(x) for n, x in value.items()})
    if owner is tuple:
        return dict(input_tuple=[_long_data(x) for x in value])
    # _encode itself only reads the pinned immutable field schema. Unlike
    # canonical_content it does not decode, normalize, or run an owner constructor.
    return dict(typed=_typed_data(value))


def _construction_data(value):
    if type(value) in _CONSTRUCTION_INPUT_TYPES:
        return dict(construction_type=type(value).__name__,
            fields={f.name: _construction_data(getattr(value, f.name)) for f in fields(value)})
    if type(value) is tuple:
        return dict(construction_tuple=[_construction_data(x) for x in value])
    return dict(legacy_input=_long_data(value))


def _mass_data(value):
    if type(value) in _MASS_INPUT_TYPES.values():
        return dict(mass_type=type(value).__name__,
            fields={f.name: _mass_data(getattr(value, f.name)) for f in fields(value)})
    if type(value) is tuple:
        return dict(mass_tuple=[_mass_data(x) for x in value])
    return dict(primitive_input=_construction_data(value))


def _rolling_data(value):
    if type(value) in _ROLLING_INPUT_TYPES:
        return dict(rolling_type=type(value).__name__,
            fields={f.name: _rolling_data(getattr(value, f.name)) for f in fields(value)})
    if type(value) in _OBSERVED_ENUMS.values():
        return dict(observed_enum=type(value).__name__, member=value.name)
    if type(value) is CheckpointState:
        return dict(private_root_checkpoint=value.to_dict())
    if type(value) is AssemblyDesign:
        return dict(assembly=_assembly_data(value))
    if type(value) is HarnessAugmentationInputs:
        return dict(mass=_mass_data(value))
    if type(value) in _CONSTRUCTION_INPUT_TYPES:
        return dict(construction=_construction_data(value))
    if type(value) is tuple:
        return dict(rolling_tuple=[_rolling_data(x) for x in value])
    return dict(immutable_input=_long_data(value))


def _base_data(base,*,input_codec=None):
    """Preserve the exact B47/B48 input envelopes while only reading data."""
    if input_codec is None:check_schema_coverage()
    else:
        from .prepared_input_codec import require_scope
        require_scope(input_codec)
    encoded = _rolling_data(base.reference)
    reference = dict(format='M5_ROLLING_INPUT_V1', version=1, inputs=encoded,
        digest=sha256(canonical(dict(domain='M5_ROLLING_INPUT_V1', inputs=encoded)).encode('utf-8')).hexdigest())
    data = dict(reference=reference,
        estimation={f.name: getattr(base.estimation, f.name) for f in fields(base.estimation)},
        controller_method=base.controller_method, api=base.api)
    document = dict(format='M5_COMMAND_ESTIMATION_INPUT_V1', version=1, inputs=data)
    document['digest'] = sha256(canonical(document).encode('utf-8')).hexdigest()
    return document


def dumps_root(root,*,input_codec=None):
    """Canonical bytes; immutable original B48 definitions are nested as DATA."""
    if type(root) is not LifecycleRoot:
        raise TypeError('exact lifecycle root required')
    root.__post_init__()
    policy=asdict(root.policy)
    if root.method not in (METHOD53,METHOD55):policy.pop('quiet_solver')
    data = dict(base=_base_data(root.base,input_codec=input_codec),
                duration_seconds=root.duration_seconds, policy=policy,
                scenario=asdict(root.scenario), sun_mode=root.sun_mode, method=root.method)
    if root.method in (METHOD53,METHOD55):
        from .lifecycle_study import study_to_data
        data.update(study=None if root.study is None else study_to_data(root.study),
                    output_policy=None if root.output_policy is None else asdict(root.output_policy))
    if root.method==METHOD55:data['service_policy']=asdict(root.service_policy)
    explicit_sun=root.reduced_sun_policy is not None
    if explicit_sun:data['reduced_sun_policy']=asdict(root.reduced_sun_policy)
    solar=root.energy_attitude_policy is not None
    if solar:
        data['energy_attitude_policy']=asdict(root.energy_attitude_policy)
        data['reduced_sun_policy']=None if root.reduced_sun_policy is None else asdict(root.reduced_sun_policy)
    battery=root.battery_port_policy is not None
    if battery:
        data['battery_port_policy']=asdict(root.battery_port_policy)
        data.setdefault('energy_attitude_policy',None)
        data.setdefault('reduced_sun_policy',None)
    ageing=root.environment_ageing_policy is not None
    if ageing:
        from .environment_ageing_document import to_data
        data['environment_ageing_policy']=to_data(root.environment_ageing_policy)
    document = dict(format=FORMAT61 if ageing else FORMAT58 if battery else FORMAT56 if solar else FORMAT55_SUN if explicit_sun else FORMAT55 if root.method==METHOD55 else FORMAT53 if root.method==METHOD53 else FORMAT,
                    version=7 if ageing else 6 if battery else 5 if solar else 4 if explicit_sun else 3 if root.method==METHOD55 else 2 if root.method==METHOD53 else 1, inputs=data)
    document['digest'] = sha256(canonical(document).encode('utf-8')).hexdigest()
    raw = canonical(document).encode('utf-8')
    if not 0 < len(raw) <= MAX_ROOT_BYTES:
        raise ValueError('lifecycle immutable input byte limit')
    return raw


def loads_root(raw,*,input_codec=None):
    """Default strict REFERENCE reader, or one explicit prepared transaction.

    The caller retains the supplied capability to obtain its bounded receipt
    after success or failure. It cannot be reused for another root read.
    """
    if input_codec is None:
        return _loads_root(raw)
    from .prepared_input_codec import PreparedInputCodec
    if type(input_codec)is not PreparedInputCodec:
        raise TypeError('B63 exact input codec required')
    with input_codec:
        return _loads_root(raw,input_codec=input_codec)


def _loads_root(raw,*,input_codec=None):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ROOT_BYTES:
        raise ValueError('bounded lifecycle input bytes required')
    document = object_fields(parse_json(raw.decode('utf-8')),
                             ('format', 'version', 'inputs', 'digest'))
    _bounded(document)
    if type(document['format']) is not str or type(document['version']) is not int or (document['format'],document['version']) not in ((FORMAT,1),(FORMAT53,2),(FORMAT55,3),(FORMAT55_SUN,4),(FORMAT56,5),(FORMAT58,6),(FORMAT61,7)):
        raise ValueError('lifecycle input format/version')
    identity(document['digest'])
    body = {n: document[n] for n in ('format', 'version', 'inputs')}
    if sha256(canonical(body).encode('utf-8')).hexdigest() != document['digest']:
        raise ValueError('lifecycle input content digest')
    ageing=document['format']==FORMAT61
    battery=document['format']==FORMAT58 or ageing and 'battery_port_policy'in document['inputs']
    solar=document['format'] in (FORMAT56,FORMAT58) or ageing and 'energy_attitude_policy'in document['inputs']
    explicit_sun=document['format']==FORMAT55_SUN or solar or ageing and 'reduced_sun_policy'in document['inputs']
    service=document['format'] in (FORMAT55,FORMAT55_SUN,FORMAT56,FORMAT58) or ageing and 'service_policy'in document['inputs']
    extended=document['format'] in (FORMAT53,FORMAT55,FORMAT55_SUN,FORMAT56,FORMAT58,FORMAT61)
    data = object_fields(document['inputs'],
                         ('base', 'duration_seconds', 'policy', 'scenario', 'sun_mode', 'method')+
                         (('study','output_policy') if extended else ())+ (('service_policy',) if service else ())+
                         (('reduced_sun_policy',) if explicit_sun else ())+ (('energy_attitude_policy',) if solar else ())+ (('battery_port_policy',) if battery else ())+ (('environment_ageing_policy',) if ageing else ()))
    object_fields(data['policy'], tuple(f.name for f in fields(LifecyclePolicy) if extended or f.name!='quiet_solver'))
    object_fields(data['scenario'], tuple(f.name for f in fields(LifecycleScenario)))
    # The accepted strict B48 reader owns immutable hardware/initial-state
    # admission. It is never used to deserialize an advanced lifecycle state.
    base = inputs_from_json(canonical(data['base']))if input_codec is None else inputs_from_json(canonical(data['base']),input_codec=input_codec)
    policy=dict(data['policy']);study=output=service_policy=reduced_sun_policy=energy_policy=port_policy=None
    if extended:
        from .lifecycle_quiet import QuietIntegrationPolicy,BatteryQuietIntegrationPolicy,EnvironmentQuietIntegrationPolicy
        from .lifecycle_stream import LifecycleStreamPolicy
        from .lifecycle_study import study_from_data
        if policy['quiet_solver'] is not None:
            owner=EnvironmentQuietIntegrationPolicy if ageing else BatteryQuietIntegrationPolicy if battery else QuietIntegrationPolicy
            object_fields(policy['quiet_solver'],tuple(f.name for f in fields(owner)))
            policy['quiet_solver']=owner(**policy['quiet_solver'])
        study=None if data['study'] is None else study_from_data(data['study'])
        if data['output_policy'] is not None:
            object_fields(data['output_policy'],tuple(f.name for f in fields(LifecycleStreamPolicy)))
            output=LifecycleStreamPolicy(**data['output_policy'])
        if data['method']!=(METHOD55 if service else METHOD53):raise ValueError('extended input requires explicit method identity')
    if service:
        from .lifecycle_service import PowerServicePolicy
        object_fields(data['service_policy'],tuple(f.name for f in fields(PowerServicePolicy)))
        service_policy=PowerServicePolicy(**data['service_policy'])
    if explicit_sun and data['reduced_sun_policy'] is not None:
        from .lifecycle_world import ReducedSunPolicy
        object_fields(data['reduced_sun_policy'],tuple(f.name for f in fields(ReducedSunPolicy)))
        reduced_sun_policy=ReducedSunPolicy(**data['reduced_sun_policy'])
    if explicit_sun and not solar and reduced_sun_policy is None:raise ValueError('legacy explicit Sun input requires its complete policy')
    if solar and data['energy_attitude_policy'] is not None:
        from .solar_attitude import EnergyAttitudePolicy
        object_fields(data['energy_attitude_policy'],tuple(f.name for f in fields(EnergyAttitudePolicy)))
        energy_policy=EnergyAttitudePolicy(**data['energy_attitude_policy'])
    if solar and not battery and energy_policy is None:raise ValueError('solar input requires energy policy')
    if battery:
        from .battery_port import BatteryPortPolicy
        raw_policy=object_fields(data['battery_port_policy'],tuple(f.name for f in fields(BatteryPortPolicy)))
        port_data=dict(raw_policy)
        curve=port_data['ocv_curve']
        if type(curve)is not list or any(type(p)is not list or len(p)!=2 for p in curve):raise ValueError('strict OCV point array')
        port_data['ocv_curve']=tuple(tuple(p)for p in curve)
        port_policy=BatteryPortPolicy(**port_data)
    env=None
    if ageing:
        from .environment_ageing_document import from_data
        env=from_data(data['environment_ageing_policy'])
    root = LifecycleRoot(base, data['duration_seconds'], LifecyclePolicy(**policy),
                         LifecycleScenario(**data['scenario']), data['sun_mode'], data['method'],study,output,service_policy,reduced_sun_policy,energy_policy,port_policy,env)
    if dumps_root(root,input_codec=input_codec) != raw:
        raise ValueError('noncanonical lifecycle immutable input document')
    return root
