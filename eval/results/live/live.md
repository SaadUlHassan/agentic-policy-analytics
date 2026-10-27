# Live evaluation

Generated 2026-10-27T16:16:09+00:00 from snapshot data with real providers.

**Incomplete: not evaluated because a provider account had no credits (recorded as such in the call ledger).** The gates below cover only what was evaluated; this is not a full pass.

- Runs (28): G07 openai #1, G08 openai #1, G09 openai #1, G10 openai #1, G11 openai #1, G12 openai #1, G01 bedrock #2, G01 openai #2, G02 bedrock #2, G02 openai #2, G03 bedrock #2, G04 bedrock #2, G03 openai #2, G05 bedrock #2, G04 openai #2, G06 bedrock #2, G05 openai #2, G07 bedrock #2, G06 openai #2, G09 bedrock #2, G07 openai #2, G08 openai #2, G09 openai #2, G11 bedrock #2, G10 openai #2, G11 openai #2, G12 bedrock #2, G12 openai #2
- Resilience scenarios: fallback_bedrock_to_openai, primary_lost_mid_run
- Judges: openai

| Hard gate | Result |
|---|---|
| refusal correctness | pass |
| retained claim correctness | pass |
| live computation accuracy | pass |
| three agents decide | pass |
| evidence driven decisions | pass |
| runs completed | pass |
| provider resilience | pass |

| Target | Result |
|---|---|
| series identities | pass |
| clarification only when ambiguous | pass |
| consistency jaccard | pass |
| direction agreement | pass |
| qualitative recall | pass |
| human relevance | pass |

## Golden runs

| Primary provider | Refusal correctness | Series identities | Golden computations | Unexpected clarifications | Active time p50 / p95 (s) | Calls per run | Answered by primary |
|---|---|---|---|---|---|---|---|
| bedrock | 12/12 | 11/12 | 10/13 | none | 38 / 43 | 16.0 | 91% |
| openai | 12/12 | 11/12 | 8/13 | none | 77 / 114 | 16.2 | 95% |
- bedrock G02: selected ['mrsd_4_annl_emp_chg_by_ind:J58-63 Information & Communications@SSIC2020']
- openai G12: selected ['ict_vacancies']

**Retained-claim failures:** 0 across 72 runs.

**Live computation mismatches:** 0.

**Refusal correctness over all runs:** bedrock 25/26, openai 18/18.

**Golden computations made on a republication:** 0, compared in base units: all equal.

**Evidence-driven decisions (golden runs, no faults):**

- G09 bedrock: extraction rejected a candidate series: Rejected M182841:3.4@SSIC2020: Missing data for the years 1985 to 1990.
- G09 bedrock: coordinator requested more evidence: employment_level in info_comms
- G09 bedrock: extraction rejected a candidate series: Rejected M182841:3.4@SSIC2020: The series does not cover the years 1985 to 1990.
- G01 openai: extraction rejected a candidate series: Rejected M183891:1@SSIC2020: This series is quarterly employment change, not annual year-end employment level, so it cannot provide comparable All industries le
- G06 openai: extraction rejected a candidate series: Rejected M184071:1.2.4@SSIC2020: This series measures Information & Communications job vacancies but is quarterly quarter-end data rather than the planned annua
- G09 openai: extraction rejected a candidate series: Rejected M182841:3.4@SSIC2020: This series measures annual year-end employment for Information & Communications but starts only in 2008, so it does not cover 19
- G09 openai: extraction rejected a candidate series: Rejected mrsd_4_annl_emp_chg_by_ind:J58-63 Information & Communications@SSIC2020: This series is annual employment change rather than employment level and start
- G09 openai: coordinator requested more evidence: Find and validate an available year-end employment_level series for the info_comms sector covering 1985 to 1990, or determine after this extraction round whethe
- G09 openai: extraction rejected a candidate series: Rejected M182841:3.4@SSIC2020: This annual year-end employment_level series measures Information & Communications but starts in 2008, so all requested years 198
- G12 openai: extraction rejected a candidate series: Rejected M184021:1@SSIC2020: This series is total all industries, not Information & Communications, so it does not fit the planned sector.
- G12 openai: extraction rejected a candidate series: Rejected M184021:1.4.4@SSIC2020: The fetched dataset flags the Information & Communications recruitment-rate rows as ambiguous across multiple occupational-grou
- G12 openai: extraction rejected a candidate series: Rejected M184021:2.4.4@SSIC2020: This candidate is one of several ambiguous Information & Communications recruitment-rate rows and cannot be validated as the pl

**Tokens:** apac.amazon.nova-pro-v1:0: 969,079 in / 49,396 out, gpt-5.5: 631,408 in / 77,064 out. **Cost:** unknown (1 call(s) without usage, or LLM_PRICES not set).

## Consistency

Mean pairwise Jaccard of selected series: 0.89.

| Query | Runs | Jaccard | Direction conflicts |
|---|---|---|---|
| G01 | 4 | 0.67 | none |
| G02 | 4 | 0.33 | none |
| G03 | 4 | 1.00 | none |
| G04 | 4 | 1.00 | none |
| G05 | 4 | 1.00 | none |
| G06 | 4 | 1.00 | none |
| G07 | 3 | 1.00 | none |
| G08 | 4 | 1.00 | none |
| G09 | 3 | 1.00 | none |
| G10 | 4 | 1.00 | none |
| G11 | 3 | 1.00 | none |
| G12 | 3 | 0.67 | none |

## Provider resilience

| Scenario | Expected | Result |
|---|---|---|
| fallback bedrock to openai | Bedrock switched off: every call answered by OpenAI, each fallback disclosed as injected | not evaluated: a provider account had no credits |
| fallback openai to bedrock | OpenAI primary and switched off: every call answered by Bedrock | pass (completed_with_limitations, answered by bedrock) |
| verifier provider unavailable | The judge's provider is down: the check runs on the writer's provider and is disclosed as not independent | pass (completed_with_limitations, answered by bedrock) |
| primary lost mid run | Bedrock lost after the first verified finding: the run continues on OpenAI | not evaluated: a provider account had no credits |
| total outage early | Both providers down from the start: failed with LLM_UNAVAILABLE, no plan, no report | pass (failed, answered by none) |
| total outage late | Both providers lost after verified findings exist: completed with limitations, the verified findings without narrative, the early stop disclosed | pass (completed_with_limitations, answered by bedrock) |
| partial stream failure | A provider failing mid-stream leaves no duplicated text | n/a: Model output is not streamed: every call returns a complete reply or fails, and only verified results are published (draft streaming, enhancement 5, is not built). |

## Human relevance review

| Primary provider | Relevant | Not relevant | Not reviewed |
|---|---|---|---|
| bedrock | 12/12 | none | none |
| openai | 11/12 | G12 | none |

## Qualitative judge

| Judge | Judged | Recall | False positives | Missed |
|---|---|---|---|---|
| bedrock | 34/34 | 100% | 0% | none |
| openai | 0/34 | not evaluated: the provider gave no verdicts | | |
