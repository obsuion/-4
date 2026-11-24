"""Pinned snapshot record constructors. No payload-selected import/attribute lookup."""
from dataclasses import fields
from ._experiment_types import RECORD_FIELDS as BASE_RECORD_FIELDS, ENUM_TYPES as BASE_ENUM_TYPES
from .assembly import (AssemblyMassProperties, MassCoverage, MountPose, UniformCuboid)
from .assembly_attitude import (ComponentAxisBinding)
from .assembly_attitude_3d import (AssemblyHardware3D, BodyAttitude3D, NetTorqueActuatorPolicy)
from .assembly_choices import (AssemblyDesign, InstallationBox, InstallationRegion, PhysicalInstance, PlacementChoice, Selection)
from .assembly_interfaces import (ElectricalPort, HarnessMassDeclaration, LineConnection, OperatingPoint, ThermalBinding, WireProperties)
from .assembly_slew_3d import (SpatialEulerSample)
from .campaign_contract import (ResourceObservation)
from .checkpoint import (ThermalNodeStateSnapshot)
from .command_controller import (CommandDecision)
from .command_estimation import (CommandForecastResult, CommandIntent, CommandWork, EstimatedCommandState, Reconciliation)
from .communications import (ServiceableGroundContact)
from .construction_contact import (ConstructionContactEvaluation, ConstructionContactForcing)
from .construction_coupling import (CompiledBranch, ConstructionCompilation, ConstructionConfiguration, ReceivingBranch)
from .construction_mission import (ConstructionWork)
from .construction_physics import (BranchOperatingResult, ConstructionEPSResult, ConstructionPhysicalResult)
from .contact_execution import (ConsumedContacts, ContactAttempt, ContactOutcome, ContactSegment, ContactTrace, RecordService)
from .coupled_downlink import (CoupledDownlinkInputs, DownlinkTransmitterConfig)
from .data_delivery import (CompletedAcquisitionDelivery, DownlinkTransferProgress)
from .degradation import (BatteryDegradationSubstepTransition, SolarDegradationForcingInput, SolarDegradationTransition)
from .design_trade_physics import (ElectricalLineResult, WireSpec)
from .engine import (CoupledPhysicalSubstepResult)
from .eps import (BatterySubstepTransition)
from .eps_capability import (BatteryCapacityReconciliationResult, EPSCapabilityResult)
from .eps_system import (EPSSubstepResult)
from .frames import (CartesianDirection, CartesianPosition, CartesianState, CartesianVelocity)
from .harness_hardware import (EffectiveAssemblyHardware)
from .harness_mass import (HarnessAugmentationInputs, HarnessMassCompilation, HarnessMassPolicy, MassContribution, RouteMassDistribution, SpatialMassPoint)
from .harness_mission import (HarnessWork)
from .harness_slew import (EffectiveSpatialSlew)
from .ids import (AcquisitionDataRecordId, GroundContactId, GroundStationId, GroundTargetId, ImagingRequestId, ObservationOpportunityId, ParameterId, SourceRecordId, ThermalLinkId, ThermalNodeId)
from .integration_time import (RationalSeconds)
from .long_mission import (EnvironmentActionOutcome, LongMissionAction, MissionContactForcing, MissionPhysicalCut, RuntimeWork)
from .long_nominal_provider import (NominalWork)
from .mission_diagnosis import (DiagnosisFinding, EvidenceReference, MissionDiagnosis)
from .mission_environment import (MissionPointObservation)
from .ms_product import (MSAcquisitionEvidence, MSAcquisitionPlan, MSFootprint, MSGridSizing, MSProductAssessment)
from .observation import (ImagingRequest)
from .onboard_data import (OnboardAcquisitionDataRecord)
from .operational_protection import (StandbyInputs)
from .orbit_config import (FrameDefinition, GeometryInstant, ReferenceEllipsoid, TTEpoch, UniformRotationDefinition)
from .orbit_geometry import (GroundPointDefinition, GroundPointGeometry)
from .orbit_visibility import (GroundVisibilityPolicy, GroundVisibilityResult)
from .parameters import (ScalarParameter)
from .power_loads import (PowerLoadBreakdown)
from .provenance import (ParameterProvenance)
from .rolling_controller import (RollingDecision)
from .rolling_execution import (CommittedCommand)
from .rolling_knowledge import (IssuedCommand, ReceivedKnowledge, ReceivedObservation)
from .rolling_physics import (ConstructionAdapter, ConstructionAdapterInputs, HarnessAdapter, HarnessAdapterInputs, PhysicalInputs)
from .solar import (SolarGenerationResult)
from .substepped_execution import (ActionAccounting, PhysicalSample, SubstepAvailability)
from .thermal import (ThermalIntervalInputs, ThermalLinkHeatFlow, ThermalNodeBoundaryInput, ThermalNodeTransition, ThermalSubstepResult)
from .thermal_config import (ThermalLinkConfig, ThermalNetworkConfig, ThermalNodeConfig)
from .thermal_coupling import (EPSThermalSubstepResult, ThermalHeatSourceInputs, ThermalNodeHeatLedger, ThermalNodeHeatSourceInput)
from .thermal_routing import (ComponentHeatRoute, ComponentHeatRoutingConfig)
from .operational_protection import (ActionKind)
from .orbit_config import (FrameKind)
from .orbit_visibility import (BodyLocation, ElevationStatus, GroundVisibilityStatus, LineOfSightReason, LineOfSightStatus, SegmentMinimumLocation)
from .payload import (OpticalAcquisitionChannelSelection)
from .provenance import (ProvenanceClass, ProvenanceStatus)
from .state import (FDIRState, OperationalMode)
from .thermal_routing import (ElectricalLoadComponent)
RECORD_FIELDS = dict(BASE_RECORD_FIELDS)
RECORD_FIELDS.update({
    AssemblyMassProperties: ('body_frame_id', 'total_mass_kg', 'center_body_m', 'inertia_com_body_kg_m2'),
    MassCoverage: ('paths',),
    MountPose: ('mount_id', 'choice_id', 'body_frame_id', 'local_frame_id', 'origin_body_m', 'rotation_body_from_local', 'occupied_slots'),
    UniformCuboid: ('definition_id', 'local_frame_id', 'mass_kg', 'size_m', 'center_local_m', 'mass_distribution'),
    ComponentAxisBinding: ('role', 'component_id', 'local_frame_id', 'local_axis', 'assumption'),
    AssemblyHardware3D: ('design', 'assembly_digest', 'mass_properties', 'camera_body_axis', 'panel_body_normal', 'tensor_exact', 'spd_leading_minors', 'symmetry_residual_kg_m2', 'symmetry_allowance_kg_m2', 'actuator', 'capabilities', 'method'),
    BodyAttitude3D: ('body_frame_id', 'inertial_frame', 'at_seconds', 'quaternion', 'rest_since_seconds', 'method'),
    NetTorqueActuatorPolicy: ('torque_limits_nm', 'rate_limits_rad_s', 'electronics_power_w', 'drive_efficiency', 'settling_seconds', 'body_momentum_limits_nms', 'assumption', 'mode'),
    AssemblyDesign: ('body_frame_id', 'definitions', 'instances', 'choices', 'selections', 'allowed_regions', 'reserved_regions', 'clearance_m'),
    InstallationBox: ('lower_m', 'upper_m'),
    InstallationRegion: ('region_id', 'box'),
    PhysicalInstance: ('instance_id', 'definition_id', 'mass_coverage'),
    PlacementChoice: ('choice_id', 'definition_id', 'allowed_instance_ids', 'pose', 'envelope', 'allowed_region_id', 'exclusive'),
    Selection: ('instance_id', 'choice_id'),
    ElectricalPort: ('port_id', 'instance_id', 'local_frame_id', 'position_local_m', 'role'),
    HarnessMassDeclaration: ('status', 'coverage', 'included_instance_id'),
    LineConnection: ('line_id', 'source_port_id', 'load_port_id', 'waypoints_body_m', 'slack_m', 'wire', 'operating_point', 'mass', 'wire_loss_node_id'),
    OperatingPoint: ('mode', 'source_voltage_v', 'power_w'),
    ThermalBinding: ('instance_id', 'node_id', 'lumping_group'),
    WireProperties: ('cross_section_m2', 'resistivity_ohm_m', 'density_kg_m3', 'connector_resistance_ohm', 'connector_count', 'connector_mass_kg', 'current_limit_a', 'max_drop_v'),
    SpatialEulerSample: ('offset_seconds', 'theta_rad', 'omega_body_rad_s', 'alpha_body_rad_s2', 'momentum_body_nms', 'gyro_torque_nm', 'net_torque_nm', 'kinetic_j', 'mechanical_power_w', 'phase'),
    ResourceObservation: ('battery_energy_wh', 'battery_retention', 'solar_retention', 'throughput_wh', 'observed_temperatures', 'operational_mode', 'fdir_state', 'critical_energy_since_seconds'),
    ThermalNodeStateSnapshot: ('node_id', 'temperature_k'),
    CommandDecision: ('decision_id', 'view_identity', 'knowledge_age_seconds', 'selected_suffix', 'explanation', 'forecasts', 'rejected', 'controller_method', 'estimate_identity', 'assumption'),
    CommandForecastResult: ('view_identity', 'suffix', 'status', 'reason', 'predicted_end_seconds', 'predicted_energy_wh', 'predicted_temperatures', 'predicted_records', 'predicted_partial_bits', 'predicted_delivery_acks', 'predicted_outcomes', 'runtime_work', 'construction_work', 'harness_work', 'catchup_outcome', 'estimate'),
    CommandIntent: ('command_id', 'model_identity', 'action', 'issued_at_seconds', 'expected_end_seconds', 'expected_attitude', 'profile_identity', 'prediction_status'),
    CommandWork: ('forecast_invocations', 'forecast_physical_reserved', 'actual_physical_reserved', 'harness_compiles', 'construction_line_reserved', 'nominal_force_reserved', 'control_reserved', 'output_bytes', 'output_capacity_peak_bytes', 'output_admission_events', 'publication_reencoded_bytes', 'publication_reuse_hits', 'publication_digests', 'publication_reuse_mode', 'publication_reuse_seen', 'reconstructions', 'decisions', 'invocation_records', 'estimator_invocations', 'estimator_command_propagations_reserved', 'estimator_command_propagations_completed', 'estimator_method'),
    EstimatedCommandState: ('method', 'view_identity', 'model_identity', 'source_packet_id', 'observed_at_seconds', 'received_at_seconds', 'estimated_at_seconds', 'observation_age_seconds', 'assumption', 'command_ids', 'status', 'reason', 'attitude', 'energy_wh', 'temperatures_k', 'expected_records', 'expected_partial_bits', 'expected_receipts', 'propagation_outcomes', 'runtime_work', 'construction_work', 'harness_work'),
    Reconciliation: ('command_id', 'packet_id', 'observed_at_seconds', 'received_at_seconds', 'observed_status', 'observed_reason', 'conclusion', 'expected_end_seconds', 'observed_end_seconds', 'pose_exactly_matches_prediction'),
    ServiceableGroundContact: ('contact_id', 'ground_station_id', 'start_time_seconds', 'end_time_seconds'),
    ConstructionContactEvaluation: ('start_bits', 'duration_bits', 'rate', 'standby', 'selected', 'parts', 'trace', 'unmet_w', 'evaluated'),
    ConstructionContactForcing: ('legacy_forcing', 'evaluations'),
    CompiledBranch: ('line_id', 'source_body_m', 'load_body_m', 'polyline_length_m', 'wire', 'heat_node_id', 'mass_status'),
    ConstructionCompilation: ('configuration', 'configuration_digest', 'branches', 'conductor_mass_kg', 'connector_mass_kg', 'mass_scope'),
    ConstructionConfiguration: ('assembly_digest', 'body_frame_id', 'bus_instance_id', 'bus_voltage_v', 'bus_current_limit_a', 'pv_source_voltage_v', 'pv_line_id', 'ports', 'lines', 'receiving', 'thermal_bindings', 'thermal_network', 'thermal_boundaries', 'rationale', 'topology', 'generation_model', 'regulator_loss_model'),
    ReceivingBranch: ('component', 'line_id'),
    ConstructionWork: ('line_calls_reserved', 'line_calls_returned', 'line_calls_refused', 'line_work_unknown', 'compilation_calls', 'control_units', 'reconstruction_count'),
    BranchOperatingResult: ('line_id', 'component', 'electrical', 'heat_node_id'),
    ConstructionEPSResult: ('compilation_digest', 'source_solar', 'receiving_loads', 'branches', 'source_generation_w', 'delivered_generation_w', 'receiving_load_w', 'source_load_w', 'pv_wire_loss_w', 'receiving_wire_loss_w', 'battery', 'fully_served', 'regulator_conversion_loss_w'),
    ConstructionPhysicalResult: ('physical', 'electrical', 'receiving_retained_heat_w', 'wire_heat_w', 'mechanical_heat_adjustments_w'),
    ConsumedContacts: ('contacts',),
    ContactAttempt: ('record_id', 'availability', 'predicted_trace', 'evaluated_eps_substeps', 'evaluated_thermal_substeps'),
    ContactOutcome: ('contact', 'requested_order', 'bitrate_bps', 'subdivision_level', 'services', 'attempts', 'segments', 'accounting', 'denied_record_id', 'operational_mode', 'fdir_state', 'critical_energy_since_seconds', 'recovered'),
    ContactSegment: ('record_id', 'trace', 'accounting'),
    ContactTrace: ('start_offset', 'end_offset', 'denominator', 'samples'),
    RecordService: ('record', 'progress_before_bits', 'transmitted_bits', 'progress_after_bits', 'start_offset', 'end_offset', 'completed', 'completion_time_seconds'),
    CoupledDownlinkInputs: ('transmitter', 'baseline_loads', 'sunlit', 'incidence_angle_deg', 'routing_config', 'thermal_inputs', 'external_heat_sources', 'solar_degradation_forcing'),
    DownlinkTransmitterConfig: ('electrical_power_w',),
    CompletedAcquisitionDelivery: ('record', 'completing_contact'),
    DownlinkTransferProgress: ('record_id', 'transmitted_equivalent_bits'),
    BatteryDegradationSubstepTransition: ('start_usable_capacity_retention', 'end_usable_capacity_retention', 'start_cumulative_energy_throughput_wh', 'throughput_increment_wh', 'end_cumulative_energy_throughput_wh', 'representative_temperature_k', 'calendar_temperature_acceleration', 'cycling_temperature_acceleration', 'calendar_damage', 'cycling_damage', 'total_damage', 'dt_seconds', 'duration'),
    SolarDegradationForcingInput: ('retention_loss',),
    SolarDegradationTransition: ('start_generation_retention', 'retention_loss', 'end_generation_retention'),
    ElectricalLineResult: ('current_a', 'voltage_drop_v', 'loss_w', 'source_power_w', 'delivered_power_w', 'load_voltage_v', 'resistance_ohm', 'harness_mass_kg'),
    WireSpec: ('one_way_length_m', 'cross_section_m2', 'resistivity_ohm_m', 'density_kg_m3', 'connector_resistance_ohm', 'connector_count', 'connector_mass_kg', 'current_limit_a', 'max_drop_v'),
    CoupledPhysicalSubstepResult: ('eps_result', 'thermal_coupling_result', 'battery_degradation_result', 'solar_degradation_result', 'eps_capability_result', 'battery_capacity_reconciliation_result'),
    BatterySubstepTransition: ('start_energy_wh', 'end_energy_wh', 'generation_w', 'load_w', 'charge_input_w', 'discharge_output_w', 'curtailed_generation_w', 'unmet_load_w', 'conversion_loss_wh', 'dt_seconds', 'duration'),
    BatteryCapacityReconciliationResult: ('proposed_end_energy_wh', 'end_capacity_retention', 'end_usable_capacity_wh', 'unavailable_energy_wh', 'authoritative_end_energy_wh'),
    EPSCapabilityResult: ('battery_capacity_retention', 'battery_usable_capacity_wh', 'solar_generation_retention', 'solar_nominal_generation_capability_w'),
    EPSSubstepResult: ('solar', 'loads', 'battery'),
    CartesianDirection: ('frame', 'instant', 'components'),
    CartesianPosition: ('frame', 'instant', 'components_m'),
    CartesianState: ('position', 'velocity'),
    CartesianVelocity: ('frame', 'instant', 'components_m_per_s'),
    EffectiveAssemblyHardware: ('base_hardware', 'configuration', 'augmentation_inputs', 'augmentation', 'tensor_exact', 'method'),
    HarnessAugmentationInputs: ('assembly_digest', 'construction_digest', 'body_frame_id', 'routes', 'policy', 'method'),
    HarnessMassCompilation: ('input_digest', 'construction_digest', 'base_mass_properties', 'effective_mass_properties', 'contributions', 'added_mass_exact_kg', 'effective_mass_exact_kg', 'effective_center_exact_m', 'effective_tensor_exact_kg_m2', 'route_closure', 'tensor_as_binary64', 'spd_leading_minors', 'mass_scope', 'method'),
    HarnessMassPolicy: ('max_contributions', 'max_fraction_bits', 'max_runtime_compiles', 'control_units_per_compile', 'max_runtime_control_units'),
    MassContribution: ('contribution_id', 'line_id', 'kind', 'coverage', 'mass_kg', 'center_body_m', 'intrinsic_tensor_body_kg_m2', 'endpoints_body_m'),
    RouteMassDistribution: ('line_id', 'geometry_digest', 'slack_point', 'connector_points', 'rationale', 'slack_model'),
    SpatialMassPoint: ('frame_id', 'coordinates_m', 'instance_id', 'frame_kind'),
    HarnessWork: ('compilation_calls', 'control_reserved_units', 'reconstruction_count'),
    EffectiveSpatialSlew: ('hardware', 'initial', 'axis_body', 'theta_rad', 'acceleration_rad_s2', 'acceleration_seconds', 'peak_rate_rad_s', 'effective_inertia_kg_m2', 'unit_axis_abs_upper', 'inertia_axis_abs_upper', 'gyro_coefficients_exact', 'whole_torque_abs_upper_nm', 'whole_rate_abs_upper_rad_s', 'whole_body_momentum_abs_upper_nms', 'duration_seconds', 'rest_start_offset_seconds', 'method'),
    AcquisitionDataRecordId: ('value',),
    GroundContactId: ('value',),
    GroundStationId: ('value',),
    GroundTargetId: ('value',),
    ImagingRequestId: ('value',),
    ObservationOpportunityId: ('value',),
    ParameterId: ('value',),
    SourceRecordId: ('value',),
    ThermalLinkId: ('value',),
    ThermalNodeId: ('value',),
    RationalSeconds: ('numerator', 'denominator'),
    EnvironmentActionOutcome: ('action_id', 'kind', 'status', 'reason', 'start_seconds', 'end_seconds', 'geometry', 'cuts', 'contact_outcomes', 'acquired_record', 'acquisition_plan', 'attitude', 'accounting', 'slew', 'contact_forcing', 'continuous_geometry', 'failure_diagnostic'),
    LongMissionAction: ('action_id', 'kind', 'point_id', 'duration_seconds', 'until_seconds', 'product_id'),
    MissionContactForcing: ('start_seconds', 'end_seconds', 'source_support_indices', 'incidence_angle_deg', 'camera_inertial', 'panel_inertial', 'transmitter_inputs', 'idle_inputs', 'contact_id'),
    MissionPhysicalCut: ('start_seconds', 'end_seconds', 'source_support_indices', 'incidence_angle_deg', 'camera_inertial', 'panel_inertial', 'kinetic_start_j', 'kinetic_end_j', 'actuator_draw_w', 'heat_adjustment_w', 'part', 'pose_quaternion', 'euler_midpoint', 'kinetic_start_exact_j', 'kinetic_end_exact_j'),
    RuntimeWork: ('output_control_units', 'runtime_entries', 'nominal_force_reserved', 'nominal_force_completed', 'nominal_control_units', 'index_control_units', 'nominal_unknown_events', 'upstream_entries', 'nominal_orbit_queries', 'point_geometry_queries', 'physical_reserved_calls', 'physical_completed_calls', 'reconstruction_count', 'geometry_queries', 'geometry_operations', 'geometry_control_units', 'contact_work_unknown_events', 'physical_work_unknown_events', 'spatial_reserved_units'),
    NominalWork: ('queries', 'cache_reads', 'cache_records', 'full_steps', 'tail_steps', 'force_reserved', 'force_completed', 'control_reserved', 'unknown_primitive_events'),
    DiagnosisFinding: ('finding_id', 'scope', 'category', 'decision_id', 'action_id', 'request_id', 'at_seconds', 'owner_reason', 'conclusion', 'evidence'),
    EvidenceReference: ('owner_type', 'record_id', 'field_path', 'value', 'units'),
    MissionDiagnosis: ('method', 'root_identity', 'model_identity', 'assembly_identity', 'construction_identity', 'controller_method', 'estimation_method', 'boundary_commands', 'findings'),
    MissionPointObservation: ('point_id', 'requested_seconds', 'evaluated_instant', 'rounding_seconds', 'geometry', 'visibility', 'station_available', 'rf_admitted', 'nominal_rate_bps', 'service_assumption', 'mode'),
    MSAcquisitionEvidence: ('record', 'plan'),
    MSAcquisitionPlan: ('version', 'request', 'capture_group', 'sizing', 'capability_rationale'),
    MSFootprint: ('region_id', 'width_m', 'length_m'),
    MSGridSizing: ('version', 'footprint', 'spacing_x_m', 'spacing_y_m', 'captured_channels', 'bits_per_sample', 'nx', 'ny', 'stored_bits'),
    MSProductAssessment: ('status', 'reasons', 'credited_record_ids', 'completion_time_seconds'),
    ImagingRequest: ('request_id', 'target_id', 'priority_weight'),
    OnboardAcquisitionDataRecord: ('record_id', 'imaging_request_id', 'observation_opportunity_id', 'scheduled_start_seconds', 'acquisition_duration_seconds', 'channel_selection', 'uncompressed_equivalent_bits', 'stored_equivalent_bits'),
    StandbyInputs: ('loads', 'sunlit', 'incidence_angle_deg', 'routing_config', 'thermal_inputs', 'external_heat_sources', 'solar_degradation_forcing', 'rationale'),
    FrameDefinition: ('kind', 'ellipsoid', 'rotation'),
    GeometryInstant: ('epoch', 'elapsed_seconds'),
    ReferenceEllipsoid: ('name', 'equatorial_radius_m', 'flattening'),
    TTEpoch: ('julian_day', 'fractional_day'),
    UniformRotationDefinition: ('epoch', 'initial_phase_rad', 'angular_velocity_rad_per_s'),
    GroundPointDefinition: ('point_id', 'ellipsoid', 'latitude_rad', 'longitude_rad', 'ellipsoidal_height_m'),
    GroundPointGeometry: ('point', 'spacecraft_state', 'ground_state', 'ground_to_spacecraft', 'spacecraft_to_ground', 'orbital_x', 'orbital_y', 'orbital_z', 'slant_range_m', 'slant_range_rate_m_per_s', 'elevation_rad', 'ground_azimuth_rad', 'incidence_rad', 'off_nadir_rad', 'orbital_azimuth_rad', 'ground_azimuth_projection_norm', 'ground_azimuth_resolution', 'orbital_azimuth_projection_norm', 'orbital_azimuth_resolution'),
    GroundVisibilityPolicy: ('minimum_elevation_rad',),
    GroundVisibilityResult: ('point', 'spacecraft_state', 'policy', 'geometry', 'line_of_sight_status', 'line_of_sight_reason', 'elevation_status', 'elevation_margin_rad', 'elevation_allowance_rad', 'status', 'ground_location', 'spacecraft_location', 'ground_level', 'spacecraft_level', 'quadratic_a', 'quadratic_b', 'minimum_parameter', 'minimum_location', 'minimum_level', 'ground_position_allowance_scaled', 'exact_axis_definition', 'occultation_predicate', 'occultation_signed_value', 'occultation_allowance'),
    ScalarParameter: ('value', 'provenance'),
    PowerLoadBreakdown: ('base_bus_w', 'obc_w', 'adcs_w', 'payload_w', 'communications_w', 'thermal_control_w', 'propulsion_w'),
    ParameterProvenance: ('parameter_id', 'classification', 'units', 'source_ids', 'status', 'rationale', 'derivation', 'sensitivity_range'),
    RollingDecision: ('decision_id', 'view_identity', 'knowledge_age_seconds', 'selected_suffix', 'explanation', 'forecasts', 'rejected'),
    CommittedCommand: ('root_identity', 'previous_identity', 'decision_identity', 'knowledge_identity', 'action', 'lineage_identity', 'decision_payload_identity'),
    IssuedCommand: ('command_id', 'kind', 'point_id', 'product_id', 'issued_at_seconds', 'feedback_due_seconds'),
    ReceivedKnowledge: ('observation', 'received', 'issued'),
    ReceivedObservation: ('packet_id', 'observed_at_seconds', 'received_at_seconds', 'resources', 'attitude', 'onboard_records', 'partial_transfers', 'delivery_acks', 'consumed_contacts', 'command_id', 'command_status', 'command_reason', 'origin'),
    ConstructionAdapter: ('inputs', 'compilation', 'work'),
    ConstructionAdapterInputs: ('limits', 'configuration'),
    HarnessAdapter: ('inputs', 'hardware', 'work'),
    HarnessAdapterInputs: ('augmentation',),
    PhysicalInputs: ('model', 'products', 'limits', 'api'),
    SolarGenerationResult: ('nominal_generation_w', 'sunlit', 'incidence_angle_deg'),
    ActionAccounting: ('generation_wh', 'requested_load_wh', 'served_load_wh', 'unmet_load_wh', 'charge_input_wh', 'discharge_output_wh', 'curtailed_generation_wh', 'conversion_loss_wh', 'throughput_wh', 'unavailable_energy_wh', 'calendar_damage', 'cycling_damage', 'solar_retention_loss', 'routed_internal_heat_wh', 'external_heat_wh', 'numerical_substeps'),
    PhysicalSample: ('offset_numerator_seconds', 'battery_energy_wh', 'battery_retention', 'solar_retention', 'cumulative_throughput_wh', 'temperatures_k', 'operating_node_ids', 'survival_node_ids', 'unmet_load_w'),
    SubstepAvailability: ('requested_kind', 'reasons', 'operating_start_node_ids', 'predicted_operating_node_ids', 'standby_operating_node_ids', 'action_unmet_w', 'essential_unmet_wh'),
    ThermalIntervalInputs: ('node_boundaries',),
    ThermalLinkHeatFlow: ('link_id', 'node_a_id', 'node_b_id', 'heat_flow_a_to_b_w'),
    ThermalNodeBoundaryInput: ('node_id', 'radiative_sink_temperature_k'),
    ThermalNodeTransition: ('node_id', 'start_temperature_k', 'end_temperature_k', 'conductive_heat_into_w', 'radiative_heat_into_w', 'applied_heat_into_w', 'net_heat_into_w', 'thermal_energy_change_j'),
    ThermalSubstepResult: ('node_transitions', 'link_heat_flows', 'dt_seconds', 'duration'),
    ThermalLinkConfig: ('link_id', 'node_a_id', 'node_b_id', 'conductance_w_per_k'),
    ThermalNetworkConfig: ('nodes', 'links', 'bus_node_id', 'battery_node_id', 'payload_node_id'),
    ThermalNodeConfig: ('node_id', 'heat_capacity_j_per_k', 'emissivity', 'radiating_area_m2', 'operating_min_temperature_k', 'operating_max_temperature_k', 'survival_min_temperature_k', 'survival_max_temperature_k'),
    EPSThermalSubstepResult: ('node_heat_ledgers', 'thermal_result'),
    ThermalHeatSourceInputs: ('node_sources',),
    ThermalNodeHeatLedger: ('node_id', 'internal_dissipation_w', 'absorbed_solar_w', 'absorbed_albedo_w', 'absorbed_earth_ir_w', 'battery_conversion_heat_w', 'total_applied_heat_w'),
    ThermalNodeHeatSourceInput: ('node_id', 'internal_dissipation_w', 'absorbed_solar_w', 'absorbed_albedo_w', 'absorbed_earth_ir_w'),
    ComponentHeatRoute: ('component', 'thermal_node_id', 'retained_heat_fraction'),
    ComponentHeatRoutingConfig: ('routes',),
})
ENUM_TYPES = tuple(dict.fromkeys((*BASE_ENUM_TYPES, ActionKind, FrameKind, BodyLocation, ElevationStatus, GroundVisibilityStatus, LineOfSightReason, LineOfSightStatus, SegmentMinimumLocation, OpticalAcquisitionChannelSelection, ProvenanceClass, ProvenanceStatus, FDIRState, OperationalMode, ElectricalLoadComponent)))
RECORDS = {c.__module__+"."+c.__name__: c for c in RECORD_FIELDS}
ENUMS = {c.__module__+"."+c.__name__: c for c in ENUM_TYPES}
def validate_schema():
    for owner, names in RECORD_FIELDS.items():
        f=fields(owner)
        if tuple(x.name for x in f)!=names or any(not x.init for x in f) and owner not in (GroundPointGeometry,GroundVisibilityResult):
            raise ValueError("unreviewed snapshot record schema: "+owner.__name__)

def restore_ground_geometry(values):
    """Dedicated trusted cached geometry; no prior point-query recalculation.

    All 19 declared fields are preserved. This is NOT a general object loader;
    the one fixed non-init record owner is selected by source, never payload code.
    """
    import math
    names=RECORD_FIELDS[GroundPointGeometry]
    if tuple(values)!=names:raise ValueError('ground geometry snapshot fields')
    if type(values['point']) is not GroundPointDefinition or type(values['spacecraft_state']) is not CartesianState:
        raise ValueError('ground geometry snapshot authorities')
    if type(values['ground_state']) is not CartesianState:raise ValueError('ground geometry snapshot ground state')
    frame=values['spacecraft_state'].position.frame;instant=values['spacecraft_state'].position.instant
    for n in names[3:8]:
        v=values[n]
        if type(v) is not CartesianDirection or v.frame!=frame or v.instant!=instant:raise ValueError('ground geometry common-frame snapshot')
    for n in names[8:]:
        value=values[n]
        if value is None and n in ('ground_azimuth_rad','orbital_azimuth_rad'):continue
        if type(value) is not float or not math.isfinite(value):raise ValueError('ground geometry snapshot scalar')
    result=object.__new__(GroundPointGeometry)
    for n in names:object.__setattr__(result,n,values[n])
    return result

def restore_ground_visibility(values):
    """Second and last fixed cached derived owner; no geometric re-evaluation."""
    from fractions import Fraction
    import math
    names=RECORD_FIELDS[GroundVisibilityResult]
    if tuple(values)!=names:raise ValueError('ground visibility snapshot fields')
    checks=dict(point=GroundPointDefinition,spacecraft_state=CartesianState,policy=GroundVisibilityPolicy,
        geometry=GroundPointGeometry,line_of_sight_status=LineOfSightStatus,line_of_sight_reason=LineOfSightReason,
        elevation_status=ElevationStatus,status=GroundVisibilityStatus,ground_location=BodyLocation,
        spacecraft_location=BodyLocation,minimum_location=SegmentMinimumLocation,exact_axis_definition=bool,occultation_predicate=str)
    for n,t in checks.items():
        if type(values[n]) is not t:raise ValueError('ground visibility snapshot type: '+n)
    if values['geometry'].point!=values['point'] or values['geometry'].spacecraft_state!=values['spacecraft_state']:raise ValueError('visibility retained input/geometry binding')
    for n in ('elevation_margin_rad','elevation_allowance_rad'):
        if type(values[n]) is not float or not math.isfinite(values[n]):raise ValueError('visibility finite angle')
    for n in names:
        if n not in checks and n not in ('elevation_margin_rad','elevation_allowance_rad') and type(values[n]) is not Fraction:raise ValueError('visibility exact dimensionless value')
    result=object.__new__(GroundVisibilityResult)
    for n in names:object.__setattr__(result,n,values[n])
    return result
