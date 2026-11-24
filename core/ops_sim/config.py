"""All numerical constants used by the Version 1 model.

Keeping the constants here makes the intentionally simplified assumptions easy to
audit.  Rates that the model specification describes only as "very small" are
explicit V1 assumptions, not claims about spacecraft physics.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SimulationConfig:
    default_simulation_years: float = 10.0
    hours_per_day: int = 24
    days_per_year: float = 365.25
    hours_per_year: int = 8766
    checkpoint_hours: int = 4383
    contact_interval_hours: int = 4
    cmd_contact_minutes: int = 15
    data_contact_minutes: int = 15

    storage_capacity_gb: float = 1000.0
    imaging_rate_gb_per_hour: float = 25.0
    public_x_band_rate_mbit_per_s: float = 270.0
    x_band_downlink_rate_gb_per_min: float = 2.0
    imaging_block_fraction: float = 0.95
    storage_stress_fraction: float = 0.90

    initial_soc: float = 80.0
    minimum_percent: float = 0.0
    maximum_percent: float = 100.0
    minimum_health: float = 0.0
    maximum_health: float = 1.0
    soc_safe_delta: float = 0.30
    soc_standby_delta: float = 0.10
    soc_imaging_delta: float = -0.80
    soc_downlink_delta: float = -0.50
    maneuver_soc_delta: float = -1.00
    soc_backup_delta: float = 0.05
    soc_emergency_delta: float = -0.15

    # V3.6A bounded power/eclipse proxies. The public value is retained only
    # as reference metadata; the generation and load values are transparent
    # simulator assumptions, not calibrated KazEOSat-1 electrical parameters.
    public_power_reference_w: float = 1200.0
    eclipse_fraction_per_orbit: float = 0.35
    solar_generation_proxy_w: float = 1000.0
    safe_power_load_proxy_w: float = 300.0
    standby_power_load_proxy_w: float = 400.0
    imaging_power_load_proxy_w: float = 1000.0
    downlink_power_load_proxy_w: float = 900.0
    maneuver_power_load_proxy_w: float = 1100.0
    backup_power_load_proxy_w: float = 250.0
    emergency_power_load_proxy_w: float = 350.0

    # V3.6B bounded thermal/load stress assumptions. These values drive only
    # the optional thermal proxy and are not calibrated spacecraft parameters.
    thermal_model_hot_load_threshold_w: float = 800.0
    thermal_model_cold_load_threshold_w: float = 400.0
    thermal_hot_stress_degradation_per_hour: float = 0.000001
    thermal_cold_stress_degradation_per_hour: float = 0.0000005
    thermal_high_load_stress_degradation_per_hour: float = 0.0000005
    thermal_stress_max_per_hour: float = 0.000002

    # V3.7A deterministic synthetic scene/tasking assumptions. Public scene,
    # revisit, and productivity values are metadata/sanity references only;
    # they do not calibrate real demand, coverage, or operations.
    target_scene_width_km: float = 20.0
    target_scene_height_km: float = 20.0
    public_scene_width_reference_km: float = 20.0
    public_scene_height_reference_km: float = 20.0
    public_spatial_resolution_reference_m: float = 1.0
    public_imagery_mode_references: tuple[str, ...] = (
        "panchromatic",
        "multispectral",
    )
    target_opportunity_period_hours: int = 4
    target_opportunity_window_hours: int = 1
    target_priority_max: int = 5
    target_multispectral_every_n_opportunities: int = 3
    public_revisit_min_days: float = 3.0
    public_revisit_max_days: float = 5.0
    public_productivity_reference_km2_per_day: float = 220000.0

    # V3.7B bounded pointing assumptions. These values drive only the optional
    # deterministic stress proxy; they are not calibrated ADCS, slew, or
    # off-nadir performance parameters.
    pointing_quality_min_threshold: float = 0.75
    pointing_quality_critical_threshold: float = 0.25
    pointing_max_off_nadir_proxy_deg: float = 35.0
    pointing_max_slew_proxy_deg: float = 25.0
    pointing_off_nadir_penalty_scale: float = 0.25
    pointing_slew_penalty_scale: float = 0.15
    pointing_geometry_degraded_penalty: float = 0.10

    # V3.8A passive packet-accounting assumptions. These KB values are not
    # calibrated spacecraft packet sizes and are not derived from the public
    # X-band payload rate or QPSK metadata.
    housekeeping_telemetry_packet_kb: float = 4.0
    command_packet_kb: float = 1.0
    daily_plan_packet_kb: float = 8.0

    # V3.8B bounded delivery stress assumption. This is an experimental
    # fraction, not an estimated packet-loss probability or RF parameter.
    packet_drop_fraction_proxy: float = 0.10

    # V2.7 maneuver-resource proxies. These are transparent experiment
    # assumptions, not values derived from KazEOSat-1 operations.
    initial_delta_v_budget_m_per_s: float = 10.0
    stationkeeping_delta_v_cost_m_per_s: float = 0.10
    maneuver_propulsion_degradation: float = 0.0001
    orbit_drift_proxy_km_per_day: float = 0.05
    orbit_drift_threshold_km: float = 0.10
    orbit_drift_warning_threshold_km: float = 0.10
    orbit_drift_critical_threshold_km: float = 0.50
    orbit_drift_reduction_per_maneuver_km: float = 0.10
    orbit_drift_damage_per_hour: float = 0.00001
    orbit_drift_damage_targets: tuple[str, ...] = (
        "adcs_health", "thermal_health", "comms_health",
    )
    minimum_delta_v_for_maneuver_m_per_s: float = 0.10
    propulsion_maneuver_health_threshold: float = 0.20
    debris_avoidance_delta_v_cost_m_per_s: float = 0.20
    debris_avoidance_drift_reduction_km: float = 0.0
    debris_damage_targets: tuple[str, ...] = (
        "solar_health", "adcs_health", "thermal_health", "comms_health",
    )

    # V2.8 orbit-evolution proxies. These values make drift and maneuver
    # bookkeeping visible to the optional geometry model; they are transparent
    # stress-test assumptions, not KazEOSat-1 orbit-determination data or
    # flight-dynamics constants.
    orbit_phase_error_deg_per_drift_km: float = 0.008
    orbit_altitude_offset_km_per_drift_km: float = -0.10
    orbit_groundtrack_error_km_per_drift_km: float = 1.00
    orbit_geometry_degraded_threshold_km: float = 0.10
    orbit_geometry_critical_threshold_km: float = 0.50
    stationkeeping_phase_correction_fraction: float = 0.90
    stationkeeping_altitude_correction_fraction: float = 0.90
    stationkeeping_groundtrack_correction_fraction: float = 0.90
    debris_avoidance_phase_impulse_deg: float = 0.001
    debris_avoidance_altitude_impulse_km: float = 0.01
    debris_avoidance_groundtrack_impulse_km: float = 0.10
    maximum_orbit_phase_error_deg: float = 10.0
    maximum_orbit_altitude_offset_km: float = 10.0
    maximum_orbit_groundtrack_error_km: float = 100.0

    solar_annual_degradation: float = 0.01
    battery_annual_degradation: float = 0.02
    high_battery_degradation_multiplier: float = 2.0
    # Explicit assumptions for qualitative "very small" degradation requirements.
    payload_annual_degradation: float = 0.001
    payload_imaging_degradation_per_hour: float = 0.000002
    storage_annual_degradation: float = 0.0005
    storage_stress_degradation_per_hour: float = 0.000001
    comms_annual_degradation: float = 0.0005
    placeholder_annual_degradation: float = 0.0

    eps_battery_weight: float = 0.60
    eps_solar_weight: float = 0.40
    total_eps_weight: float = 0.35
    total_comms_weight: float = 0.20
    total_payload_weight: float = 0.20
    total_storage_weight: float = 0.15
    total_placeholder_weight: float = 0.10
    placeholder_subsystem_count: int = 4

    critical_soc: float = 5.0
    critical_soc_max_consecutive_hours: int = 6
    eps_failure_health: float = 0.15
    comms_failure_health: float = 0.10
    payload_failure_health: float = 0.10
    storage_failure_health: float = 0.10
    obc_failure_health: float = 0.10
    adcs_failure_health: float = 0.10
    thermal_failure_health: float = 0.10
    plan_duration_hours: int = 24
    emergency_after_hours: int = 336

    aggressive_safe_threshold: float = 15.0
    aggressive_downlink_buffer_fraction: float = 0.20
    aggressive_imaging_soc: float = 35.0
    conservative_safe_threshold: float = 30.0
    conservative_downlink_buffer_fraction: float = 0.10
    conservative_imaging_soc: float = 65.0
    conservative_imaging_buffer_fraction: float = 0.70
    adaptive_safe_threshold: float = 25.0
    adaptive_downlink_buffer_fraction: float = 0.60
    adaptive_imaging_soc: float = 55.0
    adaptive_imaging_buffer_fraction: float = 0.80
    adaptive_safe_soc: float = 35.0

    outage_start_year: float = 8.0
    outage_duration_days: int = 16

    score_data_weight: float = 0.35
    score_health_weight: float = 0.25
    score_survival_weight: float = 0.20
    score_soc_weight: float = 0.10
    score_safe_penalty_weight: float = 0.10
    score_data_loss_penalty_weight: float = 0.10
    score_emergency_penalty_weight: float = 0.05

    # V2.1 coupling assumptions. A healthy subsystem always produces a factor of 1.
    thermal_high_load_sensitivity: float = 2.0

    seconds_per_hour: int = 3600
    seconds_per_minute: int = 60
    degrees_per_circle: float = 360.0
    earth_radius_km: float = 6371.0
    earth_mu_km3_s2: float = 398600.4418
    earth_rotation_rate_rad_s: float = 7.2921159e-5
    orbit_altitude_km: float = 750.0
    orbit_inclination_deg: float = 98.5
    public_orbit_altitude_reference_km: float = 750.0
    public_orbit_inclination_reference_deg: float = 98.5
    orbit_raan_deg: float = 0.0
    orbit_initial_phase_deg: float = 0.0
    minimum_elevation_deg: float = 5.0

    # Deterministic V2 post-design-life stress assumptions.
    post_life_stress_start_year: float = 8.0
    solar_stress_degradation_multiplier: float = 3.0
    reduced_downlink_capacity_multiplier: float = 0.50
    storage_pressure_initial_fraction: float = 0.85
    storage_pressure_degradation_multiplier: float = 5.0
    payload_stress_degradation_multiplier: float = 8.0
    comms_stress_degradation_multiplier: float = 20.0
    low_contact_keep_every_n: int = 3
    extended_outage_days: int = 30
    repeated_outage_period_days: int = 90
    repeated_outage_duration_days: int = 3
    high_imaging_demand_multiplier: float = 1.50
    attitude_imaging_adcs_penalty: float = 0.00002
    attitude_imaging_soc_penalty: float = 0.10
    combined_energy_battery_multiplier: float = 2.50
    combined_energy_solar_multiplier: float = 3.0
    combined_energy_soc_penalty: float = 0.12
    extreme_battery_multiplier: float = 3.0
    extreme_solar_multiplier: float = 4.0
    extreme_payload_multiplier: float = 12.0
    extreme_comms_multiplier: float = 30.0
    extreme_blackout_start_year: float = 10.0
    extreme_blackout_duration_days: int = 30
    extreme_attitude_imaging_adcs_penalty: float = 0.00004
    extreme_energy_soc_penalty: float = 0.18

    # V2.3 seeded external-event catalog assumptions (per post-life day).
    stochastic_solar_storm_probability_per_day: float = 0.002
    stochastic_radiation_event_probability_per_day: float = 0.003
    stochastic_contact_disruption_probability_per_day: float = 0.005
    stochastic_payload_glitch_probability_per_day: float = 0.003
    stochastic_storage_upset_probability_per_day: float = 0.002
    stochastic_thermal_stress_probability_per_day: float = 0.004
    stochastic_debris_conjunction_probability_per_day: float = 0.001
    stochastic_min_severity: float = 0.50
    stochastic_max_severity: float = 1.00
    stochastic_solar_storm_duration_hours: int = 24
    stochastic_radiation_event_duration_hours: int = 12
    stochastic_contact_disruption_duration_hours: int = 24
    stochastic_payload_glitch_duration_hours: int = 6
    stochastic_storage_upset_duration_hours: int = 1
    stochastic_thermal_stress_duration_hours: int = 12
    stochastic_debris_conjunction_duration_hours: int = 1
    stochastic_solar_storm_health_effect: float = 0.010
    stochastic_radiation_health_effect: float = 0.008
    stochastic_payload_glitch_health_effect: float = 0.010
    stochastic_storage_upset_data_effect_gb: float = 5.0
    stochastic_thermal_stress_health_effect: float = 0.010
    stochastic_debris_conjunction_damage_effect: float = 0.020


DEFAULT_CONFIG = SimulationConfig()
