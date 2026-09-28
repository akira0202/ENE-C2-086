# ENE-C2-086 — Unit Tests: LimitGapAnalysisNode (inner evidence workflow)
#
# Covers the inner limitation/gap contract (docs/02 — inner `limit_gap_analysis` row):
# methodology_limitations derived ONLY from supplied method notes (verbatim statement + inherited
# source_ref, no LLM/inference), coverage_gaps derived deterministically from the SUPPLIED
# observations / associations structure (structural basis, NO source_ref reuse), owned-delta-only
# returns, fail-closed node-local defense with non-sensitive audit, no arithmetic on observation
# values, and the absence of any leak / attribution / estimation / breach field. This node writes
# NONE of citations / context_brief / result / formatted_output. Graph wiring is a later issue.

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes import limit_gap_analysis_node as node_mod
from src.nodes.limit_gap_analysis_node import LimitGapAnalysisNode
from src.services import input_schema as ischema

_ALLOWED_KEYS = {"methodology_limitations", "coverage_gaps", "status"}
_FORBIDDEN_FIELDS = {
    "leak_detected", "emission_source", "estimated_emission", "regulatory_breach",
    "recommended_action", "context_brief", "result", "formatted_output", "citations",
}
# Distinctive supplied observation values — must NOT appear anywhere in the output (no arithmetic).
_V1, _V2 = 111.5, 222.25


def _src(source_id="s1"):
    return {
        "source_id": source_id,
        "locator": "page-1",
        "approval": {"attested_by": "env-owner", "attested_at": "2026-01-01", "approval_ref": "a1"},
    }


def _obs(obs_id, location, value):
    return {"observation_id": obs_id, "value": value, "unit": "ppb",
            "observed_at": "2026-01-01T00:00:00Z", "location": location, "source_ref": _src("os")}


def _state(method_notes=None, observations=None, asset_associations=None):
    if method_notes is None:
        method_notes = [{"text": "coverage limited to sectors A/B", "source_ref": _src("s1")}]
    if observations is None:
        observations = [_obs("obs-1", "sector-A", _V1), _obs("obs-2", "sector-B", _V2)]
    if asset_associations is None:
        asset_associations = [{"observation_ref": "obs-1", "asset_id": "asset-X",
                               "relation": "locational", "source_ref": _src("os")}]
    return {
        "validated_input": {"method_notes": method_notes,
                            "observations": observations,  # (present in validated_input too; node reads top-level)
                            "asset_reference_map": [], "reporting_template": {}},
        "observations": observations,
        "asset_associations": asset_associations,
        "correlation_id": "c1",
    }


def _run(**kw):
    return LimitGapAnalysisNode().execute(_state(**kw))


def _assert_rejected(out, code=ischema.ERR_SCHEMA):
    assert out["status"] == AgentStatus.ERROR.value
    assert isinstance(out["status"], str)
    assert out["error_log"] == [code]
    assert "methodology_limitations" not in out
    assert "coverage_gaps" not in out


# --- 1. one limitation per method note, verbatim statement + inherited source_ref -------------
def test_limitation_per_note_inherits_source_ref_verbatim():
    notes = [
        {"text": "coverage limited to sectors A/B", "source_ref": _src("s1")},
        {"text": "instrument calibrated 2026-01", "source_ref": _src("s2")},
    ]
    out = _run(method_notes=notes)
    assert out["status"] == AgentStatus.SUCCESS.value
    assert len(out["methodology_limitations"]) == 2
    for note, lim in zip(notes, out["methodology_limitations"]):
        assert lim["kind"] == "methodology_limitation"
        assert lim["statement"] == note["text"]          # verbatim, not summarized
        assert lim["source_ref"] == note["source_ref"]   # inherited from the originating note
        assert set(lim.keys()) == {"kind", "statement", "source_ref"}


def test_limitation_source_ref_is_deep_copied():
    notes = [{"text": "note", "source_ref": _src("s1")}]
    out = _run(method_notes=notes)
    out["methodology_limitations"][0]["source_ref"]["source_id"] = "TAMPERED"
    assert notes[0]["source_ref"]["source_id"] == "s1"


# --- 2. empty method notes → empty limitations, still success ---------------------------------
def test_empty_method_notes_is_success_with_no_limitations():
    out = _run(method_notes=[])
    assert out["status"] == AgentStatus.SUCCESS.value
    assert out["methodology_limitations"] == []


# --- 3. missing / invalid source_ref or text on a note → fail-closed, no partial -------------
def test_note_without_source_ref_rejected():
    _assert_rejected(LimitGapAnalysisNode().execute(_state(method_notes=[{"text": "note"}])))


def test_note_with_non_dict_source_ref_rejected():
    _assert_rejected(_run(method_notes=[{"text": "note", "source_ref": "s1"}]))


def test_note_with_empty_source_ref_rejected():
    # {} is missing source_id / locator → uncitable, not merely a schema shape error.
    _assert_rejected(_run(method_notes=[{"text": "note", "source_ref": {}}]), ischema.ERR_UNCITABLE)


def test_note_source_ref_empty_source_id_rejected():
    sr = _src(); sr["source_id"] = ""
    _assert_rejected(_run(method_notes=[{"text": "note", "source_ref": sr}]), ischema.ERR_UNCITABLE)


def test_note_source_ref_missing_locator_rejected():
    sr = _src(); del sr["locator"]
    _assert_rejected(_run(method_notes=[{"text": "note", "source_ref": sr}]), ischema.ERR_UNCITABLE)


def test_note_source_ref_missing_approval_rejected():
    sr = _src(); del sr["approval"]
    _assert_rejected(_run(method_notes=[{"text": "note", "source_ref": sr}]), ischema.ERR_UNATTESTED_SOURCE)


def test_note_source_ref_extra_raw_blob_rejected():
    # an extra nested key must not ride through into the limitation citation.
    sr = _src(); sr["raw_blob"] = {"x": [1, 2]}
    _assert_rejected(_run(method_notes=[{"text": "note", "source_ref": sr}]), ischema.ERR_SCHEMA)


def test_limitation_source_ref_is_allowlisted_canonical_copy():
    # even a valid source_ref is rebuilt from the allowlisted keys only (no pass-through).
    out = _run(method_notes=[{"text": "note", "source_ref": _src("s9")}])
    sr = out["methodology_limitations"][0]["source_ref"]
    assert set(sr.keys()) == {"source_id", "locator", "approval"}
    assert set(sr["approval"].keys()) == {"attested_by", "attested_at", "approval_ref"}
    assert sr["source_id"] == "s9"


def test_note_without_text_rejected():
    for bad in ({"source_ref": _src()}, {"text": "", "source_ref": _src()}, {"text": 5, "source_ref": _src()}):
        _assert_rejected(_run(method_notes=[bad]))


def test_no_citation_is_fabricated_on_reject():
    # a bad note must not produce a limitation with an invented citation — nothing partial escapes.
    out = _run(method_notes=[{"text": "note", "source_ref": {}}])
    assert "methodology_limitations" not in out


# --- 4. deterministic structural coverage gaps ------------------------------------------------
def test_gap_no_observations():
    # no observations → also no associations can resolve, so associations are empty here.
    out = _run(observations=[], asset_associations=[])
    reasons = {g["reason"]: g for g in out["coverage_gaps"]}
    assert "no_observations_supplied" in reasons
    assert reasons["no_observations_supplied"]["basis"] == {"observation_count": 0}
    assert reasons["no_observations_supplied"]["kind"] == "coverage_gap"


def test_gap_no_association():
    out = _run(asset_associations=[])
    reasons = {g["reason"]: g for g in out["coverage_gaps"]}
    assert "no_locational_association_supplied" in reasons
    assert reasons["no_locational_association_supplied"]["basis"] == {"association_count": 0}


def test_gap_single_location():
    obs = [_obs("obs-1", "sector-A", _V1), _obs("obs-2", "sector-A", _V2)]
    out = _run(observations=obs)
    reasons = {g["reason"]: g for g in out["coverage_gaps"]}
    assert "single_location_coverage" in reasons
    assert reasons["single_location_coverage"]["basis"] == {"location_count": 1, "observation_count": 2}


def test_malformed_association_is_not_counted_as_coverage():
    # A malformed / non-locational / unresolved association must NOT be silently counted (which would
    # wrongly suppress the no_locational_association gap) — it fails closed instead.
    _assert_rejected(_run(asset_associations=[{}]), ischema.ERR_SCHEMA)
    _assert_rejected(_run(asset_associations=[{"observation_ref": "obs-1", "asset_id": "", "relation": "locational"}]),
                     ischema.ERR_SCHEMA)
    _assert_rejected(
        _run(asset_associations=[{"observation_ref": "obs-1", "asset_id": "asset-X", "relation": "emission_source"}]),
        ischema.ERR_NONLOCATIONAL_RELATION)
    _assert_rejected(
        _run(asset_associations=[{"observation_ref": "obs-404", "asset_id": "asset-X", "relation": "locational"}]),
        ischema.ERR_UNKNOWN_OBSERVATION_REF)


def test_no_spurious_gap_when_coverage_is_adequate():
    # 2 observations, 2 locations, 1 association → none of the structural gaps fire.
    out = _run()
    assert out["status"] == AgentStatus.SUCCESS.value
    assert out["coverage_gaps"] == []


def test_gaps_never_carry_a_source_ref():
    # a gap is not a source-derived statement — it must not reuse any method-note source_ref.
    out = _run(observations=[], asset_associations=[])
    assert len(out["coverage_gaps"]) >= 2
    for gap in out["coverage_gaps"]:
        assert "source_ref" not in gap
        assert set(gap.keys()) == {"kind", "reason", "basis"}


# --- 5. no arithmetic / estimation / averaging on observation values --------------------------
def test_no_observation_value_arithmetic_or_leak_into_output():
    out = _run()  # observations carry _V1 / _V2
    blob = json.dumps(out)
    # supplied values never surface, and no averaged / summed derivative appears either
    assert str(_V1) not in blob
    assert str(_V2) not in blob
    assert str((_V1 + _V2)) not in blob
    assert str((_V1 + _V2) / 2) not in blob


# --- 6. no leak / attribution / estimation / breach field is ever emitted ---------------------
def test_output_contains_no_leak_or_attribution_fields_even_with_associations():
    out = _run()  # has an asset association
    assert set(out.keys()) == _ALLOWED_KEYS
    blob = json.dumps(out)
    for banned in _FORBIDDEN_FIELDS:
        assert banned not in blob, f"forbidden field {banned!r} leaked into output"


# --- 7. owned delta bounded to the three fields ----------------------------------------------
def test_returned_keys_bounded_on_success():
    assert set(_run().keys()) == _ALLOWED_KEYS


def test_returned_keys_bounded_on_reject():
    out = _run(method_notes=[{"text": "note", "source_ref": {}}])
    assert set(out.keys()) == {"status", "error_log"}


# --- 8. one domain audit event on both success and reject; payload is counts / code only ------
def test_success_emits_exactly_one_domain_event(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda ev, payload, state: events.append((ev, payload)))
    out = _run()
    assert out["status"] == AgentStatus.SUCCESS.value
    assert len(events) == 1
    assert events[0][0] == "limit_gap"


def test_reject_emits_one_event_and_leaks_nothing(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda ev, payload, state: events.append((ev, payload)))
    notes = [{"text": "SENTINEL_NOTE_TEXT_x1", "source_ref": {}}]  # uncitable source_ref → reject
    observations = [_obs("obs-1", "SENTINEL_LOCATION_zz", _V1)]
    st = _state(method_notes=notes, observations=observations)
    out = LimitGapAnalysisNode().execute(st)
    assert out["error_log"] == [ischema.ERR_UNCITABLE]
    assert len(events) == 1
    blob = json.dumps(out) + json.dumps(events, default=str)
    assert "SENTINEL_NOTE_TEXT_x1" not in blob
    assert "SENTINEL_LOCATION_zz" not in blob
    assert str(_V1) not in blob


# --- node-local defense: malformed top-level shapes fail closed -------------------------------
def test_bad_validated_input_and_shapes_rejected():
    # validated_input not a dict
    _assert_rejected(LimitGapAnalysisNode().execute(
        {"validated_input": "x", "observations": [], "asset_associations": [], "correlation_id": "c1"}))
    # method_notes not a list
    st = _state(); st["validated_input"]["method_notes"] = "nope"
    _assert_rejected(LimitGapAnalysisNode().execute(st))
    # observations not a list
    st = _state(); st["observations"] = {"a": 1}
    _assert_rejected(LimitGapAnalysisNode().execute(st))
    # asset_associations not a list
    st = _state(); st["asset_associations"] = "nope"
    _assert_rejected(LimitGapAnalysisNode().execute(st))


def test_broken_observation_shape_rejected():
    for bad_obs in ([{"observation_id": "obs-1"}],           # missing location
                    [{"location": "sector-A"}],              # missing observation_id
                    [{"observation_id": "", "location": "sector-A"}],  # empty id
                    [{"observation_id": "obs-1", "location": ""}],     # empty location
                    ["not-a-dict"]):
        _assert_rejected(_run(observations=bad_obs))


# --- S-1 trust + construction + real __call__ boundary ---------------------------------------
def test_required_trust_level_is_anonymous():
    assert LimitGapAnalysisNode.required_trust_level is TrustLevel.ANONYMOUS


def test_node_is_constructible_with_no_args():
    assert LimitGapAnalysisNode() is not None


def test_call_path_reaches_execute_and_returns_owned_delta():
    node = LimitGapAnalysisNode()
    st = _state()
    st["caller_trust_level"] = TrustLevel.ANONYMOUS.value
    st["node_history"] = []
    st["error_log"] = []
    out = node(st)
    assert out["status"] == AgentStatus.SUCCESS.value
    assert _ALLOWED_KEYS <= set(out.keys())
