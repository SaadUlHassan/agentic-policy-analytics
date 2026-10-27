# Live evaluation

Generated 2026-10-27T12:45:17+00:00 from snapshot data with real providers.

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
| series identities | **FAIL** |
| clarification only when ambiguous | **FAIL** |
| consistency jaccard | pass |
| direction agreement | pass |
| qualitative recall | pass |

## Golden runs

| Primary provider | Refusal correctness | Series identities | Golden computations | Unexpected clarifications | Active time p50 / p95 (s) | Calls per run | Answered by primary |
|---|---|---|---|---|---|---|---|
| bedrock | 12/12 | 10/12 | 7/13 | G09 | 45 / 54 | 18.5 | 94% |
| openai | 12/12 | 10/12 | 6/13 | none | 71 / 160 | 16.8 | 95% |
- bedrock G01: selected ['ict_employment_change']
- bedrock G02: selected ['mrsd_4_annl_emp_chg_by_ind:J58-63 Information & Communications@SSIC2020']
- openai G07: selected ['d_01966fdb498fa7fa2863635e25539693:it and other information services@SSIC2020', 'ict_vacancies_annual_average']
- openai G12: selected ['ict_vacancies']

**Retained-claim failures:** 0 across 72 runs.

**Live computation mismatches:** 0.

**Refusal correctness over all runs:** bedrock 36/36, openai 36/36.

**Golden computations made on a republication:** 14, compared in base units: all equal.

**Evidence-driven decisions (golden runs, no faults):**

- G01 bedrock: coordinator requested more analysis: compute statistics on the selected series and draft findings
- G02 bedrock: coordinator requested more analysis: compute statistics on the selected series and draft findings
- G03 bedrock: coordinator requested more analysis: compute the compound annual growth rate of employment in the Information & Communications sector between 2020 and 2024
- G04 bedrock: coordinator requested more analysis: compute statistics on the selected series and draft findings
- G05 bedrock: coordinator requested more analysis: compute statistics on the selected series and draft findings
- G06 bedrock: coordinator requested more analysis: compute the correlation between annual employment in the Information & Communications sector and annual ICT job vacancies from 2020 to 2024.
- G07 bedrock: coordinator requested more analysis: compute statistics on the selected series and draft findings
- G11 bedrock: coordinator requested more analysis: compute statistics on the selected series and draft findings
- G12 bedrock: coordinator requested more analysis: compute statistics on the selected series and draft findings
- G06 openai: extraction rejected a candidate series: Rejected M184071:1.2.4@SSIC2020: Although it measures the correct SSIC 2020 Information & Communications job vacancy stock and covers 2020-Q1 to 2024-Q4, it is 
- G06 openai: coordinator requested more analysis: Recompute the annual comparison using the verified employment and vacancy series, explicitly annualising quarterly vacancy observations with a documented method
- G09 openai: extraction rejected a candidate series: Rejected M182841:3.4@SSIC2020: This annual employment-level series is the correct sector and metric, but it starts in 2008 and has no observations for 1985–1990

**Tokens:** apac.amazon.nova-pro-v1:0: 1,929,684 in / 100,257 out, gpt-5.5: 1,455,073 in / 178,846 out. **Cost:** unknown (4 call(s) without usage, or LLM_PRICES not set).

## Consistency

Mean pairwise Jaccard of selected series: 0.81.

| Query | Runs | Jaccard | Direction conflicts |
|---|---|---|---|
| G01 | 6 | 0.30 | none |
| G02 | 6 | 0.47 | none |
| G03 | 6 | 1.00 | none |
| G04 | 6 | 1.00 | none |
| G05 | 6 | 1.00 | none |
| G06 | 6 | 1.00 | none |
| G07 | 6 | 0.57 | none |
| G08 | 6 | 1.00 | none |
| G09 | 6 | 1.00 | none |
| G10 | 6 | 1.00 | none |
| G11 | 6 | 0.53 | none |
| G12 | 6 | 0.83 | none |

## Provider resilience

| Scenario | Expected | Result |
|---|---|---|
| fallback bedrock to openai | Bedrock switched off: every call answered by OpenAI, each fallback disclosed as injected | pass (completed_with_limitations, answered by openai) |
| fallback openai to bedrock | OpenAI primary and switched off: every call answered by Bedrock | pass (completed_with_limitations, answered by bedrock) |
| verifier provider unavailable | The judge's provider is down: the check runs on the writer's provider and is disclosed as not independent | pass (completed_with_limitations, answered by bedrock) |
| primary lost mid run | Bedrock lost after the first verified finding: the run continues on OpenAI | pass (completed_with_limitations, answered by bedrock, openai) |
| total outage early | Both providers down from the start: failed with LLM_UNAVAILABLE, no plan, no report | pass (failed, answered by none) |
| total outage late | Both providers lost after verified findings exist: completed with limitations, the verified findings without narrative, the early stop disclosed | pass (completed_with_limitations, answered by bedrock) |
| partial stream failure | A provider failing mid-stream leaves no duplicated text | n/a: Model output is not streamed: every call returns a complete reply or fails, and only verified results are published (draft streaming, enhancement 5, is not built). |

## Qualitative judge

| Judge | Judged | Recall | False positives | Missed |
|---|---|---|---|---|
| bedrock | 34/34 | 100% | 0% | none |
| openai | 34/34 | 100% | 0% | none |
