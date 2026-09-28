"""AgentCore Platform v1.0 — LimitGapAnalysisNode for ENE-C2-086 (inner evidence workflow).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state} — error_log / node_history are
   operator.add reducer channels, so spreading state double-appends the audit trail).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Constructible with no arguments (PB-6 instantiates every node via node_cls()).
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — inner `limit_gap_analysis` row):
 - Reads the supplied `method_notes` (from the canonical `validated_input`) and the extracted
   `observations` / `asset_associations` (set upstream by the observation-extraction node). Emits
   ONLY two owned domain fields plus `status`:
     * `methodology_limitations` — one per supplied method note, each carrying that note's
       `source_ref` as its citation anchor. The `statement` quotes / structures the note text
       verbatim — NO summarization, semantic inference, or synthesized limitation (satellite
       accuracy, detection limit, leak likelihood, error rate, etc. are never invented).
     * `coverage_gaps` — deterministic structural insufficiencies of the SUPPLIED observations /
       associations only (counts / distinct locations). A gap states that observed facts are
       insufficient; it carries a non-inferential structural `basis`, and it does NOT reuse a
       method note's `source_ref` (a gap is not a source-derived statement).
 - Read-only, deterministic, inference-free. This node NEVER identifies a leak, attributes
   emissions to an asset, estimates emissions beyond supplied values, makes a regulatory-breach
   claim, proposes field work, or does any arithmetic on observation values (no add / subtract /
   average / interpolation / extrapolation / unit conversion). `asset_id` is treated purely as a
   locational association — never as a cause / emission source / leak location. It writes NONE of
   `context_brief`, `result`, `formatted_output`, or `citations` (later inner nodes / outer
   post_process own those); the terminal S-3 prohibited-phrasing check is the output gate's job.
 - Node-local defense: even though the input-boundary and extraction nodes canonicalize the data,
   this node performs a minimal shape check (dict `validated_input`; `method_notes` a list of
   {text, valid source_ref}; `observations` / `asset_associations` lists; well-formed observation
   shape for the fields it reads) and fails closed with a non-sensitive error CODE and no partial
   output. It does NOT re-run or widen the input contract — it verifies only what it consumes.

S-1: inner nodes declare `required_trust_level = ANONYMOUS` — S-1 is enforced at the outer
`VERIFIED_EXTERNAL` boundary (docs/02 §Security). Declared explicitly.
S-4: exactly one domain `emit_trace_event()` per execute() on both the success and reject path; the
payload carries only counts / a non-sensitive code — never note text, observation values, locations,
or approval detail.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Reuse the input-contract service (single source of truth): the fail-closed error CODES (plain
# non-sensitive strings), the shared source_ref validator/canonicalizer, and its exception type.
# Reusing these re-verifies the citation/association shape this node consumes/emits WITHOUT
# re-implementing or widening the input contract, and keeps the codes from drifting.
from src.services.input_schema import (
    ERR_NONLOCATIONAL_RELATION,
    ERR_SCHEMA,
    ERR_UNKNOWN_OBSERVATION_REF,
    InputContractError,
    canonical_source_ref,
)
from src.services.failure_message import explain
from src.services.progress import emit_progress


def _req(cond: object, code: str) -> None:
    """Raise InputContractError(code) — a non-sensitive fail-closed code — when cond is falsy."""
    if not cond:
        raise InputContractError(code)


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class LimitGapAnalysisNode(FunctionNode):
    """Inner evidence-workflow node — record deterministic methodology limitations (from the supplied
    method notes, each source-cited) and structural coverage gaps (from the supplied observations /
    associations, structurally grounded). No estimation, no attribution, no regulatory conclusion.
    Fail-closed on malformed input."""

    # S-1 (docs/02 §Security): inner node — caller trust enforced at the outer boundary. Declared
    # explicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        validated_input = state.get("validated_input")
        if not isinstance(validated_input, dict):
            return self._reject(state, ERR_SCHEMA, "validated_input_not_dict")

        method_notes = validated_input.get("method_notes")
        observations = state.get("observations")
        asset_associations = state.get("asset_associations")
        if not isinstance(method_notes, list):
            return self._reject(state, ERR_SCHEMA, "method_notes_not_list")
        if not isinstance(observations, list):
            return self._reject(state, ERR_SCHEMA, "observations_not_list")
        if not isinstance(asset_associations, list):
            return self._reject(state, ERR_SCHEMA, "asset_associations_not_list")

        try:
            methodology_limitations = self._limitations(method_notes)
            observation_ids, location_count = self._observation_structure(observations)
            association_count = self._valid_association_count(asset_associations, observation_ids)
        except InputContractError as exc:
            return self._reject(state, exc.code, "contract_violation")

        coverage_gaps = self._coverage_gaps(len(observations), association_count, location_count)

        emit_trace_event(
            "limit_gap",
            {
                "correlation_id": state.get("correlation_id"),
                "limitation_count": len(methodology_limitations),
                "gap_count": len(coverage_gaps),
            },
            state,
        )
        return {
            "methodology_limitations": methodology_limitations,
            "coverage_gaps": coverage_gaps,
            "status": AgentStatus.SUCCESS.value,
        }

    # --- methodology_limitations: one per note, verbatim statement + validated/canonical source_ref
    def _limitations(self, method_notes: list[Any]) -> list[Any]:
        """One limitation per supplied method note. The statement quotes the note text verbatim; the
        source_ref is re-verified + canonicalized (allowlisted rebuild) via the shared validator, so
        a broken / uncitable / extra-nested source_ref fails closed and no fabricated or raw-blob
        citation reaches State. Raises InputContractError(code) on the first violation."""
        limitations: list[Any] = []
        for note in method_notes:
            _req(isinstance(note, dict), ERR_SCHEMA)
            text = note.get("text")
            _req(_nonempty_str(text), ERR_SCHEMA)
            limitations.append(
                {
                    "kind": "methodology_limitation",
                    # Verbatim quote of the note text — no summarization / semantic inference.
                    "statement": text,
                    # Validated + canonicalized citation (source_id / locator / approval); a bad or
                    # extra-keyed source_ref raises, never copies through.
                    "source_ref": canonical_source_ref(note.get("source_ref")),
                }
            )
        return limitations

    # --- observation structure: read only observation_id + location (never value — no arithmetic)
    def _observation_structure(self, observations: list[Any]) -> tuple[set[str], int]:
        """Return (observation_ids, distinct_location_count). A broken observation shape (non-dict,
        empty observation_id / location) fails closed. Raises InputContractError(ERR_SCHEMA)."""
        observation_ids: set[str] = set()
        locations: set[str] = set()
        for obs in observations:
            _req(isinstance(obs, dict), ERR_SCHEMA)
            _req(_nonempty_str(obs.get("observation_id")), ERR_SCHEMA)
            _req(_nonempty_str(obs.get("location")), ERR_SCHEMA)
            observation_ids.add(obs["observation_id"])
            locations.add(obs["location"])
        return observation_ids, len(locations)

    # --- associations: count only VALID locational associations (contents verified, not just length)
    def _valid_association_count(self, asset_associations: list[Any], observation_ids: set[str]) -> int:
        """Verify each association is a well-formed LOCATIONAL association that resolves to a supplied
        observation, then return the count. Counting by list length alone would let a malformed /
        non-locational / unresolved entry wrongly suppress the no-association gap. Raises
        InputContractError(code) on the first violation."""
        for assoc in asset_associations:
            _req(isinstance(assoc, dict), ERR_SCHEMA)
            _req(_nonempty_str(assoc.get("observation_ref")), ERR_SCHEMA)
            _req(_nonempty_str(assoc.get("asset_id")), ERR_SCHEMA)
            _req(assoc.get("relation") == "locational", ERR_NONLOCATIONAL_RELATION)
            _req(assoc["observation_ref"] in observation_ids, ERR_UNKNOWN_OBSERVATION_REF)
        return len(asset_associations)

    # --- deterministic, inference-free coverage-gap derivation from validated structure ---------
    def _coverage_gaps(self, observation_count: int, association_count: int, location_count: int) -> list[Any]:
        """Structural insufficiencies of the supplied evidence only. Each gap carries a
        non-inferential structural basis, never a source_ref, and never estimates / attributes."""
        gaps: list[Any] = []
        if observation_count == 0:
            gaps.append(
                {
                    "kind": "coverage_gap",
                    "reason": "no_observations_supplied",
                    "basis": {"observation_count": 0},
                }
            )
        if association_count == 0:
            gaps.append(
                {
                    "kind": "coverage_gap",
                    "reason": "no_locational_association_supplied",
                    "basis": {"association_count": 0},
                }
            )
        # All supplied observations fall in a single location (only meaningful with >1 observation).
        if observation_count > 1 and location_count == 1:
            gaps.append(
                {
                    "kind": "coverage_gap",
                    "reason": "single_location_coverage",
                    "basis": {"location_count": 1, "observation_count": observation_count},
                }
            )
        return gaps

    # --- fail-closed helper: owned delta only; code in error_log, slug in the trace event ---
    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # Never echo note text / observation values / locations / approval detail — only the
        # non-sensitive code / reason slug / correlation_id.
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "limit_gap_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"status": AgentStatus.ERROR.value, "error_log": [code]}
