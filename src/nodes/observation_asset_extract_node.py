"""AgentCore Platform v1.0 — ObservationAssetExtractNode for ENE-C2-086 (inner evidence workflow).

Node contract:
 - Extend FunctionNode; implement execute(state) -> dict.
 - Return ONLY the fields this node changes (never {**state} — error_log / node_history are
   operator.add reducer channels, so spreading state double-appends the audit trail).
 - Return AgentStatus.<X>.value strings — never the bare Enum object.
 - Constructible with no arguments (PB-6 instantiates every node via node_cls()).
 - Never import from mediator/, api/, src/graph/, or other agents.

Responsibility (docs/02 — inner `observation_asset_extract` row):
 - Reads the canonical `validated_input` produced upstream by `SourceIntakeNode` (the outer
   pre_process boundary) and restored by `InputHydrateNode`. Emits ONLY three owned domain fields
   plus `status`:
     * `observations`        — a minimal, value-invariant copy of the supplied observations;
     * `asset_associations`  — locational-only (observation <-> asset vicinity) associations, each
                               inheriting the resolved observation's `source_ref` citation anchor;
     * `citations`           — one provenance anchor per emitted observation / association, so every
                               emitted item resolves 1:1 to a supplied `source_ref`.
 - Read-only extraction: values are copied verbatim — never converted, rounded, completed, or
   estimated. This node NEVER identifies a leak, attributes emissions to an asset, computes a
   difference / threshold / time-series estimate, or writes `methodology_limitations`,
   `coverage_gaps`, `context_brief`, `result`, or `formatted_output` (later inner nodes / the outer
   post_process own those).
 - Node-local defense: even though the input-boundary node canonicalizes the contract, this node
   does not blindly trust `validated_input`. It re-checks the minimal shape + citation integrity it
   depends on (dict shape, observation-id validity + 1:1 uniqueness, `relation == "locational"`,
   reference resolution, `source_ref` presence) and fails closed with a non-sensitive error CODE, no
   partial output. It does NOT re-run or widen the input contract (owned by the input-boundary node)
   — it re-verifies only what it emits.

S-1: inner nodes declare `required_trust_level = ANONYMOUS` — `BaseGraph.invoke()` does not
propagate caller trust into the subgraph; S-1 is enforced at the outer `VERIFIED_EXTERNAL` boundary
(docs/02 §Security). The declaration is explicit — implicit inheritance is not accepted.
S-4: exactly one domain `emit_trace_event()` per execute() on both the success and the reject path;
the payload carries only counts / a non-sensitive code — never observation values, locations, source
text, or approval detail.
"""

import copy
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Reuse the fail-closed error CODES from the input-contract service so a single source of truth
# defines them (no drift). These are plain non-sensitive strings — importing them does NOT re-run
# or widen the input contract; this node only re-verifies the minimal shape it emits.
from src.services.input_schema import (
    ERR_AMBIGUOUS_OBSERVATION_REF,
    ERR_NONLOCATIONAL_RELATION,
    ERR_SCHEMA,
    ERR_UNKNOWN_OBSERVATION_REF,
)
from src.services.failure_message import explain
from src.services.progress import emit_progress

# The exact field set of an emitted observation (a minimal copy of the supplied observation).
_OBS_KEYS = ("observation_id", "value", "unit", "observed_at", "location", "source_ref")


def _has_sentence(reason: str) -> bool:
    """True when `reason` resolves to a sentence of its own rather than the general fallback."""
    return explain(reason) != explain("__no_such_code__")


class ObservationAssetExtractNode(FunctionNode):
    """Inner evidence-workflow node — extract supplied observations and locational-only asset
    associations, each citation-anchored to the supplied `source_ref`. No leak identification,
    no emission attribution, no estimation. Fail-closed on malformed `validated_input`."""

    # S-1 (docs/02 §Security): inner node — caller trust is enforced at the outer boundary, so the
    # inner node is ANONYMOUS. Declared explicitly.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        validated_input = state.get("validated_input")
        if not isinstance(validated_input, dict):
            return self._reject(state, ERR_SCHEMA, "validated_input_not_dict")

        observations = validated_input.get("observations")
        asset_reference_map = validated_input.get("asset_reference_map")
        if not (isinstance(observations, list) and observations):
            return self._reject(state, ERR_SCHEMA, "observations_missing")
        if not isinstance(asset_reference_map, list):
            return self._reject(state, ERR_SCHEMA, "asset_reference_map_missing")

        # --- observations: minimal value-invariant copy; index by unique observation_id ---------
        out_observations: list[Any] = []
        obs_source_ref: dict[str, Any] = {}  # observation_id -> its source_ref (for association / citation)
        for obs in observations:
            if not isinstance(obs, dict) or any(k not in obs for k in _OBS_KEYS):
                return self._reject(state, ERR_SCHEMA, "observation_shape")
            obs_id = obs["observation_id"]
            if not isinstance(obs_id, str) or not obs_id.strip():
                return self._reject(state, ERR_SCHEMA, "observation_id_invalid")
            source_ref = obs["source_ref"]
            if not isinstance(source_ref, dict):
                return self._reject(state, ERR_SCHEMA, "source_ref_missing")
            if obs_id in obs_source_ref:
                # A duplicate observation_id makes every reference to it resolve to >1 observation.
                return self._reject(state, ERR_AMBIGUOUS_OBSERVATION_REF, "duplicate_observation_id")
            obs_source_ref[obs_id] = source_ref
            # Copy exactly the documented fields, verbatim (no transform / rounding / estimation).
            out_observations.append(
                {
                    "observation_id": obs_id,
                    "value": obs["value"],
                    "unit": obs["unit"],
                    "observed_at": obs["observed_at"],
                    "location": obs["location"],
                    "source_ref": copy.deepcopy(source_ref),
                }
            )

        # --- asset_associations: locational-only; inherit the resolved observation's source_ref --
        out_associations: list[Any] = []
        for entry in asset_reference_map:
            if not isinstance(entry, dict) or any(k not in entry for k in ("observation_ref", "asset_id", "relation")):
                return self._reject(state, ERR_SCHEMA, "association_shape")
            if entry["relation"] != "locational":
                # Never accept an attribution/causal relation — locational vicinity only.
                return self._reject(state, ERR_NONLOCATIONAL_RELATION, "nonlocational_relation")
            observation_ref = entry["observation_ref"]
            if observation_ref not in obs_source_ref:
                return self._reject(state, ERR_UNKNOWN_OBSERVATION_REF, "unresolved_observation_ref")
            out_associations.append(
                {
                    "observation_ref": observation_ref,
                    "asset_id": entry["asset_id"],
                    "relation": "locational",
                    # source_ref is NOT minted here — it is inherited from the referenced observation.
                    "source_ref": copy.deepcopy(obs_source_ref[observation_ref]),
                }
            )

        # --- citations: one anchor per emitted observation / association (every item is citable) --
        citations: list[Any] = []
        for obs in out_observations:
            citations.append(
                {
                    "subject_type": "observation",
                    "subject_ref": obs["observation_id"],
                    "source_ref": copy.deepcopy(obs["source_ref"]),
                }
            )
        for assoc in out_associations:
            citations.append(
                {
                    "subject_type": "asset_association",
                    # subject_ref must identify the association uniquely: a bare observation_ref is
                    # NOT unique when one observation is locationally associated with several assets
                    # (all sharing that observation's source_ref). Keying on (observation_ref, asset_id)
                    # keeps each association's citation 1:1 traceable. source_ref is still inherited
                    # from the referenced observation — never minted here.
                    "subject_ref": {"observation_ref": assoc["observation_ref"], "asset_id": assoc["asset_id"]},
                    "source_ref": copy.deepcopy(assoc["source_ref"]),
                }
            )

        emit_trace_event(
            "observation_extract",
            {
                "correlation_id": state.get("correlation_id"),
                "observation_count": len(out_observations),
                "association_count": len(out_associations),
                "citation_count": len(citations),
            },
            state,
        )
        return {
            "observations": out_observations,
            "asset_associations": out_associations,
            "citations": citations,
            "status": AgentStatus.SUCCESS.value,
        }

    # --- fail-closed helper: owned delta only; code in error_log, slug in the trace event -------
    def _reject(self, state: dict[str, Any], code: str, reason: str) -> dict[str, Any]:
        # Never echo observation values / locations / source text / approval detail — only the
        # non-sensitive code / reason slug / correlation_id.
        # `reason` names the specific cause (malformed_json, too_deep, ...) while `code` is the
        # coarse contract bucket the run fails under. Explaining the code alone collapses every
        # rejection to one sentence, so prefer the reason and fall back to the code only when it
        # has no sentence of its own.
        emit_progress(explain(reason) if _has_sentence(reason) else explain(code))
        emit_trace_event(
            "observation_extract_rejected",
            {"correlation_id": state.get("correlation_id"), "code": code, "reason": reason},
            state,
        )
        return {"status": AgentStatus.ERROR.value, "error_log": [code]}
