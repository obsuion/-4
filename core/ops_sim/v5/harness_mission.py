"""Explicit mass-aware opt-in long mission, with independent owned hardware."""
from dataclasses import dataclass,replace
from .assembly import _identity
from .construction_mission import ConstructionMissionInputs,start_construction_mission,advance_construction_mission
from .construction_document import construction_input_digest
from .harness_mass import HarnessAugmentationInputs,compile_harness_mass
from .harness_hardware import compile_effective_hardware


@dataclass(slots=True)
class HarnessWork:
    compilation_calls: int = 0
    control_reserved_units: int = 0
    reconstruction_count: int = 0
    def validate(self,policy):
        policy.__post_init__()
        if any(type(v) is not int or v<0 for v in (self.compilation_calls,self.control_reserved_units,self.reconstruction_count)):raise ValueError('strict cumulative harness work')
        if self.compilation_calls>policy.max_runtime_compiles or self.control_reserved_units>policy.max_runtime_control_units:raise ValueError('cumulative harness quota exhausted')
        if self.control_reserved_units!=self.compilation_calls*policy.control_units_per_compile:raise ValueError('reset/inconsistent harness control ledger')
    def reserve_compile(self,policy):
        self.validate(policy)
        if self.compilation_calls+1>policy.max_runtime_compiles or self.control_reserved_units+policy.control_units_per_compile>policy.max_runtime_control_units:raise ValueError('HARNESS_COMPILATION_QUOTA')
        self.compilation_calls+=1;self.control_reserved_units+=policy.control_units_per_compile


@dataclass(frozen=True,slots=True)
class HarnessMissionInputs:
    coupled: ConstructionMissionInputs
    augmentation: HarnessAugmentationInputs
    mass_mode: str = 'MASS_AUGMENTED_CLOSED_V1'
    api: str = 'B46_HARNESS_COUPLED_MISSION_V1'
    def __post_init__(self):
        if type(self.coupled) is not ConstructionMissionInputs or type(self.augmentation) is not HarnessAugmentationInputs:raise TypeError('exact mass-aware input families required')
        _identity(self.mass_mode,'mass mode');_identity(self.api,'harness mission API')
        if self.mass_mode not in ('MASS_AUGMENTED_CLOSED_V1','UNASSEMBLED_HARNESS_CONTROL_V1') or self.api!='B46_HARNESS_COUPLED_MISSION_V1':raise ValueError('unsupported mass-aware mode/API')
        self.coupled.__post_init__();self.augmentation.__post_init__()
        compile_harness_mass(self.coupled.mission.assembly,self.coupled.configuration,self.augmentation)


@dataclass(frozen=True,slots=True)
class HarnessBinding:
    inputs: HarnessMissionInputs
    input_digest: str
    hardware: object
    work: HarnessWork
    @property
    def mass_scope(self):return ('MASS_CLOSED_WITHIN_RIGID_LUMPED_B46_MODEL' if self.hardware is not None else 'NOT_MASS_CLOSED_UNASSEMBLED_CONTROL')


def _compile(inputs):
    c=inputs.coupled;m=c.mission
    if inputs.mass_mode=='UNASSEMBLED_HARNESS_CONTROL_V1':
        compile_harness_mass(m.assembly,c.configuration,inputs.augmentation);return None
    return compile_effective_hardware(m.assembly,m.capabilities,m.actuator,c.configuration,inputs.augmentation)


def start_harness_mission(inputs,*,runtime_work=None,construction_work=None,harness_work=None):
    if type(inputs) is not HarnessMissionInputs:raise TypeError('mass-aware inputs required')
    inputs.__post_init__();policy=inputs.augmentation.policy
    work=HarnessWork() if harness_work is None else harness_work
    if type(work) is not HarnessWork:raise TypeError('harness work required')
    work.reserve_compile(policy);hardware=_compile(inputs)
    from .harness_document import harness_input_digest
    state=start_construction_mission(inputs.coupled,runtime_work=runtime_work,construction_work=construction_work)
    return replace(state,harness=HarnessBinding(inputs,harness_input_digest(inputs),hardware,work))


def guard_harness_state(state):
    binding=state.harness
    if type(binding) is not HarnessBinding:raise TypeError('owned harness binding required')
    from .harness_document import harness_input_digest
    if harness_input_digest(binding.inputs)!=binding.input_digest or construction_input_digest(binding.inputs.coupled)!=state.construction.input_digest:raise ValueError('stale augmentation/mission authority')
    binding.work.reserve_compile(binding.inputs.augmentation.policy)
    actual=_compile(binding.inputs)
    if actual!=binding.hardware:raise ValueError('foreign cached effective hardware/mass/tensor')


def advance_harness_mission(state,*,expected_action_id=None):
    if state.harness is None:raise ValueError('explicit mass-aware opt-in required')
    return advance_construction_mission(state,expected_action_id=expected_action_id)


def continue_harness_mission(state):
    while state.cursor<len(state.inputs.actions):state=advance_harness_mission(state)
    return state
