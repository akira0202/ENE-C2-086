# ENE-C2-086 — Cat-2 compiled-graph invoke() E2E (real framework / CI; skips off-runtime).
#
# Drives the OUTER agent.invoke() caller boundary end-to-end and proves the docs/02 contracts:
#   * valid + VERIFIED_EXTERNAL           → status:success, a cited-brief packet is published
#   * ANONYMOUS caller                    → outer S-1 refuses before execute(); no caller output
#   * inner node error (fault-injected)   → SubgraphError → outer finalize (post_process skipped);
#                                           no partial / caller-facing output, no inner-State leak
#   * S-3 prohibited phrasing in the brief → terminal gate blocks; no caller output
#
# The compiled-graph invoke() path needs the real framework runtime (langgraph + InvocationContext);
# `importorskip` skips these cleanly where that runtime is absent. The template is deterministic and
# secret-free, so no secrets provisioning is required.

import json

import pytest

_SUCCESS = "success"
_ERROR = "error"


def _src(sid):
    return {"source_id": sid, "locator": "p1",
            "approval": {"attested_by": "env-owner", "attested_at": "2026-01-01", "approval_ref": "a1"}}


def _payload(note_text="coverage limited to sectors A/B"):
    return {
        "observations": [
            {"observation_id": "obs-1", "value": 1.2, "unit": "ppb",
             "observed_at": "2026-01-01T00:00:00Z", "location": "sector-A", "source_ref": _src("s1")},
            {"observation_id": "obs-2", "value": 3.4, "unit": "ppb",
             "observed_at": "2026-01-02T00:00:00Z", "location": "sector-B", "source_ref": _src("s2")},
        ],
        "asset_reference_map": [{"observation_ref": "obs-1", "asset_id": "asset-X", "relation": "locational"}],
        "method_notes": [{"text": note_text, "source_ref": _src("s3")}],
        "reporting_template": {"sections": ["summary", "limitations"]},
    }


def _agent_and_ctx(trust_name):
    pytest.importorskip("framework.schemas.invocation_context")
    pytest.importorskip("langgraph.graph")
    from framework.schemas.invocation_context import InvocationContext
    from framework.schemas.trust_level import TrustLevel
    from src.graph import build_agent

    agent = build_agent()
    ctx = InvocationContext(session_id="e2e", caller_trust_level=getattr(TrustLevel, trust_name))
    return agent, ctx


def _packet_of(out: dict):
    for key in ("output", "formatted_output", "result"):
        val = out.get(key)
        if isinstance(val, dict):
            return val
    return None


def test_invoke_valid_reaches_success_brief():
    agent, ctx = _agent_and_ctx("VERIFIED_EXTERNAL")
    out = agent.invoke(json.dumps(_payload()), ctx=ctx)
    assert isinstance(out, dict) and out.get("status") == _SUCCESS, out
    packet = _packet_of(out)
    assert isinstance(packet, dict) and packet.get("statements"), out
    kinds = {s["kind"] for s in packet["statements"]}
    assert {"observation", "asset_association", "methodology_limitation"} <= kinds, kinds
    # locational-only phrasing survives the terminal S-3 gate
    assert any("locationally associated with asset" in s.get("statement", "")
               for s in packet["statements"] if s["kind"] == "asset_association")


def test_invoke_anonymous_caller_produces_no_output():
    agent, ctx = _agent_and_ctx("ANONYMOUS")
    out = agent.invoke(json.dumps(_payload()), ctx=ctx)
    # outer S-1 refuses the ANONYMOUS caller before execute() → no caller-facing output
    assert out.get("status") == _ERROR, out
    assert out.get("output") is None, out
    assert out.get("result") is None and out.get("formatted_output") is None, out


def test_invoke_inner_error_yields_no_caller_output(monkeypatch):
    # Fault-inject an inner-node error and prove it propagates through the OUTER agent.invoke()
    # with no partial output and no inner-State leak (docs/02: inner error → SubgraphError →
    # outer finalize, post_process skipped).
    pytest.importorskip("framework.schemas.invocation_context")
    from framework.errors import SubgraphError
    from src.nodes import observation_asset_extract_node as extract_mod
    from src.nodes import output_gate_node as gate_mod

    monkeypatch.setattr(extract_mod.ObservationAssetExtractNode, "execute",
                        lambda self, state: {"status": _ERROR, "error_log": ["injected inner error"]})
    post_ran = {"hit": False}
    real_gate = gate_mod.OutputGateNode.execute
    monkeypatch.setattr(gate_mod.OutputGateNode, "execute",
                        lambda self, state, _r=post_ran, _o=real_gate: (_r.__setitem__("hit", True) or _o(self, state)))

    agent, ctx = _agent_and_ctx("VERIFIED_EXTERNAL")
    out = None
    raised = None
    try:
        out = agent.invoke(json.dumps(_payload()), ctx=ctx)
    except SubgraphError as exc:
        raised = exc

    assert post_ran["hit"] is False, "post_process (terminal S-3) must not run on an inner error"
    assert (raised is not None) ^ (out is not None), (raised, out)
    if out is not None:
        assert out.get("status") == _ERROR, out
        assert out.get("output") is None, out
        assert out.get("result") is None and out.get("formatted_output") is None, out
        for leaked in ("validated_input", "observations", "context_brief", "citations"):
            assert out.get(leaked) is None, (leaked, out)


def test_invoke_s3_block_on_prohibited_phrasing_yields_no_output():
    # a supplied method note carrying hedged attribution reaches the assembled brief; the terminal
    # S-3 gate withholds the whole brief → the run completes with the fixed notice and nothing of
    # the brief.
    from src.services.degradation import BRIEF_WITHHELD, explain_degradation

    agent, ctx = _agent_and_ctx("VERIFIED_EXTERNAL")
    out = agent.invoke(json.dumps(_payload(note_text="emissions likely originate from asset-X")), ctx=ctx)
    assert out.get("status") == _SUCCESS, out
    assert out.get("output") == explain_degradation(BRIEF_WITHHELD), out
    assert "asset-X" not in json.dumps(out), out
