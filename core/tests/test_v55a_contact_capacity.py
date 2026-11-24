"""Externally supplied contacts and nominal capacity for V5.5A."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, MISSING, fields, replace
from fractions import Fraction
from inspect import Parameter, signature
from math import isfinite
from pathlib import Path
import subprocess

import pytest

from ops_sim.v5.checkpoint import CURRENT_CHECKPOINT_SCHEMA_VERSION
from ops_sim.v5.communications import (
    DownlinkCapacityProposal,
    ServiceableGroundContact,
    compute_downlink_capacity,
)
import ops_sim.v5.communications as communications_module
from ops_sim.v5.configuration import CommunicationsConfig
import ops_sim.v5.ids as ids_module
from ops_sim.v5.ids import (
    GroundContactId,
    GroundStationId,
    ParameterId,
    SourceRecordId,
    SubsystemConfigurationId,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops_sim" / "v5" / "communications.py"
CONFIGURATION_PATH = ROOT / "ops_sim" / "v5" / "configuration.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
MODEL_STATUS_PATH = ROOT / "MODEL_STATUS.md"
PUBLIC_SPEC_PATH = ROOT / "KAZEOSAT_PUBLIC_SPEC.md"
V54_FINAL_COMMIT = "526d131a8ca2df7fdce25d90619f5545806eac1d"
V55A_COMMIT = "b6c42a79c7ed28c6abb6685692e0a117cbdd26dc"
AIRBUS_SOURCE_ID = "s001-airbus-kazeosat-1-technical-sheet-2019"


def _provenance(
    *,
    classification: ProvenanceClass = ProvenanceClass.PUBLIC_SPECIFICATION,
    status: ProvenanceStatus = ProvenanceStatus.VERIFIED,
    source_ids: tuple[SourceRecordId, ...] | None = None,
) -> ParameterProvenance:
    if source_ids is None:
        source_ids = (SourceRecordId(AIRBUS_SOURCE_ID),)
    return ParameterProvenance(
        ParameterId("communications.nominal-downlink-data-rate"),
        classification,
        "bit/s",
        source_ids,
        status,
        rationale=(
            "Airbus-reported nominal X-band instrument telemetry link rate."
            if classification is ProvenanceClass.PUBLIC_SPECIFICATION
            else "Synthetic communications rate used only by a unit test."
        ),
    )


def _parameter(
    value: object = 270_000_000.0,
    *,
    provenance: ParameterProvenance | None = None,
) -> ScalarParameter:
    return ScalarParameter(
        value,
        _provenance() if provenance is None else provenance,
    )


def _synthetic_parameter() -> ScalarParameter:
    return _parameter(
        1_000_000.0,
        provenance=_provenance(
            classification=ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            status=ProvenanceStatus.TO_RESEARCH,
            source_ids=(),
        ),
    )


def _config(value: object = 270_000_000.0) -> CommunicationsConfig:
    return CommunicationsConfig(
        SubsystemConfigurationId("v55a-communications"),
        _parameter(value),
    )


def _contact(
    *,
    start: int = 100,
    end: int = 160,
) -> ServiceableGroundContact:
    return ServiceableGroundContact(
        GroundContactId("v55a-contact"),
        GroundStationId("astana"),
        start,
        end,
    )


def _run_git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def test_contact_and_station_ids_use_exact_canonical_prefixes() -> None:
    contact_id = GroundContactId("pass-001")
    station_id = GroundStationId("astana-main")

    assert contact_id.canonical == "ground-contact:pass-001"
    assert station_id.canonical == "ground-station:astana-main"
    assert GroundContactId.from_canonical(contact_id.canonical) == contact_id
    assert GroundStationId.from_canonical(station_id.canonical) == station_id
    assert type(contact_id) is GroundContactId
    assert type(station_id) is GroundStationId
    assert ids_module.__all__.index("GroundContactId") < (
        ids_module.__all__.index("GroundStationId")
    ) < ids_module.__all__.index("GroundTargetId")


def test_contact_contract_is_exact_frozen_slotted_and_required() -> None:
    contact = _contact()

    assert tuple(field.name for field in fields(ServiceableGroundContact)) == (
        "contact_id",
        "ground_station_id",
        "start_time_seconds",
        "end_time_seconds",
    )
    assert ServiceableGroundContact.__dataclass_params__.frozen
    assert not hasattr(contact, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(ServiceableGroundContact)
    )
    with pytest.raises(FrozenInstanceError):
        contact.end_time_seconds = 161


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    (
        ("contact_id", object()),
        ("ground_station_id", object()),
        ("start_time_seconds", True),
        ("start_time_seconds", 1.0),
        ("end_time_seconds", False),
        ("end_time_seconds", 2.0),
    ),
)
def test_contact_requires_exact_field_types(field_name, invalid) -> None:
    with pytest.raises(TypeError, match=field_name):
        replace(_contact(), **{field_name: invalid})


@pytest.mark.parametrize(
    ("start", "end"),
    ((-1, 1), (0, 0), (2, 1)),
)
def test_contact_requires_nonnegative_positive_interval(start, end) -> None:
    with pytest.raises(ValueError):
        _contact(start=start, end=end)


def test_contact_revalidates_corrupted_ids() -> None:
    contact_id = GroundContactId("pass-001")
    object.__setattr__(contact_id, "value", "CORRUPTED")
    with pytest.raises(ValueError, match="StableId value"):
        replace(_contact(), contact_id=contact_id)

    station_id = GroundStationId("astana")
    object.__setattr__(station_id, "value", "CORRUPTED")
    with pytest.raises(ValueError, match="StableId value"):
        replace(_contact(), ground_station_id=station_id)


def test_contact_has_half_open_semantics_without_derived_or_geometry_fields() -> None:
    contact = _contact(start=100, end=107)

    assert contact.end_time_seconds - contact.start_time_seconds == 7
    names = {field.name.lower() for field in fields(ServiceableGroundContact)}
    assert "duration" not in names
    assert names.isdisjoint(
        {
            "latitude",
            "longitude",
            "elevation",
            "azimuth",
            "aos",
            "los",
            "visibility",
            "geometry",
            "serviceable",
            "weather",
        }
    )


def test_communications_config_contract_is_exact_and_required() -> None:
    config = _config()

    assert tuple(field.name for field in fields(CommunicationsConfig)) == (
        "configuration_id",
        "nominal_downlink_data_rate_bps",
    )
    assert CommunicationsConfig.__dataclass_params__.frozen
    assert not hasattr(config, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(CommunicationsConfig)
    )
    assert type(config.nominal_downlink_data_rate_bps) is ScalarParameter


def test_public_reference_parameter_has_exact_airbus_provenance() -> None:
    parameter = _config().nominal_downlink_data_rate_bps

    assert parameter.value == 270_000_000.0
    assert parameter.parameter_id == ParameterId(
        "communications.nominal-downlink-data-rate"
    )
    assert parameter.units == "bit/s"
    assert parameter.provenance.classification is (
        ProvenanceClass.PUBLIC_SPECIFICATION
    )
    assert parameter.provenance.status is ProvenanceStatus.VERIFIED
    assert parameter.provenance.source_ids == (
        SourceRecordId(AIRBUS_SOURCE_ID),
    )


def test_live_reference_parameter_sources_remain_registered() -> None:
    parameter = _config().nominal_downlink_data_rate_bps
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")

    for source_id in parameter.provenance.source_ids:
        assert source_id.value in sources


def test_synthetic_reference_policy_is_explicit_and_source_free() -> None:
    parameter = _synthetic_parameter()
    config = CommunicationsConfig(
        SubsystemConfigurationId("synthetic-communications"),
        parameter,
    )

    assert config.nominal_downlink_data_rate_bps.value == 1_000_000.0
    assert parameter.provenance.classification is (
        ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
    )
    assert parameter.provenance.status is ProvenanceStatus.TO_RESEARCH
    assert parameter.provenance.source_ids == ()
    assert parameter.provenance.rationale is not None


@pytest.mark.parametrize(
    ("parameter_id", "units", "value"),
    (
        ("wrong.parameter", "bit/s", 1.0),
        ("communications.nominal-downlink-data-rate", "Mbit/s", 1.0),
        ("communications.nominal-downlink-data-rate", "bit/s", 0.0),
        ("communications.nominal-downlink-data-rate", "bit/s", -1.0),
    ),
)
def test_communications_config_rejects_wrong_parameter_contract(
    parameter_id,
    units,
    value,
) -> None:
    provenance = ParameterProvenance(
        ParameterId(parameter_id),
        ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
        units,
        (),
        ProvenanceStatus.TO_RESEARCH,
        rationale="Synthetic invalid contract test.",
    )
    with pytest.raises(ValueError):
        CommunicationsConfig(
            SubsystemConfigurationId("communications"),
            ScalarParameter(value, provenance),
        )


def test_communications_config_rejects_wrong_top_level_types() -> None:
    with pytest.raises(TypeError, match="configuration_id"):
        CommunicationsConfig(ParameterId("wrong"), _parameter())
    with pytest.raises(TypeError, match="ScalarParameter"):
        CommunicationsConfig(
            SubsystemConfigurationId("communications"),
            270_000_000.0,
        )


def test_communications_config_revalidates_complete_nested_parameter() -> None:
    parameter = _parameter()
    object.__setattr__(parameter, "value", float("nan"))
    with pytest.raises(ValueError, match="finite"):
        CommunicationsConfig(
            SubsystemConfigurationId("communications"),
            parameter,
        )

    parameter = _parameter()
    object.__setattr__(parameter.provenance.parameter_id, "value", "BAD")
    with pytest.raises(ValueError, match="StableId value"):
        CommunicationsConfig(
            SubsystemConfigurationId("communications"),
            parameter,
        )

    parameter = _parameter()
    object.__setattr__(parameter.provenance.source_ids[0], "value", "BAD")
    with pytest.raises(ValueError, match="StableId value"):
        CommunicationsConfig(
            SubsystemConfigurationId("communications"),
            parameter,
        )


def test_proposal_contract_is_exact_frozen_slotted_and_required() -> None:
    contact = _contact(start=100, end=107)
    proposal = DownlinkCapacityProposal(
        contact,
        270_000_000.0,
        7,
        1_890_000_000.0,
    )

    assert tuple(field.name for field in fields(DownlinkCapacityProposal)) == (
        "contact",
        "nominal_downlink_data_rate_bps",
        "serviceable_contact_duration_seconds",
        "nominal_contact_capacity_bits",
    )
    assert DownlinkCapacityProposal.__dataclass_params__.frozen
    assert not hasattr(proposal, "__dict__")
    assert all(
        field.default is MISSING and field.default_factory is MISSING
        for field in fields(DownlinkCapacityProposal)
    )
    with pytest.raises(FrozenInstanceError):
        proposal.nominal_contact_capacity_bits = 1.0


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    (
        ("contact", object()),
        ("nominal_downlink_data_rate_bps", 1),
        ("serviceable_contact_duration_seconds", 60.0),
        ("serviceable_contact_duration_seconds", True),
        ("nominal_contact_capacity_bits", 1),
    ),
)
def test_proposal_requires_exact_evidence_types(field_name, invalid) -> None:
    proposal = compute_downlink_capacity(_config(), _contact())
    with pytest.raises(TypeError, match=field_name):
        replace(proposal, **{field_name: invalid})


def test_proposal_revalidates_contact_and_exact_consistency() -> None:
    proposal = compute_downlink_capacity(_config(), _contact())
    corrupted = deepcopy(proposal.contact)
    object.__setattr__(corrupted.contact_id, "value", "BAD")
    with pytest.raises(ValueError, match="StableId value"):
        replace(proposal, contact=corrupted)
    with pytest.raises(ValueError, match="duration"):
        replace(proposal, serviceable_contact_duration_seconds=59)
    with pytest.raises(ValueError, match="rate times duration"):
        replace(proposal, nominal_contact_capacity_bits=1.0)


def test_public_function_signature_and_exports_are_exact() -> None:
    parameters = signature(compute_downlink_capacity).parameters

    assert tuple(parameters) == ("communications_config", "contact")
    assert all(
        parameter.kind is Parameter.POSITIONAL_OR_KEYWORD
        and parameter.default is Parameter.empty
        for parameter in parameters.values()
    )
    assert str(signature(compute_downlink_capacity)) == (
        "(communications_config: 'CommunicationsConfig', contact: "
        "'ServiceableGroundContact') -> 'DownlinkCapacityProposal'"
    )
    assert communications_module.__all__ == [
        "ServiceableGroundContact",
        "DownlinkCapacityProposal",
        "compute_downlink_capacity",
    ]


@pytest.mark.parametrize(
    ("duration", "capacity"),
    (
        (1, 270_000_000.0),
        (7, 1_890_000_000.0),
        (23, 6_210_000_000.0),
        (60, 16_200_000_000.0),
        (10**100, 2.7e108),
    ),
)
def test_capacity_arithmetic_is_exact_for_positive_durations(
    duration,
    capacity,
) -> None:
    contact = _contact(start=0, end=duration)
    proposal = compute_downlink_capacity(_config(), contact)

    assert proposal.contact is contact
    assert type(proposal.nominal_downlink_data_rate_bps) is float
    assert proposal.nominal_downlink_data_rate_bps == 270_000_000.0
    assert type(proposal.serviceable_contact_duration_seconds) is int
    assert proposal.serviceable_contact_duration_seconds == duration
    assert type(proposal.nominal_contact_capacity_bits) is float
    assert proposal.nominal_contact_capacity_bits == capacity
    assert proposal.nominal_contact_capacity_bits == float(
        proposal.nominal_downlink_data_rate_bps * duration
    )


def test_sixty_second_decimal_gb_is_derived_evidence_only() -> None:
    proposal = compute_downlink_capacity(_config(), _contact(start=0, end=60))

    assert proposal.nominal_contact_capacity_bits == 16_200_000_000.0
    assert proposal.nominal_contact_capacity_bits / 8_000_000_000.0 == 2.025
    assert not hasattr(proposal, "bytes")
    assert not hasattr(proposal, "decimal_gb")


def test_general_real_rate_is_normalized_to_builtin_float() -> None:
    config = _config(Fraction(3, 2))
    proposal = compute_downlink_capacity(config, _contact(start=0, end=2))

    assert proposal.nominal_downlink_data_rate_bps == 1.5
    assert type(proposal.nominal_downlink_data_rate_bps) is float
    assert proposal.nominal_contact_capacity_bits == 3.0
    assert type(proposal.nominal_contact_capacity_bits) is float


def test_capacity_rejects_overflow_and_represented_underflow() -> None:
    with pytest.raises(ValueError, match="finite"):
        compute_downlink_capacity(
            _config(float.fromhex("0x1.fffffffffffffp+1023")),
            _contact(start=0, end=2),
        )

    with pytest.raises(ValueError, match="greater than zero"):
        compute_downlink_capacity(
            _config(Fraction(1, 10**400)),
            _contact(start=0, end=1),
        )


def test_capacity_rejects_corrupted_nonfinite_rate() -> None:
    config = _config()
    object.__setattr__(
        config.nominal_downlink_data_rate_bps,
        "value",
        float("inf"),
    )
    with pytest.raises(ValueError, match="finite"):
        compute_downlink_capacity(config, _contact())


def test_capacity_rejects_wrong_top_level_types_before_calculation() -> None:
    with pytest.raises(TypeError, match="communications_config"):
        compute_downlink_capacity(object(), _contact())
    with pytest.raises(TypeError, match="contact"):
        compute_downlink_capacity(_config(), object())


def test_capacity_evaluation_is_pure_deterministic_and_preserves_identity() -> None:
    config = _config()
    contact = _contact()
    config_before = deepcopy(config)
    contact_before = deepcopy(contact)

    first = compute_downlink_capacity(config, contact)
    second = compute_downlink_capacity(config, contact)

    assert config == config_before
    assert contact == contact_before
    assert first == second
    assert first is not second
    assert first.contact is contact
    assert second.contact is contact


def test_module_dependencies_and_numerical_operations_are_narrow() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(MODULE_PATH))
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    call_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    identifiers = {
        value.lower()
        for node in ast.walk(tree)
        for value in (
            (node.id,)
            if isinstance(node, ast.Name)
            else (node.attr,)
            if isinstance(node, ast.Attribute)
            else (node.name,)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
            else ()
        )
    }

    assert imports.isdisjoint(
        {
            "context",
            "state",
            "checkpoint",
            "engine",
            "mission",
            "controller",
            "storage",
        }
    )
    assert call_names.isdisjoint(
        {"round", "ceil", "floor", "isclose", "quantize", "int"}
    )
    assert identifiers.isdisjoint(
        {
            "epsilon",
            "tolerance",
            "efficiency",
            "packet_overhead",
            "rf_link_budget",
            "partial",
            "complete",
            "delivery",
            "record_removal",
            "communications_power",
        }
    )


def test_a_adds_no_persistent_or_engine_behavior() -> None:
    forbidden_names = (
        "GroundDataDeliveryState",
        "DownlinkTransferProgress",
        "CompletedAcquisitionDelivery",
        "DownlinkTransmissionResult",
    )

    for name in forbidden_names:
        assert not hasattr(communications_module, name)
    assert not hasattr(communications_module, "PARTIAL")
    assert not hasattr(communications_module, "COMPLETE")
    assert not hasattr(communications_module, "step_downlink")


def test_a_checkpoint_schema_four_is_historical_and_live_schema_is_five() -> None:
    historical_checkpoint = _run_git(
        "show",
        f"{V55A_COMMIT}:ops_sim/v5/checkpoint.py",
    )

    assert "CURRENT_CHECKPOINT_SCHEMA_VERSION = 4" in historical_checkpoint
    assert CURRENT_CHECKPOINT_SCHEMA_VERSION == 5


def test_d297_and_source_families_record_exact_a_semantics() -> None:
    decisions = _run_git("show", f"{V55A_COMMIT}:V5_DECISION_LOG.md")
    sources = _run_git("show", f"{V55A_COMMIT}:V5_SOURCE_REGISTER.md")
    heading = (
        "## D297 — V5.5A defines externally supplied serviceable contacts "
        "and nominal X-band capacity"
    )

    assert decisions.count(heading) == 1
    assert decisions.index("## D296 ") < decisions.index(heading)
    assert "## D298 " not in decisions
    normalized_decision = _normalized(decisions.partition(heading)[2])
    for phrase in (
        "`groundcontactid`",
        "`groundstationid`",
        "positive half-open integer-second",
        "serviceability is supplied externally",
        "`communicationsconfig` now requires",
        "270_000_000.0 bit/s",
        "public specification",
        "nominal x-band data-link rate",
        "no arbitrary efficiency factor",
        "no persistent communications state",
        "no persistent communications state",
    ):
        assert phrase in normalized_decision

    assert sources.count("### S001 ") == 1
    assert sources.count("### S007 ") == 1
    assert "### S011 " not in sources
    normalized_sources = _normalized(sources)
    for phrase in (
        AIRBUS_SOURCE_ID,
        "270_000_000.0 bit/s",
        "s007-wmo-oscar-kazeosat-programme",
        "independent institutional corroboration",
        "s007-syzdykov-et-al-2023",
        "mass memory",
        "dcu-x",
        "qpsk mod",
        "twt",
        "derived value",
        "explicit model assumption",
    ):
        assert phrase in normalized_sources


def test_status_and_public_spec_distinguish_current_and_historical_truth() -> None:
    status = _normalized(
        _run_git("show", f"{V55A_COMMIT}:MODEL_STATUS.md")
    )
    public_spec = _normalized(PUBLIC_SPEC_PATH.read_text(encoding="utf-8"))

    for phrase in (
        "v5.4 is preserved at the annotated `v5.4-final` tag",
        V54_FINAL_COMMIT,
        "v5.5 is **in progress** through a",
        "typed externally supplied serviceable ground contacts",
        "270 mbit/s",
        "checkpoint schema 4",
        "no persistent communications or transfer state",
        "no contact geometry",
    ):
        assert phrase in status
    for phrase in (
        "historical v3 uses 2.0 gb/min as a rounded",
        "270_000_000 × 60",
        "16_200_000_000 bits = 2.025 decimal gb",
        "does not treat it as measured operational delivered throughput",
        "not a radio link budget",
    ):
        assert phrase in public_spec


def test_v54_final_history_is_fixed_while_live_compatibility_remains() -> None:
    audit_source = _run_git(
        "show",
        f"{V55A_COMMIT}:tests/test_v54f_final_release_audit.py",
    )

    assert _run_git("cat-file", "-t", "v5.4-final").strip() == "tag"
    assert _run_git("rev-parse", "v5.4-final^{}").strip() == V54_FINAL_COMMIT
    assert f'F_COMMIT = "{V54_FINAL_COMMIT}"' in audit_source
    assert 'E_COMMIT, F_COMMIT' in audit_source
    assert '_git_show(F_COMMIT, "V5_DECISION_LOG.md")' in audit_source
    assert '_git_show(F_COMMIT, "MODEL_STATUS.md")' in audit_source
    assert (
        "CURRENT_CHECKPOINT_SCHEMA_VERSION == checkpoint.schema_version == 4"
        in audit_source
    )


def test_a_scope_is_exactly_twenty_one_files_and_three_production_files() -> None:
    changes = set(
        _run_git(
            "diff",
            "--name-only",
            V54_FINAL_COMMIT,
            V55A_COMMIT,
        ).splitlines()
    )
    production = {
        path for path in changes if path.startswith("ops_sim/v5/")
    }

    assert production == {
        "ops_sim/v5/communications.py",
        "ops_sim/v5/configuration.py",
        "ops_sim/v5/ids.py",
    }
    assert changes == {
        "KAZEOSAT_PUBLIC_SPEC.md",
        "MODEL_STATUS.md",
        "V5_DECISION_LOG.md",
        "V5_SOURCE_REGISTER.md",
        "examples/v52_integrated_eps_thermal_demo.py",
        "ops_sim/v5/communications.py",
        "ops_sim/v5/configuration.py",
        "ops_sim/v5/ids.py",
        "tests/test_v50b2_configuration.py",
        "tests/test_v50b4_context_checkpoint.py",
        "tests/test_v50d1_time_engine.py",
        "tests/test_v50d2_atomic_transitions.py",
        "tests/test_v51d_eps_engine_integration.py",
        "tests/test_v51e_eps_validation.py",
        "tests/test_v51f_eps_release_hardening.py",
        "tests/test_v52a2_thermal_state_checkpoint.py",
        "tests/test_v52d1_degradation_state.py",
        "tests/test_v52d2b2_degradation_engine_integration.py",
        "tests/test_v52e1_eps_thermal_engine.py",
        "tests/test_v54f_final_release_audit.py",
        "tests/test_v55a_contact_capacity.py",
    }


def test_production_contains_no_hard_coded_public_rate() -> None:
    assert "270_000_000" not in MODULE_PATH.read_text(encoding="utf-8")
    assert "270_000_000" not in CONFIGURATION_PATH.read_text(encoding="utf-8")
