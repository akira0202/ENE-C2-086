# API entry-point regression: src/api/server.py must resolve against the current graph entry-point.
#
# graph composition removed the scaffold `Graph` class; server.py used to import + instantiate it,
# which would fail the deploy-stg server import. These tests pin the fixed contract:
#   * the graph module exposes build_agent() and no longer exposes Graph (CI-runnable, no fastapi);
#   * the FastAPI app imports, /health is ok, and /invoke drives the compiled agent end-to-end
#     (needs fastapi + the real framework runtime; importorskip skips it where absent — fastapi is
#     not a run-tests dependency, so this runs locally / in the STG image, not in bare run-tests).

import json

import pytest

_SUCCESS = "success"
_ERROR = "error"


def _src(sid):
    return {"source_id": sid, "locator": "p1",
            "approval": {"attested_by": "env-owner", "attested_at": "2026-01-01", "approval_ref": "a1"}}


def _payload():
    return json.dumps({
        "observations": [{"observation_id": "obs-1", "value": 1.2, "unit": "ppb",
                          "observed_at": "2026-01-01T00:00:00Z", "location": "sector-A", "source_ref": _src("s1")}],
        "asset_reference_map": [{"observation_ref": "obs-1", "asset_id": "asset-X", "relation": "locational"}],
        "method_notes": [{"text": "coverage limited to sector A", "source_ref": _src("s2")}],
        "reporting_template": {"sections": ["summary", "limitations"]},
    })


# --- CI-runnable: the entry-point server.py imports must exist (no fastapi needed) -------------
def test_graph_module_exposes_build_agent_not_scaffold_graph():
    from src.graph import graph as graph_mod
    assert hasattr(graph_mod, "build_agent"), "src.graph.graph.build_agent (the server entry-point) must exist"
    assert not hasattr(graph_mod, "Graph"), "the scaffold Graph class must be gone — server.py imports build_agent"


# --- full FastAPI app (fastapi + real framework runtime; skipped where absent) ----------------
def _client():
    pytest.importorskip("fastapi")
    pytest.importorskip("framework.schemas.invocation_context")
    from fastapi.testclient import TestClient
    from src.api import server
    return TestClient(server.app)


def test_health_ok():
    client = _client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_invoke_verified_caller_returns_brief(monkeypatch):
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", "stg-token")
    client = _client()
    resp = client.post("/invoke", json={"input": _payload()},
                       headers={"authorization": "Bearer stg-token"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == _SUCCESS, body
    brief = body.get("output") or body.get("formatted_output") or body.get("result")
    assert isinstance(brief, dict) and brief.get("statements"), body


def test_invoke_bad_token_is_401(monkeypatch):
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", "stg-token")
    client = _client()
    resp = client.post("/invoke", json={"input": _payload()}, headers={"authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_invoke_anonymous_no_token_refused_no_output(monkeypatch):
    monkeypatch.delenv("INVOKE_AUTH_TOKEN", raising=False)
    client = _client()
    resp = client.post("/invoke", json={"input": _payload()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # no entry-point token + ANONYMOUS caller → S-1 refuses at SourceIntakeNode → no caller output
    assert body.get("status") == _ERROR, body
    assert body.get("output") is None and body.get("result") is None and body.get("formatted_output") is None, body
