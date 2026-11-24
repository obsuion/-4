"""Synthetic static M1-C causal example; no hardware or mission inference."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

from ops_sim.v5.assembly import MassCoverage, MountPose, UniformCuboid, calculate_mass_properties
from ops_sim.v5.assembly_choices import (
    AssemblyDesign, InstallationBox, InstallationRegion, PhysicalInstance, PlacementChoice, Selection,
)
from ops_sim.v5.assembly_document import assembly_document_digest, load_assembly_document, save_assembly_document
from ops_sim.v5.assembly_interfaces import (
    AssemblyInterfaces, ElectricalPort, HarnessMassDeclaration, LineConnection,
    OperatingPoint, ThermalBinding, WireProperties, compile_interfaces,
)
from ops_sim.v5.assembly_interface_document import (
    interface_document_digest, load_interface_document, save_interface_document,
)
from ops_sim.v5.ids import ParameterId, ThermalLinkId, ThermalNodeId
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import ParameterProvenance, ProvenanceClass, ProvenanceStatus
from ops_sim.v5.thermal import ThermalIntervalInputs, ThermalNodeBoundaryInput
from ops_sim.v5.thermal_config import ThermalLinkConfig, ThermalNetworkConfig, ThermalNodeConfig


IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def parameter(pid, units, value):
    return ScalarParameter(float(value), ParameterProvenance(ParameterId(pid),
        ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION, units, (), ProvenanceStatus.TO_RESEARCH,
        rationale='Synthetic unit fixture only; not a hardware coefficient.'))


def thermal_network():
    nodes = []
    for name in ('bus', 'battery', 'payload'):
        params = [(s, unit, v) for s, unit, v in (
            ('heat-capacity', 'J/K', 1000), ('emissivity', '1', .8), ('radiating-area', 'm^2', 1),
            ('operating-min-temperature', 'K', 270), ('operating-max-temperature', 'K', 320),
            ('survival-min-temperature', 'K', 250), ('survival-max-temperature', 'K', 340))]
        nodes.append(ThermalNodeConfig(ThermalNodeId(name),
            *(parameter(f'thermal.node.{name}.{s}', unit, v) for s, unit, v in params)))
    links = tuple(ThermalLinkConfig(ThermalLinkId(name), ThermalNodeId('bus'), ThermalNodeId(target),
        parameter(f'thermal.link.{name}.conductance', 'W/K', value))
        for name, target, value in (('bus-battery', 'battery', 1), ('bus-payload', 'payload', 2)))
    return ThermalNetworkConfig(tuple(nodes), links, ThermalNodeId('bus'),
                                ThermalNodeId('battery'), ThermalNodeId('payload'))


def synthetic_inputs(case='near', *, generated=False):
    if case not in ('near', 'far'):
        raise ValueError('unknown synthetic placement')
    definition = UniformCuboid('unit-device', 'device-local', 1, (.2, .2, .2), (0, 0, 0),
                                'ASSUMED_UNIFORM_CUBOID')
    instances = tuple(PhysicalInstance(i, definition.definition_id, MassCoverage((('devices', i),)))
                      for i in ('source', 'load'))
    choices = []
    for cid, iid, x in (('source-fixed', 'source', 0), ('load-near', 'load', 1), ('load-far', 'load', 2)):
        pose = MountPose(cid + '-mount', cid, 'body', 'device-local', (x, 0, 0), IDENTITY, (cid,))
        choices.append(PlacementChoice(cid, definition.definition_id, (iid,), pose,
            InstallationBox((x-.125, -.125, -.125), (x+.125, .125, .125)), 'bay', True))
    design = AssemblyDesign('body', (definition,), instances, tuple(choices),
        (Selection('source', 'source-fixed'), Selection('load', 'load-' + case)),
        (InstallationRegion('bay', InstallationBox((-1, -1, -1), (3, 1, 1))),), (), .125)
    ports = (ElectricalPort('supply', 'source', 'device-local', (0, 0, 0), 'SOURCE'),
             ElectricalPort('receiver', 'load', 'device-local', (0, 0, 0), 'LOAD'))
    line = LineConnection('power-line', 'supply', 'receiver', (), 0,
        WireProperties(1, .25, 10, 0, 0, 0, 100, 100),
        OperatingPoint('GENERATED' if generated else 'CONSTANT_LOAD', 10, 20 if generated else 18),
        HarnessMassDeclaration('EXCLUDED', MassCoverage((('external-harness', 'power-line'),)), None), 'bus')
    network = thermal_network()
    interfaces = AssemblyInterfaces(assembly_document_digest(design), 'body', ports, (line,),
        (ThermalBinding('source', 'battery', None), ThermalBinding('load', 'payload', None)), network,
        ThermalIntervalInputs(tuple(ThermalNodeBoundaryInput(n.node_id, 250.0) for n in network.nodes)),
        'IDEAL_INDEPENDENT_SOURCES', 'Synthetic fixed 10 V source; no EPS or mission service assertion.')
    return design, interfaces


def summary(design, interfaces):
    report = compile_interfaces(design, interfaces)
    return {'assembly_digest': assembly_document_digest(design),
        'interface_digest': interface_document_digest(design, interfaces),
        'usable_static_compilation': report.compilation is not None,
        'issues': [{'category': i.category, 'code': i.code, 'ids': list(i.affected_ids), 'detail': i.detail}
                   for i in report.issues],
        'assembled_mass_kg': None if report.assembly_assessment.assembly is None else
            calculate_mass_properties(report.assembly_assessment.assembly).total_mass_kg,
        'lines': [{'line_id': l.line_id, 'source_body_m': list(l.source_body_m), 'load_body_m': list(l.load_body_m),
            'polyline_length_m': l.polyline_length_m, 'one_way_length_m': l.wire.one_way_length_m,
            'resistance_ohm': l.wire.resistance_ohm, 'conductor_mass_kg': l.wire.conductor_mass_kg,
            'connector_mass_kg': l.wire.connector_total_mass_kg, 'calculated_harness_mass_kg': l.wire.harness_mass_kg,
            'harness_mass_status': l.harness_mass_status, 'current_a': l.electrical.current_a,
            'source_power_w': l.electrical.source_power_w, 'delivered_power_w': l.electrical.delivered_power_w,
            'wire_loss_w': l.electrical.loss_w, 'wire_loss_node_id': l.wire_loss_node_id}
            for l in report.line_diagnostics],
        'wire_loss_heat_w': None if report.compilation is None else
            {h.node_id.value: h.applied_heat_into_w for h in report.compilation.wire_loss_heat.node_heat_inputs},
        'limitation': 'Static ideal-source, wire-loss-only diagnostics; excluded harness mass is not assembled.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-dir', type=Path)
    parser.add_argument('--assembly', type=Path)
    parser.add_argument('--interfaces', type=Path)
    parser.add_argument('--expected-digest')
    args = parser.parse_args()
    if args.assembly is not None or args.interfaces is not None:
        if args.assembly is None or args.interfaces is None or args.export_dir is not None:
            parser.error('load requires both files, without --export-dir')
        design = load_assembly_document(args.assembly)
        inputs = load_interface_document(args.interfaces, design, expected_digest=args.expected_digest)
        print(json.dumps(summary(design, inputs), sort_keys=True, allow_nan=False))
        return
    if args.expected_digest is not None:
        parser.error('--expected-digest requires loading')
    if args.export_dir is not None:
        args.export_dir.mkdir(parents=True, exist_ok=False)
    results = {}
    for name, generated in (('near', False), ('far', False), ('near-generated', True), ('far-generated', True)):
        design, inputs = synthetic_inputs(name.split('-')[0], generated=generated)
        if args.export_dir is not None:
            save_assembly_document(design, args.export_dir / (name + '-assembly.json'))
            save_interface_document(design, inputs, args.export_dir / (name + '-interfaces.json'))
        results[name] = summary(design, inputs)
    print(json.dumps(results, sort_keys=True, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
