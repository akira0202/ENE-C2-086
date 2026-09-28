# ENE-C2-086 — Unit Tests: caller-facing notices for runs that end without a brief
# (src/services/degradation.py)
#
# A degraded run completes with one of these notices as its output, so each notice is held to the
# same terminal output policy a brief must pass, and none can carry request content: the sentence is
# derived from the allow-listed code alone.

import pytest

from src.services import degradation
from src.services.degradation import DEGRADATION_CODES, explain_degradation
from src.services.input_schema import (
    ERR_AMBIGUOUS_OBSERVATION_REF,
    ERR_NONLOCATIONAL_RELATION,
    ERR_SCHEMA,
    ERR_SOURCE_CITATION_MISMATCH,
    ERR_UNATTESTED_SOURCE,
    ERR_UNCITABLE,
    ERR_UNKNOWN_OBSERVATION_REF,
)
from src.services.output_policy import find_prohibited


def test_every_input_contract_code_the_caller_can_correct_has_a_notice():
    for code in (
        ERR_SCHEMA,
        ERR_UNATTESTED_SOURCE,
        ERR_UNCITABLE,
        ERR_NONLOCATIONAL_RELATION,
        ERR_UNKNOWN_OBSERVATION_REF,
        ERR_AMBIGUOUS_OBSERVATION_REF,
    ):
        assert code in DEGRADATION_CODES


def test_an_internal_consistency_code_is_not_degradable():
    # A citation that fails to resolve after the contract was validated is a defect, not a request
    # the caller can correct — it must stay a fail-closed error.
    assert ERR_SOURCE_CITATION_MISMATCH not in DEGRADATION_CODES


@pytest.mark.parametrize("code", sorted(DEGRADATION_CODES))
def test_every_notice_passes_the_output_policy(code):
    assert find_prohibited(explain_degradation(code)) is None


@pytest.mark.parametrize("code", sorted(DEGRADATION_CODES))
def test_every_notice_is_its_own_sentence(code):
    notice = explain_degradation(code)
    assert notice and not notice.startswith(degradation._FALLBACK)
    assert code not in notice  # an answered code needs no handle appended


def test_withheld_notices_say_nothing_was_released():
    for code in (degradation.BRIEF_WITHHELD, degradation.PERSONAL_DATA_WITHHELD):
        assert "No brief was returned" in explain_degradation(code)


def test_an_unknown_code_falls_back_with_its_handle():
    assert explain_degradation("ERR_SOMETHING_ELSE") == f"{degradation._FALLBACK} [ERR_SOMETHING_ELSE]"
    assert explain_degradation("") == degradation._FALLBACK
