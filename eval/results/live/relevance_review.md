# Relevance review

For each golden run, mark whether the report answers the question a policy researcher asked:
the right sector, measures and period, findings that address the question, and limitations
that explain any gap.
Target: at least 10 of 12 relevant for each primary provider.

**Proposed verdicts** below are a pre-review by the development assistant, which also built the system. They are not the human review: confirm or override each by ticking a box (and saying why for 'Not relevant'). Proposed tally: Bedrock 9/12, OpenAI 11/12.

## G01 (bedrock primary): Analyse employment trends in the technology sector from 2020-2024

Covers: trend, change and CAGR of a stock. Status: completed_with_limitations.
Analysis id: 123e6338-b37c-4431-826a-94f3ab20c092
Plan: To analyse employment trends in the technology sector from 2020-2024. (sectors ['info_comms'], metrics ['employment_level', 'employment_change', 'job_vacancies', 'recruitment_rate'], 2020-2024).
Summary: Employment in the Information & Communications sector increased over the observed period. The rate of employment growth was lower in the latter part of the period compared to the earlier part.

Findings:

- Employment change in Information & Communications totalled +26,800 persons between 2020-Q1 and 2024-Q4 and employment change in Information & Communications averaged 2,600 persons less in 2022-Q3 to 2024-Q4 than in 2020-Q1 to 2022-Q2.

Limitations:

- No verified finding covers employment level in Information & Communications.
- No verified finding covers job vacancies in Information & Communications.
- No verified finding covers recruitment rate in Information & Communications.
- M183891: using snapshot retrieved 2026-10-25
- The data does not provide insights into the reasons behind the employment changes.
- The analysis does not cover employment trends beyond the specified period.

Proposed verdict: **Relevant**: borderline: describes the trend through net employment change and its slowdown, but misses the employment level, CAGR and trend the question invites; the gaps are disclosed.

- [x] Relevant
- [ ] Not relevant. Why:

## G02 (bedrock primary): How did employment in information and communications change in 2023 compared with 2022?

Covers: year-on-year change. Status: completed.
Analysis id: 81eaa7d4-19ec-43c5-bd34-8cd526d4b17a
Plan: To determine the change in employment in the Information & Communications sector in 2023 compared to 2022. (sectors ['info_comms'], metrics ['employment_change'], 2022-2023).
Summary: Employment in the Information & Communications sector showed a positive change between the two periods. However, the average employment change was lower in the later period compared to the earlier period.

Findings:

- Employment change in Information & Communications totalled +9.2 thousand persons between 2022 and 2023.
- Meanwhile, employment change in Information & Communications averaged 19.4 thousand persons less in 2023 to 2023 than in 2022 to 2022.

Limitations:

- mrsd_4_annl_emp_chg_by_ind: using snapshot retrieved 2026-10-25
- The data does not include detailed breakdowns by sub-sectors within Information & Communications.

Proposed verdict: **Not relevant**: misleading: answers with MOM's annual change summed over 2022 and 2023 (+9.2 thousand) and a summary saying employment 'showed a positive change', while employment fell in 2023.

- [ ] Relevant
- [x] Not relevant. Why:

## G03 (bedrock primary): What was the compound annual growth rate of employment in information and communications between 2020 and 2024?

Covers: compound annual growth. Status: completed.
Analysis id: cfc84118-9d5c-4cba-a563-e0b3cbf5fba9
Plan: Calculate the compound annual growth rate of employment in the Information & Communications sector between 2020 and 2024. (sectors ['info_comms'], metrics ['employment_level'], 2020-2024).

Findings:

- Employment level in Information & Communications grew at a compound rate of 3.4% a year between 2020 and 2024.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- The growth rate is specific to the Information & Communications sector and may not represent other sectors.
- The data does not provide insights into the quality or nature of the jobs created.
- External factors influencing employment growth are not accounted for in the findings.

Proposed verdict: **Relevant**: states the requested CAGR for the requested sector and period.

- [x] Relevant
- [ ] Not relevant. Why:

## G04 (bedrock primary): Did quarterly employment growth in information and communications weaken after mid-2022, compared with 2020 to mid-2022?

Covers: period comparison of a flow. Status: completed.
Analysis id: 065b08f3-9df7-4c98-916a-81e182aa9226
Plan: To determine if quarterly employment growth in the Information & Communications sector weakened after mid-2022 compared to the period from 2020 to mid-2022. (sectors ['info_comms'], metrics ['employment_change'], 2021-2025).
Summary: The average quarterly employment change in the Information & Communications sector was lower in the period from 2023-Q3 to 2025-Q4 compared to the period from 2021-Q1 to 2023-Q2. The total employment change showed a decline in the later period.

Findings:

- In contrast, employment change in Information & Communications averaged 3,820 persons less in 2023-Q3 to 2025-Q4 than in 2021-Q1 to 2023-Q2.
- Meanwhile, employment change in Information & Communications totalled -9,900 persons between 2023-Q3 and 2025-Q4 and employment change in Information & Communications totalled +28,300 persons between 2021-Q1 and 2023-Q2.

Limitations:

- M183891: using snapshot retrieved 2026-10-25

Proposed verdict: **Not relevant**: compares 2021-Q1..2023-Q2 with 2023-Q3..2025-Q4: the split is at mid-2023, not mid-2022, so it does not answer the question asked.

- [ ] Relevant
- [x] Not relevant. Why:

## G05 (bedrock primary): Were ICT job vacancies and quarterly ICT employment change related between 2020 and 2024?

Covers: quarterly correlation (the named pair). Status: completed.
Analysis id: 4cd9125b-caae-4ce5-ac74-08ce2e1aa8fa
Plan: To determine if there is a relationship between ICT job vacancies and quarterly ICT employment change between 2020 and 2024. (sectors ['info_comms'], metrics ['job_vacancies', 'employment_change'], 2020-2024).
Summary: Job vacancies and employment change in the Information & Communications sector tended to be higher together in the same quarter and in the following quarter. This relationship was observed over multiple quarters.

Findings:

- Job vacancies in Information & Communications and employment change in Information & Communications in the same quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.47 over 20 quarters; exploratory, not evidence of cause).
- Meanwhile, employment change in Information & Communications totalled +26.8 thousand persons between 2020-Q1 and 2024-Q4.
- Meanwhile, job vacancies in Information & Communications and employment change in Information & Communications in the following quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.36 over 19 quarters; exploratory, not evidence of cause).

Limitations:

- Job vacancies in Information & Communications and employment change in Information & Communications: consecutive quarters are serially dependent, so the coefficient overstates how much independent evidence there is; it shows co-movement, not cause
- Job vacancies in Information & Communications and employment change in Information & Communications: the two series count different populations (establishments vs total employment)
- M184071: using snapshot retrieved 2026-10-25
- mrsd_3_qtly_emp_chg_by_ind: using snapshot retrieved 2026-10-25
- The findings are exploratory and do not establish causation.
- The analysis covers a specific time period and may not be representative of other periods.

Proposed verdict: **Relevant**: both lags of the named pair, stated as exploratory associations.

- [x] Relevant
- [ ] Not relevant. Why:

## G06 (bedrock primary): Is annual employment in information and communications correlated with annual ICT job vacancies from 2020 to 2024?

Covers: refused annual correlation. Status: completed_with_limitations.
Analysis id: f74700e7-3c7e-4db9-8488-7e361416435e
Plan: To determine if there is a correlation between annual employment in the Information & Communications sector and annual ICT job vacancies from 2020 to 2024. (sectors ['info_comms'], metrics ['employment_level', 'job_vacancies'], 2020-2024).
Summary: The employment level and job vacancies in the Information & Communications sector have shown an upward trend over the observed period. Both metrics experienced growth, with job vacancies increasing at a higher rate compared to employment levels.

Findings:

- Employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024 and employment level in Information & Communications grew at a compound rate of 3.4% a year between 2020 and 2024.
- Over the same period, job vacancies in Information & Communications rose by 1,700 vacancies between 2020 and 2024 and job vacancies in Information & Communications grew at a compound rate of 8.2% a year between 2020 and 2024.

Limitations:

- Employment level in Information & Communications (annual) and job vacancies in Information & Communications (annual) were not correlated: REFERENCE_MISMATCH (both are stocks but observed differently (year_end vs average_of_quarter_ends), so equal period labels do not describe the same moment)
- M182841: using snapshot retrieved 2026-10-25
- d_01966fdb498fa7fa2863635e25539693: using snapshot retrieved 2026-10-25
- The findings do not establish a causal relationship between employment levels and job vacancies.
- The analysis is limited to the Information & Communications sector and may not be representative of other sectors.

Proposed verdict: **Relevant**: the annual correlation is refused with a clear REFERENCE_MISMATCH explanation; the trend findings are supporting context.

- [x] Relevant
- [ ] Not relevant. Why:

## G07 (bedrock primary): How did job vacancies in IT and other information services change compared with the wider ICT sector, 2020 to 2024?

Covers: subsector kept distinct from its parent. Status: completed.
Analysis id: 12e78cba-6d88-4faa-8f5c-db6d9fbcca8f
Plan: To compare the change in job vacancies in IT and other information services with the wider ICT sector from 2020 to 2024. (sectors ['it_info_services', 'info_comms'], metrics ['job_vacancies'], 2020-2024).
Summary: Job vacancies in IT & Other Information Services showed a greater increase compared to the wider Information & Communications sector over the observed period. The upward trend in job vacancies was more pronounced in IT & Other Information Services.

Findings:

- In contrast, job vacancies in IT & Other Information Services rose by 1,100 vacancies between 2020-Q1 and 2024-Q4 and job vacancies in Information & Communications rose by 1,000 vacancies between 2020-Q1 and 2024-Q4.
- Meanwhile, job vacancies in IT & Other Information Services grew at a compound rate of 5.2% a year between 2020-Q1 and 2024-Q4 and job vacancies in Information & Communications grew at a compound rate of 4.2% a year between 2020-Q1 and 2024-Q4.
- Over the same period, job vacancies in IT & Other Information Services trended upward by about 179 vacancies a year between 2020-Q1 and 2024-Q4 and job vacancies in Information & Communications trended upward by about 161 vacancies a year between 2020-Q1 and 2024-Q4.

Limitations:

- M184071: using snapshot retrieved 2026-10-25
- The data does not cover other potential influencing factors such as economic conditions or industry-specific events.
- The report does not include projections or future trends beyond the observed period.

Proposed verdict: **Relevant**: subsector and parent compared side by side on three measures.

- [x] Relevant
- [ ] Not relevant. Why:

## G08 (bedrock primary): How is the sector doing?

Covers: ambiguous question. Status: awaiting_input.
Analysis id: 9a2c453f-ac58-44cd-9e00-9cdabc5cd49f
Asked: Which sector are you interested in? Please choose from the following options: Goods-producing industries, Services, Manufacturing, Construction, Wholesale & Retail Trade, Transportation & Storage, Accommodation & Food Services, Information & Communications, IT & Other Information Services, Telecommunications, Broadcasting & Publishing, Financial & Insurance Services, Real Estate Services, Professional Services, Administrative & Support Services. Options: ['Goods-producing industries', 'Services', 'Manufacturing', 'Construction']

Findings:

- none

Limitations:

- none

Proposed verdict: **Relevant**: borderline: asking is right, but the four options offered (goods-producing, services, manufacturing, construction) leave out Information & Communications, listed only in the question text.

- [x] Relevant
- [ ] Not relevant. Why:

## G09 (bedrock primary): Analyse employment in information and communications from 1985 to 1990

Covers: period outside the data's coverage. Status: completed_with_limitations.
Analysis id: 164a2e06-96c7-42e9-8e39-743d3eccd1fc
Plan: Analyse employment in the Information & Communications sector from 1985 to 1990 using a specific metric. (sectors ['info_comms'], metrics [], 1985-1990).
Asked: Which metric would you like to use for the analysis of employment in the Information & Communications sector from 1985 to 1990? Options: ['employment_level', 'employment_change', 'job_vacancies', 'recruitment_rate']

Findings:

- none

Limitations:

- The question could not be mapped to supported data: no metric chosen

Proposed verdict: **Not relevant**: the only explanation is 'could not be mapped to supported data: no metric chosen'; the researcher is not told the data starts in 2008.

- [ ] Relevant
- [x] Not relevant. Why:

## G10 (bedrock primary): What happened to HDB resale flat prices in 2024?

Covers: out of domain. Status: completed_with_limitations.
Analysis id: 6df8371c-eff1-4c5b-b243-541c581d255a
Plan: To understand the changes in HDB resale flat prices in 2024. (sectors [], metrics [], 2024-2024).

Findings:

- none

Limitations:

- The question is about HDB resale flat prices, which is not part of Singapore labour-market data by industry.

Proposed verdict: **Relevant**: correctly declined as outside labour-market data, with no findings.

- [x] Relevant
- [ ] Not relevant. Why:

## G11 (bedrock primary): How has employment in Singapore's infocomm sector developed between 2020 and 2024?

Covers: paraphrase of G01. Status: completed_with_limitations.
Analysis id: 91041128-034a-40db-b820-b84874f7af99
Plan: To understand the development of employment in Singapore's infocomm sector between 2020 and 2024. (sectors ['info_comms'], metrics ['employment_level', 'employment_change'], 2020-2024).

Findings:

- Employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024.
- Over the same period, employment level in Information & Communications grew at a compound rate of 3.4% a year between 2020 and 2024.
- Meanwhile, employment level in Information & Communications trended upward by about 5.4 thousand persons a year between 2020 and 2024.
- Over the same period, employment change in Information & Communications totalled +26.8 thousand persons between 2020 and 2024.
- Meanwhile, employment change in Information & Communications averaged 6.0 thousand persons less in 2022 to 2024 than in 2020 to 2021.

Limitations:

- Employment level in Information & Communications (annual) and employment change in Information & Communications (annual) were not correlated: NO_PAIRING_RULE (no declared rule pairs a stock (year_end) with a flow (year_end_difference) at annual frequency)
- M182841: using snapshot retrieved 2026-10-25
- mrsd_4_annl_emp_chg_by_ind: using snapshot retrieved 2026-10-25
- The data does not include detailed breakdowns by sub-sectors within Infocomm.
- The report does not cover employment projections beyond the observed period.

Proposed verdict: **Relevant**: employment level change, CAGR and trend, plus net change, for the requested period.

- [x] Relevant
- [ ] Not relevant. Why:

## G12 (bedrock primary): Quarter by quarter from 2020 to 2024, did more ICT job openings go with stronger ICT hiring?

Covers: paraphrase of G05. Status: completed.
Analysis id: 872dad75-528a-41a3-b402-a4270e63eb88
Plan: To determine if there is a correlation between the number of job openings and the strength of hiring in the Information & Communications (ICT) sector from 2020 to 2024. (sectors ['info_comms'], metrics ['job_vacancies', 'employment_change'], 2020-2024).
Summary: The findings indicate a positive association between job vacancies and employment change in the Information & Communications sector, both within the same quarter and in the following quarter. This suggests that periods with higher job openings tended to coincide with stronger hiring.

Findings:

- Over the same period, job vacancies in Information & Communications and employment change in Information & Communications in the same quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.47 over 20 quarters; exploratory, not evidence of cause) and job vacancies in Information & Communications and employment change in Information & Communications in the following quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.36 over 19 quarters; exploratory, not evidence of cause).
- Meanwhile, employment change in Information & Communications totalled +26.8 thousand persons between 2020-Q1 and 2024-Q4.

Limitations:

- Job vacancies in Information & Communications and employment change in Information & Communications: consecutive quarters are serially dependent, so the coefficient overstates how much independent evidence there is; it shows co-movement, not cause
- Job vacancies in Information & Communications and employment change in Information & Communications: the two series count different populations (establishments vs total employment)
- M184071: using snapshot retrieved 2026-10-25
- mrsd_3_qtly_emp_chg_by_ind: using snapshot retrieved 2026-10-25
- The analysis is exploratory and does not establish causation.
- The findings are based on a specific time frame and may not apply to other periods.
- The data is aggregated and may not reflect individual company experiences.

Proposed verdict: **Relevant**: both lags of vacancies against net employment change: answers 'openings with hiring' quarter by quarter.

- [x] Relevant
- [ ] Not relevant. Why:

## G01 (openai primary): Analyse employment trends in the technology sector from 2020-2024

Covers: trend, change and CAGR of a stock. Status: completed.
Analysis id: 3403f8d1-0fc6-4d38-a818-e43534c69942
Plan: Analyse how employment in Singapore's technology sector evolved over 2020–2024. (sectors ['info_comms'], metrics ['employment_level'], 2020-2024).
Summary: Employment in Information and Communications was higher at the end of the period than at the start, showing overall growth across the period reviewed. The series also shows a peak before the end of the period, followed by a small decline in the latest interval.

Findings:

- Employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024 and employment level in Information & Communications rose by 14.4% between 2020 and 2024.
- Employment level in Information & Communications was 157.6 thousand persons in 2020 and employment level in Information & Communications was 180.3 thousand persons in 2024.
- In addition, employment level in Information & Communications was 187.8 thousand persons in 2022.
- Meanwhile, employment level in Information & Communications fell by 1.6 thousand persons between 2023 and 2024 and employment level in Information & Communications fell by 0.9% between 2023 and 2024.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- The findings use Information and Communications as the sector measure, which may not cover all technology roles or firms.
- The findings describe employment levels and changes, but not job quality, pay, vacancies, or hours worked.
- The findings do not explain why employment changed.

Proposed verdict: **Relevant**: level change, growth and the 2022 peak with the later dip: a direct trend answer.

- [x] Relevant
- [ ] Not relevant. Why:

## G02 (openai primary): How did employment in information and communications change in 2023 compared with 2022?

Covers: year-on-year change. Status: completed.
Analysis id: 8ebbf683-ff28-4e43-9766-4adafc913c29
Plan: Assess how employment in Singapore’s Information & Communications sector changed in 2023 compared with 2022. (sectors ['info_comms'], metrics ['employment_level'], 2022-2023).
Summary: Employment in information and communications was lower in the latest period than in the previous period. The verified findings show a modest decline in both the employment level and the relative change.

Findings:

- Employment level in Information & Communications was 187.8 thousand persons in 2022.
- By comparison, employment level in Information & Communications was 181.9 thousand persons in 2023.
- Overall, employment level in Information & Communications fell by 5.9 thousand persons between 2022 and 2023.
- In addition, employment level in Information & Communications fell by 3.1% between 2022 and 2023.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- The findings describe the size of the change but do not explain why it happened.
- The figures refer only to information and communications, not the wider labour market.
- The comparison covers only the periods provided, so it does not show longer-term trends.

Proposed verdict: **Relevant**: 2022 and 2023 levels with the fall in persons and per cent.

- [x] Relevant
- [ ] Not relevant. Why:

## G03 (openai primary): What was the compound annual growth rate of employment in information and communications between 2020 and 2024?

Covers: compound annual growth. Status: completed.
Analysis id: a8b46223-ac6c-4b52-a4b4-ac300c618d2e
Plan: Estimate the compound annual growth rate of employment in Singapore’s Information & Communications sector from 2020 to 2024. (sectors ['info_comms'], metrics ['employment_level'], 2020-2024).
Summary: Employment in information and communications increased over the period reviewed. The verified findings show compound annual growth in the sector alongside a higher employment level at the end of the period.

Findings:

- Employment level in Information & Communications was 157.6 thousand persons in 2020.
- By comparison, employment level in Information & Communications was 180.3 thousand persons in 2024.
- Overall, employment level in Information & Communications grew at a compound rate of 3.4% a year between 2020 and 2024.
- In addition, employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- The findings cover only employment in information and communications.
- The summary does not explain why employment changed.
- The figures are reported as verified findings and are not independently recalculated here.

Proposed verdict: **Relevant**: states the requested CAGR with the endpoint levels.

- [x] Relevant
- [ ] Not relevant. Why:

## G04 (openai primary): Did quarterly employment growth in information and communications weaken after mid-2022, compared with 2020 to mid-2022?

Covers: period comparison of a flow. Status: completed.
Analysis id: 016e383e-8429-4054-b866-4cc0dcdd4f44
Plan: Assess whether quarterly employment growth in Singapore's Information & Communications sector weakened after mid-2022 relative to the period from 2020 to mid-2022. (sectors ['info_comms'], metrics ['employment_change'], 2021-2025).
Summary: The verified findings indicate that employment growth in information and communications weakened after the earlier expansion phase. The sector shifted from net job gains before the break to net job losses afterward, with average quarterly change lower in the later period and a downward trend evident.

Findings:

- Employment change in Information & Communications totalled +23,700 persons between 2021-Q1 and 2022-Q2.
- In contrast, employment change in Information & Communications totalled -5,300 persons between 2022-Q3 and 2025-Q4.
- Overall, employment change in Information & Communications averaged 4,329 persons less in 2022-Q3 to 2025-Q4 than in 2021-Q1 to 2022-Q2.
- Separately, employment change in Information & Communications averaged 3,820 persons less in 2023-Q3 to 2025-Q4 than in 2021-Q1 to 2023-Q2.
- In addition, employment change in Information & Communications trended downward by about 973 persons a year between 2022-Q3 and 2025-Q4.
- Meanwhile, employment change in Information & Communications was +4,200 persons in 2022-Q3.

Limitations:

- M183891: using snapshot retrieved 2026-10-25
- The findings describe employment changes only, not why they occurred.
- The comparison depends on the chosen break point and periods.
- The results are for the information and communications sector as a whole, so they may hide differences within the sector.
- The findings do not show whether the pattern reflects temporary movements or lasting shifts beyond the observed period.

Proposed verdict: **Relevant**: borderline: correct split at 2022-Q3 and a clear 'weakened' answer, but the earlier window starts in 2021, not 2020, and runs past 2024.

- [x] Relevant
- [ ] Not relevant. Why:

## G05 (openai primary): Were ICT job vacancies and quarterly ICT employment change related between 2020 and 2024?

Covers: quarterly correlation (the named pair). Status: completed.
Analysis id: dd6e01f6-516e-4218-8e7e-18d570b63366
Plan: Assess whether job vacancies and quarterly employment changes in Singapore's ICT sector were related from 2020 to 2024. (sectors ['info_comms'], metrics ['job_vacancies', 'employment_change'], 2020-2024).

Findings:

- Job vacancies in Information & Communications rose by 1,000 vacancies between 2020-Q1 and 2024-Q4.
- Overall, job vacancies in Information & Communications trended upward by about 161 vacancies a year between 2020-Q1 and 2024-Q4.
- In addition, employment change in Information & Communications totalled +26,800 persons between 2020-Q1 and 2024-Q4.
- Meanwhile, employment change in Information & Communications averaged 2,600 persons less in 2022-Q3 to 2024-Q4 than in 2020-Q1 to 2022-Q2.
- Separately, job vacancies in Information & Communications and employment change in Information & Communications in the same quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.47 over 20 quarters; exploratory, not evidence of cause).
- By comparison, job vacancies in Information & Communications and employment change in Information & Communications in the following quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.36 over 19 quarters; exploratory, not evidence of cause).

Limitations:

- Job vacancies in Information & Communications and employment change in Information & Communications: consecutive quarters are serially dependent, so the coefficient overstates how much independent evidence there is; it shows co-movement, not cause
- Job vacancies in Information & Communications and employment change in Information & Communications: the two series count different populations (establishments vs total employment)
- M184071: using snapshot retrieved 2026-10-25
- M183891: using snapshot retrieved 2026-10-25
- The analysis is exploratory and does not establish cause.
- The period covered is limited.
- Quarterly labour market data can be volatile.
- The measures may be affected by definitions, revisions, or survey error.
- Other labour market factors were not assessed.

Proposed verdict: **Relevant**: both lags of the named pair, with context on each series.

- [x] Relevant
- [ ] Not relevant. Why:

## G06 (openai primary): Is annual employment in information and communications correlated with annual ICT job vacancies from 2020 to 2024?

Covers: refused annual correlation. Status: completed_with_limitations.
Analysis id: 8bf92309-76f3-4482-8d92-fcc4568e5f3e
Plan: Assess whether annual employment levels in Information & Communications are correlated with annual job vacancies in the same sector from 2020 to 2024. (sectors ['info_comms'], metrics ['employment_level', 'job_vacancies'], 2020-2024).
Summary: The verified findings show that employment and job vacancies in Information and Communications both moved upward over the period reviewed. This indicates a shared upward pattern, but the findings do not provide a direct correlation measure or evidence about the strength of the relationship.

Findings:

- Employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024.
- In addition, employment level in Information & Communications grew at a compound rate of 3.4% a year between 2020 and 2024.
- Meanwhile, job vacancies in Information & Communications rose by 1,700 vacancies between 2020 and 2024.
- Separately, job vacancies in Information & Communications grew at a compound rate of 8.2% a year between 2020 and 2024.
- Overall, employment level in Information & Communications trended upward by about 5.4 thousand persons a year between 2020 and 2024.
- Overall, job vacancies in Information & Communications trended upward by about 190 vacancies a year between 2020 and 2024.
- Separately, employment level in Information & Communications was 180.3 thousand persons in 2024 and job vacancies in Information & Communications was 6,300 vacancies in 2024.
- Employment level in Information & Communications was 157.6 thousand persons in 2020 and job vacancies in Information & Communications was 4,600 vacancies in 2020.

Limitations:

- Employment level in Information & Communications (annual) and job vacancies in Information & Communications (annual) were not correlated: REFERENCE_MISMATCH (both are stocks but observed differently (year_end vs average_of_quarter_ends), so equal period labels do not describe the same moment)
- M182841: using snapshot retrieved 2026-10-25
- d_01966fdb498fa7fa2863635e25539693: using snapshot retrieved 2026-10-25
- No correlation statistic is provided.
- The findings cover a short time span.
- The findings show movement over time, not whether one measure explains the other.
- Definitions and data collection methods are not described.

Proposed verdict: **Relevant**: the annual correlation is refused with a clear REFERENCE_MISMATCH explanation; the summary says no correlation measure is given.

- [x] Relevant
- [ ] Not relevant. Why:

## G07 (openai primary): How did job vacancies in IT and other information services change compared with the wider ICT sector, 2020 to 2024?

Covers: subsector kept distinct from its parent. Status: completed.
Analysis id: 38c118c2-107f-46a6-a8b4-fbb954b59136
Plan: Assess how job vacancies in IT & Other Information Services changed relative to the broader Information & Communications sector in Singapore from 2020 to 2024. (sectors ['it_info_services', 'info_comms'], metrics ['job_vacancies'], 2020-2024).
Summary: Job vacancies in IT and other information services increased over the period, rising a little faster than vacancies in the wider information and communications sector. The wider sector still had more vacancies at both the start and end of the period.

Findings:

- Job vacancies in IT & Other Information Services rose by 37.5% between 2020 and 2024.
- By comparison, job vacancies in Information & Communications rose by 37.0% between 2020 and 2024.
- Overall, job vacancies in IT & Other Information Services trended upward by about 200 vacancies a year between 2020 and 2024 and job vacancies in Information & Communications trended upward by about 190 vacancies a year between 2020 and 2024.
- Separately, job vacancies in IT & Other Information Services was 4,000 vacancies in 2020 and job vacancies in Information & Communications was 4,600 vacancies in 2020.
- In addition, job vacancies in IT & Other Information Services was 5,500 vacancies in 2024 and job vacancies in Information & Communications was 6,300 vacancies in 2024.

Limitations:

- d_01966fdb498fa7fa2863635e25539693: using snapshot retrieved 2026-10-25
- The findings describe vacancies, not filled jobs or total employment.
- The comparison uses broad sector groupings, so it does not show differences within smaller industries.
- The findings do not explain why vacancies changed.
- Only the broad trend and start-to-end comparison are shown, so short-term movements are not described.

Proposed verdict: **Relevant**: subsector and parent compared on annual-average vacancies; a defensible reading, the question names no frequency.

- [x] Relevant
- [ ] Not relevant. Why:

## G08 (openai primary): How is the sector doing?

Covers: ambiguous question. Status: awaiting_input.
Analysis id: ea1cb990-64f1-43aa-b509-604dda0c08d6
Asked: Which sector and labour-market metric should I analyse? Options: ['Information & Communications — employment level and employment change', 'Manufacturing — employment level and employment change', 'Construction — employment level and job vacancies', 'Services — employment level, employment change, job vacancies, and recruitment rate']

Findings:

- none

Limitations:

- none

Proposed verdict: **Relevant**: asks which sector and measure, with four concrete options.

- [x] Relevant
- [ ] Not relevant. Why:

## G09 (openai primary): Analyse employment in information and communications from 1985 to 1990

Covers: period outside the data's coverage. Status: completed_with_limitations.
Analysis id: 487ae164-f21d-4883-91fe-8fde1addd4bd
Plan: Analyse employment levels in Singapore's Information & Communications industry from 1985 to 1990. (sectors ['info_comms'], metrics ['employment_level'], 1985-1990).
Summary: No verified findings were provided for employment in information and communications. As a result, the report cannot describe patterns, comparisons, or changes for the requested period.

Findings:

- none

Limitations:

- No verified finding covers employment level in info comms.
- No verified evidence was supplied.
- The requested time span cannot be assessed from the available material.
- No breakdowns or context are available to support interpretation.

Proposed verdict: **Relevant**: borderline: no findings and says the span cannot be assessed, though it does not say the data starts in 2008.

- [x] Relevant
- [ ] Not relevant. Why:

## G10 (openai primary): What happened to HDB resale flat prices in 2024?

Covers: out of domain. Status: completed_with_limitations.
Analysis id: 11c500f1-b131-4187-8ce2-73d0e269de75
Plan: Assess what happened to HDB resale flat prices in 2024. (sectors [], metrics [], 2024-2024).

Findings:

- none

Limitations:

- This is about Singapore housing prices, not Singapore labour-market data by industry.

Proposed verdict: **Relevant**: correctly declined as outside labour-market data, with no findings.

- [x] Relevant
- [ ] Not relevant. Why:

## G11 (openai primary): How has employment in Singapore's infocomm sector developed between 2020 and 2024?

Covers: paraphrase of G01. Status: completed.
Analysis id: b05a08e3-e757-44d7-8b3b-a73d510ec62c
Plan: Assess how employment in Singapore’s infocomm sector changed over 2020 to 2024. (sectors ['info_comms'], metrics ['employment_level'], 2020-2024).
Summary: Employment in Singapore’s infocomm-related sector ended higher than it began. The overall trend was upward, although employment fell during the later part of the period.

Findings:

- Employment level in Information & Communications was 157.6 thousand persons in 2020.
- By comparison, employment level in Information & Communications was 180.3 thousand persons in 2024.
- Overall, employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024.
- In addition, employment level in Information & Communications rose by 14.4% between 2020 and 2024.
- Separately, employment level in Information & Communications trended upward by about 5.4 thousand persons a year between 2020 and 2024.
- Meanwhile, employment level in Information & Communications fell by 7.5 thousand persons between 2022 and 2024.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- The findings cover employment levels only, not job quality, occupations, wages, or worker characteristics.
- They do not explain why employment changed.
- They use the Information & Communications category, which may not match every definition of the infocomm sector.

Proposed verdict: **Relevant**: level, change, CAGR-like growth, trend and the later fall: a full answer.

- [x] Relevant
- [ ] Not relevant. Why:

## G12 (openai primary): Quarter by quarter from 2020 to 2024, did more ICT job openings go with stronger ICT hiring?

Covers: paraphrase of G05. Status: completed_with_limitations.
Analysis id: ffda7b78-700e-4259-8605-4e8500f00471
Plan: Assess whether quarters with more job openings in Singapore's ICT sector were associated with stronger hiring from 2020 to 2024. (sectors ['info_comms'], metrics ['job_vacancies', 'recruitment_rate'], 2020-2024).
Summary: The verified evidence shows Information & Communications job vacancies increased over the period, with an overall upward trend and positive compound growth. The evidence also identifies the end-of-period vacancy level. Because no hiring findings are provided, these results do not show whether more openings went with stronger ICT hiring.

Findings:

- Job vacancies in Information & Communications rose by 1,000 vacancies between 2020-Q1 and 2024-Q4.
- Overall, job vacancies in Information & Communications grew at a compound rate of 4.2% a year between 2020-Q1 and 2024-Q4.
- In addition, job vacancies in Information & Communications trended upward by about 161 vacancies a year between 2020-Q1 and 2024-Q4.
- Separately, job vacancies in Information & Communications was 5,600 vacancies in 2024-Q4.

Limitations:

- No verified finding covers recruitment rate in Information & Communications.
- M184071: using snapshot retrieved 2026-10-25
- The findings do not include hiring data.
- The evidence is limited to Information & Communications job vacancies.
- The findings do not show whether vacancies and hiring moved together quarter by quarter.

Proposed verdict: **Not relevant**: reads 'hiring' as the recruitment rate, finds no ICT series for it, and reports vacancies only; the summary admits it cannot answer.

- [ ] Relevant
- [x] Not relevant. Why:
