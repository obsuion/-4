import csv
from pathlib import Path

import pytest

import paper_suite
from ops_sim.contacts import GeometryContactModel
from ops_sim.research_design import (
    FINAL_V40_ABLATION_CONFIGURATIONS,
    FINAL_V40_ABLATION_REFERENCE,
    FINAL_V40_CONFIGURATION,
    LEGACY_V30_CORE_CONFIGURATION,
    MODEL_SELECTOR_FIELDS,
)


REQUIRED_RAW_FIELDS = {
    "suite_profile",
    "experiment_group",
    "configuration",
    "configuration_label",
    "policy",
    "scenario",
    "seed",
    *MODEL_SELECTOR_FIELDS,
}


def _design(*args: str):
    parser = paper_suite.build_parser()
    return paper_suite.build_experiment_design(parser.parse_args(list(args)))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_profile_defaults_and_canonical_final_configuration() -> None:
    default = _design("--skip-rul")
    legacy = _design(
        "--suite-profile", "legacy_v30", "--skip-rul"
    )

    assert default.suite_profile == "final_v40"
    assert default.core_configuration is FINAL_V40_CONFIGURATION
    assert default.core_configuration.selector_provenance() == {
        "contact_model": "geometry",
        "operator_view": "delayed_telemetry",
        "planning_model": "risk_aware",
        "maneuver_model": "stationkeeping_proxy",
        "orbit_evolution_model": "drift_proxy",
        "stationkeeping_planning_model": "drift_aware",
        "event_lifecycle_model": "warning_proxy",
        "debris_risk_model": "severity_proxy",
        "autonomy_model": "contingency_plan",
        "power_model": "eclipse_proxy",
        "thermal_model": "load_stress_proxy",
        "target_model": "scene_scheduling_proxy",
        "pointing_model": "bounded_pointing_proxy",
        "packet_model": "packet_proxy",
        "packet_delivery_model": "loss_retry_proxy",
        "packet_drop_fraction_proxy": 0.10,
    }
    assert legacy.suite_profile == "legacy_v30"
    assert legacy.core_configuration is LEGACY_V30_CORE_CONFIGURATION
    assert legacy.core_configuration.contact_model == "synthetic"


def test_final_profile_rejects_obsolete_include_geometry_flag() -> None:
    with pytest.raises(ValueError, match="already the primary contact model"):
        _design("--include-geometry")


def test_every_complete_stack_selector_reaches_simulator(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class RecordingSimulator:
        def __init__(self, policy, scenario, config, **kwargs):
            captured.update(kwargs)

        def run(self, years):
            return object()

    def summary(_result, _years):
        return {
            "policy": "adaptive",
            "scenario": "nominal",
            **{
                field: captured[field]
                for field in MODEL_SELECTOR_FIELDS
                if field != "contact_model"
            },
            "packet_delivery_seed": captured["packet_delivery_seed"],
        }

    monkeypatch.setattr(paper_suite, "Simulator", RecordingSimulator)
    monkeypatch.setattr(paper_suite, "_summary_row", summary)
    row = paper_suite.run_simulator_case(
        suite_profile="final_v40",
        policy_name="adaptive",
        scenario_name="nominal",
        years=0.0,
        seed=40,
        configuration=FINAL_V40_CONFIGURATION,
        event_catalog=None,
        experiment_group="core",
    )

    assert isinstance(captured["contact_model"], GeometryContactModel)
    expected = FINAL_V40_CONFIGURATION.simulator_kwargs(seed=40)
    assert {
        key: value for key, value in captured.items() if key != "contact_model"
    } == expected
    assert row["packet_delivery_seed"] == 40
    assert {
        field: row[field] for field in MODEL_SELECTOR_FIELDS
    } == FINAL_V40_CONFIGURATION.selector_provenance()


def test_quick_final_profile_writes_geometry_rows_and_full_provenance(
    tmp_path,
) -> None:
    results_dir = tmp_path / "final_v40"
    assert paper_suite.main([
        "--suite-profile", "final_v40",
        "--quick",
        "--skip-plots",
        "--skip-rul",
        "--results-dir", str(results_dir),
        "--seed", "40",
    ]) == 0

    core = _read_csv(results_dir / "raw" / "core_summary.csv")
    ablations = _read_csv(results_dir / "raw" / "ablation_raw.csv")
    assert len(core) == 2
    assert len(ablations) == 11
    assert {row["contact_model"] for row in core} == {"geometry"}
    assert {row["suite_profile"] for row in core + ablations} == {
        "final_v40"
    }
    assert all(REQUIRED_RAW_FIELDS <= row.keys() for row in core + ablations)
    assert all(
        row[field] != ""
        for row in core + ablations
        for field in MODEL_SELECTOR_FIELDS
    )
    for row in core:
        for field, expected in (
            FINAL_V40_CONFIGURATION.selector_provenance().items()
        ):
            actual = row[field]
            if field == "packet_drop_fraction_proxy":
                assert float(actual) == expected
            else:
                assert actual == expected
        assert row["packet_delivery_seed"] == "40"

    synthetic = [
        row for row in ablations if row["contact_model"] == "synthetic"
    ]
    assert [row["configuration_label"] for row in synthetic] == [
        "synthetic_contact_control"
    ]
    layer_rows = _read_csv(
        results_dir / "tables" / "ablation_summary.csv"
    )
    assert len(layer_rows) == 10
    assert {row["reference_configuration"] for row in layer_rows} == {
        "final_full_stack"
    }


def test_legacy_profile_preserves_bounded_v30_architecture() -> None:
    full = _design("--suite-profile", "legacy_v30", "--skip-rul")
    quick = _design(
        "--suite-profile", "legacy_v30", "--quick", "--skip-rul"
    )

    assert full.core_configuration.contact_model == "synthetic"
    assert full.core_run_count == 48
    assert full.ablation_run_count == 15
    assert [item.label for item in full.ablation_configurations] == [
        "A_omniscient_reactive_none_fixed",
        "B_delayed_reactive_none_fixed",
        "C_delayed_risk_aware_none_fixed",
        "D_delayed_risk_aware_stationkeeping_fixed",
        "E_delayed_risk_aware_stationkeeping_drift",
    ]
    assert quick.core_run_count == 2
    assert quick.ablation_run_count == 5


def test_common_catalog_is_reused_and_packet_seed_is_profile_seed(
    monkeypatch,
) -> None:
    design = _design("--skip-rul")
    shared_catalog = object()
    calls: list[dict[str, object]] = []

    def record_case(**kwargs):
        calls.append(kwargs)
        return {"sensitivity_label": kwargs["configuration"].label}

    monkeypatch.setattr(paper_suite, "run_simulator_case", record_case)
    paper_suite.run_core_matrix(design, shared_catalog)
    paper_suite.run_ablation_matrix(design, shared_catalog)

    stochastic_calls = [
        call for call in calls
        if call["scenario_name"] == paper_suite.STOCHASTIC_SCENARIO
    ]
    assert stochastic_calls
    assert all(call["event_catalog"] is shared_catalog for call in stochastic_calls)
    assert {call["seed"] for call in calls} == {design.seed}
    assert {
        configuration.simulator_kwargs(seed=design.seed)[
            "packet_delivery_seed"
        ]
        for configuration in design.ablation_configurations
    } == {design.seed}


def test_final_layer_ablations_change_only_declared_fields() -> None:
    reference = FINAL_V40_ABLATION_REFERENCE.selector_provenance()
    expected_changes = {
        "final_full_stack": set(),
        "no_delayed_telemetry": {"operator_view"},
        "no_risk_aware_planning": {"planning_model"},
        "no_drift_aware_stationkeeping": {
            "stationkeeping_planning_model"
        },
        "no_lifecycle_debris_layer": {
            "event_lifecycle_model", "debris_risk_model"
        },
        "legacy_power_thermal": {"power_model", "thermal_model"},
        "legacy_target_pointing": {"target_model", "pointing_model"},
        "ideal_packet_delivery": {"packet_delivery_model"},
        "no_autonomy": {"autonomy_model"},
        "limited_maneuver_autonomy": {"autonomy_model"},
        "synthetic_contact_control": {"contact_model"},
    }

    for configuration in FINAL_V40_ABLATION_CONFIGURATIONS:
        provenance = configuration.selector_provenance()
        changed = {
            field for field in MODEL_SELECTOR_FIELDS
            if provenance[field] != reference[field]
        }
        assert changed == expected_changes[configuration.label]

    assert FINAL_V40_CONFIGURATION.autonomy_model == "contingency_plan"
    limited = next(
        item for item in FINAL_V40_ABLATION_CONFIGURATIONS
        if item.label == "limited_maneuver_autonomy"
    )
    assert limited.autonomy_model == "limited_maneuver_authority"
    synthetic = FINAL_V40_ABLATION_CONFIGURATIONS[-1]
    assert synthetic.label == "synthetic_contact_control"
    assert synthetic.contact_model == "synthetic"


def test_generated_methods_and_limitations_are_profile_accurate(
    tmp_path,
) -> None:
    final_dir = tmp_path / "final"
    legacy_dir = tmp_path / "legacy"
    final_dir.mkdir()
    legacy_dir.mkdir()
    final = _design("--quick", "--skip-rul")
    legacy = _design(
        "--suite-profile", "legacy_v30", "--quick", "--skip-rul"
    )

    for design, directory in ((final, final_dir), (legacy, legacy_dir)):
        paper_suite.write_paper_markdown(
            design=design,
            ranking_rows=[],
            ablation_summary_rows=[],
            rul_summary_rows=[],
            paper_dir=directory,
        )

    final_methods = final_dir.joinpath(
        "methods_autogenerated.md"
    ).read_text(encoding="utf-8")
    legacy_methods = legacy_dir.joinpath(
        "methods_autogenerated.md"
    ).read_text(encoding="utf-8")
    limitations = final_dir.joinpath(
        "limitations_autogenerated.md"
    ).read_text(encoding="utf-8")

    assert "`final_v40`" in final_methods
    assert "primary scientific matrix uses geometry contacts" in final_methods
    assert "stationkeeping_planning_model=drift_aware" in final_methods
    assert "packet_delivery_model=loss_retry_proxy" in final_methods
    assert "explicit synthetic stress assumption" in final_methods
    assert "`legacy_v30`" in legacy_methods
    assert "historical synthetic-contact core" in legacy_methods
    assert "regression and control architecture" in legacy_methods
    assert "bounded lifecycle/debris" in limitations
    assert "no real conjunction screening, collision probability" in limitations
    assert "Bounded packet accounting" in limitations
    assert "no real RF propagation" in limitations
    assert "no model is calibrated from real telemetry" in limitations
    assert "no operational event lifecycle or debris-warning model" not in limitations


def test_final_decision_report_receives_primary_complete_stack(
    monkeypatch, tmp_path
) -> None:
    design = _design(
        "--quick", "--skip-rul", "--include-decision-report"
    )
    captured: dict[str, object] = {}

    def record_report(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(paper_suite, "run_decision_report", record_report)
    paper_suite.run_suite_decision_report(
        design, tmp_path, quick=True
    )

    assert captured["policy"] == "adaptive"
    assert captured["scenario"] == "nominal"
    assert captured["seed"] == design.seed
    assert {
        field: captured[field] for field in MODEL_SELECTOR_FIELDS
    } == FINAL_V40_CONFIGURATION.selector_provenance()


def test_final_v40_rul_uses_the_v40b_complete_stack_extension(
    tmp_path,
) -> None:
    design = _design("--quick")
    assert design.rul_configuration is FINAL_V40_CONFIGURATION
    assert design.rul_is_final_stack is True
    paper_suite.write_paper_markdown(
        design=design,
        ranking_rows=[],
        ablation_summary_rows=[],
        rul_summary_rows=[],
        paper_dir=tmp_path,
    )
    methods = tmp_path.joinpath("methods_autogenerated.md").read_text(
        encoding="utf-8"
    )
    assert "RUL matrix uses the same canonical complete-stack" in methods
    assert "conditional population includes only samples alive" in methods
    assert "not a real lifetime model" in methods


def test_v40a_documentation_records_profiles_boundaries_and_roadmap() -> None:
    documents = {
        name: " ".join(Path(name).read_text(encoding="utf-8").split())
        for name in ("README.md", "PROJECT_CANON.md", "FINAL_CONFIG.md")
    }
    combined = " ".join(documents.values())

    assert "V4.0A final geometry-first research-suite architecture" in combined
    assert "`final_v40`" in combined
    assert "`legacy_v30`" in combined
    assert "Synthetic contacts are not the primary scientific model" in combined
    assert "`contingency_plan`" in combined
    assert "`limited_maneuver_authority` is a sensitivity case" in combined
    assert "`0.10` is an explicit synthetic stress assumption" in combined
    assert "adds no spacecraft physics" in combined
    assert "V4.0B" in combined
    assert "V4.1" in combined
    assert "V4.2" in combined
    assert "validation, calibration, and final paper suite" not in combined
