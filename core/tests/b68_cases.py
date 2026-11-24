"""Portable original DESIGNS R3 DATA, not a second DESIGNS compiler."""
from pathlib import Path
from dataclasses import replace
from math import fsum
import hashlib,json

FIXTURES=Path(__file__).with_name('fixtures')

def authored(case='composition'):
    name='r3-user-composition'if case=='composition'else'r3-my-own-json-spacecraft'
    user_path=FIXTURES/('b68-'+name+'.user-spec-v1.json')
    core_path=FIXTURES/('b68-'+name+'.core-project-v2.json')
    mapping=json.loads((FIXTURES/('b68-'+name+'.mapping.json')).read_bytes())
    user=json.loads(user_path.read_bytes())
    from ops_sim.v5.spacecraft_project_v2_document import loads_project
    from ops_sim.v5.spacecraft_route_thermal import RouteThermalDeclaration,DesignSpecificationV2
    from ops_sim.v5.spacecraft_design import DesignProvenance
    from ops_sim.v5.spacecraft_project_v3 import SpacecraftProjectV3
    from ops_sim.v5.spacecraft_project import project_source_identity
    from ops_sim.v5.assembly_choices import assess_design
    prior=loads_project(core_path.read_text('utf8'))
    base=prior.specification;components=assess_design(base.assembly).assembly.components
    parts={p['id']:p for p in user['parts']};instances={i['id']:i for i in user['instances']}
    assert {c.component_id for c in components}==set(instances)
    for c in components:
        instance=instances[c.component_id];part=parts[instance['part_id']]
        assert c.definition.mass_kg==part['mass_kg']and tuple(c.definition.size_m)==tuple(part['size_m'])
        assert c.center_body_m==tuple(instance['position_m']) # fixture local COM offsets are zero
        assert c.rotation_body_from_local==tuple(tuple(v)for v in instance['rotation_body_from_local'])
        thermal=next(t for t in base.thermal_parts if t.instance_id==c.component_id)
        assert thermal.specific_heat_j_per_kg_k==part['specific_heat_j_kg_k']
    cp=user['thermal']['harness_specific_heat_j_kg_k'];bus=base.configuration.thermal_network.bus_node_id.value
    provenance=DesignProvenance('ASSUMED',(),user['thermal']['rationale']+'; original UserDesignSpecV1 SHA256='+hashlib.sha256(user_path.read_bytes()).hexdigest())
    declarations=tuple(RouteThermalDeclaration(l.line_id,bus,cp,provenance)for l in base.configuration.lines)
    project=SpacecraftProjectV3(prior.common,DesignSpecificationV2(base,declarations),project_source_identity(),title='B68 '+user['project_id'],requirements=prior.requirements,limits=prior.limits)
    return project,user,mapping
