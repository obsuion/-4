"""Focused tests for V5.2A1 immutable thermal-network configuration."""

import ast
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from ops_sim.v5.ids import (
    ParameterId,
    ThermalLinkId,
    ThermalNodeId,
)
from ops_sim.v5.parameters import ScalarParameter
from ops_sim.v5.provenance import (
    ParameterProvenance,
    ProvenanceClass,
    ProvenanceStatus,
)
from ops_sim.v5.thermal_config import (
    ThermalLinkConfig,
    ThermalNetworkConfig,
    ThermalNodeConfig,
)


ROOT = Path(__file__).resolve().parents[1]
THERMAL_CONFIG_PATH = ROOT / "ops_sim" / "v5" / "thermal_config.py"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"

NODE_PARAMETER_FIELDS = (
    ("heat_capacity_j_per_k", "heat-capacity", "J/K", 1000.0),
    ("emissivity", "emissivity", "1", 0.8),
    ("radiating_area_m2", "radiating-area", "m^2", 1.0),
    (
        "operating_min_temperature_k",
        "operating-min-temperature",
        "K",
        270.0,
    ),
    (
        "operating_max_temperature_k",
        "operating-max-temperature",
        "K",
        320.0,
    ),
    (
        "survival_min_temperature_k",
        "survival-min-temperature",
        "K",
        250.0,
    ),
    (
        "survival_max_temperature_k",
        "survival-max-temperature",
        "K",
        340.0,
    ),
)


def _parameter(parameter_id: str, units: str, value: object) -> ScalarParameter:
    return ScalarParameter(
        value,
        ParameterProvenance(
            ParameterId(parameter_id),
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION,
            units,
            (),
            ProvenanceStatus.TO_RESEARCH,
            rationale="Synthetic value used only by a focused unit test.",
        ),
    )


def _node(node_name: str = "bus", **changes: object) -> ThermalNodeConfig:
    values: dict[str, object] = {"node_id": ThermalNodeId(node_name)}
    for field_name, semantic_name, units, value in NODE_PARAMETER_FIELDS:
        values[field_name] = _parameter(
            f"thermal.node.{node_name}.{semantic_name}",
            units,
            value,
        )
    values.update(changes)
    return ThermalNodeConfig(**values)


def _link(
    link_name: str,
    node_a: str,
    node_b: str,
    *,
    conductance: object = 2.0,
) -> ThermalLinkConfig:
    return ThermalLinkConfig(
        ThermalLinkId(link_name),
        ThermalNodeId(node_a),
        ThermalNodeId(node_b),
        _parameter(
            f"thermal.link.{link_name}.conductance",
            "W/K",
            conductance,
        ),
    )


def _baseline_nodes() -> tuple[ThermalNodeConfig, ...]:
    return (_node("bus"), _node("battery"), _node("payload"))


def _network(
    *,
    nodes: tuple[ThermalNodeConfig, ...] | None = None,
    links: tuple[ThermalLinkConfig, ...] | None = None,
    bus_node_id: object = ThermalNodeId("bus"),
    battery_node_id: object = ThermalNodeId("battery"),
    payload_node_id: object = ThermalNodeId("payload"),
) -> ThermalNetworkConfig:
    return ThermalNetworkConfig(
        _baseline_nodes() if nodes is None else nodes,
        (
            (
                _link("bus-battery", "bus", "battery"),
                _link("bus-payload", "bus", "payload"),
            )
            if links is None
            else links
        ),
        bus_node_id,
        battery_node_id,
        payload_node_id,
    )


def _replacement_parameter(
    node_name: str,
    field_name: str,
    *,
    parameter_id: str | None = None,
    units: str | None = None,
    value: object | None = None,
) -> ScalarParameter:
    specification = next(
        item for item in NODE_PARAMETER_FIELDS if item[0] == field_name
    )
    _, semantic_name, expected_units, default_value = specification
    return _parameter(
        parameter_id or f"thermal.node.{node_name}.{semantic_name}",
        expected_units if units is None else units,
        default_value if value is None else value,
    )


def test_thermal_configuration_dataclasses_have_exact_fields() -> None:
    assert tuple(field.name for field in fields(ThermalNodeConfig)) == (
        "node_id",
        "heat_capacity_j_per_k",
        "emissivity",
        "radiating_area_m2",
        "operating_min_temperature_k",
        "operating_max_temperature_k",
        "survival_min_temperature_k",
        "survival_max_temperature_k",
    )
    assert tuple(field.name for field in fields(ThermalLinkConfig)) == (
        "link_id",
        "node_a_id",
        "node_b_id",
        "conductance_w_per_k",
    )
    assert tuple(field.name for field in fields(ThermalNetworkConfig)) == (
        "nodes",
        "links",
        "bus_node_id",
        "battery_node_id",
        "payload_node_id",
    )


@pytest.mark.parametrize(
    "configuration_type",
    (ThermalNodeConfig, ThermalLinkConfig, ThermalNetworkConfig),
)
def test_thermal_configuration_fields_have_no_defaults(
    configuration_type,
) -> None:
    for field in fields(configuration_type):
        assert field.default is MISSING
        assert field.default_factory is MISSING


def test_thermal_configuration_graph_is_deeply_immutable_and_hashable() -> None:
    network = _network()
    node = network.nodes[0]
    link = network.links[0]

    assert not hasattr(node, "__dict__")
    assert not hasattr(link, "__dict__")
    assert not hasattr(network, "__dict__")
    assert isinstance(hash(node), int)
    assert isinstance(hash(link), int)
    assert isinstance(hash(network), int)
    assert type(network.nodes) is tuple
    assert type(network.links) is tuple
    with pytest.raises(FrozenInstanceError):
        node.node_id = ThermalNodeId("replacement")
    with pytest.raises(FrozenInstanceError):
        node.emissivity.value = 0.5
    with pytest.raises(FrozenInstanceError):
        node.emissivity.provenance.units = "percent"
    with pytest.raises(FrozenInstanceError):
        link.node_a_id = ThermalNodeId("replacement")
    with pytest.raises(FrozenInstanceError):
        network.nodes = ()


@pytest.mark.parametrize("node_name", ("bus", "battery", "payload", "radiator"))
def test_node_parameter_ids_are_derived_from_arbitrary_node_identity(
    node_name: str,
) -> None:
    node = _node(node_name)

    for field_name, semantic_name, units, _ in NODE_PARAMETER_FIELDS:
        parameter = getattr(node, field_name)
        assert parameter.parameter_id == ParameterId(
            f"thermal.node.{node_name}.{semantic_name}"
        )
        assert parameter.units == units


@pytest.mark.parametrize(
    "field_name",
    tuple(item[0] for item in NODE_PARAMETER_FIELDS),
)
def test_node_rejects_parameter_id_owned_by_wrong_node(field_name: str) -> None:
    _, semantic_name, _, _ = next(
        item for item in NODE_PARAMETER_FIELDS if item[0] == field_name
    )
    parameter = _replacement_parameter(
        "bus",
        field_name,
        parameter_id=f"thermal.node.battery.{semantic_name}",
    )

    with pytest.raises(ValueError, match="ParameterId"):
        _node("bus", **{field_name: parameter})


@pytest.mark.parametrize(
    "field_name",
    tuple(item[0] for item in NODE_PARAMETER_FIELDS),
)
def test_node_rejects_wrong_units_for_every_parameter(field_name: str) -> None:
    parameter = _replacement_parameter(
        "bus",
        field_name,
        units="wrong-unit",
    )

    with pytest.raises(ValueError, match="units"):
        _node("bus", **{field_name: parameter})


@pytest.mark.parametrize(
    "field_name",
    tuple(item[0] for item in NODE_PARAMETER_FIELDS),
)
def test_node_rejects_bare_physical_scalars(field_name: str) -> None:
    with pytest.raises(TypeError, match="ScalarParameter"):
        _node("bus", **{field_name: 1.0})


def test_heat_capacity_requires_strictly_positive_value() -> None:
    assert _node(
        heat_capacity_j_per_k=_replacement_parameter(
            "bus", "heat_capacity_j_per_k", value=0.001
        )
    ).heat_capacity_j_per_k.value == 0.001
    for value in (0.0, -0.001):
        with pytest.raises(ValueError, match="strictly greater"):
            _node(
                heat_capacity_j_per_k=_replacement_parameter(
                    "bus", "heat_capacity_j_per_k", value=value
                )
            )


@pytest.mark.parametrize("value", (0.0, 0.5, 1.0))
def test_emissivity_accepts_closed_unit_interval(value: float) -> None:
    node = _node(
        emissivity=_replacement_parameter("bus", "emissivity", value=value)
    )

    assert node.emissivity.value == value


@pytest.mark.parametrize("value", (-0.001, 1.001))
def test_emissivity_rejects_values_outside_closed_unit_interval(
    value: float,
) -> None:
    with pytest.raises(ValueError):
        _node(
            emissivity=_replacement_parameter(
                "bus", "emissivity", value=value
            )
        )


def test_radiating_area_requires_strictly_positive_value() -> None:
    assert _node(
        radiating_area_m2=_replacement_parameter(
            "bus", "radiating_area_m2", value=0.001
        )
    ).radiating_area_m2.value == 0.001
    for value in (0.0, -0.001):
        with pytest.raises(ValueError, match="strictly greater"):
            _node(
                radiating_area_m2=_replacement_parameter(
                    "bus", "radiating_area_m2", value=value
                )
            )


@pytest.mark.parametrize(
    "field_name",
    (
        "operating_min_temperature_k",
        "operating_max_temperature_k",
        "survival_min_temperature_k",
        "survival_max_temperature_k",
    ),
)
@pytest.mark.parametrize("value", (0.0, -1.0))
def test_every_temperature_bound_requires_positive_kelvin(
    field_name: str,
    value: float,
) -> None:
    parameter = _replacement_parameter(
        "bus", field_name, value=value
    )
    with pytest.raises(ValueError, match="strictly greater"):
        _node("bus", **{field_name: parameter})


@pytest.mark.parametrize(
    ("value", "error_type"),
    (
        (True, TypeError),
        ("270", TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (float("-inf"), ValueError),
    ),
)
def test_temperature_scalar_domain_is_inherited_from_scalar_parameter(
    value: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        _replacement_parameter(
            "bus", "operating_min_temperature_k", value=value
        )


def test_temperature_order_accepts_equal_outer_operating_boundaries() -> None:
    node = _node(
        survival_min_temperature_k=_replacement_parameter(
            "bus", "survival_min_temperature_k", value=270.0
        ),
        survival_max_temperature_k=_replacement_parameter(
            "bus", "survival_max_temperature_k", value=320.0
        ),
    )

    assert node.survival_min_temperature_k.value == 270.0
    assert node.survival_max_temperature_k.value == 320.0


@pytest.mark.parametrize(
    "changes",
    (
        {"operating_min_temperature_k": 320.0},
        {"operating_min_temperature_k": 321.0},
        {"survival_min_temperature_k": 271.0},
        {"survival_max_temperature_k": 319.0},
        {
            "survival_min_temperature_k": 340.0,
            "survival_max_temperature_k": 340.0,
        },
    ),
    ids=(
        "operating-equal",
        "operating-reversed",
        "survival-min-above-operating",
        "survival-max-below-operating",
        "survival-not-strictly-ordered",
    ),
)
def test_temperature_order_rejects_every_invalid_relationship(
    changes: dict[str, float],
) -> None:
    replacements = {
        field_name: _replacement_parameter(
            "bus", field_name, value=value
        )
        for field_name, value in changes.items()
    }

    with pytest.raises(ValueError):
        _node("bus", **replacements)


def test_node_rejects_wrong_node_id_type() -> None:
    with pytest.raises(TypeError, match="ThermalNodeId"):
        replace(_node(), node_id=ParameterId("bus"))


def test_link_contract_is_dynamic_immutable_and_positive() -> None:
    link = _link("battery-payload", "battery", "payload")

    assert link.conductance_w_per_k.parameter_id == ParameterId(
        "thermal.link.battery-payload.conductance"
    )
    assert link.conductance_w_per_k.units == "W/K"
    assert link.conductance_w_per_k.value == 2.0
    assert isinstance(hash(link), int)
    assert not hasattr(link, "__dict__")
    with pytest.raises(FrozenInstanceError):
        link.conductance_w_per_k = _parameter(
            "thermal.link.battery-payload.conductance", "W/K", 3.0
        )


def test_link_rejects_wrong_parameter_id_units_and_nonpositive_value() -> None:
    link = _link("bus-battery", "bus", "battery")
    with pytest.raises(ValueError, match="ParameterId"):
        replace(
            link,
            conductance_w_per_k=_parameter(
                "thermal.link.wrong.conductance", "W/K", 2.0
            ),
        )
    with pytest.raises(ValueError, match="units"):
        replace(
            link,
            conductance_w_per_k=_parameter(
                "thermal.link.bus-battery.conductance", "W", 2.0
            ),
        )
    for value in (0.0, -0.001):
        with pytest.raises(ValueError, match="strictly greater"):
            replace(
                link,
                conductance_w_per_k=_parameter(
                    "thermal.link.bus-battery.conductance", "W/K", value
                ),
            )
    with pytest.raises(TypeError, match="ScalarParameter"):
        replace(link, conductance_w_per_k=2.0)


def test_link_rejects_self_link_and_wrong_id_types() -> None:
    link = _link("bus-battery", "bus", "battery")
    with pytest.raises(ValueError, match="distinct"):
        _link("bus-self", "bus", "bus")
    with pytest.raises(TypeError, match="ThermalLinkId"):
        replace(link, link_id=ParameterId("bus-battery"))
    with pytest.raises(TypeError, match="node_a_id"):
        replace(link, node_a_id=ParameterId("bus"))
    with pytest.raises(TypeError, match="node_b_id"):
        replace(link, node_b_id=ParameterId("battery"))


def test_minimal_three_role_network_is_valid() -> None:
    network = _network()

    assert tuple(node.node_id.value for node in network.nodes) == (
        "bus",
        "battery",
        "payload",
    )
    assert network.bus_node_id == ThermalNodeId("bus")
    assert network.battery_node_id == ThermalNodeId("battery")
    assert network.payload_node_id == ThermalNodeId("payload")


def test_network_accepts_fourth_node_and_additional_link() -> None:
    nodes = (*_baseline_nodes(), _node("radiator"))
    links = (
        _link("bus-battery", "bus", "battery"),
        _link("bus-payload", "bus", "payload"),
        _link("bus-radiator", "bus", "radiator"),
    )

    network = _network(nodes=nodes, links=links)

    assert len(network.nodes) == 4
    assert ThermalNodeId("radiator") in tuple(
        node.node_id for node in network.nodes
    )
    assert len(network.links) == 3


def test_network_accepts_empty_links_without_connectivity_requirement() -> None:
    network = _network(links=())

    assert network.links == ()


def test_network_requires_tuple_collections_and_exact_member_types() -> None:
    network = _network()
    with pytest.raises(TypeError, match="nodes must be a tuple"):
        replace(network, nodes=list(network.nodes))
    with pytest.raises(TypeError, match="links must be a tuple"):
        replace(network, links=list(network.links))
    with pytest.raises(TypeError, match="ThermalNodeConfig"):
        replace(network, nodes=(*network.nodes, object()))
    with pytest.raises(TypeError, match="ThermalLinkConfig"):
        replace(network, links=(*network.links, object()))
    with pytest.raises(ValueError, match="at least three"):
        replace(network, nodes=network.nodes[:2], links=())


def test_network_rejects_duplicate_node_and_link_ids() -> None:
    network = _network()
    duplicate_node = _node("bus")
    with pytest.raises(ValueError, match="node IDs"):
        replace(network, nodes=(*network.nodes, duplicate_node))

    duplicate_link_id = _link("bus-battery", "payload", "battery")
    with pytest.raises(ValueError, match="link IDs"):
        replace(network, links=(*network.links, duplicate_link_id))


def test_network_rejects_duplicate_undirected_pair_in_reverse_order() -> None:
    network = _network()
    reverse = _link("battery-bus-reverse", "battery", "bus")

    with pytest.raises(ValueError, match="undirected"):
        replace(network, links=(*network.links, reverse))


@pytest.mark.parametrize("unknown_side", ("a", "b"))
def test_network_rejects_unknown_link_endpoint(unknown_side: str) -> None:
    network = _network()
    endpoint_a = "unknown" if unknown_side == "a" else "bus"
    endpoint_b = "unknown" if unknown_side == "b" else "battery"
    unknown_link = _link("unknown-endpoint", endpoint_a, endpoint_b)

    with pytest.raises(ValueError, match="endpoint"):
        replace(network, links=(unknown_link,))


@pytest.mark.parametrize(
    "role_field",
    ("bus_node_id", "battery_node_id", "payload_node_id"),
)
def test_network_roles_require_exact_existing_thermal_node_ids(
    role_field: str,
) -> None:
    network = _network()
    with pytest.raises(TypeError, match="ThermalNodeId"):
        replace(network, **{role_field: ParameterId("wrong-type")})
    with pytest.raises(ValueError, match="configured node"):
        replace(network, **{role_field: ThermalNodeId("unknown")})


@pytest.mark.parametrize(
    "changes",
    (
        {"battery_node_id": ThermalNodeId("bus")},
        {"payload_node_id": ThermalNodeId("bus")},
        {"payload_node_id": ThermalNodeId("battery")},
    ),
)
def test_network_requires_three_distinct_role_references(
    changes: dict[str, ThermalNodeId],
) -> None:
    with pytest.raises(ValueError, match="role node IDs"):
        replace(_network(), **changes)


def test_all_test_parameters_are_labeled_synthetic_explicit_assumptions() -> None:
    network = _network()
    parameters = [
        getattr(node, field_name)
        for node in network.nodes
        for field_name, _, _, _ in NODE_PARAMETER_FIELDS
    ] + [link.conductance_w_per_k for link in network.links]

    for parameter in parameters:
        assert parameter.provenance.classification is (
            ProvenanceClass.EXPLICIT_MODEL_ASSUMPTION
        )
        assert parameter.provenance.status is ProvenanceStatus.TO_RESEARCH
        assert parameter.provenance.source_ids == ()
        assert parameter.provenance.rationale == (
            "Synthetic value used only by a focused unit test."
        )


def test_thermal_configuration_contains_no_state_physics_or_degradation() -> None:
    source = THERMAL_CONFIG_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(THERMAL_CONFIG_PATH))
    imports = {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    numeric_constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and type(node.value) in {int, float}
    }

    assert imports.isdisjoint(
        {"engine", "context", "checkpoint", "state", "configuration"}
    )
    assert identifiers.isdisjoint(
        {
            "DEFAULT_CONFIG",
            "Simulator",
            "SatelliteState",
            "ThermalState",
            "temperature_k",
            "current_thermal_energy",
            "dt",
            "dt_seconds",
            "sigma",
            "stefan_boltzmann_constant",
            "heat_flow_w",
            "external_heat_w",
            "internal_heat_w",
            "capacity_fade",
            "solar_retention",
            "activation_energy",
            "cycle_count",
            "health",
        }
    )
    assert "** 4" not in source
    assert numeric_constants <= {0, 1, 3}


def test_source_register_records_v52a1_semantics_without_values() -> None:
    register = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    s004 = register.partition("### S004 ")[2].partition("### S005 ")[0]

    for _, semantic_name, units, _ in NODE_PARAMETER_FIELDS:
        assert f"thermal.node.<node>.{semantic_name}" in s004
        assert f"(`{units}`)" in s004
    assert "thermal.link.<link>.conductance" in s004
    assert "(`W/K`)" in s004
    assert "not numerical values" in s004
    assert "PUBLIC" in s004
    assert "LITERATURE" in s004
    assert "DERIVED" in s004
    assert "EXPLICIT" in s004
    assert "Sensitivity ranges" in s004
    assert "reduced-order model quantities" in s004


def test_v52a1_decisions_are_appended_once() -> None:
    decision_log = DECISION_LOG_PATH.read_text(encoding="utf-8")

    for decision_number in range(79, 85):
        assert decision_log.count(f"## D{decision_number:03d} ") == 1
    assert decision_log.index("## D078 ") < decision_log.index("## D079 ")
    assert "exactly three nodes" in decision_log.partition("## D079 ")[2]
    assert "Runtime temperature is not" in decision_log.partition(
        "## D081 "
    )[2]


def test_thermal_configuration_public_exports_are_exact() -> None:
    from ops_sim.v5 import thermal_config

    assert thermal_config.__all__ == [
        "ThermalLinkConfig",
        "ThermalNetworkConfig",
        "ThermalNodeConfig",
    ]
