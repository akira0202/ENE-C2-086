"""AgentCore Platform v1.0 — CitedBriefAssembleNode for ENE-C2-086 (inner evidence workflow).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state}).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Constructible with no arguments (PB-6 instantiates every node via node_cls()).
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — inner `cited_brief_assemble` row):
 - Deterministically assembles the cited context brief from the ALREADY-EXTRACTED, canonical
   evidence in State (observations, asset_associations, methodology_limitations, coverage_gaps) plus
   the supplied `reporting_template` (read from the canonical `validated_input`, never a raw
   re-parse). Every source-derived statement (observation / locational association / methodology
   limitation) resolves to EXACTLY ONE supplied `source_ref`; a coverage gap carries a structural
   basis and no source_ref. On a missing / duplicate / inconsistent citation the whole run fails
   closed (`ERR_SOURCE_CITATION_MISMATCH`) with NO partial brief.
 - Emits ONLY `context_brief`, `result`, `status` (owned delta). `result` is the SAME cited brief as
   `context_brief`. This node writes no `formatted_output` (the terminal S-3 gate in the outer
   post_process owns that) and no other domain field.
 - Assembly is deterministic and read-only: it quotes / structures supplied data with fixed safe
   templates — no LLM free-text, no arithmetic on observation values (diff / average / interpolation
   / extrapolation / unit conversion / emission estimation), no leak identification, and no asset
   attribution. The terminal S-3 gate is the separate final defence line; this node MUST NOT rely on
   it to sanitise an unsafe brief.

S-1: inner node — `required_trust_level = ANONYMOUS` (S-1 enforced at the outer VERIFIED_EXTERNAL
boundary; declared explicitly rather than inherited).
S-4: exactly one domain `emit_trace_event()` per execute() on the success and reject path; payload
carries only counts / a non-sensitive code — never statement text, values, locations, or source detail.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.brief_assembler import assemble_brief
from src.services.input_schema import InputContractError
from src.services.failure_message import explain
from src.services.progress import emit_progress


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class CitedBriefAssembleNode(FunctionNode):
    """Inner evidence-workflow node — deterministically assemble the cited context brief with a 1:1
    source citation per source-derived statement and a structural basis per coverage gap. Fail-closed
    on any citation mismatch or malformed evidence; no partial brief."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        try:
            context_brief = assemble_brief(
                state.get("validated_input"),
                state.get("observations"),
                state.get("asset_associations"),
                state.get("methodology_limitations"),
                state.get("coverage_gaps"),
                state.get("citations"),
            )
        except InputContractError as exc:
            return self._reject(state, exc.code, "assemble")

        emit_trace_event(
            "brief_assemble",
            {
                "correlation_id": state.get("correlation_id"),
                "statement_count": len(context_brief["statements"]),
            },
            state,
        )
        # result is the SAME cited brief as context_brief (docs/02: result limited to the cited brief).
        return {
            "context_brief": context_brief,
            "result": context_brief,
            "status": AgentStatus.SUCCESS.value,
        }

    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # No brief content / values / source detail echoed — only the non-sensitive code / reason.
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "brief_assemble_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"status": AgentStatus.ERROR.value, "error_log": [code]}
