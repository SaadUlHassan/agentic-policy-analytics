# Testing

How the platform is tested, how hallucination is detected, and what the tests and evaluations found. Every number here comes from an artifact in the repository or a CI run, named where it is quoted.

- [Strategy](#strategy)
- [Test suites](#test-suites)
- [Hallucination detection](#hallucination-detection)
- [Evaluation gates and results](#evaluation-gates-and-results)
- [Failure and recovery tests](#failure-and-recovery-tests)
- [Data quality tests](#data-quality-tests)
- [Browser tests](#browser-tests)
- [Performance and load](#performance-and-load)
- [Coverage](#coverage)
- [Continuous integration](#continuous-integration)
- [Reproducing the results](#reproducing-the-results)
- [Known gaps](#known-gaps)

## Strategy

Three principles shape the tests.

1. **Test mechanics with doubles, numbers against independent expectations, and models live.** Orchestration (routing, guards, budgets, ReAct triples, recovery) is tested with a scripted LLM double, so the tests are fast and deterministic. Every statistic is compared with values computed by a separate script that shares no code with the application. Model competence (planning, choosing data, wording) can only be measured with real models, so it has its own live evaluation.
2. **Trust nothing a run says about itself.** The evaluation re-verifies every stored finding, recomputes every stored computation from the fetched series, and checks citations against lineage, rather than reading the run's own verdicts.
3. **Hard gates are never waived.** A gate is either hard (a miss blocks release) or a documented target (a miss is reported with its cause). Rerunning never turns a hard-gate miss into a pass, and work that couldn't be evaluated is reported as not evaluated, never as passed.

**Test doubles** live only under `backend/tests/`, `eval/` and `app/llm/scripted.py`; none is reachable from a production path. The offline stand-in (`LLM_MODE=offline`) used by the browser and load tests is refused when `APP_ENV=prod`.

## Test suites

| Suite | Count | What it covers | Runs on |
|---|---|---|---|
| Backend unit (`backend/tests/unit/`) | 228 | Connectors on recorded real payloads (paging, fragment merging, discovery, throttling), identity and periods, data-quality mutations, analytics tools with eligible and ineligible fixtures for every refusal code, correlation pairing rules, grounding checks, the router (retries, fallback, circuit breaker, SDK retries off), faults, pricing, settings, agent tools, the ReAct loop | every CI run |
| Backend integration (`backend/tests/integration/`) | 105 | The full graph with a scripted LLM on Postgres and Redis: lifecycle, recovery, fencing, checkpoints, clarification, cancel, the API and WebSocket, exports, offline mode, live-scoring logic | every CI run (service containers) |
| Backend evaluation (`backend/tests/evaluation/`) | 41 | The deterministic gates, the live-evaluation scorer and suites, the load driver | every CI run |
| Frontend unit (`frontend/tests/`) | 31 | Event merging and the resume cursor, the dashboard (series toggles, period filter, finding↔chart highlight, small multiples), report rendering and citations, the data-quality panel, the clarification card, the query form, history paging, health, usage | every CI run |
| Browser end to end (`frontend/e2e/`) | 3 tests × 3 widths | See [Browser tests](#browser-tests) | every CI run |
| Live tests (`-m live`) | — | Real government APIs and real models; excluded by default | on demand |

**Backend: 374 tests. Frontend: 31 unit tests and 9 browser runs.** All pass in CI.

## Hallucination detection

Hallucination is prevented by construction where possible and detected where not.

### By construction: numbers can't be invented

- **The LLM never writes a number.** Analytics drafts a claim by choosing a predicate from a closed registry (`change.increase`, `cagr.growth`, `assoc.positive`, …) and binding it to a field of a stored, deterministic computation. The platform renders the sentence from the predicate's template, so the number in the text is the number in the computation.
- **Citations are derived from lineage,** never written by a model: the dataset version, series, periods, platform, origin agency, human URL and retrieval time come from the computation's inputs (the API URL of each version is in the JSON export bundle).

### Detected deterministically: 14 checks on every claim

Every drafted claim passes all of these before it can reach the report; the full list with what each rejects is in [ARCHITECTURE.md](ARCHITECTURE.md#claim-verification):

`resolution`, `predicate_fit`, `metric_equality`, `identity_equality`, `interval_equality`, `sign_rule`, `strength_rule`, `kind_allowed`, `slots_bound`, `no_free_numbers`, `no_causal_language`, `safe_prose`, `recommendation_has_no_figures`, `finding_has_evidence`.

The generated title, summary and limitations also pass `no_free_numbers` (years only when they are asserted interval endpoints) and `no_causal_language`.

### Detected by an independent judge: unsupported prose

Deterministic checks can't catch a plausible sentence with no numbers that the findings don't support ("hiring rebounded strongly"). An LLM judge reads each narrative sentence against the rendered verified findings and flags overstatement and unsupported additions. It runs on the provider that did **not** write the narrative when that provider is healthy; when it isn't, the report discloses that the check was not independent. A flagged summary gets one rewrite, then is omitted.

### How the detectors are measured

- **Adversarial verifier suite** (`app/evaluation/adversarial.py`): 25 valid controls (20 claims and 5 narrative sentences) and 44 corrupted cases in 17 categories, all bound to real computations. A case counts as detected only when **the rule it breaks** rejects it: a wrong direction must fail `sign_rule`, not some other check. This rule caught a bug in the suite itself during development, where every case first failed `resolution`, controls included; that would have reported 100% recall with an 80% false-positive rate.
- **Judge suite** (`app/evaluation/judge.py`): 10 faithful summaries, 12 overstated or contradicted sentences and 12 unsupported additions, none of which can be caught deterministically (a test enforces this). Each is judged alone, by each provider, against the real golden findings. A sentence that couldn't be judged counts against the target.
- **Live re-verification:** every retained finding of every live run is verified again from what was stored, and every stored computation is recomputed from the series the run fetched.

## Evaluation gates and results

### Deterministic gates (`make eval`, CI)

From `eval/results/deterministic.md`, snapshots of 25 October 2026:

| Gate | Class | Result |
|---|---|---|
| Expectations current for the snapshots | Hard | pass |
| Computation accuracy | Hard | **32/32** fields within tolerance and in the expected unit and scale, across 12 golden computations |
| Refusal correctness | Hard | **4/4** (`REFERENCE_MISMATCH`, `INSUFFICIENT_PAIRS`, two `NOT_A_LEVEL`) |
| Adversarial recall, deterministic categories | Hard | **100%** in all 17 categories (44/44); precision 100% |
| Adversarial false positives on valid controls | Target ≤ 5% | **0%** (0/25) |

**Independent expectations.** `eval/compute_expected.py` reads the raw snapshot payloads through the manifest and parses them itself. It computes every statistic from its definition (closed-form OLS slope, Newey-West HAC bounds, Pearson's r, Spearman's ρ with averaged ties) with no scipy, statsmodels, pandas or application code; a test inspects its imports to enforce that. **Tolerances:** exact for integer arithmetic on source values, relative 1e-9 for closed-form formulas, relative 1e-6 for estimators. A computation must produce exactly the expected fields, each in the expected unit and scale, so a right number in the wrong unit fails.

The golden check also found an error in a test fixture: analytics unit tests labelled values as real M182841 data, but four of six years differed from the published figures. The fixture now holds the published values.

### Live evaluation (`make eval-live`)

Real providers on snapshot data, in an isolated database and Redis. 12 golden queries (see the [README](README.md#sample-queries)), each run 3 times per provider order: 72 runs. Results from PR #9 (commit `97a97cd`, `eval/results/live/` at that commit), the last complete run:

| Gate | Class | Bedrock primary | OpenAI primary |
|---|---|---|---|
| Runs completed | Hard | 36/36 | 36/36 |
| Refusal correctness, golden runs | Hard | **12/12** | **12/12** |
| Retained-claim failures (all runs) | Hard | **0** | **0** |
| Live computation mismatches (278 computations recomputed) | Hard | **0** | **0** |
| All three agents make decisions on supported runs | Hard | yes | yes |
| Provider resilience (6 scenarios) | Hard | all pass | all pass |
| Series identities, golden runs | Target ≥ 11/12 | 10/12 | 10/12 |
| Judge recall / false positives (34/34 judged) | Target ≥ 80% recall | 100% / 0% | 100% / 0% |
| Human relevance review | Target ≥ 10/12 | 9/12 | 11/12 |
| Consistency: mean Jaccard of selected series | Target ≥ 0.8 | 0.81 (pooled) | |
| Direction agreement across repeat runs | Target 100% | 100% | 100% |
| Active time p50 / p95 | Reported | 45 s / 54 s | 71 s / 160 s |

**Provider resilience scenarios** (all passed): fallback Bedrock → OpenAI; fallback OpenAI → Bedrock; the verifier's provider unavailable (disclosed as not independent); the primary lost mid-run; a total outage at the start, before any finding is verified (fails clearly with `LLM_UNAVAILABLE`); a total outage after the first verified finding (ends `completed_with_limitations` with the findings and no generated narrative). Partial-stream failure doesn't apply: model output isn't streamed.

**Target misses and what was done.** The three misses (series identities, relevance, and one unexpected clarification on G09) were traced to five product issues: the Coordinator couldn't see which planned items still lacked a series; the plan's period wasn't checked against the question; Extraction's rejection reasons never reached the report; totals over annual flows read like year-to-year changes; and long clarification lists were cut off. All five were fixed in PR #10, then the evaluation was rerun (commit `6b94d20`, `eval/results/live/` on `main`):

| | PR #9 | PR #10 |
|---|---|---|
| Refusal correctness, golden runs | 12/12, 12/12 | 12/12, 12/12 |
| Retained-claim failures, computation mismatches | 0, 0 | 0, 0 |
| Series identities (target ≥ 11/12) | 10/12, 10/12 | **11/12, 11/12** |
| Unexpected clarifications | G09 (Bedrock) | **none** |
| Golden computations found | 7/13, 6/13 | 10/13, 8/13 |
| Human relevance review (target ≥ 10/12) | 9/12, 11/12 | **12/12, 11/12** |
| Consistency (Jaccard) | 0.81 | 0.89 |
| Bedrock active time p50 | 45 s | 38 s |

**The PR #10 rerun is incomplete, and is reported as such.** The OpenAI account ran out of credits partway through; the call ledger records it. All 24 golden runs were evaluated, but 28 of the 48 repeat runs, the two resilience scenarios that need OpenAI as the fallback, and the OpenAI judge were not. They are reported as "not evaluated" (chosen from the ledger, never from the outcome), the summary is marked incomplete, and the command exits non-zero. The router and fallback code those scenarios exercise is unchanged since the complete PR #9 run.

**Evidence-driven decisions** (no faults injected) appear in the live traces: Extraction rejected M182841 for a 1985–1990 question because the series starts in 2008; GPT-5.5's Extraction rejected the quarterly vacancy series for a question about annual vacancies; the Coordinator requested further extraction for planned items still uncovered.

**Human relevance review.** Each golden run's report (findings and limitations) was marked relevant or not on `eval/results/live/relevance_review.md`. A mark counts only for the analysis it names, so a stale or duplicated sheet can't be counted. The development assistant proposed a verdict with a reason for each entry; the reviewer confirmed all of them.

**Cost.** The complete PR #9 run cost about $14.50 for 72 runs (Nova Pro $0.80/$3.20 and GPT-5.5 $5/$30 per million input/output tokens). That is a lower bound: four calls had unknown usage, so the summary reports the exact total as unknown.

### Capability probe (`make probe`)

`eval/results/probe/probe-20261025T205537Z.json`, 25 October 2026:

| Model | Invoke | Tool call | Structured output | ReAct turn | Streaming |
|---|---|---|---|---|---|
| Bedrock `apac.amazon.nova-pro-v1:0` (ap-southeast-1) | pass, 975 ms | pass, 1,393 ms | pass, 1,298 ms | pass, 2,145 ms | pass, 577 ms |
| OpenAI `gpt-5.5` | pass, 1,399 ms | pass, 1,627 ms | pass, 3,621 ms | pass, 3,466 ms | pass, 1,326 ms |

Claude models on Bedrock were also probed and weren't available to the account (they need Anthropic's use-case form), so Nova Pro is the primary.

## Failure and recovery tests

Each is a named integration test against real Postgres and Redis.

**Job lifecycle and recovery**
- `test_create_writes_analysis_and_start_intent_together`, `test_dispatch_is_idempotent`
- `test_dispatched_job_lost_in_redis_before_pickup_redelivered_once`
- `test_redis_restart_queue_rebuilt_from_outbox`
- `test_concurrent_claims_have_exactly_one_winner`, `test_duplicate_delivery_after_ack_does_not_run_again`, `test_claim_supersedes_other_open_intents`
- `test_stale_worker_is_fenced_after_takeover`, `test_stale_execution_cannot_write_a_checkpoint_and_the_new_owner_resumes`, `test_checkpoint_write_with_a_wrong_epoch_is_refused`
- `test_delivery_retries_do_not_consume_execution_attempts`, `test_exhausted_execution_attempts_fail_and_fence_the_old_owner`
- `test_expired_lease_reconciled_without_restart`, `test_healthy_long_run_not_reaped`, `test_no_redelivery_for_terminal_or_awaiting_input`
- `test_crash_after_computation_write_resumes_without_duplicates`, `test_saving_the_same_computation_twice_is_idempotent`
- `test_report_status_and_terminal_event_commit_together_or_not_at_all`
- `test_incompatible_checkpoint_fails_cleanly`
- `test_recovery_charges_the_unreported_heartbeat_interval`, `test_crashed_execution_time_is_charged_on_resume`, `test_heartbeat_in_flight_during_pause_or_finish_is_not_lost`

**Clarification and cancel**
- `test_clarification_round_trip_resumes_the_same_thread`, `test_clarification_pause_excluded_from_deadline`
- `test_clarification_queues_one_resume_and_a_duplicate_is_stale`, `test_concurrent_duplicate_clarifications_resume_once`, `test_stale_clarification_version_409`
- `test_accepted_answer_survives_a_crash_before_the_graph_resumes`, `test_crash_before_the_pause_commits_asks_again`
- `test_cancel_vs_clarify_race_single_winner`, `test_cancel_queued_now_running_on_request_terminal_409`, `test_cancel_while_running_stops_at_the_next_step`, `test_cancel_arriving_just_before_the_pause_cancels`, `test_cancel_during_the_report_step_discards_the_report`, `test_expired_lease_with_cancel_requested_is_cancelled_not_resumed`

**Event delivery**
- `test_events_get_consecutive_sequence_numbers_and_replay_in_order`
- `test_websocket_replays_then_closes_after_terminal_status`, `test_websocket_resumes_from_cursor`
- `test_event_committed_without_a_hint_still_arrives` (a lost hint is covered by the drain timer)
- `test_client_resuming_after_the_terminal_event_is_closed_not_left_waiting`
- `test_replayed_events_carry_their_commit_time_where_the_database_tracks_it`
- Frontend: "orders by seq and drops duplicates from a replay after reconnect", "tracks the resume cursor"

**Agent failures and degraded modes**
- `test_primary_provider_denied_falls_back_and_is_visible`, `test_fallback_events_say_the_outage_was_injected`
- `test_total_outage_before_a_plan_fails_clearly`
- `test_a_narrative_checked_by_its_own_writer_is_disclosed_as_not_independent`, `test_title_and_summary_the_judge_finds_unsupported_are_removed`
- `test_out_of_scope_question_gets_a_limitation_not_figures`, `test_unanswered_planned_metric_is_a_limitation_not_completed`
- `test_a_policy_route_gives_its_own_objective_not_the_refused_one`
- Router unit tests: SDK retries off (one HTTP request per attempt), circuit breaker, deadlines

**API contract**
- `test_create_validates_and_queues`, `test_unknown_analysis_is_404_problem`, `test_history_pages_newest_first_with_a_cursor`, `test_clarify_answers_once_then_409s_and_get_shows_the_question`, `test_cancel_running_is_a_request`
- `test_fault_switches_exist_only_when_injection_is_enabled`, `test_production_settings_refuse_fault_injection`

## Data quality tests

`backend/tests/unit/data/test_quality_mutations.py` corrupts real captured payloads and checks each corruption is detected and handled, never silently accepted:

| Mutation | Expected handling |
|---|---|
| Dropped column | Schema drift error, not a crash; the CSV alone dropping it falls back to the datastore |
| Renamed label | Disclosed and never matched to a sector |
| New marker | Nulled and flagged, not parsed as a number |
| Duplicate period with a different value | The series is blocked |
| Unit change in the workbook; unrecognised or missing unit | An error; the series can't be used |
| Child relabelled as its parent | Identity conflict (MOM); both rows ambiguous (SingStat) |
| Changed legend | Flagged as `LEGEND_CHANGED` |
| Missing sheet | Falls back to the CSV and says what is lost |
| Mirror mismatch | Reported period by period; unmutated mirrors agree across published precision |
| Changed unit with the same numbers | Different evidence with its own identity |

## Browser tests

Playwright 1.63 (Chromium) at **375, 768 and 1280 px**, against the offline stack (`make e2e`, and a CI job):

1. **A question becomes a verified, cited report that can be explored and exported.** The plan card and the agents' activity appear; the report has two findings citing SingStat and Data.gov.sg; the chart's table view works; all three exports are offered and the Markdown export is fetched and checked; the analysis appears in the history.
2. **An ambiguous question is asked about, and the answer resumes the analysis** to completion.
3. **A question must be long enough before it can be run.**

Every page is also checked for horizontal overflow. That check found that the report page scrolled sideways at every width (by up to 1,000 px at 375 px) because long dataset identifiers widened the grid; it was fixed.

**Result:** 9/9 pass locally and in CI.

## Performance and load

`make load` runs a purpose-built asyncio driver for 5 minutes against the offline stack: the whole platform (API, queue, worker, graph, verifier, database, event delivery) with only the model replaced by the deterministic stand-in.

**Workload:** 10 analysis slots resubmitting continuously and following their analyses to completion; 50 WebSocket listeners in all; 20 reads a second of the history and of finished analyses, on a fixed arrival schedule.

**How it is measured:**
- **Event delivery** is from each event's commit time (Postgres `track_commit_timestamp`, sent as `committed_at`) to the client receiving it. History replayed on connecting is not counted.
- **A result is lost** if it never reaches a terminal status with a stored report. **A result is incorrect** if its findings differ in series or text from the expected ones, whose values come from the independent golden expectations, or if any claim was rejected.
- **A target with no samples is "not measured"**, never met, and a run that checked no analysis fails.

**Results** (`eval/results/load/load.md`, 27 October 2026, Apple M1 Pro with 8 CPUs, Docker Desktop, one worker running four analyses at a time):

| Measure | p50 | p95 | Target |
|---|---|---|---|
| POST acknowledgement | 81 ms | 140 ms | p95 < 300 ms, **met** |
| Read (history or detail) | 32 ms | 99 ms | p95 < 300 ms, **met** |
| Event delivery (commit to client) | 29 ms | 99 ms | p95 < 1 s, **met** |
| Queue wait (submission to start) | 2.6 s | 3.6 s | reported |

- **Volume:** 782 analyses (156 a minute), 306,411 live events delivered, 5,999 reads.
- **Failures:** 0 errors, **0 lost results, 0 incorrect results** (hard gates).
- **Queue wait** comes from 10 slots sharing 4 worker slots; it is what adding workers removes.
- **Scope:** these are platform numbers, not model latency. Live analyses take 38 s (Bedrock, p50) to 77 s (OpenAI, p50) of active time, almost all of it in model calls.

## Coverage

From CI on `main`:

- **Backend core packages** (`agents`, `analytics`, `connectors`, `data`, `grounding`, `jobs`, `events`): **94%** with branch coverage, gated at 80%.
- **Backend overall:** 88%.
- **Frontend:** 66% of lines, reported as an lcov artifact, not gated.

`make coverage` reproduces both.

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and on pushes to `main` and `v*` tags:

| Job | Steps |
|---|---|
| `backend` | ruff, mypy, unit and integration tests on Postgres and Redis service containers, the 80% core coverage gate, the deterministic evaluation gates (results uploaded) |
| `frontend` | ESLint, `tsc`, Vitest with coverage (uploaded) |
| `secret-scan` | gitleaks over the commits being pushed or proposed |
| `compose-smoke` | Builds and starts the development stack and checks health, the web app and a worker job round trip; then the production compose file on the built images, with a database password containing `@ : / % # ? &`, checking the production settings and that fault routes don't exist |
| `e2e` | The offline stack, the browser tests at three widths, then a 30-second load smoke that fails on any lost or incorrect result (latency reported, not gated, because hosted runners vary) |
| `publish` | After every other job passes, on pushes only: backend and web images to GHCR |

## Reproducing the results

| Result | Command | Cost |
|---|---|---|
| Unit, integration and evaluation tests | `docker compose up -d postgres redis && make test` | free |
| Deterministic gates | `make eval` | free |
| Expected values | `make eval-expected` (recomputes `eval/golden/expected.json` from the raw snapshots) | free |
| Browser tests | `make e2e` | free |
| Load run | `make load` | free |
| Live evaluation | `make eval-live`; `make eval-live ARGS=--rescore` rescores stored runs without LLM calls; `ARGS=--redo` reruns only work that couldn't be evaluated | LLM calls (about $15 for a full run) |
| Capability probe | `make probe` | a few LLM calls |

## Known gaps

- **The latest live evaluation is incomplete** because the OpenAI account has no credits; see [Live evaluation](#live-evaluation-make-eval-live). The complete run is PR #9's.
- **Open live findings:** for G02, Bedrock answers with MOM's annual employment change rather than the year-end level (worded correctly, but indirect); for G12, GPT-5.5 reads "hiring" as the recruitment rate, which has no ICT series in the snapshots; for G08, Bedrock asks with two broad options.
- **No streaming tests:** model output isn't streamed to the browser, so partial-stream failure doesn't apply.
- **No slow-client overflow test:** the WebSocket handler awaits each send, so a slow client only slows its own connection and there is no buffer to overflow.
- **Load runs on one machine** with one worker; horizontal scaling is by design but wasn't load-tested.
