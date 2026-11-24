"""Immutable experiment definitions for the V4 research-suite profiles.

This module describes experiment architecture only.  It does not alter any
simulator, subsystem, RUL, or reliability behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


FINAL_V40_PROFILE = "final_v40"
LEGACY_V30_PROFILE = "legacy_v30"
SUITE_PROFILES = (FINAL_V40_PROFILE, LEGACY_V30_PROFILE)

# This tuple is the authoritative ordered provenance contract for one complete
# simulator configuration.  Helpers below derive their mappings from it.
MODEL_SELECTOR_FIELDS = (
    "contact_model",
    "operator_view",
    "planning_model",
    "maneuver_model",
    "orbit_evolution_model",
    "stationkeeping_planning_model",
    "event_lifecycle_model",
    "debris_risk_model",
    "autonomy_model",
    "power_model",
    "thermal_model",
    "target_model",
    "pointing_model",
    "packet_model",
    "packet_delivery_model",
    "packet_drop_fraction_proxy",
)


@dataclass(frozen=True)
class ExperimentConfiguration:
    """One explicit complete-stack simulator configuration."""

    label: str
    contact_model: str
    operator_view: str
    planning_model: str
    maneuver_model: str
    orbit_evolution_model: str
    stationkeeping_planning_model: str
    event_lifecycle_model: str
    debris_risk_model: str
    autonomy_model: str
    power_model: str
    thermal_model: str
    target_model: str
    pointing_model: str
    packet_model: str
    packet_delivery_model: str
    packet_drop_fraction_proxy: float
    applicable_policies: tuple[str, ...] | None = None

    def selector_provenance(self) -> dict[str, object]:
        """Return the ordered complete-stack raw-provenance mapping."""
        return {
            field: getattr(self, field) for field in MODEL_SELECTOR_FIELDS
        }

    def simulator_kwargs(self, *, seed: int) -> dict[str, object]:
        """Return selector kwargs accepted directly by ``Simulator``."""
        kwargs = self.selector_provenance()
        kwargs.pop("contact_model")
        kwargs["packet_delivery_seed"] = seed
        return kwargs

    def decision_report_kwargs(self) -> dict[str, object]:
        """Return the complete selector surface accepted by the report API."""
        return self.selector_provenance()

    def rul_kwargs(self) -> dict[str, object]:
        """Return complete-stack selectors in the estimator's convention."""
        kwargs = self.selector_provenance()
        kwargs["contact_model_name"] = kwargs.pop("contact_model")
        return kwargs


@dataclass(frozen=True)
class ExperimentDesign:
    """Resolved, bounded experiment design used by the CLI and tests."""

    suite_profile: str
    years: float
    seed: int
    core_policies: tuple[str, ...]
    core_scenarios: tuple[str, ...]
    core_configuration: ExperimentConfiguration
    ablation_policies: tuple[str, ...]
    ablation_scenario: str
    ablation_configurations: tuple[ExperimentConfiguration, ...]
    ablation_comparisons: tuple[tuple[str, str], ...]
    run_rul: bool
    rul_policies: tuple[str, ...]
    rul_samples: int
    rul_start_year: float
    rul_horizon_years: float
    rul_configuration: ExperimentConfiguration
    bootstrap_replicates: int
    bootstrap_seed: int
    rul_is_final_stack: bool = False
    include_decision_report: bool = False

    @property
    def core_run_count(self) -> int:
        return len(self.core_policies) * len(self.core_scenarios)

    @property
    def ablation_run_count(self) -> int:
        return sum(
            len(
                configuration.applicable_policies
                if configuration.applicable_policies is not None
                else self.ablation_policies
            )
            for configuration in self.ablation_configurations
        )

    @property
    def rul_simulation_count(self) -> int:
        if not self.run_rul:
            return 0
        return len(self.rul_policies) * self.rul_samples

    @property
    def rul_run_count(self) -> int:
        """Alias for the number of independently simulated RUL samples."""
        return self.rul_simulation_count

    @property
    def decision_run_count(self) -> int:
        return 1 if self.include_decision_report else 0

    @property
    def is_final_v40(self) -> bool:
        return self.suite_profile == FINAL_V40_PROFILE


FINAL_V40_CONFIGURATION = ExperimentConfiguration(
    label="final_geometry_full_stack",
    contact_model="geometry",
    operator_view="delayed_telemetry",
    planning_model="risk_aware",
    maneuver_model="stationkeeping_proxy",
    orbit_evolution_model="drift_proxy",
    stationkeeping_planning_model="drift_aware",
    event_lifecycle_model="warning_proxy",
    debris_risk_model="severity_proxy",
    autonomy_model="contingency_plan",
    power_model="eclipse_proxy",
    thermal_model="load_stress_proxy",
    target_model="scene_scheduling_proxy",
    pointing_model="bounded_pointing_proxy",
    packet_model="packet_proxy",
    packet_delivery_model="loss_retry_proxy",
    packet_drop_fraction_proxy=0.10,
)

# The layer table uses the requested reference label while the primary core
# retains the canonical configuration label above.
FINAL_V40_ABLATION_REFERENCE = replace(
    FINAL_V40_CONFIGURATION,
    label="final_full_stack",
)

FINAL_V40_ABLATION_CONFIGURATIONS = (
    FINAL_V40_ABLATION_REFERENCE,
    replace(
        FINAL_V40_ABLATION_REFERENCE,
        label="no_delayed_telemetry",
        operator_view="omniscient",
    ),
    replace(
        FINAL_V40_ABLATION_REFERENCE,
        label="no_risk_aware_planning",
        planning_model="reactive",
    ),
    replace(
        FINAL_V40_ABLATION_REFERENCE,
        label="no_drift_aware_stationkeeping",
        stationkeeping_planning_model="legacy",
    ),
    replace(
        FINAL_V40_ABLATION_REFERENCE,
        label="no_lifecycle_debris_layer",
        event_lifecycle_model="none",
        debris_risk_model="legacy",
    ),
    replace(
        FINAL_V40_ABLATION_REFERENCE,
        label="legacy_power_thermal",
        power_model="legacy",
        thermal_model="legacy",
    ),
    replace(
        FINAL_V40_ABLATION_REFERENCE,
        label="legacy_target_pointing",
        target_model="legacy",
        pointing_model="legacy",
    ),
    replace(
        FINAL_V40_ABLATION_REFERENCE,
        label="ideal_packet_delivery",
        packet_delivery_model="ideal",
    ),
    replace(
        FINAL_V40_ABLATION_REFERENCE,
        label="no_autonomy",
        autonomy_model="none",
    ),
    replace(
        FINAL_V40_ABLATION_REFERENCE,
        label="limited_maneuver_autonomy",
        autonomy_model="limited_maneuver_authority",
    ),
    replace(
        FINAL_V40_ABLATION_REFERENCE,
        label="synthetic_contact_control",
        contact_model="synthetic",
    ),
)

FINAL_V40_ABLATION_COMPARISONS = tuple(
    (FINAL_V40_ABLATION_REFERENCE.label, configuration.label)
    for configuration in FINAL_V40_ABLATION_CONFIGURATIONS[1:]
)


def _legacy_configuration(
    label: str,
    *,
    contact_model: str = "synthetic",
    operator_view: str = "omniscient",
    planning_model: str = "reactive",
    maneuver_model: str = "none",
    orbit_evolution_model: str = "fixed",
    applicable_policies: tuple[str, ...] | None = None,
) -> ExperimentConfiguration:
    return ExperimentConfiguration(
        label=label,
        contact_model=contact_model,
        operator_view=operator_view,
        planning_model=planning_model,
        maneuver_model=maneuver_model,
        orbit_evolution_model=orbit_evolution_model,
        stationkeeping_planning_model="legacy",
        event_lifecycle_model="none",
        debris_risk_model="legacy",
        autonomy_model="none",
        power_model="legacy",
        thermal_model="legacy",
        target_model="legacy",
        pointing_model="legacy",
        packet_model="legacy",
        packet_delivery_model="ideal",
        packet_drop_fraction_proxy=0.10,
        applicable_policies=applicable_policies,
    )


LEGACY_V30_CORE_CONFIGURATION = _legacy_configuration(
    "core_advanced",
    operator_view="delayed_telemetry",
    planning_model="risk_aware",
    maneuver_model="stationkeeping_proxy",
    orbit_evolution_model="drift_proxy",
)

LEGACY_V30_ABLATION_CONFIGURATIONS = (
    _legacy_configuration("A_omniscient_reactive_none_fixed"),
    _legacy_configuration(
        "B_delayed_reactive_none_fixed",
        operator_view="delayed_telemetry",
    ),
    _legacy_configuration(
        "C_delayed_risk_aware_none_fixed",
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
    ),
    _legacy_configuration(
        "D_delayed_risk_aware_stationkeeping_fixed",
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
    ),
    _legacy_configuration(
        "E_delayed_risk_aware_stationkeeping_drift",
        operator_view="delayed_telemetry",
        planning_model="risk_aware",
        maneuver_model="stationkeeping_proxy",
        orbit_evolution_model="drift_proxy",
    ),
)

LEGACY_V30_GEOMETRY_ABLATION_CONFIGURATION = _legacy_configuration(
    "F_geometry_delayed_risk_aware_stationkeeping_drift",
    contact_model="geometry",
    operator_view="delayed_telemetry",
    planning_model="risk_aware",
    maneuver_model="stationkeeping_proxy",
    orbit_evolution_model="drift_proxy",
    applicable_policies=("adaptive",),
)

LEGACY_V30_ABLATION_COMPARISONS = (
    (
        "A_omniscient_reactive_none_fixed",
        "B_delayed_reactive_none_fixed",
    ),
    (
        "B_delayed_reactive_none_fixed",
        "C_delayed_risk_aware_none_fixed",
    ),
    (
        "C_delayed_risk_aware_none_fixed",
        "D_delayed_risk_aware_stationkeeping_fixed",
    ),
    (
        "D_delayed_risk_aware_stationkeeping_fixed",
        "E_delayed_risk_aware_stationkeeping_drift",
    ),
)

LEGACY_V30_GEOMETRY_ABLATION_COMPARISON = (
    "E_delayed_risk_aware_stationkeeping_drift",
    "F_geometry_delayed_risk_aware_stationkeeping_drift",
)
