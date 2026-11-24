"""Ground targets and explicit observation opportunities for V5.3A."""

import ast
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import numpy as np
import pytest

from ops_sim.v5.ids import (
    GroundTargetId,
    ImagingRequestId,
    ObservationOpportunityId,
)
from ops_sim.v5.observation import (
    GroundTarget,
    ImagingRequest,
    ImagingRequestCatalog,
    ObservationCampaign,
    ObservationOpportunity,
    ObservationOpportunityCatalog,
    ObservationPointing,
    TargetCatalog,
)


ROOT = Path(__file__).resolve().parents[1]
IDS_PATH = ROOT / "ops_sim" / "v5" / "ids.py"
OBSERVATION_PATH = ROOT / "ops_sim" / "v5" / "observation.py"
DECISION_LOG_PATH = ROOT / "V5_DECISION_LOG.md"
SOURCE_REGISTER_PATH = ROOT / "V5_SOURCE_REGISTER.md"


def _target(
    value: str = "target-one",
    *,
    latitude_deg: object = 45.0,
    longitude_deg: object = 60.0,
) -> GroundTarget:
    return GroundTarget(
        GroundTargetId(value),
        latitude_deg,
        longitude_deg,
    )


def _request(
    value: str = "request-one",
    *,
    target_id: GroundTargetId | None = None,
    priority_weight: object = 1.0,
) -> ImagingRequest:
    return ImagingRequest(
        ImagingRequestId(value),
        GroundTargetId("target-one") if target_id is None else target_id,
        priority_weight,
    )


def _pointing(
    view_angle_from_nadir_deg: object = 10.0,
    view_azimuth_deg: object = 20.0,
) -> ObservationPointing:
    return ObservationPointing(
        view_angle_from_nadir_deg,
        view_azimuth_deg,
    )


def _opportunity(
    value: str = "opportunity-one",
    *,
    request_id: ImagingRequestId | None = None,
    window_start_seconds: object = 100,
    window_end_seconds: object = 200,
    imaging_duration_seconds: object = 40,
    pointing: ObservationPointing | None = None,
) -> ObservationOpportunity:
    return ObservationOpportunity(
        ObservationOpportunityId(value),
        ImagingRequestId("request-one") if request_id is None else request_id,
        window_start_seconds,
        window_end_seconds,
        imaging_duration_seconds,
        _pointing() if pointing is None else pointing,
    )


def _campaign() -> ObservationCampaign:
    return ObservationCampaign(
        TargetCatalog((_target(),)),
        ImagingRequestCatalog((_request(),)),
        ObservationOpportunityCatalog((_opportunity(),)),
    )


@pytest.mark.parametrize(
    "id_type,value,prefix",
    (
        (GroundTargetId, "target-one", "ground-target"),
        (ImagingRequestId, "request-one", "imaging-request"),
        (
            ObservationOpportunityId,
            "opportunity-one",
            "observation-opportunity",
        ),
    ),
)
def test_v53a_ids_use_stable_typed_canonical_behavior(
    id_type,
    value,
    prefix,
) -> None:
    identifier = id_type(value)

    assert identifier.canonical == f"{prefix}:{value}"
    assert id_type.from_canonical(identifier.canonical) == identifier
    assert not hasattr(identifier, "__dict__")
    with pytest.raises(FrozenInstanceError):
        identifier.value = "replacement"


def test_observation_records_have_exact_frozen_slotted_fields() -> None:
    contracts = {
        GroundTarget: ("target_id", "latitude_deg", "longitude_deg"),
        ImagingRequest: ("request_id", "target_id", "priority_weight"),
        ObservationPointing: (
            "view_angle_from_nadir_deg",
            "view_azimuth_deg",
        ),
        ObservationOpportunity: (
            "opportunity_id",
            "request_id",
            "window_start_seconds",
            "window_end_seconds",
            "imaging_duration_seconds",
            "pointing",
        ),
        TargetCatalog: ("targets",),
        ImagingRequestCatalog: ("requests",),
        ObservationOpportunityCatalog: ("opportunities",),
        ObservationCampaign: ("targets", "requests", "opportunities"),
    }
    instances = (
        _target(),
        _request(),
        _pointing(),
        _opportunity(),
        TargetCatalog((_target(),)),
        ImagingRequestCatalog((_request(),)),
        ObservationOpportunityCatalog((_opportunity(),)),
        _campaign(),
    )

    for domain_type, instance in zip(contracts, instances):
        assert tuple(field.name for field in fields(domain_type)) == (
            contracts[domain_type]
        )
        assert domain_type.__dataclass_params__.frozen
        assert not hasattr(instance, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(instance, fields(domain_type)[0].name, None)


def test_domain_records_require_exact_identity_and_pointing_types() -> None:
    with pytest.raises(TypeError, match="target_id"):
        GroundTarget(ImagingRequestId("wrong"), 0, 0)
    with pytest.raises(TypeError, match="request_id"):
        ImagingRequest(GroundTargetId("wrong"), GroundTargetId("target"), 1)
    with pytest.raises(TypeError, match="target_id"):
        ImagingRequest(
            ImagingRequestId("request"),
            ObservationOpportunityId("wrong"),
            1,
        )
    with pytest.raises(TypeError, match="opportunity_id"):
        ObservationOpportunity(
            ImagingRequestId("wrong"),
            ImagingRequestId("request"),
            0,
            10,
            1,
            _pointing(),
        )
    with pytest.raises(TypeError, match="pointing"):
        ObservationOpportunity(
            ObservationOpportunityId("opportunity"),
            ImagingRequestId("request"),
            0,
            10,
            1,
            object(),
        )


@pytest.mark.parametrize("latitude", (-90, 90, -90.0, 90.0))
def test_ground_target_accepts_closed_latitude_boundaries(latitude) -> None:
    assert _target(latitude_deg=latitude).latitude_deg == latitude


@pytest.mark.parametrize("latitude", (-90.0001, 90.0001))
def test_ground_target_rejects_latitude_outside_closed_interval(latitude) -> None:
    with pytest.raises(ValueError, match="latitude_deg"):
        _target(latitude_deg=latitude)


@pytest.mark.parametrize("longitude", (-180, -179.999, 0, 179.999))
def test_ground_target_accepts_canonical_longitude_interval(longitude) -> None:
    assert _target(longitude_deg=longitude).longitude_deg == longitude


@pytest.mark.parametrize("longitude", (-180.001, 180, 360, -360))
def test_ground_target_rejects_longitude_without_wrapping(longitude) -> None:
    with pytest.raises(ValueError, match="longitude_deg"):
        _target(longitude_deg=longitude)


@pytest.mark.parametrize("field_name", ("latitude_deg", "longitude_deg"))
@pytest.mark.parametrize("invalid", (True, float("nan"), float("inf")))
def test_ground_target_rejects_bool_and_nonfinite_coordinates(
    field_name,
    invalid,
) -> None:
    arguments = {field_name: invalid}
    error_type = TypeError if invalid is True else ValueError
    with pytest.raises(error_type):
        _target(**arguments)


@pytest.mark.parametrize("priority", (1, 0.25, np.float64(2.5)))
def test_imaging_request_accepts_positive_real_priority(priority) -> None:
    assert _request(priority_weight=priority).priority_weight == priority


@pytest.mark.parametrize(
    "priority,error_type",
    (
        (0, ValueError),
        (-1, ValueError),
        (True, TypeError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
    ),
)
def test_imaging_request_rejects_invalid_priority(priority, error_type) -> None:
    with pytest.raises(error_type):
        _request(priority_weight=priority)


def test_pointing_accepts_zero_and_values_arbitrarily_near_upper_bounds() -> None:
    assert _pointing(0, 0) == ObservationPointing(0, 0)
    assert _pointing(89.999999, 359.999999) == ObservationPointing(
        89.999999,
        359.999999,
    )


@pytest.mark.parametrize("angle", (-0.001, 90, 180, 360))
def test_pointing_rejects_view_angle_without_clipping(angle) -> None:
    with pytest.raises(ValueError, match="view_angle"):
        _pointing(angle, 0)


@pytest.mark.parametrize("azimuth", (-0.001, 360, 720))
def test_pointing_rejects_azimuth_without_wrapping(azimuth) -> None:
    with pytest.raises(ValueError, match="view_azimuth"):
        _pointing(0, azimuth)


@pytest.mark.parametrize(
    "field_name",
    ("view_angle_from_nadir_deg", "view_azimuth_deg"),
)
@pytest.mark.parametrize("invalid", (True, float("nan"), float("inf")))
def test_pointing_rejects_bool_and_nonfinite_values(field_name, invalid) -> None:
    arguments = {
        "view_angle_from_nadir_deg": 0,
        "view_azimuth_deg": 0,
        field_name: invalid,
    }
    error_type = TypeError if invalid is True else ValueError
    with pytest.raises(error_type):
        _pointing(**arguments)


def test_opportunity_accepts_duration_equal_to_complete_window() -> None:
    opportunity = _opportunity(
        window_start_seconds=0,
        window_end_seconds=100,
        imaging_duration_seconds=100,
    )

    assert opportunity.window_start_seconds == 0
    assert opportunity.imaging_duration_seconds == 100


@pytest.mark.parametrize(
    "start,end,duration",
    (
        (0, 0, 1),
        (10, 9, 1),
        (-1, 10, 1),
        (0, -1, 1),
        (0, 10, 0),
        (0, 10, -1),
        (0, 10, 11),
    ),
)
def test_opportunity_rejects_invalid_window_or_duration(
    start,
    end,
    duration,
) -> None:
    with pytest.raises(ValueError):
        _opportunity(
            window_start_seconds=start,
            window_end_seconds=end,
            imaging_duration_seconds=duration,
        )


@pytest.mark.parametrize(
    "field_name",
    (
        "window_start_seconds",
        "window_end_seconds",
        "imaging_duration_seconds",
    ),
)
@pytest.mark.parametrize("invalid", (True, 1.0, np.int64(1), "1"))
def test_opportunity_requires_exact_python_integer_times(
    field_name,
    invalid,
) -> None:
    arguments = {
        "window_start_seconds": 0,
        "window_end_seconds": 10,
        "imaging_duration_seconds": 1,
        field_name: invalid,
    }
    with pytest.raises(TypeError):
        _opportunity(**arguments)


@pytest.mark.parametrize(
    "catalog",
    (
        TargetCatalog(()),
        ImagingRequestCatalog(()),
        ObservationOpportunityCatalog(()),
    ),
)
def test_catalogs_accept_empty_exact_tuples(catalog) -> None:
    assert not getattr(catalog, fields(type(catalog))[0].name)


@pytest.mark.parametrize(
    "factory,items",
    (
        (TargetCatalog, [_target()]),
        (ImagingRequestCatalog, [_request()]),
        (ObservationOpportunityCatalog, [_opportunity()]),
    ),
)
def test_catalogs_require_exact_tuples(factory, items) -> None:
    with pytest.raises(TypeError, match="tuple"):
        factory(items)


@pytest.mark.parametrize(
    "factory,items",
    (
        (TargetCatalog, (_request(),)),
        (ImagingRequestCatalog, (_opportunity(),)),
        (ObservationOpportunityCatalog, (_target(),)),
    ),
)
def test_catalogs_require_exact_owned_item_types(factory, items) -> None:
    with pytest.raises(TypeError, match="contain only"):
        factory(items)


@pytest.mark.parametrize(
    "factory,items",
    (
        (TargetCatalog, (_target(), _target())),
        (ImagingRequestCatalog, (_request(), _request())),
        (
            ObservationOpportunityCatalog,
            (_opportunity(), _opportunity()),
        ),
    ),
)
def test_catalogs_reject_duplicate_owned_ids(factory, items) -> None:
    with pytest.raises(ValueError, match="unique"):
        factory(items)


def test_campaign_accepts_complete_cross_references() -> None:
    assert _campaign() == _campaign()


def test_campaign_rejects_missing_target_reference() -> None:
    campaign = _campaign()
    with pytest.raises(ValueError, match="target_id"):
        ObservationCampaign(
            TargetCatalog((_target("target-two"),)),
            campaign.requests,
            campaign.opportunities,
        )


def test_campaign_rejects_missing_request_reference() -> None:
    campaign = _campaign()
    with pytest.raises(ValueError, match="request_id"):
        ObservationCampaign(
            campaign.targets,
            ImagingRequestCatalog((_request("request-two"),)),
            campaign.opportunities,
        )


def test_numpy_real_coordinates_and_pointing_are_admitted() -> None:
    target = _target(
        latitude_deg=np.float64(-12.5),
        longitude_deg=np.float64(179.5),
    )
    pointing = _pointing(np.float64(35.5), np.float64(270.0))

    assert target.latitude_deg == -12.5
    assert target.longitude_deg == 179.5
    assert pointing.view_angle_from_nadir_deg == 35.5
    assert pointing.view_azimuth_deg == 270.0


def test_production_has_no_numpy_or_forbidden_subsystem_dependency() -> None:
    tree = ast.parse(
        OBSERVATION_PATH.read_text(encoding="utf-8"),
        filename=str(OBSERVATION_PATH),
    )
    imported_modules = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert imported_modules.isdisjoint(
        {
            "numpy",
            "engine",
            "context",
            "state",
            "checkpoint",
            "orbit",
            "adcs",
            "payload",
            "eps",
            "thermal",
            "degradation",
        }
    )


def test_observation_domain_has_no_platform_limit_or_slew_rate_equation() -> None:
    source = OBSERVATION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(OBSERVATION_PATH))

    assert not any(
        isinstance(node, ast.Constant) and node.value == 35
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and isinstance(node.left, ast.Constant)
        and isinstance(node.right, ast.Constant)
        and {node.left.value, node.right.value} == {60, 90}
        for node in ast.walk(tree)
    )
    assert "visibility" not in {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }


def test_new_ids_are_explicitly_exported() -> None:
    from ops_sim.v5 import ids

    assert "GroundTargetId" in ids.__all__
    assert "ImagingRequestId" in ids.__all__
    assert "ObservationOpportunityId" in ids.__all__


def test_observation_module_defines_exact_exports() -> None:
    from ops_sim.v5 import observation

    assert observation.__all__ == [
        "GroundTarget",
        "ImagingRequest",
        "ImagingRequestCatalog",
        "ObservationCampaign",
        "ObservationOpportunity",
        "ObservationOpportunityCatalog",
        "ObservationPointing",
        "TargetCatalog",
    ]


def test_d157_through_d162_are_recorded_once_after_d156() -> None:
    decisions = DECISION_LOG_PATH.read_text(encoding="utf-8")

    for number in range(157, 163):
        assert decisions.count(f"## D{number:03d} ") == 1
    assert decisions.index("## D156 ") < decisions.index("## D157 ")


def test_airbus_and_observation_opportunity_semantics_are_recorded() -> None:
    sources = SOURCE_REGISTER_PATH.read_text(encoding="utf-8")
    lower = sources.lower()

    assert "Airbus Defence and Space" in sources
    assert "April 2019" in sources
    assert "five bands" in lower
    assert "simultaneously" in lower
    assert "60" in sources and "90" in sources
    assert "constant" in lower and "slew" in lower
    assert "observation opportunit" in lower
    assert "no optimization" in lower


def test_v53a_production_scope_is_only_ids_and_observation() -> None:
    assert IDS_PATH.exists()
    assert OBSERVATION_PATH.exists()
