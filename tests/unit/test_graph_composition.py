# ENE-C2-086 — Cat-2 graph composition / wiring tests (docs/02 Architecture + Data Flow).
#
# Verifies the WIRING deterministically (runs locally under the framework stub AND in CI against the
# real wheel): outer slot registration + fixed backbone, inner node order, the GraphNode handoff
# (extract_input / merge_output) with NO inner-working-State leak, the inner get_output allowlist,
# the error short-circuit predicate, PB-6 constructibility, and that both graphs compile. The full
# compiled-graph invoke() E2E lives in tests/integration/test_graph_invoke_e2e.py.

import json
import pathlib

from framework.schemas.trust_level import TrustLevel
from src.graph import EnergyMethaneObservationContextBriefGraph  # manifest entry-point (docs/02 §Manifest)
from src.graph.domain_workflow_graph import EvidenceWorkflowGraph
from src.graph.graph import EvidenceWorkflowGraphNode, build_agent
from src.nodes.cited_brief_assemble_node import CitedBriefAssembleNode
from src.nodes.input_hydrate_node import InputHydrateNode
from src.nodes.limit_gap_analysis_node import LimitGapAnalysisNode
from src.nodes.observation_asset_extract_node import ObservationAssetExtractNode
from src.nodes.output_gate_node import OutputGateNode
from src.nodes.source_intake_node import SourceIntakeNode

# Inner working fields that MUST NOT cross the inner→outer boundary.
_INNER_WORKING = {
    "validated_input", "observations", "asset_associations", "citations",
    "methodology_limitations", "coverage_gaps", "context_brief", "method_notes",
}


# ── outer backbone wiring ────────────────────────────────────────────────────
def test_outer_registers_three_slots_plus_backbone():
    graph = EnergyMethaneObservationContextBriefGraph(config={})
    graph.register_nodes()
    assert "initialize" in graph._nodes and "finalize" in graph._nodes  # super() first
    assert isinstance(graph._nodes["pre_process"], SourceIntakeNode)
    assert isinstance(graph._nodes["main"], EvidenceWorkflowGraphNode)
    assert isinstance(graph._nodes["post_process"], OutputGateNode)


def test_outer_does_not_override_add_edges():
    # the fixed backbone belongs to the framework — templates must not override add_edges()
    assert "add_edges" not in EnergyMethaneObservationContextBriefGraph.__dict__


def test_name_and_state_schema():
    from src.schemas.state import State
    graph = EnergyMethaneObservationContextBriefGraph(config={})
    assert graph.name == "EnergyMethaneObservationContextBriefGenerator"
    assert graph.state_schema is State


def test_main_graphnode_is_verified_external():
    assert EvidenceWorkflowGraphNode.required_trust_level is TrustLevel.VERIFIED_EXTERNAL


# ── inner workflow wiring ────────────────────────────────────────────────────
def test_inner_registers_four_nodes_in_order():
    inner = EvidenceWorkflowGraph(config={})
    inner.register_nodes()
    assert isinstance(inner._nodes["input_hydrate"], InputHydrateNode)
    assert isinstance(inner._nodes["observation_asset_extract"], ObservationAssetExtractNode)
    assert isinstance(inner._nodes["limit_gap_analysis"], LimitGapAnalysisNode)
    assert isinstance(inner._nodes["cited_brief_assemble"], CitedBriefAssembleNode)


def test_inner_error_short_circuits_else_continues():
    from framework.schemas.agent_status import AgentStatus
    inner = EvidenceWorkflowGraph(config={})
    assert inner._continue_or_end({"status": AgentStatus.ERROR.value}) == "end"
    assert inner._continue_or_end({"status": AgentStatus.SUCCESS.value}) == "continue"
    assert inner._continue_or_end({}) == "continue"


def test_inner_get_output_is_allowlisted_and_leaks_no_working_state():
    inner = EvidenceWorkflowGraph(config={})
    state = {
        "result": {"statements": []}, "status": "success", "error_log": [],
        "trace_id": "t", "correlation_id": "c", "node_history": ["x"],
        # inner working fields that must NOT be surfaced:
        "validated_input": {"secret": 1}, "observations": [1], "asset_associations": [1],
        "citations": [1], "methodology_limitations": [1], "coverage_gaps": [1],
        "context_brief": {"x": 1}, "method_notes": [1],
    }
    out = inner.get_output(state)
    assert out["output"] == {"statements": []}
    assert out["status"] == "success"
    assert _INNER_WORKING.isdisjoint(out.keys()), out.keys()


# ── GraphNode handoff ────────────────────────────────────────────────────────
def test_extract_input_serialises_validated_input_to_json_string():
    node = EvidenceWorkflowGraphNode()
    vi = {"observations": [{"observation_id": "obs-1"}], "reporting_template": {}}
    handoff = node.extract_input({"validated_input": vi})
    assert isinstance(handoff, str) and json.loads(handoff) == vi  # round-trips


def test_merge_output_maps_only_result_and_status_no_leak():
    node = EvidenceWorkflowGraphNode()
    sub = {
        "output": {"statements": ["brief"]}, "status": "success",
        # extra inner fields the GraphNode must NOT pass through:
        "observations": [1], "citations": [1], "context_brief": {"x": 1}, "validated_input": {"y": 1},
    }
    merged = node.merge_output({}, sub)
    assert merged == {"result": {"statements": ["brief"]}, "status": "success"}
    assert _INNER_WORKING.isdisjoint(merged.keys())


def test_graphnode_error_strategy_is_propagate():
    assert EvidenceWorkflowGraphNode.error_strategy == "propagate"


# ── PB-6 constructibility ────────────────────────────────────────────────────
def test_graphnode_constructible_with_no_args():
    assert EvidenceWorkflowGraphNode() is not None


# ── compile (locally: framework stub; in CI: real StateGraph build) ──────────
def test_outer_graph_compiles():
    # in CI this builds the real backbone StateGraph — a missing slot (MissingNodeError)
    # or a bad edge would raise here; it must not.
    build_agent().compile()


def test_inner_graph_compiles():
    EvidenceWorkflowGraph(config={}).compile()


# ── manifest entry-point resolves (docs/02 §Manifest verification command) ───
def test_manifest_module_and_class_resolve():
    import importlib
    import re
    text = (pathlib.Path(__file__).resolve().parents[2] / "config" / "agent.yaml").read_text()
    # Root-level schema: a SINGLE dotted class: path (module.Class), no module:/class: split.
    assert not re.search(r'^\s*module:', text, re.MULTILINE), \
        "manifest must use a single dotted class:, not module:/class:"
    dotted = re.search(r'^class:\s*"([^"]+)"', text, re.MULTILINE).group(1)
    module, class_name = dotted.rsplit(".", 1)
    resolved = getattr(importlib.import_module(module), class_name)
    assert resolved is EnergyMethaneObservationContextBriefGraph
