"""B58 separately versioned battery-port resource-chain production CLI/Workbench.

Old B55-R2 controller/source/store are never migrated. Exact trusted membership
of the new674-file worker and this controller SHA are separate plan authorities.
"""
from pathlib import Path
from dataclasses import asdict
from copy import deepcopy
from hashlib import sha256
import argparse,datetime,json,os,threading,time,uuid
from ops_sim.v5.experiment_codec import object_fields
from ops_sim.v5.lifecycle_contract import integer,identity
from ops_sim.v5.project_store import identifier,file_sha,runtime_identity
from ops_sim.v5.spacecraft_project import project_source_identity
from ops_sim.v5.lifecycle_application import (LifecycleStore,LifecycleRunner,make_intent,
    _read,_write_new,_admit_execution_terminal,_settled_publication_work,
    _admit_publication,_verify_checkpoint_streams,_write_stop_request,TERMINAL)
from ops_sim.v5.lifecycle_execution_budget import admit_budget
from ops_sim.v5.lifecycle_checkpoint import admit_checkpoint,make_bindings

PLAN='B58_SETTLED_SOLAR_RESOURCE_CHAIN_V3'
STATE='B58_SOLAR_RESOURCE_CHAIN_STATE_V3'
POLICY='B58_SAME_SOLAR_POLICY_SETTLED_TIME_OR_OUTPUT_V3'
OUTPUT_REASON='PROSPECTIVE_OUTPUT_ADMISSION_BEFORE_NEXT_MODEL_TRANSITION'

EXPECTED_WORKER_MEMBERS = ('.gitignore', 'FINAL_CONFIG.md', 'HANDOFF.md', 'KAZEOSAT_PUBLIC_SPEC.md', 'M1_ASSEMBLY.md', 'M1_ASSEMBLY_CHOICES.md', 'M1_ASSEMBLY_INTERFACES.md', 'M2_CONTINUOUS_MISSION_GEOMETRY.md', 'M2_ENVIRONMENT_FORCING.md', 'M2_ENVIRONMENT_MISSION.md', 'M2_GENERAL_EARTH_GEOMETRY.md', 'M2_ILLUMINATION_WINDOWS.md', 'M2_INTERVAL_ILLUMINATION.md', 'M2_J2_COEFFICIENTS.md', 'M2_J2_SEGMENTS.md', 'M2_J2_ZONOTOPE.md', 'M2_J2_ZONOTOPE_INCREMENTAL.md', 'M2_J2_ZONOTOPE_SEGMENTS.md', 'M2_LOCAL_ILLUMINATION.md', 'M2_LONG_CONNECTED_MISSION.md', 'M2_ORBIT_SUN.md', 'M2_PICARD_SEED.md', 'M2_SUN_TABLE.md', 'M2_ZONOTOPE_INTERVAL_ILLUMINATION.md', 'M2_ZONOTOPE_LOCAL_ILLUMINATION.md', 'M2_ZONOTOPE_LOCAL_RESOURCE_V2.md', 'M3_ASSEMBLY_ACTIONS.md', 'M3_SPATIAL_ASSEMBLY_MISSION.md', 'M4_CONSTRUCTION_COUPLING.md', 'M4_HARNESS_MASS.md', 'M5_COMMAND_ESTIMATION.md', 'M5_ROLLING_CONTROLLER.md', 'M6_FAILURE_ANALYSIS.md', 'M7_DESIGN_REPAIR.md', 'M8_BATTERY_PORT.md', 'M8_COMPACT_PUBLICATION.md', 'M8_LIFECYCLE.md', 'M8_LONG_STUDY.md', 'M8_POWER_RECOVERY.md', 'M8_PRODUCTION_MONTH.md', 'M8_QUIET_PHYSICS.md', 'M8_SNAPSHOTS_REPORTS.md', 'M8_SOLAR_ATTITUDE.md', 'M8_WORKBENCH.md', 'MODEL_STATUS.md', 'PROJECT_CANON.md', 'README.md', 'V5_2_RELEASE_AUDIT.md', 'V5_3_RELEASE_AUDIT.md', 'V5_4_RELEASE_AUDIT.md', 'V5_5_RELEASE_AUDIT.md', 'V5_CONTACT_EXECUTION.md', 'V5_CONTINUOUS_TRADE.md', 'V5_COUPLED_DOWNLINK.md', 'V5_DECISION_LOG.md', 'V5_DESIGN_SPEC.md', 'V5_DESIGN_TRADE.md', 'V5_DESIGN_TRADE_SOURCES.md', 'V5_EPS_STRESS.md', 'V5_EXPERIMENT_BUNDLE.md', 'V5_J2_BINDING.md', 'V5_J2_ENCLOSURE.md', 'V5_MS_CAMPAIGN.md', 'V5_MS_COMPARISON.md', 'V5_MS_MISSION.md', 'V5_OPERATIONAL_PROTECTION.md', 'V5_SOURCE_REGISTER.md', 'V5_SUBSTEPPED_EXECUTION.md', 'autonomy_report.py', 'debris_risk_report.py', 'decision_report.py', 'event_lifecycle_report.py', 'examples/m1_assembly_choices_demo.py', 'examples/m1_assembly_interfaces_demo.py', 'examples/m2_environment_forcing_demo.py', 'examples/m2_illumination_windows_demo.py', 'examples/m2_interval_illumination_demo.py', 'examples/m2_j2_segments_demo.py', 'examples/m2_j2_zonotope_segments_demo.py', 'examples/m2_local_illumination_demo.py', 'examples/m2_orbit_sun_demo.py', 'examples/m2_sun_table_demo.py', 'examples/m2_zonotope_interval_illumination_demo.py', 'examples/m2_zonotope_local_illumination_demo.py', 'examples/m2_zonotope_local_v2_illumination_demo.py', 'examples/m3_constructor_mission_demo.py', 'examples/m3_continuous_mission_demo.py', 'examples/m3_general_earth_mission_demo.py', 'examples/m3_long_mission_demo.py', 'examples/m3_spatial_constructor_mission_demo.py', 'examples/m4_construction_mission_demo.py', 'examples/m4_mass_closed_mission_demo.py', 'examples/m5_command_mission_demo.py', 'examples/m5_rolling_mission_demo.py', 'examples/m6_engineering_comparison.py', 'examples/m7_design_repair_demo.py', 'examples/m8_battery_port.py', 'examples/m8_lifecycle.py', 'examples/m8_snapshot_report_demo.py', 'examples/m8_workbench.py', 'examples/v52_integrated_eps_thermal_demo.py', 'examples/v53_integrated_imaging_demo.py', 'examples/v54_integrated_storage_demo.py', 'examples/v55_integrated_downlink_demo.py', 'examples/v5_assembly_demo.py', 'examples/v5_contact_execution_demo.py', 'examples/v5_continuous_trade_checks.py', 'examples/v5_continuous_trade_study.py', 'examples/v5_coupled_downlink_demo.py', 'examples/v5_design_trade_report.py', 'examples/v5_design_trade_study.py', 'examples/v5_eps_stress.py', 'examples/v5_eps_stress_report.py', 'examples/v5_eps_stress_study.py', 'examples/v5_experiment_bundle_demo.py', 'examples/v5_j2_bundle_demo.py', 'examples/v5_j2_enclosure_pilot.py', 'examples/v5_ms_campaign_demo.py', 'examples/v5_ms_comparison.py', 'examples/v5_ms_comparison_checks.py', 'examples/v5_ms_comparison_report.py', 'examples/v5_ms_comparison_study.py', 'examples/v5_ms_mission_demo.py', 'examples/v5_operational_protection_demo.py', 'examples/v5_substepped_execution_demo.py', 'inspect.py', 'lifecycle_seed_finder.py', 'm8_compact_chain_cli.py', 'm8_resource_chain_cli.py', 'm8_solar_chain_cli.py', 'main.py', 'ops_sim/__init__.py', 'ops_sim/__main__.py', 'ops_sim/analysis.py', 'ops_sim/autonomy.py', 'ops_sim/cli.py', 'ops_sim/config.py', 'ops_sim/contacts.py', 'ops_sim/debris_risk.py', 'ops_sim/decision.py', 'ops_sim/event_catalog.py', 'ops_sim/event_lifecycle.py', 'ops_sim/geometry.py', 'ops_sim/inspect_tool.py', 'ops_sim/metrics.py', 'ops_sim/models.py', 'ops_sim/orbit.py', 'ops_sim/packets.py', 'ops_sim/pointing.py', 'ops_sim/policies.py', 'ops_sim/power.py', 'ops_sim/reliability.py', 'ops_sim/reporting.py', 'ops_sim/research_design.py', 'ops_sim/research_validation.py', 'ops_sim/rul.py', 'ops_sim/scenarios.py', 'ops_sim/simulator.py', 'ops_sim/stationkeeping.py', 'ops_sim/targets.py', 'ops_sim/thermal.py', 'ops_sim/v5/__init__.py', 'ops_sim/v5/_experiment_types.py', 'ops_sim/v5/_snapshot_records.py', 'ops_sim/v5/adcs.py', 'ops_sim/v5/adcs_config.py', 'ops_sim/v5/assembly.py', 'ops_sim/v5/assembly_attitude.py', 'ops_sim/v5/assembly_attitude_3d.py', 'ops_sim/v5/assembly_choices.py', 'ops_sim/v5/assembly_document.py', 'ops_sim/v5/assembly_interface_document.py', 'ops_sim/v5/assembly_interfaces.py', 'ops_sim/v5/assembly_slew_3d.py', 'ops_sim/v5/battery_port.py', 'ops_sim/v5/battery_port_construction.py', 'ops_sim/v5/battery_port_reporting.py', 'ops_sim/v5/campaign_continuation.py', 'ops_sim/v5/campaign_contract.py', 'ops_sim/v5/campaign_controller.py', 'ops_sim/v5/checkpoint.py', 'ops_sim/v5/command_controller.py', 'ops_sim/v5/command_document.py', 'ops_sim/v5/command_estimation.py', 'ops_sim/v5/communications.py', 'ops_sim/v5/comparison_campaign.py', 'ops_sim/v5/comparison_evidence.py', 'ops_sim/v5/comparison_manifest.py', 'ops_sim/v5/configuration.py', 'ops_sim/v5/construction_contact.py', 'ops_sim/v5/construction_coupling.py', 'ops_sim/v5/construction_document.py', 'ops_sim/v5/construction_mission.py', 'ops_sim/v5/construction_physics.py', 'ops_sim/v5/construction_service.py', 'ops_sim/v5/contact_continuation.py', 'ops_sim/v5/contact_execution.py', 'ops_sim/v5/context.py', 'ops_sim/v5/continuation.py', 'ops_sim/v5/continuous_trade.py', 'ops_sim/v5/continuous_trade_io.py', 'ops_sim/v5/controller_state.py', 'ops_sim/v5/coupled_downlink.py', 'ops_sim/v5/data_delivery.py', 'ops_sim/v5/degradation.py', 'ops_sim/v5/degradation_config.py', 'ops_sim/v5/design_repair.py', 'ops_sim/v5/design_repair_continuation.py', 'ops_sim/v5/design_repair_document.py', 'ops_sim/v5/design_repair_study.py', 'ops_sim/v5/design_trade_campaign.py', 'ops_sim/v5/design_trade_continuation.py', 'ops_sim/v5/design_trade_design.py', 'ops_sim/v5/design_trade_execution.py', 'ops_sim/v5/design_trade_physics.py', 'ops_sim/v5/diagnostics.py', 'ops_sim/v5/downlink.py', 'ops_sim/v5/engine.py', 'ops_sim/v5/engineering_experiment.py', 'ops_sim/v5/environment_forcing.py', 'ops_sim/v5/environment_forcing_document.py', 'ops_sim/v5/environment_mission.py', 'ops_sim/v5/environment_mission_3d.py', 'ops_sim/v5/environment_mission_3d_continuation.py', 'ops_sim/v5/environment_mission_3d_document.py', 'ops_sim/v5/environment_mission_continuation.py', 'ops_sim/v5/environment_mission_document.py', 'ops_sim/v5/environment_mission_general_continuation.py', 'ops_sim/v5/environment_mission_general_document.py', 'ops_sim/v5/environment_physics.py', 'ops_sim/v5/eps.py', 'ops_sim/v5/eps_capability.py', 'ops_sim/v5/eps_system.py', 'ops_sim/v5/eps_validation.py', 'ops_sim/v5/experiment_bundle.py', 'ops_sim/v5/experiment_codec.py', 'ops_sim/v5/experiment_provenance.py', 'ops_sim/v5/frames.py', 'ops_sim/v5/harness_document.py', 'ops_sim/v5/harness_hardware.py', 'ops_sim/v5/harness_mass.py', 'ops_sim/v5/harness_mission.py', 'ops_sim/v5/harness_slew.py', 'ops_sim/v5/ids.py', 'ops_sim/v5/imaging_authorization.py', 'ops_sim/v5/imaging_execution.py', 'ops_sim/v5/imaging_feasibility.py', 'ops_sim/v5/imaging_resources.py', 'ops_sim/v5/imaging_storage.py', 'ops_sim/v5/imaging_thermal.py', 'ops_sim/v5/integration_time.py', 'ops_sim/v5/knowledge.py', 'ops_sim/v5/lifecycle_admission.py', 'ops_sim/v5/lifecycle_application.py', 'ops_sim/v5/lifecycle_chain.py', 'ops_sim/v5/lifecycle_checkpoint.py', 'ops_sim/v5/lifecycle_compact.py', 'ops_sim/v5/lifecycle_contract.py', 'ops_sim/v5/lifecycle_document.py', 'ops_sim/v5/lifecycle_execution.py', 'ops_sim/v5/lifecycle_execution_budget.py', 'ops_sim/v5/lifecycle_orbit.py', 'ops_sim/v5/lifecycle_physics.py', 'ops_sim/v5/lifecycle_quiet.py', 'ops_sim/v5/lifecycle_report.py', 'ops_sim/v5/lifecycle_runner_policy.py', 'ops_sim/v5/lifecycle_service.py', 'ops_sim/v5/lifecycle_service_contact.py', 'ops_sim/v5/lifecycle_state.py', 'ops_sim/v5/lifecycle_stream.py', 'ops_sim/v5/lifecycle_study.py', 'ops_sim/v5/lifecycle_world.py', 'ops_sim/v5/long_environment.py', 'ops_sim/v5/long_general_geometry.py', 'ops_sim/v5/long_mission.py', 'ops_sim/v5/long_mission_continuation.py', 'ops_sim/v5/long_mission_document.py', 'ops_sim/v5/long_nominal_provider.py', 'ops_sim/v5/manifest.py', 'ops_sim/v5/mission.py', 'ops_sim/v5/mission_camera_3d.py', 'ops_sim/v5/mission_continuous_geometry.py', 'ops_sim/v5/mission_diagnosis.py', 'ops_sim/v5/mission_environment.py', 'ops_sim/v5/mission_general_geometry.py', 'ops_sim/v5/mission_report.py', 'ops_sim/v5/mission_report_document.py', 'ops_sim/v5/ms_acquisition.py', 'ops_sim/v5/ms_continuation.py', 'ops_sim/v5/ms_product.py', 'ops_sim/v5/observation.py', 'ops_sim/v5/observation_feasibility.py', 'ops_sim/v5/onboard_data.py', 'ops_sim/v5/operational_continuation.py', 'ops_sim/v5/operational_protection.py', 'ops_sim/v5/orbit.py', 'ops_sim/v5/orbit_binding.py', 'ops_sim/v5/orbit_config.py', 'ops_sim/v5/orbit_contact_serviceability.py', 'ops_sim/v5/orbit_geometry.py', 'ops_sim/v5/orbit_ground_contacts.py', 'ops_sim/v5/orbit_j2.py', 'ops_sim/v5/orbit_j2_binding.py', 'ops_sim/v5/orbit_j2_enclosure.py', 'ops_sim/v5/orbit_j2_gravity.py', 'ops_sim/v5/orbit_j2_segments.py', 'ops_sim/v5/orbit_j2_segments_document.py', 'ops_sim/v5/orbit_j2_zonotope.py', 'ops_sim/v5/orbit_j2_zonotope_segments.py', 'ops_sim/v5/orbit_j2_zonotope_segments_document.py', 'ops_sim/v5/orbit_observation_boresight.py', 'ops_sim/v5/orbit_observation_catalog.py', 'ops_sim/v5/orbit_observation_opportunity.py', 'ops_sim/v5/orbit_observation_sequence.py', 'ops_sim/v5/orbit_observation_transition.py', 'ops_sim/v5/orbit_sun.py', 'ops_sim/v5/orbit_sun_document.py', 'ops_sim/v5/orbit_sun_intervals.py', 'ops_sim/v5/orbit_sun_intervals_document.py', 'ops_sim/v5/orbit_sun_local.py', 'ops_sim/v5/orbit_sun_local_document.py', 'ops_sim/v5/orbit_sun_windows.py', 'ops_sim/v5/orbit_sun_windows_document.py', 'ops_sim/v5/orbit_sun_zonotope_intervals.py', 'ops_sim/v5/orbit_sun_zonotope_intervals_document.py', 'ops_sim/v5/orbit_sun_zonotope_local.py', 'ops_sim/v5/orbit_sun_zonotope_local_document.py', 'ops_sim/v5/orbit_sun_zonotope_local_v2.py', 'ops_sim/v5/orbit_sun_zonotope_local_v2_document.py', 'ops_sim/v5/orbit_visibility.py', 'ops_sim/v5/orbit_visibility_grid.py', 'ops_sim/v5/orbit_visibility_windows.py', 'ops_sim/v5/parameters.py', 'ops_sim/v5/payload.py', 'ops_sim/v5/payload_config.py', 'ops_sim/v5/power_loads.py', 'ops_sim/v5/project_diagnostics.py', 'ops_sim/v5/project_intents.py', 'ops_sim/v5/project_offline_guard.py', 'ops_sim/v5/project_runner.py', 'ops_sim/v5/project_store.py', 'ops_sim/v5/project_windows_job.py', 'ops_sim/v5/project_workbench.py', 'ops_sim/v5/project_worker.py', 'ops_sim/v5/provenance.py', 'ops_sim/v5/reconstruction_planning.py', 'ops_sim/v5/rolling_cache.py', 'ops_sim/v5/rolling_contract.py', 'ops_sim/v5/rolling_controller.py', 'ops_sim/v5/rolling_document.py', 'ops_sim/v5/rolling_execution.py', 'ops_sim/v5/rolling_forecast.py', 'ops_sim/v5/rolling_knowledge.py', 'ops_sim/v5/rolling_physics.py', 'ops_sim/v5/rolling_snapshot.py', 'ops_sim/v5/rolling_snapshot_document.py', 'ops_sim/v5/run_config.py', 'ops_sim/v5/solar.py', 'ops_sim/v5/solar_attitude.py', 'ops_sim/v5/solar_lifecycle.py', 'ops_sim/v5/spacecraft_project.py', 'ops_sim/v5/spacecraft_project_document.py', 'ops_sim/v5/state.py', 'ops_sim/v5/storage.py', 'ops_sim/v5/substepped_continuation.py', 'ops_sim/v5/substepped_execution.py', 'ops_sim/v5/sun_table.py', 'ops_sim/v5/sun_table_document.py', 'ops_sim/v5/thermal.py', 'ops_sim/v5/thermal_config.py', 'ops_sim/v5/thermal_coupling.py', 'ops_sim/v5/thermal_routing.py', 'ops_sim/v5/workbench_assets/control.js', 'ops_sim/v5/workbench_assets/index.html', 'ops_sim/v5/workbench_assets/lifecycle.js', 'ops_sim/v5/workbench_assets/workbench.css', 'ops_sim/v5/workbench_assets/workbench.js', 'ops_sim/v5/world.py', 'overview.py', 'paper_suite.py', 'requirements.txt', 'rul.py', 'run.py', 'stationkeeping_report.py', 'tests/fixtures/assembly_05e_nominal.json', 'tests/fixtures/assembly_document_v1.json', 'tests/fixtures/b40_compact.json', 'tests/fixtures/b40_outboard.json', 'tests/fixtures/m2_b11_incoming_box.json', 'tests/fixtures/m7_refused_point_prefix.json', 'tests/fixtures/sun_horizons_20261001.json', 'tests/frozen_release_history.py', 'tests/test_assembly.py', 'tests/test_assembly_attitude.py', 'tests/test_assembly_attitude_3d.py', 'tests/test_assembly_choices.py', 'tests/test_assembly_document.py', 'tests/test_assembly_inputs.py', 'tests/test_assembly_interface_document.py', 'tests/test_assembly_interfaces.py', 'tests/test_assembly_slew_3d.py', 'tests/test_battery_port.py', 'tests/test_battery_port_coupling.py', 'tests/test_battery_port_lifecycle.py', 'tests/test_command_controller.py', 'tests/test_command_document.py', 'tests/test_command_estimation.py', 'tests/test_compact_application.py', 'tests/test_construction_coupling.py', 'tests/test_construction_document.py', 'tests/test_construction_mission.py', 'tests/test_construction_repairs.py', 'tests/test_construction_service.py', 'tests/test_contact_execution.py', 'tests/test_contact_restart.py', 'tests/test_continuous_mission.py', 'tests/test_continuous_profile.py', 'tests/test_continuous_trade.py', 'tests/test_continuous_trade_checks.py', 'tests/test_continuous_trade_io.py', 'tests/test_coupled_downlink.py', 'tests/test_coupled_downlink_restart.py', 'tests/test_data_chronology.py', 'tests/test_design_repair.py', 'tests/test_design_repair_continuation.py', 'tests/test_design_repair_document.py', 'tests/test_design_repair_study.py', 'tests/test_design_trade_campaign.py', 'tests/test_design_trade_continuation.py', 'tests/test_design_trade_design.py', 'tests/test_design_trade_execution.py', 'tests/test_design_trade_heat.py', 'tests/test_design_trade_physics.py', 'tests/test_design_trade_report.py', 'tests/test_design_trade_study.py', 'tests/test_engineering_experiment.py', 'tests/test_environment_forcing.py', 'tests/test_environment_forcing_document.py', 'tests/test_environment_mission.py', 'tests/test_environment_mission_3d.py', 'tests/test_environment_mission_3d_continuation.py', 'tests/test_environment_mission_continuation.py', 'tests/test_environment_mission_general.py', 'tests/test_environment_mission_general_continuation.py', 'tests/test_environment_mission_repairs.py', 'tests/test_environment_physics.py', 'tests/test_eps_stress.py', 'tests/test_experiment_bundle.py', 'tests/test_experiment_codec.py', 'tests/test_experiment_provenance_paths.py', 'tests/test_experiment_restart.py', 'tests/test_harness_document.py', 'tests/test_harness_mass.py', 'tests/test_harness_mission.py', 'tests/test_j2_binding.py', 'tests/test_j2_binding_restart.py', 'tests/test_j2_coefficients.py', 'tests/test_j2_enclosure.py', 'tests/test_j2_seed.py', 'tests/test_j2_segments.py', 'tests/test_j2_segments_document.py', 'tests/test_j2_zonotope.py', 'tests/test_j2_zonotope_incremental.py', 'tests/test_j2_zonotope_segments.py', 'tests/test_j2_zonotope_segments_document.py', 'tests/test_lifecycle_admission.py', 'tests/test_lifecycle_application.py', 'tests/test_lifecycle_calendar.py', 'tests/test_lifecycle_chain.py', 'tests/test_lifecycle_checkpoint.py', 'tests/test_lifecycle_compact.py', 'tests/test_lifecycle_contract.py', 'tests/test_lifecycle_execution.py', 'tests/test_lifecycle_execution_budget.py', 'tests/test_lifecycle_lighting.py', 'tests/test_lifecycle_physics.py', 'tests/test_lifecycle_progress_schema.py', 'tests/test_lifecycle_publication.py', 'tests/test_lifecycle_quiet.py', 'tests/test_lifecycle_quiet_checkpoint.py', 'tests/test_lifecycle_recovery.py', 'tests/test_lifecycle_report.py', 'tests/test_lifecycle_runner_policy.py', 'tests/test_lifecycle_service.py', 'tests/test_lifecycle_service_allocation_r2.py', 'tests/test_lifecycle_service_contract.py', 'tests/test_lifecycle_service_physics.py', 'tests/test_lifecycle_stream.py', 'tests/test_lifecycle_study.py', 'tests/test_lifecycle_world.py', 'tests/test_long_environment.py', 'tests/test_long_general_geometry.py', 'tests/test_long_mission.py', 'tests/test_long_mission_continuation.py', 'tests/test_long_mission_document.py', 'tests/test_long_nominal_provider.py', 'tests/test_mission_camera_3d.py', 'tests/test_mission_continuous_geometry.py', 'tests/test_mission_diagnosis.py', 'tests/test_mission_environment.py', 'tests/test_mission_general_geometry.py', 'tests/test_mission_general_predicates.py', 'tests/test_mission_report.py', 'tests/test_ms_campaign.py', 'tests/test_ms_campaign_restart.py', 'tests/test_ms_comparison.py', 'tests/test_ms_execution.py', 'tests/test_ms_product.py', 'tests/test_ms_restart.py', 'tests/test_operational_protection.py', 'tests/test_operational_restart.py', 'tests/test_operational_standby_allocation.py', 'tests/test_orbit_sun.py', 'tests/test_orbit_sun_document.py', 'tests/test_orbit_sun_intervals.py', 'tests/test_orbit_sun_intervals_document.py', 'tests/test_orbit_sun_local.py', 'tests/test_orbit_sun_local_document.py', 'tests/test_orbit_sun_windows.py', 'tests/test_orbit_sun_windows_document.py', 'tests/test_orbit_sun_zonotope_intervals.py', 'tests/test_orbit_sun_zonotope_intervals_document.py', 'tests/test_orbit_sun_zonotope_local.py', 'tests/test_orbit_sun_zonotope_local_document.py', 'tests/test_orbit_sun_zonotope_local_v2.py', 'tests/test_orbit_sun_zonotope_local_v2_document.py', 'tests/test_project_diagnostics.py', 'tests/test_project_intents.py', 'tests/test_project_runner.py', 'tests/test_project_store.py', 'tests/test_project_workbench.py', 'tests/test_resource_chain_cli.py', 'tests/test_rolling_controller.py', 'tests/test_rolling_document.py', 'tests/test_rolling_execution.py', 'tests/test_rolling_forecast.py', 'tests/test_rolling_history_binding.py', 'tests/test_rolling_knowledge.py', 'tests/test_rolling_snapshot.py', 'tests/test_simulator.py', 'tests/test_solar_application.py', 'tests/test_solar_attitude.py', 'tests/test_solar_checkpoint.py', 'tests/test_solar_lifecycle.py', 'tests/test_solar_retirement.py', 'tests/test_spacecraft_project.py', 'tests/test_stream_admission.py', 'tests/test_substepped_execution.py', 'tests/test_substepped_physics.py', 'tests/test_substepped_restart.py', 'tests/test_sun_table.py', 'tests/test_sun_table_document.py', 'tests/test_v21_coupling.py', 'tests/test_v22_inspect.py', 'tests/test_v23_events.py', 'tests/test_v242_geometry_contacts.py', 'tests/test_v243_contact_cli.py', 'tests/test_v244_contact_logging.py', 'tests/test_v24_final.py', 'tests/test_v24_geometry.py', 'tests/test_v25_operator_view.py', 'tests/test_v26_planning.py', 'tests/test_v27_maneuvers.py', 'tests/test_v281_dynamic_planning_contacts.py', 'tests/test_v28_orbit_evolution.py', 'tests/test_v29_continuation.py', 'tests/test_v29_rul.py', 'tests/test_v29_rul_cli.py', 'tests/test_v2_scenarios.py', 'tests/test_v2_tools.py', 'tests/test_v30_analysis.py', 'tests/test_v30_paper_suite.py', 'tests/test_v31_decision.py', 'tests/test_v31_decision_report.py', 'tests/test_v32_event_lifecycle.py', 'tests/test_v32_event_lifecycle_report.py', 'tests/test_v32b_lifecycle_diagnostics.py', 'tests/test_v32b_lifecycle_seed_finder.py', 'tests/test_v33_debris_risk.py', 'tests/test_v33_debris_risk_report.py', 'tests/test_v342_project_canon.py', 'tests/test_v34_autonomy.py', 'tests/test_v34_autonomy_report.py', 'tests/test_v35_stationkeeping_planning.py', 'tests/test_v36_power_eclipse.py', 'tests/test_v36_thermal_load.py', 'tests/test_v37_pointing.py', 'tests/test_v37_targets.py', 'tests/test_v38_packets.py', 'tests/test_v38b_packet_delivery.py', 'tests/test_v39a_rul_stack.py', 'tests/test_v39b_reliability.py', 'tests/test_v40a_research_suite.py', 'tests/test_v40b_final_research_integration.py', 'tests/test_v50b1_foundation.py', 'tests/test_v50b2_configuration.py', 'tests/test_v50b3_state_domains.py', 'tests/test_v50b4_context_checkpoint.py', 'tests/test_v50d1_time_engine.py', 'tests/test_v50d2_atomic_transitions.py', 'tests/test_v51a_battery_energy.py', 'tests/test_v51b_power_loads.py', 'tests/test_v51c_solar_generation.py', 'tests/test_v51d_eps_engine_integration.py', 'tests/test_v51e_eps_validation.py', 'tests/test_v51f_eps_release_hardening.py', 'tests/test_v51g_numeric_real_hardening.py', 'tests/test_v52a1_thermal_configuration.py', 'tests/test_v52a2_thermal_state_checkpoint.py', 'tests/test_v52b_thermal_physics.py', 'tests/test_v52c1_thermal_forcing.py', 'tests/test_v52c2_heat_routing.py', 'tests/test_v52d1_degradation_state.py', 'tests/test_v52d2a_degradation_physics.py', 'tests/test_v52d2b1_degradation_config_ownership.py', 'tests/test_v52d2b2_degradation_engine_integration.py', 'tests/test_v52e1_eps_thermal_engine.py', 'tests/test_v52e2_degradation_capability_coupling.py', 'tests/test_v52f1_integrated_release.py', 'tests/test_v52f2_final_release_audit.py', 'tests/test_v53a_observation_domain.py', 'tests/test_v53b1_payload_acquisition_config.py', 'tests/test_v53b2_payload_acquisition_physics.py', 'tests/test_v53c1_adcs_maneuver_config.py', 'tests/test_v53c2_adcs_boresight_transition.py', 'tests/test_v53c3_observation_transition_feasibility.py', 'tests/test_v53d_observation_acquisition_composition.py', 'tests/test_v53e1_imaging_eps_resources.py', 'tests/test_v53e2_imaging_thermal_proposal.py', 'tests/test_v53f1_imaging_execution_contracts.py', 'tests/test_v53f2_imaging_authorization.py', 'tests/test_v53f3a_engine_transaction_refactor.py', 'tests/test_v53f3b_imaging_engine_integration.py', 'tests/test_v53f4a_integrated_imaging_demo.py', 'tests/test_v53f4b_final_release_audit.py', 'tests/test_v54a1_onboard_data_volume.py', 'tests/test_v54a2_acquisition_data_record.py', 'tests/test_v54b1_storage_admission.py', 'tests/test_v54b2_persistent_storage_checkpoint.py', 'tests/test_v54c_imaging_storage_authorization.py', 'tests/test_v54d1_engine_precommit_result.py', 'tests/test_v54d2_imaging_storage_engine_integration.py', 'tests/test_v54e_integrated_storage_demo.py', 'tests/test_v54f_final_release_audit.py', 'tests/test_v55a_contact_capacity.py', 'tests/test_v55b_delivery_state_checkpoint.py', 'tests/test_v55c_downlink_transmission.py', 'tests/test_v55d_downlink_engine_integration.py', 'tests/test_v55e_integrated_downlink_demo.py', 'tests/test_v55f_final_release_audit.py', 'tests/test_v56a_frame_transforms.py', 'tests/test_v56a_time_frame_contracts.py', 'tests/test_v56b1_two_body_contracts.py', 'tests/test_v56b1_two_body_propagation.py', 'tests/test_v56b2_checkpoint_binding.py', 'tests/test_v56b2_orbit_binding.py', 'tests/test_v56c1_ground_point_contracts.py', 'tests/test_v56c1_viewing_geometry.py', 'tests/test_v56c2a_ellipsoid_visibility.py', 'tests/test_v56c2a_visibility_contracts.py', 'tests/test_v56c2b_temporal_windows.py', 'tests/test_v56c2b_window_contracts.py', 'tests/test_v56c2c_engine_grid_projection.py', 'tests/test_v56c2c_grid_projection_contracts.py', 'tests/test_v56c3a_ground_contact_contracts.py', 'tests/test_v56c3a_ground_contact_generation.py', 'tests/test_v56c3b_serviceability_binding_contracts.py', 'tests/test_v56c3b_serviceability_geometry.py', 'tests/test_v56d1a_observation_opportunity_contracts.py', 'tests/test_v56d1a_observation_opportunity_geometry.py', 'tests/test_v56d1b_observation_boresight_contracts.py', 'tests/test_v56d1b_observation_boresight_geometry.py', 'tests/test_v56d1c_observation_transition_contracts.py', 'tests/test_v56d1c_observation_transition_geometry.py', 'tests/test_v56d1d_observation_sequence_contracts.py', 'tests/test_v56d1d_observation_sequence_timing.py', 'tests/test_v56d1e_observation_catalog_composition.py', 'tests/test_v56d1e_observation_catalog_contracts.py', 'tests/test_v56f1_j2_gravity_contracts.py', 'tests/test_v56f1_j2_gravity_physics.py', 'tests/test_v56f2_j2_coast_contracts.py', 'tests/test_v56f2_j2_coast_propagation.py', 'tests/test_v56h_frozen_release_compatibility.py', 'tests/test_workbench_control.js')

def trusted_worker_binding():
    """Source-owned producer. Payload cannot choose membership or helper code."""
    source=Path(__file__).resolve().parent
    current={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
    if current!=set(EXPECTED_WORKER_MEMBERS)|{'m8_battery_chain_cli.py'}:raise ValueError('B58 complete source membership drift/pollution')
    return dict(revision='B58_SOLAR_WORKER_SOURCE_V1',source_root=str(source),source_sha256={n:file_sha(source/n) for n in EXPECTED_WORKER_MEMBERS},runtime=runtime_identity(),frozen_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())

def create_for_store(store,chain_id,execution_budget,maximum_primary_segments=5,maximum_output_bytes=128*2**20,maximum_observed_seconds=9600,*,runner=None):
    from ops_sim.v5.lifecycle_chain import LifecycleChain,make_plan
    identifier(chain_id)
    integer(maximum_primary_segments,'B58 primary segments',1,5)
    if store.root_input.battery_port_policy is None:raise ValueError('B58 requires immutable battery port')
    if store.root_input.energy_attitude_policy is None:raise ValueError('B58 resource plan requires explicit solar policy')
    if store.path('resource-chains',chain_id).exists():
        chain=ResourceChain(store,chain_id,runner=runner)
        expected=dict(execution_budget=asdict(execution_budget),maximum_primary_segments=maximum_primary_segments,maximum_output_bytes=maximum_output_bytes,maximum_observed_seconds=maximum_observed_seconds)
        if any(chain.plan[k]!=v for k,v in expected.items()):raise ValueError('duplicate create cannot change solar plan')
        return chain
    original=sha256(('B58_DECLARED_FINITE_RESERVATIONS:'+chain_id).encode()).hexdigest()[:32]
    plan=make_plan(store,chain_id=original,execution_budget=execution_budget,maximum_primary_segments=maximum_primary_segments,maximum_output_bytes=maximum_output_bytes,maximum_observed_seconds=maximum_observed_seconds)
    LifecycleChain(store,original,plan=plan)
    return ResourceChain.create_initial(store,chain_id,trusted_worker_binding(),original,runner=runner)

PLAN_FIELDS=('format','policy','chain_id','controller_sha256','worker_source_identity',
    'worker_manifest_sha256','publication_profile_identity','energy_attitude_policy_identity','root_identity','input_sha256','runtime','original_plan_sha256',
    'original_chain_id','adopted_parent_job_id','adopted_snapshot_sha256',
    'maximum_primary_segments','maximum_observed_seconds','maximum_output_bytes',
    'reserved_diagnostic_slots','execution_budget','execution_budget_identity','plan_identity')
STATE_FIELDS=('format','plan_identity','sequence','previous_sha256','state','command_keys',
    'segments','pending_intent','reason','failed_attempt','observed_seconds','estimate')
SEGMENT_FIELDS=('ordinal','job_id','intent_sha256','checkpoint_sha256','terminal_sha256',
                'clock','observed_seconds','resource_cause')
STATES=('READY_INITIAL','READY_ADOPTED_OUTPUT','RUNNING','DISPATCHING','TIME_BUDGET_CONTINUING',
    'OUTPUT_BUDGET_CONTINUING','USER_PAUSED','COMPLETED','PLAN_EXHAUSTED','ADMISSION_STOP','BLOCKED')

def raw(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def digest(v):return sha256(raw(v)).hexdigest()
def controller_sha():return file_sha(Path(__file__))
def publish(path,value):
    pending=path.with_suffix('.pending');_write_new(pending,raw(value))
    if path.exists():raise ValueError('immutable resource publication already exists')
    os.rename(pending,path) # publish NEW filename; do not replace a reader-held file.

def admit_plan(plan,store,binding,original):
    object_fields(plan,PLAN_FIELDS)
    if plan['format']!=PLAN or plan['policy']!=POLICY or plan['plan_identity']!=digest({k:v for k,v in plan.items() if k!='plan_identity'}):raise ValueError('resource plan version/hash')
    identifier(plan['chain_id']);identifier(plan['original_chain_id'])
    if store.root_input.energy_attitude_policy is None or plan['energy_attitude_policy_identity']!=store.root_input.energy_attitude_policy.identity:raise ValueError('B58 explicit solar root/policy binding')
    if plan['adopted_parent_job_id'] is None:
        if plan['adopted_snapshot_sha256'] is not None:raise ValueError('initial resource plan cannot borrow state')
    else:identifier(plan['adopted_parent_job_id']);identity(plan['adopted_snapshot_sha256'])
    if plan['controller_sha256']!=controller_sha():raise ValueError('resource controller source drift')
    if plan['publication_profile_identity']!=(None if store.publication_profile is None else store.publication_profile.identity):raise ValueError('chain publication profile binding')
    if plan['worker_source_identity']!=store.source_identity or plan['worker_source_identity']!=project_source_identity() or plan['runtime']!=store.runtime or plan['runtime']!=runtime_identity():raise ValueError('frozen worker source/runtime drift')
    if plan['root_identity']!=store.meta['root_identity'] or plan['input_sha256']!=store.meta['input_sha256']:raise ValueError('resource immutable root/input')
    if plan['worker_manifest_sha256']!=digest(binding):raise ValueError('frozen worker manifest binding')
    if type(binding) is not dict or set(binding)!=set(('revision','source_root','source_sha256','runtime','frozen_utc')) or type(binding['source_sha256']) is not dict or set(binding['source_sha256'])!=set(EXPECTED_WORKER_MEMBERS):raise ValueError('explicit B58 worker674 trusted membership manifest')
    if any(type(binding[k]) is not str for k in ('revision','source_root','frozen_utc')):raise ValueError('worker binding text types')
    for name,h in binding['source_sha256'].items():
        if type(name) is not str:raise ValueError('worker manifest path type')
        identity(h)
    from ops_sim.v5.lifecycle_chain import admit_plan as admit_original
    admit_original(original,store)
    if plan['original_plan_sha256']!=digest(original):raise ValueError('original finite plan binding')
    for key in ('maximum_primary_segments','maximum_observed_seconds','maximum_output_bytes','reserved_diagnostic_slots','execution_budget','execution_budget_identity'):
        if type(plan[key]) is not type(original[key]) or plan[key]!=original[key]:raise ValueError('cannot raise or change original reservation: '+key)
    integer(plan['maximum_primary_segments'],'resource primary maximum',1,5)
    integer(plan['maximum_observed_seconds'],'resource elapsed allowance',1,10800)
    integer(plan['maximum_output_bytes'],'resource job output',2**20,128*2**20)
    if type(plan['reserved_diagnostic_slots']) is not int or plan['reserved_diagnostic_slots']!=2:raise ValueError('reserve MAIN/loupe')
    b=admit_budget(plan['execution_budget'],execution_seconds=plan['execution_budget']['hard_execution_seconds'])
    if b.identity!=plan['execution_budget_identity']:raise ValueError('resource budget hash')
    if store.runner_policy is None or plan['maximum_primary_segments']+2>store.maximum_jobs or (plan['maximum_primary_segments']+2)*plan['maximum_output_bytes']+33*2**20>store.maximum_reserved_job_output_bytes:raise ValueError('unchanged finite store reservations')
    return deepcopy(plan)

class ResourceChain:
    def __init__(self,store,chain_id,*,runner=None):
        self.store=store;self.chain_id=identifier(chain_id);self.folder=store.path('resource-chains',chain_id)
        self.lock=threading.RLock();self.runner=runner or LifecycleRunner(store)
        self.binding=_read(self.folder/'frozen-worker.json',2**20)
        self.original=_read(self.folder/'original-plan.json')
        self.plan=admit_plan(_read(self.folder/'plan.json'),store,self.binding,self.original)
        self._source_admit();self._states()

    @classmethod
    def create_initial(cls,store,chain_id,binding,original_chain_id,*,runner=None):
        """New original experiment: automatic resource chain from its initial authority."""
        identifier(chain_id);identifier(original_chain_id)
        if store.jobs():raise ValueError('initial resource plan requires empty store')
        folder=store.path('resource-chains',chain_id)
        if folder.exists():raise ValueError('new explicit resource plan required')
        original=_read(store.path('chains',original_chain_id,'plan.json'))
        p=dict(format=PLAN,policy=POLICY,chain_id=chain_id,controller_sha256=controller_sha(),energy_attitude_policy_identity=store.root_input.energy_attitude_policy.identity,
            worker_source_identity=store.source_identity,worker_manifest_sha256=digest(binding),publication_profile_identity=None if store.publication_profile is None else store.publication_profile.identity,
            root_identity=store.meta['root_identity'],input_sha256=store.meta['input_sha256'],runtime=store.runtime,
            original_plan_sha256=digest(original),original_chain_id=original_chain_id,
            adopted_parent_job_id=None,adopted_snapshot_sha256=None,
            **{k:deepcopy(original[k]) for k in ('maximum_primary_segments','maximum_observed_seconds','maximum_output_bytes','reserved_diagnostic_slots','execution_budget','execution_budget_identity')})
        p['plan_identity']=digest(p);admit_plan(p,store,binding,original)
        source=Path(binding['source_root']).resolve()
        if source!=Path(__file__).resolve().parent or any(file_sha(source/n)!=h for n,h in binding['source_sha256'].items()):raise ValueError('frozen worker admission before publication')
        _write_new(folder/'frozen-worker.json',binding,2**20);_write_new(folder/'original-plan.json',original);_write_new(folder/'plan.json',p)
        temporary=object.__new__(cls);temporary.folder=folder;temporary.plan=p
        temporary._append(dict(state='READY_INITIAL',command_keys=[],segments=[],pending_intent=None,
            reason='NEW_INITIAL_AUTHORITY_NO_BORROWED_STATE',failed_attempt=None,observed_seconds=0.,estimate=None),initial=True)
        return cls(store,chain_id,runner=runner)

    @classmethod
    def adopt(cls,store,chain_id,binding,original_chain_id,parent_job_id,snapshot_sha256,*,runner=None):
        identifier(chain_id);identifier(original_chain_id);identifier(parent_job_id);identity(snapshot_sha256)
        folder=store.path('resource-chains',chain_id)
        if folder.exists():raise ValueError('new explicit resource plan required; no rewrite')
        if len(store.jobs())!=1 or store.jobs()[0]['job_id']!=parent_job_id:raise ValueError('adoption requires the sole existing settled first primary')
        original=_read(store.path('chains',original_chain_id,'plan.json'))
        from ops_sim.v5.lifecycle_chain import admit_plan as admit_original
        admit_original(original,store)
        p=dict(format=PLAN,policy=POLICY,chain_id=chain_id,controller_sha256=controller_sha(),energy_attitude_policy_identity=store.root_input.energy_attitude_policy.identity,
            worker_source_identity=store.source_identity,worker_manifest_sha256=digest(binding),publication_profile_identity=None if store.publication_profile is None else store.publication_profile.identity,
            root_identity=store.meta['root_identity'],input_sha256=store.meta['input_sha256'],runtime=store.runtime,
            original_plan_sha256=digest(original),original_chain_id=original_chain_id,
            adopted_parent_job_id=parent_job_id,adopted_snapshot_sha256=snapshot_sha256,
            **{k:deepcopy(original[k]) for k in ('maximum_primary_segments','maximum_observed_seconds','maximum_output_bytes','reserved_diagnostic_slots','execution_budget','execution_budget_identity')})
        p['plan_identity']=digest(p);admit_plan(p,store,binding,original)
        temporary=object.__new__(cls);temporary.store=store;temporary.plan=p
        source=Path(binding['source_root']).resolve()
        if source!=Path(__file__).resolve().parent or any(file_sha(source/n)!=h for n,h in binding['source_sha256'].items()):raise ValueError('frozen worker admission before publication')
        segment=temporary.validate_job(store.job(parent_job_id),1)
        if segment['checkpoint_sha256']!=snapshot_sha256 or segment['resource_cause']!='OUTPUT':raise ValueError('only exact settled first output prefix is adopted')
        _write_new(folder/'frozen-worker.json',binding,2**20);_write_new(folder/'original-plan.json',original);_write_new(folder/'plan.json',p)
        value=dict(state='READY_ADOPTED_OUTPUT',command_keys=[],segments=[segment],pending_intent=None,reason='EXPLICIT_V2_ADOPTION_OF_SETTLED_OUTPUT_PREFIX_NO_REFUND',failed_attempt=None,observed_seconds=segment['observed_seconds'],estimate=None)
        temporary.folder=folder;temporary._append(value,initial=True)
        return cls(store,chain_id,runner=runner)

    def _source_admit(self):
        admit_plan(self.plan,self.store,self.binding,self.original);self.store._pinned()
        source=Path(self.binding['source_root']).resolve()
        if source!=Path(__file__).resolve().parent:raise ValueError('explicit original worker source directory')
        for name,h in self.binding['source_sha256'].items():
            p=Path(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or file_sha(source/p)!=h:raise ValueError('frozen worker byte drift: '+name)
        if _read(self.folder/'plan.json')!=self.plan or _read(self.folder/'frozen-worker.json',2**20)!=self.binding or _read(self.folder/'original-plan.json')!=self.original:raise ValueError('resource saved authority drift')

    def _states(self):
        paths=sorted((self.folder/'states').glob('*.json'))
        if not 1<=len(paths)<=128:raise ValueError('finite resource journal')
        last=None;previous='0'*64
        for n,path in enumerate(paths,1):
            data=path.read_bytes();v=json.loads(data);object_fields(v,STATE_FIELDS)
            if len(data)>256*2**10 or raw(v)!=data or path.name!=f'{n:04}.json' or v['format']!=STATE or type(v['sequence']) is not int or v['sequence']!=n or v['previous_sha256']!=previous or v['plan_identity']!=self.plan['plan_identity'] or type(v['state']) is not str or v['state'] not in STATES:raise ValueError('resource journal binding')
            if type(v['segments']) is not list or not 0<=len(v['segments'])<=self.plan['maximum_primary_segments']:raise ValueError('resource primary population')
            for ordinal,segment in enumerate(v['segments'],1):
                object_fields(segment,SEGMENT_FIELDS)
                if type(segment['ordinal']) is not int or segment['ordinal']!=ordinal:raise ValueError('resource ordinal')
                identifier(segment['job_id']);identity(segment['intent_sha256']);identity(segment['checkpoint_sha256']);identity(segment['terminal_sha256']);integer(segment['clock'],'resource clock')
                if segment['resource_cause'] not in ('OUTPUT','TIME','USER','TARGET') or type(segment['observed_seconds']) not in (int,float) or not 0<=segment['observed_seconds']<float('inf'):raise ValueError('resource segment fields')
            if type(v['command_keys']) is not list or len(v['command_keys'])>32 or len(set(v['command_keys']))!=len(v['command_keys']):raise ValueError('resource command keys')
            for k in v['command_keys']:identifier(k)
            if v['reason'] is not None and (type(v['reason']) is not str or len(v['reason'])>4096):raise ValueError('resource diagnostic reason')
            if v['observed_seconds']!=sum(x['observed_seconds'] for x in v['segments']):raise ValueError('resource settled elapsed no refund')
            if last is not None and (v['segments'][:len(last['segments'])]!=last['segments'] or not set(last['command_keys'])<=set(v['command_keys'])):raise ValueError('resource lineage cannot rewind')
            if v['pending_intent'] is not None and v['pending_intent']!=self._intent(len(v['segments'])+1,v['segments'][-1] if v['segments'] else None):raise ValueError('resource pending intent drift')
            previous=sha256(data).hexdigest();last=v
        return last,previous

    def _append(self,value,*,initial=False):
        if initial:n=1;previous='0'*64
        else:old,previous=self._states();n=old['sequence']+1
        if n>128:raise ValueError('resource journal exhausted')
        v=dict(value,format=STATE,plan_identity=self.plan['plan_identity'],sequence=n,previous_sha256=previous)
        publish(self.folder/'states'/f'{n:04}.json',v);return v
    def _save(self,prior,**updates):
        v={k:deepcopy(v) for k,v in prior.items() if k not in ('format','plan_identity','sequence','previous_sha256')};v.update(updates);return self._append(v)
    def _intent(self,ordinal,parent):
        p=self.plan;b=admit_budget(p['execution_budget'],execution_seconds=p['execution_budget']['hard_execution_seconds'])
        key=sha256((p['plan_identity']+':'+str(ordinal)+':'+('INITIAL' if parent is None else parent['checkpoint_sha256'])).encode()).hexdigest()[:32]
        return make_intent(p['root_identity'],key=key,parent_job_id=None if parent is None else parent['job_id'],snapshot_sha256=None if parent is None else parent['checkpoint_sha256'],execution_seconds=b.hard_execution_seconds,maximum_output_bytes=p['maximum_output_bytes'],execution_budget=b,publication_profile=self.store.publication_profile,profile_bound=True)

    def validate_job(self,job,ordinal):
        if job['status'] not in TERMINAL or job['ownership_valid'] is not True or job['launch'] is None or job['launch'].get('forced_interruption') is not False or job['launch'].get('timeout') is not False or job['launch'].get('unexpected') is not None:raise ValueError('resource refuses unknown/forced/failure authority')
        r=job['result']
        if r is None:raise ValueError('resource needs terminal and settled receipt')
        _admit_execution_terminal(job,r)
        app=r['application_status']
        if app=='COMPLETED_WINDOW' and r['clock']==self.store.root_input.end_seconds:cause='TARGET'
        elif app=='INCOMPLETE_BUDGET_STOP' and r['reason']=='WORKER_LOCAL_SOFT_BUDGET_PAID_PREFIX':cause='TIME'
        elif app=='INCOMPLETE_APPLICATION_ADMISSION' and r['reason']==OUTPUT_REASON:cause='OUTPUT'
        elif app=='INCOMPLETE_STOP' and r['reason']=='USER_COOPERATIVE_STOP_BEFORE_NEXT_MODEL_TRANSITION':cause='USER'
        else:raise ValueError('resource terminal reason is not an approved settled resource cut')
        if cause!='TARGET' and r['status']!='ACTIVE':raise ValueError('resource native must remain ACTIVE')
        if job['source_identity']!=self.store.meta['source_identity'] or job['runtime']!=self.store.meta['runtime'] or job['root_identity']!=self.store.meta['root_identity']:raise ValueError('resource worker/root/runtime binding')
        cp=r['checkpoint'];folder=self.store.path('jobs',job['job_id'])
        if cp['kind']!='FINAL' or cp not in job['checkpoints'] or cp['clock']!=r['clock'] or cp['bindings']!=make_bindings(self.store.root_input,cp['clock']):raise ValueError('resource exact final native')
        _settled_publication_work(folder,self.store.root_input,job,r);_admit_publication(folder,cp,self.store.root_input,settled=True)
        data=(folder/cp['file']).read_bytes();admit_checkpoint(data,self.store.root_input,expected_sha256=cp['sha256'],expected_bindings=cp['bindings'])
        _verify_checkpoint_streams(folder,cp,self.store.root_input,reserve=lambda n:self.store._reserve_saved_read(job['job_id'],n))
        if file_sha(folder/'terminal.json')!=sha256(raw(r)).hexdigest():raise ValueError('resource exact terminal bytes')
        elapsed=job['launch']['observed_envelope_seconds']
        if type(elapsed) not in (int,float) or not 0<=elapsed<float('inf'):raise ValueError('resource finite envelope')
        return dict(ordinal=ordinal,job_id=job['job_id'],intent_sha256=digest(job['intent']),checkpoint_sha256=cp['sha256'],terminal_sha256=file_sha(folder/'terminal.json'),clock=r['clock'],observed_seconds=elapsed,resource_cause=cause)

    def _paused(self,state):
        consumed=0
        for path in sorted((self.folder/'states').glob('*.json')):
            v=_read(path)
            if v['reason']=='EXPLICIT_CONTINUE':consumed=max(consumed,v['sequence']-1)
        for path in self.folder.glob('pause-*.json'):
            v=_read(path);object_fields(v,('plan_identity','sequence'))
            if v['plan_identity']!=self.plan['plan_identity'] or path.name!=f"pause-{v['sequence']:04}.json":raise ValueError('resource pause binding')
            if v['sequence']>consumed:return True
        return False
    def snapshot(self):
        self._source_admit();state,_=self._states();job=None
        if self.runner.active is not None:job=self.store.job(self.runner.active)
        return dict(plan=deepcopy(self.plan),state=state,active_job_id=self.runner.active,
            live_progress=None if job is None else job['progress'],active_job_created_utc=None if job is None else job['created_utc'])
    def stop(self):
        with self.lock:
            state=self.snapshot()['state'];path=self.folder/f"pause-{state['sequence']:04}.json"
            if not path.exists():publish(path,dict(plan_identity=self.plan['plan_identity'],sequence=state['sequence']))
            if self.runner.active is not None:self.runner.stop(self.runner.active)
            elif state['pending_intent'] is not None:
                job=self.store.reconcile(state['pending_intent'])
                if job is not None and job['status'] not in TERMINAL:
                    marker=self.store.path('jobs',job['job_id'],'stop-request.json')
                    if not marker.exists():_write_stop_request(marker,job)
            return self.snapshot()

    def run(self,key):
        identifier(key)
        with self.lock:
            state=self.snapshot()['state']
            if key in state['command_keys'] or state['state'] in ('COMPLETED','BLOCKED','PLAN_EXHAUSTED','ADMISSION_STOP'):return self.snapshot()
            if list((self.folder/'states').glob('*.pending')):raise ValueError('unpublished resource state; no retry')
            owner=self.folder/'owner.json';token=dict(token=uuid.uuid4().hex,PID=os.getpid(),plan_identity=self.plan['plan_identity'])
            _write_new(owner,token)
            state=self._save(state,command_keys=[*state['command_keys'],key],reason='EXPLICIT_CONTINUE')
        try:
            while True:
                self.snapshot()
                if self._paused(state):state=self._save(state,state='USER_PAUSED',reason='USER_STOP');break
                if len(state['segments'])>=self.plan['maximum_primary_segments']:state=self._save(state,state='PLAN_EXHAUSTED',reason='ORIGINAL_FINITE_PRIMARY_LIMIT');break
                b=self.plan['execution_budget'];remaining=self.plan['maximum_observed_seconds']-state['observed_seconds']
                if remaining<b['hard_execution_seconds']+2:state=self._save(state,state='ADMISSION_STOP',reason='CANNOT_RESERVE_FULL_NEXT_SLOT');break
                parent=state['segments'][-1] if state['segments'] else None
                if parent is not None and self.validate_job(self.store.job(parent['job_id']),parent['ordinal'])!=parent:raise ValueError('resource stale/tampered parent')
                ordinal=len(state['segments'])+1;intent=self._intent(ordinal,parent)
                with self.lock:
                    if self._paused(state):state=self._save(state,state='USER_PAUSED',reason='USER_STOP');break
                    state=self._save(state,state='DISPATCHING',pending_intent=intent,reason=None)
                    job=self.runner.submit(intent);state=self._save(state,state='RUNNING')
                thread=self.runner.thread
                if thread is not None:thread.join(b['hard_execution_seconds']+3)
                if thread is not None and thread.is_alive():raise RuntimeError('resource owned worker did not settle')
                job=self.store.job(job['job_id']);segment=self.validate_job(job,ordinal)
                if segment['clock']<=(parent['clock'] if parent is not None else self.store.root_input.start_seconds):raise ValueError('resource no progress; no blind retry')
                segments=[*state['segments'],segment];elapsed=sum(x['observed_seconds'] for x in segments)
                estimate=dict(method='OBSERVED_CUMULATIVE_RATE_NOT_RUNTIME_BOUND',remaining_seconds=elapsed*(self.store.root_input.end_seconds-segment['clock'])/(segment['clock']-self.store.root_input.start_seconds))
                state=self._save(state,segments=segments,observed_seconds=elapsed,pending_intent=None,estimate=estimate)
                if segment['clock']==self.store.root_input.end_seconds:state=self._save(state,state='COMPLETED',reason='IMMUTABLE_TARGET');break
                if segment['resource_cause']=='USER' or self._paused(state):state=self._save(state,state='USER_PAUSED',reason='USER_STOP');break
                if estimate['remaining_seconds']>self.plan['maximum_observed_seconds']-elapsed:state=self._save(state,state='ADMISSION_STOP',reason='MEASURED_RATE_CANNOT_FIT');break
                state=self._save(state,state='OUTPUT_BUDGET_CONTINUING' if segment['resource_cause']=='OUTPUT' else 'TIME_BUDGET_CONTINUING',reason=segment['resource_cause'])
        except BaseException as error:
            failed=None
            if state['pending_intent'] is not None:
                failed=self.store.reconcile(state['pending_intent'])
            state=self._save(state,state='BLOCKED',reason=type(error).__name__+': '+str(error),failed_attempt=failed)
            raise
        finally:
            if _read(owner)!=token:raise RuntimeError('foreign resource owner; preserve')
            owner.unlink()
        return self.snapshot()


class ResourceWorkbench:
    """Explicit same-origin adapter around the existing Workbench application.

    Does not replace its scientific owners, old routes, assets or store metadata.
    The additional page/JS are bound by this controller's plan hash, separately
    from the unmodified worker source hash. Reopen never starts its run thread.
    """
    def __init__(self,app,chain):
        self.app=app;self.chain=chain;self.thread=None;self.error=None
        rid=chain.store.meta['root_identity'];key=(rid,chain.chain_id)
        app.lifecycle.stores[rid]=chain.store
        app.lifecycle.runners[rid]=chain.runner
        self.key=key
    def continue_command(self,body):
        object_fields(body,('command_key',));identifier(body['command_key'])
        with self.app.dispatch_lock:
            state=self.chain.snapshot()['state']
            if body['command_key'] in state['command_keys']:return self.chain.snapshot()
            if self.thread is not None and self.thread.is_alive():return self.chain.snapshot()
            if self.app.runner.active is not None or self.app.lifecycle.active is not None:raise ValueError('another owned worker active')
            def execute():
                try:self.chain.run(body['command_key'])
                except BaseException as error:
                    import traceback
                    self.error=dict(type=type(error).__name__,reason=str(error),traceback=traceback.format_exc())
            self.thread=threading.Thread(target=execute,name='B58-solar-resource-chain',daemon=False)
            # Existing application shutdown/active-owner checks include this
            # adapter between segments too. No second scientific worker can fit.
            self.app.lifecycle.chains[self.key]=self.chain
            self.app.lifecycle.chain_threads[self.key]=self.thread
            self.thread.start();return self.chain.snapshot()
    def handler(self):
        adapter=self;base=self.app.handler()
        class Handler(base):
            def do_GET(self):
                if self.path not in ('/resource-chain','/resource-chain.js','/api/resource-chain/state'):return super().do_GET()
                try:
                    self.guard()
                    if self.path=='/resource-chain':
                        page=('<!doctype html><meta charset="utf-8"><title>Resource chain</title>'
                            '<meta name="csrf" content="'+adapter.app.token+'"><link rel="stylesheet" href="/workbench.css">'
                            '<h1>Bounded solar resource chain V3</h1><p>Paid panel Sun-point / charge policy. Time/output budget: automatic continuation. User Stop: pause.</p>'
                            '<button id="continue">Run / Continue</button><button id="stop">User Stop</button>'
                            '<p id="elapsed"></p><pre id="status"></pre><script src="/resource-chain.js"></script>')
                        self.respond(200,page.encode(),'text/html; charset=utf-8',True)
                    elif self.path=='/resource-chain.js':self.respond(200,RESOURCE_JS.encode(),'text/javascript; charset=utf-8')
                    else:self.respond(200,adapter.chain.snapshot())
                except (ValueError,TypeError,KeyError,OSError) as e:self.respond(400,dict(error=str(e)))
            def do_POST(self):
                if self.path not in ('/api/resource-chain/continue','/api/resource-chain/stop'):return super().do_POST()
                try:
                    self.guard(True);lengths=self.headers.get_all('Content-Length')
                    if lengths is None or len(lengths)!=1 or not lengths[0].isdigit() or not 0<int(lengths[0])<=4096:raise ValueError('bounded exact resource request length')
                    from ops_sim.v5.experiment_codec import parse_json
                    body=parse_json(self.rfile.read(int(lengths[0])).decode())
                    if self.path.endswith('/continue'):result=adapter.continue_command(body)
                    else:object_fields(body,());result=adapter.chain.stop()
                    self.respond(200,result)
                except (ValueError,TypeError,KeyError,OSError,RuntimeError) as e:self.respond(400,dict(error=str(e)))
        return Handler
    def close(self):
        if self.thread is not None and self.thread.is_alive():self.chain.stop()
        self.chain.runner.close()
        if self.thread is not None:self.thread.join(3)
        if self.thread is not None and self.thread.is_alive():raise RuntimeError('resource adapter thread not settled')


RESOURCE_JS=r"""'use strict';
const token=document.querySelector('meta[name=csrf]').content;
let latest=null;
async function api(path,body){const r=await fetch('/api/resource-chain/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':token},body:body===undefined?undefined:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error);return v;}
async function refresh(){latest=await api('state');const key='resource-command-'+latest.plan.plan_identity,pending=localStorage.getItem(key);if(pending&&latest.state.command_keys.includes(pending))localStorage.removeItem(key);document.getElementById('status').textContent=JSON.stringify({state:latest.state.state,reason:latest.state.reason,segments:latest.state.segments,settled_envelope_seconds:latest.state.observed_seconds,model_progress:latest.live_progress,estimate:latest.state.estimate},null,2);document.getElementById('elapsed').textContent=latest.active_job_created_utc?'Current job UTC age (not worker CPU/monotonic): '+Math.max(0,(Date.now()-Date.parse(latest.active_job_created_utc))/1000).toFixed(1)+' s':'No active owned worker';}
document.getElementById('continue').onclick=async()=>{try{await refresh();const key='resource-command-'+latest.plan.plan_identity;let command=localStorage.getItem(key);if(!command){command=crypto.randomUUID().replaceAll('-','');localStorage.setItem(key,command);}await api('continue',{command_key:command});await refresh();}catch(e){document.getElementById('status').textContent=String(e);}};
document.getElementById('stop').onclick=async()=>{try{await api('stop',{});await refresh();}catch(e){document.getElementById('status').textContent=String(e);}};
refresh().catch(e=>document.getElementById('status').textContent=String(e));setInterval(()=>refresh().catch(e=>document.getElementById('status').textContent=String(e)),1500);
"""

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--store',type=Path,required=True);p.add_argument('--chain-id',required=True)
    sub=p.add_subparsers(dest='action',required=True)
    c=sub.add_parser('adopt');c.add_argument('--worker-binding',type=Path,required=True);c.add_argument('--original-chain-id',required=True);c.add_argument('--parent-job',required=True);c.add_argument('--snapshot-sha256',required=True)
    c=sub.add_parser('create');c.add_argument('--worker-binding',type=Path,required=True);c.add_argument('--original-chain-id',required=True)
    c=sub.add_parser('serve');c.add_argument('--app-store',type=Path,required=True);c.add_argument('--port',type=int,default=8765)
    c=sub.add_parser('run');c.add_argument('--command-key',required=True)
    sub.add_parser('status');sub.add_parser('stop');a=p.parse_args(argv);store=LifecycleStore(a.store)
    if a.action=='adopt':chain=ResourceChain.adopt(store,a.chain_id,_read(a.worker_binding,2**20),a.original_chain_id,a.parent_job,a.snapshot_sha256)
    elif a.action=='create':chain=ResourceChain.create_initial(store,a.chain_id,_read(a.worker_binding,2**20),a.original_chain_id)
    else:chain=ResourceChain(store,a.chain_id)
    if a.action=='serve':
        from http.server import ThreadingHTTPServer
        from ops_sim.v5.project_store import ProjectStore
        from ops_sim.v5.lifecycle_application import LifecycleWorkspace
        from ops_sim.v5.project_workbench import Workbench
        integer(a.port,'loopback port',0,65535)
        projects=ProjectStore(a.app_store,store.root_input.base,create=not a.app_store.exists())
        workspace=LifecycleWorkspace(projects.path('lifecycle'),project_store=projects)
        app=Workbench(projects,lifecycle_workspace=workspace);adapter=ResourceWorkbench(app,chain)
        server=ThreadingHTTPServer(('127.0.0.1',a.port),adapter.handler());app.server=server
        try:
            print('http://127.0.0.1:'+str(server.server_port)+'/resource-chain',flush=True)
            server.serve_forever(poll_interval=.1)
        finally:adapter.close();workspace.close();app.runner.close();server.server_close();app.release_owner()
        return
    try:result=chain.run(a.command_key) if a.action=='run' else chain.stop() if a.action=='stop' else chain.snapshot();print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except KeyboardInterrupt:chain.stop();raise
    finally:chain.runner.close()

if __name__=='__main__':main()
