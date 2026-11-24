"""Input-only, content-bound J2 segment requests using canonical codec v1.

No segment/result record is added to the codec allowlist. Loading reconstructs
the already-supported J2 authorities and the strict request; evaluation remains
an explicit call. Derived tubes, states and cached evidence are never authority.
"""

from pathlib import Path

from .experiment_codec import (
    CANONICAL_VERSION, canonical_content, content_digest, decode_content,
    json_text, object_fields, parse_json,
)
from .orbit_config import _exact
from .orbit_j2_segments import J2SegmentRequest


SEGMENT_DOCUMENT_VERSION = 1
SEGMENT_DOCUMENT_FORMAT = "M2_J2_SEGMENT_REQUEST"
SEGMENT_DIGEST_DOMAIN = "m2-j2-segment-request-v1"


def _request_map(request):
    _exact(request, J2SegmentRequest, "segment request")
    checked = J2SegmentRequest(request.coast, request.start, request.end)
    return {"coast": checked.coast, "start": checked.start, "end": checked.end}


def _digest(value):
    _exact(value, str, "digest")
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("digest must be 64 lowercase hexadecimal characters")
    return value


def segment_request_digest(request):
    """Content identity includes both instants and every original coast input."""
    return content_digest(SEGMENT_DIGEST_DOMAIN, _request_map(request))


def segment_request_to_json(request):
    data = _request_map(request)
    return json_text({
        "format": SEGMENT_DOCUMENT_FORMAT,
        "version": SEGMENT_DOCUMENT_VERSION,
        "canonical_version": CANONICAL_VERSION,
        "inputs": canonical_content(data),
        "digest": content_digest(SEGMENT_DIGEST_DOMAIN, data),
    })


def segment_request_from_json(text, *, expected_digest=None):
    """Reject malformed/redigested authorities and noncanonical normalization."""
    payload = object_fields(parse_json(text), (
        "format", "version", "canonical_version", "inputs", "digest"))
    if (type(payload["format"]) is not str or
            payload["format"] != SEGMENT_DOCUMENT_FORMAT):
        raise ValueError("unsupported segment document format")
    if (type(payload["version"]) is not int or
            payload["version"] != SEGMENT_DOCUMENT_VERSION or
            type(payload["canonical_version"]) is not int or
            payload["canonical_version"] != CANONICAL_VERSION):
        raise ValueError("unsupported segment document version")
    data = object_fields(decode_content(payload["inputs"]), ("coast", "start", "end"))
    request = J2SegmentRequest(data["coast"], data["start"], data["end"])
    checked = _request_map(request)
    if canonical_content(checked) != payload["inputs"]:
        raise ValueError("noncanonical segment input normalization")
    digest = content_digest(SEGMENT_DIGEST_DOMAIN, checked)
    if _digest(payload["digest"]) != digest:
        raise ValueError("segment document digest mismatch")
    if expected_digest is not None and _digest(expected_digest) != digest:
        raise ValueError("expected segment digest mismatch")
    return request


def save_segment_request(path, request):
    """Exclusive creation: do not replace existing evidence or caller files."""
    text = segment_request_to_json(request)
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text + "\n")


def load_segment_request(path, *, expected_digest=None):
    return segment_request_from_json(
        Path(path).read_text(encoding="utf-8"), expected_digest=expected_digest)


__all__ = [
    "segment_request_digest", "segment_request_to_json", "segment_request_from_json",
    "save_segment_request", "load_segment_request",
]
