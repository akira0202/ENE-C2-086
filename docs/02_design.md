# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: EnergyMethaneObservationContextBriefGraph
- **L1 Base**: AgentBaseGraph
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

This is a **Cat 2** template (L1-direct on `AgentBaseGraph`). Domain complexity is hidden inside
the `main` slot via a `GraphNode` that wraps an inner `BaseGraph` (`EvidenceWorkflowGraph`). The
outer backbone is the fixed framework pipeline; `add_edges()` is **not** overridden on the outer
graph. It is read-only and produces a cited internal context brief for qualified human analysis;
it never identifies leaks, attributes emissions to an asset, estimates emissions beyond supplied
values, initiates field work, reports a regulatory breach, or controls an energy asset.

## Architecture Overview

### Node Configuration

**Outer graph — `EnergyMethaneObservationContextBriefGraph(AgentBaseGraph)`** (backbone fixed; `add_edges()` not overridden)

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | Framework init | — | — | InitializeNode (default) |
| pre_process | `SourceIntakeNode` — untrusted-input boundary: parse `user_input` (JSON string) into the supplied inputs, enforce the input schema and the **Input Contract & Source-Approval Assurance** (caller-attested, agent-verified citability), S-2 screen free-text; a request that breaks the contract (unattested/uncitable/non-locational/malformed) completes with an allow-listed `error_code` and no `validated_input` (see **Outcome Classification**), with no retrieval/refresh/inference | `user_input` | `validated_input` or `error_code`, `status` | FunctionNode → override `execute()` |
| main | `EvidenceWorkflowGraphNode` (GraphNode) — run the inner evidence workflow; `extract_input()` → JSON string of `validated_input`; `merge_output()` → outer `result`. When `error_code` is set the inner workflow is skipped (nothing was validated to extract) | `validated_input`, `error_code` | `result`, `status` | GraphNode → `get_subgraph`/`extract_input`/`merge_output` (+ `execute()` guard) |
| post_process | `OutputGateNode` — terminal S-3 output gate over the assembled brief; on pass set `formatted_output` to the brief; on a degraded request, a scope-policy match or PII set `formatted_output` to the fixed notice for the `error_code`; on injection-derived text fail-closed | `result`, `error_code` | `formatted_output`, `error_code`, `status` | FunctionNode → override `execute()` |
| finalize | Framework finalize | — | — | FinalizeNode (default) |

**Inner graph — `EvidenceWorkflowGraph(BaseGraph)`** (linear topology via `add_edges()`)

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| input_hydrate | `InputHydrateNode` — parse inner `user_input` (JSON string handed from the outer graph) back into `validated_input` | `user_input` | `validated_input`, `status` | FunctionNode → override `execute()` |
| observation_asset_extract | `ObservationAssetExtractNode` — extract supplied observation values and **locational-only** asset associations; each association resolves its `observation_ref` to the single matching `observation_id` and carries that observation's `source_ref` as its citation anchor; never identify a leak or attribute emissions | `validated_input` | `observations`, `asset_associations`, `citations`, `status` | FunctionNode → override `execute()` |
| limit_gap_analysis | `LimitGapAnalysisNode` — deterministic methodology limitations (from the supplied `method_notes`, read from `validated_input`) + coverage gaps (from `observations`); each methodology limitation carries the originating method note's `source_ref` as its citation anchor; no estimation beyond supplied values, no regulatory-breach claims | `validated_input`, `observations`, `asset_associations` | `methodology_limitations`, `coverage_gaps`, `status` | FunctionNode → override `execute()` |
| cited_brief_assemble | `CitedBriefAssembleNode` — deterministically assemble the cited context brief per the supplied `reporting_template` (read from `validated_input`); every statement (observation, association, **methodology limitation, coverage gap**) resolves 1:1 to a supplied `source_ref` citation, else fail-closed (`ERR_SOURCE_CITATION_MISMATCH`) | `validated_input`, `observations`, `asset_associations`, `methodology_limitations`, `coverage_gaps`, `citations` | `context_brief`, `result`, `status` | FunctionNode → override `execute()` |

### Data Flow

**Outer backbone (fixed — framework-owned `add_edges()`):**
```
START → initialize → pre_process → main → {route} → post_process → finalize → END
                                            ↓ (retry, max 3)
                                          pre_process
```

**Inner evidence workflow (`EvidenceWorkflowGraph.add_edges()` — linear):**
```
START → input_hydrate → observation_asset_extract → limit_gap_analysis → cited_brief_assemble → END
```

> `validated_input` (set by `input_hydrate`, carrying `method_notes` and `reporting_template`)
> persists in inner State and is read downstream: `limit_gap_analysis` reads `method_notes`,
> `cited_brief_assemble` reads `reporting_template`. Every emitted statement (observation,
> association, methodology limitation, coverage gap) is citation-anchored 1:1 to a supplied
> `source_ref`; an unresolved statement fails closed (`ERR_SOURCE_CITATION_MISMATCH`).

`EvidenceWorkflowGraphNode.execute()` calls `inner.invoke(extract_input(state), ctx=ctx)`; the
inner graph's `get_output()` dict is what `GraphNode.execute()` hands to
`merge_output(state, sub_result)` as `sub_result`, and `merge_output()` maps only the changed key
(`result`) out of `sub_result` into the outer state (no raw pass-through of other inner fields).
`error_strategy = "propagate"`: any inner error is re-raised as `SubgraphError` and the run ends
fail-closed (no partial output). A request degraded at `pre_process` never reaches the inner graph:
`main` returns `SUCCESS` without invoking it and `post_process` returns the notice for the code.

### State Definition

**Outer State — `State(AgentState)`** (adds no domain field; its one own field is the degradation marker `error_code`)

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| user_input | str (inherited) | JSON string carrying the supplied inputs (observation extracts, locational-only asset-reference map, method notes, reporting template) | required |
| validated_input | Any (inherited) | Parsed + screened supplied inputs (flat dict) set by `pre_process` | set by pre_process |
| result | Any (inherited) | Assembled cited context brief (dict) mapped from the inner graph by `merge_output` | set by main |
| formatted_output | Any (inherited) | The S-3-gated cited brief, or the fixed notice (str) on a run that completes without a brief; terminal output via `AgentBaseGraph.get_output()` (`formatted_output or result`) | set by post_process |
| error_code | str (NotRequired) | Allow-listed degradation code (`src/services/degradation.py`); absent on a normal run, never carries request or brief content | set by pre_process / post_process |
| status | str (inherited) | AgentStatus value | set by every node |

**Inner State — `EvidenceWorkflowState(AgentState)`**

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| user_input | str (inherited) | JSON string handed in via `BaseGraph.invoke(user_input)` | required |
| validated_input | Any (inherited) | Hydrated supplied inputs (flat dict) set by `input_hydrate` | set by input_hydrate |
| observations | list[dict] | Supplied observation values, passed through (never re-estimated) | set by observation_asset_extract |
| asset_associations | list[dict] | Locational-only associations (observation ↔ asset vicinity); never emission attribution | set by observation_asset_extract |
| citations | list[dict] | Provenance anchors (supplied-source references) per extracted item | set by observation_asset_extract |
| methodology_limitations | list[dict] | Deterministic method limitations from the supplied `method_notes` (read from `validated_input`); each carries the originating method note's `source_ref` as its citation anchor | set by limit_gap_analysis |
| coverage_gaps | list[dict] | Deterministic coverage gaps in the supplied observations | set by limit_gap_analysis |
| context_brief | dict | Assembled cited brief per the reporting template | set by cited_brief_assemble |
| result | Any (inherited) | `context_brief`, returned by `get_output()` | set by cited_brief_assemble |
| status | str (inherited) | AgentStatus value | set by every node |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)
- `node_history` / `error_log` are `Annotated[list[str], operator.add]` reducers — not projected inner→outer

### Input Contract & Source-Approval Assurance

**Assurance model (v1): caller-attested, agent-verified for citability/consistency.** The caller is
the approval authority — it attests that each supplied source is approved by including approval
evidence in the payload. In v1 the agent does **not** re-verify approval authenticity against an
external authority (supplied-only; no external service): approval authenticity is trusted at the
S-1 `VERIFIED_EXTERNAL` boundary. The agent instead enforces, fail-closed, that every supplied
observation and method note is **attested and citable**, and that every brief statement resolves
1:1 to a supplied source. This external-verification gap is the declared v1 trust boundary (a
future v2 with an external source registry could add allowlist/signature verification — out of v1
scope).

**`user_input` payload (JSON string) — required shape (enforced by `SourceIntakeNode` / `input_schema.py`):**

| Field | Type | Required fields / rule |
|-------|------|------------------------|
| `observations` | list[object] | each `{observation_id, value, unit, observed_at, location, source_ref}`; `observation_id` is a caller-supplied stable string identifier, **unique within `observations`** — it is the sole referent for `asset_reference_map.observation_ref`; `value`/`unit` passed through, never re-estimated |
| `asset_reference_map` | list[object] | each `{observation_ref, asset_id, relation}`; `observation_ref` MUST resolve to **exactly one** `observations[].observation_id` (existence + uniqueness), giving each association a 1:1 traceable path to that observation's `source_ref`; `relation` MUST equal `"locational"` (any other value rejected) |
| `method_notes` | list[object] | each `{text, source_ref}` |
| `reporting_template` | object | typed brief template (sections / placeholders) |
| `source_ref` (on each observation & method note) | object | `{source_id, locator, approval}` — `source_id` identifies the approved source; `locator` points to the exact in-source location enabling a per-statement citation; `approval` = caller attestation `{attested_by, attested_at, approval_ref}` (well-formedness enforced; authenticity caller-attested, not re-verified in v1) |

**Accepted-source policy (v1):** no external allowlist / signature / attestation-authority
verification (supplied-only). The agent verifies presence + well-formedness of `source_ref` and
`approval` for every observation / method note, and per-statement citability; it trusts approval
authenticity at the `VERIFIED_EXTERNAL` boundary.

**Contract violation — the caller can correct it** (`SourceIntakeNode` → `status = AgentStatus.SUCCESS.value`
with the code below in `error_code`, no `validated_input`; the inner workflow is skipped and the output
is the fixed notice for the code, derived from the code alone — never payload content). `SUCCESS` here
means the request was handled safely, not that a brief was returned:

| Error code | Trigger |
|------------|---------|
| `ERR_EMPTY_REQUEST` | `user_input` empty or blank |
| `ERR_MALFORMED_JSON` | `user_input` is not JSON (e.g. a plain-text request) |
| `ERR_TOO_DEEP` | `user_input` is nested beyond what the parser accepts |
| `ERR_SCHEMA` | not a JSON object, or a missing / malformed field or type violation |
| `ERR_UNATTESTED_SOURCE` | an observation / method note lacks a well-formed `source_ref.approval` |
| `ERR_UNCITABLE` | a `source_ref` missing `source_id` or `locator` (cannot cite) |
| `ERR_NONLOCATIONAL_RELATION` | an `asset_reference_map` entry has `relation != "locational"` |
| `ERR_UNKNOWN_OBSERVATION_REF` | an `asset_reference_map.observation_ref` matches no `observations[].observation_id` |
| `ERR_AMBIGUOUS_OBSERVATION_REF` | `observations` contains a duplicate `observation_id` (or an `observation_ref` resolves to more than one), so the reference cannot resolve 1:1 |

`ERR_SOURCE_CITATION_MISMATCH` is **not** a contract violation: a brief statement — including a
methodology-limitation or coverage-gap statement — that cannot resolve 1:1 to a supplied
`source_ref` after the contract above was validated is an internal inconsistency, and the run ends
fail-closed as `status = AgentStatus.ERROR.value` with no output (checked at assemble).

> **docs/03 acceptance tests:** unattested source / missing citation / non-locational relation /
> unknown `observation_ref` / duplicate `observation_id` / empty / non-JSON request → the notice for
> the code, no brief, inner workflow not run; source/citation mismatch → fail-closed error; and
> valid input → each `asset_reference_map` entry resolves 1:1 to an observation (carrying that
> observation's `source_ref`) and statement-to-citation 1:1 preserved in the brief.

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle) — via `config["configurable"]`; `InvocationContext.from_state(state)` where needed
- [ ] ConnectionPolicy (retry/timeout strategy) — N/A (no external connection in v1; supplied inputs only)
- [x] SecurityViolationError
- [x] S-2: `_extra_security_gate_input()` — **structural screen only** on the raw `user_input` string: reject non-`str` / NUL / control characters / oversized payloads (never `str()`-coerced, so a `\x00` cannot be smuggled). The per-field input schema (types / shape / required fields / references) is enforced by `execute()` via `input_schema.py` (a violation completes with a non-sensitive `error_code` and the fixed notice; the structural screen itself stays a fail-closed error). **PII masking is the framework baseline `@final` `_security_gate_input()`, which is NOT overridden** — per-value PII pattern-matching is deliberately avoided so that legitimate location / attester names are not false-positive-blocked, and `validated_input` carries only the contract fields (structured-only), which bounds the PII surface. v1 has no LLM boundary, so there is no prompt-injection sink to defend at the input; the terminal S-3 semantic gate governs prohibited output. `InputHydrateNode` re-validates after the string handoff.
- [x] S-3: `_extra_security_gate_output()` — baseline credential scan runs `@final` on every node. The **terminal** domain S-3 gate is `OutputGateNode.execute()` in the outer `post_process` (see Security summary) because a downstream hook sees only the node delta; the outer node clears the full brief on violation — withholding it with a fixed notice for a scope category or PII, failing closed for injection-derived text.
- [x] S-4: `emit_trace_event()` — at least one domain event inside each `execute()` (`source_intake`, `observation_extract`, `limit_gap`, `brief_assemble`, `output_gate`, `hydrate`). No `node_start`/`node_complete`/`node_error` duplication.

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - All domain nodes here are `FunctionNode` subclasses → the framework `@final` gates always run; domain checks go in `_extra_security_gate_input()` / `_extra_security_gate_output()`, plus the terminal `OutputGateNode.execute()` for the whole-brief S-3 contract.
> - `EvidenceWorkflowGraphNode` is a `GraphNode` → its S-2/S-3 are deliberate no-ops (the inner nodes' gates apply inside the subgraph; the outer `SourceIntakeNode`/`OutputGateNode` bound the untrusted input and the final output).

### Composition Pattern

- **Pattern**: GraphNode (in-process subgraph)
- **Composition target**: inner `EvidenceWorkflowGraph` at `src/graph/domain_workflow_graph.py`, instantiated by `EvidenceWorkflowGraphNode.get_subgraph()`
- **Error propagation strategy**: propagate (inner error → `SubgraphError` → fail-closed, no partial output)
- **Trust**: outer nodes declare `required_trust_level = VERIFIED_EXTERNAL` (S-1 enforced at the outer boundary); inner nodes declare `ANONYMOUS` because `BaseGraph.invoke()` does not propagate caller trust into the subgraph — S-1 is already enforced at the outer boundary.

### Manifest Entry-Point (implementation timing)

`config/agent.yaml` fixes the runnable entry-point at design time as `module: src.graph` /
`class: EnergyMethaneObservationContextBriefGraph` (`base_type: Other`, L1-direct). That class is
**implemented and exported in the Stage ③ graph-composition MR**; until then `src/graph/graph.py`
holds only the scaffold `Graph` class and `src/graph/__init__.py` exports nothing. Fixing the
manifest ahead of the implementation is safe because nothing imports the class before it exists:
AgentRegistry reads the manifest metadata and loads the class **lazily** (only at invocation), the
first deploy/invoke is **Stage ⑤** (after Stage ③), and no Stage-② artifact imports the
manifest-declared class — `gate-cat-consistency` reads only `id` / `category`, `run-tests` imports the
graph module directly (not via `agent.yaml`) and does not reference the manifest class name, and there
is no manifest-validation gate at Stage ②. A broken entry-point therefore cannot surface before the
Stage ③ MR lands (the branch pipeline is green with the manifest already resolved).

**Completion condition — Stage ③ graph-composition MR (acceptance criterion):** that MR MUST, in the
**same change set**, (1) implement `class EnergyMethaneObservationContextBriefGraph(AgentBaseGraph)` in
`src/graph/graph.py` and (2) export it from `src/graph/__init__.py`, so
`src.graph.EnergyMethaneObservationContextBriefGraph` resolves before any AgentRegistry discovery or
STG deploy. **Verification command (must exit 0 in that MR):**
`python -c "from src.graph import EnergyMethaneObservationContextBriefGraph"`. The manifest MUST NOT be
left pointing at a missing class once Stage ③ lands.

## Services (`src/services/`)

Deterministic, side-effect-free domain helpers (no `agenticstar` imports, no external I/O):
- `input_schema.py` — validate/parse the supplied-inputs schema per **Input Contract & Source-Approval Assurance**: observation-extract fields/units/time and **unique `observation_id`**, `asset_reference_map` with `relation == "locational"` and each `observation_ref` resolving to exactly one `observation_id` (traceable to that observation's `source_ref`), method-notes and reporting-template typing, and per-item `source_ref = {source_id, locator, approval}`; reject unknown/ambiguous references (`ERR_UNKNOWN_OBSERVATION_REF` / `ERR_AMBIGUOUS_OBSERVATION_REF`), unattested (`ERR_UNATTESTED_SOURCE`), uncitable (`ERR_UNCITABLE`), non-locational (`ERR_NONLOCATIONAL_RELATION`), or malformed (`ERR_SCHEMA`).
- `brief_assembler.py` — deterministic template-driven brief assembly with per-statement citations and declared limitations/gaps.
- `output_policy.py` — the S-3 semantic policy: allowed locational phrasing vs prohibited attribution/estimation/leak/breach/control phrasing (explicit allow/deny lists + rules), used by `OutputGateNode`.

No LLM client is used in v1 (see DDR — deterministic assembly). `requires.secrets` is empty.

**Runtime dependencies & availability.** The core path has **zero live-infrastructure dependency** — no LLM, database, vector store, or external API. It runs fully deterministically and offline, so the template is unit-testable, STG-deployable, and releasable **without** the pending dev-infrastructure/credential provisioning tracked centrally as an open provisioning request; that unresolved request does not block this template. **Forward rule (v2):** if an optional LLM or external service is ever added (e.g. a non-authoritative narrative pass), it MUST stay non-authoritative (the deterministic result remains the authority), its unavailability MUST return a controlled `status = AgentStatus.ERROR.value` (`ERR_DEPENDENCY_UNAVAILABLE`) — never an uncaught exception — and tests MUST inject a fake client rather than call live infrastructure. This keeps any future optional dependency off the mandatory core path.

## Security & Error Handling Summary (traceability to proposal §Boundaries)

| Layer | Where | Behaviour |
|-------|-------|-----------|
| S-1 Trust | every node (`required_trust_level`) | outer = `VERIFIED_EXTERNAL`, inner = `ANONYMOUS`; refused before `execute()` on insufficient trust |
| S-2 Input | `SourceIntakeNode._extra_security_gate_input()` (structural screen) + `execute()` / `input_schema.py` (contract) + baseline `@final` PII scan + `InputHydrateNode` | structural screen (non-`str` / NUL / control-char / oversized) in the hook; schema + source-approval + reference contract enforced in `execute()` — a violation completes with a non-sensitive `error_code` and the fixed notice, the structural screen fails closed; PII masking via the framework baseline (the hook does not override it); structured-only `validated_input` bounds the PII surface (no LLM boundary in v1, so no input-side injection defense) |
| S-3 Output | baseline `@final` credential scan (all nodes) + `OutputGateNode.execute()` (outer post_process) | terminal gate **blocks** leak identification, asset attribution (including hedged-equivalent phrasing such as "emissions likely from the vicinity of asset X"), estimation beyond supplied values, regulatory-breach reporting, and asset-control directives, and PII — the whole brief is withheld with a fixed notice (`BRIEF_WITHHELD` / `PERSONAL_DATA_WITHHELD`); injection-derived text and credentials → fail-closed error |
| S-4 Audit | every `execute()` | ≥1 domain `emit_trace_event()` |
| S-5 Supply chain | `pyproject.toml` | exact `==` pins; no credentials in `src/` |

### Outcome Classification

Every run of this agent completes and states what happened. A run that returns no brief is one of
the following; the brief is never returned in part.

| Class | Cases | Result |
|-------|-------|--------|
| Caller-correctable | empty / non-JSON / too-deep request, and every input-contract code (`ERR_SCHEMA`, `ERR_UNATTESTED_SOURCE`, `ERR_UNCITABLE`, `ERR_NONLOCATIONAL_RELATION`, `ERR_UNKNOWN_OBSERVATION_REF`, `ERR_AMBIGUOUS_OBSERVATION_REF`) | `status = SUCCESS`, `error_code` = the code, output = the fixed notice naming what to send instead; inner workflow not run |
| Policy withholding | the assembled brief matches a scope category of the output policy (leak identification, asset attribution incl. hedged, estimation beyond supplied values, regulatory breach/reporting, field-work initiation, energy-asset control) → `BRIEF_WITHHELD`; the brief carries PII → `PERSONAL_DATA_WITHHELD` | `status = SUCCESS`, `error_code` = the code, output = the fixed notice; `result` cleared, the matched category recorded in the audit trail only |
| Security failure | input refused by the structural S-2 screen; injection-derived text in the brief (asked first, so it is never reported as merely withheld); credential-shaped content (baseline `@final` S-3) | `status = ERROR`, no output; never converted to `SUCCESS` |
| Internal inconsistency | a statement that cannot resolve 1:1 to a supplied `source_ref` after validation (`ERR_SOURCE_CITATION_MISMATCH`); an inner node finding state a preceding step guarantees absent or malformed; no brief reaching the terminal gate | `status = ERROR`, no output; inner errors re-raised as `SubgraphError` under `error_strategy = "propagate"` |

`SUCCESS` with an `error_code` means the request was handled safely, not that a brief was returned.
Every notice is derived from the allow-listed code alone and is worded to pass the same output
policy a brief must pass, so no request value or withheld content reaches the caller.

**Error & Edge Cases:**

| Case | Behaviour |
|------|-----------|
| Contract violation (codes in *Input Contract & Source-Approval Assurance*) | `SourceIntakeNode` → `status = AgentStatus.SUCCESS.value` + `error_code`, no `validated_input`; `main` skips the inner workflow; `post_process` returns the notice |
| Structural S-2 screen (non-`str` / NUL / control-char / oversized) | `status = AgentStatus.ERROR.value`, code in `error_log`, no output |
| Brief statement cannot resolve 1:1 to a supplied `source_ref` (`ERR_SOURCE_CITATION_MISMATCH`) | detected at assemble → fail-closed, no output |
| Inner node error (extract/limit-gap/assemble) | re-raised as `SubgraphError`; outer run ends fail-closed, `get_output()` → `output: None` |
| Scope category or PII detected at S-3 | `OutputGateNode` → `status = AgentStatus.SUCCESS.value`, `error_code = BRIEF_WITHHELD / PERSONAL_DATA_WITHHELD`, `result = None`, `formatted_output` = the notice; no part of the brief returned |
| Injection-derived text detected at S-3 | `OutputGateNode` → `status = AgentStatus.ERROR.value`, `result = None`, `formatted_output = None` |
| Credential-shaped content in a node's return dict | baseline `@final` S-3 blocks (`RuntimeError`) → node `status: ERROR`, no output |
| Optional external dependency unavailable (forward rule — **none on the v1 core path**; applies only if a v2 adds an LLM/service) | controlled `status = AgentStatus.ERROR.value` (`ERR_DEPENDENCY_UNAVAILABLE`), no output; never an uncaught exception — the deterministic path carries no such dependency |

No partial-output path exists: the brief is returned only when every stage and the terminal S-3 gate pass.

## EU AI Act Art.13 Design-Time Evidence (Advisory until 2026-09-01; required from 2026-09-01 when the Annex III determination is `In scope`)

The Annex III determination is recorded as **advisory / to be determined at
Stage ② Design** (ENE, before 2026-09-01). This template is a read-only drafting aid with no
operational effect; it makes no automated decision and the environmental owner retains all
judgment. A full Art.13 evidence table is not required while the determination is advisory; it
will be completed here if the determination becomes `In scope`.

| Evidence item | Design reference / description |
|---------------|--------------------------------|
| Intended purpose and operating context | Cited internal context brief from supplied approved GHG observation evidence, for qualified human analysis (read-only) |
| System capabilities and limitations | Deterministic extraction/limitation/gap analysis over supplied inputs only; no retrieval, no estimation, no attribution, no operational action |
| User-facing transparency information | Output labelled a human-review draft; per-statement citations; declared limitations/gaps |
| Human oversight mechanism | Environmental-owner review required; agent takes no downstream action |

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | Bounded, fixed multi-step workflow (not an autonomous think→act loop) |
| Composition pattern | Standalone flat nodes | GraphNode + inner BaseGraph | **GraphNode + inner** | Cat-2 pattern: 4-step domain workflow hidden in `main`; outer backbone fixed |
| Brief generation | Deterministic template assembly | LLM narrative | **Deterministic** | Read-only, exact citations, no hallucination/injection surface; keeps output source-bound and reproducible. `requires.secrets` empty; no external LLM |
| S-3 terminal gate placement | Downstream hook | Outer `post_process.execute()` | **Outer post_process** | A hook sees only the node delta; the outer node clears the whole brief (`result`/`formatted_output`) on violation, giving a true end-to-end block |
| Attribution boundary | Literal phrase block | Semantic (incl. hedged-equivalent) | **Semantic** | Block phrasing that reaches attribution by implication (e.g. "likely from the vicinity of asset X"), not only literal "asset X is the source" |
| Reporting a run with no brief | `status = ERROR` for every refusal | Classify: correctable / withheld → `SUCCESS` + `error_code` + fixed notice; security failure / inconsistency → `ERROR` | **Classify** | A caller who can act on the reason gets it as the run's output; a security failure is not answered with guidance (that would explain how to get past the gate) and an inconsistency stays visible as a failure to monitoring |
| Inner-node trust | VERIFIED_EXTERNAL | ANONYMOUS | **ANONYMOUS** | `BaseGraph.invoke()` does not propagate caller trust; S-1 is enforced at the outer boundary |
| External data | Live fetch (GOSAT-GW) | Supplied only | **Supplied only** | v1 scope: no retrieval/refresh; PB-3 (external service) N/A |
| Source-approval assurance | Agent-verified vs external authority | Caller-attested + agent-verified citability | **Caller-attested (v1)** | No external source registry in v1 (supplied-only); agent enforces `source_ref`/`approval` presence + per-statement citability + `relation=="locational"`, and trusts approval authenticity at the `VERIFIED_EXTERNAL` boundary. Declared trust boundary; external allowlist/signature deferred to v2 |
