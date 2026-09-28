"""AgentCore Platform v1.0 — input-contract validation for ENE-C2-086 SourceIntakeNode.

Deterministic, side-effect-free, framework-free (no agenticstar / framework imports, no I/O).
Validates the supplied-inputs contract per docs/02 (Input Contract & Source-Approval Assurance)
and returns a CANONICAL, JSON-safe validated_input — every object is rebuilt from an allowlist of
known keys (unknown keys are rejected, not carried through), so no unvalidated nested blob reaches
State / the inner GraphNode. Raises InputContractError carrying a non-sensitive error CODE (never
payload content); how that code is reported to the caller is the calling node's decision. v1 is caller-attested /
agent-verified for well-formedness + citability: approval authenticity is NOT re-verified against
any external registry or signature, and no external retrieval / refresh / inference / gap-filling
is performed.
"""

import math
from typing import Any

# Fail-closed error codes (docs/02 error contract). Non-sensitive — safe for error_log.
ERR_SCHEMA = "ERR_SCHEMA"
ERR_UNATTESTED_SOURCE = "ERR_UNATTESTED_SOURCE"
ERR_UNCITABLE = "ERR_UNCITABLE"
ERR_NONLOCATIONAL_RELATION = "ERR_NONLOCATIONAL_RELATION"
ERR_UNKNOWN_OBSERVATION_REF = "ERR_UNKNOWN_OBSERVATION_REF"
ERR_AMBIGUOUS_OBSERVATION_REF = "ERR_AMBIGUOUS_OBSERVATION_REF"
# Raised at cited-brief assembly (and re-checkable at the terminal gate) when a source-derived brief
# statement cannot resolve 1:1 to a supplied source_ref (missing / duplicate / inconsistent citation).
ERR_SOURCE_CITATION_MISMATCH = "ERR_SOURCE_CITATION_MISMATCH"

_REQUIRED_TOP = ("observations", "asset_reference_map", "method_notes", "reporting_template")
# Exact key sets — each object is rebuilt from exactly these (no extra keys smuggled through).
_OBS_KEYS = frozenset({"observation_id", "value", "unit", "observed_at", "location", "source_ref"})
_METHOD_NOTE_KEYS = frozenset({"text", "source_ref"})
_SOURCE_REF_KEYS = frozenset({"source_id", "locator", "approval"})
_APPROVAL_KEYS = frozenset({"attested_by", "attested_at", "approval_ref"})
_ASSET_MAP_KEYS = frozenset({"observation_ref", "asset_id", "relation"})

# Defensive bounds (structural — counts / lengths / nesting, not semantic).
_MAX_ITEMS = 10_000
_MAX_KEY_LEN = 256
_MAX_TEXT_LEN = 20_000
_TEMPLATE_MAX_DEPTH = 8
_TEMPLATE_MAX_NODES = 2_000
# msgpack int64 bound — an arbitrary-precision Python int beyond this is not checkpoint-safe AND
# would raise OverflowError on float conversion (math.isfinite), so it must be rejected by magnitude.
_MAX_ABS_INT = 2**63


def _finite_number(value: Any) -> bool:
    """A JSON number that is checkpoint-safe: a bounded int (never float-converted, so no
    OverflowError), or a finite float. bool is NOT a number here."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) < _MAX_ABS_INT
    if isinstance(value, float):
        return math.isfinite(value)
    return False


class InputContractError(Exception):
    """Carries a non-sensitive fail-closed error CODE (never payload content)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(cond: Any, code: str) -> None:
    if not cond:
        raise InputContractError(code)


def _has_control(text: str, *, allow_ws: bool = False) -> bool:
    """True if the string carries a control character (NUL / C0 / DEL). tab / newline /
    carriage-return are permitted only when allow_ws."""
    for ch in text:
        code_point = ord(ch)
        if code_point == 127 or (code_point < 32 and not (allow_ws and ch in "\t\n\r")):
            return True
    return False


def _clean_str(value: Any, *, allow_ws: bool = False, max_len: int = _MAX_KEY_LEN) -> bool:
    """A non-empty string within max_len and free of control characters. Strict isinstance —
    never str()-coerces, so a decoded ``\\x00`` inside a parsed value is caught."""
    return (
        isinstance(value, str)
        and value.strip() != ""
        and len(value) <= max_len
        and not _has_control(value, allow_ws=allow_ws)
    )


def _exact_keys(obj: Any, allowed: frozenset[str], code: str) -> None:
    """Reject a non-dict, or a dict whose key set is not exactly `allowed` (missing OR extra key)."""
    _require(isinstance(obj, dict) and frozenset(obj.keys()) == allowed, code)


def _canonical_source_ref(source_ref: Any) -> dict[str, Any]:
    """Validate + rebuild a source_ref = {source_id, locator, approval{attested_by, attested_at,
    approval_ref}} into a canonical dict. Citability (source_id + locator) is checked before
    attestation (approval)."""
    _require(isinstance(source_ref, dict), ERR_SCHEMA)
    _require(frozenset(source_ref.keys()) <= _SOURCE_REF_KEYS, ERR_SCHEMA)  # reject extra keys
    # Citability first (a missing source_id / locator makes the source uncitable).
    _require(_clean_str(source_ref.get("source_id")) and _clean_str(source_ref.get("locator")), ERR_UNCITABLE)
    # Attestation — approval object well-formed (missing / invalid → unattested; extra key → schema).
    approval = source_ref.get("approval")
    _require(isinstance(approval, dict), ERR_UNATTESTED_SOURCE)
    _require(frozenset(approval.keys()) <= _APPROVAL_KEYS, ERR_SCHEMA)
    _require(all(_clean_str(approval.get(f)) for f in _APPROVAL_KEYS), ERR_UNATTESTED_SOURCE)
    return {
        "source_id": source_ref["source_id"],
        "locator": source_ref["locator"],
        "approval": {
            "attested_by": approval["attested_by"],
            "attested_at": approval["attested_at"],
            "approval_ref": approval["approval_ref"],
        },
    }


# Public alias — inner nodes that consume/emit a source_ref reuse this single validator to
# re-verify + canonicalize (allowlisted rebuild) the citation they carry, instead of hand-rolling
# a drifting partial check. Raises InputContractError(code) on the first violation.
canonical_source_ref = _canonical_source_ref


def _validate_json_safe(value: Any, depth: int, counter: list[Any]) -> None:
    """Recursively assert JSON/msgpack-safe content within bounds: only str / int / float / bool /
    None / list / dict; depth <= _TEMPLATE_MAX_DEPTH; total nodes <= _TEMPLATE_MAX_NODES; every
    string leaf/key <= _MAX_TEXT_LEN and free of control characters (NUL / C0 / DEL, tab/nl/cr ok);
    floats finite. Any violation → ERR_SCHEMA. Used for reporting_template (open structure)."""
    _require(depth <= _TEMPLATE_MAX_DEPTH, ERR_SCHEMA)
    counter[0] += 1
    _require(counter[0] <= _TEMPLATE_MAX_NODES, ERR_SCHEMA)
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, str):
        _require(len(value) <= _MAX_TEXT_LEN and not _has_control(value, allow_ws=True), ERR_SCHEMA)
    elif isinstance(value, (int, float)):
        _require(_finite_number(value), ERR_SCHEMA)  # bounded int / finite float — no OverflowError
    elif isinstance(value, list):
        for item in value:
            _validate_json_safe(item, depth + 1, counter)
    elif isinstance(value, dict):
        for key, item in value.items():
            _require(isinstance(key, str) and len(key) <= _MAX_KEY_LEN and not _has_control(key), ERR_SCHEMA)
            _validate_json_safe(item, depth + 1, counter)
    else:
        raise InputContractError(ERR_SCHEMA)  # non-JSON-safe type


def validate_and_normalize(payload: Any) -> dict[str, Any]:
    """Validate the supplied-inputs contract and return a CANONICAL, JSON-safe validated_input
    rebuilt from allowlisted keys only. Raises InputContractError(code) on the first violation;
    performs no retrieval / inference / gap-filling. observation_id must be unique; each
    asset_reference_map.observation_ref must resolve to exactly one observation_id; relation must
    be "locational"."""
    _require(isinstance(payload, dict), ERR_SCHEMA)
    for key in _REQUIRED_TOP:
        _require(key in payload, ERR_SCHEMA)

    observations = payload["observations"]
    asset_reference_map = payload["asset_reference_map"]
    method_notes = payload["method_notes"]
    reporting_template = payload["reporting_template"]

    _require(isinstance(observations, list) and 0 < len(observations) <= _MAX_ITEMS, ERR_SCHEMA)
    _require(isinstance(asset_reference_map, list) and len(asset_reference_map) <= _MAX_ITEMS, ERR_SCHEMA)
    _require(isinstance(method_notes, list) and len(method_notes) <= _MAX_ITEMS, ERR_SCHEMA)
    _require(isinstance(reporting_template, dict), ERR_SCHEMA)

    # --- observations: exact keys, typed fields, unique observation_id; rebuilt canonically ---
    observation_ids: set[str] = set()
    canonical_observations: list[Any] = []
    for obs in observations:
        _exact_keys(obs, _OBS_KEYS, ERR_SCHEMA)
        _require(_clean_str(obs["observation_id"]), ERR_SCHEMA)
        value = obs["value"]
        _require(_finite_number(value), ERR_SCHEMA)
        _require(_clean_str(obs["unit"]) and _clean_str(obs["observed_at"]) and _clean_str(obs["location"]), ERR_SCHEMA)
        obs_id = obs["observation_id"]
        _require(obs_id not in observation_ids, ERR_AMBIGUOUS_OBSERVATION_REF)
        observation_ids.add(obs_id)
        canonical_observations.append(
            {
                "observation_id": obs_id,
                "value": value,
                "unit": obs["unit"],
                "observed_at": obs["observed_at"],
                "location": obs["location"],
                "source_ref": _canonical_source_ref(obs["source_ref"]),
            }
        )

    # --- method_notes: exact keys {text, source_ref}; rebuilt canonically --------------------
    canonical_method_notes: list[Any] = []
    for note in method_notes:
        _exact_keys(note, _METHOD_NOTE_KEYS, ERR_SCHEMA)
        _require(_clean_str(note["text"], allow_ws=True, max_len=_MAX_TEXT_LEN), ERR_SCHEMA)
        canonical_method_notes.append(
            {
                "text": note["text"],
                "source_ref": _canonical_source_ref(note["source_ref"]),
            }
        )

    # --- asset_reference_map: locational-only, ref resolves 1:1; rebuilt canonically ---------
    canonical_asset_map: list[Any] = []
    for entry in asset_reference_map:
        _exact_keys(entry, _ASSET_MAP_KEYS, ERR_SCHEMA)  # rejects smuggled attribution / leak keys
        _require(_clean_str(entry["asset_id"]) and _clean_str(entry["observation_ref"]), ERR_SCHEMA)
        _require(entry["relation"] == "locational", ERR_NONLOCATIONAL_RELATION)
        _require(entry["observation_ref"] in observation_ids, ERR_UNKNOWN_OBSERVATION_REF)
        canonical_asset_map.append(
            {
                "observation_ref": entry["observation_ref"],
                "asset_id": entry["asset_id"],
                "relation": "locational",
            }
        )

    # --- reporting_template: open structure → recursively bound + control-char screen ---------
    _validate_json_safe(reporting_template, 0, [0])

    return {
        "observations": canonical_observations,
        "asset_reference_map": canonical_asset_map,
        "method_notes": canonical_method_notes,
        "reporting_template": reporting_template,
    }
