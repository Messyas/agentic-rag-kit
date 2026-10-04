# Local evaluation

Split: dev. Warmups excluded from measurements.

| Arm | Cases | Failures | Outcome accuracy | Mean latency (s) | p95 (s) |
|---|---:|---:|---:|---:|---:|
| rule_baseline | 24 | 0 | 1.000 | 0.001 | 0.003 |
| simple_rag | 24 | 0 | 0.750 | 1.034 | 4.360 |
| corrective_rag | 24 | 0 | 0.750 | 1.511 | 5.427 |
| react_agent_native | 24 | 0 | 0.750 | 16.292 | 45.052 |
| react_agent_structured_json | 24 | 0 | 0.750 | 2.118 | 5.320 |

See outputs.jsonl for per-case outputs and errors; metrics.json includes confidence intervals.
This report measures this dataset and configuration only. A small synthetic dataset does not establish production targets.
