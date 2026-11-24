"""Fresh Task05C configurations and a shared prescribed version-7 workload.

No dependency on earlier demo fixtures. No change to accepted physical owners.
"""

from . import configuration as cfg
from . import ids
from .adcs import CommonFrameBoresightDirection
from .adcs_config import AgilePointingConfig, BoresightSlewTimeAnchor
from .campaign_contract import (ReleasedMSRequest, MSOpportunity, CampaignForcing,
    BoundaryKnowledgeMode, RollingPolicy, MSCampaignProgram)
from .checkpoint import CheckpointState
from .communications import ServiceableGroundContact
from .comparison_manifest import manifest, derive_hardware
from .context import SimulationInputs, SimulationContext
from .controller_state import ControllerState
from .coupled_downlink import DownlinkTransmitterConfig
from .data_delivery import GroundDataDeliveryState
from .degradation_config import BatteryAgeingModelConfig
from .diagnostics import Diagnostics
from .imaging_feasibility import ObservationAcquisitionCandidate
from .integration_time import IntegrationPolicy
from .knowledge import GroundKnowledgeState
from .manifest import ModelManifest
from .mission import MissionState
from .ms_acquisition import InitialAttitudeEvidence
from .ms_product import MSFootprint, MSProductSpec, MSAcquisitionPlan, size_ms_grid, REQUIRED_MS_CHANNELS
from .observation import ImagingRequest, ObservationOpportunity, ObservationPointing
from .observation_feasibility import ObservationManeuverCandidate
from .operational_protection import ProtectionPolicy, StandbyInputs
from .parameters import ScalarParameter
from .payload import OpticalAcquisitionInput, OpticalAcquisitionChannelSelection
from .payload_config import OpticalAcquisitionConfig
from .power_loads import PowerLoadBreakdown
from .provenance import ParameterProvenance, ProvenanceClass, ProvenanceStatus
from .run_config import NumericalConfig, EnvironmentConfig, FlightRulesConfig, ScenarioConfig
from .state import (SpacecraftState, BatteryState, PropulsionState, ThermalState, ThermalNodeState,
    DegradationState, BatteryDegradationState, SolarDegradationState, OnboardOperationsState, DataStorageState, OperationalMode, FDIRState)
from .thermal import ThermalIntervalInputs, ThermalNodeBoundaryInput
from .thermal_config import ThermalNodeConfig, ThermalNetworkConfig
from .thermal_coupling import ThermalHeatSourceInputs, ThermalNodeHeatSourceInput
from .thermal_routing import ComponentHeatRoute, ComponentHeatRoutingConfig, ElectricalLoadComponent
from .world import CommonWorld


HORIZON = 3600
ADMISSION_END = 2700
CONTACTS_S1 = ((900,910),(1200,1210),(2700,2710),(3000,3010),(3300,3310))
CONTACTS_S2 = (CONTACTS_S1[0],CONTACTS_S1[2],CONTACTS_S1[4])
COMMON_ASSUMPTIONS = (
    "Prescribed synthetic 3600 s experiment at normalized 630 km; no orbital, RF or real-station reconstruction.",
    "Six 10 km cross-track by 30 km along-track rectangles; 60 s acquisitions, nadir and held identical boresight. Swath inactive.",
    "Admission ends at 2700 s; drain ends at 3600 s. All six requests remain in priority denominator 12; common acquisition windows 300 s.",
    "Illumination false [0,1800), true [1800,3600); incidence zero. No solar ageing; no orbit-average interpretation.",
    "Initial energy half working capacity; retention 1, throughput 0, empty custody; 293.15 K on all three nodes.",
    "Common thermal normalization: each node 50000 J/K, emissivity 0.8, area 0.2 m2, sink 250 K, no links/external absorbed heat.",
    "Common operating 270..320 K, survival 250..340 K. All electrical load retained as heat in bus except payload; battery conversion heat routed by existing owner.",
    "All temperatures observed at idealized zero-latency boundaries; estimate tuple explicitly empty, no hidden truth forecasting.",
    "ADCS assumed 45 deg limit, 5 s settling and linear 0 deg/0 s to 90 deg/180 s envelope; held pointing makes slew inactive.",
    "Battery calendar/cycle coefficients zero for this short screening; no lifetime prediction, delta-v zero and no propulsion.",
    "MS-only counterfactual, raw integer samples, all J bands charged. No PAN, compression, overhead or radiometric-equivalence claim.",
    "P_ref is mapped to separate imaging/transmit increments by assumption, not calibrated or a conservative upper bound; baseline 12 W.",
    "P80-inspired aggregate limits only: converter voltage, individual channels, mounts and deployment remain unverified.",
)


def parameter(name, units, value, *, source=None, derivation=None, rationale=None):
    classification = (ProvenanceClass.DERIVED_VALUE if derivation else
        ProvenanceClass.PUBLIC_SPECIFICATION if source else ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION)
    return ScalarParameter(value, ParameterProvenance(ids.ParameterId(name),classification,units,
        () if source is None else (ids.SourceRecordId(source.lower()),),
        ProvenanceStatus.VERIFIED if source else ProvenanceStatus.TO_RESEARCH,
        rationale=rationale or "Task05C declared normalized screening assumption; see COMMON_ASSUMPTIONS and source manifest.",
        derivation=derivation))


def build_inputs_program(identity, scenario="S1", *, level=0, mode_factor=1., hardware_manifest=None):
    if type(scenario) is not str or scenario not in ("S1","S2"):
        raise ValueError("unknown shared scenario")
    m = manifest() if hardware_manifest is None else hardware_manifest
    h = derive_hardware(m,identity,mode_factor)
    p = parameter
    sub = lambda name: ids.SubsystemConfigurationId("task05c-"+name)
    derived = "Counterfactual formula in comparison_manifest.derive_hardware; source plus explicitly declared assumptions"
    battery = cfg.BatteryConfig(sub("battery"),p("eps.battery.nominal-energy","Wh",h["working_energy_wh"],source="BP8",derivation="packs * 86 Wh recommended window, once"),
        p("eps.battery.charge-efficiency","1",h["charge_efficiency"]),p("eps.battery.discharge-efficiency","1",h["discharge_efficiency"]),
        p("eps.battery.max-charge-input-power","W",h["charge_bus_w"],source="BP8",derivation=derived),
        p("eps.battery.max-discharge-output-power","W",h["discharge_bus_w"],source="BP8",derivation=derived))
    eps = cfg.EPSConfig(sub("eps"),battery,cfg.SolarArrayConfig(sub("array"),
        p("eps.solar-array.nominal-generation","W",h["solar_w"],source="TSP",derivation="arrays * 45 W illuminated reference")))
    src = "JSS56" if identity[0] == "J" else "DMAC-HIRAIS"
    optical = OpticalAcquisitionConfig(
        p("payload.optical.reference-nadir-swath-width","m",h["swath_m"],source=src,derivation="native swath * 630 / native altitude; no second scaling"),
        p("payload.optical.panchromatic-reference-sample-spacing","m",1.,rationale="Unused positive PAN placeholder; PAN unsupported in this configuration"),
        p("payload.optical.multispectral-reference-sample-spacing","m",h["sampling_m"],source=src,derivation="native sampling * 630 / native altitude, one binary64 conversion without decimal rounding"),
        p("payload.optical.multispectral-band-count","1",len(h["channels"]),source=src),
        p("payload.optical.acquisition-bits-per-sample","bit/sample",h["bits_per_sample"],source=src),
        p("payload.optical.acquisition-power","W",h["mode_power_w"],rationale="ASSUMED P_ref times mode factor; not measured or bounded mode power"),False)
    payload = cfg.PayloadConfig(sub("payload"),cfg.PayloadFamily.OPTICAL_EO,(cfg.PayloadMode.MULTISPECTRAL,),optical)
    adcs = AgilePointingConfig(p("adcs.pointing.maximum-view-angle-from-nadir","deg",45.),
        p("adcs.pointing.post-slew-settling-time","s",5.),tuple(BoresightSlewTimeAnchor(ids.ADCSSlewAnchorId(n),
            p(f"adcs.slew-envelope.{n}.angular-separation","deg",angle),
            p(f"adcs.slew-envelope.{n}.elapsed-time","s",seconds)) for n,angle,seconds in (("zero",0.,0.),("end",90.,180.))))
    node_ids = tuple(ids.ThermalNodeId(n) for n in ("bus","battery","payload"))
    nodes = tuple(ThermalNodeConfig(n,*(p(f"thermal.node.{n.value}.{key}",unit,val) for key,unit,val in (
        ("heat-capacity","J/K",50000.),("emissivity","1",.8),("radiating-area","m^2",.2),
        ("operating-min-temperature","K",270.),("operating-max-temperature","K",320.),
        ("survival-min-temperature","K",250.),("survival-max-temperature","K",340.)))) for n in node_ids)
    network = ThermalNetworkConfig(nodes,(),*node_ids)
    ageing = BatteryAgeingModelConfig(*(p("degradation.battery."+key,unit,val) for key,unit,val in (
        ("reference-temperature","K",293.15),("calendar-damage-rate-at-reference","1/s",0.),
        ("calendar-activation-energy","J/mol",0.),("cycling-damage-per-normalized-throughput-at-reference","1",0.),
        ("cycling-activation-energy","J/mol",0.))))
    degradation = cfg.DegradationConfig(sub("degradation"),
        p("degradation.battery.initial-usable-capacity-retention","1",1.),p("degradation.solar.initial-generation-retention","1",1.),
        p("degradation.battery.initial-energy-throughput","Wh",0.),ageing)
    configuration = cfg.SpacecraftConfiguration(ids.SpacecraftConfigurationId("task05c-"+identity.lower()),
        "Task05C counterfactual "+identity,1,eps,payload,
        cfg.StorageConfig(sub("storage"),p("storage.usable-capacity","GB",h["storage_gb"],source=src,derivation="published decimal Gbit / 8 * assumed available fraction")),
        cfg.CommunicationsConfig(sub("link"),p("communications.nominal-downlink-data-rate","bit/s",h["rate_bps"],
            source="KGS" if identity[0] == "J" else src,derivation="published Mbit/s * 1e6 * assumed useful fraction")),
        cfg.ADCSConfig(sub("adcs"),adcs),cfg.ThermalConfig(sub("thermal"),network),degradation,
        cfg.PropulsionConfig(sub("propulsion"),p("propulsion.initial-delta-v","m/s",0.)),cfg.OBCConfig(sub("obc")))
    # Scenario identity is common: S1/S2 differ only by the program contact tuple.
    numerics = NumericalConfig(ids.NumericalConfigId("task05c-physical-duration"),60,1,60)
    env = EnvironmentConfig(ids.EnvironmentId("task05c-prescribed"))
    rules = FlightRulesConfig(ids.FlightRulesId("task05c-normalized-protection"))
    scen = ScenarioConfig(ids.ScenarioId("task05c-common-workload"))
    world = CommonWorld(ids.WorldId("task05c-common-world"),scen.scenario_id,HORIZON,())
    model = ModelManifest(ids.ModelManifestId("task05c-"+identity.lower()),1,configuration.configuration_id,
        numerics.configuration_id,env.environment_id,rules.flight_rules_id,scen.scenario_id,world.world_id,
        ids.ControllerId("accepted-ms7-rolling-policy"))
    inputs = SimulationInputs(configuration,numerics,env,rules,scen,world,model)
    state = SpacecraftState(BatteryState(h["initial_energy_wh"]),PropulsionState(0.),
        ThermalState(tuple(ThermalNodeState(n,293.15) for n in node_ids)),
        DegradationState(BatteryDegradationState(1.,0.),SolarDegradationState(1.)),
        OnboardOperationsState(OperationalMode.STANDBY,FDIRState.NORMAL,None,None,None,None),DataStorageState(()))
    context = SimulationContext(0,inputs,state,GroundKnowledgeState(None,()),GroundDataDeliveryState((),()),
        MissionState((),(),(),None,(),()),ControllerState(model.controller_id,None,0),Diagnostics(0))
    direction = CommonFrameBoresightDirection(ids.ADCSBoresightFrameId("task05c-prescribed-common-frame"),0.,0.,1.)
    initial = InitialAttitudeEvidence(0,direction,"Assumed settled at origin; held common pointing between all actions")
    requests, opportunities = [], []
    for i,release in enumerate((0,300,600,1800,2100,2400)):
        request = ImagingRequest(ids.ImagingRequestId(f"task05c-r{i}"),ids.GroundTargetId(f"task05c-target{i}"),float(3-i%3))
        footprint = MSFootprint(f"task05c-region{i}",10000.,30000.)
        product = MSProductSpec(1,request,f"task05c-capture{i}",REQUIRED_MS_CHANNELS,footprint,release,release+300,6.5,6.5,1500 if i<3 else 3500)
        sizing = size_ms_grid(footprint,h["sampling_m"],h["sampling_m"],tuple(h["channels"]),h["bits_per_sample"])
        association = MSAcquisitionPlan(1,request,product.capture_group,sizing,"Assumed MS-only raw capture; all declared instrument channels charged")
        opportunity = ObservationOpportunity(ids.ObservationOpportunityId(f"task05c-op{i}"),request.request_id,release,release+300,60,ObservationPointing(0.,0.))
        candidate = ObservationAcquisitionCandidate(ObservationManeuverCandidate(opportunity,direction),
            OpticalAcquisitionInput(footprint.width_m,footprint.length_m,60,OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY))
        requests.append(ReleasedMSRequest(product,release))
        opportunities.append(MSOpportunity(candidate,association))
    contacts = tuple(ServiceableGroundContact(ids.GroundContactId(f"task05c-contact-{start}"),ids.GroundStationId("task05c-synthetic-station"),start,end)
        for start,end in (CONTACTS_S1 if scenario == "S1" else CONTACTS_S2))
    routing = ComponentHeatRoutingConfig(tuple(ComponentHeatRoute(component,node_ids[2] if component is ElectricalLoadComponent.PAYLOAD else node_ids[0],
        p(f"thermal.routing.{component.value}.retained-heat-fraction","1",1.)) for component in ElectricalLoadComponent))
    boundaries = ThermalIntervalInputs(tuple(ThermalNodeBoundaryInput(n,250.) for n in node_ids))
    heat = ThermalHeatSourceInputs(tuple(ThermalNodeHeatSourceInput(n,0.,0.,0.,0.) for n in node_ids))
    forcing = tuple(CampaignForcing(start,end,StandbyInputs(PowerLoadBreakdown(m["assumptions"]["baseline_w"]["value"],0.,0.,0.,0.,0.,0.),
        sunlit,0.,routing,boundaries,heat,None,"12 W normalized essential baseline; no external absorbed heat or degradation forcing"),
        DownlinkTransmitterConfig(p("communications.transmitter-electrical-power","W",h["mode_power_w"],rationale="ASSUMED mutually exclusive transmitter proxy P_ref * factor")))
        for start,end,sunlit in ((0,1800,False),(1800,HORIZON,True)))
    protection = ProtectionPolicy(node_ids,node_ids[:2],node_ids[:2],node_ids[0],tuple(ElectricalLoadComponent),
        "all-declared-standby-loads","next-admissible-sampled-boundary","Normalized shared sampled protection, all standby demand essential",
        "ASSUMED transmitter uses bus node temperature; no hardware calibration")
    policy = RollingPolicy(1,3600,300,3,32,64,4096)
    knowledge = BoundaryKnowledgeMode("idealized-boundary-telemetry-v1",node_ids,(),
        "All three node temperatures observed exactly at received boundaries; no unobserved temperature estimates needed. Idealized zero latency.")
    program = MSCampaignProgram(7,CheckpointState.from_context(context),initial,tuple(requests),tuple(opportunities),contacts,forcing,
        protection,IntegrationPolicy(level),policy,knowledge,COMMON_ASSUMPTIONS)
    return inputs, program
