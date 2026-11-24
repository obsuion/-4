"""Focused V3.4.2 project-canon and public-spec consistency tests."""

from pathlib import Path

from ops_sim.config import DEFAULT_CONFIG


ROOT = Path(__file__).resolve().parents[1]


def _document(name: str) -> str:
    path = ROOT / name
    assert path.is_file()
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_project_canon_records_architectural_boundaries() -> None:
    canon = _document("PROJECT_CANON.md")

    required = (
        "synthetic contacts are baseline/regression controls",
        "geometry + `drift_proxy` is the final research direction",
        "uploaded daily plan -> backup -> emergency_beacon",
        "v3.4 autonomy does not replace the fallback ladder",
        "ground-only warnings do not make the spacecraft aware",
        "lifecycle warnings do not refresh delayed telemetry",
        "scheduled future events remain hidden before `warning_hour`",
        "not official kazeosat-1 software",
        "not a physical digital twin",
    )
    for phrase in required:
        assert phrase in canon


def test_public_spec_records_all_values_and_proxy_distinctions() -> None:
    spec = _document("KAZEOSAT_PUBLIC_SPEC.md")

    required = (
        "2.10",
        "3.70",
        "1200 w",
        "270 mbit/s",
        "x-band",
        "sun-synchronous",
        "750 km",
        "98.5",
        "qpsk",
        "820 kg",
        "1 m",
        "panchromatic",
        "multispectral",
        "20 x 20 km",
        "3 to 5 days",
        "220,000",
        "2.025 gb/min",
        "2.0 gb/min",
    )
    for phrase in required:
        assert phrase in spec


def test_final_config_separates_research_and_regression_paths() -> None:
    config = _document("FINAL_CONFIG.md")

    required = (
        "contact_model = geometry",
        "orbit_evolution_model = drift_proxy",
        "operator_view = delayed_telemetry",
        "planning_model = risk_aware",
        "maneuver_model = stationkeeping_proxy",
        "event_lifecycle_model = warning_proxy",
        "debris_risk_model = severity_proxy",
        "autonomy_model = contingency_plan or limited_maneuver_authority",
        "contact_model = synthetic",
        "baseline/regression",
    )
    for phrase in required:
        assert phrase in config


def test_readme_links_all_canon_documents() -> None:
    readme = _document("README.md")

    assert "[project canon](project_canon.md)" in readme
    assert "(kazeosat_public_spec.md)" in readme
    assert "(final_config.md)" in readme
    assert "98.5-degree inclination" in readme


def test_default_reference_inclination_matches_public_spec() -> None:
    assert DEFAULT_CONFIG.orbit_inclination_deg == 98.5
