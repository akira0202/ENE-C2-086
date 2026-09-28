"""AgentCore Platform v1.0 — caller-facing wording for runs that end without a brief.

Each outcome here is reported by completing the run with an allow-listed ``error_code`` and a
fixed sentence derived from that code alone. No request value is ever interpolated, so a notice can
never echo caller content back. On such a run ``status=SUCCESS`` means the agent finished handling
the request safely; it does not mean a brief was returned.

Caller-correctable (the request does not meet the input contract): an empty request, a request that
is not JSON or is nested too deeply, and every input-contract code raised by
``src/services/input_schema.py``. Each sentence names what to send instead. Nothing is extracted and
no brief is assembled.

Policy withholding on output: ``BRIEF_WITHHELD`` when the assembled brief would state something
outside what this agent reports (any category of ``src/services/output_policy.py`` other than
injection-style directives), and ``PERSONAL_DATA_WITHHELD`` when it would carry personal data. The
brief is not returned in part or in full; the matched category is recorded in the audit trail only.

Not reported here, and ending as ``status=ERROR`` instead: input refused by the structural S-2
screen, injection-style directives found in the brief, credential-shaped content (the framework's
baseline S-3 scan), and an internally inconsistent run (state a preceding step guarantees is absent
or malformed). None of these is ever represented as a successful completion.
"""

from __future__ import annotations

from src.services.input_schema import (
    ERR_AMBIGUOUS_OBSERVATION_REF,
    ERR_NONLOCATIONAL_RELATION,
    ERR_SCHEMA,
    ERR_UNATTESTED_SOURCE,
    ERR_UNCITABLE,
    ERR_UNKNOWN_OBSERVATION_REF,
)

EMPTY_REQUEST = "ERR_EMPTY_REQUEST"
MALFORMED_JSON = "ERR_MALFORMED_JSON"
TOO_DEEP = "ERR_TOO_DEEP"
BRIEF_WITHHELD = "BRIEF_WITHHELD"
PERSONAL_DATA_WITHHELD = "PERSONAL_DATA_WITHHELD"

_SHAPE = (
    "Send a JSON object with observations, asset_reference_map, method_notes and "
    "reporting_template, each object carrying only its documented keys."
)

# Each notice is released as the output, so each is worded to pass the same output policy a brief
# must pass — none names a withheld category.
_MESSAGES: dict[str, str] = {
    EMPTY_REQUEST: f"No request content was received. {_SHAPE}",
    MALFORMED_JSON: "The request is not valid JSON. Check for a missing quote, comma, or brace, then send it again.",
    TOO_DEEP: "The request is nested too deeply. Flatten the structure and send it again.",
    ERR_SCHEMA: f"The request does not match the documented shape. {_SHAPE}",
    ERR_UNATTESTED_SOURCE: (
        "A source reference has no complete approval record. Every source_ref needs an approval "
        "object with attested_by, attested_at and approval_ref."
    ),
    ERR_UNCITABLE: "A source reference cannot be cited. Every source_ref needs a non-empty source_id and locator.",
    ERR_NONLOCATIONAL_RELATION: (
        'Every asset_reference_map entry must have relation "locational"; this agent records '
        "locational associations only."
    ),
    ERR_UNKNOWN_OBSERVATION_REF: (
        "An asset_reference_map entry refers to an observation_ref that matches no observation_id in observations."
    ),
    ERR_AMBIGUOUS_OBSERVATION_REF: (
        "An observation_id appears more than once in observations, so a reference to it cannot "
        "resolve to one observation. Give each observation a unique observation_id."
    ),
    BRIEF_WITHHELD: (
        "No brief was returned. The assembled brief would have gone beyond the locational, "
        "source-cited context this agent reports, so nothing in it was released. Check the wording "
        "of the supplied method notes and reporting template."
    ),
    PERSONAL_DATA_WITHHELD: (
        "No brief was returned. The assembled brief would have carried personal data, so nothing in "
        "it was released. Send the request without personal information."
    ),
}

# Every code this module answers. A node degrades only with one of these; anything else is a defect.
DEGRADATION_CODES = frozenset(_MESSAGES)

_FALLBACK = "The request could not be completed and no brief was produced."


def explain_degradation(code: str) -> str:
    """Return one caller-facing sentence for a degradation code."""
    return _MESSAGES.get(code, f"{_FALLBACK} [{code}]" if code else _FALLBACK)
