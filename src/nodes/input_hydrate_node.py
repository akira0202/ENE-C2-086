"""AgentCore Platform v1.0 — InputHydrateNode for ENE-C2-086 (inner evidence workflow entry).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state}).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Constructible with no arguments (PB-6 instantiates every node via node_cls()).
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — inner `input_hydrate` row):
 - The inner graph receives its `user_input` as the JSON string that the outer `EvidenceWorkflowGraphNode.extract_input()` produced from the canonical `validated_input`. This node parses that
   string back into `validated_input` and RE-VALIDATES it after the string handoff (defence against
   any corruption crossing the boundary), reusing the same input-contract validator as the outer
   pre_process — it does not re-implement or widen the contract. It writes ONLY `validated_input`
   and `status` (owned delta); the downstream inner nodes read `validated_input` from there.
 - Fail-closed with a non-sensitive error CODE (never payload content) on a missing / non-string /
   malformed / contract-violating handoff, with no partial output.

S-1: inner node — `required_trust_level = ANONYMOUS` (S-1 enforced at the outer VERIFIED_EXTERNAL
boundary; declared explicitly rather than inherited).
S-4: exactly one domain `emit_trace_event()` per execute() on the success and reject path; payload
carries only counts / a non-sensitive code — never observation values, locations, or source detail.
"""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.input_schema import ERR_SCHEMA, InputContractError, validate_and_normalize
from src.services.failure_message import explain
from src.services.progress import emit_progress


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class InputHydrateNode(FunctionNode):
    """Inner entry node — parse the JSON-string handoff back into `validated_input` and re-validate
    it against the input contract. Fail-closed on a malformed handoff; no partial output."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input")
        if not isinstance(raw, str) or not raw.strip():
            return self._reject(state, ERR_SCHEMA, "empty_or_missing")

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return self._reject(state, ERR_SCHEMA, "malformed_json")
        except RecursionError:
            return self._reject(state, ERR_SCHEMA, "too_deep")

        try:
            # Re-validate the handed-off payload with the SAME contract validator (defence after the
            # string round-trip); the canonical validated_input is idempotent under it.
            validated_input = validate_and_normalize(payload)
        except InputContractError as exc:
            return self._reject(state, exc.code, "contract_violation")

        emit_trace_event(
            "hydrate",
            {
                "correlation_id": state.get("correlation_id"),
                "observation_count": len(validated_input["observations"]),
                "asset_reference_count": len(validated_input["asset_reference_map"]),
                "method_note_count": len(validated_input["method_notes"]),
            },
            state,
        )
        return {"validated_input": validated_input, "status": AgentStatus.SUCCESS.value}

    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "hydrate_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"status": AgentStatus.ERROR.value, "error_log": [code]}
