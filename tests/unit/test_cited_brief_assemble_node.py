# ENE-C2-086 — Unit Tests: CitedBriefAssembleNode (inner evidence workflow)
#
# Covers the deterministic cited-brief assembly (docs/02 — inner `cited_brief_assemble` row):
# every source-derived statement (observation / locational association / methodology limitation)
# resolves 1:1 to a supplied source_ref; a coverage gap carries a structural basis and NO source_ref;
# missing / duplicate / inconsistent citations fail closed with ERR_SOURCE_CITATION_MISMATCH and no
# partial brief; owned-delta-only returns; non-sensitive audit; no leak / attribution / estimation
# field. Assembly is deterministic (no LLM, no arithmetic). Graph wiring is a later issue.

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes import cited_brief_assemble_node as node_mod
from src.nodes.cited_brief_assemble_node import CitedBriefAssembleNode
from src.services import input_schema as ischema

_ALLOWED_KEYS = {"context_brief", "result", "status"}
_FORBIDDEN_FIELDS = {
    "leak_detected", "emission_source", "estimated_emission", "regulatory_breach",
    "recommended_action", "formatted_output",
}


def _src(sid="s1"):
    return {
        "source_id": sid,
        "locator": "page-1",
        "approval": {"attested_by": "env-owner", "attested_at": "2026-01-01", "approval_ref": "a1"},
    }


def _full_state():
    sr1, sr2, sr3 = _src("s1"), _src("s2"), _src("s3")
    observations = [
        {"observation_id": "obs-1", "value": 111.5, "unit": "ppb",
         "observed_at": "2026-01-01T00:00:00Z", "location": "sector-A", "source_ref": sr1},
        {"observation_id": "obs-2", "value": 222, "unit": "ppb",
         "observed_at": "2026-01-02T00:00:00Z", "location": "sector-B", "source_ref": sr2},
    ]
    asset_associations = [
        {"observation_ref": "obs-1", "asset_id": "asset-X", "relation": "locational", "source_ref": sr1},
    ]
    methodology_limitations = [
        {"kind": "methodology_limitation", "statement": "coverage limited to sectors A/B", "source_ref": sr3},
    ]
    coverage_gaps = [
        {"kind": "coverage_gap", "reason": "single_location_coverage",
         "basis": {"location_count": 1, "observation_count": 2}},
    ]
    citations = [
        {"subject_type": "observation", "subject_ref": "obs-1", "source_ref": sr1},
        {"subject_type": "observation", "subject_ref": "obs-2", "source_ref": sr2},
        {"subject_type": "asset_association",
         "subject_ref": {"observation_ref": "obs-1", "asset_id": "asset-X"}, "source_ref": sr1},
    ]
    # method_notes is the provenance set for methodology limitations: the supplied note here matches
    # the limitation (same text + source_ref), so it resolves 1:1.
    method_notes = [{"text": "coverage limited to sectors A/B", "source_ref": sr3}]
    return {
        "validated_input": {"reporting_template": {"sections": ["summary", "limitations"]},
                            "method_notes": method_notes, "observations": observations, "asset_reference_map": []},
        "observations": observations,
        "asset_associations": asset_associations,
        "methodology_limitations": methodology_limitations,
        "coverage_gaps": coverage_gaps,
        "citations": citations,
        "correlation_id": "c1",
    }


def _run(state=None):
    return CitedBriefAssembleNode().execute(state if state is not None else _full_state())


def _assert_rejected(out, code):
    assert out["status"] == AgentStatus.ERROR.value
    assert out["error_log"] == [code]
    assert "context_brief" not in out
    assert "result" not in out


# --- 1. normal brief: every source-derived statement resolves 1:1 to its source_ref -----------
def test_normal_brief_resolves_citations_1to1():
    out = _run()
    assert out["status"] == AgentStatus.SUCCESS.value
    brief = out["context_brief"]
    assert out["result"] == brief  # result is the same cited brief
    statements = brief["statements"]
    # 2 observations + 1 association + 1 limitation + 1 gap
    assert len(statements) == 5
    for st in statements:
        if st["kind"] == "coverage_gap":
            assert "source_ref" not in st
            assert isinstance(st["basis"], dict)
        else:
            # source-derived → exactly one canonical source_ref citation
            assert set(st["source_ref"].keys()) == {"source_id", "locator", "approval"}


# --- 3. brief includes each statement kind ----------------------------------------------------
def test_brief_contains_each_statement_kind():
    brief = _run()["context_brief"]
    kinds = {st["kind"] for st in brief["statements"]}
    assert kinds == {"observation", "asset_association", "methodology_limitation", "coverage_gap"}


def test_observation_citation_matches_supplied_source_ref():
    state = _full_state()
    out = _run(state)
    by_ref = {st["subject_ref"]: st for st in out["context_brief"]["statements"] if st["kind"] == "observation"}
    assert by_ref["obs-1"]["source_ref"]["source_id"] == "s1"
    assert by_ref["obs-2"]["source_ref"]["source_id"] == "s2"


def test_association_inherits_referenced_observation_source_ref():
    st = next(s for s in _run()["context_brief"]["statements"] if s["kind"] == "asset_association")
    assert st["source_ref"]["source_id"] == "s1"  # obs-1's source
    assert st["subject_ref"] == {"observation_ref": "obs-1", "asset_id": "asset-X"}


def test_coverage_gap_carries_basis_not_source_ref():
    st = next(s for s in _run()["context_brief"]["statements"] if s["kind"] == "coverage_gap")
    assert st["basis"] == {"location_count": 1, "observation_count": 2}
    assert "source_ref" not in st


# --- 2. citation missing / duplicate / inconsistent → ERR_SOURCE_CITATION_MISMATCH ------------
def test_missing_citation_rejected():
    state = _full_state()
    state["citations"] = [c for c in state["citations"] if c["subject_ref"] != "obs-2"]  # drop obs-2 citation
    _assert_rejected(_run(state), ischema.ERR_SOURCE_CITATION_MISMATCH)


def test_duplicate_citation_rejected():
    state = _full_state()
    state["citations"].append({"subject_type": "observation", "subject_ref": "obs-1", "source_ref": _src("s1")})
    _assert_rejected(_run(state), ischema.ERR_SOURCE_CITATION_MISMATCH)


def test_inconsistent_citation_source_ref_rejected():
    state = _full_state()
    for c in state["citations"]:
        if c["subject_ref"] == "obs-1":
            c["source_ref"] = _src("DIFFERENT")  # citation anchors a different source than the observation
    _assert_rejected(_run(state), ischema.ERR_SOURCE_CITATION_MISMATCH)


def test_missing_association_citation_rejected():
    state = _full_state()
    state["citations"] = [c for c in state["citations"] if c["subject_type"] != "asset_association"]
    _assert_rejected(_run(state), ischema.ERR_SOURCE_CITATION_MISMATCH)


def test_limitation_without_valid_source_ref_rejected():
    state = _full_state()
    state["methodology_limitations"][0]["source_ref"] = {}  # uncitable → citation mismatch
    _assert_rejected(_run(state), ischema.ERR_SOURCE_CITATION_MISMATCH)


def test_limitation_citation_missing_from_supplied_notes_rejected():
    # limitation whose (text, source_ref) matches NO supplied method note → missing citation
    state = _full_state()
    state["validated_input"]["method_notes"] = []  # no note backs the limitation
    _assert_rejected(_run(state), ischema.ERR_SOURCE_CITATION_MISMATCH)


def test_limitation_citation_duplicate_in_supplied_notes_rejected():
    # two identical supplied notes both match the limitation → ambiguous/duplicate resolution
    state = _full_state()
    note = state["validated_input"]["method_notes"][0]
    state["validated_input"]["method_notes"] = [note, {"text": note["text"], "source_ref": note["source_ref"]}]
    _assert_rejected(_run(state), ischema.ERR_SOURCE_CITATION_MISMATCH)


def test_limitation_citation_source_ref_inconsistent_rejected():
    # the limitation's source_ref does not match the source_ref of the note carrying its text
    state = _full_state()
    state["methodology_limitations"][0]["source_ref"] = _src("s9-different")
    _assert_rejected(_run(state), ischema.ERR_SOURCE_CITATION_MISMATCH)


def test_malformed_evidence_shape_rejected():
    # non-dict validated_input, non-list evidence, broken observation → ERR_SCHEMA
    state = _full_state(); state["validated_input"] = "x"
    _assert_rejected(_run(state), ischema.ERR_SCHEMA)
    state = _full_state(); state["validated_input"]["reporting_template"] = "x"
    _assert_rejected(_run(state), ischema.ERR_SCHEMA)
    state = _full_state(); state["observations"] = "x"
    _assert_rejected(_run(state), ischema.ERR_SCHEMA)
    state = _full_state(); del state["observations"][0]["unit"]
    _assert_rejected(_run(state), ischema.ERR_SCHEMA)


# --- 4. no leak / attribution / estimation field in the assembled brief -----------------------
def test_brief_contains_no_forbidden_fields():
    blob = json.dumps(_run()["context_brief"])
    for banned in _FORBIDDEN_FIELDS:
        assert banned not in blob


# --- 8. owned delta bounded to the three fields ----------------------------------------------
def test_returned_keys_bounded_on_success():
    assert set(_run().keys()) == _ALLOWED_KEYS


def test_returned_keys_bounded_on_reject():
    state = _full_state(); state["citations"] = []
    out = _run(state)
    assert set(out.keys()) == {"status", "error_log"}


# --- 9. one domain audit event on success and reject -----------------------------------------
def test_success_emits_one_event(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda ev, payload, state: events.append((ev, payload)))
    _run()
    assert len(events) == 1 and events[0][0] == "brief_assemble"


def test_reject_emits_one_event_and_leaks_nothing(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda ev, payload, state: events.append((ev, payload)))
    state = _full_state()
    state["methodology_limitations"][0]["statement"] = "SENTINEL_NOTE_zz"
    state["citations"] = []  # force a mismatch on the first observation
    out = _run(state)
    assert out["status"] == AgentStatus.ERROR.value
    assert len(events) == 1
    blob = json.dumps(out) + json.dumps(events, default=str)
    assert "SENTINEL_NOTE_zz" not in blob


# --- S-1 trust + construction ----------------------------------------------------------------
def test_required_trust_level_is_anonymous():
    assert CitedBriefAssembleNode.required_trust_level is TrustLevel.ANONYMOUS


def test_node_is_constructible_with_no_args():
    assert CitedBriefAssembleNode() is not None
