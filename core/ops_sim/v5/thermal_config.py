"""Immutable, extensible lumped thermal-network configuration for V5."""

from __future__ import annotations

from dataclasses import dataclass

from .ids import ParameterId, ThermalLinkId, ThermalNodeId
from .parameters import ScalarParameter


def _validate_parameter(
    field_name: str,
    parameter: object,
    *,
    parameter_id: str,
    units: str,
    strictly_positive: bool,
) -> None:
    if type(parameter) is not ScalarParameter:
        raise TypeError(f"{field_name} must be a ScalarParameter")
    if (
        type(parameter.parameter_id) is not ParameterId
        or parameter.parameter_id.value != parameter_id
    ):
        raise ValueError(
            f"{field_name} must use ParameterId {parameter_id!r}"
        )
    if parameter.units != units:
        raise ValueError(f"{field_name} must use units {units!r}")
    if strictly_positive and parameter.value <= 0:
        raise ValueError(f"{field_name} must be strictly greater than zero")
    if not strictly_positive and parameter.value < 0:
        raise ValueError(
            f"{field_name} must be greater than or equal to zero"
        )


@dataclass(frozen=True, slots=True)
class ThermalNodeConfig:
    """Own immutable reduced-order parameters for one lumped thermal node."""

    node_id: ThermalNodeId
    heat_capacity_j_per_k: ScalarParameter
    emissivity: ScalarParameter
    radiating_area_m2: ScalarParameter
    operating_min_temperature_k: ScalarParameter
    operating_max_temperature_k: ScalarParameter
    survival_min_temperature_k: ScalarParameter
    survival_max_temperature_k: ScalarParameter

    def __post_init__(self) -> None:
        if type(self.node_id) is not ThermalNodeId:
            raise TypeError("node_id must be a ThermalNodeId")

        parameter_prefix = f"thermal.node.{self.node_id.value}"
        _validate_parameter(
            "heat_capacity_j_per_k",
            self.heat_capacity_j_per_k,
            parameter_id=f"{parameter_prefix}.heat-capacity",
            units="J/K",
            strictly_positive=True,
        )
        _validate_parameter(
            "emissivity",
            self.emissivity,
            parameter_id=f"{parameter_prefix}.emissivity",
            units="1",
            strictly_positive=False,
        )
        if self.emissivity.value > 1:
            raise ValueError("emissivity must be less than or equal to one")
        _validate_parameter(
            "radiating_area_m2",
            self.radiating_area_m2,
            parameter_id=f"{parameter_prefix}.radiating-area",
            units="m^2",
            strictly_positive=True,
        )
        for field_name, semantic_name in (
            (
                "operating_min_temperature_k",
                "operating-min-temperature",
            ),
            (
                "operating_max_temperature_k",
                "operating-max-temperature",
            ),
            (
                "survival_min_temperature_k",
                "survival-min-temperature",
            ),
            (
                "survival_max_temperature_k",
                "survival-max-temperature",
            ),
        ):
            _validate_parameter(
                field_name,
                getattr(self, field_name),
                parameter_id=f"{parameter_prefix}.{semantic_name}",
                units="K",
                strictly_positive=True,
            )

        survival_min = self.survival_min_temperature_k.value
        operating_min = self.operating_min_temperature_k.value
        operating_max = self.operating_max_temperature_k.value
        survival_max = self.survival_max_temperature_k.value
        if survival_min >= survival_max:
            raise ValueError(
                "survival_min_temperature_k must be less than "
                "survival_max_temperature_k"
            )
        if survival_min > operating_min:
            raise ValueError(
                "survival_min_temperature_k must be less than or equal to "
                "operating_min_temperature_k"
            )
        if operating_min >= operating_max:
            raise ValueError(
                "operating_min_temperature_k must be less than "
                "operating_max_temperature_k"
            )
        if operating_max > survival_max:
            raise ValueError(
                "operating_max_temperature_k must be less than or equal to "
                "survival_max_temperature_k"
            )


@dataclass(frozen=True, slots=True)
class ThermalLinkConfig:
    """Own one undirected effective conductive coupling between two nodes."""

    link_id: ThermalLinkId
    node_a_id: ThermalNodeId
    node_b_id: ThermalNodeId
    conductance_w_per_k: ScalarParameter

    def __post_init__(self) -> None:
        if type(self.link_id) is not ThermalLinkId:
            raise TypeError("link_id must be a ThermalLinkId")
        if type(self.node_a_id) is not ThermalNodeId:
            raise TypeError("node_a_id must be a ThermalNodeId")
        if type(self.node_b_id) is not ThermalNodeId:
            raise TypeError("node_b_id must be a ThermalNodeId")
        if self.node_a_id == self.node_b_id:
            raise ValueError("thermal link endpoints must be distinct")
        _validate_parameter(
            "conductance_w_per_k",
            self.conductance_w_per_k,
            parameter_id=(
                f"thermal.link.{self.link_id.value}.conductance"
            ),
            units="W/K",
            strictly_positive=True,
        )


@dataclass(frozen=True, slots=True)
class ThermalNetworkConfig:
    """Own a generic thermal graph and its mandatory baseline role references.

    ``bus_node_id`` identifies the spacecraft bus/electronics role,
    ``battery_node_id`` identifies the battery role, and ``payload_node_id``
    identifies the payload role. Additional nodes may represent other
    reduced-order thermal domains without changing this configuration model.
    """

    nodes: tuple[ThermalNodeConfig, ...]
    links: tuple[ThermalLinkConfig, ...]
    bus_node_id: ThermalNodeId
    battery_node_id: ThermalNodeId
    payload_node_id: ThermalNodeId

    def __post_init__(self) -> None:
        if type(self.nodes) is not tuple:
            raise TypeError("nodes must be a tuple")
        if len(self.nodes) < 3:
            raise ValueError("nodes must contain at least three thermal nodes")
        if not all(type(node) is ThermalNodeConfig for node in self.nodes):
            raise TypeError("nodes must contain only ThermalNodeConfig values")

        node_ids = tuple(node.node_id for node in self.nodes)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("thermal node IDs must be unique")
        node_id_set = set(node_ids)

        if type(self.links) is not tuple:
            raise TypeError("links must be a tuple")
        if not all(type(link) is ThermalLinkConfig for link in self.links):
            raise TypeError("links must contain only ThermalLinkConfig values")

        link_ids = tuple(link.link_id for link in self.links)
        if len(set(link_ids)) != len(link_ids):
            raise ValueError("thermal link IDs must be unique")
        physical_pairs: set[tuple[str, str]] = set()
        for link in self.links:
            if (
                link.node_a_id not in node_id_set
                or link.node_b_id not in node_id_set
            ):
                raise ValueError("thermal link endpoint must exist in nodes")
            pair = tuple(
                sorted((link.node_a_id.canonical, link.node_b_id.canonical))
            )
            if pair in physical_pairs:
                raise ValueError(
                    "duplicate undirected thermal node pair is not allowed"
                )
            physical_pairs.add(pair)

        roles = (
            ("bus_node_id", self.bus_node_id),
            ("battery_node_id", self.battery_node_id),
            ("payload_node_id", self.payload_node_id),
        )
        for field_name, role_id in roles:
            if type(role_id) is not ThermalNodeId:
                raise TypeError(f"{field_name} must be a ThermalNodeId")
            if role_id not in node_id_set:
                raise ValueError(f"{field_name} must identify a configured node")
        if len({role_id for _, role_id in roles}) != len(roles):
            raise ValueError("thermal role node IDs must be distinct")


__all__ = [
    "ThermalLinkConfig",
    "ThermalNetworkConfig",
    "ThermalNodeConfig",
]
