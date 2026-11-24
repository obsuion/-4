"""New effective hardware authority, never a forged AssemblyHardware3D."""
from dataclasses import dataclass
from .assembly_attitude_3d import compile_assembly_hardware_3d,admit_tensor
from .harness_mass import compile_harness_mass


@dataclass(frozen=True,slots=True)
class EffectiveAssemblyHardware:
    base_hardware: object
    configuration: object
    augmentation_inputs: object
    augmentation: object
    tensor_exact: tuple
    method: str = 'B46_DERIVED_FULL_TENSOR_EFFECTIVE_HARDWARE_V1'
    @property
    def design(self):return self.base_hardware.design
    @property
    def capabilities(self):return self.base_hardware.capabilities
    @property
    def actuator(self):return self.base_hardware.actuator
    @property
    def camera_body_axis(self):return self.base_hardware.camera_body_axis
    @property
    def panel_body_normal(self):return self.base_hardware.panel_body_normal
    @property
    def mass_properties(self):return self.augmentation.effective_mass_properties


def compile_effective_hardware(design,capabilities,actuator,configuration,augmentation):
    base=compile_assembly_hardware_3d(design,capabilities,actuator)
    mass=compile_harness_mass(design,configuration,augmentation)
    tensor,_=admit_tensor(mass.effective_mass_properties.inertia_com_body_kg_m2)
    return EffectiveAssemblyHardware(base,configuration,augmentation,mass,tensor)


def validate_effective_hardware(hardware):
    if type(hardware) is not EffectiveAssemblyHardware:raise TypeError('exact B46 effective hardware required')
    actual=compile_effective_hardware(hardware.design,hardware.capabilities,hardware.actuator,hardware.configuration,hardware.augmentation_inputs)
    if actual!=hardware:raise ValueError('foreign/stale supplied effective hardware/tensor')
    return hardware
