# Architecture and scope decisions

## Current system boundary

A Python standard-library client sends non-streaming requests directly to a local
Ollama process. It records transport outcomes and Ollama's own timing counters.
There is no gateway, Kubernetes workload, metrics backend, autoscaler or GPU cloud
resource in this milestone. It does not measure TTFT (time to first token), streaming
inter-token latency, GPU utilization, server queue length or user-perceived application latency.

## Decisions

- **Keep the backend local.** The installed Apple Silicon model enables a low-cost
  baseline. Reproduce on NVIDIA before making vLLM/GPU claims.
- **One small measurement library, two experiments.** Transport, validation, metrics
  and provenance are shared. Model unload is isolated from the concurrency runner;
  a concurrent run never intentionally unloads a model.
- **Fixed-batch closed-loop concurrency.** Bound worker count without a new load
  testing framework. It answers how a fixed batch behaves as outstanding work rises.
  It cannot establish sustainable arrival-rate capacity or expose all overload modes.
- **Evidence before infrastructure.** Immutable per-invocation directories and raw
  bodies support independent reanalysis. Tests simulate failures; fabricated responses
  stay in tests and never become measured PoC results.
- **No retry policy in the baseline.** Retries hide upstream failures and multiply
  work. A later gateway should evaluate bounded deadlines and retry eligibility
  against this baseline, considering cancellation and duplicate generation cost.

## Next design gate

First agree with the customer on prompt/output distributions, concurrency versus
arrival rate, P95 target, timeout, acceptable error rate, and cost per successful request.
Then compare direct inference with a small gateway under the same workload. Measure
warmup/readiness behavior and overload handling before deploying suitable components
on kind. Instrument client HTTP duration, server generation/load durations, tokens,
errors and admission outcomes; do not infer a queue length from latency alone.

Only after a costed GPU experiment should NVIDIA telemetry, vLLM batching, KServe,
llm-d or KEDA become implementation requirements. Keep local and GPU results labeled
with their hardware, model digest, quantization, runtime and workload differences.
