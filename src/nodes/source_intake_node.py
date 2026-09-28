"""AgentCore Platform v1.0 — SourceIntakeNode for ENE-C2-086 (outer pre_process).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state} — error_log / node_history are
   operator.add reducer channels, so spreading state double-appends the audit trail).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — outer pre_process / SourceIntakeNode row):
 - Receives the framework-inherited user_input: str (a JSON string of the supplied inputs),
   parses it, and validates the supplied-source / provenance contract, writing the canonical,
   JSON-safe validated_input. It builds NO inner domain value (observations / asset_associations /
   citations / methodology_limitations / coverage_gaps / context_brief) and does NOT touch result —
   those belong to the inner EvidenceWorkflowGraph. The main GraphNode.extract_input() JSON-encodes
   validated_input into the inner user_input; the inner input_hydrate restores it.
 - S-2 lives in _extra_security_gate_input(): STRUCTURAL sanitization of the raw string only —
   non-str / NUL / control-character / oversized payloads are rejected there. The framework @final
   _security_gate_input() (baseline PII scan) is NOT overridden and still runs. No lexical / semantic
   prompt-injection heuristic is applied — v1 has no LLM boundary; semantic output policy is the
   terminal S-3 gate's job (post_process, later issue).
 - execute() performs the input-contract validation via src/services/input_schema.py. A request that
   does not meet the contract is one the caller can correct, so the run completes as SUCCESS carrying
   an allow-listed `error_code` (src/services/degradation.py) and no validated_input: `main` skips
   the inner workflow and `post_process` returns the fixed notice for that code instead of a brief.
   Payload content is never echoed. The structural S-2 screen above stays a fail-closed ERROR — it is
   the gate refusing the input, and guidance would tell the sender how to get past it. No retrieval /
   refresh / inference / gap-filling; approval authenticity is trusted at the VERIFIED_EXTERNAL
   boundary, not re-verified.
"""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.degradation import DEGRADATION_CODES, EMPTY_REQUEST, MALFORMED_JSON, TOO_DEEP
from src.services.input_schema import ERR_SCHEMA, InputContractError, validate_and_normalize
from src.services.progress import emit_progress
from src.services.failure_message import explain

# Defensive raw-input size limit (structural S-2 screen).
_MAX_INPUT_CHARS = 2_000_000


def _screen_non_text(text: str) -> bool:
    """True when the raw string is non-text / binary: a NUL byte, or an excessive proportion
    of other control characters (tab / newline / carriage-return excluded — legitimate in JSON)."""
    if "\x00" in text:
        return True
    control = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\n\r")
    return bool(control) and control > max(8, len(text) // 100)


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class SourceIntakeNode(FunctionNode):
    """Outer pre_process node — untrusted-input boundary: parse + validate the supplied inputs,
    fail-closed on malformed / unattested / uncitable / non-locational / unresolved-reference input."""

    # S-1 (docs/02 §Security): the outer boundary requires a verified external caller.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    # --- S-2 structural gate (runs before execute(); never raises, returns a dict) --------
    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = state.get("user_input")
        if payload is None:
            return state  # missing input — surfaced by execute() as ERR_SCHEMA
        if not isinstance(payload, str):
            # Non-text input — NEVER str()-coerced (that would smuggle binary / NUL through).
            return self._reject(state, ERR_SCHEMA, "s2_non_text_type")
        if _screen_non_text(payload):
            return self._reject(state, ERR_SCHEMA, "s2_non_text")
        if len(payload) > _MAX_INPUT_CHARS:
            return self._reject(state, ERR_SCHEMA, "s2_oversized")
        return state

    # --- business validation ---------------------------------------------------------------
    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emit_progress("Checking the request...")
        raw = state.get("user_input")
        if not isinstance(raw, str) or not raw.strip():
            return self._degrade(state, EMPTY_REQUEST)

        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return self._degrade(state, MALFORMED_JSON)
        except RecursionError:
            # Which of the two codes a very deeply nested request lands on depends on where the
            # parser gives up, so both are caller-correctable and both complete with a notice —
            # the outcome never differs in class, only in wording.
            return self._degrade(state, TOO_DEEP)

        try:
            validated_input = validate_and_normalize(payload)
        except InputContractError as exc:
            return self._degrade(state, exc.code)

        emit_trace_event(
            "source_intake",
            {
                "correlation_id": state.get("correlation_id"),
                "observation_count": len(validated_input["observations"]),
                "asset_reference_count": len(validated_input["asset_reference_map"]),
                "method_note_count": len(validated_input["method_notes"]),
            },
            state,
        )
        return {"validated_input": validated_input, "status": AgentStatus.SUCCESS.value}

    # --- degraded completion: the caller can correct the request ----------------------------
    def _degrade(self, state: dict[str, Any], code: str) -> dict[str, Any]:
        # The run completes and carries the reason; post_process turns the code into the notice.
        # Only the allow-listed code is recorded — never payload content. A code this agent has no
        # notice for is a defect, not a caller correction, so it stays a fail-closed error.
        if code not in DEGRADATION_CODES:
            return self._reject(state, ERR_SCHEMA, "contract_violation")
        emit_trace_event(
            "source_intake_degraded",
            {"correlation_id": state.get("correlation_id"), "error_code": code},
            state,
        )
        return {"error_code": code, "status": AgentStatus.SUCCESS.value}

    # --- fail-closed helper: owned delta only; code in error_log, slug in the trace event ---
    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # Payload is never echoed — only the non-sensitive code / reason slug / correlation_id.
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "source_intake_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"status": AgentStatus.ERROR.value, "error_log": [code]}
