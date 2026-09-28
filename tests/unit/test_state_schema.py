# ENE-C2-086 — Unit Tests: State schema contract
#
# Verifies the flat-TypedDict State contract only — NOT graph/node behavior:
#   - outer State adds no domain field (inherited AgentState slots only);
#   - inner EvidenceWorkflowState declares exactly the documented domain fields;
#   - annotations are JSON/msgpack-safe containers (list/dict), no Pydantic/dataclass/objects;
#   - no credential-like or raw-payload fields (method_notes/reporting_template stay in
#     validated_input, never copied into State);
#   - minimal valid examples serialize round-trip.
# (docs/02 State Definition — Outer/Inner State tables + Input Contract & Data Flow)

import json

from framework.schemas.agent_state import AgentState
from src.schemas.state import EvidenceWorkflowState, State

EXPECTED_INNER = {
    "observations",
    "asset_associations",
    "citations",
    "methodology_limitations",
    "coverage_gaps",
    "context_brief",
}

# Names that must never enter the typed State contract (credentials / raw objects / raw payload).
# method_notes and reporting_template are deliberately included: docs/02 keeps them inside the
# inherited validated_input, never copied into a domain State field.
FORBIDDEN = {
    "api_key", "apikey", "token", "approval_token", "credential", "credentials",
    "secret", "password", "jwt", "client", "llm", "context", "invocation_context",
    "raw_payload", "payload", "method_notes", "reporting_template",
}


def _annotations(cls) -> dict:
    """All TypedDict annotations on the class (inherited from AgentState + own)."""
    return dict(getattr(cls, "__annotations__", {}))


_BASE = set(_annotations(AgentState))


def _own(cls) -> set:
    """Field names declared ON this class only (not inherited from AgentState)."""
    return set(_annotations(cls)) - _BASE


def test_outer_state_adds_no_domain_field():
    # docs/02: the outer State adds no domain field — its one own field is the degradation marker,
    # which carries an allow-listed code and never brief content.
    assert _own(State) == {"error_code"}


def test_inner_state_declares_exactly_the_documented_domain_fields():
    own = _own(EvidenceWorkflowState)
    assert own == EXPECTED_INNER, f"inner domain fields drift vs docs/02: {own ^ EXPECTED_INNER}"


def test_no_credential_or_raw_object_fields():
    for cls in (State, EvidenceWorkflowState):
        leaked = _own(cls) & FORBIDDEN
        assert not leaked, f"{cls.__name__} declares forbidden field(s): {leaked}"


def test_annotations_are_json_safe_containers():
    # Every inner domain field is a list/dict container (JSON/msgpack-safe) — never an
    # arbitrary Python object / Pydantic model / dataclass annotation.
    ann = _annotations(EvidenceWorkflowState)
    for field in EXPECTED_INNER:
        text = str(ann[field])
        assert ("list" in text) or ("dict" in text), f"{field} is not a list/dict container: {text}"


def test_minimal_examples_are_serializable():
    example = {
        "observations": [{
            "observation_id": "obs-1", "value": 1.2, "unit": "ppb",
            "observed_at": "2026-01-01T00:00:00Z", "location": "sector-A",
            "source_ref": {"source_id": "s1", "locator": "p1",
                           "approval": {"attested_by": "owner", "attested_at": "2026-01-01",
                                        "approval_ref": "a1"}},
        }],
        "asset_associations": [{
            "observation_ref": "obs-1", "asset_id": "asset-X", "relation": "locational",
            "source_ref": {"source_id": "s1", "locator": "p1"},
        }],
        "citations": [{"statement_id": "st-1", "source_id": "s1", "locator": "p1"}],
        "methodology_limitations": [{
            "text": "coverage limited to sector-A",
            "source_ref": {"source_id": "s1", "locator": "p1"},
        }],
        "coverage_gaps": [{"text": "sector-B not covered", "basis_observation_id": "obs-1"}],
        "context_brief": {"sections": [{
            "title": "Summary",
            "statements": [{"text": "...", "citation": {"source_id": "s1", "locator": "p1"}}],
        }]},
    }
    # msgpack-safe proxy: json round-trips only primitives / list / dict.
    assert json.loads(json.dumps(example)) == example
    assert set(example) == EXPECTED_INNER
