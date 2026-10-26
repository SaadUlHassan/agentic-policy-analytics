# Deterministic evaluation

Generated 2026-10-26T22:30:38+00:00 from snapshots captured 2026-10-25T16:31:21+00:00.

| Gate | Result |
|---|---|
| expectations current | pass |
| computation accuracy | pass |
| refusal correctness | pass |
| adversarial recall | pass |
| adversarial false positives | pass |

**Computation accuracy:** 32/32 result fields within tolerance and in the expected unit and scale, across 12 golden computations.

**Refusal correctness:** 4/4 (R01 REFERENCE_MISMATCH, R02 INSUFFICIENT_PAIRS, R03 NOT_A_LEVEL, R04 NOT_A_LEVEL).

**Adversarial verifier suite:** 44 corrupted claims, recall 100%, precision 100%; 25 valid controls, false-positive rate 0%.

A case counts as detected only when the rule it breaks rejected it.

| Category | Rule that must reject it | Detected | Checks that fired |
|---|---|---|---|
| association from descriptive | kind_allowed | 2/2 | kind_allowed |
| association strength | strength_rule | 2/2 | strength_rule |
| causal hedged | no_causal_language | 2/2 | no_causal_language, safe_prose |
| causal unhedged | no_causal_language | 2/2 | no_causal_language, safe_prose |
| fabricated literal | no_free_numbers | 3/3 | no_free_numbers, safe_prose |
| level as change | predicate_fit | 3/3 | predicate_fit |
| longer interval | interval_equality | 3/3 | interval_equality |
| narrative causal | no_causal_language | 2/2 | no_causal_language |
| narrative fabricated number | no_free_numbers | 2/2 | no_free_numbers |
| parent child swap | identity_equality | 2/2 | identity_equality |
| recommendation with figures | recommendation_has_no_figures | 1/1 | kind_allowed, recommendation_has_no_figures |
| shorter interval | interval_equality | 3/3 | interval_equality |
| tampered lineage | identity_equality | 2/2 | identity_equality |
| wrong computation ref | resolution | 3/3 | resolution |
| wrong direction | sign_rule | 5/5 | sign_rule |
| wrong metric | metric_equality | 3/3 | metric_equality |
| wrong unit or field | predicate_fit | 4/4 | predicate_fit |
