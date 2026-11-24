"""Focused tests for the isolated V5.0B1 foundation."""

import ast
from dataclasses import FrozenInstanceError
import importlib
from pathlib import Path

import pytest

from ops_sim.v5.ids import (
    AuthorityId,
    CommandId,
    ControllerId,
    DataProductId,
    EnvironmentId,
    FlightRulesId,
    ManeuverId,
    MissionRequestId,
    ModelManifestId,
    NumericalConfigId,
    ParameterId,
    PlanId,
    ScenarioId,
    SourceRecordId,
    SpacecraftConfigurationId,
    SubsystemConfigurationId,
    TelemetrySnapshotId,
    ThermalLinkId,
    ThermalNodeId,
    WorldEventId,
    WorldId,
)
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
    SensitivityRange,
)


ROOT = Path(__file__).resolve().parents[1]
V5_PACKAGE = ROOT / "ops_sim" / "v5"

ID_CASES = (
    (ParameterId, "eps.battery.nominal-energy", "parameter"),
    (SourceRecordId, "s003-battery-study-01", "source"),
    (
        SpacecraftConfigurationId,
        "reference-optical",
        "spacecraft-config",
    ),
    (
        SubsystemConfigurationId,
        "reference-battery",
        "subsystem-config",
    ),
    (AuthorityId, "ground-authority-0001", "authority"),
    (
        TelemetrySnapshotId,
        "snapshot-0001",
        "telemetry-snapshot",
    ),
    (NumericalConfigId, "primary-step", "numerical-config"),
    (EnvironmentId, "level1-environment", "environment"),
    (FlightRulesId, "primary-flight-rules", "flight-rules"),
    (ScenarioId, "nominal-world", "scenario"),
    (WorldId, "world_0001", "world"),
    (ModelManifestId, "level1-optical", "model-manifest"),
    (ControllerId, "rolling-horizon", "controller"),
    (MissionRequestId, "request_00017", "mission-request"),
    (DataProductId, "product_00017", "data-product"),
    (PlanId, "plan_00017", "plan"),
    (WorldEventId, "radiation-0001", "event"),
    (CommandId, "command_00017", "command"),
    (ManeuverId, "maneuver_00017", "maneuver"),
    (ThermalNodeId, "battery", "thermal-node"),
    (ThermalLinkId, "bus-battery", "thermal-link"),
)


def test_concrete_id_prefixes_are_unique() -> None:
    prefixes = [id_type.prefix for id_type, _, _ in ID_CASES]

    assert len(prefixes) == len(set(prefixes))


@pytest.mark.parametrize("id_type,value,prefix", ID_CASES)
def test_every_concrete_id_has_stable_canonical_form(
    id_type, value, prefix
) -> None:
    identifier = id_type(value)

    assert identifier.value == value
    assert identifier.canonical == f"{prefix}:{value}"
    assert str(identifier) == identifier.canonical
    assert hash(identifier) == hash(id_type(value))
    assert identifier == id_type(value)
    assert not hasattr(identifier, "__dict__")
    with pytest.raises(FrozenInstanceError):
        identifier.value = "replacement"


@pytest.mark.parametrize("id_type,value,prefix", ID_CASES)
def test_every_concrete_id_round_trips_from_canonical(
    id_type, value, prefix
) -> None:
    canonical = f"{prefix}:{value}"

    parsed = id_type.from_canonical(canonical)

    assert type(parsed) is id_type
    assert parsed == id_type(value)


def test_ids_are_immutable_and_type_sensitive() -> None:
    parameter = ParameterId("shared-value")

    with pytest.raises(FrozenInstanceError):
        parameter.value = "replacement"
    assert parameter != SourceRecordId("shared-value")


@pytest.mark.parametrize("id_type,value,prefix", ID_CASES)
def test_wrong_canonical_prefix_is_rejected(id_type, value, prefix) -> None:
    wrong_prefix = "world" if prefix != "world" else "parameter"

    with pytest.raises(ValueError):
        id_type.from_canonical(f"{wrong_prefix}:{value}")


@pytest.mark.parametrize(
    "invalid",
    (
        "",
        " leading-space",
        "trailing-space ",
        "Reference Optical",
        "contains:colon",
        "contains/slash",
        "two..segments",
        "-leading-separator",
        "trailing-separator-",
    ),
)
def test_invalid_id_values_are_rejected(invalid: str) -> None:
    with pytest.raises(ValueError):
        ParameterId(invalid)


def test_non_string_and_overlong_id_values_are_rejected() -> None:
    assert ParameterId("a" * 128).value == "a" * 128
    with pytest.raises(TypeError):
        ParameterId(17)
    with pytest.raises(ValueError):
        ParameterId("a" * 129)


def test_canonical_parser_rejects_non_string_and_malformed_values() -> None:
    with pytest.raises(TypeError):
        ParameterId.from_canonical(17)
    with pytest.raises(ValueError):
        ParameterId.from_canonical("parameter:")
    with pytest.raises(ValueError):
        ParameterId.from_canonical("parameter:contains:colon")


def test_provenance_enums_have_exact_values() -> None:
    assert tuple(item.value for item in ProvenanceClass) == (
        "PUBLIC_SPECIFICATION",
        "LITERATURE_VALUE",
        "DERIVED_VALUE",
        "EXPLICIT_MODEL_ASSUMPTION",
    )
    assert tuple(item.value for item in ProvenanceStatus) == (
        "TO_RESEARCH",
        "TO_VERIFY",
        "VERIFIED",
        "REJECTED",
        "SUPERSEDED",
    )


def test_sensitivity_range_accepts_ordered_and_equal_bounds() -> None:
    assert SensitivityRange(1.0, 2.0) == SensitivityRange(1.0, 2.0)
    assert SensitivityRange(1.0, 1.0).lower == 1.0


def test_sensitivity_range_rejects_reversed_nonfinite_and_bool_bounds() -> None:
    with pytest.raises(ValueError):
        SensitivityRange(2.0, 1.0)
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            SensitivityRange(value, 1.0)
        with pytest.raises(ValueError):
            SensitivityRange(0.0, value)
    with pytest.raises(TypeError):
        SensitivityRange(False, 1.0)
    with pytest.raises(TypeError):
        SensitivityRange(0.0, True)


def _provenance(**changes) -> ParameterProvenance:
    values = {
        "parameter_id": ParameterId("eps.battery.nominal-energy"),
        "classification": ProvenanceClass.PUBLIC_SPECIFICATION,
        "units": "Wh",
        "source_ids": (SourceRecordId("s001-reference"),),
        "status": ProvenanceStatus.VERIFIED,
    }
    values.update(changes)
    return ParameterProvenance(**values)


def test_valid_public_and_literature_provenance() -> None:
    public = _provenance()
    literature = _provenance(
        classification=ProvenanceClass.LITERATURE_VALUE,
        source_ids=(SourceRecordId("s003-battery-study-01"),),
        status=ProvenanceStatus.TO_VERIFY,
    )

    assert public.classification is ProvenanceClass.PUBLIC_SPECIFICATION
    assert literature.classification is ProvenanceClass.LITERATURE_VALUE


def test_valid_derived_and_explicit_assumption_provenance() -> None:
    derived = _provenance(
        classification=ProvenanceClass.DERIVED_VALUE,
        source_ids=(),
        status=ProvenanceStatus.TO_RESEARCH,
        derivation="Computed from documented parent quantities.",
    )
    assumption = _provenance(
        classification=ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
        units="1",
        source_ids=(),
        status=ProvenanceStatus.TO_RESEARCH,
        rationale="Required to bound the initial architecture comparison.",
        sensitivity_range=SensitivityRange(0.5, 1.5),
    )

    assert derived.derivation is not None
    assert assumption.units == "1"
    assert assumption.sensitivity_range == SensitivityRange(0.5, 1.5)


def test_parameter_provenance_is_immutable_and_slotted() -> None:
    provenance = _provenance()

    with pytest.raises(FrozenInstanceError):
        provenance.units = "kWh"
    assert not hasattr(provenance, "__dict__")
    assert isinstance(hash(provenance), int)


@pytest.mark.parametrize("units", ("", " ", " Wh", "Wh "))
def test_empty_or_unstripped_units_are_rejected(units: str) -> None:
    with pytest.raises(ValueError):
        _provenance(units=units)


def test_duplicate_and_invalid_source_ids_are_rejected() -> None:
    source = SourceRecordId("s003-battery-study-01")
    with pytest.raises(ValueError):
        _provenance(source_ids=(source, source))
    with pytest.raises(TypeError):
        _provenance(source_ids=[source])
    with pytest.raises(TypeError):
        _provenance(source_ids=(ParameterId("not-a-source"),))


@pytest.mark.parametrize(
    "classification",
    (
        ProvenanceClass.PUBLIC_SPECIFICATION,
        ProvenanceClass.LITERATURE_VALUE,
    ),
)
@pytest.mark.parametrize(
    "status", (ProvenanceStatus.VERIFIED, ProvenanceStatus.TO_VERIFY)
)
def test_verified_or_to_verify_external_values_require_a_source(
    classification, status
) -> None:
    with pytest.raises(ValueError):
        _provenance(
            classification=classification,
            source_ids=(),
            status=status,
        )


@pytest.mark.parametrize(
    "classification",
    (
        ProvenanceClass.PUBLIC_SPECIFICATION,
        ProvenanceClass.LITERATURE_VALUE,
    ),
)
def test_to_research_external_values_may_have_no_source(
    classification,
) -> None:
    result = _provenance(
        classification=classification,
        source_ids=(),
        status=ProvenanceStatus.TO_RESEARCH,
    )

    assert result.source_ids == ()


def test_derived_value_requires_derivation() -> None:
    with pytest.raises(ValueError):
        _provenance(
            classification=ProvenanceClass.DERIVED_VALUE,
            source_ids=(),
            status=ProvenanceStatus.TO_RESEARCH,
        )


def test_explicit_assumption_requires_rationale() -> None:
    with pytest.raises(ValueError):
        _provenance(
            classification=ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            source_ids=(),
            status=ProvenanceStatus.TO_RESEARCH,
        )


@pytest.mark.parametrize(
    "changes",
    (
        {"rationale": ""},
        {"rationale": " rationale"},
        {"derivation": ""},
        {"derivation": "derivation "},
    ),
)
def test_empty_or_unstripped_optional_text_is_rejected(changes) -> None:
    with pytest.raises(ValueError):
        _provenance(**changes)


def test_rejected_and_superseded_metadata_remains_constructible() -> None:
    rejected = _provenance(
        source_ids=(),
        status=ProvenanceStatus.REJECTED,
        rationale="Rejected after source review.",
    )
    superseded = _provenance(
        source_ids=(),
        status=ProvenanceStatus.SUPERSEDED,
        rationale="Superseded by a later provenance record.",
    )

    assert rejected.status is ProvenanceStatus.REJECTED
    assert superseded.status is ProvenanceStatus.SUPERSEDED


def _imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node, node.module or ""


def _is_v5_import(
    node: ast.Import | ast.ImportFrom,
    module: str,
) -> bool:
    """Return whether one AST import targets the isolated V5 namespace."""
    if isinstance(node, ast.Import):
        return module == "ops_sim.v5" or module.startswith("ops_sim.v5.")

    if node.level > 0:
        return (
            module == "v5"
            or module.startswith("v5.")
            or (
                not module
                and any(alias.name == "v5" for alias in node.names)
            )
        )

    return (
        module == "ops_sim.v5"
        or module.startswith("ops_sim.v5.")
        or (
            module == "ops_sim"
            and any(alias.name == "v5" for alias in node.names)
        )
    )


@pytest.mark.parametrize(
    "source",
    (
        "import ops_sim.v5",
        "import ops_sim.v5.ids",
        "from ops_sim.v5 import ids",
        "from ops_sim.v5.ids import ParameterId",
        "from ops_sim import v5",
        "from . import v5",
        "from .v5 import ids",
        "from ..v5 import ids",
    ),
)
def test_v5_import_detector_recognizes_all_supported_forms(
    source: str,
) -> None:
    imports = list(_imports(ast.parse(source)))

    assert any(_is_v5_import(node, module) for node, module in imports)


@pytest.mark.parametrize(
    "source",
    (
        "import ops_simulator",
        "import ops_sim.v50",
        "from ops_sim import config",
        "from another_package import v5",
    ),
)
def test_v5_import_detector_ignores_unrelated_imports(source: str) -> None:
    imports = list(_imports(ast.parse(source)))

    assert not any(_is_v5_import(node, module) for node, module in imports)


def _legacy_production_python_files() -> tuple[Path, ...]:
    package_files = [
        path
        for path in (ROOT / "ops_sim").rglob("*.py")
        if V5_PACKAGE not in path.parents
    ]
    root_scripts = list(ROOT.glob("*.py"))
    return tuple(
        sorted(
            (*package_files, *root_scripts),
            key=lambda path: path.as_posix(),
        )
    )


def test_all_v5_sources_obey_the_isolated_import_boundary() -> None:
    forbidden_top_level = {
        "decision_report",
        "overview",
        "paper_suite",
        "reporting",
        "rul",
        "run",
    }
    for path in sorted(V5_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node, module in _imports(tree):
            if isinstance(node, ast.ImportFrom) and node.level > 1:
                pytest.fail(f"{path.name} has an import escaping ops_sim.v5")
            import_level = node.level if isinstance(node, ast.ImportFrom) else 0
            allowed_v5_namespace = (
                module == "ops_sim.v5"
                or module.startswith("ops_sim.v5.")
            )
            if import_level == 0 and (
                module == "ops_sim"
                or (
                    module.startswith("ops_sim.")
                    and not allowed_v5_namespace
                )
            ):
                pytest.fail(f"{path.name} imports legacy module {module}")
            root_module = module.partition(".")[0]
            if root_module in forbidden_top_level or root_module.endswith(
                "_report"
            ):
                pytest.fail(f"{path.name} imports forbidden module {module}")
            if isinstance(node, (ast.Import, ast.ImportFrom)) and any(
                alias.name == "DEFAULT_CONFIG" for alias in node.names
            ):
                pytest.fail(f"{path.name} imports DEFAULT_CONFIG")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "DEFAULT_CONFIG":
                pytest.fail(f"{path.name} references DEFAULT_CONFIG")
            if isinstance(node, ast.Attribute) and node.attr == "DEFAULT_CONFIG":
                pytest.fail(f"{path.name} references DEFAULT_CONFIG")
            if isinstance(node, ast.ImportFrom) and any(
                alias.name == "*" for alias in node.names
            ):
                pytest.fail(f"{path.name} uses a wildcard import")


def test_v4_modules_do_not_import_the_v5_package() -> None:
    for path in _legacy_production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node, module in _imports(tree):
            assert not _is_v5_import(node, module), (
                f"legacy production module {path.relative_to(ROOT)} imports V5"
            )


def test_v5_foundation_modules_import_successfully() -> None:
    assert importlib.import_module("ops_sim.v5.ids")
    assert importlib.import_module("ops_sim.v5.provenance")
