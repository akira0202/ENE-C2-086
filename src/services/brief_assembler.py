"""AgentCore Platform v1.0 — deterministic cited-brief assembly for ENE-C2-086.

Deterministic, side-effect-free, framework-free (no agenticstar / framework imports, no I/O, no
LLM). Assembles a cited context brief from ALREADY-EXTRACTED, canonical evidence (observations,
locational asset associations, methodology limitations, coverage gaps) following the supplied
`reporting_template`, and resolves each source-derived statement to EXACTLY ONE supplied
`source_ref` citation. Fails closed with a non-sensitive error CODE:

  - source-derived statement (observation / asset_association / methodology_limitation) whose
    citation is missing, duplicated, or inconsistent with the item's own source_ref
    → ERR_SOURCE_CITATION_MISMATCH
  - malformed input shape (a field this assembler reads is absent / wrong type)
    → ERR_SCHEMA

A coverage gap is NOT a source-derived statement: it carries a non-inferential structural `basis`
and MUST NOT reuse a method note's source_ref. No arithmetic on observation values (no diff /
average / interpolation / extrapolation / unit conversion / emission estimation), no leak
identification, and no asset attribution — the assembler only quotes / structures supplied data.
"""

from typing import Any

from src.services.input_schema import (
    ERR_SCHEMA,
    ERR_SOURCE_CITATION_MISMATCH,
    InputContractError,
    canonical_source_ref,
)


def _req(cond: object, code: str) -> None:
    if not cond:
        raise InputContractError(code)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _safe_canonical_source_ref(source_ref: Any) -> dict[str, Any] | None:
    """Canonicalize a supplied source_ref, or return None if it is malformed (so a broken note
    source_ref simply fails to match rather than raising)."""
    try:
        return canonical_source_ref(source_ref)
    except InputContractError:
        return None


def _resolve_citation(
    citations: list[Any], subject_type: str, subject_ref: Any, own_source_ref: dict[str, Any]
) -> dict[str, Any]:
    """Resolve EXACTLY ONE citation for a source-derived statement and return its canonical
    source_ref. Zero matches = missing, more than one = duplicate, a source_ref inconsistent with
    the item's own source_ref = unresolved — all ERR_SOURCE_CITATION_MISMATCH."""
    matches = [
        c
        for c in citations
        if isinstance(c, dict) and c.get("subject_type") == subject_type and c.get("subject_ref") == subject_ref
    ]
    _req(len(matches) == 1, ERR_SOURCE_CITATION_MISMATCH)
    cited_source_ref = matches[0].get("source_ref")
    # The citation must anchor to the SAME supplied source_ref the item carries (1:1 to source).
    _req(cited_source_ref == own_source_ref, ERR_SOURCE_CITATION_MISMATCH)
    try:
        return canonical_source_ref(cited_source_ref)  # validate + allowlisted rebuild
    except InputContractError as exc:
        raise InputContractError(ERR_SOURCE_CITATION_MISMATCH) from exc


def assemble_brief(
    validated_input: Any,
    observations: Any,
    asset_associations: Any,
    methodology_limitations: Any,
    coverage_gaps: Any,
    citations: Any,
) -> dict[str, Any]:
    """Assemble the deterministic cited context brief. Raises InputContractError(code) on the first
    shape or citation violation; returns no partial brief."""
    _req(isinstance(validated_input, dict), ERR_SCHEMA)
    reporting_template = validated_input.get("reporting_template")
    _req(isinstance(reporting_template, dict), ERR_SCHEMA)  # canonical (bounded) structure from intake
    # Supplied method notes are the provenance set for methodology limitations (the citations list
    # from extraction only anchors observations / associations). Each limitation must resolve 1:1 to
    # exactly one supplied method note.
    supplied_method_notes = validated_input.get("method_notes")
    _req(isinstance(supplied_method_notes, list), ERR_SCHEMA)
    for seq in (observations, asset_associations, methodology_limitations, coverage_gaps, citations):
        _req(isinstance(seq, list), ERR_SCHEMA)

    statements: list[Any] = []

    # --- observation statements: verbatim supplied value, cited 1:1 -----------------------------
    for obs in observations:
        _req(isinstance(obs, dict), ERR_SCHEMA)
        obs_id = obs.get("observation_id")
        _req(_nonempty_str(obs_id), ERR_SCHEMA)
        for field in ("value", "unit", "observed_at", "location", "source_ref"):
            _req(field in obs, ERR_SCHEMA)
        _req(isinstance(obs["source_ref"], dict), ERR_SCHEMA)
        source_ref = _resolve_citation(citations, "observation", obs_id, obs["source_ref"])
        statements.append(
            {
                "kind": "observation",
                # Reports the supplied value verbatim — no arithmetic / conversion / estimation.
                "statement": (
                    f"Observation {obs_id} recorded {obs['value']} {obs['unit']} "
                    f"at {obs['location']} (observed {obs['observed_at']})."
                ),
                "subject_ref": obs_id,
                "source_ref": source_ref,
            }
        )

    # --- locational asset-association statements: locational-only, cited 1:1 ---------------------
    for assoc in asset_associations:
        _req(isinstance(assoc, dict), ERR_SCHEMA)
        observation_ref = assoc.get("observation_ref")
        asset_id = assoc.get("asset_id")
        _req(_nonempty_str(observation_ref) and _nonempty_str(asset_id), ERR_SCHEMA)
        _req(assoc.get("relation") == "locational", ERR_SCHEMA)
        _req(isinstance(assoc.get("source_ref"), dict), ERR_SCHEMA)
        subject_ref = {"observation_ref": observation_ref, "asset_id": asset_id}
        source_ref = _resolve_citation(citations, "asset_association", subject_ref, assoc["source_ref"])
        statements.append(
            {
                "kind": "asset_association",
                # Locational vicinity ONLY — never a cause / emission source / leak location.
                "statement": f"Observation {observation_ref} is locationally associated with asset {asset_id}.",
                "subject_ref": subject_ref,
                "source_ref": source_ref,
            }
        )

    # --- methodology-limitation statements: verbatim note text, cited 1:1 to a supplied note -----
    for lim in methodology_limitations:
        _req(isinstance(lim, dict), ERR_SCHEMA)
        text = lim.get("statement")
        _req(_nonempty_str(text), ERR_SCHEMA)
        try:
            source_ref = canonical_source_ref(lim.get("source_ref"))
        except InputContractError as exc:
            raise InputContractError(ERR_SOURCE_CITATION_MISMATCH) from exc
        # Resolve 1:1 to a supplied method note: exactly one note must match BOTH the verbatim text
        # and the canonical source_ref. Zero = missing, more than one = duplicate/ambiguous, a
        # source_ref that matches no note carrying that text = inconsistent → all fail closed.
        matches = [
            note
            for note in supplied_method_notes
            if isinstance(note, dict)
            and note.get("text") == text
            and _safe_canonical_source_ref(note.get("source_ref")) == source_ref
        ]
        _req(len(matches) == 1, ERR_SOURCE_CITATION_MISMATCH)
        statements.append(
            {
                "kind": "methodology_limitation",
                "statement": text,
                "source_ref": source_ref,
            }
        )

    # --- coverage-gap statements: structural basis ONLY, never a source_ref ----------------------
    for gap in coverage_gaps:
        _req(isinstance(gap, dict), ERR_SCHEMA)
        reason = gap.get("reason")
        basis = gap.get("basis")
        _req(_nonempty_str(reason), ERR_SCHEMA)
        _req(isinstance(basis, dict), ERR_SCHEMA)
        statements.append(
            {
                "kind": "coverage_gap",
                "statement": f"Coverage gap: {reason}.",
                "reason": reason,
                "basis": dict(basis),  # structural, non-inferential; NO source_ref
            }
        )

    return {
        "reporting_template": reporting_template,
        "statements": statements,
    }
