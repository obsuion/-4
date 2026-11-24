"""Canonical strict immutable input codec; outputs and filesystem paths reject."""
from dataclasses import asdict,fields
from hashlib import sha256
from .spacecraft_project import SpacecraftProject,ProjectLimits
from .design_repair import MissionRequirements
from .command_document import inputs_to_json as root_json,inputs_from_json as parse_root
from .long_mission_document import canonical_json
from .experiment_codec import parse_json,object_fields
from .long_mission_continuation import _bounded_tree
FORMAT='M8_IMMUTABLE_SPACECRAFT_PROJECT_INPUT_V1'
MAX_BYTES=16*2**20

def dumps_project(project):
    from .spacecraft_project_v3 import SpacecraftProjectV3
    if type(project)is SpacecraftProjectV3:
        from .spacecraft_project_v3_document import dumps_project as dumps_v3
        return dumps_v3(project)
    if type(project) is not SpacecraftProject:
        from .spacecraft_project_v2_document import dumps_project as dumps_v2
        return dumps_v2(project)
    project.__post_init__()
    inputs=dict(reference=parse_json(root_json(project.reference)),source_identity=project.source_identity,
        title=project.title,placement=project.placement,payload_area_hex=project.payload_area_m2.hex(),
        requirements=asdict(project.requirements),limits=asdict(project.limits),method=project.method)
    body=dict(format=FORMAT,version=1,inputs=inputs)
    body['digest']=sha256(canonical_json(body).encode()).hexdigest()
    text=canonical_json(body)
    if len(text.encode())>MAX_BYTES:raise ValueError('project input bytes')
    return text

def loads_project(text,*,expected_identity=None,expected_source_identity=None,expected_reference_identity=None):
    if type(text) is not str or len(text.encode())>MAX_BYTES:raise ValueError('bounded exact project text')
    d=object_fields(parse_json(text),('format','version','inputs','digest'));_bounded_tree(d)
    from .spacecraft_project_v3_document import FORMAT as V3_FORMAT
    if d['format']==V3_FORMAT:
        from .spacecraft_project_v3_document import loads_project as loads_v3
        return loads_v3(text,expected_identity=expected_identity,expected_source_identity=expected_source_identity,expected_reference_identity=expected_reference_identity)
    if d['format']!=FORMAT:
        from .spacecraft_project_v2_document import loads_project as loads_v2
        return loads_v2(text,expected_identity=expected_identity,expected_source_identity=expected_source_identity,
            expected_reference_identity=expected_reference_identity)
    if type(d['format']) is not str or d['format']!=FORMAT or type(d['version']) is not int or d['version']!=1:
        raise ValueError('exact project format/version')
    body={n:d[n] for n in ('format','version','inputs')}
    if type(d['digest']) is not str or sha256(canonical_json(body).encode()).hexdigest()!=d['digest']:
        raise ValueError('project content digest')
    i=object_fields(d['inputs'],('reference','source_identity','title','placement','payload_area_hex','requirements','limits','method'))
    if type(i['payload_area_hex']) is not str or len(i['payload_area_hex'])>32:raise ValueError('exact SI area spelling')
    area=float.fromhex(i['payload_area_hex'])
    if area.hex()!=i['payload_area_hex']:raise ValueError('canonical area')
    req=object_fields(i['requirements'],tuple(f.name for f in fields(MissionRequirements)))
    limits=object_fields(i['limits'],tuple(f.name for f in fields(ProjectLimits)))
    root=parse_root(canonical_json(i['reference']))
    project=SpacecraftProject(root,i['source_identity'],i['title'],i['placement'],area,MissionRequirements(**req),ProjectLimits(**limits),i['method'])
    from .rolling_physics import digest
    if expected_identity is not None and project.identity!=expected_identity:raise ValueError('foreign project revision')
    if expected_source_identity is not None and project.source_identity!=expected_source_identity:raise ValueError('foreign source')
    if expected_reference_identity is not None and digest(root)!=expected_reference_identity:raise ValueError('foreign mission template')
    if dumps_project(project)!=canonical_json(d):raise ValueError('noncanonical project input')
    return project
