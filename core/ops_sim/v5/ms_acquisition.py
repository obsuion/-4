"""Explicit MS sizing/initial-attitude adapter into the shared protected owner."""

from dataclasses import dataclass
from fractions import Fraction

from .adcs import CommonFrameBoresightDirection, compute_boresight_transition
from .continuation import ImagingAction, _exact, _label
from .ms_product import MSAcquisitionPlan, _time
from .observation_feasibility import evaluate_observation_view_feasibility
from .payload import OpticalAcquisitionChannelSelection, compute_optical_acquisition


@dataclass(frozen=True, slots=True)
class InitialAttitudeEvidence:
    """Known settled direction at an instant; no fictitious observation/product.

    Direction is declared held between actions in this bounded fixed script.
    Slew/settling timing uses the existing ADCS envelope, not new dynamics.
    """
    at_seconds: int
    common_frame_boresight: CommonFrameBoresightDirection
    rationale: str

    def __post_init__(self):
        _time(self.at_seconds)
        _exact(self.common_frame_boresight, CommonFrameBoresightDirection, "initial direction")
        self.common_frame_boresight.__post_init__()
        _label(self.rationale, "initial attitude evidence")


def validate_ms_acquisition(action, config, plan):
    _exact(action, ImagingAction, "imaging action")
    _exact(plan, MSAcquisitionPlan, "MS acquisition plan")
    plan.__post_init__()
    g = plan.sizing
    acquisition = action.execution.candidate.acquisition_input
    opportunity = action.execution.candidate.maneuver_candidate.opportunity
    # Legacy channel-selection semantics are authoritative, including simultaneous PAN/MS.
    compute_optical_acquisition(config, acquisition)
    if acquisition.channel_selection is not OpticalAcquisitionChannelSelection.MULTISPECTRAL_ONLY:
        raise ValueError("mission sizing requires explicit MS-only acquisition")
    if opportunity.request_id != plan.request.request_id:
        raise ValueError("MS association request does not match acquisition")
    if (acquisition.effective_cross_track_width_m != g.footprint.width_m
            or acquisition.effective_along_track_length_m != g.footprint.length_m
            or g.spacing_x_m != config.multispectral_reference_sample_spacing_m.value
            or g.spacing_y_m != config.multispectral_reference_sample_spacing_m.value
            or len(g.captured_channels) != config.multispectral_band_count.value
            or g.bits_per_sample != config.acquisition_bits_per_sample.value):
        raise ValueError("MS grid/spectral manifest differs from physical acquisition inputs")


def initial_acquisition_result(config, previous, action):
    """Use actual initial attitude, next-view envelope and common-frame timing."""
    previous.__post_init__()
    candidate = action.execution.candidate
    next_view = evaluate_observation_view_feasibility(config.adcs.agile_pointing,
                                                      candidate.maneuver_candidate.opportunity)
    transition = compute_boresight_transition(config.adcs.agile_pointing,
        previous.common_frame_boresight, candidate.maneuver_candidate.common_frame_boresight)
    ready = Fraction(previous.at_seconds) + Fraction(transition.total_transition_time_seconds)
    if not next_view.feasible or ready > action.execution.scheduled_start_seconds:
        return None
    return compute_optical_acquisition(config.payload.optical_acquisition, candidate.acquisition_input)


def execute_ms_request(context, previous, timed, *, acquisition, policy, integration):
    """Opt-in integer acquisition or physical standby, never post-execution rounding."""
    from .operational_protection import StandbyAction
    from .substepped_execution import _execute_substepped_request
    if type(timed.request.action) is ImagingAction:
        _exact(acquisition, MSAcquisitionPlan, "MS acquisition plan")
    elif type(timed.request.action) is not StandbyAction or acquisition is not None:
        raise ValueError("MS request adapter admits only declared MS acquisition or standby")
    return _execute_substepped_request(context, previous, timed, policy=policy,
        integration=integration, ms_acquisition=acquisition, allow_initial_attitude=True)
