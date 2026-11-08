# Architecture and scope decisions

## Current system boundary

The local deployment has two processes: an aiohttp gateway on port 8080 and
Ollama on port 11434. Ollama runs the installed model; the gateway validates and
forwards non-streaming requests, controls admission, bounds upstream waiting, and
maps failures to HTTP errors. The original standard-library benchmark can still
call Ollama directly, bypassing gateway controls.

| Module | Responsibility |
|---|---|
| `gateway/__main__.py` | Parse CLI configuration, configure logging, start the HTTP server |
| `gateway/server.py`: `create_app` | Register routes/middleware and manage one shared HTTP client session |
| `Gateway.generate` | Validate input, reserve a slot, forward generation, release the slot in `finally` |
| `Gateway.upstream` | Apply an upstream deadline, read a bounded response, validate JSON, map failures |
| `Gateway.diagnostic` | Query model metadata and implement the readiness check |
| Audit middleware | Attach request IDs and log route, status and duration without prompts or generated text |
| `tests/test_gateway.py` | Use a controlled HTTP upstream and injected failures to verify gateway behavior |

```mermaid
sequenceDiagram
    participant C as Client
    participant G as Gateway :8080
    participant O as Ollama :11434
    C->>G: POST /api/generate
    alt Admission limit reached
        G-->>C: 429 capacity_exceeded
    else Slot available
        G->>G: active += 1
        G->>O: Forward generation request
        alt Valid completed response
            O-->>G: Generated response
            G->>G: Release slot in finally
            G-->>C: 200 + response + X-Request-ID
        else Connection failure / timeout / invalid response
            G->>G: Map error; release slot in finally
            G-->>C: 503 / 504 / 502 + request ID
        end
    end
```

The deadline covers the upstream operation, not the complete client upload and
response delivery. A timeout closes the gateway's wait but does not prove that
backend computation stopped. Admission is per gateway process; direct backend
requests and other gateway processes do not share this counter.

### Health and readiness contract

| Route | What it checks | What success does not prove |
|---|---|---|
| `/healthz` | Gateway can respond to HTTP | Ollama is available |
| `/readyz` | Ollama `/api/tags` responds and the configured model is installed | Model is warm, spare admission capacity exists, or generation will succeed |

The readiness probe does not run inference. This avoids generating tokens on each
probe, at the cost of a weaker readiness guarantee. Connection failure currently
maps to 503 and a probe deadline to 504. A missing configured model maps to 503.

No Kubernetes workload, metrics backend, autoscaler, or cloud GPU is deployed.
Current experiments do not measure TTFT, inter-token latency, GPU utilization,
or server queue length. The gateway is a local learning implementation, without
an authentication or TLS layer; it binds to loopback by default.

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
  work. The gateway also disables retries. Future retry eligibility must consider
  cancellation behavior and the cost of duplicate generation.

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
