# Load run

Generated 2026-10-27T18:20:31+00:00 on macOS-26.6.2-arm64-arm-64bit (8 CPUs), against the stack in offline mode (deterministic LLM stand-in, snapshot data).

Workload: 300 s; 10 analysis slots resubmitting continuously; 50 WebSocket listeners; 20 reads a second.

| Target | Result |
|---|---|
| zero lost terminal results | met |
| zero correctness failures | met |
| post ack p95 < 300 ms | met |
| read p95 < 300 ms | met |
| event delivery p95 < 1000 ms | met |

| Measure | p50 | p95 |
|---|---|---|
| POST acknowledgement (ms) | 74.1 | 127.7 |
| Read, history or detail (ms) | 26.3 | 73.5 |
| Event delivery, commit to client (ms) | 28.6 | 92.8 |
| Queue wait, submission to start (ms) | 2599.0 | 3557.7 |

- Analyses submitted: 798 (159.6 a minute).
- Live events delivered: 315641; reads: 5518.
- Errors: 0 (rate 0.00%).
- Lost terminal results: 0; incorrect results: 0.
