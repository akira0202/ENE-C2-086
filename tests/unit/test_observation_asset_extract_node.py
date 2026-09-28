# ENE-C2-086 — Unit Tests: ObservationAssetExtractNode (inner evidence workflow)
#
# Covers the inner extraction contract (docs/02 — inner `observation_asset_extract` row):
# value-invariant observation pass-through, locational-only
# associations inheriting the resolved observation's source_ref, one citation per emitted item
# (1:1 traceable to a supplied source_ref), node-local fail-closed defense with owned-delta-only
# rejects and non-sensitive audit, the S-1 (ANONYMOUS) trust declaration, and the bounded output
# key set. This node NEVER identifies a leak, attributes emissions, or estimates — verified by the
# absence of any such field in the output. Graph wiring is a later issue.

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes import observation_asset_extract_node as node_mod
from src.nodes.observation_asset_extract_node import ObservationAssetExtractNode
from src.services import input_schema as ischema

# Owned delta: this node writes exactly these keys and nothing else.
_ALLOWED_KEYS = {"observations", "asset_associations", "citations", "status"}
# Fields that must NEVER appear in the output — leak / attribution / estimation markers.
_FORBIDDEN_FIELDS = {
    "leak_detected", "emission_source", "estimated_emission", "regulatory_breach",
    "recommended_action", "methodology_limitations", "coverage_gaps", "context_brief",
    "result", "formatted_output",
}


def _src(source_id="s1", approval_ref="a1"):
    return {
        "source_id": source_id,
        "locator": "page-1",
        "approval": {"attested_by": "env-owner", "attested_at": "2026-01-01", "approval_ref": approval_ref},
    }


def _valid_input():
    """A canonical validated_input as produced by SourceIntakeNode (outer pre_process) — the node's sole input."""
    return {
        "observations": [
            {"observation_id": "obs-1", "value": 1.2, "unit": "ppb",
             "observed_at": "2026-01-01T00:00:00Z", "location": "sector-A", "source_ref": _src("s1")},
            {"observation_id": "obs-2", "value": 3, "unit": "ppb",
             "observed_at": "2026-01-02T00:00:00Z", "location": "sector-B", "source_ref": _src("s2")},
        ],
        "asset_reference_map": [
            {"observation_ref": "obs-1", "asset_id": "asset-X", "relation": "locational"},
        ],
        "method_notes": [{"text": "coverage limited to sectors A/B", "source_ref": _src("s3")}],
        "reporting_template": {"sections": ["summary", "limitations"]},
    }


def _run(validated_input):
    return ObservationAssetExtractNode().execute({"validated_input": validated_input, "correlation_id": "c1"})


def _assert_rejected(out, code):
    assert out["status"] == AgentStatus.ERROR.value
    assert isinstance(out["status"], str)
    assert out["error_log"] == [code]
    # No partial output on the fail-closed path.
    assert "observations" not in out
    assert "asset_associations" not in out
    assert "citations" not in out


# --- 1. valid input: value-invariant observations + associations inherit source_ref -----------
def test_valid_extraction_is_value_invariant_and_inherits_source_ref():
    vi = _valid_input()
    out = _run(vi)
    assert out["status"] == AgentStatus.SUCCESS.value

    # observations are a minimal copy with EXACTLY the six documented keys, values unchanged.
    assert [o["observation_id"] for o in out["observations"]] == ["obs-1", "obs-2"]
    for src_obs, out_obs in zip(vi["observations"], out["observations"]):
        assert set(out_obs.keys()) == {"observation_id", "value", "unit", "observed_at", "location", "source_ref"}
        assert out_obs["value"] == src_obs["value"]          # not converted / rounded / estimated
        assert type(out_obs["value"]) is type(src_obs["value"])  # int stays int, float stays float
        assert out_obs["unit"] == src_obs["unit"]
        assert out_obs["observed_at"] == src_obs["observed_at"]
        assert out_obs["location"] == src_obs["location"]
        assert out_obs["source_ref"] == src_obs["source_ref"]

    # associations are locational-only and carry the referenced observation's source_ref (inherited,
    # not minted at the association).
    assert out["asset_associations"] == [{
        "observation_ref": "obs-1",
        "asset_id": "asset-X",
        "relation": "locational",
        "source_ref": vi["observations"][0]["source_ref"],
    }]


def test_association_source_ref_is_the_referenced_observation_not_a_new_one():
    vi = _valid_input()
    # obs-1 and obs-2 have distinct sources; the association references obs-1 → must carry s1.
    out = _run(vi)
    assert out["asset_associations"][0]["source_ref"]["source_id"] == "s1"


def test_output_is_decoupled_from_input_no_shared_mutable_refs():
    vi = _valid_input()
    out = _run(vi)
    # Mutating the output source_ref must not reach back into validated_input (deep-copied).
    out["asset_associations"][0]["source_ref"]["source_id"] = "TAMPERED"
    assert vi["observations"][0]["source_ref"]["source_id"] == "s1"


# --- 2. every citation traces 1:1 from an emitted subject to a supplied source_ref -------------
def test_every_emitted_item_has_a_citation_tracing_to_a_supplied_source_ref():
    vi = _valid_input()
    supplied_source_ids = {o["source_ref"]["source_id"] for o in vi["observations"]}
    out = _run(vi)

    # one citation per observation + one per association (no un-cited emitted item).
    assert len(out["citations"]) == len(out["observations"]) + len(out["asset_associations"])

    obs_ids = {o["observation_id"] for o in out["observations"]}
    assoc_ids = {(a["observation_ref"], a["asset_id"]) for a in out["asset_associations"]}
    for cit in out["citations"]:
        assert cit["subject_type"] in {"observation", "asset_association"}
        # subject_ref resolves to a real emitted subject...
        if cit["subject_type"] == "observation":
            assert cit["subject_ref"] in obs_ids
        else:
            # association subject_ref uniquely identifies the association (observation_ref, asset_id)
            assert (cit["subject_ref"]["observation_ref"], cit["subject_ref"]["asset_id"]) in assoc_ids
        # ...and the citation anchors to a supplied source_ref (1:1 back to source).
        assert cit["source_ref"]["source_id"] in supplied_source_ids


def test_no_observation_or_association_is_emitted_without_a_citation():
    vi = _valid_input()
    # add a second association so we exercise multiple associations
    vi["asset_reference_map"].append({"observation_ref": "obs-2", "asset_id": "asset-Y", "relation": "locational"})
    out = _run(vi)
    cited_obs = {c["subject_ref"] for c in out["citations"] if c["subject_type"] == "observation"}
    cited_assoc = {
        (c["subject_ref"]["observation_ref"], c["subject_ref"]["asset_id"])
        for c in out["citations"] if c["subject_type"] == "asset_association"
    }
    assert cited_obs == {o["observation_id"] for o in out["observations"]}
    assert cited_assoc == {(a["observation_ref"], a["asset_id"]) for a in out["asset_associations"]}


# --- 3. relation: locational allowed; attribution / causal rejected ---------------------------
def test_locational_relation_allowed():
    out = _run(_valid_input())
    assert out["status"] == AgentStatus.SUCCESS.value
    assert out["asset_associations"][0]["relation"] == "locational"


def test_nonlocational_relation_rejected():
    for bad in ("emission_source", "causal", "attribution", "Locational", "LOCATIONAL", ""):
        vi = _valid_input()
        vi["asset_reference_map"][0]["relation"] = bad
        _assert_rejected(_run(vi), ischema.ERR_NONLOCATIONAL_RELATION)


# --- 4. fail-closed: unresolved / duplicate ref, missing source_ref, bad validated_input -------
def test_unresolved_observation_ref_rejected():
    vi = _valid_input()
    vi["asset_reference_map"][0]["observation_ref"] = "obs-404"
    _assert_rejected(_run(vi), ischema.ERR_UNKNOWN_OBSERVATION_REF)


def test_duplicate_observation_id_rejected():
    vi = _valid_input()
    vi["observations"][1]["observation_id"] = "obs-1"  # duplicate → reference cannot resolve 1:1
    _assert_rejected(_run(vi), ischema.ERR_AMBIGUOUS_OBSERVATION_REF)


def test_missing_source_ref_rejected():
    vi = _valid_input()
    del vi["observations"][0]["source_ref"]
    _assert_rejected(_run(vi), ischema.ERR_SCHEMA)


def test_source_ref_not_a_dict_rejected():
    vi = _valid_input()
    vi["observations"][0]["source_ref"] = "s1"
    _assert_rejected(_run(vi), ischema.ERR_SCHEMA)


def test_invalid_observation_id_rejected():
    for bad in ("", "   ", 123, None):
        vi = _valid_input()
        vi["observations"][0]["observation_id"] = bad
        _assert_rejected(_run(vi), ischema.ERR_SCHEMA)


def test_observation_missing_field_rejected():
    for missing in ("value", "unit", "observed_at", "location"):
        vi = _valid_input()
        del vi["observations"][0][missing]
        _assert_rejected(_run(vi), ischema.ERR_SCHEMA)


def test_association_missing_field_rejected():
    for missing in ("observation_ref", "asset_id", "relation"):
        vi = _valid_input()
        del vi["asset_reference_map"][0][missing]
        _assert_rejected(_run(vi), ischema.ERR_SCHEMA)


def test_bad_validated_input_rejected():
    # not a dict
    for bad in (None, "x", 123, ["a"]):
        assert_out = ObservationAssetExtractNode().execute({"validated_input": bad, "correlation_id": "c1"})
        _assert_rejected(assert_out, ischema.ERR_SCHEMA)
    # missing observations array
    vi = _valid_input(); del vi["observations"]
    _assert_rejected(_run(vi), ischema.ERR_SCHEMA)
    # observations present but empty
    vi = _valid_input(); vi["observations"] = []
    _assert_rejected(_run(vi), ischema.ERR_SCHEMA)
    # observations wrong type
    vi = _valid_input(); vi["observations"] = {"obs-1": {}}
    _assert_rejected(_run(vi), ischema.ERR_SCHEMA)
    # asset_reference_map missing / wrong type
    vi = _valid_input(); del vi["asset_reference_map"]
    _assert_rejected(_run(vi), ischema.ERR_SCHEMA)
    vi = _valid_input(); vi["asset_reference_map"] = "nope"
    _assert_rejected(_run(vi), ischema.ERR_SCHEMA)


def test_same_observation_multiple_assets_yield_uniquely_resolvable_citations():
    # One observation locationally associated with several distinct assets: each association MUST
    # get its own citation that resolves 1:1 to that specific association (not collapse to a shared
    # observation_ref). All share the referenced observation's source_ref (inherited, not minted).
    vi = _valid_input()
    vi["asset_reference_map"] = [
        {"observation_ref": "obs-1", "asset_id": "asset-X", "relation": "locational"},
        {"observation_ref": "obs-1", "asset_id": "asset-Y", "relation": "locational"},
    ]
    out = _run(vi)
    assert out["status"] == AgentStatus.SUCCESS.value

    assoc_citations = [c for c in out["citations"] if c["subject_type"] == "asset_association"]
    # one citation per association — not deduplicated down to a single shared observation_ref
    assert len(assoc_citations) == 2
    subject_refs = [(c["subject_ref"]["observation_ref"], c["subject_ref"]["asset_id"]) for c in assoc_citations]
    assert set(subject_refs) == {("obs-1", "asset-X"), ("obs-1", "asset-Y")}
    assert len(set(subject_refs)) == 2  # each association's citation is uniquely identifiable
    # both inherit obs-1's source_ref
    for c in assoc_citations:
        assert c["source_ref"]["source_id"] == "s1"


def test_empty_asset_reference_map_is_valid_no_associations():
    vi = _valid_input()
    vi["asset_reference_map"] = []
    out = _run(vi)
    assert out["status"] == AgentStatus.SUCCESS.value
    assert out["asset_associations"] == []
    # citations still cover every observation
    assert len(out["citations"]) == len(out["observations"])
    assert all(c["subject_type"] == "observation" for c in out["citations"])


# --- 5. no estimation / leak / attribution field is ever emitted ------------------------------
def test_output_contains_no_leak_or_attribution_fields():
    out = _run(_valid_input())
    # top-level owned delta is bounded
    assert set(out.keys()) == _ALLOWED_KEYS
    # no forbidden marker anywhere in the emitted structure
    blob = json.dumps(out)
    for banned in _FORBIDDEN_FIELDS:
        assert banned not in blob, f"forbidden field {banned!r} leaked into output"
    # associations expose ONLY the four documented keys (no smuggled attribution field)
    for assoc in out["asset_associations"]:
        assert set(assoc.keys()) == {"observation_ref", "asset_id", "relation", "source_ref"}
    for cit in out["citations"]:
        assert set(cit.keys()) == {"subject_type", "subject_ref", "source_ref"}


# --- 6. exactly one domain audit event on both success and reject -----------------------------
def test_success_emits_exactly_one_domain_event(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda ev, payload, state: events.append((ev, payload)))
    out = _run(_valid_input())
    assert out["status"] == AgentStatus.SUCCESS.value
    assert len(events) == 1
    assert events[0][0] == "observation_extract"


def test_reject_emits_exactly_one_domain_event_and_leaks_nothing(monkeypatch):
    events = []
    monkeypatch.setattr(node_mod, "emit_trace_event", lambda ev, payload, state: events.append((ev, payload)))
    vi = _valid_input()
    vi["observations"][0]["source_ref"]["approval"]["approval_ref"] = "SENTINEL_APPROVAL_9f3a"
    vi["observations"][0]["location"] = "SENTINEL_LOCATION_zz"
    vi["asset_reference_map"][0]["relation"] = "emission_source"  # → ERR_NONLOCATIONAL_RELATION
    out = ObservationAssetExtractNode().execute({"validated_input": vi, "correlation_id": "c1"})
    assert out["error_log"] == [ischema.ERR_NONLOCATIONAL_RELATION]
    assert len(events) == 1
    # neither the reject delta nor the audit payload echoes raw values / approval / location
    blob = json.dumps(out) + json.dumps(events, default=str)
    assert "SENTINEL_APPROVAL_9f3a" not in blob
    assert "SENTINEL_LOCATION_zz" not in blob


# --- 7. returned keys are bounded to the four owned fields ------------------------------------
def test_returned_keys_are_bounded_on_success():
    out = _run(_valid_input())
    assert set(out.keys()) == _ALLOWED_KEYS


def test_returned_keys_are_bounded_on_reject():
    vi = _valid_input()
    vi["asset_reference_map"][0]["relation"] = "causal"
    out = _run(vi)
    assert set(out.keys()) == {"status", "error_log"}


# --- S-1 trust: inner node is ANONYMOUS (enforced at the outer boundary) ----------------------
def test_required_trust_level_is_anonymous():
    assert ObservationAssetExtractNode.required_trust_level is TrustLevel.ANONYMOUS


def test_node_is_constructible_with_no_args():
    # PB-6 instantiates every node via node_cls() — must not require constructor args.
    assert ObservationAssetExtractNode() is not None


def test_call_path_reaches_execute_and_returns_owned_delta():
    # Exercise the REAL BaseNode.__call__ boundary (S-1 gate → execute), not execute() directly.
    # The inner node is ANONYMOUS, so an ANONYMOUS caller is admitted (no refusal to prove here);
    # this asserts the owned domain fields flow out through __call__. (Framework __call__ may add
    # its own node_history / execution_time — assert a subset, not exact equality.)
    node = ObservationAssetExtractNode()
    out = node({"validated_input": _valid_input(), "caller_trust_level": TrustLevel.ANONYMOUS.value,
                "correlation_id": "c1", "node_history": [], "error_log": []})
    assert out["status"] == AgentStatus.SUCCESS.value
    assert _ALLOWED_KEYS <= set(out.keys())
    assert [o["observation_id"] for o in out["observations"]] == ["obs-1", "obs-2"]
