"""Bound opt-in B45 consumer; caches are derived, never persistence authority."""
from dataclasses import dataclass, replace, asdict
from .construction_coupling import ConstructionConfiguration, ConstructionCompilation, compile_construction
from .long_mission import LongMissionInputs, start_long_mission, advance_long_mission
from .long_mission_document import mission_input_digest
from .assembly import _identity


@dataclass(frozen=True, slots=True)
class ConstructionLimits:
    max_line_calls: int = 65536
    max_compilations: int = 256
    max_control_units: int = 2**26
    def __post_init__(self):
        for name,ceiling in (('max_line_calls',262144),('max_compilations',1024),('max_control_units',2**28)):
            value=getattr(self,name)
            if type(value) is not int or not 1<=value<=ceiling:raise ValueError('finite construction quota '+name)


@dataclass(slots=True)
class ConstructionWork:
    line_calls_reserved: int = 0
    line_calls_returned: int = 0
    line_calls_refused: int = 0
    line_work_unknown: int = 0
    compilation_calls: int = 0
    control_units: int = 0
    reconstruction_count: int = 0
    def validate(self,limits):
        limits.__post_init__()
        if any(type(v) is not int or v<0 for v in asdict(self).values()):raise ValueError('invalid construction work')
        if self.line_calls_reserved>limits.max_line_calls or self.compilation_calls>limits.max_compilations or self.control_units>limits.max_control_units:raise ValueError('cumulative construction quota')
        if self.line_calls_returned+self.line_calls_refused+self.line_work_unknown>self.line_calls_reserved:raise ValueError('construction line work exceeds reservations')
    def reserve_lines(self,count,limits):
        self.validate(limits)
        if self.line_calls_reserved+count>limits.max_line_calls:raise ValueError('CONSTRUCTION_LINE_QUOTA')
        self.line_calls_reserved+=count
    def reserve_compile(self,limits):
        self.validate(limits)
        if self.compilation_calls+1>limits.max_compilations or self.control_units+32768>limits.max_control_units:raise ValueError('CONSTRUCTION_COMPILATION_QUOTA')
        self.compilation_calls+=1;self.control_units+=32768


@dataclass(frozen=True, slots=True)
class ConstructionMissionInputs:
    mission: LongMissionInputs
    configuration: ConstructionConfiguration
    limits: ConstructionLimits = ConstructionLimits()
    api: str = 'B45_CONSTRUCTION_MISSION_V1'
    def __post_init__(self):
        if type(self.mission) is not LongMissionInputs or type(self.configuration) is not ConstructionConfiguration or type(self.limits) is not ConstructionLimits:raise TypeError('exact construction input families required')
        _identity(self.api,'construction API')
        if self.api!='B45_CONSTRUCTION_MISSION_V1':raise ValueError('unsupported construction API')
        self.mission.__post_init__();self.configuration.__post_init__();self.limits.__post_init__()
        compile_construction(self.mission.assembly,self.configuration)
        if self.configuration.thermal_network!=self.mission.simulation_inputs.spacecraft_configuration.thermal.network:raise ValueError('mission/configured thermal network must match')
        from .environment_forcing import _case
        if any(_case(p,False).thermal_inputs!=self.configuration.thermal_boundaries for p in self.mission.environment.profile):raise ValueError('explicit common thermal boundary binding required')


@dataclass(frozen=True, slots=True)
class ConstructionBinding:
    inputs: ConstructionMissionInputs
    input_digest: str
    compilation: ConstructionCompilation
    work: ConstructionWork


def start_construction_mission(inputs,*,runtime_work=None,construction_work=None):
    if type(inputs) is not ConstructionMissionInputs:raise TypeError('construction mission inputs required')
    inputs.__post_init__()
    work=ConstructionWork() if construction_work is None else construction_work
    if type(work) is not ConstructionWork:raise TypeError('construction work required')
    work.reserve_compile(inputs.limits)
    compilation=compile_construction(inputs.mission.assembly,inputs.configuration)
    from .construction_document import construction_input_digest
    state=start_long_mission(inputs.mission,runtime_work=runtime_work)
    return replace(state,construction=ConstructionBinding(inputs,construction_input_digest(inputs),compilation,work))


def guard_construction_state(state):
    if state.harness is not None:
        from .harness_mission import guard_harness_state
        guard_harness_state(state)
    binding=state.construction
    if type(binding) is not ConstructionBinding:raise TypeError('bound construction consumer required')
    from .construction_document import construction_input_digest
    if construction_input_digest(binding.inputs)!=binding.input_digest or mission_input_digest(binding.inputs.mission)!=state.input_digest:raise ValueError('stale coupling/mission identity')
    binding.work.reserve_compile(binding.inputs.limits)
    actual=compile_construction(state.inputs.assembly,binding.inputs.configuration)
    if actual!=binding.compilation:raise ValueError('stale cached construction geometry/authority')


def advance_construction_mission(state,*,expected_action_id=None):
    if state.construction is None:raise ValueError('explicit B45 opt-in required')
    return advance_long_mission(state,expected_action_id=expected_action_id)


def continue_construction_mission(state):
    while state.cursor<len(state.inputs.actions):state=advance_construction_mission(state)
    return state
