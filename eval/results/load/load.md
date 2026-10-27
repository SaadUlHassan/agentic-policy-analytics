# Load run

Generated 2026-10-27T21:13:03+00:00 on macOS-26.6.2-arm64-arm-64bit (8 CPUs), against the stack in offline mode (deterministic LLM stand-in, snapshot data).

Workload: 300 s; 10 analysis slots resubmitting continuously; 50 WebSocket listeners; 20 reads a second.

| Target | Result |
|---|---|
| analyses checked | met |
| zero lost terminal results | met |
| zero correctness failures | met |
| post ack p95 < 300 ms | met |
| read p95 < 300 ms | met |
| event delivery p95 < 1000 ms | met |

| Measure | p50 | p95 |
|---|---|---|
| POST acknowledgement (ms) | 80.5 | 139.5 |
| Read, history or detail (ms) | 31.5 | 99.2 |
| Event delivery, commit to client (ms) | 29.0 | 99.4 |
| Queue wait, submission to start (ms) | 2647.8 | 3576.4 |

- Analyses submitted: 782 (156.4 a minute).
- Live events delivered: 306411; reads: 5999.
- Errors: 0 (rate 0.00%).
- Lost terminal results: 0; incorrect results: 0.
