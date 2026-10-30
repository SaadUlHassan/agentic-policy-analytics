# Innovation Assessment

**How would I evolve this platform for policy researchers in secure government environments?**

The build rests on one idea: **a policy researcher must be able to trust every number without trusting the model.** Agents choose what to fetch and compute, but every figure in a report comes from a deterministic computation, passes 14 checks, and cites the exact dataset version behind it. The proposals extend that idea. For each theme: what exists now, with an example from the code, and what I would build next.

## 1. Agent intelligence and adaptability

**Now.** The Coordinator proposes each step and a policy layer can refuse it (analysis before any data is selected, say); both appear in the timeline. Agents adapt to evidence, not scripts: in the live evaluation, Extraction rejected M182841 for a 1985–1990 question because the series starts in 2008, the Coordinator sent it back to search, and the report explained the gap from the data ("M182841 has it only for 2008 to 2025").

**Next.**
- **Learn from researchers' verdicts.** The evaluation already uses a human relevance review of each report. Make that verdict a button on every report, store each researcher's "relevant / not relevant" and dataset-fitness judgements per team, and feed them into catalogue ranking and the planning prompt. The live evaluation showed why: one model read "hiring" as the recruitment rate twice, and a team's single correction would fix it for everyone.
- **Suggested follow-ups.** The method policy already knows which further computations are eligible (a subsector breakdown, the other lag). Offer them as one-click follow-up questions that reuse the evidence already fetched.

## 2. Real-world data challenges

**Now.** Every quirk found became a check, not a workaround: MOM's release-dated files are discovered on each fetch, SingStat's 5,000-point pages are merged by series, MOM's stated unit and legend are verified every time, mirrors are compared at published precision (±50 persons), and a failed source is served from a disclosed snapshot. A mutation suite proves each check fires.

**Next.**
- **Revision tracking.** Official statistics are revised (M184071 notes a June 2022 revision). Artifacts are already content-addressed and pinned per analysis. A nightly job that refetches the catalogue could flag every past finding whose inputs have since been revised ("this finding used 2022 values that MOM has since revised by +0.3 thousand"), turning silent staleness into a notification.
- **Source-health monitor.** Run the connectors and schemas nightly and alert on drift (a renamed column, a new marker, a moved MOM file) before a researcher meets it.
- **Privacy for restricted data.** Today's data is public and aggregated. For restricted microdata, the design already gives the right shape: the LLM chooses and phrases while deterministic code computes. A classification tag on each dataset would make the router send restricted values only to approved in-region models, or send the model only schema and computed aggregates, never rows.

## 3. User trust and transparency

**Now.** No LLM writes a number. A finding is a predicate from a closed registry bound to a computed field, and the platform renders the sentence. The adversarial suite (44 corrupted claims in 17 categories) is caught at 100% with no false positives, each by the rule it breaks. Citations are derived from lineage, never written by a model. When the narrative check ran on the same provider that wrote it, the report says it was not independent.

**Next.**
- **"Show me this number."** Clicking a finding would open its computation: the formula, the exact observations used, and a recomputation in the browser. A researcher can verify a CAGR without trusting the server either.
- **Sensitivity notes.** Rerun each headline computation over neighbouring windows (2019–2024, 2021–2024) and flag findings whose direction depends on the chosen years. Choosing the window is the most common way a true number misleads.

## 4. Scalability and performance for large datasets

**Now.** Graph state holds references only, so checkpoints stay small. Dataset artifacts are content-addressed and shared across analyses, and computations are keyed by fingerprint so a resumed step reuses them. Workers scale horizontally; leases, the reconciler and the source rate limits coordinate through Postgres and Redis. Under load (10 concurrent analyses, 50 WebSocket clients, 20 reads a second) the platform kept p95 event delivery at 99 ms with zero lost or incorrect results. The main delay is queue wait (p50 2.6 s) on a single worker, which is what more workers remove.

**Next.**
- **Columnar evidence and pushed-down computation.** Store observations as Parquet and compute with DuckDB, so a statistic over a large establishment-level table runs where the data is and only results reach the agents. Reuse each artifact across analyses until its source's `updated_at` changes.

## 5. Collaboration and knowledge sharing

**Now.** Every analysis is reproducible from its export: the JSON bundle pins each dataset version with its raw payload hashes, and the CSV holds the exact observations used.

**Next.**
- **Fork an analysis.** Rerun it with one change (a period, a sector), reusing cached evidence, and show what changed.
- **An evidence library.** Verified findings, with their lineage and team annotations ("this dip is the 2020 reclassification"), become citable building blocks that another team's report can reuse without re-verifying.

## 6. Security and compliance in government contexts

**Now.** Production settings refuse fault injection and the offline model; gitleaks scans every pull request; ports bind to loopback; and every agent decision and LLM call is recorded (event log, call ledger), the raw material of an audit trail. There is **no authentication yet**, and the documentation says so.

**Next.**
- **Agency SSO (OIDC) with role-based access,** analyses scoped to teams, and an exportable audit record per analysis.
- **Deployment inside the Government Commercial Cloud** with single-region model endpoints. The APAC inference profile used today can route within the APAC region, which supports residency but doesn't by itself guarantee it.
- **Prompt-injection hardening:** source labels and footnotes already reach prompts, so treat them as data with strict delimiting and output validation, as the verifier already does for numbers.

These are supporting controls; compliance would still need the agency's own assessment.

## 7. Multi-cloud resilience and cost

**Now.** The router falls back between Bedrock (Nova Pro) and OpenAI (GPT-5.5) in both directions, owns all retries, opens a circuit breaker after three failures, and records every call. That record proved its worth when the OpenAI account ran out of credits mid-evaluation: the ledger identified exactly which runs were affected, and they were reported as "not evaluated", not as passes or failures. Cost is shown only when every call's usage is known. A live analysis cost at least $0.20; the offline mode ran the end-to-end and load tests (782 analyses) for nothing.

**Next.**
- **Budget guards.** A per-team spending cap, checked against the ledger before each analysis starts, so spending stops at a known point rather than when a provider account runs dry mid-run.
- **Cost-aware routing.** Routing decisions are short structured outputs, and a smaller model would do; keep the stronger model for drafting and judging. The ledger already records each call's purpose and tokens, so the saving can be measured before it's adopted.
- **A third, self-hosted fallback.** An open-weights model hosted in-region would cover both a commercial outage and data that mustn't leave the agency. It would have to pass the same capability probe the current models passed.
