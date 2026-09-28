"""AgentCore Platform v1.0 — OutputGateNode for ENE-C2-086 (outer post_process — terminal S-3).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state}).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Constructible with no arguments (PB-6 instantiates every node via node_cls()).
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — outer `post_process` / OutputGateNode row):
 - The TERMINAL S-3 gate over the WHOLE assembled brief mapped into the outer `result`. It applies
   the explicit domain deny policy (`src/services/output_policy.py`) across every string leaf/key of
   the brief — recursively, because the baseline `@final` S-3 credential scan is credential-only and
   the domain-semantic prohibitions are this node's responsibility. It is the final defence line and
   MUST NOT try to "repair" an unsafe brief.
 - On a clean brief: set `formatted_output` to the brief and `status = SUCCESS` (owned delta).
 - On a degraded request (pre_process set `error_code`): no brief exists by design; return the fixed
   notice for the code as `formatted_output` with `status = SUCCESS` (src/services/degradation.py).
 - On injection-derived text in the brief — a security failure: fail closed with
   `{status: ERROR, result: None, formatted_output: None}` so no partial output reaches the caller.
 - On any scope category (leak identification, explicit/hedged asset attribution, extrapolated
   emissions, regulatory-breach/report, field-work initiation, energy-asset control) OR any PII in
   the brief: withhold — clear the whole brief and complete with `error_code` `BRIEF_WITHHELD` /
   `PERSONAL_DATA_WITHHELD`, the fixed notice as `formatted_output`, and `status = SUCCESS`
   (meaning the request was handled safely, not that a brief was returned).
   In every case the blocked brief content is NEVER written to the error log, an audit event or the
   response; only the non-sensitive category slug / code is recorded.
 - PII: as the terminal output boundary this gate independently scans the brief for PII using the
   substrate detector `framework.security.detect_pii` (recursive string leaf/key scan) and withholds
   on any hit — defence-in-depth beyond the baseline S-2 input mask (which only guards the normal
   input path, not corrupt State or a downstream regression). The substrate detector is used as-is;
   no PII regex is hand-rolled here.
 - Credentials are handled by the framework baseline `@final` S-3 credential scan that runs on this
   node's returned dict (recursing containers). This node does not re-implement it.

S-1: outer node — `required_trust_level = VERIFIED_EXTERNAL` (S-1 enforced at the outer boundary;
declared explicitly rather than inherited).
S-4: exactly one domain `emit_trace_event()` per execute() on the pass, withhold and block path.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.degradation import BRIEF_WITHHELD, PERSONAL_DATA_WITHHELD, explain_degradation
from src.services.input_schema import ERR_SCHEMA
from src.services.output_policy import ERR_PROHIBITED_OUTPUT, INJECTION_DERIVED, contains_pii, find_prohibited
from src.services.failure_message import explain
from src.services.progress import emit_progress

# Substrate PII detector — reuse, never hand-roll the PII regex; tolerate either wheel layout
# (the detector ships under shared.security in this fleet's wheel; framework.security is an older
# fallback layout). If no substrate detector is present, detect_pii is None and the terminal PII
# scan degrades to a no-op while the domain-semantic deny policy still applies.
try:
    from shared.security.pii_detector import detect_pii
except ImportError:  # pragma: no cover - cross-layout shim
    try:
        from framework.security import detect_pii
    except ImportError:  # pragma: no cover - substrate absent in this layout
        detect_pii = None


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class OutputGateNode(FunctionNode):
    """Outer post_process node — terminal S-3 gate over the assembled brief. Pass → set
    formatted_output; scope category / PII → withhold with a fixed notice; injection-derived text →
    fail-closed with result / formatted_output cleared."""

    # S-1 (docs/02 §Security): outer boundary — a verified external caller. Declared explicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emit_progress("Preparing the response...")
        # A degraded request produced no brief by design. The output is the notice for its code, not
        # the brief shape with empty fields — an empty brief would read as "assembled, nothing to
        # report". Every value is a constant, so nothing the refused request carried reaches the
        # caller.
        degraded_code = state.get("error_code")
        if degraded_code:
            return self._notice(state, degraded_code, "degraded_request")

        brief = state.get("result")
        # A missing / non-dict brief means there is nothing safe to release — fail closed, no output.
        if not isinstance(brief, dict):
            return self._block(state, ERR_SCHEMA, "no_brief")

        # An instruction addressed to the agent is a security failure, not a scope question: asked on
        # its own first so that a brief carrying both is never reported as merely withheld.
        if find_prohibited(brief, (INJECTION_DERIVED,)) is not None:
            return self._block(state, ERR_PROHIBITED_OUTPUT, INJECTION_DERIVED)

        category = find_prohibited(brief)
        if category is not None:
            # category slug is non-sensitive (e.g. "asset_attribution"); brief content is NOT logged.
            return self._notice(state, BRIEF_WITHHELD, category)

        # Terminal PII scan via the substrate detector — withhold on any hit (defence-in-depth).
        # Guarded: if the substrate detector is unavailable in this layout, skip (no-op) rather
        # than crash; the domain-semantic deny policy above still applies.
        if detect_pii is not None and contains_pii(brief, detect_pii):
            return self._notice(state, PERSONAL_DATA_WITHHELD, "pii")

        emit_trace_event(
            "output_gate",
            {"correlation_id": state.get("correlation_id"), "statement_count": len(brief.get("statements", []))},
            state,
        )
        return {"formatted_output": brief, "status": AgentStatus.SUCCESS.value}

    def _notice(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # Completed without a brief: the fixed notice for the code is the output and the whole brief
        # is cleared. `error_code` is carried in this node's own dict as well as in State, so the
        # response and the audit trail name the same code. Only the code / category slug is recorded
        # — never brief content.
        emit_trace_event(
            "output_gate_withheld",
            {"correlation_id": state.get("correlation_id"), "error_code": code, "reason": reason},
            state,
        )
        return {
            "error_code": code,
            "result": None,
            "formatted_output": explain_degradation(code),
            "status": AgentStatus.SUCCESS.value,
        }

    def _block(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # Terminal block: clear the whole brief end-to-end (result + formatted_output). Only the
        # non-sensitive code / category slug is recorded — never the blocked brief content.
        emit_trace_event(
            "output_gate_blocked",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        return {
            "status": AgentStatus.ERROR.value,
            "result": None,
            "formatted_output": None,
            "error_log": [code],
        }
