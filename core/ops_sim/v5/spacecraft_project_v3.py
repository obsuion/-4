"""Versioned general supported spacecraft design inputs; legacy V1/V2 are separate."""
from dataclasses import dataclass, replace, asdict
from hashlib import sha256
from .lifecycle_contract import LifecycleRoot, canonical
from .spacecraft_design import specification_from_root
from .spacecraft_route_thermal import DesignSpecificationV2, admit_design_v2
from .spacecraft_project import ProjectLimits, project_source_identity
from .design_repair import MissionRequirements, ConstructorLedger, hash_identity
from .rolling_physics import digest

METHOD = 'B68_IMMUTABLE_ROUTE_THERMAL_DESIGN_PROJECT_V3'


@dataclass(frozen=True, slots=True)
class SpacecraftProjectV3:
    common: LifecycleRoot
    specification: DesignSpecificationV2
    source_identity: str
    title: str = 'User spacecraft'
    requirements: MissionRequirements | None = None
    limits: ProjectLimits = ProjectLimits()
    method: str = METHOD

    def __post_init__(self):
        if type(self.common) is not LifecycleRoot:
            raise TypeError('exact B66 project LifecycleRoot')
        if self.requirements is None:
            object.__setattr__(self, 'requirements', MissionRequirements(
                minimum_credited_products=min(2, max(1, self.common.offered_population))))
        for name, owner in (('common', LifecycleRoot), ('specification', DesignSpecificationV2),
                            ('requirements', MissionRequirements), ('limits', ProjectLimits)):
            value = getattr(self, name)
            if type(value) is not owner:
                raise TypeError('exact B66 project ' + owner.__name__)
            value.__post_init__()
        hash_identity(self.source_identity)
        if type(self.title) is not str or not 1 <= len(self.title) <= 120 or any(ord(c) < 32 for c in self.title):
            raise ValueError('bounded plain project title')
        if type(self.method) is not str or self.method != METHOD:
            raise ValueError('explicit general project family')
        cp = self.common.base.initial_checkpoint
        if cp.diagnostics.completed_steps or cp.spacecraft.data_storage.stored_records or cp.ground_data_delivery.partial_transfers or cp.ground_data_delivery.completed_deliveries:
            raise ValueError('general project accepts original definitions, never advanced custody/state')
        if self.requirements.minimum_credited_products > self.common.offered_population:
            raise ValueError('requirements exceed actual recurring lifecycle request population')

    @property
    def reference(self):
        return self.common.base

    @property
    def placement(self):
        return 'CUSTOM'

    @property
    def payload_area_m2(self):
        return None  # There is no single privileged editable wire in V2.

    @property
    def identity(self):
        from .spacecraft_project_v3_document import dumps_project
        return sha256(dumps_project(self).encode()).hexdigest()

    @property
    def comparison_identity(self):
        return digest((METHOD, self.common, self.requirements, self.source_identity))


def project_from_root(common, *, route_thermal, title='User spacecraft', source_identity=None):
    return SpacecraftProjectV3(common, DesignSpecificationV2(specification_from_root(common), route_thermal),
        project_source_identity() if source_identity is None else source_identity, title)


def _admit_project(project, ledger):
    if type(project) is not SpacecraftProjectV3 or type(ledger) is not ConstructorLedger:
        raise TypeError('exact general project and paid ledger')
    project.__post_init__()
    if project.source_identity != project_source_identity():
        raise ValueError('PROJECT_SOURCE_MISMATCH')
    result = admit_design_v2(project.specification, project.common, ledger)
    return result


def materialize_lifecycle_project(project,ledger):
    result=_admit_project(project,ledger)
    return result.root,result.construction,result.hardware


def materialize_project(project, ledger):
    root, construction, hardware = materialize_lifecycle_project(project, ledger)
    return root.base, construction, hardware


def preview_project(project, ledger):
    from .spacecraft_project import _preview_materialized
    admission=_admit_project(project,ledger)
    lifecycle,construction,hardware=admission.root,admission.construction,admission.hardware
    root = lifecycle.base
    result = _preview_materialized(project, ledger, root, construction, hardware)
    result.update(route_thermal=admission.route_thermal.as_data(),format='B68_PAID_ROUTE_THERMAL_DESIGN_PREVIEW_V3',declaration_identity=project.specification.declaration_identity,route_thermal_method=project.specification.method,
        specification_identity=project.specification.identity, common_identity=project.common.identity,
        comparison_identity=project.comparison_identity,
        functional_composition=dict(battery_instances=[b.instance_id for b in project.specification.base.batteries],
            pv_instances=[p.instance_id for p in project.specification.base.pv_modules],
            nominal_battery_wh=root.model.simulation_inputs.spacecraft_configuration.eps.battery.nominal_energy_wh.value,
            nominal_pv_w=root.model.simulation_inputs.spacecraft_configuration.eps.solar_array.nominal_generation_w.value,
            baseline_loads_w=asdict(project.specification.base.functional.baseline_loads),
            acquisition_w=root.model.simulation_inputs.spacecraft_configuration.payload.optical_acquisition.acquisition_power_w.value,
            transmitter_w=root.model.transmitter.electrical_power_w.value,
            camera_half_fov_rad=root.model.camera_half_fov_rad,
            battery_rint_ohm=None if lifecycle.battery_port_policy is None else
                lifecycle.battery_port_policy.resistance_reference_ohm),
        thermal_plant=[dict(node=n.node_id.value,heat_capacity_j_per_k=n.heat_capacity_j_per_k.value,
            radiating_area_m2=n.radiating_area_m2.value,emissivity=n.emissivity.value)
            for n in root.model.configuration.thermal_network.nodes],
        assumptions=[project.specification.base.provenance.rationale,
            'Rigid uniform cuboids; authored admissible arbitrary poses; ideal common-SOC/temperature parallel battery bank.',
            'Co-oriented PV modules (origins may differ) and ideal internal bank conductors; one aggregate PV + seven load branches; wire-loss heat.',
            'Explicit lumped heat capacities/radiators; inherited prescribed external heat is not an attitude-dependent heat budget.',
            'Source/derived/assumed declarations are accounting inputs, not independently verified hardware truth.'])
    return result


def edit_project(project, **changes):
    if type(project) is not SpacecraftProjectV3:
        raise TypeError('exact V3 project')
    if set(changes) - {'specification', 'requirements', 'title'}:
        raise ValueError('V2 edits require a general specification; V1 placement/area presets are not applicable')
    return replace(project, **{k: v for k, v in changes.items() if v is not None})
