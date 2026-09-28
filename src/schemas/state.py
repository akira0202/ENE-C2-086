"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel / dataclass /
# arbitrary Python object. LangGraph checkpoints use msgpack serialization, so only
# JSON-safe types are allowed (str / int / float / bool / None / list / dict).
# Do NOT add credentials, secrets, InvocationContext, client objects, or raw source blobs.

from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Outer State for EnergyMethaneObservationContextBriefGraph (Cat 2, L1-direct).

    Flat TypedDict — JSON-serializable types only. The outer graph adds NO domain field;
    the handoff uses inherited AgentState slots:
      - user_input: str   — JSON string carrying the supplied inputs
      - validated_input   — parsed supplied inputs (set by the outer pre_process)
      - result            — cited context brief mapped from the inner graph by merge_output
      - formatted_output  — the S-3-gated brief; AgentBaseGraph.get_output() = formatted_output or result
      - status, session_id, and the reducer-managed node_history / error_log
    The domain pipeline runs in EvidenceWorkflowState (below); node_history / error_log are
    reducer-managed and are NEVER projected inner -> outer.
    """

    # Degradation marker (src/services/degradation.py). A request the caller can correct, or a brief
    # withheld by the output policy, ends the run as SUCCESS carrying this allow-listed code and a
    # fixed notice instead of a brief. Absent on a normal run. The structural S-2 screen, an
    # injection-style directive in the brief, and an internally inconsistent run stay status=ERROR.
    error_code: NotRequired[str]


class EvidenceWorkflowState(AgentState):
    """Inner State for EvidenceWorkflowGraph (the domain pipeline inside the main GraphNode).

    Flat TypedDict — JSON-safe types only (no Pydantic / dataclass / InvocationContext /
    credentials / raw source blobs). `method_notes` and `reporting_template` are NOT copied
    into domain fields: they stay in the inherited `validated_input` and are read there by
    limit_gap_analysis / cited_brief_assemble (docs/02 Input Contract & Data Flow).

    Inherited from AgentState: user_input (JSON string handed in by the outer GraphNode),
    validated_input (parsed supplied inputs), result (the cited brief, returned by get_output),
    status. Domain working fields (set progressively by the inner nodes) are declared below.
    """

    # Supplied observation values, passed through — never re-estimated.
    # (set by observation_asset_extract)
    observations: NotRequired[list[dict[str, Any]]]
    # Locational-only associations (observation <-> asset vicinity). Each retains
    # `observation_ref` and the resolved observation's `source_ref` citation anchor;
    # never emission attribution. (set by observation_asset_extract)
    asset_associations: NotRequired[list[dict[str, Any]]]
    # Provenance anchors (supplied-source references) per extracted item.
    # (set by observation_asset_extract)
    citations: NotRequired[list[dict[str, Any]]]
    # Deterministic method limitations derived from `validated_input.method_notes`; each
    # retains the originating method note's `source_ref` as its citation anchor.
    # (set by limit_gap_analysis)
    methodology_limitations: NotRequired[list[dict[str, Any]]]
    # Deterministic coverage gaps in the supplied observations — absence / coverage only;
    # never synthesized values, leak attribution, emissions estimation, or regulatory
    # conclusions. (set by limit_gap_analysis)
    coverage_gaps: NotRequired[list[dict[str, Any]]]
    # Assembled cited brief per the supplied `reporting_template`, one citation per statement.
    # (set by cited_brief_assemble)
    context_brief: NotRequired[dict[str, Any]]
