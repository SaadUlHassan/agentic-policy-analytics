# Final Implementation Plan — Agentic Policy Data Analytics Platform (IMDA Tech Challenge)

## Context

**The brief.** *Tech Challenge – Full Stack Engineer (Gen AI) v1.0*, 7 pages, is the single source of truth. It asks for:
- a full-stack agentic platform where policy researchers ask questions in natural language;
- at least 3 collaborating agents that extract Singapore government data from 2 or more sources, analyse it deterministically and return cited insights;
- a Next.js UI that streams agent activity live;
- 2 or more LLM providers with fallback;
- comprehensive tests (including hallucination detection), Docker and CI/CD, four documents, a 20-minute demo and a 1–2-page innovation essay.

**Starting point.** An empty repository (README only). The remote `origin` is `https://github.com/SaadUlHassan/agentic-policy-analytics`. The assessment brief and planning working notes are kept outside the repository.

**How this plan was revised.** It replaces the first draft and incorporates two external review rounds: amendments R1–R12, then findings F1–F7. I re-checked the reviews' unverified claims against the live APIs on 25 Oct 2026 (§4.1). The architecture is unchanged. What changed is the execution contracts: series identity, mandatory evidence validation, job and event durability, statistical eligibility, evaluation gates, and budget.

**Confirmed decisions:**
- OpenAI and AWS Bedrock credentials are both available. **Bedrock is primary, OpenAI is the fallback.** This is confirmed only once the Day-1 capability probe passes.
- **Budget: 10 working days**, including a contingency day. Bonus work only starts after the mandatory gates pass.
- Ambiguous queries: **the coordinator asks, and the user can choose "proceed with stated assumptions"**.
- **Real data sources only.** No fabricated research data and no fabricated findings. Test-only doubles (ScriptedLLM, mutated fixtures, corrupted adversarial claims) are allowed, clearly isolated under `tests/` and `eval/`, and never reachable from production paths.

**Rubric weights (p.4) that drive priority:** Development Excellence 50%, Agentic Design 25%, Testing & QA 15%, DevOps & Docs 10%. Bonus has no stated weight.

### Review disposition

| Review item | Where it is resolved |
|---|---|
| R1 taxonomy and definitions | §4.3 series identity and join rules |
| R2 mandatory evidence validation | §3.6 report/claim contract; verified-only output |
| R3 durable lifecycle and idempotency | §3.7 state machine, outbox, lease, reconciler |
| R4 WebSocket catch-up | §3.8 DB-authoritative drain loop |
| R5 statistical eligibility | §4.5 method policy with reason codes |
| R6 evaluation gates | §8 concrete gates and targets |
| R7 budget | §7 ten-day plan + gates |
| R8 provider probe and degradation | §4.7 |
| R9 provenance and manifest | §4.2, §4.4 |
| R10 reproducibility tiers | §4.6 |
| R11 traceability and DoD | §1 matrix, §7 milestones, §3.6 contracts |
| R12 bonus, demo and submission | §1.3, §9.2, §9.3, §10 |
| F1 lost dispatched jobs | §3.7 delivery generation + worker acknowledgement; reconciler covers dispatched-but-unacknowledged |
| F2 stale-worker fencing | §3.7 execution epoch fencing token on every authoritative write, including checkpoints |
| F3 cache/computation keys | §3.7 canonical evidence + method fingerprint |
| F4 exact claim binding | §3.6 predicate templates bound to field, metric, identities and exact interval |
| F5 named correlation pair | §4.5 pair, rationale and stock/flow compatibility rule |
| F6 botocore retries | §4.7 `total_max_attempts=1` |
| F7 non-waivable gates | §7 hard gates vs documented targets; §8.3; §9.4 |

---

## 1. Requirements Traceability Matrix

PDF references below use page number + core requirement (CR) number from Section 1, e.g. *p.1 CR1*.
- *Official* = text of the brief.
- *Implementation* = our chosen means.
- *Enhancement* = not required (see §1.3).

### 1.1 Core requirements

| ID | Official requirement | Selected implementation | Acceptance criterion | Validation |
|---|---|---|---|---|
| MA-1 | p.1 CR1: ≥3 autonomous agents — Coordinator (plans and delegates), Extraction (multi-source), Analytics (processes and generates insights) | LangGraph supervisor graph with **Coordinator**, **Extraction** (ReAct) and **Analytics** (ReAct). The deterministic verification layer is used by the Coordinator before finalising (§3.6). | On every **successful supported analytical run**, all 3 agents appear in the trace, each with at least one LLM decision and a public rationale. Refusal and limitation-only paths (out-of-domain, no usable evidence) may legitimately end without Analytics. No LLM calls are forced on them. | Integration test asserts agent decision events. Live demo trace. |
| MA-2 | p.1 CR1: show orchestration, coordination, autonomous collaboration | Coordinator `NextAction` structured decision + deterministic policy guards. Handoffs via typed state. Evidence-driven re-planning. | Live golden traces show at least one **evidence-driven decision not triggered by a fault switch**: Extraction rejecting an unfit dataset (e.g. subsector or reference-period mismatch) and the Coordinator refining an objective (e.g. requesting a quarterly series after an annual reference mismatch) | Live golden-run assertions (§8.3) plus scripted scenario tests |
| GD-1 | p.1 CR2: ≥2 different sources among SingStat, MOM, Data.gov.sg | **Three source platforms:** SingStat Table Builder, Data.gov.sg, MOM Statistics site. Origin agency is recorded separately from the platform. | The demo report cites at least 2 platforms. Mirrored data is labelled same-origin and never presented as corroboration. | E2E test plus citation inspection |
| GD-2 | p.1 CR2: handle CSV, Excel, JSON, APIs | JSON REST (SingStat, Data.gov.sg datastore), CSV (Data.gov.sg download, MOM CSV), Excel (MOM `.xlsx`) | One parser per format passes on recorded real payloads, including the multi-sheet MOM workbook | Unit tests on fixtures |
| GD-3 | p.1 CR2: error handling for API failures and missing data | Shared Redis rate limiter, bounded retries, snapshot fallback, alternate dataset, explicit limitations. Source-defined marker semantics. | Simulated 429/5xx/timeout/schema drift each end in a disclosed fallback or limitation. No crash, no silent imputation. | Fault-injection and data-quality tests |
| GD-4 | p.1 CR2: show data quality validation and cleaning | pandera schemas, cleaning pipeline, cross-platform consistency check, `QualityReport` UI panel and events | UI shows each check run, result, rows affected and the marker meanings applied | Data-quality suite, demo |
| IA-1 | p.2 CR3: statistical analysis (trends, patterns, correlations) | Deterministic tools governed by the method policy (§4.5): YoY, CAGR, trend (OLS/HAC), period comparison, exploratory correlation | Every tool has eligible and ineligible fixtures with reason codes. At least one *eligible* correlation is preserved (quarterly ICT pair, n=20). | Unit tests against independently computed expectations |
| IA-2 | p.2 CR3: policy-relevant insights | Analytics drafts typed `Claim`s (measured / comparison / association / limitation). Recommendations are a separate claim kind. | Every retained claim passes all deterministic checks (§3.6). Recommendations never carry measured numbers or causal assertions. | Verifier suite, golden runs |
| IA-3 | p.2 CR3: visualisations | `Chart` specs bound to computation and dataset-version IDs, rendered with Recharts | Every chart's plotted values equal the stored observations or computations | Frontend tests + data-equality test |
| IA-4 | p.2 CR3: structured reports with source citations | Typed `Report` of `ReportBlock`s. **Citations are derived from computation lineage, not written by the LLM.** | 100% of citations resolve to the dataset versions, series and periods actually used | Citation-lineage test |
| FE-1 | p.2 CR4: NL query input | Query box with validation (3–1000 chars), sample queries, disabled during submit | Empty or oversize input is blocked client- and server-side (422). Submit returns 202 and navigates to the live view in under 1 s. | Vitest, API test, Playwright |
| FE-2 | p.2 CR4: real-time agent activity showing reasoning steps | Agent-lane timeline of public `rationale` summaries, tool calls/results, handoffs, quality checks, provider fallbacks. No private chain-of-thought. | Events render in order without duplicates. After reconnect the timeline converges to the committed history (§3.8). | WS failure tests (§8.1) |
| FE-3 | p.2 CR4: interactive dashboard | Series toggle, period range filter, tooltips, claim↔chart highlight, data-table view, responsive layout | Each interaction works at 375 px, 768 px and 1280 px. Filters never alter stored results. | Component tests + Playwright viewport runs |
| FE-4 | p.2 CR4: analysis history and export | Keyset-paginated history with status filter. Export as Markdown, JSON bundle and CSV of observations used. | Exports contain only verified claims, citations and pinned dataset versions. Drafts are never exportable. | API + E2E tests |
| BE-1 | p.2 CR4: RESTful API with proper error handling | FastAPI, RFC 7807 problem+json with stable error codes, 409 for state conflicts (§3.7), OpenAPI | Every documented error path returns typed problem+json. No stack traces leak. | API tests |
| BE-2 | p.2 CR4: async processing for long-running analyses | Transactional outbox → arq worker, with lease and heartbeat (§3.7) | Named crash and duplicate tests (§8.1) end in a single coherent outcome | Lifecycle failure tests |
| BE-3 | p.2 CR4: DB storing datasets and results | PostgreSQL: immutable dataset versions, observations, computations, reports, events, LLM ledger | Reopening an analysis returns identical stored bytes without refetching | Reopen test (§4.6) |
| BE-4 | p.2 CR4: WebSocket real-time updates | `/ws/analyses/{id}?after_seq=` drains committed events from Postgres. Redis pub/sub is only a wake-up hint. | Named WS failure tests pass | §8.1 |
| LLM-1 | p.2 CR5: ≥2 providers | AWS Bedrock (primary) + OpenAI (fallback) behind `LLMRouter` | Day-1 probe passes on both models: tool call, structured output, one ReAct turn | `scripts/probe_llm.py` output recorded in TESTING.md |
| LLM-2 | p.2 CR5: demonstrate fallback | Router with retries, circuit breaker and `provider_fallback` events | Live fallback works **in both directions**. A partial-stream failure produces no duplicated text. | Live tests (§8.3) |
| LLM-3 | p.2 CR5: LLMs for query interpretation, insight generation, report creation | Coordinator: query → `ResearchPlan`. Analytics: claim drafting. Coordinator: report narrative from verified claims. | `ResearchPlan` validates against its schema for all 12 golden queries. Narrative contains no unbound numbers. | Golden runs |
| LLM-4 | p.2 CR5: practical use in the workflow | LLMs also do tool selection, dataset-fitness judgement, re-planning and the qualitative claim check | Golden traces show LLM decisions changing the outcome (MA-2) | Live golden runs |
| AF-1 | p.2 CR6: use an agentic framework | LangGraph: `StateGraph`, `Command`, `interrupt`, Postgres checkpointer | — (structural) | Code review |
| AF-2 | p.2 CR6: ReAct (Reason, Action, Observation) | Custom ReAct subgraphs (model → ToolNode → model) that emit `rationale` → `tool_call` → `tool_result` | Every Extraction/Analytics step in the trace has an R-A-O triple. Tool errors appear as observations. | Scripted-LLM unit tests |
| AF-3 | p.2 CR6: decision-making and planning | Plan card (intent, entities, SSIC code set, metrics, period, sub-questions, assumptions). Re-plan events. | Ambiguous golden queries trigger clarification. Explicit ones do not. | Golden runs |
| AF-4 | p.2 CR6: handle agent failures gracefully | Recovery matrix (§3.5), budgets, degraded modes (§4.7) | An expired execution is recovered (re-queued under a new epoch) or failed within one reconcile interval. Terminal completion follows the bounded retry/deadline policy (≤3 attempts, active deadline). `awaiting_input` analyses may intentionally stay paused. | Lifecycle tests |
| T-1 | p.3 CR7: unit tests for agents, tools, APIs | pytest + ScriptedLLM + respx | Suites green in CI | Hosted CI run |
| T-2 | p.3 CR7: multi-agent integration tests | Full graph on Postgres/Redis service containers + live golden runs before release | Scripted suite green in CI. Live gate (§8.3) passed before demo. | CI + release checklist |
| T-3 | p.3 CR7: hallucination detection, accuracy, consistency | Eval harness (§8.3) | Gates in §8.3 met, with precision and recall reported | `make eval` |
| T-4 | p.3 CR7: data quality validation tests | Real and mutated fixtures | All mutation classes detected | CI |
| T-5 | p.3 CR7: performance and load | Locust workload (§8.4) | Proposed targets met or honestly reported as missed | `make load` |
| TD-1..3 | p.3 CR7: test plan, hallucination approach, results/coverage | TESTING.md + CI coverage artifacts | All numbers generated from actual runs | Review |
| DO-1 | p.3 CR8: Docker + Compose | Multi-stage images; compose: postgres(pgvector image), redis, migrate, api, worker, web | Fresh clone + `.env` → `docker compose up` → all services healthy | Compose smoke job in CI |
| DO-2 | p.3 CR8: CI/CD (automated testing + deployment config) | GitHub Actions: lint → tests → build → compose smoke → GHCR push on `main`/tags; `docker-compose.prod.yml` | **A green hosted run on GitHub** (a workflow file alone is not evidence) | GitHub Actions run link |
| DO-3 | p.3 CR8: environment and secrets | pydantic-settings, `.env.example`, AWS default credential chain, GitHub Secrets, gitleaks | No secrets in git history or images. Fault injection disabled in the prod config. | gitleaks job, config test |
| DO-4 | p.3 CR8: deployment docs | README "Deploy" section | A reviewer can deploy from the docs alone | Fresh-clone rehearsal |

### 1.2 Submission, demo, innovation

| ID | Official requirement | Deliverable | Acceptance |
|---|---|---|---|
| SUB-1 | p.5: source code, Dockerfile, docker-compose.yml, tests with docs | Repo per §6 | Fresh-clone rehearsal passes |
| SUB-2 | p.5: README (overview/architecture, step-by-step setup, run locally, run tests, sample queries, tech choices) | README.md | Every listed item present and exercised in the rehearsal |
| SUB-3 | p.5: ARCHITECTURE.md (system design, agent workflows, DB schema, decisions) | Mermaid system, graph, sequence and ER diagrams; decision records | Diagrams match the code |
| SUB-4 | p.5: TESTING.md (strategy, hallucination methodology, results) | Real results tables | All numbers traceable to CI or eval artifacts |
| SUB-5 | p.5: DATA_SOURCES.md (sources, API docs, mock approach) | Source manifest; "no mock data; real-data snapshots" | Every dataset entry has full ID and canonical link |
| DEMO | p.5–6: 20-min E2E, multi-source extraction, quality checks, insights/visuals, architecture, challenges & solutions, Q&A; be ready for API failure / missing data / ambiguous query, testing, multi-cloud, scalability | docs/DEMO_SCRIPT.md (§9.2) | Two timed dry runs within 16 min of presentation, leaving 4 min for Q&A |
| INN | p.6–7: 1–2-page innovation assessment with concrete implementation examples | docs/INNOVATION.md (§9.3) | Separates implemented features from proposals. No compliance claims. |

### 1.3 Enhancements (not required; scheduled only after gates G1–G8 pass, §7)

| Bonus (p.4–5) | Enhancement | Order |
|---|---|---|
| Performance and cost tracking | Cost/latency dashboard. *The ledger itself is core.* | 1 |
| Advanced / predictive analytics | Quarterly forecast with backtest-gated prediction interval (§4.5) | 2 |
| Advanced analytics | Robust anomaly flags on differenced quarterly series | 3 |
| Vector DB / RAG | pgvector semantic catalogue search with **one** embedding model and lexical fallback | 4 |
| Streaming responses | Token streaming of a clearly segregated *draft* narrative (never exportable or labelled final) | 5 |
| Innovative agent design / creative data / code quality | Delivered inside core work: evidence-bound claims, lineage-derived citations, series-identity join rules, release-URL discovery, cross-platform consistency checks | core |

### 1.4 Ambiguities resolved
- **"Showing reasoning steps" vs. no private chain-of-thought.** Each LLM decision returns a short public `rationale` field. The UI shows rationales, tool events and observations only.
- **"Technology sector".** Mapped to **SSIC 2020 Section J, Information & Communications (J58–63)** as a stated assumption. The subsector **IT & Other Information Services (J62–63)** is kept distinct and offered as an optional breakdown, never merged with its parent (§4.3).
- **"At least 2 sources".** Satisfied by two source platforms even where MOM originates the statistic. We describe this as platform diversity, not independent corroboration.
- **Deployment.** Compose + prod config + GHCR images + docs. A public hosted URL is optional and not planned. The demo stays local/private because the app is unauthenticated.

---

## 2. System Architecture

```
┌──────────────┐  REST (JSON)   ┌──────────────────┐ outbox→arq   ┌──────────────────────────┐
│  Next.js web │ ─────────────► │  FastAPI  (api)  │ ───────────► │  Worker (same image)     │
│  TS·TW·      │ ◄── WebSocket ─│  REST + WS drain │              │  LangGraph graph, tools, │
│  Recharts    │                └───┬───────▲──────┘              │  lease+heartbeat         │
└──────────────┘                    │       │ wake-up hints       └───┬─────────┬────────────┘
                                    │       └── Redis pub/sub ◄───────┤         │
                         ┌──────────▼─────────────────────┐           │   ┌─────▼────────────┐
                         │ PostgreSQL 16 (authoritative)  │◄──────────┘   │ LLMRouter        │
                         │ analyses·outbox·events·dataset │               │ Bedrock → OpenAI │
                         │ versions·observations·computa- │               │ timeout/retry/CB │
                         │ tions·reports·llm_calls·ckpts  │               └──────────────────┘
                         └────────────────────────────────┘   ┌──────────────────────────────┐
                         ┌────────┐ queue, wake-up hints,     │ Connectors: SingStat ·       │
                         │ Redis  │ shared rate-limit buckets,│ Data.gov.sg · MOM (httpx)    │
                         └────────┘ HTTP cache (all rebuildable from Postgres)              │
                                                              └──────────────────────────────┘
```

**Boundaries.**
- One Python codebase with two entrypoints, `api` and `worker`. No microservices.
- Postgres is authoritative for all state. Redis holds only rebuildable or advisory data.
- The frontend talks only to the API.

**REST surface.**
- `POST /api/analyses` → 202
- `GET /api/analyses?cursor=&limit=&status=` — keyset pagination
- `GET /api/analyses/{id}`
- `POST /api/analyses/{id}/clarify` `{clarification_version, answer | proceed_with_assumptions}`
- `POST /api/analyses/{id}/cancel`
- `GET /api/analyses/{id}/export?format=md|json|csv`
- `GET /api/datasets/{version_id}`
- `GET /api/sources/health`
- `GET /api/health`
- `POST /api/admin/faults` — routed only when `ENABLE_FAULT_INJECTION=true`; false in the prod config

---

## 3. Agent Architecture

### 3.1 Agents

| Agent | Responsibility | LLM decisions | Tools (deterministic) |
|---|---|---|---|
| **Coordinator** | Interpret → `ResearchPlan`. Decide clarification. Delegate. Evaluate evidence coverage. Re-plan. Assemble report from verified claims. Decide termination. | Plan, `NextAction` + rationale, report narrative over verified claims | `check_coverage`, `run_verification` (§3.6), `list_supported_domains` |
| **Extraction** (ReAct) | Discover candidates. Fetch. Validate. Judge fitness against plan identity requirements (code set, population, reference period). Reject unfit data. Fall back. | Candidate choice, fitness accept/reject with reason, fallback choice | `search_catalog` (lexical over curated catalogue), `search_singstat` (live; results marked *uncurated* and usable only if they parse and validate), `fetch_singstat_table`, `fetch_datagov_dataset`, `fetch_mom_timeseries`, `profile_dataset`, `validate_and_clean` |
| **Analytics** (ReAct) | Pick eligible methods. Run them. Draft typed claims bound to computation IDs. | Method selection, claim drafting (placeholders only) | `yoy_change`, `cagr`, `trend`, `compare_periods`, `correlate`, `make_chart_spec`. Each tool enforces the §4.5 policy and returns either a result or a refusal code. |

**Verification layer.** Deterministic validators always run. An additional LLM check of qualitative wording runs on the provider *other than* the writer when that provider is healthy. Otherwise independence is marked unavailable. Verification is a mandatory gate the Coordinator must invoke, not an optional agent. This meets the 3-agent requirement without a fourth agent that could be skipped.

### 3.2 State (`AnalysisState`, Pydantic; references only, so checkpoints stay small)
- `analysis_id`, `query`, `plan`, `clarification`
- `tasks[]` (id, agent, objective, status, attempts)
- `dataset_versions{}` (refs), `quality{}`, `computations[]` (refs), `claims[]`, `report_ref`
- `budget` (active_ms, tool_calls, tokens, cost), `errors[]`, `graph_version`, `prompt_version`

### 3.3 Graph

```
START → interpret ─needs_clarification─► clarify (interrupt; worker releases slot)
           │                                   │ resume via same thread_id
           ▼                                   ▼
       supervise ◄──────────── task results / verification verdicts ──────────────┐
  (LLM NextAction → policy guards)                                                 │
     ├─► extraction (ReAct) ───────────────────────────────────────────────────────┤
     ├─► analytics  (ReAct) ───────────────────────────────────────────────────────┤
     ├─► verify (deterministic + qualitative) → reject list back to analytics (≤1) ┤
     ├─► compose_report (narrative over verified claims only) → verify narrative ──┤
     ├─► finalize  (completed | completed_with_limitations)
     └─► fail      (failed: no plan/evidence possible)
```

**Policy guards — "LLM proposes, policy disposes":**
- analytics needs ≥1 validated dataset version matching a plan identity;
- `compose_report` needs ≥1 verified claim, or only-limitations;
- `finalize` needs the report verification to pass. There is **no bypass**, including for limited reports;
- agent attempts ≤2.

An invalid choice goes back to the LLM once with the reason. If it fails again, the deterministic fallback route runs. Both steps are logged.

### 3.4 ReAct and events

Event schema: `{seq, ts, analysis_id, agent, type ∈ {plan, rationale, tool_call, tool_result, handoff, quality_report, computation, claim_verdict, llm_call, provider_fallback, clarification, status, error}, title, detail}`.

The UI shows one lane per agent with expandable R-A-O details. Rationales are at most 2 sentences and public.

### 3.5 Recovery matrix

| Failure | Handling |
|---|---|
| HTTP 429/5xx/timeout | Shared Redis token bucket. ≤3 retries with jittered backoff inside the source deadline. Then snapshot (labelled with retrieval date). Then alternate dataset. Then a limitation claim. |
| Schema drift / parse failure | Quarantine the version, emit `quality_report`, Extraction picks an alternate or reports a limitation |
| Missing or suppressed values | Source-defined marker semantics (§4.4). Never imputed. Tools refuse with reason codes when eligibility fails. |
| Tool exception | Returned as an error observation. After 2 consecutive errors on the same tool, hand back to the Coordinator. |
| LLM failure | §4.7 router and degraded modes |
| Runaway / loop | `recursion_limit`, ≤8 tool calls per agent run, repeated-call detector, active-time deadline (default 240 s, paused time excluded), cost cap → finalize with limitations (still verified-only) |
| Worker crash | Lease expiry → reconciler → resume on the same `thread_id` (§3.7) |
| Cancel | §3.7 |
| Out-of-scope query | Polite failure listing supported domains (§4.2). No analysis is fabricated. |

### 3.6 Report, claim and chart contract (mandatory evidence validation)

```
Computation {id, fingerprint (§3.7), tool, method_version, params, input_series:[SeriesRef],
             result:{field: {value, metric, unit, scale, interval:{start,end}, value_kind: level|change|pct_change|pp_change|rate|coefficient|projection}},
             eligibility:"ok", interpretation_allowed: descriptive|exploratory_association|projection}
SeriesRef   {normalized_artifact_id (§4.6), series_key, identity:SeriesIdentity (§4.3), periods_used[]}
Predicate   {id (e.g. "change.increase"), allowed_tools, allowed_value_kinds, sign_rule, template}   # closed registry
Assertion   {predicate_id, computation_id, field, metric, input_identities, interval:{start,end}}
Claim       {id, kind: measured|comparison|association|projection|recommendation|limitation,
             assertions:[Assertion], rendered_text, interpretation, status: verified|removed, checks:[{name, pass, detail}]}
Citation    {id, dataset_version_id, series_keys, periods, publisher, origin_agency, platform,
             url_human, url_api, retrieved_at, source_updated_at}     # derived from bindings→computation lineage
Chart       {id, type, series:[SeriesRef|computation_id], period_range, unit, citation_ids}
ReportBlock {id, heading, claim_ids, chart_ids, caveats[]}
Report      {analysis_id, version, status: final, blocks, limitations[], verification_summary, provenance_manifest}
```

**How claims are written.** The LLM does not write numeric sentences freely. It picks predicates from a **closed registry**, for example:
- `level.at` — "X was {v} in {t}"
- `change.increase` / `change.decrease` — "X rose/fell by {v} between {t0} and {t1}"
- `cagr.value`
- `period.compare`
- `assoc.positive` / `assoc.negative` / `assoc.weak`
- `limitation.insufficient_evidence`

It binds each predicate to a specific computation **field**, and the renderer produces the numeric text from the predicate template. The LLM may add only connective prose between rendered assertions.

**Deterministic checks**, applied to every claim, chart, composed narrative, caveat and export whatever the analysis status:
1. **Resolution.** Each assertion's `computation_id` and `field` resolve to an `eligibility=ok` computation of this analysis.
2. **Predicate fit.** The predicate allows the computation's tool and the field's `value_kind`. A level can never be presented as a change. A coefficient can never be presented as a measured change.
3. **Metric equality.** The assertion `metric` equals the field's metric (e.g. `employment_level` ≠ `employment_change` ≠ `vacancies`).
4. **Identity equality.** The assertion `input_identities` equal the computation's input identities: code set, classification version, population, measure type, reference convention.
5. **Interval equality.** The assertion interval **equals** the field's evaluation interval, not merely lies within it. A sub-period claim needs its own sub-period computation. For example, a 2020–2024 change cannot be restated as a 2023–2024 change.
6. **Unit and scale.** These come from the field (%, pp, persons, thousands) and are rendered by the template.
7. **Sign rule.** The predicate's sign rule holds on the bound value (e.g. `change.increase` requires change > 0). Direction is never inferred from the sign of a level.
8. **Kind allowed.** The claim `kind` is permitted by `interpretation_allowed`. `association` comes only from `correlate`, `projection` only from `forecast`.
9. **No free numbers.** No numeric literal outside rendered assertions in claims, **composed narrative and caveats**. Years are allowed only if they equal an asserted interval endpoint.
10. **No causal language** (lexicon: *caused, led to, drove, due to, because of, resulted in, impact of*) in any text, **hedged or not**.
11. **Recommendations** contain no assertions with numbers. They may reference claim IDs and are rendered in a separate "Considerations (not findings)" block.
12. **Citations** are generated from lineage; the LLM cannot author or alter them.

**Qualitative check (LLM)** applies only to the remaining connective prose. It checks faithfulness of wording (e.g. "surged" for +2% fails) and flags any *unsupported addition* in the composed narrative that no verified claim supports. A flagged sentence is removed.

**Failures:** a claim that fails is sent back to Analytics once with the reasons. If it still fails, it is **removed**. When removal leaves a sub-question unanswered, a deterministic limitation statement replaces it ("Evidence for X was insufficient: reason code").

**Status semantics.** `completed` = all sub-questions answered by verified claims. `completed_with_limitations` = some sub-questions answered only by limitations. In both cases, **only verified claims reach dashboards and exports.**

**Streaming.** Activity events stream live. Report blocks are published only after verification. Draft narrative streaming is enhancement #5, clearly segregated.

### 3.7 Durable job lifecycle and idempotency

**States:**
- `queued → running → {awaiting_input → queued (resume)} → completed | completed_with_limitations | failed | cancelled`.
- A row has `cancel_requested_at` while running.

**Persisted fields (`analyses`):** `status`, `row_version` (optimistic concurrency), `thread_id` (= analysis_id, stable across attempts), `execution_epoch` (fencing token), `attempt`, `lease_owner`, `lease_expires_at`, `heartbeat_at`, `cancel_requested_at`, `clarification_version`, `pending_interrupt_id`, `active_ms_used`, `last_event_seq`, `graph_version`, `prompt_version`.

**Persisted fields (`outbox` = durable run intents):** `id`, `analysis_id`, `kind` (start|resume), `payload`, `delivery_generation`, `dispatched_at`, `acked_at` (set by the worker when it takes the lease for this intent), `superseded_at`.

**Mechanics:**
- **Transactional outbox.** `POST /analyses` inserts the analysis and an intent (`kind=start`, `delivery_generation=1`) in one transaction. A dispatcher loop in the API and the worker cron push to arq with `job_id = {analysis_id}:{intent_id}:{delivery_generation}`, then set `dispatched_at`. arq dedup is a convenience only; **durability comes from the Postgres acknowledgement, not Redis keys**.
- **Atomic claim (F1 + F2).** A worker claims an intent in **one transaction** that does all of the following:
  1. takes the lease: `lease_owner`, `lease_expires_at = now()+60s`, conditioned on `status IN ('queued','running')` and no live lease;
  2. sets `status = 'running'`;
  3. increments `execution_epoch` (the fencing token) and `attempt` (the **execution attempt**);
  4. sets `acked_at` on this intent;
  5. sets `superseded_at` on every other unacked intent for the analysis.
  
  If any condition fails, nothing commits. A job whose intent is already acked or superseded, or whose analysis is terminal or `awaiting_input`, exits without side effects.
- **Two separate counters.**
  - `outbox.delivery_generation` counts **delivery retries**, i.e. re-dispatches of an intent no worker acknowledged. Redelivery never touches `analyses.attempt`.
  - `analyses.attempt` counts **execution attempts**: claims that actually started running. Only execution attempts count against the crash-recovery allowance (≤3). Queue loss therefore cannot use up the recovery budget.
- **Fencing (F2).**
  - **Execution ownership is enforced by the lease plus epoch fencing.** Every authoritative write is conditioned on `execution_epoch = :my_epoch`: lease renewals, event appends (inside the seq-allocation update), computation and report writes, status transitions, **and LangGraph checkpoint writes**.
  - Checkpoint writes go through a thin wrapper around the Postgres checkpointer. It runs the epoch check and the checkpoint write **atomically in the same transaction**.
  - A transaction-level advisory lock (`pg_advisory_xact_lock(analysis_id)`) held in that transaction **serialises checkpoint commits** for an analysis. It does not serialise graph execution itself; the lease and epoch do that.
  - When a renewal or any fenced write affects 0 rows, the worker raises `LeaseLost`, cancels in-flight LLM/HTTP calls and exits without further writes.
- **Reconciler** (arq cron, every 15 s, independent of restarts). It handles three cases:
  - **(a)** an intent never dispatched → dispatch;
  - **(b)** an intent **dispatched but not acked** for more than 60 s, with the analysis still `queued` → bump `delivery_generation` and re-dispatch. This covers jobs lost in Redis before pickup;
  - **(c)** a `running` analysis with an expired lease → if the execution `attempt < 3`, write a new `resume` intent (the epoch is bumped on the next claim, which fences the old owner); else `failed` with an error event. Delivery retries from case (b) do not count here.
  
  It never re-dispatches for terminal or `awaiting_input` analyses. A healthy long run keeps renewing its lease and is never reaped.
- **Evidence and method fingerprint (F3).** Each tool result and computation is keyed by `fingerprint = sha256(canonical_json{tool, method_version, normalized_artifact_ids[] (§4.6), series_identities[], selected_periods[], transform_version, taxonomy_version, numerical_options, display_rounding_version})`.
  - Persisted as `computations UNIQUE (analysis_id, fingerprint)` with `ON CONFLICT DO NOTHING`. The same fingerprint is used for the tool-result cache.
  - The same evidence and options on retry reuse the result. Any change in source version, series, period, transform or method produces a new computation.
- **Other idempotent effects:**
  - normalised artifacts are content-addressed;
  - events unique on `(analysis_id, seq)`;
  - the report is written once per epoch-fenced finalize;
  - a node restarted from its beginning (LangGraph resume semantics) hits the fingerprint cache instead of refetching or duplicating.
  - **LLM calls may repeat on resume. We do not promise exactly-once LLM billing.**
- **Clarification.** The node calls `interrupt({interrupt_id, version})`. The worker sets `awaiting_input`, stores `pending_interrupt_id`, **releases the lease and ends the job**. The active deadline clock pauses. `POST /clarify` does a conditional update `WHERE status='awaiting_input' AND clarification_version=$v`, then bumps the version and writes `outbox(resume, payload)` in one transaction. The worker resumes with `Command(resume=answer)` on the same `thread_id`. Responses:
  - stale or duplicate version → **409** `CLARIFICATION_STALE`;
  - not awaiting input → **409** `NOT_AWAITING_INPUT`.
- **Cancel:**
  - `queued` or `awaiting_input` → conditional update to `cancelled`;
  - `running` → set `cancel_requested_at`; the worker checks it between nodes and tool calls, then moves to `cancelled`;
  - terminal → **409** `ALREADY_TERMINAL`.
  - A clarify/cancel race is settled by `row_version`: exactly one wins and the other gets 409.
- **Redis restart.** The queue is rebuilt from unacked intents and expired leases (reconciler cases b and c). Pub/sub loss means WS clients fall back to the DB drain timer. Rate-limit buckets fall back to conservative per-process limits.
- **Checkpoint compatibility.** Resume only if the stored `graph_version` major matches. Otherwise mark `failed` (`INCOMPATIBLE_CHECKPOINT`) with a "re-run" action that reuses cached evidence.

### 3.8 Event delivery (no lost or duplicated UI events)
- **Emit:** in one transaction, `UPDATE analyses SET last_event_seq = last_event_seq+1 RETURNING last_event_seq`, then `INSERT event`, then commit. After commit, `PUBLISH analysis:{id} seq` as a **hint only**.
- **WS handler:**
  1. subscribe to the hint channel first;
  2. loop: drain `SELECT … WHERE seq > cursor ORDER BY seq LIMIT 200` → send → advance the cursor;
  3. wait for a hint **or a 2 s timer**;
  4. repeat until a terminal status event has been sent and the drain is empty.
  
  Because each drain re-reads committed rows, an event published during replay or a publish dropped after commit is still delivered.
- **Client:** dedupes by `seq` and ignores `seq ≤ cursor`. If it detects a gap, it reconnects with `after_seq=cursor`.
- **Slow clients:** bounded per-connection send queue of 500. On overflow the server closes with code 4008 and the client reconnects with its cursor.

---

## 4. Data Integration and AI Reliability

### 4.1 Facts verified live (24–25 Oct 2026)
- **SingStat Table Builder:** `GET tablebuilder.singstat.gov.sg/api/table/tabledata/{id}`, no key.
  - **`limit`/`offset` count data points, not rows.** A series can be split across pages, so the connector merges fragments by `seriesNo`.
  - Values are strings.
  - Hierarchy is held in `seriesNo` (e.g. `1.2.4` ICT parent, `1.2.4.2` IT & Other Information Services child).
  - Keyword search: `/api/table/resourceid?keyword=`.
- **Data.gov.sg:**
  - datastore JSON at `data.gov.sg/api/action/datastore_search?resource_id=`;
  - CSV via `api-open.data.gov.sg/v1/public/api/datasets/{id}/initiate-download` → `poll-download` (signed S3 URL);
  - metadata at `api-production.data.gov.sg/v2/public/api/datasets/{id}/metadata`.
  - Published limits without a key are 4 datastore calls and 2 download calls per 10 s. **A 429-style rejection was actually observed** during probing.
- **MOM Statistics:** `.xlsx`/`.csv` links on `stats.mom.gov.sg/Pages/EmploymentTimeSeries.aspx` have **release-dated filenames**. Workbooks have one sheet per SSIC version, with `-` and `^` markers.
- **Definitions that matter:**
  - **MOM annual vacancies = mean of the four quarterly values, rounded to 100.** Verified for ICT, e.g. 2022: quarterly mean 10,325 → published 10,300.
  - SingStat M182841 = **year-end** employment, from admin records plus LFS self-employed, classified under SSIC 2020 from 2008.
  - Data.gov.sg `d_d2518fed6cc2014f0cd061b4570a9592` **mirrors** M182841, with MOM as the origin agency.
  - Quarterly ICT vacancy values are identical on SingStat M184071 and Data.gov.sg `d_3f17bbf67d31d4d402caa8755eb74afc` (same origin).

### 4.2 Source manifest (`data/manifest/sources.yaml`) and supported domain

Each entry records:
- dataset identity (full ID), canonical human and API URLs;
- platform, publisher, **origin agency**;
- format;
- **reference-period convention**, **classification system and version** (from metadata/footnotes), units and scale, frequency, coverage;
- footnotes, marker legend, licence/terms **as stated by the source**;
- retrieval date and validation evidence (fixture hash, last validated).

Initial curated entries (a 12–15-entry boundary; IDs to be re-confirmed in the Day-1 spike):

| Dataset | Platform / origin | Identity notes |
|---|---|---|
| `M182841` Employment (Persons) by Sector, annual | SingStat / MOM | Year-end stock, thousands, SSIC 2020 (from 2008) |
| `M183891` Changes in Employment by Sector, quarterly | SingStat / MOM | Quarterly flow (end-of-quarter difference), persons |
| `M184071` Job Vacancies by Industry & Occupational Group (SSIC 2020), quarterly | SingStat / MOM | End-of-period stock; rounded to 100 |
| `M184021` / `M184041` Average Monthly Recruitment Rate by Industry (SSIC 2020), quarterly / annual | SingStat / MOM | Rate, %, average over period |
| `M184031` / `M184051` Average Monthly Resignation Rate, quarterly / annual | SingStat / MOM | Rate, % |
| `M182081` Employed Residents by Industry & Occupation (June) | SingStat / MOM LFS | **Residents only**, June reference |
| `d_01966fdb498fa7fa2863635e25539693` Job Vacancy by Industry — Annual | Data.gov.sg / MOM | **Annual = quarterly average** |
| `d_3f17bbf67d31d4d402caa8755eb74afc` Job Vacancy by Industry — Quarterly | Data.gov.sg / MOM | Mirrors M184071 |
| `d_74803e94c5299493f76d71c8994c50c1` Job Vacancy Rate by Industry & Occupation — Quarterly | Data.gov.sg / MOM | Rate, % |
| `d_000d49cda016c13522d7d5be6a050f59` Number of Retrenched Employees — Quarterly | Data.gov.sg / MOM | Total only |
| `d_d2518fed6cc2014f0cd061b4570a9592` Employment by Sector (mirror of M182841) | Data.gov.sg / MOM | Used for the cross-platform consistency check |
| MOM `mrsd_4_annl_emp_chg_by_ind_*.xlsx`, `mrsd_3_qtly_emp_chg_by_ind_*.xlsx/.csv` | MOM site / MOM | Discovered by prefix pattern; SSIC sheet selection |

**Supported domain:** the Singapore labour market by industry — employment levels and changes, vacancies, recruitment, resignation, retrenchment — at national level.
**Out of scope** (e.g. housing prices, health, forecasts beyond the data): a clear unsupported result. Live SingStat discovery can surface other tables, but they are marked uncurated and used only if they parse and validate. Their identity metadata must be complete, or they are refused.

### 4.3 Series identity and join rules (fixes the taxonomy error)

`SeriesIdentity = {classification_system, classification_version, code_set (e.g. SSIC2020:J58-63), hierarchy_level, population (total employment | residents | establishments), measure_type (stock | flow | rate | average), unit, scale, frequency, reference_convention (year_end | june | quarter_end | period_average | monthly_average)}`.
- **Normalisation:** only capitalisation, whitespace, `&`↔`and`, and genuine synonyms recorded in `taxonomy.yaml`.
- **Parent and child stay separate:** "Information & Communications" (J58–63) and "IT & Other Information Services" (J62–63) are different identities.
- **No join by letter alone:** SSIC 2020 J and SSIC 2025 J are incompatible without a crosswalk, and no crosswalk is assumed.
- **Roll-up** is allowed only over documented, mutually exclusive and complete child sets. Otherwise compare side by side or refuse (`INCOMPATIBLE_IDENTITY`).
- **Comparisons and correlations** require identical classification version and code set, a compatible population and reference convention, and the same frequency. Otherwise refuse with a reason code.
- **Acceptance fixtures:**
  - a parent+child fixture stays distinct;
  - 2020-J vs 2025-J refuses;
  - parent+child sum refuses;
  - an unknown crosswalk produces a disclosed incompatibility.

### 4.4 Ingestion, cleaning, markers
- **Tidy schema** (pandera): `series_key, identity_ref, period, period_start, period_end, value (Decimal-safe float | null), marker_code, unit, scale, dataset_version_id`.
- **Markers** keep their **source-defined meaning**, parsed from footnotes or legends and recorded in the manifest. Examples: nil/negligible, not available, suppressed, provisional, revised, footnote reference.
  - Unknown markers → `marker_code=unknown`, value null, flagged in the QualityReport.
  - Footnote symbols such as `^` are stripped from labels and recorded as annotations.
- **Rate limiting:** Redis-backed token buckets per endpoint class, **shared across workers**. Datastore and download buckets are set to the published limits. `DATAGOV_API_KEY` raises the limits if registered.
- **Pagination** is verified per endpoint:
  - SingStat: point-based paging with fragment merging;
  - datastore: `offset`/`limit` until `total`;
  - downloads: initiate → poll with a bounded wait.
- **MOM discovery:** scrape the time-series page for a prefix pattern and pick the newest by embedded date. Fall back to the last-known URL, then to a snapshot.
- **Cross-platform consistency check:** for mirrored series, values must match exactly. A mismatch is a quality issue, reported and not silently resolved.

### 4.5 Method policy (eligibility, outputs, refusal codes)

| Tool | Eligible when | Output | Refusal codes |
|---|---|---|---|
| `yoy_change` | Actual prior-year period exists (annual: t−1; quarterly: same quarter t−4); both values non-null | Absolute change; % change for stocks and flows; **pp change for rates** | `MISSING_PRIOR_PERIOD`, `ZERO_BASE`, `NULL_VALUE` |
| `cagr` | Stock/level measure; both endpoints >0; elapsed years from `period_start` dates ≥2 | Annualised % with elapsed years stated | `NOT_A_LEVEL`, `NON_POSITIVE_ENDPOINT`, `INSUFFICIENT_SPAN` |
| `trend` | ≥5 annual or ≥12 quarterly non-null points; not constant | OLS slope per year in source unit. For quarterly n≥12, **HAC (Newey-West) SEs**. Annual n<8 → descriptive slope only, no interval. Interval labelled a *parameter confidence interval*. | `INSUFFICIENT_POINTS`, `CONSTANT_SERIES` |
| `compare_periods` | Same identity; both windows have ≥1 non-null | Mean/sum difference per declared aggregation | `EMPTY_WINDOW`, `INCOMPATIBLE_IDENTITY` |
| `correlate` | Same frequency (quarterly); identical classification version and code set; **≥12 aligned complete pairs**; no constant series; the pair satisfies a **declared pairing rule** (below) for the stated lag | Pearson and Spearman with actual aligned n and the stated lag. **No p-values** (descriptive, exploratory). Labelled *exploratory association; observations are serially dependent; not causal*. Population differences are listed as caveats. | `FREQ_MISMATCH`, `REFERENCE_MISMATCH`, `NO_PAIRING_RULE`, `INSUFFICIENT_PAIRS`, `CLASSIFICATION_MISMATCH`, `CONSTANT_SERIES` |
| `forecast` *(enhancement)* | ≥16 quarterly points; rolling-origin backtest beats naive MAE | Point forecast + **prediction interval**, labelled *projection* | `INSUFFICIENT_HISTORY`, `FAILS_BACKTEST` |

**Pairing rules for `correlate`** (method-specific compatibility; F5). Each pair of measure types needs a rule that defines which observations align at a given lag:

| Pair | Lag 0 alignment | Lag 1 alignment |
|---|---|---|
| `stock@quarter_end` × `flow over quarter (end-to-end difference)` | Stock at end of Q_t with flow over the quarter ending Q_t (shared end date) | Stock at end of Q_t with flow over Q_t+1 (stock leads) |
| `stock@quarter_end` × `stock@quarter_end` | Same quarter end | — |
| `rate (monthly average within quarter)` × `stock@quarter_end` | Same quarter; caveat that the rate averages within the quarter | — |

Any other combination is refused with `NO_PAIRING_RULE`. Mixing an annual year-end stock with an annual quarterly-average stock is refused with `REFERENCE_MISMATCH`.

**First differences** are optional robustness only. They are computed only between consecutive quarters where both are present. A change across a missing quarter is never treated as a one-quarter difference. n levels give at most n−1 differences.

**Named demo pair (confirmed live 25 Oct 2026; to be pinned in the Day-1 manifest).**
- **Series X:** SingStat **M184071** series `1.2.4` *Information And Communications*, job vacancies.
  - Stock at quarter end ("End Of Period"), establishments survey.
  - SSIC 2020 from 2006. Persons, rounded to 100.
  - Data from 2006 Q1.
- **Series Y:** SingStat **M183891** series `1.2.4` *Information & Communications*, employment change.
  - Flow: difference between end-of-quarter employment levels. Total employment.
  - SSIC 2020 from 2009. Persons.
  - Data from 2017 Q1.
- **Research question:** "In quarters when more ICT vacancies were open at quarter end, was ICT employment growth over the same quarter (lag 0) and the next quarter (lag 1) stronger?" This is an exploratory, labour-demand vs realised-hiring association.
- **Alignment:** pairing rule row 1.
  - 2020 Q1–2024 Q4 gives **n=20 at lag 0**.
  - **n=19 at lag 1** (2024 Q4 vacancies have no in-window Q+1 flow; extended to 2025 Q1 only if the plan's period allows).
  - Actual aligned n is recomputed after missingness and reported.
- **Caveats recorded:** different populations (establishment survey vs administrative total employment); vacancies rounded to 100; labels differ only by `&`/`and`, a recorded synonym.
- **Golden expectations:** Pearson/Spearman values for both lags, computed independently from the snapshot by the eval script.

**Rules:**
- No series is resampled by repetition. Annual is never converted to quarterly.
- Unit scales are normalised internally and displayed in source units.
- Display rounding policy: persons to source precision (e.g. thousands to 1 dp); % and pp to 1 dp. The verifier compares values after display rounding.

**Demo consequence.** For "technology sector 2020–2024":
- The **annual year-end employment level** (M182841, n=5) gets descriptive trend, YoY and CAGR.
- **The named pair above** (M184071 ICT vacancies × M183891 ICT employment change, lag 0 n=20 and lag 1 n=19) gets the exploratory correlation. Data.gov.sg `d_3f17bbf67d31d4d402caa8755eb74afc` supplies the cross-platform mirror check on the vacancy series.
- **Annual year-end employment vs annual vacancies** (a quarterly average) is **refused with `REFERENCE_MISMATCH`**. That refusal is a visible, explainable decision in the demo.

### 4.6 Provenance and reproducibility tiers
- **Two immutable identities:**
  - **raw payload** = `sha256(bytes)`;
  - **normalised artifact** = `sha256(canonical normalised observations, source metadata/footnotes hash, parser version, taxonomy version, marker-legend version)`. It deliberately excludes the raw hash, because unchanged data can arrive with different bytes (Day-1 outcome).
  
  A data revision, metadata change or parser/taxonomy change creates a new normalised artifact. A byte-only change such as a response timestamp does not. Computation fingerprints (§3.7) reference normalised artifacts, not raw downloads. Old analyses keep their pinned artifacts, values, citations and report.
- **Stored with every analysis:** dataset version IDs, normalised observations, parser/transform version, taxonomy version, method version + params, display-rounding version, prompt/schema versions, model IDs, final report and chart JSON.
- **Three tiers:**
  - **Reopen**: byte-identical stored result. Guaranteed.
  - **Recompute**: deterministic outputs from the same evidence, within declared tolerances. Tested.
  - **Regenerate**: a fresh LLM narrative. Not identical and not promised.
- **`DATA_MODE=snapshot`** means offline *data retrieval* from committed real-data snapshots (manifest of URL, retrieval date, hash). Live LLMs still need network access. **Fully offline CI = snapshots + ScriptedLLM.**

### 4.7 LLM reliability, provider probe and degraded behaviour
- **Day-1 capability probe** (`scripts/probe_llm.py`) for the chosen Bedrock model (primary, region per account) and the OpenAI model. It tests:
  - tool call;
  - structured (Pydantic) output;
  - one full ReAct turn on a fixture;
  - streaming, if enhancement #5 is retained.
  
  Model IDs (`BEDROCK_MODEL_ID`, `BEDROCK_REGION`, `OPENAI_MODEL`) are fixed only after the probe passes. Until then, model selection is tracked as dependency D1.
- **Router:**
  - Message and tool-result normalisation at the router boundary.
  - **SDK-level retries disabled.** OpenAI client `max_retries=0`. Bedrock client `botocore.config.Config(retries={"total_max_attempts": 1, "mode": "standard"})`, which means exactly one HTTP request (note: `max_attempts=1` would still allow one retry).
  - The router owns retries: ≤2 attempts per provider on 429/5xx/timeout/throttling, jittered backoff.
  - Router retries, the structured-output repair retry and fallback all draw from **one total LLM deadline per call site**.
  - Per-call timeout: 20 s for routing, 45 s for narrative. Each call is capped by `remaining_deadline − fallback_reserve (30 s)`.
  - Circuit breaker per provider (opens after 3 consecutive failures for 60 s).
  - Structured-output repair: 1 retry.
  - No LLM retries at node level. The queue retries only for crash recovery.
  - Superseded streams are cancelled, and partial text is discarded.
- **Ledger:** `llm_calls` (provider, model, purpose, tokens, latency, cost from config price table, ok, fallback_from).
- **Degraded modes:**
  - one provider healthy → all deterministic checks still run; the qualitative check uses the same provider with `verifier_independence: unavailable` recorded;
  - both fail **after** verified computations exist → a template report built from deterministic claim templates bound to computations (fully verified), status `completed_with_limitations` ("narrative unavailable");
  - both fail **before** a plan or evidence exists → `failed` (`LLM_UNAVAILABLE`), with no implication that any analysis was done.

---

## 5. Technology Decisions

| Area | Choice | Why | Trade-off |
|---|---|---|---|
| Frontend | Next.js 15 App Router, TypeScript, Tailwind, shadcn/ui, TanStack Query, `openapi-typescript` | Typed end to end; fast, accessible UI | Mostly client components |
| Charts | Recharts | React-idiomatic, light, covers line/bar/scatter | Fewer exotic chart types (not needed) |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, asyncpg | Async REST + WS, OpenAPI | — |
| Agents | LangGraph with custom ReAct subgraphs, Postgres checkpointer | Explicit control of events, guards, budgets, interrupts, resume | A little more code than prebuilt agents |
| LLMs | `langchain-aws` `ChatBedrockConverse` (primary), `langchain-openai` (fallback), own `LLMRouter` | Uniform tool calling; router owns retries, circuit breaking, ledger | Small router to maintain |
| Jobs | arq + transactional outbox + lease/reconciler in Postgres | asyncio-native; durability lives in Postgres, not Redis | We implement the outbox (small) |
| DB | PostgreSQL 16 (pgvector image so enhancement #4 needs no new service) | One authoritative store | — |
| Catalogue search | Postgres full-text + synonym table (core); pgvector with one embedding model (enhancement) | Lexical retrieval suffices for 12–15 entries; **embedding spaces of different models are not interchangeable** | — |
| Data/stats | pandas, NumPy, SciPy, statsmodels (OLS/HAC), pandera, openpyxl | Credible, testable statistics | Image size |
| HTTP | httpx + tenacity + Redis token bucket | Async, shared limits | — |
| Tests | pytest, respx, ScriptedLLM, Vitest + RTL, Playwright, Locust | — | — |
| Tooling/infra | uv, ruff, mypy (core), ESLint, gitleaks, Docker Compose, GitHub Actions, GHCR | — | No Kubernetes, deliberately |

---

## 6. Repository Structure

```
agentic-policy-analytics/
├─ backend/app/
│  ├─ main.py
│  ├─ api/          analyses.py datasets.py sources.py ws.py admin.py problems.py
│  ├─ core/         config.py logging.py faults.py
│  ├─ db/           models.py session.py repositories.py
│  ├─ jobs/         outbox.py lease.py reconciler.py lifecycle.py   # §3.7
│  ├─ events/       emit.py drain.py                                # §3.8
│  ├─ agents/       state.py graph.py coordinator.py extraction.py analytics.py react.py guards.py prompts/
│  ├─ tools/        data_tools.py analytics_tools.py
│  ├─ connectors/   base.py http.py ratelimit.py singstat.py datagov.py mom.py
│  ├─ data/         identity.py taxonomy.py schemas.py cleaning.py markers.py profiling.py
│  ├─ analytics/    policy.py trends.py correlation.py compare.py charts.py forecast.py(enh)
│  ├─ grounding/    contracts.py checks.py qualitative.py render.py citations.py   # §3.6
│  ├─ llm/          router.py providers.py circuit.py scripted.py pricing.py
│  └─ worker/       settings.py tasks.py
├─ backend/alembic/  backend/tests/{unit,integration,lifecycle,data_quality,llm_eval,load}/  backend/tests/fixtures/recorded/
├─ frontend/src/{app,components,lib}/  frontend/tests/  frontend/e2e/
├─ data/manifest/sources.yaml  data/taxonomy.yaml  data/snapshots/(real payloads + manifest.json)
├─ eval/golden/ (queries.yaml, expected/*.json, adversarial_claims.yaml)  eval/results/
├─ scripts/probe_llm.py  scripts/capture_snapshots.py
├─ docs/INNOVATION.md  docs/DEMO_SCRIPT.md  docs/diagrams/
├─ .github/workflows/{ci.yml,release.yml,live-eval.yml}
├─ docker-compose.yml  docker-compose.prod.yml  .env.example  Makefile
└─ README.md ARCHITECTURE.md TESTING.md DATA_SOURCES.md
```

**DB tables:**
- `analyses` (lifecycle fields §3.7)
- `outbox`
- `analysis_events` (unique analysis_id+seq)
- `datasets` → `dataset_versions` (sha256, retrieved_at, source_updated_at, metadata, footnotes, marker legend, quality)
- `raw_payloads` (sha256 PK)
- `series_identities`
- `observations` (dataset_version_id, series_key, period…, value, marker_code)
- `analysis_dataset_versions`
- `normalized_artifacts` (artifact id = §4.6 hash; raw sha256; parser/taxonomy/marker versions)
- `computations` (unique analysis_id+fingerprint, §3.7)
- `outbox` intents (delivery_generation, dispatched_at, acked_at, superseded_at)
- `reports` (analysis_id, version, JSON incl. claims, checks, citations, charts)
- `llm_calls`
- LangGraph checkpoint tables

---

## 7. Milestones — 10 working days

Docs, tests and CI are kept current within each milestone, not left to the end.

**Gates.**
- **Hard gates (H)** are non-waivable. A miss blocks release readiness and all enhancement work. Reporting a miss honestly is required, but **it never converts the miss into a pass**. The failing artifact and a remediation note are kept.
- **Documented targets (T)** may be missed with a justified, honest report.

| Gate | Class | Condition |
|---|---|---|
| G1 | H | Probe passes on both providers (or D1 resolved with a replacement model that passes) |
| G2 | H | **Primary demo success:** live two-platform E2E produces a verified report for the example query |
| G3 | H | **Claim validity:** every §3.6 check is enforced on every retained claim, chart, narrative, caveat and export; adversarial deterministic categories at 100% recall |
| G4 | H | **Lifecycle integrity:** all §8.1 lifecycle and WS failure tests green |
| G5 | H | **Calculation accuracy:** method-policy fixtures and golden computations 100% within tolerance |
| G6 | H | Retained-claim correctness = 0 failures in live golden runs; refusal correctness 12/12 |
| G7 | H | Hosted CI green, including the compose smoke job |
| G8 | H | Docs + innovation essay + two timed fresh-clone rehearsals done |
| T1 | T | Load latency/throughput targets (§8.4) — zero lost terminal results and zero correctness failures under load are **H** (part of G4/G5) |
| T2 | T | Coverage ≥80% on core packages |
| T3 | T | Consistency, qualitative-check recall, false-positive rate ≤5%, human-reviewed relevance ≥10/12 |
| T4 | T | Live cost and latency per analysis |

The release checklist (§9.4) **refuses readiness** while any H gate fails.

### Day 1 — M0: Spike and scaffold
- **Deliverables:**
  - capture snapshots + manifest entries (full IDs, definitions, markers, pagination behaviour);
  - run `probe_llm.py` on Bedrock (primary) and OpenAI;
  - monorepo scaffold, compose (postgres, redis, migrate, api, worker, web), `/api/health`;
  - Alembic baseline, `.env.example`, Makefile;
  - CI (lint + unit) **running green on GitHub**.
- **Depends on:** credentials; your go-ahead to push to `origin`.
- **Decisions:** model IDs and region (D1); final demo series set.
- **Acceptance:** the probe report shows tool call, structured output and a ReAct turn for both models. `docker compose up` comes up healthy. Hosted CI is green.
- **Tests:** health test; snapshot hash verification.
- **Risks:** Bedrock model access missing in region → choose another enabled model/region or escalate D1 the same day.
- **DoD:** G1 met, and manifest entries are recorded for every demo dataset.

### Days 2–4 — M1: Verified two-platform vertical slice
- **Deliverables:**
  - SingStat (point-paged, fragment merge) and Data.gov.sg datastore connectors;
  - `SeriesIdentity` + join rules;
  - tidy schema with basic validation and markers;
  - `yoy_change`, `cagr`, `trend`, `compare_periods` with policy;
  - computation registry keyed by evidence/method fingerprint;
  - **§3.6 predicate registry, contracts and deterministic checks** with lineage-derived citations;
  - outbox + lease + `thread_id`; event emit/drain WS;
  - LangGraph Coordinator / Extraction / Analytics with real LLM decisions and guards;
  - router with Bedrock → OpenAI fallback (SDK retries off) and budgets;
  - minimal UI: query, timeline, line chart, verified report, citations.
- **Depends on:** M0.
- **Decisions:** event schema and claim contract frozen (versioned).
- **Acceptance:** the demo query runs live on Bedrock and on forced-OpenAI. The report cites SingStat and Data.gov.sg dataset versions. ICT values match M182841 exactly. No unbound numbers. Extraction's fitness decision is visible.
- **Tests:** connector fixture tests (incl. split-row paging); identity join tests (parent/child, 2020-J vs 2025-J); tool eligibility fixtures; check-suite unit tests; scripted graph integration test; basic WS drain test.
- **Risks:** M1 is the densest milestone → scope only to what G2 needs. No dashboard polish.
- **DoD:** G2 met, with a live trace saved.

### Days 5–6 — M2: Formats, quality, recovery contracts, verification completeness
- **Deliverables:**
  - MOM discovery + xlsx/csv parser (SSIC sheet selection);
  - Data.gov.sg CSV download path;
  - source-defined marker semantics; cross-platform consistency check;
  - QualityReport panel; shared Redis rate limiter;
  - snapshot mode + dataset versioning;
  - `correlate` with quarterly pair + `REFERENCE_MISMATCH` refusal;
  - qualitative LLM check + reject/rewrite loop;
  - clarification interrupt/resume with versioned 409s; cancel;
  - reconciler cases (a)–(c) with delivery generation + acknowledgement;
  - execution-epoch fencing, including the fenced checkpointer wrapper;
  - circuit breaker; degraded modes; fault injection (dev only).
- **Depends on:** M1.
- **Acceptance:** every named lifecycle and WS failure test passes (§8.1). All mutation classes are detected. A clarification round-trip works. Fallback works in both directions.
- **Tests:** §8.1 lifecycle/WS suite; data-quality mutation suite; router fault tests; degraded-mode tests.
- **Risks:** MOM page change → last-known URL + snapshot.
- **DoD:** G3, G4 and G5 met.

### Days 7–8 — M3: Product completeness, evaluation, load, delivery
- **Deliverables:**
  - keyset-paginated history; exports (MD/JSON/CSV);
  - dashboard interactions and responsive layout; clarification dialog; cost/latency badges;
  - Playwright E2E (scripted + snapshot);
  - golden set + adversarial suite + live golden runs on both providers;
  - Locust run; coverage reports;
  - compose smoke + GHCR publish in CI; `docker-compose.prod.yml` with faults disabled;
  - ARCHITECTURE.md, DATA_SOURCES.md and TESTING.md written with real results.
- **Depends on:** M2.
- **Acceptance:** all H gates in §8.3 met. T targets met or honestly reported with justification. Hosted CI green end to end.
- **Tests:** as listed.
- **Risks:** live eval flakiness → semantic consistency evaluation, temperature 0, rerun policy documented. Rerunning never masks a hard-gate failure.
- **DoD:** G6 and G7 met.

### Day 9 — M4: Essay, rehearsal, demo assets
- **Deliverables:** docs/INNOVATION.md; README finalised; docs/DEMO_SCRIPT.md; pre-run history entries for each failure scenario; backup screen recording; **two timed fresh-clone rehearsals**.
- **Depends on:** M3 complete. G1–G7 passed.
- **Decisions:** which failure scenarios run live vs from pre-run history; demo machine and network fallback (snapshot mode).
- **Acceptance:** the rehearsal follows only the README. The demo fits within 16 minutes.
- **Tests:** a fresh-clone rehearsal runs `make test` and one live golden query. Doc links and commands are checked by a docs smoke script.
- **Risks:** an environment difference on a fresh machine → rehearse on a clean checkout/container, keeping the backup recording. Essay overclaiming → each "implemented" item cross-checked against code.
- **DoD:** G8 met.

### Day 10 — Contingency
- **Reserved** for outstanding H-gate failures and rehearsal findings.
- Enhancements are allowed **only after every H gate and both rehearsals pass**, in §1.3 order. Each ships with its own tests and doc updates, or not at all.
- The innovation essay cites only features that were actually delivered.

---

## 8. Testing Strategy

### 8.1 Named failure tests (lifecycle and WS)

Lifecycle:
- `test_crash_after_commit_before_enqueue_recovers_via_outbox`
- `test_dispatched_job_lost_in_redis_before_pickup_redelivered_once` (F1: enqueue, mark dispatched, flush Redis, restore → executes exactly once to a coherent result)
- `test_stale_worker_fenced_after_takeover` (F2: pause A past expiry, B takes over, resume A → A cannot renew, write checkpoint, append events or finalize)
- `test_fingerprint_reuse_on_retry_and_new_computation_on_change` (F3: same evidence reuses; changed source version, series, period, transform or method creates new)
- `test_no_redelivery_for_terminal_or_awaiting_input`
- `test_atomic_claim_sets_running_attempt_ack_and_supersedes`
- `test_delivery_retries_do_not_consume_execution_attempts`
- `test_crash_after_computation_write_resumes_without_duplicates`
- `test_duplicate_job_delivery_single_active_execution`
- `test_duplicate_clarify_returns_409_and_single_resume`
- `test_stale_clarification_version_409`
- `test_cancel_vs_clarify_race_single_winner`
- `test_redis_restart_queue_rebuilt_from_outbox`
- `test_expired_lease_reconciled_without_restart`
- `test_healthy_long_run_not_reaped`
- `test_clarification_pause_excluded_from_deadline`
- `test_incompatible_checkpoint_fails_cleanly`

WebSocket:
- `test_ws_publish_during_replay_no_loss`
- `test_ws_disconnect_mid_replay_resumes_from_cursor`
- `test_ws_dropped_publish_after_commit_converges_via_timer`
- `test_ws_duplicate_and_out_of_order_deduped`
- `test_ws_slow_client_overflow_reconnects`

Claim binding (F4):
- `test_rejects_valid_value_with_wrong_metric`
- `test_rejects_shorter_interval_restatement`
- `test_rejects_level_presented_as_change`
- `test_rejects_unsupported_addition_in_narrative_and_caveats`

Router (F6):
- `test_bedrock_sdk_single_http_request_per_router_attempt` (an injected retryable response produces 1 HTTP request per attempt; repair and fallback stay inside the total deadline)

### 8.2 Other layers
- **Unit:**
  - connectors (recorded real payloads, paging, 429);
  - identity/taxonomy; cleaning/markers;
  - method policy (an eligible and an ineligible fixture per tool, with every reason code);
  - grounding checks; router; guards; API (problem+json, pagination, 409s).
- **Agent tests with ScriptedLLM:** prove orchestration *mechanics* (routing, R-A-O emission, budgets, guard fallbacks), not model competence.
- **Integration:** full graph on Postgres/Redis service containers; scenarios include source outage, coverage re-plan, verifier rejection, out-of-coverage, out-of-domain.
- **Data quality:** schema conformance; mutation classes (dropped column, renamed label, new marker, duplicate period, unit/scale change, parent/child relabel, mirror mismatch).
- **Frontend:** Vitest (timeline reducer dedupe/gap logic, chart-from-spec equality, citation drawer, 409 handling); Playwright happy path + clarification at 3 viewports.
- **Coverage:** ≥80% line coverage target on backend `agents/ tools/ connectors/ data/ analytics/ grounding/ jobs/ events/`, reported from actual runs.

### 8.3 Evaluation gates (hallucination, accuracy, consistency)

**Golden set: 12 queries, pinned to snapshot manifest version.**
- Coverage: trend, YoY, CAGR, period comparison, quarterly correlation, refused annual correlation, subsector breakdown, ambiguous, out-of-coverage period, out-of-domain, plus two paraphrases.
- Each query has expected series identities, periods, units, refusal codes, and **independently computed expected values**. These come from a separate script working on raw snapshot values and are hand-reviewed.

**Tolerances:**
- exact for integer arithmetic on source values;
- relative 1e-9 for closed-form float formulas (YoY, CAGR);
- relative 1e-6 for iterative or statistical estimators (OLS/HAC, correlations);
- all compared after the declared display-rounding policy where displayed.

| Gate | Class | Method | Target |
|---|---|---|---|
| Computation accuracy (CI, scripted) | **H** | Registry vs expected | 100% within tolerance |
| Retained-claim correctness (CI and live) | **H** | All §3.6 checks on every retained claim, chart, narrative, caveat and export, any status | **0 failures** |
| Adversarial verifier suite — deterministic categories (CI) | **H** | ≥60 claims: 20 valid controls + ≥40 corrupted across wrong computation ref, wrong metric, shorter/longer interval, level-as-change, wrong unit (%/pp/scale), wrong direction, fabricated literal, tampered lineage, causal wording (hedged and unhedged), parent/child identity swap, unsupported narrative addition | 100% recall. Precision and recall reported per category. |
| Adversarial suite — valid-control false positives | T | Same suite | ≤5% |
| Adversarial suite — qualitative (LLM) category | T | Magnitude overstatement, unsupported prose | Recall reported, target ≥80% |
| Live golden runs (pre-demo, Bedrock-primary and OpenAI-primary) | **H** for refusal correctness 12/12 and 0 retained-claim failures; T for the rest | Real providers + snapshot data | Correct series identities in ≥11/12. Human-reviewed relevance ≥10/12. Autonomy evidence traces (MA-2) captured. |
| Consistency | T | 3 runs × 2 providers per query | Mean Jaccard of selected identities ≥0.8. Headline direction agreement 100%. Semantic equivalence judged by rubric (LLM judge + human spot check). |
| Provider resilience (live) | **H** | Fallback both directions, partial-stream failure, verifier-provider unavailable, total outage early and late | Behaviour matches §4.7 in every case |

### 8.4 Load (proposed engineering targets, not rubric requirements)
- **Workload:** ScriptedLLM + snapshot mode; stated machine (e.g. local Apple Silicon, compose defaults); 5-minute run.
  - 10 concurrent analyses continuously re-submitted;
  - 50 WS listeners;
  - 20 rps of history/detail reads.
- **Targets:**
  - zero lost terminal results;
  - zero correctness failures;
  - p95 `POST` ack < 300 ms;
  - p95 reads < 300 ms;
  - p95 event delivery (commit → client) < 1 s.
  
  Throughput, queue wait and error rate are reported.
- **Live workflow latency and cost per analysis** are measured separately from the live golden runs and reported as p50/p95.

---

## 9. Documentation, Demo, Innovation

### 9.1 Documentation
- **README:** overview + diagram; step-by-step setup; run locally (compose and native); run tests/eval/load; sample queries; tech choices; deploy; troubleshooting.
- **ARCHITECTURE.md:** components; graph; state; contracts (§3.6); lifecycle (§3.7); event delivery (§3.8); recovery; ER diagram; decision records; scalability (horizontal workers, partitioned observations, read replicas).
- **TESTING.md:** strategy; named failure tests; hallucination methodology; gates with real results; probe results; coverage; load workload and results.
- **DATA_SOURCES.md:** manifest per dataset (full IDs, links, definitions, conventions, markers, licence/terms as stated, limits, paging); same-origin mirror note; snapshot approach; no mock data; how to add a connector.

### 9.2 Twenty-minute demo (fault the configured primary: Bedrock)

| Time | Segment |
|---|---|
| 0–1 | Framing |
| 1–7 | **Live two-platform E2E** with the example query: plan card (SSIC J58–63 assumption, subsector distinct) → Extraction lanes (SingStat JSON, Data.gov.sg, MOM Excel) incl. a fitness rejection → quality panel (markers, mirror consistency) → Analytics R-A-O incl. **`REFERENCE_MISMATCH` refusal** and quarterly correlation → dashboard → verified report with lineage citations |
| 7–11 | **Bounded failure segment:** (1) fault Bedrock → OpenAI fallback event; (2) source outage → disclosed snapshot; (3) missing-data/limitation disclosure; (4) ambiguous query → clarification. Uses pre-run history entries, clearly disclosed, wherever a live run would exceed the slot. |
| 11–14 | Architecture, autonomy evidence, **challenges & solutions** (release-dated URLs, point-based paging, quarterly-average vacancies, parent/child taxonomy) |
| 14–16 | Tests and multi-cloud evidence: hosted CI run, eval gate table, adversarial suite, probe results |
| 16–20 | **Q&A / buffer** |

**Contingency:** snapshot data mode, pre-run history, backup recording.

### 9.3 Innovation assessment (docs/INNOVATION.md, 1–2 pages)

Each brief theme gets two clearly labelled parts: **Implemented now** (a concrete example from the code) and **Proposed next** (specific and actionable).
- **Trust:** lineage-derived citations, evidence-bound claims, reproducibility tiers.
- **Adaptability:** evidence-driven re-planning, method refusals; proposed: researcher feedback on dataset fitness.
- **Real-world data:** identity/join rules, marker semantics, release-URL discovery, mirror checks; proposed: source-health monitoring and schema-drift alerts.
- **Security and privacy:** data-classification tags gating which providers may see which data; PII guard; audit trail from the event log; deployment within government cloud environments.
  - Region pinning and similar measures are presented as *supporting* controls, **not as proof of compliance**.
- **Scale:** in-database aggregation, worker scaling.
- **Collaboration:** shared, forkable analyses with annotations.
- **Multi-cloud and cost:** circuit-breaking router, cost-aware model routing, the ledger.

Only delivered features are cited as implemented.

### 9.4 Submission checklist
- [ ] Source code: structured frontend and backend; Dockerfiles + docker-compose.yml; fresh-clone verified (SUB-1, DO-1)
- [ ] **All hard gates G1–G8 pass.** Readiness is refused otherwise; failing artifacts and remediation notes are kept.
- [ ] Test suite + docs; named failure tests green; T targets met or honestly reported with justification (T-1..5, TD-1..3)
- [ ] README with all p.5 items (SUB-2)
- [ ] ARCHITECTURE.md, TESTING.md, DATA_SOURCES.md (SUB-3..5)
- [ ] 3 agents with evidence-driven decisions; ReAct visible; graceful failures (MA-1/2, AF-1..4)
- [ ] ≥2 source platforms; CSV + Excel + JSON + API; validation/cleaning shown (GD-1..4)
- [ ] Eligible analyses incl. a supported correlation; verified-only insights; charts; lineage citations (IA-1..4)
- [ ] NL input; live monitor; interactive dashboard; history + export (FE-1..4)
- [ ] REST + problem+json; durable async jobs; DB; WS catch-up (BE-1..4)
- [ ] Bedrock + OpenAI; fallback demonstrated both directions; LLM used for interpretation, insights, report (LLM-1..4)
- [ ] **Green hosted GitHub Actions run**; deployment config; secrets handling; deploy docs (DO-2..4)
- [ ] Demo script, two timed rehearsals, backup recording (DEMO)
- [ ] Innovation essay, implemented vs proposed (INN)

---

## 10. Risks, Dependencies, Open Items

| Risk / dependency | Mitigation |
|---|---|
| **D1: Bedrock model/region capability** | Day-1 probe. If it fails, pick another enabled model or region the same day. Primary stays configurable. |
| Live source outage or format change during the demo | Snapshot mode, last-known URLs, pre-run history, backup recording |
| Data.gov.sg rate limits (429 already observed without a key) | Shared token bucket and caching; **recommend registering a free API key** |
| M1 density | Strict G2-only scope; dashboard polish deferred to M3 |
| Live LLM variance | Temperature 0, structured outputs, semantic consistency gates, guards |
| Weak inference on small n | Method policy (§4.5): descriptive annual statistics; quarterly n=20 for exploratory correlation |
| Unauthenticated app | Local/private demo boundary; fault injection disabled in prod config; SSO/RBAC covered as future work |

**Items needing your input (defaults apply if unanswered):**
1. **Push to `origin`.** Hosted CI (G7) needs pushes, so this is an explicit dependency. Approving this plan does **not** authorise commits or pushes. *Default: I ask before the first commit/push on Day 1.*
2. **Data.gov.sg API key.** *Default: run without one, with throttling.*
3. **Bedrock region and models enabled.** *Default: determined by the Day-1 probe and reported back to you before M1.*
4. **Working files** (assessment PDF, planning prompt, review notes). *Decision: kept out of the repository and the submission.*

---

## Verification (end-to-end proof of the finished system)
1. Fresh clone → `cp .env.example .env` → `docker compose up --build` → all services healthy. Hosted GitHub Actions run green, including compose smoke and Playwright.
2. Run the example query live with Bedrock primary.
   - Confirm the agent lanes stream.
   - Confirm citations open the exact SingStat, Data.gov.sg and MOM sources.
   - ICT employment values match M182841 exactly.
   - The annual employment-vs-vacancy correlation is refused with `REFERENCE_MISMATCH`.
   - The named quarterly pair (M184071 × M183891) is shown as exploratory, with lag 0 n=20 and lag 1 n=19, and matches the golden expectations.
3. Fault Bedrock → OpenAI fallback. Fault a source → snapshot disclosure. Ambiguous query → clarification → resume. Duplicate clarify → 409.
4. `make test`, `make eval`, `make load`. The §8.3 and §8.4 gate tables are populated from actual artifacts in TESTING.md.
5. Reopen and export a past analysis. The bytes match the stored report, and every claim carries passing checks and lineage citations.

---

## Day-1 outcomes (2026-10-25)

Recorded as evidence. Raw files are in `eval/results/probe/` and `data/snapshots/manifest.json`.

**D1 resolved: G1 met.**
- **Bedrock primary is `apac.amazon.nova-pro-v1:0`.** It passed all five probe checks: invoke, tool call, structured output, ReAct turn, streaming.
- **OpenAI fallback is `gpt-5.5`.** It also passed all five.
- **Claude on Bedrock is not yet usable.**
  - The 5.x models return "not available for this account".
  - Sonnet 4.6 and Haiku 4.5 need the Anthropic use-case form submitted in the Bedrock console.
  - Switching later is a config-only change (`BEDROCK_MODEL_ID`), and it must re-pass `make probe`.
- **Router requirement (for M1):** Nova returns `reasoning_content` blocks inside message content. The router must strip them. Only the public `rationale` field is ever shown.

**Data facts confirmed (recorded in `data/manifest/sources.yaml`):**
- **SingStat paging:** the server caps each page at 5,000 data points regardless of `limit`.
- **MOM units:** MOM files report employment change in thousands, while SingStat M183891 reports persons.
- **Markers:** MOM defines `-` as "Nil or negligible". SingStat's meaning for `-` is unverified, so it is treated as an unknown marker.
- **Messy CSV:** MOM's quarterly CSV carries 6 empty trailing columns.
- **Mirror open issue:** the Data.gov.sg mirror of M182841 shows `na` for 2001–2003. To be investigated by the consistency check.
- **Named pair confirmed:** lag 0 n=20, lag 1 n=19. ICT vacancies are identical on SingStat and Data.gov.sg.
- **Raw bytes are not a stable identity:** two captures of unchanged data differed byte-wise. SingStat stamps `dateGenerated` on every response, and MOM's HTML carries random CSS IDs. Normalised-artifact identity (§4.6) and the F3 fingerprint must therefore hash the **normalised content** (observations + source metadata + parser/taxonomy versions), never the raw-payload hash. The raw hash stays as provenance only.

**Version deviation:** the frontend was scaffolded on **Next.js 16.4.3**, not 15. Node 22 is the baseline.

---

## Verified vertical slice: outcomes and design changes

All of the following was verified live: the example query on Bedrock primary, on OpenAI primary, and through the UI.

**Design changes driven by live runs**
- **Claims are composed by the platform.** The agent supplies an optional short lead-in (8 words or fewer, no digits) and at most two assertions. The renderer writes the sentence.
  - Why: free prose around slots produced garbled, duplicated statements.
  - Effect: drafts that restate already-verified statements are refused.
- **Public rationale travels as a required tool argument.** Nova returns its explanation only as private `reasoning_content`, which the router strips, so message text cannot carry it.
- **The tool-call budget is enforced per call.** Every skipped call gets an answer, and `compute` is capped per round.
  - Why: Nova issues large parallel batches; one run made 34 `value_at` calls.
- **Flows are refused for endpoint differences**, and a `cumulative` tool replaces them. `list_evidence` offers eligible suggested computations with exact arguments.
- **The cross-platform consistency check runs automatically** whenever a selected series has a catalogued mirror. It is quality control, not an LLM choice.
  - The wide-format Data.gov.sg mirror of M182841 is now supported, and matches SingStat exactly.
  - Its `na` cells for 2001–2003 are periods SingStat does not publish; they are not conflicting values.
- **The qualitative narrative check was pulled forward from M2.** Deterministic checks cannot catch a plausible sentence with invented facts.
  - The judge prefers the other provider. A rejected summary gets one rewrite, then is omitted.
  - Bug found in the process: the narrative writer had been receiving claim *templates*, not the rendered findings.
- **Argument mistakes (`INVALID_WINDOW`) are agent errors, not data limitations.** They never reach the report or the status.
- **Next.js Cache Components are disabled.** The analysis route renders on request.
  - Why: under Partial Prerendering the Suspense boundary never resolved on the client, and the app uses no `use cache`.

**Known gaps carried into M2**
- **The reconciler is not implemented yet** (lease expiry, re-dispatch of unacknowledged intents). An analysis whose worker is replaced mid-run stays `running`, as observed once during a stack rebuild.
- **The epoch-fenced checkpointer, clarification interrupt, cancel endpoint and MOM Excel connector are still to build.**

## M2 outcomes: durable lifecycle

**Closed from the M1 gaps:** the reconciler, the epoch-fenced checkpointer, the clarification interrupt and the cancel endpoint. The MOM Excel connector remains for the data PR.

**Decisions taken while building:**
- **Checkpoints use `durability="sync"`.**
  - Why: with the default asynchronous durability, a checkpoint could still be in flight when the lease moved, and the fence then rejected it. The resumed run lost a step.
  - Each checkpoint write takes a per-analysis advisory lock and re-checks the epoch (`FOR SHARE`) in the same transaction.
- **Graph state carries evidence *references* only.** A resumed run reloads datasets and computations from their tables. Computation IDs derive from the fingerprint, so a restarted step reuses its rows instead of duplicating them.
- **Clarification is its own graph node**, so answering resumes at the question without repeating the planning call.
  - An answer re-plans once with the researcher's text. "Proceed" adopts the plan and records the assumption.
- **The question version is bumped on pause and again on acceptance.** A duplicate answer is therefore `CLARIFICATION_STALE`, not a second resume.
- **An accepted answer is keyed by the interrupt it answers.** Every resume looks for an answer to the pending interrupt, so the answer survives a crash of the worker that first claimed it.
  - Once the checkpoint records the answer, the interrupt is no longer pending and the answer is not applied twice.
  - If the worker crashed before the question was shown, the resumed run asks it again.
- **Cancellation takes precedence over an answer.** Cancelling a queued or paused analysis supersedes its open intents, and a claim only succeeds on a queued or running analysis, so a queued answer can never resume a cancelled run.
  - A running analysis stops at the next node or tool-call boundary.
  - The final transitions (pause, finish) re-check `cancel_requested_at` under the row lock that decides them. A cancel arriving after the last boundary therefore still wins, and the report is discarded.
  - An expired lease with a pending cancel is cancelled by the reconciler, not resumed.
- **The reconciler runs every 15 s in every worker.** It replaces the 5 s dispatch cron.
  - Concurrent passes are safe: row locks plus `SKIP LOCKED`.
  - When a run fails for exhausted attempts, the epoch is bumped, so a late original worker stays fenced.
- **Only active time counts against the deadline.**
  - Each heartbeat (15 s) adds the active time since the last one. Pause and finish add the remainder.
  - Reports are serialised, and an interval counts as reported only once its write commits. The final pause or finish therefore waits for an in-flight heartbeat rather than racing it.
  - When a crashed run is recovered, it is charged one more interval for time its worker never reported, so recovery cannot grant extra budget.
  - A resume gets what remains.

**Verified live:**
- An analysis left `running` by an earlier stack rebuild was resumed at worker startup.
- A worker killed mid-run was recovered about 60 s later (lease expiry), finished on attempt 2, and wrote no duplicate computations.
- An ambiguous question paused with options and resumed from the UI. A repeated answer got a 409.
- A cancel during a run stopped at the next step.

**Observed, not yet addressed:**
- Nova sometimes offers far more than four clarification options.
- The planner can pick a stale "last five years" window, e.g. 2018–2022.
- Two drafted claims can restate the same verified assertion.

## M2 outcomes: data integration and quality

**Delivered:** the MOM workbook connector (CSV as fallback), the Data.gov.sg CSV download path, rate limits shared across workers with the API key sent when configured, the raw-payload store, mirror checks at published precision, and the data-quality mutation suite.

**Decisions taken while building:**
- **MOM files are discovered at every fetch.** The index page is scanned for the dataset's stable filename prefix and the newest release date wins.
  - When the page is down or no longer links the dataset, the last-known release URL in the catalogue is used, and a `DISCOVERY_FALLBACK` warning says so.
  - A page served from its snapshot after a live failure is also a discovery fallback, even when the workbook it links is then fetched live.
  - The warning is raised only when the fallback file is actually used.
- **The workbook is the primary MOM format, the CSV the fallback.** The workbook publishes sector totals with SSIC codes, its legend and its unit; the CSV lists only the lowest-level industries (no Information & Communications total) and carries no legend.
  - The quarterly SSIC2020 sheet is six side-by-side blocks of three years. Rows are merged across blocks.
  - Legend (`'-' : Nil or negligible`) and unit (`In Thousands`) are read from the sheet on every fetch and checked against the reviewed manifest: `LEGEND_CHANGED` and `UNIT_MISMATCH` respectively.
  - The scale must be confirmed by the sheet. An unstated or unrecognised unit (e.g. "In Millions") is a blocking `UNIT_UNVERIFIED` error, never a silent assumption.
  - The newest quarter header reads `1Q^`, a footnote mark the sheet does not explain. It is stripped and disclosed (`PERIOD_FOOTNOTE`).
- **A MOM row is identified by its stated SSIC code plus its label.** The taxonomy records the code ranges sources state per sector (e.g. `J58-63`). A row whose code contradicts its label, such as a child relabelled with its parent's name, is an `IDENTITY_CONFLICT` error and is not used.
- **The Data.gov.sg CSV download is preferred where catalogued.** It is one rate-limited request instead of one per 1,000 datastore records. The datastore is the fallback.
  - Both paths carry the same records as text and yield the same artifact ID (tested).
  - The pre-signed S3 URL is used once and never stored. The download's identity is its `poll-download` URL, which is also the snapshot key. The initiate and poll responses are never recorded.
- **Rate limits are shared through Redis.** Each call claims the next slot (`SET NX PX`), spaced 10% inside the published limit. Without Redis, each process falls back to twice the interval, with the spacing state shared by every analysis in that process.
  - Published limits per 10 s: datastore 4 / 8 / 20 and downloads 2 / 4 / 10 (none / dev / prod key).
  - `DATAGOV_API_KEY` is sent as `x-api-key`, only to `data.gov.sg` hosts. `DATAGOV_KEY_TIER` selects the limits.
- **Schema drift is checked with pandera** on the columns each parser relies on. A missing column is a `SourceSchemaError`, never a `KeyError`. The extraction tool reports it to the agent and shows it in the timeline.
- **Artifact identity covers what the source says about its values.** Besides the observations, the hash includes `source_metadata` (stated units, legend, SingStat units of measure) and every blocking issue. A workbook with the same numbers but a different stated unit is a different artifact, so a clean copy stored earlier can never stand in for it on resume.
- **Shared values, per-analysis fetch.** An artifact's values are shared, but provenance and fetch-time disclosures (discovery or format fallbacks, snapshot use) belong to each analysis's fetch. They are kept on `analysis_artifacts.fetch_record` and restored over the shared artifact on resume, so a fallback disclosed in one analysis never disappears because another analysis stored the same values first.
- **Mirror checks run in both directions and only on usable evidence.** Selecting MOM's release checks SingStat's republication, and vice versa. If either side has a blocking error, the result is "not comparable", never "consistent".
- **Mirrors agree within half the coarser published increment.** MOM publishes thousands to 0.1 and SingStat whole persons, so they are compared at ±50 persons. An exact comparison would also have failed on float noise (-1.1 × 1000 ≠ -1100).
- **A republished copy of an already-selected statistic is refused.** Selecting both would report one figure twice. This was observed live before the guard; it is now only a cross-check.
- **Raw payload bytes are stored by SHA-256** alongside each dataset artifact, which already lists those hashes.

**Verified live:**
- MOM discovery found the 21 Sep 2026 quarterly workbook.
- The Data.gov.sg CSV download completed in 7 s without a key.
- A quarterly ICT employment question was answered from SingStat M183891, cross-checked against MOM's workbook ("consistent within published rounding (±50)"), and both raw payloads were stored.

**Not yet done:** the data-quality panel in the UI (area D).

## M2 outcomes: exploratory correlation

**Delivered:** `correlate` with declared pairing rules and refusal codes, association predicates with a strength rule, agent wiring, and golden values for the named pair.

**Decisions taken while building:**
- **Eligibility is checked in a fixed order:** classification and code set (`CLASSIFICATION_MISMATCH`), frequency (`FREQ_MISMATCH`), observation moment (`REFERENCE_MISMATCH`), a declared pairing rule at that lag (`NO_PAIRING_RULE`), then at least 12 aligned complete pairs (`INSUFFICIENT_PAIRS`) and no constant series (`CONSTANT_SERIES`).
  - Annual year-end employment vs annual vacancies (a mean of four quarter ends) is refused with `REFERENCE_MISMATCH`, as planned.
- **Pairing rules are oriented.** The leading series comes first; for stock × flow, lag 1 pairs the stock at the end of a quarter with the flow over the next quarter. Arguments given the other way round are reordered, not refused.
- **Both members of a pair must lie in the window.** The named pair (M184071 vacancies × M183891 employment change, 2020-Q1..2024-Q4) gives n = 20 at lag 0 and n = 19 at lag 1. Incomplete pairs are skipped and listed, never filled.
- **Descriptive output only:** Pearson r, Spearman ρ and the pair count, with no p-values (consecutive quarters are serially dependent).
- **Caveats travel with the finding.** Serial dependence, population differences, rule caveats and skipped quarters are a computation's `caveats`. Every retained finding's caveats are added to the report limitations deterministically.
- **One request, one identity.** Lag and window spellings are canonicalised before fingerprinting and rendering ("01" is lag 1; "2020 1Q" is 2020-Q1). A refusal is identified by tool, code, the unordered pair of series and the parameters, so the same pair refused in reverse order is recorded once.
- **Associations are stated with `assoc.positive`, `assoc.negative` or `assoc.weak`.** The positive and negative predicates need |r| ≥ 0.3; weak needs |r| < 0.3.
  - They are allowed only in association claims on exploratory computations.
  - The rendered text names both series and the lag, keeps the sign, and says "exploratory, not evidence of cause".
  - The claim kind follows from the predicate, not from what the model calls it.
- **Pairs are evaluated deterministically, lag by lag.** `list_evidence` evaluates every same-sector pair of selected series measuring different metrics, at every lag its rule allows. Eligible lags are listed first under the leading series, with their pair count. Ineligible pairs or lags (e.g. 11 pairs at lag 1 over 2022–2024) are recorded once as refusals, visible in the timeline and the report.
- **Reuse is checked before the budget.** A repeated computation returns the earlier result without spending the round's budget, even once the budget is used up. In a live run, the second analytics round had re-computed the same statistics and never reached the correlation.

**Golden values (snapshot of 25 Oct 2026, independently recomputed in the tests):** lag 0 r = 0.468, ρ = 0.471 (n = 20); lag 1 r = 0.360, ρ = 0.311 (n = 19).

**Verified live:** the demo question ("Analyse employment trends in the technology sector from 2020-2024") reported both correlations as exploratory associations. It also recorded `FREQ_MISMATCH` refusals for annual employment against the two quarterly series.

## M2 outcomes: fault injection, verifier independence, data-quality panel

**Delivered:** demo fault switches, a record of whether the narrative check was independent, and a data-quality panel in the report.

**Decisions taken while building:**
- **Faults are named switches in Redis with an expiry** (default 10 minutes, at most 1 hour), so the API sets them, every worker sees them, and a forgotten switch turns itself off.
  - Switches: `llm:bedrock`, `llm:openai`, `source:singstat`, `source:datagov`, `source:mom`.
  - Routes: `GET/PUT/DELETE /api/admin/faults[/{name}]`. They are mounted only when `ENABLE_FAULT_INJECTION=true`, which the settings refuse when `APP_ENV=prod`, so the routes do not exist in production.
  - Compose passes the flag through, e.g. `ENABLE_FAULT_INJECTION=true docker compose up -d`, then `curl -X PUT localhost:8000/api/admin/faults/llm:bedrock`.
- **An injected failure is never disguised.**
  - A switched-off provider fails in the router like a real outage, so the fallback, the circuit breaker and the `provider_fallback` events all behave as they would for a real failure. The ledger records the failure as injected.
  - Every fallback event states its cause: "bedrock switched off (injected fault (demo)); answered by openai". This holds after the circuit opens too, because the circuit remembers the failure that opened it.
  - A switched-off source is served from its snapshot. The disclosure reads "source:singstat switched off (injected fault (demo))".
  - A switchboard outage counts as "no faults", never as an outage of its own.
- **Verifier independence is recorded.** The router keeps which provider answered each purpose. The report's `verification.narrative_check` lists the writers, the judges and whether they differ. When they do not (the other provider was unavailable), a limitation says the check was not independent.
- **The report has a `data_quality` section.** It covers each dataset used as evidence, and each republication it was cross-checked against, with:
  - every relevant check, with severity and count;
  - the markers actually present in the values used, with the source's own meaning and their treatment (nulled, excluded from calculations).
  - A dataset used both ways (evidence for one sector, cross-check for another) lists every series it was relied on for.
  - Cross-checks that were refused (an identity mismatch, or blocking errors on either side) are recorded and shown as "not comparable", never as agreement, and the broken dataset stays in the panel with its errors.
  - Marker meanings are the ones the fetched source states (a workbook's own legend), falling back to the reviewed manifest. A disagreement between them is flagged as `LEGEND_CHANGED`.
  - The UI shows severity with an icon and a word, never colour alone.
- **Association findings carry an "Exploratory association" tag** in the UI.
- **Unidentified rows are named with their classification** (e.g. "Information And Communications (SSIC2005)"). The panel showed that without it, a series used as evidence appeared to be unidentified.

**Verified live,** with Bedrock and SingStat switched off, on the demo question:
- OpenAI answered every call, with the failed Bedrock calls and the fallbacks recorded.
- Both SingStat datasets were served from snapshot, with the injected-fault disclosure.
- The narrative check was recorded and disclosed as not independent.
- The panel listed four datasets: two as evidence, two as cross-checks.

## M3 outcomes: exports, history and dashboard

**Delivered:** exports, a history status filter with paging, a usage summary, and chart interactions.

**Decisions taken while building:**
- **Exports are built only from what was stored when the analysis finished** (`GET /api/analyses/{id}/export?format=md|json|csv`). Nothing is recomputed or regenerated, so an export matches what the researcher saw.
  - Markdown: the readable report.
  - JSON bundle: the analysis, the verified report and every pinned dataset version (identity, provenance, raw payload hashes).
  - CSV: the exact stored observations of each selected series in the plan window: value, source marker, raw source text, unit, scale and citation.
  - Drafts are never exportable, because only verified findings reach the report. Exporting before a report exists is a `409 REPORT_NOT_AVAILABLE`.
  - The report's selected series now record their `artifact_id`. Older reports resolve the version their citation pins. When several versions are stored and none is pinned, nothing is exported rather than a guess.
  - The JSON bundle shows each dataset as this analysis fetched it (its own retrieval time, snapshot use and raw hashes), using the same fetch-record overlay as resume.
- **Cost counts every call, failed ones included, and is shown only when every model used has a configured price and every call's token usage is known.** A structured-output failure is metered from its rejected replies (they were generated), and a repaired answer counts both replies. An injected fault sent nothing, so it is recorded as zero. A failure with unknown usage, such as a timeout, makes the cost unknown.
  - Prices come from `LLM_PRICES` (USD per million input and output tokens); they are configuration, never guesses. Otherwise the UI says "cost not configured" rather than showing a partial total.
  - Calls, tokens, LLM latency, active time and the provider mix are always shown.
- **History** filters by status and pages with the existing keyset cursor ("Load more"). A page requested under an earlier filter is discarded when it arrives.
- **Charts:**
  - Series can be toggled; at least one stays visible, and colours stay with their series.
  - A period range filter applies to both the chart and the table view.
  - Hovering or focusing a finding highlights the chart series it rests on. Findings record the series keys behind their computations, because one citation can cover several sectors of a dataset; older reports fall back to citations.
  - Tables scroll horizontally on narrow screens.

## M3 outcomes: deterministic evaluation gates (F1)

**Delivered:** the golden set, independently computed expected values, and the computation-accuracy, refusal-correctness and adversarial-verifier gates. They run as tests in CI and as `make eval`, and the results go to `eval/results/deterministic.{json,md}`.

**Decisions taken while building:**
- **Expected values share no code with the application.** `eval/compute_expected.py` reads the raw snapshot payloads through the manifest and parses them itself. It computes every statistic from its definition: closed-form OLS slope, Pearson's r, and Spearman's ρ with averaged tied ranks. It uses no scipy, statsmodels or pandas, and none of the application's parsers or tools.
  - A test enforces this independence by inspecting the script's imports.
  - `expected.json` is committed for human review, and a gate fails if it is stale for the current snapshots.
- **The golden set** (`eval/golden/queries.yaml`) contains:
  - 12 computations: ICT employment change, CAGR, trend and YoY; quarterly employment change total and period comparison; vacancies change for the sector and the IT subsector; vacancy trend and CAGR; the named correlation pair at lag 0 and lag 1;
  - 4 refusals: `REFERENCE_MISMATCH`, `INSUFFICIENT_PAIRS` and two `NOT_A_LEVEL`;
  - 12 queries for the live runs (F2).
  - No recruitment-rate computation is included, because M184021 has no identified ICT series in the snapshots.
- **Tolerances** follow §8.3: exact for integer arithmetic on source values, a relative 1e-9 for closed-form formulas, and 1e-6 for estimators.
  - The tolerance is strictly relative: an absolute floor would loosen it for correlations, which are below one.
  - Every field must also be in the expected unit and scale, derived independently from what it measures, so a right number in the wrong unit fails.
  - A computation must produce exactly the expected set of fields: a missing or unexpected field fails.
- **The quarterly trend's HAC interval is checked too.** The script computes Newey-West bounds itself (Bartlett kernel, lags equal to periods per year, no small-sample correction, normal critical value) and matches the application to about 1e-15.
- **The adversarial suite** has 25 valid controls (20 claims and 5 narrative sentences) and 44 corrupted cases in 17 categories, all bound to real computations.
  - Detection must come from the rule each corruption breaks: e.g. a wrong direction must fail `sign_rule`, not some other check. The runtime gate enforces this, not only the tests, and reports any misattributed rejection.
  - This caught a bug in the suite itself during development: every case first failed `resolution`, controls included, which would have reported 100% recall with an 80% false-positive rate.
  - Unsupported narrative additions with no numbers or causal words need the LLM judge, so they are measured in the live evaluation.
- **The golden check found an error in a test fixture.** `ICT_EMPLOYMENT` in the analytics unit tests was labelled as real M182841 values, but four of its six years differed from the published figures (e.g. 2022 was 176.4; SingStat publishes 187.8). It now holds the published values.

**Results (snapshots of 25 Oct 2026):**
- computation accuracy 32/32 fields within tolerance and in the expected unit and scale;
- refusal correctness 4/4;
- adversarial recall 100% in every category, precision 100%, false-positive rate 0%.

**Next (F2):** live golden runs on both providers, the consistency runs, the provider-resilience scenarios, the qualitative judge category, and a human relevance review sheet.

