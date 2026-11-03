# Customer PoC: local inference reliability baseline

## 1. Customer problem and assumptions

A fictional internal assistant works for single users but has no characterized
concurrency envelope. The customer needs evidence before adding traffic or buying
GPU capacity. This PoC evaluates local inference only; no availability SLO, production
traffic distribution, concurrency target or acceptable error budget has been agreed.

Assume short English prompts and approximately 116 output tokens in the measured
workload. This assumption is intentionally narrow and must be replaced by representative
customer input/output distributions before sizing a deployment.

## 2. Requirements and hypotheses

Requirements: reproducible Cold/Warm measurement, bounded concurrency 1/2/4, 12 requests
per run, three repeats, no retries, request-level errors/status/body preservation, unit
tests, environment provenance and reanalysis without live inference.

Hypotheses (not guarantees):

- Model residency reduces load overhead and can reduce overall latency.
- More outstanding requests may stop improving aggregate throughput before latency
  becomes acceptable for users.
- Short successful runs can hide overload or rare failures; zero observed errors is
  insufficient to choose an error budget.

## 3. Test environment

- Actual host: Apple M1 Pro, 16 GiB RAM, macOS 27.0.1 arm64; Python 3.15.2.
- Ollama API version: 0.40.13, local HTTP endpoint `127.0.0.1:11434`.
- Model: `llama3.2:1b`, 1.2B, Q8_0; digest
  `baf6a787fdffd633537aa2eb51cfd54cb93ff08e28040095462bb63daf552878`.
- Model initially not resident. Requested context length: 4096, output cap: 128,
  temperature: 0, seed: 42, keep-alive: 10m, non-streaming.
- Effective `OLLAMA_NUM_PARALLEL`: **unknown**, not inferred from client workers.
- Background applications, power mode and thermal state: not controlled.
- No NVIDIA GPU/DCGM, Kubernetes, gateway, or AWS resources used.
- Source provenance: base commit `2d53a1c40299247c1ee3af84c29cacdbd28d7cab`
  with local uncommitted benchmark additions; executed source hashes are recorded in
  each environment file. A base commit alone does not identify these new scripts.

## 4. Methodology

Three model-residency Cold/Warm pairs, each with explicit unload, residency check,
cold measurement, excluded warmup and warm measurement. Unloading does not clear OS caches.

Nine fixed-batch concurrency runs, 12 requests each, with a warmup before each run
and rotating order across repeats. Client latency covers the HTTP exchange; server
load/prompt/generation metrics retain their own boundaries. P50/P95 are descriptive
successful-request percentiles. Failures count against throughput and error rate.
See [full methodology](methodology.md) and [execution guide](../README.md).

## 5. Verified results

**Live integration executed on 2026-11-03 UTC.** Both new executables exited successfully.
Cold/Warm: 3 measured cold responses, 3 measured warm responses, with successful
unload/priming checks. Concurrency: 108/108 measured successes, no observed timeouts
or HTTP/response-validation failures. These are observations, not injected test data.
Automated validation: 18 standard-library tests passed via `make check`; mock failures
exercise error paths that the real run did not encounter.

| Concurrency | Attempted/successful | P50 ms | P95 ms | RPS | Output tokens/s | Error rate |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 36/36 | 1936.18 | 2216.91 | 0.507 | 58.85 | 0.0% |
| 2 | 36/36 | 3951.35 | 6086.90 | 0.459 | 53.19 | 0.0% |
| 4 | 36/36 | 8198.27 | 11285.11 | 0.422 | 48.95 | 0.0% |

Cold client latency ranged from 2680.23 to 3869.25 ms; measured warm latency from
1910.25 to 2043.13 ms. Warm model-load time was 1.29–1.56 ms, versus 836.76–1917.70 ms
for cold samples. Full per-run timing and evidence links are in [analysis](analysis.md).
Historical supplied numbers and pre-existing local artifacts are clearly separate there.

## 6. Potential bottlenecks

Increasing client concurrency increased response latency and did not improve aggregate
throughput in these runs. Possible contributors include scheduling/serialization,
compute or memory-bandwidth contention, thermal/power effects and background activity.
This experiment cannot distinguish them. Server queue evidence, effective parallelism
and resource utilization are missing; a high P95 alone does not prove queuing.

Model loading contributes substantially to cold startup. Keeping a model resident may
improve readiness latency but costs memory and cannot by itself increase generation
capacity. Reused prompts/cache hits bias this short workload toward warm prompt behavior.

## 7. Limitations and confidence

High confidence in calculation reproducibility for these saved samples: reanalysis
matches all nine summaries. Low confidence in generalization to production tail latency,
maximum sustainable RPS, rare failures, long prompts or streaming experience.

No fixed arrival rate, soak test, representative traffic mix, server tracing or SLO was
used. Twelve requests per configuration per repeat are insufficient for reliable P95
estimation. A desktop is not a controlled performance host. This is not evidence of a
regression against historical runs with undocumented environmental controls.

## 8. Recommended improvements

1. Agree on a P95 target, deadline, failure budget and representative input/output mix.
2. Before expanding concurrency, measure sustained fixed-rate traffic and admission
   behavior. Use a cautious low-concurrency baseline for the next PoC, not a universal
   production worker limit.
3. Add gateway deadline/error/health behavior, then compare overhead and overload
   handling with this direct-inference baseline. A timed-out HTTP call may leave
   generation running; investigate cancellation rather than blindly retrying.
4. Monitor successful RPS, output tokens/s, client latency, timeouts/HTTP errors,
   model-load and prompt/generation times, prompt/cache counts, memory and readiness.
   Add queue/admission telemetry only where the backend can actually expose it.
5. Evaluate GPU deployment only after identifying the limiting resource, agreeing on
   cost/token and cost/request, and controlling model quantization/context differences.
   NVIDIA GPU telemetry must be validated on that GPU environment.

## 9. Next experiment

Repeat with a larger sample and longer duration using a varied prompt corpus and
separate output-length buckets. Capture verified server startup parallelism settings,
logs, power/thermal observations and memory usage. Then introduce a fixed-arrival-rate
load generator to locate the point where a chosen SLO or error budget is violated.

The next software milestone is the inference gateway/router. Kubernetes, observability,
vLLM, KServe/llm-d, KEDA and budget-controlled AWS experiments remain sequenced future
work. Cloud provisioning, production readiness and maximum sustainable capacity are
**Pending validation**, not claimed by this PoC.
