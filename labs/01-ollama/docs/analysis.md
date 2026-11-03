# Experiment analysis

## Evidence classes

1. **User-reported baseline:** supplied before this implementation; no original raw
   response tied to those exact numbers was supplied. It is not a new reproduction.
2. **Inherited local artifacts:** found uncommitted on inspection, retained unchanged.
   They include different Cold/Warm raw responses and a one-pass concurrency summary.
3. **Executed and verified in this milestone:** the dated runs below, with raw request
   records, environment and source hashes. These are real local HTTP observations.

## Historical user-reported baseline

| Metric | Cold | Warm |
|---|---:|---:|
| API total latency (ms) | 2784.809166 | 1184.395584 |
| Model load (ms) | 1583.693666 | 1.609875 |
| Output tokens | 116 | 116 |
| Generation tokens/s | 102.070536 | 99.409116 |

Warm API total latency was approximately 57.5% lower. Load accounted for approximately
56.9% of cold API total time. Generation throughput was similar in this pair.
These numbers alone cannot establish a stable improvement or a production baseline.

## Inherited local artifacts (not rerun by the legacy scripts)

`results/cold.json` and `results/warm.json` have response timestamps on 2026-11-01.
They report API total time 1967.587959 / 1123.718125 ms and load time
819.455750 / 1.448 ms respectively, each with 116 output tokens.
They are **not** the same measurements as the user-reported table above.

`results/concurrency.json` contains one summary per concurrency level:

| Client concurrency | Successes/attempts | P50 ms | P95 ms | RPS | Output tokens/s |
|---|---:|---:|---:|---:|---:|
| 1 | 12/12 | 1115.84 | 1166.52 | 0.89 | 102.79 |
| 2 | 12/12 | 2260.91 | 2320.27 | 0.88 | 102.23 |
| 4 | 12/12 | 4734.50 | 5047.37 | 0.82 | 94.93 |

There are no corresponding raw per-request samples, complete run durations or environment
snapshots for that concurrency artifact. Do not pool it with the new results or call
its provenance independently verified. `results/results.txt` is model output only.

## Newly executed Cold/Warm pairs

Date: 2026-11-03 UTC. Evidence: [Cold/Warm run](../results/verified/20261103T142251Z-cold-warm-81dba1ca/summary.json),
[raw requests](../results/verified/20261103T142251Z-cold-warm-81dba1ca/requests.jsonl).

| Repeat | Phase | Client ms | API total ms | Load ms | Prompt eval ms | Generation ms | Tokens | Generation tokens/s |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | cold | 3869.25 | 3863.52 | 1917.70 | 77.19 | 1857.70 | 116 | 62.44 |
| 1 | warm | 1910.25 | 1906.83 | 1.36 | 17.92 | 1881.04 | 116 | 61.67 |
| 2 | cold | 2680.23 | 2675.91 | 836.76 | 160.62 | 1637.86 | 116 | 70.82 |
| 2 | warm | 1945.42 | 1942.68 | 1.29 | 14.79 | 1918.46 | 116 | 60.47 |
| 3 | cold | 2775.36 | 2770.77 | 1095.82 | 67.80 | 1593.94 | 116 | 72.78 |
| 3 | warm | 2043.13 | 2038.98 | 1.56 | 15.61 | 2018.01 | 116 | 57.48 |

All three cold samples followed a successful unload and an empty selected-model residency
check; warm samples followed explicit priming. Warm load time is much smaller. However,
warm generation speed is lower than cold generation speed in these pairs, demonstrating
that total-latency improvement and token-generation performance are distinct. OS caches,
background load and thermal conditions were not controlled. Do not compare these observations
with the historical numbers as a software performance regression: the environment and
explicit context-length controls of the earlier observations are not established.

## Newly executed concurrency runs

Evidence: [environment](../results/verified/20261103T142313Z-concurrency-942cd37d/environment.json),
[raw requests](../results/verified/20261103T142313Z-concurrency-942cd37d/requests.jsonl),
[per-run summary](../results/verified/20261103T142313Z-concurrency-942cd37d/summary.json),
[recomputed analysis](../results/verified/20261103T142313Z-concurrency-942cd37d/analysis.json).

| Concurrency | Repeat | Attempted/successful | P50 ms | P95 ms | RPS | Output tokens/s | Error rate | Run seconds |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 12/12 | 1941.90 | 2407.91 | 0.493 | 57.20 | 0.0% | 24.336 |
| 1 | 2 | 12/12 | 1869.70 | 1961.74 | 0.530 | 61.51 | 0.0% | 22.632 |
| 1 | 3 | 12/12 | 2003.75 | 2143.41 | 0.500 | 58.03 | 0.0% | 23.987 |
| 2 | 1 | 12/12 | 3891.67 | 7123.64 | 0.431 | 49.97 | 0.0% | 27.856 |
| 2 | 2 | 12/12 | 4096.41 | 5732.42 | 0.442 | 51.28 | 0.0% | 27.145 |
| 2 | 3 | 12/12 | 3924.47 | 4071.62 | 0.511 | 59.22 | 0.0% | 23.505 |
| 4 | 1 | 12/12 | 10625.56 | 11431.98 | 0.365 | 42.37 | 0.0% | 32.854 |
| 4 | 2 | 12/12 | 8176.14 | 8805.92 | 0.475 | 55.09 | 0.0% | 25.269 |
| 4 | 3 | 12/12 | 8039.97 | 9896.15 | 0.441 | 51.19 | 0.0% | 27.191 |

### Pooled descriptive statistics

Each row pools 36 successful samples across three runs. Percentiles are recomputed
from samples. RPS and aggregate token throughput use the sum of measured run durations,
not the complete session time including warmups and metadata calls.

| Concurrency | Attempted/successful | P50 ms | P95 ms | RPS | Output tokens/s | Error rate |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 36/36 | 1936.18 | 2216.91 | 0.507 | 58.85 | 0.0% |
| 2 | 36/36 | 3951.35 | 6086.90 | 0.459 | 53.19 | 0.0% |
| 4 | 36/36 | 8198.27 | 11285.11 | 0.422 | 48.95 | 0.0% |

All 108 measured requests completed successfully. Output counts were [116]; the
observed `prompt_eval_cached_count` values were [33]. The workload strongly
reuses the prompt, so it is not representative of a customer with diverse histories.

The highest pooled observed RPS is at concurrency 1. Higher concurrency increased
latency without a throughput gain in this experiment. This is consistent with a
capacity/contention bottleneck, but does **not** prove server queuing or identify
internal parallelism. No server scheduling trace or queue metric was collected.

**Maximum sustainable throughput remains unestablished.** These are short closed-loop
batches, not a fixed-arrival-rate soak test with a customer-defined latency/error SLO.
Twelve samples per run are inadequate for reliable tail estimates; 36 pooled samples
are still small and correlated. No confidence interval or production error bound is claimed.

## Reproduce the calculations

```bash
python3 labs/01-ollama/analyze.py labs/01-ollama/results/verified/20261103T142313Z-concurrency-942cd37d
```

This validates request counts and saved summaries before recomputing descriptive values.
Durations are client-measured monotonic intervals, retained in the summary. Raw API
nanoseconds and client milliseconds remain separate. See [methodology](methodology.md)
for definitions and [PoC report](poc-report.md) for proposed customer actions.
