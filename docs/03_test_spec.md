# Test Specification

## Test Strategy

- **Test types**: Unit (per node + State + graph wiring), Proof-of-Boundary (framework contract),
  Integration (compiled-graph `agent.invoke()` E2E).
- **Coverage**: numeric line coverage is **not collected or gated** by the current `run-tests` job —
  it runs `pytest tests/ -v --tb=short` and `pytest tests/proof_of_boundary/ -v --tb=short`, with no
  `--cov` / `--cov-report` (`pytest-cov` is only a dev dependency). The acceptance evidence for this
  template is a **green `run-tests` + `gate-stub-check`** plus the mandatory TC / PB / BL matrices
  below, each traced to a real test function. **Coverage status:** TC-01–TC-10 and the asserted part
  of TC-11 are covered by real tests now; the **only** items not yet independently asserted are the
  two S-4 domain-event assertions marked **[assertion pending]** in TC-11 and the S-4 evidence map
  (`SourceIntakeNode` success and `InputHydrateNode`), deferred to the follow-up test-implementation
  stage. Adding `--cov` with a threshold to the shared CI would be a separate CI-definition change,
  out of this docs-only scope.
- **Determinism**: the v1 core path is supplied-only / deterministic / offline (no LLM, DB, vector
  store, or external API), so every case below is reproducible without live infrastructure.

## Outcome Contract (traced from `docs/02` §Security & Error Handling)

This template has exactly **three terminal outcomes** (`docs/02` §Outcome Classification). Its one
content output is a cited context brief; it has **no comparison / branching outcome** (there is no
"comparable-metrics" or verdict branch to model).

| Outcome | Trigger | Terminal State |
|---------|---------|----------------|
| **Safe cited brief** | every stage and the terminal S-3 gate pass | `status = success`; `formatted_output` carries the single cited context brief (per-statement citations, declared limitations/gaps) |
| **Completed without a brief (notice)** | a request the caller can correct — empty / non-JSON / too-deep request or an input-contract violation (`SourceIntakeNode`; the inner workflow is not run) — or a brief withheld by the terminal S-3 gate for a scope category or PII (`OutputGateNode`) | `status = success`, `error_code` = the allow-listed code, `result = None`, `formatted_output` = the fixed notice for the code; **no brief and no request content** |
| **Fail-closed (no output)** | structural S-2 screen, injection-derived text in the brief, inner-node error (short-circuit → `SubgraphError`), citation mismatch (`CitedBriefAssembleNode`), credential-shaped content | `status = error`, `result = None`, `formatted_output = None`; **no caller-facing output, no partial brief**; `error_log` carries only a non-sensitive code |

The brief is returned only when the whole pipeline and the terminal S-3 gate pass; it is never
returned in part.

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Traced test(s) |
|-------|------|----------------|----------------|
| TC-01 | State contract: flat TypedDict, JSON-safe only | No Pydantic/dataclass; primitives/containers only | `tests/unit/test_state_schema.py::test_annotations_are_json_safe_containers`, `::test_no_credential_or_raw_object_fields`, `::test_minimal_examples_are_serializable` |
| TC-02 | `SecurityViolationError` fires on insufficient trust; invalid input fails closed | S-1 refuses before `execute()`; the structural S-2 screen → `status:error`; contract violations → the notice (BL-02–08) | `tests/unit/test_source_intake_node.py::test_s1_refuses_insufficient_trust`, `::test_s2_gate_rejects_structural`; the BL-02–08 input-contract cases |
| TC-03 | No JWT / credential in State or `src/` | CI `gate-credential-scan`: 0 violations | CI job `gate-credential-scan` (pipeline gate; no in-repo test) |
| TC-04 | `InvocationContext` not stored in State; built via `from_state()` | No `context` / `invocation_context` field in State; `GraphNode` uses `InvocationContext.from_state()` | `tests/unit/test_state_schema.py::test_no_credential_or_raw_object_fields` (forbidden `context`/`invocation_context` fields) |
| TC-05 | S-4: no duplicate lifecycle events inside `execute()` | `node_start`/`node_complete`/`node_error` not emitted (nor duplicated) inside `execute()`; domain event exactly-once **where asserted** (S-4 map — SourceIntake-success / InputHydrate pending) | See the **S-4 event evidence map** below (concrete per-node refs + scope note) |
| TC-06 | S-2: `_security_gate_input()` is `@final` (not overridable) | `TypeError` at class definition if overridden | `tests/unit/test_framework_compliance_tc06_tc07.py::TestFunctionNodeFinalSecurityGates::test_tc06_security_gate_input_cannot_be_overridden` |
| TC-07 | S-3: `_security_gate_output()` is `@final` (not overridable) | `TypeError` at class definition if overridden | `tests/unit/test_framework_compliance_tc06_tc07.py::TestFunctionNodeFinalSecurityGates::test_tc07_security_gate_output_cannot_be_overridden` |
| TC-08 | `required_trust_level` declared and enforced at `__call__` | Insufficient trust → refused before `execute()` | `tests/unit/test_source_intake_node.py::test_required_trust_level_declared`, `::test_s1_refuses_insufficient_trust`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_anonymous_caller_produces_no_output` |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial (structural screen) | Domain structural screen (non-`str` / NUL / control-char / oversized) runs in the hook | `tests/unit/test_source_intake_node.py::test_s2_gate_rejects_structural` |
| TC-10 | S-3: domain output check present | Terminal S-3 is `OutputGateNode.execute()` (design choice — a node-delta hook cannot clear the whole brief; see `docs/02` DDR *S-3 terminal gate placement*), **not** `_extra_security_gate_output()`. Covered by BL-09–13 + the PII block cases | `tests/unit/test_output_gate_node.py::test_deny_each_prohibited_category`, `::test_pii_in_statement_value_is_blocked` |
| TC-11 | S-4: ≥1 domain `emit_trace_event()` inside each `execute()` | Domain event emitted in `execute()` (contract for every node); **test evidence** per the S-4 map — directly asserted for the 4 workflow/output nodes (success+reject) + SourceIntake reject; SourceIntake-success / InputHydrate assertions pending | See the **S-4 event evidence map** below; framework lifecycle order for all nodes by `tests/proof_of_boundary/test_pb_invoke_order.py::TestInvokeOrder::test_call_order_for_every_node` |

### S-4 event evidence map

Per-node evidence for the S-4 domain `emit_trace_event()`. The framework `node_start` / `node_complete`
lifecycle is covered for **every** node by PB-6. A node with a dedicated emit-spy test additionally
proves its **domain** event fires exactly once on the noted path(s). Where a domain-event path is not
yet independently asserted, it is marked **[assertion pending]** — the code emits it, but the dedicated
spy test is deferred to the follow-up test-implementation stage; this table does not claim proof it
does not yet have.

- **`ObservationAssetExtractNode`** — success **and** reject: `tests/unit/test_observation_asset_extract_node.py::test_success_emits_exactly_one_domain_event`, `::test_reject_emits_exactly_one_domain_event_and_leaks_nothing`
- **`LimitGapAnalysisNode`** — success **and** reject: `tests/unit/test_limit_gap_analysis_node.py::test_success_emits_exactly_one_domain_event`, `::test_reject_emits_one_event_and_leaks_nothing`
- **`CitedBriefAssembleNode`** — success **and** reject: `tests/unit/test_cited_brief_assemble_node.py::test_success_emits_one_event`, `::test_reject_emits_one_event_and_leaks_nothing`
- **`OutputGateNode`** — pass, withhold **and** block: `tests/unit/test_output_gate_node.py::test_pass_emits_one_event`, `::test_withhold_emits_one_event`, `::test_block_emits_one_event`
- **`SourceIntakeNode`** — contract-violation path (`source_intake_degraded`): domain event spied (and proven non-leaking) by `tests/unit/test_source_intake_node.py::test_reject_does_not_leak_payload`. **Success path (`source_intake` event): [assertion pending]** — emitted in `execute()` but not yet independently spied (`test_valid_input_passes_through` asserts the output contract, not the event).
- **`InputHydrateNode`** — **[assertion pending]** — no dedicated unit test yet; the `hydrate` / `hydrate_rejected` domain-event exactly-once is not independently asserted. Its framework lifecycle order is covered by PB-6, and its `execute()` is reached end-to-end by `tests/integration/test_graph_invoke_e2e.py::test_invoke_valid_reaches_success_brief`.
- **All nodes** — framework `node_start` → … → `node_complete` presence and order: `tests/proof_of_boundary/test_pb_invoke_order.py::TestInvokeOrder::test_call_order_for_every_node`.

> **Scope note:** for `SourceIntakeNode` (success) and `InputHydrateNode` the domain-event
> exactly-once assertion is **pending** (deferred to the follow-up test-implementation stage). TC-05,
> TC-11 and PB-1 below are scoped accordingly — they do not assert "all domain events exactly once"
> for those two nodes until the spy tests land.

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Expected Result | Traced test(s) |
|-------|----------|----------------|----------------|
| PB-1 | BaseNode → AuditLogger | Framework lifecycle events fire for every node (no silent failures); per-node **domain** events per the S-4 map (SourceIntake-success / InputHydrate assertions pending) | `tests/proof_of_boundary/test_pb_invoke_order.py::TestInvokeOrder::test_call_order_for_every_node` (asserts `node_start` … `node_complete` for every node); per-node domain events in the **S-4 event evidence map** above |
| PB-2 | State serialization | Post-invoke State is primitives/JSON-safe only | `tests/proof_of_boundary/test_state_safety.py::TestStateSafety::test_state_file_safety`; `tests/unit/test_state_schema.py::test_annotations_are_json_safe_containers`, `::test_minimal_examples_are_serializable` |
| PB-3 | L1 → External service | **N/A — no external service in scope.** v1 is supplied-only / deterministic / offline: no LLM, DB, vector store, or external API on the core path (`docs/02` DDR *External data: Supplied only*). No external boundary exists to exercise; the deterministic path is covered by PB-6 and the BL cases. | — (N/A) |
| PB-4 | Import isolation | AST scan: 0 Level-0 imports | `tests/proof_of_boundary/test_import_isolation.py::TestImportIsolation::test_no_prohibited_imports_in_src` |
| PB-5 | Checkpoint safety *(conditional)* | **Auto-waived — checkpointing disabled.** `config/config.yaml` enables neither `memory_enabled` nor `hitl.enabled`, so no checkpointer is attached; the State declaration itself carries no JWT/Pydantic/raw object | `tests/proof_of_boundary/test_state_safety.py::test_pb5_precheckpoint_ingress_not_raw` (auto-skipped — checkpointing disabled), `::TestStateSafety::test_state_file_safety`; `tests/unit/test_state_schema.py::test_no_credential_or_raw_object_fields` |
| PB-6 | Invoke execution order | `__call__()`: S-1 → S-4 `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → S-4 `node_complete` | `tests/proof_of_boundary/test_pb_invoke_order.py::TestInvokeOrder::test_call_order_for_every_node` |
| PB-7 | HITL interrupt propagation *(conditional)* | **Auto-waived — non-HITL.** `config/config.yaml` sets no `hitl.enabled: true` (HITL absent → disabled) and the template provisions no checkpointer (`memory_enabled` false); `docs/01` / `docs/02` declare a read-only, non-HITL, deterministic template. The scaffold PB-7 test auto-skips (`pytest.mark.skipif`) when `config/config.yaml` lacks `hitl.enabled: true`. | `tests/proof_of_boundary/test_pb7_hitl_interrupt_propagation.py` (auto-skipped — non-HITL) |

> **PB gate checklist:** PB-1, PB-2, PB-4, PB-6 are mandatory and covered above. **PB-3 is N/A**
> (no external service in scope). **PB-5 is Auto-waived — checkpointing disabled** and **PB-7 is
> Auto-waived — non-HITL**; neither blocks the gate.

## Business Logic Tests

> Security & input-contract acceptance tests traced from `docs/02`: the declared input-contract
> codes, each completing with its notice (BL-01–08, except the citation mismatch BL-07, which fails
> closed), the terminal S-3 withholding and the locational-only allow-case (BL-09–13), S-2 structural
> sanitization + raw-PII non-exposure (BL-14), methodology-limitation citation integrity (BL-15), the
> graph-composition / caller-boundary contract (BL-16–17), injection-derived output (BL-18) and the
> notices themselves (BL-19). Each row cites the specific test function for its outcome.

| BL-ID | Test | Input | Expected Result | Traced test(s) |
|-------|------|-------|----------------|----------------|
| BL-01 | Valid `observation_ref` resolves 1:1 → cited brief | payload where every `asset_reference_map.observation_ref` matches exactly one unique `observations[].observation_id` | each association resolves to its observation and carries that observation's `source_ref`; citation 1:1 preserved; `status = success` | `tests/unit/test_source_intake_node.py::test_valid_input_passes_through`; `tests/unit/test_observation_asset_extract_node.py::test_valid_extraction_is_value_invariant_and_inherits_source_ref`, `::test_every_emitted_item_has_a_citation_tracing_to_a_supplied_source_ref`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_valid_reaches_success_brief` |
| BL-02 | Unknown `observation_ref` → notice | `observation_ref` matching no `observation_id` | `status = success`, `error_code = ERR_UNKNOWN_OBSERVATION_REF`, output = the fixed notice; no brief, inner workflow not run | `tests/unit/test_source_intake_node.py::test_unknown_observation_ref`; `tests/proof_of_boundary/test_pb_input_extraction_boundary.py::test_input_contract_failclose_no_caller_output`; `tests/unit/test_observation_asset_extract_node.py::test_unresolved_observation_ref_rejected` |
| BL-03 | Duplicate / ambiguous `observation_id` → notice | duplicate `observation_id` | `status = success`, `error_code = ERR_AMBIGUOUS_OBSERVATION_REF`, output = the fixed notice; no brief, inner workflow not run | `tests/unit/test_source_intake_node.py::test_duplicate_observation_id`; `tests/proof_of_boundary/test_pb_input_extraction_boundary.py::test_input_contract_failclose_no_caller_output`; `tests/unit/test_observation_asset_extract_node.py::test_duplicate_observation_id_rejected` |
| BL-04 | Unattested source → notice | `source_ref` lacking well-formed `approval` | `status = success`, `error_code = ERR_UNATTESTED_SOURCE`, output = the fixed notice; no brief, inner workflow not run | `tests/unit/test_source_intake_node.py::test_unattested_source`; `tests/proof_of_boundary/test_pb_input_extraction_boundary.py::test_input_contract_failclose_no_caller_output`; `tests/unit/test_limit_gap_analysis_node.py::test_note_source_ref_missing_approval_rejected` |
| BL-05 | Uncitable source → notice | `source_ref` missing `source_id` or `locator` | `status = success`, `error_code = ERR_UNCITABLE`, output = the fixed notice; no brief, inner workflow not run | `tests/unit/test_source_intake_node.py::test_uncitable_source`; `tests/proof_of_boundary/test_pb_input_extraction_boundary.py::test_input_contract_failclose_no_caller_output`; `tests/unit/test_limit_gap_analysis_node.py::test_note_source_ref_empty_source_id_rejected`, `::test_note_source_ref_missing_locator_rejected` |
| BL-06 | Non-locational relation → notice | `asset_reference_map` entry with `relation != "locational"` | `status = success`, `error_code = ERR_NONLOCATIONAL_RELATION`, output = the fixed notice; no brief, inner workflow not run | `tests/unit/test_source_intake_node.py::test_nonlocational_relation`; `tests/proof_of_boundary/test_pb_input_extraction_boundary.py::test_input_contract_failclose_no_caller_output`; `tests/unit/test_observation_asset_extract_node.py::test_nonlocational_relation_rejected` |
| BL-07 | Observation/association statement-to-source mismatch → fail-closed | a brief statement that cannot resolve 1:1 to a supplied citation | `ERR_SOURCE_CITATION_MISMATCH`, `status = error`, `result`/`formatted_output = None`, no partial brief | `tests/unit/test_cited_brief_assemble_node.py::test_missing_citation_rejected`, `::test_duplicate_citation_rejected`, `::test_inconsistent_citation_source_ref_rejected`, `::test_missing_association_citation_rejected` |
| BL-08 | Malformed / missing field / bad number / not the documented JSON → notice | missing required field, type violation, control char, huge int / NaN / ±Inf; empty, plain-text (non-JSON) or too-deep request | `ERR_SCHEMA` / `ERR_EMPTY_REQUEST` / `ERR_MALFORMED_JSON` / `ERR_TOO_DEEP`: `status = success`, output = the fixed notice, no `validated_input`, no brief; a code with no notice fails closed instead | `tests/unit/test_source_intake_node.py::test_schema_missing_required_field`, `::test_schema_wrong_type_value`, `::test_schema_control_character`, `::test_schema_numeric_boundary_rejected`, `::test_schema_empty_and_malformed_input`, `::test_an_unanswerable_code_is_not_degraded`; `tests/proof_of_boundary/test_pb_input_extraction_boundary.py::test_a_request_that_is_not_the_documented_json_gets_the_notice` |
| BL-09 | S-3 withholds hedged asset attribution | brief containing hedged attribution ("emissions likely originate from asset-X") | `OutputGateNode` withholds: `status = success`, `error_code = BRIEF_WITHHELD`, `result = None`, `formatted_output` = the fixed notice, no part of the brief | `tests/unit/test_output_gate_node.py::test_hedged_attribution_is_blocked_even_though_locational_is_allowed`, `::test_deny_each_prohibited_category`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_s3_block_on_prohibited_phrasing_yields_no_output` |
| BL-10 | S-3 withholds leak identification | brief that identifies a leak / names an emission source | `OutputGateNode` withholds: `status = success`, `error_code = BRIEF_WITHHELD`, `result = None`, `formatted_output` = the fixed notice, no part of the brief | `tests/unit/test_output_gate_node.py::test_deny_each_prohibited_category` (leak & explicit-attribution cases) |
| BL-11 | S-3 withholds estimation beyond supplied | brief that estimates / extrapolates emissions | `OutputGateNode` withholds: `status = success`, `error_code = BRIEF_WITHHELD`, `result = None`, `formatted_output` = the fixed notice, no part of the brief | `tests/unit/test_output_gate_node.py::test_deny_each_prohibited_category` (extrapolated-emissions case) |
| BL-12 | S-3 withholds breach-report / field-work / asset-control | brief that reports a regulatory breach, initiates field work, or controls an asset (also in a template key) | `OutputGateNode` withholds: `status = success`, `error_code = BRIEF_WITHHELD`, `result = None`, `formatted_output` = the fixed notice, no part of the brief | `tests/unit/test_output_gate_node.py::test_deny_each_prohibited_category` (breach / field-work / energy-control cases), `::test_prohibited_phrase_in_template_key_is_blocked` |
| BL-13 | S-3 allows locational-only (false-positive guard) | brief using locational-only phrasing with valid citations | passes S-3: `status = success`, cited brief in `formatted_output` | `tests/unit/test_output_gate_node.py::test_clean_locational_brief_passes`, `::test_locational_association_phrase_is_allowed`, `::test_clean_brief_passes_real_pii_detector`; `tests/integration/test_graph_invoke_e2e.py::test_invoke_valid_reaches_success_brief` |
| BL-14 | S-2 structural sanitization & raw-PII non-exposure | free-text leaves with NUL / control chars / oversized payload; and PII-bearing content | (a) NUL / control-char / oversized free-text is rejected fail-closed by the S-2 **structural** screen (`status = error`, no output); (b) **raw PII never appears in caller output / `error_log` / trace events** — rejected and withheld runs carry only a non-sensitive code; (c) PII is processed by the framework **baseline S-2 input gate per the framework's own definition** (not asserted here as a `validated_input` masking guarantee, so the spec is robust to framework implementation differences), and the terminal S-3 gate withholds a brief carrying PII (`PERSONAL_DATA_WITHHELD`). The node performs structural sanitization only — no v1 injection defense (no LLM boundary). | Structural: `tests/unit/test_source_intake_node.py::test_schema_control_character`, `::test_s2_gate_rejects_structural`. No-raw-leak: `tests/unit/test_source_intake_node.py::test_reject_does_not_leak_payload`; `tests/unit/test_output_gate_node.py::test_block_clears_output_and_does_not_leak_content`. Output-side PII withholding: `tests/unit/test_output_gate_node.py::test_pii_in_statement_value_is_blocked`, `::test_pii_in_reporting_template_key_or_leaf_is_blocked`; `tests/proof_of_boundary/test_pb_input_extraction_boundary.py::test_pii_in_brief_blocked_at_outer_boundary` |
| BL-15 | Methodology-limitation citation exact-one (missing / duplicate / mismatch) → fail-closed | a `method_notes`-derived limitation whose `(statement, source_ref)` does not resolve to exactly one supplied method note | fail-closed at assemble: `ERR_SOURCE_CITATION_MISMATCH`, `status = error`, `result` / `formatted_output = None`, no partial brief | `tests/unit/test_cited_brief_assemble_node.py::test_limitation_citation_missing_from_supplied_notes_rejected`, `::test_limitation_citation_duplicate_in_supplied_notes_rejected`, `::test_limitation_citation_source_ref_inconsistent_rejected`, `::test_limitation_without_valid_source_ref_rejected` |
| BL-16 | Graph projection: inner working State never crosses the boundary | inner State carrying `validated_input` / `observations` / `asset_associations` / `methodology_limitations` / `coverage_gaps` / `citations` / `context_brief` | inner `get_output()` and `merge_output()` surface only `result` + `status`; no inner working field is projected outward | `tests/unit/test_graph_composition.py::test_inner_get_output_is_allowlisted_and_leaks_no_working_state`, `::test_merge_output_maps_only_result_and_status_no_leak` |
| BL-17 | Caller-boundary `agent.invoke()` outcomes | valid + `VERIFIED_EXTERNAL`; `ANONYMOUS` caller; inner-node error; terminal S-3 withholding | valid → `status = success`, cited brief published; `ANONYMOUS` → refused, no output; inner error → `SubgraphError` → outer finalize (post_process skipped), no output / no leak; S-3 withholding → the notice, nothing of the brief — and the notice is what the framework's terminal normalisation delivers | `tests/integration/test_graph_invoke_e2e.py::test_invoke_valid_reaches_success_brief`, `::test_invoke_anonymous_caller_produces_no_output`, `::test_invoke_inner_error_yields_no_caller_output`, `::test_invoke_s3_block_on_prohibited_phrasing_yields_no_output`; `tests/proof_of_boundary/test_pb_input_extraction_boundary.py::test_prohibited_phrasing_blocked_at_outer_boundary`; `tests/proof_of_boundary/test_pb_output_boundary.py::test_s3_block_leaves_no_blocked_body_in_response_or_audit` |
| BL-18 | Injection-derived text in the brief → fail-closed | brief carrying an instruction addressed to the agent ("ignore previous instructions …"), alone or together with a scope category | `status = error`, `result` / `formatted_output = None`, no output; never reported as merely withheld | `tests/unit/test_output_gate_node.py::test_injection_derived_text_fails_closed_as_an_error`, `::test_injection_is_never_reported_as_merely_withheld`; `tests/proof_of_boundary/test_pb_input_extraction_boundary.py::test_injection_derived_text_blocked_at_outer_boundary` |
| BL-19 | The notices themselves | every allow-listed code | each notice is its own sentence derived from the code alone, passes the same output policy a brief must pass, and carries no request content; a degraded request reaches `post_process` as the notice for its code; an unknown code falls back with its handle | `tests/unit/test_degradation.py` (all), `tests/unit/test_output_gate_node.py::test_degraded_request_returns_the_notice_for_its_code` |

## Test Execution Summary

> Counts from a full run of this branch against `agenticstar-agentcore` 1.0.3 (the version the
> container image installs). Estimates and other-branch counts are not used.

- **Full suite** (`python -m pytest tests/`): **302 passed, 3 skipped**. Breakdown:
  - **Unit** (`tests/unit/`): **268 passed, 0 skipped**.
  - **Proof-of-Boundary** (`tests/proof_of_boundary/`): **25 passed, 3 skipped** — the skips are the
    two PB-7 cases (`test_pb7_hitl_interrupt_propagates`, `test_pb7_hitl_allowed_false_skips_interrupt`),
    auto-skipped — non-HITL, and the PB-5 case (`test_pb5_precheckpoint_ingress_not_raw`),
    auto-skipped — checkpointing disabled.
  - **Integration** (`tests/integration/`): **9 passed** — the compiled-graph `agent.invoke()` E2E
    against the real framework; it `importorskip`s where that runtime is absent.
- No `--cov` is run (see Test Strategy → Coverage).
