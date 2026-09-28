# ENE-C2-086 — Unit Tests: SourceIntakeNode + input-contract validation
#
# Covers the input-contract behaviour (docs/02 Input Contract & Source-Approval Assurance): valid
# pass-through, a request the caller can correct degrading to SUCCESS + error_code (the six contract
# codes plus empty / non-JSON / too-deep requests) with an owned delta only, non-sensitive audit (no
# raw payload / source text / approval detail leaked), the S-2 structural gate that stays a
# fail-closed error, and the S-1 trust declaration + runtime refusal.

import json

import pytest

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes import source_intake_node as node_mod
from src.nodes.source_intake_node import SourceIntakeNode
from src.services import degradation
from src.services import input_schema as ischema


def _src(source_id="s1", approval_ref="a1"):
    return {
        "source_id": source_id,
        "locator": "page-1",
        "approval": {"attested_by": "env-owner", "attested_at": "2026-01-01", "approval_ref": approval_ref},
    }


def _valid_payload():
    return {
        "observations": [
            {"observation_id": "obs-1", "value": 1.2, "unit": "ppb",
             "observed_at": "2026-01-01T00:00:00Z", "location": "sector-A", "source_ref": _src("s1")},
            {"observation_id": "obs-2", "value": 3.4, "unit": "ppb",
             "observed_at": "2026-01-02T00:00:00Z", "location": "sector-B", "source_ref": _src("s2")},
        ],
        "asset_reference_map": [
            {"observation_ref": "obs-1", "asset_id": "asset-X", "relation": "locational"},
        ],
        "method_notes": [{"text": "coverage limited to sectors A/B", "source_ref": _src("s3")}],
        "reporting_template": {"sections": ["summary", "limitations"]},
    }


def _run(payload_or_raw):
    raw = payload_or_raw if isinstance(payload_or_raw, str) else json.dumps(payload_or_raw)
    return SourceIntakeNode().execute({"user_input": raw, "correlation_id": "c1"})


# --- 1. valid input ---------------------------------------------------------------------
def test_valid_input_passes_through():
    payload = _valid_payload()
    out = _run(payload)
    assert out["status"] == AgentStatus.SUCCESS.value
    assert isinstance(out["status"], str)
    assert out["validated_input"] == {
        "observations": payload["observations"],
        "asset_reference_map": payload["asset_reference_map"],
        "method_notes": payload["method_notes"],
        "reporting_template": payload["reporting_template"],
    }


# --- 2..7. the six contract codes: the caller can correct them, so the run degrades ------
def _assert_rejected(out, code):
    # Completes as SUCCESS carrying the code; nothing validated is handed on and nothing is logged
    # as an error — post_process turns the code into the notice.
    assert out == {"error_code": code, "status": AgentStatus.SUCCESS.value}
    assert code in degradation.DEGRADATION_CODES


def test_duplicate_observation_id():
    p = _valid_payload()
    p["observations"][1]["observation_id"] = "obs-1"  # duplicate
    _assert_rejected(_run(p), ischema.ERR_AMBIGUOUS_OBSERVATION_REF)


def test_unknown_observation_ref():
    p = _valid_payload()
    p["asset_reference_map"][0]["observation_ref"] = "obs-404"
    _assert_rejected(_run(p), ischema.ERR_UNKNOWN_OBSERVATION_REF)


def test_nonlocational_relation():
    p = _valid_payload()
    p["asset_reference_map"][0]["relation"] = "emission_source"
    _assert_rejected(_run(p), ischema.ERR_NONLOCATIONAL_RELATION)


def test_unattested_source():
    p = _valid_payload()
    del p["observations"][0]["source_ref"]["approval"]  # citable but unattested
    _assert_rejected(_run(p), ischema.ERR_UNATTESTED_SOURCE)


def test_uncitable_source():
    p = _valid_payload()
    del p["observations"][0]["source_ref"]["source_id"]  # attested but uncitable
    _assert_rejected(_run(p), ischema.ERR_UNCITABLE)


def test_schema_missing_required_field():
    p = _valid_payload()
    del p["method_notes"]
    _assert_rejected(_run(p), ischema.ERR_SCHEMA)


def test_schema_wrong_type_value():
    p = _valid_payload()
    p["observations"][0]["value"] = "1.2"  # value must be a finite number, not str
    _assert_rejected(_run(p), ischema.ERR_SCHEMA)


def test_schema_control_character():
    p = _valid_payload()
    p["observations"][0]["observation_id"] = "obs\x00-1"  # NUL survives JSON round-trip
    _assert_rejected(_run(p), ischema.ERR_SCHEMA)


def test_schema_extra_map_field_rejected():
    # An asset association carries ONLY {observation_ref, asset_id, relation}; a would-be
    # attribution / leak marker is rejected structurally.
    p = _valid_payload()
    p["asset_reference_map"][0]["emission_source"] = "asset-X"
    _assert_rejected(_run(p), ischema.ERR_SCHEMA)


def test_schema_unknown_nested_field_rejected():
    # Unknown keys on observation / method_note / source_ref are rejected — no unvalidated
    # nested blob can ride through into validated_input.
    for mutate in (
        lambda p: p["observations"][0].__setitem__("raw_blob", {"x": [1, 2]}),
        lambda p: p["method_notes"][0].__setitem__("extra", "smuggled"),
        lambda p: p["observations"][0]["source_ref"].__setitem__("side_channel", {"k": "v"}),
    ):
        p = _valid_payload()
        mutate(p)
        _assert_rejected(_run(p), ischema.ERR_SCHEMA)


def test_schema_numeric_boundary_rejected():
    # An arbitrary-precision huge int (OverflowError on float conversion), NaN, and ±Infinity must
    # all fail closed with ERR_SCHEMA — never an unhandled exception at the untrusted boundary.
    for bad in (10 ** 1000, float("inf"), float("-inf"), float("nan")):
        p = _valid_payload()
        p["observations"][0]["value"] = bad
        _assert_rejected(_run(p), ischema.ERR_SCHEMA)


def test_reporting_template_huge_int_rejected():
    p = _valid_payload()
    p["reporting_template"] = {"limit": 10 ** 1000}
    _assert_rejected(_run(p), ischema.ERR_SCHEMA)


def test_reporting_template_control_char_rejected():
    # A JSON-escaped NUL survives decode into a real control char in a template leaf → ERR_SCHEMA.
    p = _valid_payload()
    p["reporting_template"] = {"sections": ["summary", "bad\x00leaf"]}
    _assert_rejected(_run(p), ischema.ERR_SCHEMA)


def test_reporting_template_over_depth_rejected():
    p = _valid_payload()
    nested: dict = {}
    for _ in range(12):  # exceeds _TEMPLATE_MAX_DEPTH
        nested = {"x": nested}
    p["reporting_template"] = nested
    _assert_rejected(_run(p), ischema.ERR_SCHEMA)


def test_valid_reporting_template_with_bounded_nesting_passes():
    p = _valid_payload()
    p["reporting_template"] = {"sections": [{"title": "Summary", "placeholders": ["{obs}", "{limits}"]}]}
    out = _run(p)
    assert out["status"] == AgentStatus.SUCCESS.value
    assert out["validated_input"]["reporting_template"] == p["reporting_template"]


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", degradation.EMPTY_REQUEST),
        ("   ", degradation.EMPTY_REQUEST),
        ("{not json", degradation.MALFORMED_JSON),
        ("[" * 100_000 + "]" * 100_000, degradation.TOO_DEEP),
        (json.dumps(["not", "an", "object"]), ischema.ERR_SCHEMA),
    ],
    ids=["empty", "blank", "not-json", "too-deep", "not-an-object"],
)
def test_schema_empty_and_malformed_input(raw, code):
    _assert_rejected(_run(raw), code)


def test_an_unanswerable_code_is_not_degraded(monkeypatch):
    # Degrading means the agent has a notice for the code. A code it cannot answer is a defect, so
    # it fails closed as an error instead of completing with a generic sentence.
    def _raise(_payload):
        raise ischema.InputContractError("ERR_NOT_A_CONTRACT_CODE")

    monkeypatch.setattr(node_mod, "validate_and_normalize", _raise)
    out = _run(_valid_payload())
    assert out["status"] == AgentStatus.ERROR.value
    assert "error_code" not in out


# --- 8. no sensitive leak in error_log or audit events ----------------------------------
def test_reject_does_not_leak_payload(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda ev, payload, state: events.append((ev, payload)))
    p = _valid_payload()
    p["observations"][0]["source_ref"]["approval"]["approval_ref"] = "SENTINEL_APPROVAL_9f3a"
    p["method_notes"][0]["text"] = "SENTINEL_NOTE_TEXT_x1"
    p["asset_reference_map"][0]["relation"] = "emission_source"  # → ERR_NONLOCATIONAL_RELATION
    out = SourceIntakeNode().execute({"user_input": json.dumps(p), "correlation_id": "c1"})
    assert out["error_code"] == ischema.ERR_NONLOCATIONAL_RELATION
    blob = json.dumps(out) + json.dumps(events, default=str)
    assert "SENTINEL_APPROVAL_9f3a" not in blob
    assert "SENTINEL_NOTE_TEXT_x1" not in blob


# --- S-2 structural gate (runs before execute; returns a dict, never raises) -------------
def test_s2_gate_rejects_structural():
    node = SourceIntakeNode()
    for bad in ("payload\x00binary", "x" * (node_mod._MAX_INPUT_CHARS + 1)):
        gated = node._extra_security_gate_input({"user_input": bad, "correlation_id": "c1"})
        assert gated["status"] == AgentStatus.ERROR.value
        assert gated["error_log"] == [ischema.ERR_SCHEMA]
    # non-str raw input is rejected, never str()-coerced
    gated = node._extra_security_gate_input({"user_input": b"\x00abc", "correlation_id": "c1"})
    assert gated["status"] == AgentStatus.ERROR.value
    # clean input passes the gate unchanged
    clean = {"user_input": json.dumps(_valid_payload()), "correlation_id": "c1"}
    assert node._extra_security_gate_input(clean) is clean


# --- 9. S-1 trust: declaration + runtime refusal before execute() -----------------------
def test_required_trust_level_declared():
    assert SourceIntakeNode.required_trust_level is TrustLevel.VERIFIED_EXTERNAL


def test_s1_refuses_insufficient_trust(monkeypatch):
    node = SourceIntakeNode()
    reached = {"execute": False}

    def _spy(state):
        reached["execute"] = True
        return {"validated_input": {}, "status": AgentStatus.SUCCESS.value}

    monkeypatch.setattr(node, "execute", _spy)
    state = {
        "user_input": json.dumps(_valid_payload()),
        "caller_trust_level": TrustLevel.ANONYMOUS.value,  # insufficient for VERIFIED_EXTERNAL
        "node_history": [],
        "error_log": [],
    }
    result = node(state)  # real BaseNode.__call__ enforces the S-1 gate
    assert reached["execute"] is False, "execute() must not run when the S-1 trust gate refuses"
    assert result.get("status") == AgentStatus.ERROR.value
