"""AgentCore Platform v1.0 — terminal S-3 output policy for ENE-C2-086.

Deterministic, side-effect-free, framework-free. Defines the DENY policy for the terminal S-3 gate
(`OutputGateNode`): an explicit, category-by-category prohibition scanned over every string leaf/key
of the assembled brief. This is the final defence line — assembly uses safe fixed templates, so the
policy MUST NOT be relied on to "fix" an unsafe brief; the gate releases none of it instead. A scope
category withholds the brief (the run completes with a fixed notice); `injection_derived` is a
security failure and fails the run closed as an error.

Prohibited categories (block on any match, in either phrasing — explicit or hedged):
  - leak_identification        — identifying / locating a methane leak
  - asset_attribution          — attributing emissions / a leak / a cause to an asset (incl. hedged,
                                 e.g. "emissions likely originate from asset-X"); locational-only
                                 phrasing ("... is locationally associated with asset-X") is ALLOWED
  - extrapolated_emissions     — estimating / extrapolating / averaging emissions beyond supplied values
  - regulatory_breach          — asserting a regulatory breach or directing a report to an authority
  - field_work_initiation      — initiating field work / a site inspection
  - energy_asset_control       — directing control of an energy asset (shutdown / valve / etc.)
  - injection_derived          — prompt-injection-style directives echoed into output (v1 has no LLM
                                 sink, but the guard is kept as defence-in-depth)

Credential and PII output are NOT re-implemented here (the framework substrate already provides those
detectors — do not hand-roll one): credentials are blocked by the framework baseline `@final` S-3
credential scan that runs on every node's output; input PII is masked upstream by the baseline S-2
input gate. This module owns only the domain-semantic prohibitions above.
"""

import re
from typing import Any, Iterator

# Non-sensitive fail-closed code for a terminal S-3 prohibited-output block.
ERR_PROHIBITED_OUTPUT = "ERR_PROHIBITED_OUTPUT"
# The one category that is a security failure rather than a scope policy: an instruction addressed to
# the agent found in the brief fails closed as an error; every other category withholds the brief.
INJECTION_DERIVED = "injection_derived"

# `[^.]*` keeps a match within a single sentence, so an attribution term in one statement cannot
# "reach across" a sentence boundary into an unrelated locational statement.
_DENY_RULES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "leak_identification",
        (
            re.compile(r"\bleak(s|ed|ing|age)?\b", re.I),
            re.compile(r"\bfugitive\s+emission", re.I),
        ),
    ),
    (
        "asset_attribution",
        (
            # asset ↔ attribution term (source / origin / cause / responsible / attribute / emit) — either order
            re.compile(
                r"\basset\b[^.]*\b(source|origin\w*|cause[sd]?|responsib\w*|attribut\w*|emit\w*|emission[s]?)\b", re.I
            ),
            re.compile(r"\b(source|origin\w*|cause[sd]?|responsib\w*|attribut\w*|emission[s]?)\b[^.]*\basset\b", re.I),
            # attribution terminology on emissions themselves (e.g. "emission source attribution")
            re.compile(r"\bemission[s]?\s+(source|origin\w*|attribut\w*)\b", re.I),
            # hedged attribution: emission tied to a location/asset via likely/probable/possible/from/suggest
            re.compile(r"\bemission[s]?\b[^.]*\b(from|likely|probabl\w*|possibl\w*|may\b|could\b|suggest\w*)\b", re.I),
        ),
    ),
    (
        "extrapolated_emissions",
        (
            re.compile(
                r"\b(estimat\w*|extrapolat\w*|project\w*|infer\w*|calculat\w*|comput\w*|deriv\w*)\b[^.]*\b(emission[s]?|flux|rate|total|volume|amount)\b",
                re.I,
            ),
            re.compile(
                r"\b(emission[s]?|flux)\b[^.]*\b(estimat\w*|extrapolat\w*|project\w*|total|average|mean)\b", re.I
            ),
            re.compile(r"\baverage\b[^.]*\b(value|concentration|reading|observation)\b", re.I),
        ),
    ),
    (
        "regulatory_breach",
        (
            re.compile(r"\bbreach\b", re.I),
            re.compile(
                r"\b(regulatory|compliance|statutory|legal|permit)\b[^.]*\b(violat\w*|exceed\w*|non-?compliance)\b",
                re.I,
            ),
            re.compile(r"\bviolat\w*\b[^.]*\b(regulat\w*|limit|threshold|standard|permit)\b", re.I),
            re.compile(
                r"\b(report|notif\w*|escalat\w*)\b[^.]*\b(authorit\w*|regulator\w*|agency|government|ministry)\b", re.I
            ),
        ),
    ),
    (
        "field_work_initiation",
        (
            re.compile(r"\bfield\s?work\b", re.I),
            re.compile(r"\bsite (visit|inspection|survey)\b", re.I),
            re.compile(
                r"\b(initiat\w*|dispatch\w*|schedul\w*|commenc\w*|deploy\w*|send\b)\b[^.]*\b(team|crew|inspector|inspection|survey|field|site)\b",
                re.I,
            ),
        ),
    ),
    (
        "energy_asset_control",
        (
            re.compile(r"\b(shut\s?down|shut\s?off|shutdown)\b", re.I),
            re.compile(
                r"\b(stop|halt|disabl\w*|clos\w*|throttl\w*|isolat\w*|activat\w*|deactivat\w*|adjust|control|restart|reboot)\b[^.]*\b(asset|valve|compressor|pipeline|well|unit|pump|station|equipment|facility)\b",
                re.I,
            ),
        ),
    ),
    (
        "injection_derived",
        (
            re.compile(r"\b(ignore|disregard|override)\b[^.]*\b(instruction|prompt|context|rule)s?\b", re.I),
            re.compile(r"\bsystem prompt\b", re.I),
        ),
    ),
)


def _string_leaves(value: Any) -> Iterator[str]:
    """Yield every string leaf AND every string dict key, recursing dict / list / tuple. Keys are
    included because a supplied `reporting_template` section name is caller-controlled content."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _string_leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _string_leaves(item)


def find_prohibited(brief: Any, categories: tuple[str, ...] | None = None) -> str | None:
    """Return the category slug of the FIRST prohibited match found anywhere in the brief, or None if
    the brief is clean. The returned slug is non-sensitive (a category name, never brief content).
    `categories` restricts the scan to those slugs — the gate asks about `INJECTION_DERIVED` on its
    own first, because it is reported differently from the rest."""
    for leaf in _string_leaves(brief):
        for category, patterns in _DENY_RULES:
            if categories is not None and category not in categories:
                continue
            for pattern in patterns:
                if pattern.search(leaf):
                    return category
    return None


def contains_pii(brief: Any, detector: Any) -> bool:
    """True if the injected substrate PII `detector` flags any string leaf/key of the brief. The
    detector is passed in (dependency injection) so this module stays framework-free; the caller
    supplies the substrate `framework.security.detect_pii`. A truthy detector result (e.g. a
    non-empty findings list) on any leaf means PII is present. Only str leaves are passed, so the
    detector's non-str TypeError contract is never triggered."""
    return any(detector(leaf) for leaf in _string_leaves(brief))
