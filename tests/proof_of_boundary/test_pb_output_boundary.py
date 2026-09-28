# PB: output boundary at the OUTER agent.invoke() caller edge (real framework / CI).
#
# Complements the input/extraction boundary PB with the OUTPUT artifact contract:
#   * the shipped STG payload (deploy/invoke_payload.json) drives the deterministic path to a cited
#     brief — every source-derived statement carries a source_ref citation; a coverage gap (when
#     present) carries a structural basis, never a source_ref;
#   * a released brief contains no prohibited operational / attribution / estimation marker;
#   * when the terminal S-3 withholds the brief (scope category or PII), the run completes with the
#     fixed notice for the code and the withheld brief body appears in NEITHER the caller response
#     tree NOR any audit event payload — only a non-sensitive code / category slug is recorded.
# Needs the real framework runtime; importorskip skips it where absent.

import json
import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
_SUCCESS = "success"
_ERROR = "error"
_INNER_FIELDS = ("validated_input", "observations", "asset_associations", "citations", "context_brief")
_FORBIDDEN_OUTPUT = ("emission_source", "leak_detected", "estimated_emission", "estimated_emissions",
                     "regulatory_breach", "recommended_action", "emission_estimate")
# every node module whose emit_trace_event we spy, to prove no audit event carries blocked content
_NODE_MODULES = (
    "src.nodes.source_intake_node", "src.nodes.input_hydrate_node",
    "src.nodes.observation_asset_extract_node", "src.nodes.limit_gap_analysis_node",
    "src.nodes.cited_brief_assemble_node", "src.nodes.output_gate_node",
)


def _agent_ctx(trust="VERIFIED_EXTERNAL"):
    pytest.importorskip("framework.schemas.invocation_context")
    pytest.importorskip("langgraph.graph")
    from framework.schemas.invocation_context import InvocationContext
    from framework.schemas.trust_level import TrustLevel
    from src.graph import build_agent
    return build_agent(), InvocationContext(session_id="pb-out", caller_trust_level=getattr(TrustLevel, trust))


def _invoke(input_str, trust="VERIFIED_EXTERNAL"):
    agent, ctx = _agent_ctx(trust)
    return agent.invoke(input_str, ctx=ctx)


def _brief(out):
    for k in ("output", "formatted_output", "result"):
        if isinstance(out.get(k), dict):
            return out[k]
    return None


def _src(sid, ref):
    return {"source_id": sid, "locator": "s", "approval": {"attested_by": "office", "attested_at": "t", "approval_ref": ref}}


def _envelope(note_text="coverage limited to the surveyed cells", observations=None):
    if observations is None:
        observations = [
            {"observation_id": "o1", "value": 1.1, "unit": "ppb", "observed_at": "t1", "location": "grid-n", "source_ref": _src("s1", "r1")},
            {"observation_id": "o2", "value": 2.2, "unit": "ppb", "observed_at": "t2", "location": "grid-s", "source_ref": _src("s2", "r2")},
        ]
    return json.dumps({
        "observations": observations,
        "asset_reference_map": [{"observation_ref": "o1", "asset_id": "asset-A", "relation": "locational"}],
        "method_notes": [{"text": note_text, "source_ref": _src("s3", "r3")}],
        "reporting_template": {"sections": ["summary", "limitations"]},
    })


# --- the shipped STG payload drives the deterministic path to a cited brief --------------------
def test_stg_payload_produces_success_brief_with_citations():
    payload = json.loads((_REPO / "deploy" / "invoke_payload.json").read_text())
    assert isinstance(payload.get("input"), str) and payload["input"].strip()  # serialized JSON string
    json.loads(payload["input"])  # input must itself be valid JSON (the template envelope)
    out = _invoke(payload["input"])
    assert out.get("status") == _SUCCESS, out
    brief = _brief(out)
    assert isinstance(brief, dict) and brief.get("statements"), out
    for st in brief["statements"]:
        if st["kind"] == "coverage_gap":
            assert "source_ref" not in st and isinstance(st["basis"], dict)
        else:  # observation / asset_association / methodology_limitation are source-cited
            assert set(st["source_ref"].keys()) == {"source_id", "locator", "approval"}
    blob = json.dumps(brief)
    for banned in _FORBIDDEN_OUTPUT:
        assert banned not in blob, banned
    assert not (set(_INNER_FIELDS) & _all_string_keys(out)), out


def test_single_location_payload_yields_gap_with_structural_basis_only():
    obs = [
        {"observation_id": "o1", "value": 1.1, "unit": "ppb", "observed_at": "t1", "location": "grid-n", "source_ref": _src("s1", "r1")},
        {"observation_id": "o2", "value": 2.2, "unit": "ppb", "observed_at": "t2", "location": "grid-n", "source_ref": _src("s2", "r2")},
    ]
    out = _invoke(_envelope(observations=obs))
    assert out.get("status") == _SUCCESS, out
    gaps = [s for s in _brief(out)["statements"] if s["kind"] == "coverage_gap"]
    assert gaps
    for g in gaps:
        assert "source_ref" not in g and isinstance(g["basis"], dict)


# --- S-3 block: blocked body absent from response tree AND every audit event payload -----------
def _all_string_keys(obj):
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                keys.add(k)
            keys |= _all_string_keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            keys |= _all_string_keys(v)
    return keys


@pytest.mark.parametrize("note_text,detect_pii_flags,code", [
    ("emissions likely originate from asset-BLKSENTINEL_zz", False, "BRIEF_WITHHELD"),  # hedged attribution
    ("routine note BLKSENTINEL_zz", True, "PERSONAL_DATA_WITHHELD"),  # PII (substrate flags the sentinel)
])
def test_s3_block_leaves_no_blocked_body_in_response_or_audit(monkeypatch, note_text, detect_pii_flags, code):
    pytest.importorskip("framework.schemas.invocation_context")
    import importlib
    captured = []
    for mod_name in _NODE_MODULES:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "emit_trace_event",
                            lambda ev, payload, state, _c=captured: _c.append((ev, payload)))
    if detect_pii_flags:
        from src.nodes import output_gate_node as gate_mod
        monkeypatch.setattr(gate_mod, "detect_pii", lambda v: ["pii"] if "BLKSENTINEL_zz" in v else [])

    out = _invoke(_envelope(note_text=note_text))
    # withheld: the output is the fixed notice, nothing of the brief
    from src.services.degradation import explain_degradation

    assert out.get("status") == _SUCCESS, out
    assert out.get("output") == explain_degradation(code), out
    assert ("output_gate_withheld", code) in [(ev, pl.get("error_code")) for ev, pl in captured], captured
    # blocked body appears in NEITHER the response tree NOR any audit event payload
    response_blob = json.dumps(out)
    audit_blob = json.dumps(captured, default=str)
    assert "BLKSENTINEL_zz" not in response_blob, out
    assert "BLKSENTINEL_zz" not in audit_blob, captured
    # no inner-State key leaks into the response at any depth
    assert not (set(_INNER_FIELDS) & _all_string_keys(out)), out
