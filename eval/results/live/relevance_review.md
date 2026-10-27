# Relevance review

For each golden run, mark whether the report answers the question a policy researcher asked:
the right sector, measures and period, findings that address the question, and limitations
that explain any gap.
Target: at least 10 of 12 relevant for each primary provider.

**Proposed verdicts** below are a pre-review by the development assistant, which also built the system. They are not the human review: confirm or override each by ticking a box (and saying why for 'Not relevant'). Proposed tally: Bedrock 12/12, OpenAI 11/12.

## G01 (bedrock primary): Analyse employment trends in the technology sector from 2020-2024

Covers: trend, change and CAGR of a stock. Status: completed_with_limitations.
Analysis id: cee85658-39e9-4dab-95b5-e618d06624b7
Plan: Analyse employment trends in the technology sector from 2020-2024 (sectors ['info_comms'], metrics ['employment_level', 'employment_change'], 2020-2024).
Summary: Employment levels in the Information & Communications sector have increased over the observed period. The sector experienced a rise in employment, with an annual growth rate and an increase in the number of persons employed each year.

Findings:

- Employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024 and employment level in Information & Communications grew at a compound rate of 3.4% a year between 2020 and 2024.
- Over the same period, employment level in Information & Communications trended upward by about 5.4 thousand persons a year between 2020 and 2024.
- Meanwhile, employment change in Information & Communications summed to +26,800 persons over 2020-Q1 to 2024-Q4.
- By comparison, employment change in Information & Communications averaged 2,600 persons less in 2022-Q3 to 2024-Q4 than in 2020-Q1 to 2022-Q2.

Limitations:

- Employment level in Information & Communications (annual) and employment change in Information & Communications (quarterly) were not correlated: FREQ_MISMATCH (annual vs quarterly; series are never resampled)
- M182841: using snapshot retrieved 2026-10-25
- M183891: using snapshot retrieved 2026-10-25
- The data does not cover other sectors for comparison.
- The report does not include projections or future trends beyond the specified period.

Proposed verdict: **Relevant**: level change, CAGR and trend, plus net quarterly change and its slowdown: a full trend answer.

- [x] Relevant
- [ ] Not relevant. Why:

## G02 (bedrock primary): How did employment in information and communications change in 2023 compared with 2022?

Covers: year-on-year change. Status: completed.
Analysis id: 30f2acff-89ea-4cc0-b034-be7fca691581
Plan: To analyze the change in employment in the Information & Communications sector in 2023 compared to 2022. (sectors ['info_comms'], metrics ['employment_change'], 2022-2023).
Summary: Employment in the Information & Communications sector showed mixed trends from 2022 to 2023, with both increases and decreases observed.

Findings:

- Employment change in Information & Communications summed to +9.2 thousand persons over 2022 to 2023.
- Meanwhile, employment change in Information & Communications averaged 19.4 thousand persons less in 2023 than in 2022.

Limitations:

- mrsd_4_annl_emp_chg_by_ind: using snapshot retrieved 2026-10-25
- The data does not cover specific sub-sectors within Information & Communications.

Proposed verdict: **Relevant**: borderline: answers through MOM's annual change ('averaged 19.4 thousand persons less in 2023 than in 2022'), now worded clearly, but never says plainly that employment fell in 2023.

- [x] Relevant
- [ ] Not relevant. Why:

## G03 (bedrock primary): What was the compound annual growth rate of employment in information and communications between 2020 and 2024?

Covers: compound annual growth. Status: completed.
Analysis id: e82e2771-cf73-44dd-bb48-0bd8acc81de8
Plan: To determine the compound annual growth rate of employment in the Information & Communications sector between 2020 and 2024. (sectors ['info_comms'], metrics ['employment_level'], 2020-2024).
Summary: The employment level in the Information & Communications sector grew at a compound annual rate. This growth indicates an increase in the number of jobs within the sector.

Findings:

- Employment level in Information & Communications grew at a compound rate of 3.4% a year between 2020 and 2024.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- The report does not provide specific employment figures for each year.
- The growth rate is an average and may not represent yearly fluctuations.
- External factors influencing employment are not discussed.

Proposed verdict: **Relevant**: states the requested CAGR for the requested sector and period.

- [x] Relevant
- [ ] Not relevant. Why:

## G04 (bedrock primary): Did quarterly employment growth in information and communications weaken after mid-2022, compared with 2020 to mid-2022?

Covers: period comparison of a flow. Status: completed.
Analysis id: 78b15a7c-73b2-477b-84d8-ae1bbce25c0b
Plan: To determine if quarterly employment growth in the Information & Communications sector weakened after mid-2022 compared to the period from 2020 to mid-2022. (sectors ['info_comms'], metrics ['employment_change'], 2020-2025).
Summary: Employment change in Information & Communications summed to a positive total over the observed period. The average quarterly employment change was lower in the later period compared to the earlier period.

Findings:

- Meanwhile, employment change in Information & Communications summed to +21,100 persons over 2020-Q1 to 2025-Q4 and employment change in Information & Communications averaged 3,019 persons less in 2022-Q3 to 2025-Q4 than in 2020-Q1 to 2022-Q2.

Limitations:

- M183891: using snapshot retrieved 2026-10-25
- The report does not provide specific quarterly data for direct comparison.

Proposed verdict: **Relevant**: compares from 2022-Q3, the question's 'after mid-2022', and says the later period was weaker.

- [x] Relevant
- [ ] Not relevant. Why:

## G05 (bedrock primary): Were ICT job vacancies and quarterly ICT employment change related between 2020 and 2024?

Covers: quarterly correlation (the named pair). Status: completed.
Analysis id: 0d4f3a47-b2e7-49ce-a720-ff868356212d
Plan: To determine if there is a relationship between ICT job vacancies and quarterly ICT employment change between 2020 and 2024. (sectors ['info_comms'], metrics ['job_vacancies', 'employment_change'], 2020-2024).
Summary: Job vacancies and employment change in the Information & Communications sector tended to be higher together both within the same quarter and in the following quarter. These trends were observed over a multi-year period.

Findings:

- Job vacancies in Information & Communications and employment change in Information & Communications in the same quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.47 over 20 quarters; exploratory, not evidence of cause).
- Meanwhile, job vacancies in Information & Communications and employment change in Information & Communications in the following quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.36 over 19 quarters; exploratory, not evidence of cause).
- Over the same period, employment change in Information & Communications summed to +26,800 persons over 2020-Q1 to 2024-Q4.

Limitations:

- Job vacancies in Information & Communications and employment change in Information & Communications: consecutive quarters are serially dependent, so the coefficient overstates how much independent evidence there is; it shows co-movement, not cause
- Job vacancies in Information & Communications and employment change in Information & Communications: the two series count different populations (establishments vs total employment)
- M184071: using snapshot retrieved 2026-10-25
- M183891: using snapshot retrieved 2026-10-25
- The findings are exploratory and do not establish causation.
- The analysis covers a specific time frame and sector, limiting broader applicability.

Proposed verdict: **Relevant**: both lags of the named pair, stated as exploratory associations.

- [x] Relevant
- [ ] Not relevant. Why:

## G06 (bedrock primary): Is annual employment in information and communications correlated with annual ICT job vacancies from 2020 to 2024?

Covers: refused annual correlation. Status: completed_with_limitations.
Analysis id: 7229ac6c-6834-4cbc-a161-c314133185ee
Plan: To determine if there is a correlation between annual employment in the information and communications sector and annual ICT job vacancies from 2020 to 2024. (sectors ['info_comms'], metrics ['employment_level', 'job_vacancies'], 2020-2024).
Summary: Employment levels and job vacancies in the Information & Communications sector have both increased over the observed period. The rise in employment levels corresponds with an increase in job vacancies.

Findings:

- Over the same period, employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024 and job vacancies in Information & Communications rose by 1,700 vacancies between 2020 and 2024.

Limitations:

- Employment level in Information & Communications (annual) and job vacancies in Information & Communications (annual) were not correlated: REFERENCE_MISMATCH (both are stocks but observed differently (year_end vs average_of_quarter_ends), so equal period labels do not describe the same moment)
- M182841: using snapshot retrieved 2026-10-25
- d_01966fdb498fa7fa2863635e25539693: using snapshot retrieved 2026-10-25
- The findings do not establish a causal relationship between employment levels and job vacancies.
- The data does not account for other factors that may influence job vacancies.
- The time frame of the data may not capture long-term trends or seasonal variations.

Proposed verdict: **Relevant**: the annual correlation is refused with a clear REFERENCE_MISMATCH explanation; the trends are context.

- [x] Relevant
- [ ] Not relevant. Why:

## G07 (bedrock primary): How did job vacancies in IT and other information services change compared with the wider ICT sector, 2020 to 2024?

Covers: subsector kept distinct from its parent. Status: completed.
Analysis id: 02fce74c-c290-49b3-b304-ed5c060c32e9
Plan: To compare the change in job vacancies in IT and other information services with the wider ICT sector from 2020 to 2024. (sectors ['it_info_services', 'info_comms'], metrics ['job_vacancies'], 2020-2024).
Summary: Job vacancies in IT & Other Information Services and Information & Communications both increased over the observed period. The IT & Other Information Services sector showed a slightly higher growth rate and annual trend increase compared to the Information & Communications sector.

Findings:

- Job vacancies in IT & Other Information Services rose by 1,100 vacancies between 2020-Q1 and 2024-Q4 and job vacancies in Information & Communications rose by 1,000 vacancies between 2020-Q1 and 2024-Q4.
- Over the same period, job vacancies in IT & Other Information Services grew at a compound rate of 5.2% a year between 2020-Q1 and 2024-Q4 and job vacancies in Information & Communications grew at a compound rate of 4.2% a year between 2020-Q1 and 2024-Q4.
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
Analysis id: 6061f518-3f25-4409-a8c0-cffcbac9ded0
Asked: Which sector are you interested in? Please choose from the following options: Options: ['Goods-producing industries', 'Services']

Findings:

- none

Limitations:

- none

Proposed verdict: **Relevant**: borderline: asking is right and the question is short, but the two options (goods-producing industries, services) are broad and leave out Information & Communications.

- [x] Relevant
- [ ] Not relevant. Why:

## G09 (bedrock primary): Analyse employment in information and communications from 1985 to 1990

Covers: period outside the data's coverage. Status: completed_with_limitations.
Analysis id: 2c8c9d5b-5842-46f5-a83d-cff9176a8514
Plan: To analyze employment in the Information & Communications sector from 1985 to 1990. (sectors ['info_comms'], metrics ['employment_level'], 1985-1990).

Findings:

- none

Limitations:

- No verified finding covers employment level in Information & Communications: M182841 has it only for 2008 to 2025, not for all of 1985 to 1990.

Proposed verdict: **Relevant**: no findings, and the limitation says why: M182841 has the series only for 2008 to 2025.

- [x] Relevant
- [ ] Not relevant. Why:

## G10 (bedrock primary): What happened to HDB resale flat prices in 2024?

Covers: out of domain. Status: completed_with_limitations.
Analysis id: 6ec548b2-70c7-4f24-a5c4-84301e273926
Plan: To understand the changes in HDB resale flat prices in 2024. (sectors [], metrics [], None-None).

Findings:

- none

Limitations:

- The question is about HDB resale flat prices, which is not part of Singapore labour-market data by industry.

Proposed verdict: **Relevant**: correctly declined as outside labour-market data, with no findings.

- [x] Relevant
- [ ] Not relevant. Why:

## G11 (bedrock primary): How has employment in Singapore's infocomm sector developed between 2020 and 2024?

Covers: paraphrase of G01. Status: completed.
Analysis id: bfb7cf98-18bb-400a-ad33-abd5436cfb27
Plan: To analyze the development of employment in Singapore's infocomm sector between 2020 and 2024. (sectors ['info_comms'], metrics ['employment_level'], 2020-2024).

Findings:

- Employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024 and employment level in Information & Communications rose by 14.4% between 2020 and 2024.
- Over the same period, employment level in Information & Communications grew at a compound rate of 3.4% a year between 2020 and 2024.
- Meanwhile, employment level in Information & Communications trended upward by about 5.4 thousand persons a year between 2020 and 2024.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- The data does not include projections beyond the observed period.
- The report does not compare the growth with other sectors.

Proposed verdict: **Relevant**: employment level change, CAGR and trend for the requested period.

- [x] Relevant
- [ ] Not relevant. Why:

## G12 (bedrock primary): Quarter by quarter from 2020 to 2024, did more ICT job openings go with stronger ICT hiring?

Covers: paraphrase of G05. Status: completed.
Analysis id: 9c32fb38-40f6-4eb1-8518-50e3c075343a
Plan: To determine if there is a correlation between the number of ICT job openings and the strength of ICT hiring on a quarterly basis from 2020 to 2024. (sectors ['info_comms'], metrics ['job_vacancies', 'employment_change'], 2020-2024).

Findings:

- Job vacancies in Information & Communications and employment change in Information & Communications in the same quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.47 over 20 quarters; exploratory, not evidence of cause).
- Meanwhile, job vacancies in Information & Communications and employment change in Information & Communications in the following quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.36 over 19 quarters; exploratory, not evidence of cause).

Limitations:

- Job vacancies in Information & Communications and employment change in Information & Communications: consecutive quarters are serially dependent, so the coefficient overstates how much independent evidence there is; it shows co-movement, not cause
- Job vacancies in Information & Communications and employment change in Information & Communications: the two series count different populations (establishments vs total employment)
- M184071: using snapshot retrieved 2026-10-25
- M183891: using snapshot retrieved 2026-10-25
- The findings are exploratory and do not establish causation.
- The analysis covers a specific time frame and may not reflect long-term trends.

Proposed verdict: **Relevant**: both lags of vacancies against net employment change: answers 'openings with hiring' quarter by quarter.

- [x] Relevant
- [ ] Not relevant. Why:

## G01 (openai primary): Analyse employment trends in the technology sector from 2020-2024

Covers: trend, change and CAGR of a stock. Status: completed.
Analysis id: 244b19be-c6de-4a7f-add1-cec139b7ff37
Plan: Analyse how employment levels in Singapore's technology sector changed over 2020 to 2024. (sectors ['info_comms'], metrics ['employment_level'], 2020-2024).
Summary: Employment in Information and Communications increased overall across the period reviewed. The series rose at first, reached a high point before easing slightly, and still ended above its starting level.

Findings:

- Employment level in Information & Communications was 157.6 thousand persons in 2020 and employment level in Information & Communications was 172.9 thousand persons in 2021.
- In addition, employment level in Information & Communications was 187.8 thousand persons in 2022 and employment level in Information & Communications was 181.9 thousand persons in 2023.
- Separately, employment level in Information & Communications was 180.3 thousand persons in 2024.
- Overall, employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024.
- Over the same period, employment level in Information & Communications trended upward by about 5.4 thousand persons a year between 2020 and 2024.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- Information and Communications may not capture all technology work across the economy.
- Only employment levels are reported; job quality, hours, wages, and vacancies are not covered.
- The findings describe changes but do not explain why employment changed.

Proposed verdict: **Relevant**: yearly levels, the overall rise and the trend: a direct trend answer.

- [x] Relevant
- [ ] Not relevant. Why:

## G02 (openai primary): How did employment in information and communications change in 2023 compared with 2022?

Covers: year-on-year change. Status: completed.
Analysis id: 2c8a973f-31b2-43e6-bc8d-f9d103f3433c
Plan: Assess how employment in Singapore's Information & Communications industry differed in 2023 compared with 2022. (sectors ['info_comms'], metrics ['employment_level'], 2022-2023).
Summary: Employment in information and communications was lower than in the prior comparison period. The verified findings show a fall in both the employment level and the percentage change measure.

Findings:

- Employment level in Information & Communications was 187.8 thousand persons in 2022 and employment level in Information & Communications was 181.9 thousand persons in 2023.
- Overall, employment level in Information & Communications fell by 5.9 thousand persons between 2022 and 2023 and employment level in Information & Communications fell by 3.1% between 2022 and 2023.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- The findings describe the change but do not explain why it happened.
- The findings cover only the information and communications sector.
- The findings do not show differences within the sector or between groups.

Proposed verdict: **Relevant**: 2022 and 2023 levels with the fall in persons and per cent.

- [x] Relevant
- [ ] Not relevant. Why:

## G03 (openai primary): What was the compound annual growth rate of employment in information and communications between 2020 and 2024?

Covers: compound annual growth. Status: completed.
Analysis id: 76d923ef-b827-442e-93ea-1cfbb92b6ffd
Plan: Calculate the compound annual growth rate of employment in Singapore’s Information & Communications sector from 2020 to 2024. (sectors ['info_comms'], metrics ['employment_level'], 2020-2024).
Summary: Employment in information and communications increased over the period reviewed. The verified finding shows steady compound annual growth, alongside a rise in the employment level.

Findings:

- Employment level in Information & Communications was 157.6 thousand persons in 2020 and employment level in Information & Communications was 180.3 thousand persons in 2024.
- Overall, employment level in Information & Communications grew at a compound rate of 3.4% a year between 2020 and 2024.
- In addition, employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- The findings cover only the information and communications sector.
- The summary does not explain why employment changed.
- The calculation depends on the starting and ending employment levels provided.

Proposed verdict: **Relevant**: states the requested CAGR with the endpoint levels.

- [x] Relevant
- [ ] Not relevant. Why:

## G04 (openai primary): Did quarterly employment growth in information and communications weaken after mid-2022, compared with 2020 to mid-2022?

Covers: period comparison of a flow. Status: completed.
Analysis id: 8c01cd51-ea00-454c-81f6-e741461d8f5b
Plan: Assess whether quarterly employment growth in Singapore's Information & Communications sector weakened after mid-2022 relative to 2020 through mid-2022. (sectors ['info_comms'], metrics ['employment_change'], 2020-2025).
Summary: The verified findings indicate that employment change in information and communications was weaker in the later period than in the earlier period. Total employment change shifted from a gain in the earlier period to a decline in the later period, although the quarter immediately after the split still showed a gain and later quarters varied.

Findings:

- Employment change in Information & Communications averaged 3,019 persons less in 2022-Q3 to 2025-Q4 than in 2020-Q1 to 2022-Q2.
- Meanwhile, employment change in Information & Communications was +4,200 persons in 2022-Q3.
- Overall, employment change in Information & Communications summed to +26,400 persons over 2020-Q1 to 2022-Q2 and employment change in Information & Communications summed to -5,300 persons over 2022-Q3 to 2025-Q4.
- Separately, employment change in Information & Communications was +4,100 persons in 2022-Q2 and employment change in Information & Communications was +1,600 persons in 2022-Q4.
- In addition, employment change in Information & Communications was -1,700 persons in 2025-Q4.

Limitations:

- M183891: using snapshot retrieved 2026-10-25
- Findings describe employment changes, not reasons for those changes.
- Results cover only information and communications.
- The comparison depends on the chosen split between earlier and later periods.
- Quarterly figures can vary, so averages and totals may hide short-run movements.

Proposed verdict: **Relevant**: compares from 2022-Q3 with totals for both parts: a clear 'weakened' answer.

- [x] Relevant
- [ ] Not relevant. Why:

## G05 (openai primary): Were ICT job vacancies and quarterly ICT employment change related between 2020 and 2024?

Covers: quarterly correlation (the named pair). Status: completed.
Analysis id: 7b2a88f1-d50f-4f2c-a7f0-3451f2080179
Plan: Assess whether ICT job vacancies and quarterly ICT employment change moved together in Singapore between 2020 and 2024. (sectors ['info_comms'], metrics ['job_vacancies', 'employment_change'], 2020-2024).
Summary: ICT job vacancies and ICT employment change tended to be higher together, both within the same quarter and when vacancies were compared with employment change in the following quarter. Vacancies rose overall, while employment change was positive across the period but weaker in the later part than in the earlier part.

Findings:

- Job vacancies in Information & Communications and employment change in Information & Communications in the same quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.47 over 20 quarters; exploratory, not evidence of cause).
- In addition, job vacancies in Information & Communications and employment change in Information & Communications in the following quarter tended to be higher together between 2020-Q1 and 2024-Q4 (Pearson r 0.36 over 19 quarters; exploratory, not evidence of cause).
- Meanwhile, job vacancies in Information & Communications rose by 1,000 vacancies between 2020-Q1 and 2024-Q4.
- Over the same period, employment change in Information & Communications summed to +26,800 persons over 2020-Q1 to 2024-Q4.
- By comparison, employment change in Information & Communications averaged 2,600 persons less in 2022-Q3 to 2024-Q4 than in 2020-Q1 to 2022-Q2.
- Overall, job vacancies in Information & Communications trended upward by about 161 vacancies a year between 2020-Q1 and 2024-Q4.

Limitations:

- Job vacancies in Information & Communications and employment change in Information & Communications: consecutive quarters are serially dependent, so the coefficient overstates how much independent evidence there is; it shows co-movement, not cause
- Job vacancies in Information & Communications and employment change in Information & Communications: the two series count different populations (establishments vs total employment)
- M184071: using snapshot retrieved 2026-10-25
- M183891: using snapshot retrieved 2026-10-25
- The comparison covers a limited run of quarterly observations.
- The findings use broad sector totals, so they may hide differences within smaller parts of the sector.

Proposed verdict: **Relevant**: both lags of the named pair, with context on each series.

- [x] Relevant
- [ ] Not relevant. Why:

## G06 (openai primary): Is annual employment in information and communications correlated with annual ICT job vacancies from 2020 to 2024?

Covers: refused annual correlation. Status: completed_with_limitations.
Analysis id: f98a37cc-c9dc-4b57-b12e-d4aed720289f
Plan: Assess whether annual employment levels in Singapore’s Information & Communications industry are correlated with annual job vacancies in the same industry from 2020 to 2024. (sectors ['info_comms'], metrics ['employment_level', 'job_vacancies'], 2020-2024).
Summary: The verified findings show that employment in information and communications increased over the period reviewed, while job vacancies in the same area also increased. Both series showed an upward annual trend, so the evidence is consistent with them moving in the same direction, but it does not establish a statistical correlation.

Findings:

- Employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024.
- Meanwhile, job vacancies in Information & Communications rose by 1,700 vacancies between 2020 and 2024.
- Overall, employment level in Information & Communications trended upward by about 5.4 thousand persons a year between 2020 and 2024 and job vacancies in Information & Communications trended upward by about 190 vacancies a year between 2020 and 2024.

Limitations:

- Employment level in Information & Communications (annual) and job vacancies in Information & Communications (annual) were not correlated: REFERENCE_MISMATCH (both are stocks but observed differently (year_end vs average_of_quarter_ends), so equal period labels do not describe the same moment)
- M182841: using snapshot retrieved 2026-10-25
- d_01966fdb498fa7fa2863635e25539693: using snapshot retrieved 2026-10-25
- Only broad annual movements are provided.
- No correlation statistic or test result is provided.
- The findings do not show whether one measure influenced the other.
- Details on data definitions and measurement quality are not provided.

Proposed verdict: **Relevant**: the annual correlation is refused with a clear REFERENCE_MISMATCH explanation.

- [x] Relevant
- [ ] Not relevant. Why:

## G07 (openai primary): How did job vacancies in IT and other information services change compared with the wider ICT sector, 2020 to 2024?

Covers: subsector kept distinct from its parent. Status: completed.
Analysis id: e4333696-56aa-4fb5-b236-69c422138b58
Plan: Assess how job vacancies in IT & Other Information Services changed relative to the wider Information & Communications sector in Singapore from 2020 to 2024. (sectors ['it_info_services', 'info_comms'], metrics ['job_vacancies'], 2020-2024).
Summary: Job vacancies in IT and other information services rose more than vacancies in the wider information and communications sector over the period covered. The IT and other information services group also showed a slightly stronger upward trend, although the wider sector still had more vacancies at the end of the period.

Findings:

- Job vacancies in IT & Other Information Services rose by 1,100 vacancies between 2020-Q1 and 2024-Q4.
- By comparison, job vacancies in Information & Communications rose by 1,000 vacancies between 2020-Q1 and 2024-Q4.
- Over the same period, job vacancies in IT & Other Information Services rose by 27.5% between 2020-Q1 and 2024-Q4 and job vacancies in Information & Communications rose by 21.7% between 2020-Q1 and 2024-Q4.
- In addition, job vacancies in IT & Other Information Services trended upward by about 179 vacancies a year between 2020-Q1 and 2024-Q4.
- Meanwhile, job vacancies in Information & Communications trended upward by about 161 vacancies a year between 2020-Q1 and 2024-Q4.
- Separately, job vacancies in IT & Other Information Services was 5,100 vacancies in 2024-Q4 and job vacancies in Information & Communications was 5,600 vacancies in 2024-Q4.

Limitations:

- M184071: using snapshot retrieved 2026-10-25
- The findings compare broad sector groupings and do not show differences within occupations or firms.
- The findings describe changes over time but do not explain why vacancies changed.
- The comparison uses the start and end points provided, which may hide short-term rises and falls.
- The wider sector includes IT and other information services, so the two groups are not fully separate.

Proposed verdict: **Relevant**: subsector and parent compared on change, percentage, trend and latest level.

- [x] Relevant
- [ ] Not relevant. Why:

## G08 (openai primary): How is the sector doing?

Covers: ambiguous question. Status: awaiting_input.
Analysis id: 1b3b20ab-aef3-4084-a29f-8ee106ad33e8
Asked: Which sector and labour-market indicator should we assess? Options: ['Information & Communications employment level', 'Information & Communications job vacancies', 'Manufacturing employment change', 'All industries recruitment rate']

Findings:

- none

Limitations:

- none

Proposed verdict: **Relevant**: asks which sector and measure, with four concrete options including ICT.

- [x] Relevant
- [ ] Not relevant. Why:

## G09 (openai primary): Analyse employment in information and communications from 1985 to 1990

Covers: period outside the data's coverage. Status: completed_with_limitations.
Analysis id: 3bb3599b-a4e2-43c7-92e9-dddc315ebd09
Plan: Analyse employment levels in Singapore's Information & Communications industry from 1985 to 1990. (sectors ['info_comms'], metrics ['employment_level'], 1985-1990).
Summary: No verified findings were provided for employment in information and communications. As a result, this narrative cannot describe changes, levels, or patterns for the period requested.

Findings:

- none

Limitations:

- No verified finding covers employment level in Information & Communications: M182841 has it only for 2008 to 2025, not for all of 1985 to 1990.
- No verified evidence was supplied.
- The requested time period cannot be assessed from the provided material.
- No comparisons or trends can be reported.

Proposed verdict: **Relevant**: no findings, and the limitation says why: M182841 has the series only for 2008 to 2025.

- [x] Relevant
- [ ] Not relevant. Why:

## G10 (openai primary): What happened to HDB resale flat prices in 2024?

Covers: out of domain. Status: completed_with_limitations.
Analysis id: 61843035-8b99-4460-aa1e-9c570a9d5042
Plan: The researcher wants to understand changes in HDB resale flat prices in 2024. (sectors [], metrics [], 2024-2024).

Findings:

- none

Limitations:

- HDB resale flat prices are housing-market data, not Singapore labour-market data by industry.

Proposed verdict: **Relevant**: correctly declined as outside labour-market data, with no findings.

- [x] Relevant
- [ ] Not relevant. Why:

## G11 (openai primary): How has employment in Singapore's infocomm sector developed between 2020 and 2024?

Covers: paraphrase of G01. Status: completed.
Analysis id: 1d7857f4-747d-4ee1-b66c-bdf5fdce5642
Plan: Assess how employment levels in Singapore's Information & Communications sector changed over 2020 to 2024. (sectors ['info_comms'], metrics ['employment_level'], 2020-2024).
Summary: Employment in Singapore’s infocomm sector grew overall across the period reviewed, ending higher than it began. The pattern was uneven, with a strong early increase followed by a later decline before the sector remained above its starting level.

Findings:

- Employment level in Information & Communications was 157.6 thousand persons in 2020 and employment level in Information & Communications was 180.3 thousand persons in 2024.
- Employment level in Information & Communications rose by 22.7 thousand persons between 2020 and 2024.
- In addition, employment level in Information & Communications rose by 15.3 thousand persons between 2020 and 2021.
- Meanwhile, employment level in Information & Communications fell by 5.9 thousand persons between 2022 and 2023.
- Separately, employment level in Information & Communications was 172.9 thousand persons in 2021.

Limitations:

- M182841: using snapshot retrieved 2026-10-25
- Only employment levels are covered, not wages, vacancies, or job quality.
- The findings do not explain why employment changed.
- The sector label may not capture infocomm roles located in other industries.

Proposed verdict: **Relevant**: levels, the overall rise, the early gain and the 2022-2023 fall.

- [x] Relevant
- [ ] Not relevant. Why:

## G12 (openai primary): Quarter by quarter from 2020 to 2024, did more ICT job openings go with stronger ICT hiring?

Covers: paraphrase of G05. Status: completed_with_limitations.
Analysis id: 10749a7f-2dbb-4845-971a-f0a91b825de8
Plan: Assess whether higher ICT job openings were associated with stronger ICT hiring in Singapore quarter by quarter from 2020 to 2024. (sectors ['info_comms'], metrics ['job_vacancies', 'recruitment_rate'], 2020-2024).
Summary: ICT job openings rose across the full period and were higher on average in the latest set of quarters than at the start. However, openings fell in the latest year-end comparison, and the findings do not include hiring figures, so they do not show whether stronger openings went with stronger hiring.

Findings:

- Job vacancies in Information & Communications rose by 1,000 vacancies between 2020-Q1 and 2024-Q4.
- Overall, job vacancies in Information & Communications was 5,600 vacancies in 2024-Q4.
- In addition, job vacancies in Information & Communications trended upward by about 161 vacancies a year between 2020-Q1 and 2024-Q4.
- Overall, job vacancies in Information & Communications averaged 1,725 vacancies more in 2024-Q1 to 2024-Q4 than in 2020-Q1 to 2020-Q4.
- Meanwhile, job vacancies in Information & Communications fell by 700 vacancies between 2023-Q4 and 2024-Q4.

Limitations:

- No verified finding covers recruitment rate in Information & Communications: no dataset fetched for this analysis has such a series.
- M184071: using snapshot retrieved 2026-10-25
- The findings cover job openings but not ICT hiring.
- They do not show a quarter-by-quarter link between openings and hiring.
- The findings describe changes in openings only and do not explain why they changed.

Proposed verdict: **Not relevant**: reads 'hiring' as the recruitment rate, finds no ICT series for it, and reports vacancies only; it says it cannot answer.

- [ ] Relevant
- [x] Not relevant. Why:
