# Deterministic evaluation

Generated 2026-10-26T21:39:26+00:00 from snapshots captured 2026-10-25T16:31:21+00:00.

| Gate | Result |
|---|---|
| expectations current | pass |
| computation accuracy | pass |
| refusal correctness | pass |
| adversarial recall | pass |
| adversarial false positives | pass |

**Computation accuracy:** 30/30 result fields within tolerance across 12 golden computations.

**Refusal correctness:** 4/4 (R01 REFERENCE_MISMATCH, R02 INSUFFICIENT_PAIRS, R03 NOT_A_LEVEL, R04 NOT_A_LEVEL).

**Adversarial verifier suite:** 44 corrupted claims, recall 100%, precision 100%; 25 valid controls, false-positive rate 0%.

| Category | Detected | Checks that fired |
|---|---|---|
| association from descriptive | 2/2 | kind_allowed |
| association strength | 2/2 | strength_rule |
| causal hedged | 2/2 | no_causal_language, safe_prose |
| causal unhedged | 2/2 | no_causal_language, safe_prose |
| fabricated literal | 3/3 | no_free_numbers, safe_prose |
| level as change | 3/3 | predicate_fit |
| longer interval | 3/3 | interval_equality |
| narrative causal | 2/2 | no_causal_language |
| narrative fabricated number | 2/2 | no_free_numbers |
| parent child swap | 2/2 | identity_equality |
| recommendation with figures | 1/1 | kind_allowed, recommendation_has_no_figures |
| shorter interval | 3/3 | interval_equality |
| tampered lineage | 2/2 | identity_equality |
| wrong computation ref | 3/3 | resolution |
| wrong direction | 5/5 | sign_rule |
| wrong metric | 3/3 | metric_equality |
| wrong unit or field | 4/4 | predicate_fit |
