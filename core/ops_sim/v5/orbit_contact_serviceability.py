"""Bind an external serviceability declaration to one C3a geometry block.

The V5.5 contact remains caller-owned evidence. Geometry does not derive RF,
availability, serviceability or execution authority. Integer sub-step contacts
may have geometric support; the existing engine separately owns alignment.
No binding evidence is persisted or included in B2 content. See D311/S007.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from .communications import ServiceableGroundContact
from .context import SimulationInputs
from .orbit_config import _exact
from .orbit_geometry import GroundPointDefinition
from .orbit_ground_contacts import (
    GeometricGroundContactBlock, GroundStationContactProjection,
    generate_geometric_ground_contacts,
)
from .orbit_visibility import GroundVisibilityPolicy
from .orbit_visibility_windows import GroundVisibilitySearchConfig


@dataclass(frozen=True, slots=True, eq=False)
class GroundContactGeometryBinding:
    """Retain an external contact and its unique complete geometric support.

    All eight inputs are required. The two derived fields recompute on replace;
    no precomputed geometry is accepted as public visibility authority.
    Equality compares external ID text without caller overloads. This transient
    binding is unhashable; external V5.5 evidence itself is left unchanged.
    """

    inputs: SimulationInputs
    station: GroundPointDefinition
    policy: GroundVisibilityPolicy
    search_start_seconds: float
    search_end_seconds: float
    search_config: GroundVisibilitySearchConfig
    first_step_start_seconds: int
    serviceable_contact: ServiceableGroundContact
    geometric_projection: GroundStationContactProjection = field(init=False)
    supporting_block: GeometricGroundContactBlock = field(init=False)

    __hash__ = None

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        left, right = self.serviceable_contact, other.serviceable_contact
        # Each contact already has exact owner-validated ID types. Preserve its
        # original objects but do not let legacy text equality erase identity.
        return (str.__eq__(left.contact_id.value, right.contact_id.value) is True
            and str.__eq__(left.ground_station_id.value, right.ground_station_id.value) is True
            and left.start_time_seconds == right.start_time_seconds
            and left.end_time_seconds == right.end_time_seconds
            and all(getattr(self, item.name) == getattr(other, item.name)
                    for item in fields(self) if item.name != "serviceable_contact"))

    def __post_init__(self) -> None:
        original = self.serviceable_contact
        _exact(original, ServiceableGroundContact, "serviceable_contact")
        # Revalidation through the existing owner retains all four fields,
        # including the original typed ID objects; no ID is generated here.
        contact = ServiceableGroundContact(original.contact_id,
            original.ground_station_id, original.start_time_seconds, original.end_time_seconds)
        projection = generate_geometric_ground_contacts(self.inputs, self.station,
            self.policy, self.search_start_seconds, self.search_end_seconds,
            self.search_config, self.first_step_start_seconds)
        # Both owners validated exact GroundStationId types. V5.5 admits str
        # subclasses: additionally compare their actual text using the base
        # implementation so overloaded equality cannot invent a station match.
        # This neither normalizes nor rewrites the external ID evidence.
        if (contact.ground_station_id != projection.station.point_id
                or str.__eq__(contact.ground_station_id.value,
                              projection.station.point_id.value) is not True):
            raise ValueError("serviceable contact station does not match geometry station")
        supporting = None
        for block in projection.contact_blocks:
            if (contact.start_time_seconds >= block.first_start_time_seconds
                    and contact.end_time_seconds <= block.last_end_time_seconds):
                if supporting is not None:
                    raise ValueError("inconsistent geometry support: more than one C3a block contains the contact")
                supporting = block
        if supporting is None:
            raise ValueError("serviceable contact lacks geometry support in a single C3a block")
        values = {
            "inputs": projection.inputs, "station": projection.station,
            "policy": projection.policy,
            "search_start_seconds": projection.search_start_seconds,
            "search_end_seconds": projection.search_end_seconds,
            "search_config": projection.search_config,
            "first_step_start_seconds": projection.first_step_start_seconds,
            "serviceable_contact": contact, "geometric_projection": projection,
            "supporting_block": supporting,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)


def bind_serviceable_ground_contact_to_geometry(
    inputs: SimulationInputs, station: GroundPointDefinition, policy: GroundVisibilityPolicy,
    search_start_seconds: float, search_end_seconds: float,
    search_config: GroundVisibilitySearchConfig, first_step_start_seconds: int,
    serviceable_contact: ServiceableGroundContact,
) -> GroundContactGeometryBinding:
    return GroundContactGeometryBinding(inputs, station, policy, search_start_seconds,
        search_end_seconds, search_config, first_step_start_seconds, serviceable_contact)


__all__ = ["GroundContactGeometryBinding", "bind_serviceable_ground_contact_to_geometry"]
