"""AgentCore Platform v1.0 — outer graph for ENE-C2-086 (Cat 2, L1-direct AgentBaseGraph).

Backbone is the fixed framework pipeline (add_edges NOT overridden):

    START → initialize → pre_process → main → {route} → post_process → finalize → END

- pre_process  = SourceIntakeNode        (untrusted-input boundary; VERIFIED_EXTERNAL)
- main         = EvidenceWorkflowGraphNode (wraps the inner EvidenceWorkflowGraph)
- post_process = OutputGateNode           (terminal S-3 gate)

The inner domain workflow is hidden inside `main` via a GraphNode. On inner success the framework
route() sends `main → post_process` (the terminal S-3 gate publishes `formatted_output`); on inner
error the GraphNode (error_strategy="propagate") raises SubgraphError, `main` returns status:error,
route() sends it straight to `finalize` (post_process skipped) and the caller output is empty — no
partial brief. `merge_output()` maps ONLY the terminal `result`/`status` outward; inner working
State never crosses the boundary.

A request the caller can correct is degraded at pre_process (SUCCESS + `error_code`, no
validated_input): `main` skips the inner workflow and post_process returns the fixed notice for the
code — see src/services/degradation.py.
"""

import json
from typing import Any, ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.graph.domain_workflow_graph import EvidenceWorkflowGraph
from src.nodes.output_gate_node import OutputGateNode
from src.nodes.source_intake_node import SourceIntakeNode
from src.schemas.state import State
from src.services.progress import emit_progress


class EvidenceWorkflowGraphNode(GraphNode):
    """`main` slot — runs the inner EvidenceWorkflowGraph as an in-process subgraph."""

    # Outer-boundary node (docs/02 §Security): a verified external caller.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    # Inner error → SubgraphError → outer finalize (no partial output).
    error_strategy: ClassVar[str] = "propagate"

    def __init__(self, node_config: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._config = node_config or {}

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # A degraded request (pre_process set `error_code`) carries no validated_input, so there is
        # nothing to extract: running the inner workflow on it would only re-reject the empty input
        # as an error. Skip it and let post_process return the notice for the code.
        if state.get("error_code"):
            emit_trace_event(
                "evidence_workflow_skipped",
                {"correlation_id": state.get("correlation_id"), "error_code": state.get("error_code")},
                state,
            )
            return {"status": AgentStatus.SUCCESS.value}
        # Bound to the declared return type rather than handing the caller the framework's
        # untyped result straight through.
        merged: dict[str, Any] = super().execute(state)
        return merged

    def get_subgraph(self) -> EvidenceWorkflowGraph:
        return EvidenceWorkflowGraph(config=self._config)

    def extract_input(self, state: dict[str, Any]) -> str:
        # Hand the canonical validated_input to the inner graph as a JSON string (deterministic:
        # sorted keys, ascii). The inner InputHydrateNode parses + re-validates it.
        emit_progress("Assembling the observation context...")
        return json.dumps(state.get("validated_input", {}), ensure_ascii=True, sort_keys=True)

    def merge_output(self, state: dict[str, Any], sub_result: dict[str, Any]) -> dict[str, Any]:
        # Explicit boundary mapping ONLY — the terminal cited brief (result) + status. No inner
        # working field (observations / asset_associations / methodology_limitations /
        # coverage_gaps / citations / context_brief / validated_input) is passed through.
        return {
            "result": sub_result.get("output"),
            "status": sub_result.get("status"),
        }


class EnergyMethaneObservationContextBriefGraph(AgentBaseGraph):
    """Outer Cat-2 backbone. Domain complexity lives in the `main` GraphNode; add_edges() is not
    overridden (the framework wires the fixed backbone)."""

    @property
    def name(self) -> str:
        return "EnergyMethaneObservationContextBriefGenerator"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize (required first)
        self._nodes["pre_process"] = SourceIntakeNode()
        self._nodes["main"] = EvidenceWorkflowGraphNode(node_config=self.config)
        self._nodes["post_process"] = OutputGateNode()

    # add_edges() is NOT overridden — the framework owns the backbone wiring.


def build_agent(config: dict[str, Any] | None = None) -> EnergyMethaneObservationContextBriefGraph:
    """Construct the agent graph. v1 needs no runtime config (deterministic, LLM-free core path)."""
    return EnergyMethaneObservationContextBriefGraph(config=config or {})
