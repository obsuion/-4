"""Opt-in continuous-study checkpoints and append-only event evidence.

Schema-5 remains the authority for physical state. This envelope adds the
continuous coordinator cursor, cumulative accounting, immutable-input/source
binding, and the external event-chain head. Restore validates those bindings
once and never replays past physical actions. A digest detects changes; it is
not an authentication or a substitute for an independent causal audit.
"""

from dataclasses import fields, replace
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import platform
import sys
import tempfile

from .checkpoint import CheckpointState
from .design_trade_design import design_record
from .experiment_codec import content_digest, parse_json
from .substepped_execution import ActionAccounting


CONTINUATION_VERSION = 1
EVENT_VERSION = 1
EMPTY_EVENT_DIGEST = "0" * 64
_STATE_FIELDS = {
    "angle_rad", "cycle_index", "next_request_index", "phase", "contact_blocked",
    "advances", "event_count", "event_digest", "events_emitted", "accounting",
}
_NONPERSISTENT_FIELDS = {
    "spec", "context", "template_spec", "program", "design", "last_events",
}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def _digest(domain, value):
    return hashlib.sha256((domain + "\n" + _json(value)).encode("utf-8")).hexdigest()


def _hex_digest(value, name):
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError(name + " must be a lowercase SHA-256 digest")


def _cursor(count, digest):
    if type(count) is not int or count < 0:
        raise ValueError("event count must be a nonnegative exact integer")
    _hex_digest(digest, "event digest")
    if (count == 0) != (digest == EMPTY_EVENT_DIGEST):
        raise ValueError("empty event count and digest disagree")


def source_fingerprint():
    """Read current production bytes at a persistence boundary, never per step."""
    root = Path(__file__).resolve().parents[1]
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*.py"))}


def runtime_fingerprint():
    """Exact Python build plus architecture; no claim of cross-runtime identity."""
    return {"implementation": platform.python_implementation(),
            "python_version": sys.version, "system": platform.system(),
            "machine": platform.machine(), "byteorder": sys.byteorder}


def input_fingerprint(state):
    return content_digest("task05fa-continuous-inputs-v1",
                          (state.context.inputs, state.program, design_record(state.design)))


def validate_accounting(state):
    """Check persisted ledgers against retained physical truth without replay.

    The actuator kinetic-heat adjustment is a signed transfer. Its cumulative
    diagnostic may be slightly negative from summing a completed rest-to-rest
    maneuver, so it is not constrained like nonnegative energy consumption.
    """
    a = state.accounting
    counters = {"numerical_substeps", "forecast_substeps", "acquired", "credited",
                "completed", "transmitted_bits", "acquired_bits", "forecast_rejections", "actual_denials"}
    scalars = {"weighted_credit", "minimum_energy_wh", "maximum_energy_wh"}
    mappings = {"energies", "diagnostic_energy_wh", "phase_seconds",
                "minimum_temperatures_k", "maximum_temperatures_k"}
    if type(a) is not dict or set(a) != counters | scalars | mappings:
        raise ValueError("continuous accounting fields mismatch")
    def number(value, name, *, signed=False):
        if type(value) not in (int, float) or not isfinite(value) or (not signed and value < 0):
            raise ValueError("accounting " + name + " must be a finite nonnegative number" if not signed
                             else "accounting " + name + " must be a finite signed number")
    for name in counters:
        if type(a[name]) is not int or a[name] < 0:
            raise ValueError("accounting " + name + " must be a nonnegative exact integer")
    for name in scalars:
        number(a[name], name)
    for name in mappings:
        if type(a[name]) is not dict or any(type(k) is not str for k in a[name]):
            raise ValueError("invalid accounting " + name + " mapping")
    energy_fields = {f.name for f in fields(ActionAccounting)} - {"numerical_substeps"}
    if (not set(a["energies"]) <= energy_fields
            or (a["numerical_substeps"] > 0 and set(a["energies"]) != energy_fields)):
        raise ValueError("invalid accounting energy fields")
    for name, value in a["energies"].items():
        number(value, name)
    diagnostics = {"solar_source_wh", "solar_bus_wh", "solar_wire_loss_wh", "solar_converter_loss_wh",
                   "load_wire_loss_wh", "actuator_electrical_wh", "terminal_load_wh", "actuator_heat_adjustment_wh"}
    if not set(a["diagnostic_energy_wh"]) <= diagnostics:
        raise ValueError("invalid diagnostic energy fields")
    for name, value in a["diagnostic_energy_wh"].items():
        number(value, name, signed=name == "actuator_heat_adjustment_wh")
    if not set(a["phase_seconds"]) <= {"hold", "motion", "settle", "imaging", "contact"}:
        raise ValueError("invalid accounting phase")
    for name, value in a["phase_seconds"].items():
        if type(value) is not int or value < 0:
            raise ValueError("phase duration must be a nonnegative exact integer")
    c = state.context
    if sum(a["phase_seconds"].values()) != c.simulation_time_seconds:
        raise ValueError("accounted phase durations disagree with physical clock")
    if c.controller_state.replan_count != state.advances:
        raise ValueError("controller replans disagree with completed advances")
    deliveries = c.ground_data_delivery_state.completed_deliveries
    onboard = c.spacecraft_state.data_storage.stored_records
    records = tuple(d.record for d in deliveries) + onboard
    if a["completed"] != len(deliveries) or a["acquired"] != len(records):
        raise ValueError("continuous counters disagree with retained custody")
    acquired_bits = sum(r.stored_equivalent_bits for r in records)
    transmitted_bits = (sum(d.record.stored_equivalent_bits for d in deliveries)
                        + sum(p.transmitted_equivalent_bits for p in c.ground_data_delivery_state.partial_transfers))
    if a["acquired_bits"] != acquired_bits or a["transmitted_bits"] != transmitted_bits:
        raise ValueError("accounted bits disagree with retained custody")
    if not a["credited"] <= a["completed"] <= a["acquired"]:
        raise ValueError("credit counters exceed physical delivery")
    energy = c.spacecraft_state.battery.energy_wh
    if not a["minimum_energy_wh"] <= energy <= a["maximum_energy_wh"] <= state.design.capacity_wh:
        raise ValueError("energy extrema do not contain completed physical energy")
    temperatures = {n.node_id.value: n.temperature_k for n in c.spacecraft_state.thermal.node_states}
    for name in ("minimum_temperatures_k", "maximum_temperatures_k"):
        if set(a[name]) != set(temperatures):
            raise ValueError("temperature extrema node identities disagree")
        for node, temperature in a[name].items():
            number(temperature, node)
            if temperature <= 0:
                raise ValueError("temperature extrema must be positive")
    if any(not a["minimum_temperatures_k"][n] <= t <= a["maximum_temperatures_k"][n]
           for n, t in temperatures.items()):
        raise ValueError("temperature extrema do not contain completed physical state")


def _streamed_boundary(state):
    _cursor(state.event_count, state.event_digest)
    if type(state.events_emitted) is not int or state.events_emitted != state.event_count:
        raise ValueError("all emitted events must be streamed before checkpoint")


def save_continuous(state):
    """Serialize one completed boundary, excluding transient diagnostic events."""
    from .continuous_trade import validate_state
    validate_state(state, full_binding=True)
    validate_accounting(state)
    if {f.name for f in fields(state)} != _STATE_FIELDS | _NONPERSISTENT_FIELDS:
        raise ValueError("unreviewed continuous-state persistence fields")
    _streamed_boundary(state)
    wire = {name: getattr(state, name) for name in sorted(_STATE_FIELDS)}
    wire["checkpoint"] = CheckpointState.from_context(state.context).to_dict()
    payload = {"version": CONTINUATION_VERSION, "spec": state.spec.to_dict(),
               "input_digest": input_fingerprint(state),
               "source_fingerprint": source_fingerprint(),
               "runtime": runtime_fingerprint(), "state": wire}
    # Normalize the envelope's declared JSON representation before hashing.
    payload = parse_json(_json(payload))
    payload["digest"] = _digest("task05fa-continuation-v1", payload)
    return _json(payload)


def restore_continuous(text):
    """Restore current-runtime state once from bound inputs; no history replay."""
    from .continuous_trade import ContinuousSpec, start_continuous, validate_state
    if type(text) is not str:
        raise TypeError("continuous continuation requires JSON text")
    payload = parse_json(text)
    expected = {"version", "spec", "input_digest", "source_fingerprint", "runtime", "state", "digest"}
    if (type(payload) is not dict or set(payload) != expected
            or type(payload["version"]) is not int or payload["version"] != CONTINUATION_VERSION):
        raise ValueError("unsupported continuous continuation envelope")
    digest = payload.pop("digest")
    _hex_digest(digest, "continuation digest")
    if digest != _digest("task05fa-continuation-v1", payload):
        raise ValueError("continuous continuation digest mismatch")
    if payload["source_fingerprint"] != source_fingerprint():
        raise ValueError("continuous continuation source binding mismatch")
    if payload["runtime"] != runtime_fingerprint():
        raise ValueError("continuous continuation runtime binding mismatch")
    wire = payload["state"]
    if type(wire) is not dict or set(wire) != _STATE_FIELDS | {"checkpoint"}:
        raise ValueError("invalid continuous runtime fields")
    _cursor(wire["event_count"], wire["event_digest"])
    base = start_continuous(ContinuousSpec.from_dict(payload["spec"]))
    if payload["input_digest"] != input_fingerprint(base):
        raise ValueError("continuous immutable input binding mismatch")
    context = CheckpointState.from_dict(wire["checkpoint"]).restore(base.context.inputs)
    state = replace(base, context=context, last_events=(),
                    **{name: wire[name] for name in _STATE_FIELDS})
    validate_state(state, full_binding=True)
    validate_accounting(state)
    _streamed_boundary(state)
    return state


def _event_line(event, count, previous_digest):
    if type(event) is not dict:
        raise TypeError("streamed event must be a JSON object")
    # A JSON round trip detaches caller-owned containers from evidence bytes.
    event = parse_json(_json(event))
    body = {"version": EVENT_VERSION, "event_count": count,
            "previous_digest": previous_digest, "event": event}
    body["digest"] = _digest("task05fa-event-v1", body)
    return body


def verify_evidence(path, *, event_count=None, event_digest=None):
    """Verify sequentially with constant history memory; reject any extra tail."""
    if (event_count is None) != (event_digest is None):
        raise ValueError("expected event count and digest must be supplied together")
    if event_count is not None:
        _cursor(event_count, event_digest)
    count, digest = 0, EMPTY_EVENT_DIGEST
    with Path(path).open("r", encoding="utf-8", newline="") as stream:
        for line in stream:
            if not line.endswith("\n"):
                raise ValueError("truncated event evidence line")
            body = parse_json(line)
            if (type(body) is not dict or set(body) != {
                    "version", "event_count", "previous_digest", "event", "digest"}
                    or type(body["version"]) is not int or body["version"] != EVENT_VERSION
                    or type(body["event_count"]) is not int or body["event_count"] != count + 1
                    or body["previous_digest"] != digest or type(body["event"]) is not dict):
                raise ValueError("event evidence sequence or schema mismatch")
            claimed = body.pop("digest")
            _hex_digest(claimed, "event digest")
            if claimed != _digest("task05fa-event-v1", body):
                raise ValueError("event evidence digest mismatch")
            count, digest = count + 1, claimed
    if event_count is not None and (count, digest) != (event_count, event_digest):
        raise ValueError("event evidence does not match checkpoint count/digest")
    return count, digest


class EvidenceStream:
    """Single-writer JSONL evidence; caller commits returned cursor to state.

    Resume verifies the complete existing stream once. An uncheckpointed tail
    is explicitly rejected, leaving its bytes available for crash diagnosis.
    The coordinator must stop if append fails; continuing would lose evidence.
    """

    def __init__(self, path, *, event_count=0, event_digest=EMPTY_EVENT_DIGEST, resume=False):
        _cursor(event_count, event_digest)
        self.path = Path(path)
        self.event_count, self.event_digest = event_count, event_digest
        if resume:
            verify_evidence(self.path, event_count=event_count, event_digest=event_digest)
            mode = "a"
        else:
            if event_count:
                raise ValueError("nonempty cursor requires resumed evidence")
            mode = "x"
        self._stream = self.path.open(mode, encoding="utf-8", newline="\n")

    def append(self, event):
        body = _event_line(event, self.event_count + 1, self.event_digest)
        line = _json(body) + "\n"
        written = self._stream.write(line)
        if written != len(line):
            raise OSError("incomplete event evidence write")
        self.event_count, self.event_digest = body["event_count"], body["digest"]
        return self.event_count, self.event_digest

    def append_events(self, events):
        for event in events:
            self.append(event)
        return self.event_count, self.event_digest

    def flush(self, *, durable=False):
        self._stream.flush()
        if durable:
            os.fsync(self._stream.fileno())

    def close(self):
        self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()


def write_checkpoint(path, state, *, evidence=None):
    """Durably flush supplied evidence, then atomically replace one checkpoint."""
    if evidence is not None:
        if (evidence.event_count, evidence.event_digest) != (state.event_count, state.event_digest):
            raise ValueError("evidence cursor differs from checkpoint state")
        evidence.flush(durable=True)
    text = save_continuous(state)
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


__all__ = ["save_continuous", "restore_continuous", "EvidenceStream", "verify_evidence",
           "write_checkpoint", "input_fingerprint", "source_fingerprint", "runtime_fingerprint",
           "validate_accounting"]
