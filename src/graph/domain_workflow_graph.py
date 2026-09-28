"""AgentCore Platform v1.0 — inner evidence workflow graph for ENE-C2-086 (Cat 2).

The inner `BaseGraph` wrapped by `EvidenceWorkflowGraphNode` (the outer `main` slot). It runs the
linear domain pipeline over the canonical `validated_input` handed in as a JSON string:

    START → input_hydrate → observation_asset_extract → limit_gap_analysis → cited_brief_assemble → END

Any inner node that returns `status: error` short-circuits to END (via a conditional edge) so the
inner graph produces NO partial output; the outer `GraphNode(error_strategy="propagate")` then
raises `SubgraphError` from that error status and the outer run ends fail-closed (post_process is
skipped, caller output is empty). `get_output()` surfaces ONLY the terminal `result` (the cited
brief) plus framework metadata — never inner working State (validated_input / observations /
asset_associations / method_notes / coverage_gaps / citations / context_brief).
"""

from typing import Any

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_status import AgentStatus

from src.nodes.cited_brief_assemble_node import CitedBriefAssembleNode
from src.nodes.input_hydrate_node import InputHydrateNode
from src.nodes.limit_gap_analysis_node import LimitGapAnalysisNode
from src.nodes.observation_asset_extract_node import ObservationAssetExtractNode
from src.schemas.state import EvidenceWorkflowState


class EvidenceWorkflowGraph(BaseGraph):
    """Inner Cat-2 domain workflow (linear, fail-closed short-circuit on any node error)."""

    @property
    def name(self) -> str:
        return "evidence_workflow"

    @property
    def state_schema(self) -> type:
        return EvidenceWorkflowState

    def _validate_config(self) -> None:
        # No mandatory config: the v1 core path is deterministic and LLM-free.
        return None

    def register_nodes(self) -> None:
        # No super() call — BaseGraph.register_nodes() is abstract; do NOT register
        # initialize/finalize here (those are the outer backbone's concern).
        self._nodes["input_hydrate"] = InputHydrateNode()
        self._nodes["observation_asset_extract"] = ObservationAssetExtractNode()
        self._nodes["limit_gap_analysis"] = LimitGapAnalysisNode()
        self._nodes["cited_brief_assemble"] = CitedBriefAssembleNode()

    def add_edges(self) -> None:
        # Each hop is conditional: a node returning status:error routes to END (no partial output),
        # otherwise it advances to the next inner node.
        self._sg.add_edge(START, "input_hydrate")
        self._sg.add_conditional_edges(
            "input_hydrate",
            self._continue_or_end,
            {"continue": "observation_asset_extract", "end": END},
        )
        self._sg.add_conditional_edges(
            "observation_asset_extract",
            self._continue_or_end,
            {"continue": "limit_gap_analysis", "end": END},
        )
        self._sg.add_conditional_edges(
            "limit_gap_analysis",
            self._continue_or_end,
            {"continue": "cited_brief_assemble", "end": END},
        )
        self._sg.add_edge("cited_brief_assemble", END)

    def _continue_or_end(self, state: dict[str, Any]) -> str:
        """END on any node error; otherwise advance to the next inner node."""
        return "end" if state.get("status") == AgentStatus.ERROR.value else "continue"

    def route(self, state: dict[str, Any]) -> str:
        # Required by the BaseGraph ABC; the per-hop edges use _continue_or_end().
        return self._continue_or_end(state)

    def get_output(self, state: dict[str, Any]) -> dict[str, Any]:
        # Minimal, allowlisted surface: the terminal cited brief (result) + framework metadata only.
        # No inner working State (validated_input / observations / asset_associations /
        # methodology_limitations / coverage_gaps / citations / context_brief) is projected outward.
        return {
            "output": state.get("result"),
            "status": state.get("status"),
            "error_log": state.get("error_log", []),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
