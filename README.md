# AI Inference Reliability Platform

A customer-oriented inference engineering project: turn serving requirements into
measured capacity, explain failures, and validate improvements with repeatable experiments.
The focus is inference behavior and operational evidence, building on existing DevOps,
Kubernetes, CI/CD, AWS, and on-premises experience.

## Customer engagement

A fictional internal AI assistant serves single requests successfully. Before adding users,
the customer needs a latency/throughput baseline, visible failures, and a defensible scaling
plan. No production SLO or target arrival rate has been supplied; experiments characterize
the system rather than declare it production-ready.

## Current implementation

**Milestone 1: reproducible Ollama baseline and bounded concurrency experiment.**

- Local HTTP inference on Apple Silicon; no CUDA assumptions or cloud resources.
- Explicit model-residency Cold/Warm pairs; fixed prompt and generation options.
- Concurrency 1/2/4, 12 requests per run, three repetitions, retries disabled.
- Request-level evidence, server timing fields, version/model/environment snapshots,
  per-run statistics, offline reanalysis, and standard-library automated tests.
- [Experiment guide](labs/01-ollama/README.md), [methodology](labs/01-ollama/docs/methodology.md),
  [analysis](labs/01-ollama/docs/analysis.md), and [customer PoC report](labs/01-ollama/docs/poc-report.md).

**Milestone 2 is in progress:** [gateway design and engineering insights](labs/02-gateway/README.md).
The gateway draft has not yet passed integration validation.

Current verified data path:

```text
Python load generator -> localhost:11434/api/generate -> Ollama / local model
         |                                                   |
         +---- raw responses, HTTP outcomes and timing ------+
                                   |
                            JSON / offline analysis
```

## Quick start

Python 3.10+ and a running Ollama installation with `llama3.2:1b` are required for live runs.
Tests require only Python and do not connect to a model. No Python packages need installing.

```bash
# Start Ollama using its desktop app (or ollama serve if no server is running).
ollama list
# If the model is absent, explicitly download it before the experiment:
ollama pull llama3.2:1b
make check
python3 labs/01-ollama/cold_warm.py
python3 labs/01-ollama/concurrency.py
# Substitute the run directory printed by the concurrency command:
python3 labs/01-ollama/analyze.py labs/01-ollama/results/runs/<run-directory>
```

Each invocation creates a new directory; it never replaces an earlier result. Cold
measurements unload the selected model: run on an idle, dedicated local server.
See the experiment guide for flags, output fields, failure handling, and code decisions.

## Target architecture and milestones

The following is a **long-term target, not the current implementation**:

```text
Client / Load Generator
         |
API Gateway / Inference Router
         |
         +-- Local inference: Ollama / Apple Silicon
         +-- Cloud inference: vLLM / NVIDIA GPU
                     |
            Kubernetes platform
                     |
       Prometheus / Grafana / GPU DCGM*
                     |
    Performance evaluation / RCA / runbooks / PoC
```

*DCGM applies only to a verified NVIDIA environment, not Apple Silicon.* Local Ollama
may stay on the host while suitable gateway components run in kind; this is not a
claim that a kind container has access to Metal acceleration.

| Milestone | Entry condition / intended evidence | Status |
|---|---|---|
| 1. Ollama baseline | Repeated raw measurements and reproducible analysis | Implemented; see PoC for executed results and limitations |
| 2. Gateway/router | Timeout contract, upstream health, error mapping; compare against direct baseline | Planned |
| 3. Local Kubernetes | Deploy suitable components; verify networking and readiness | Planned |
| 4. Observability | Define latency/error/throughput SLIs, then Prometheus/Grafana | Planned |
| 5. Controlled vLLM experiment | NVIDIA hardware, equivalent workload and explicit cost envelope | Planned |
| 6. KServe / llm-d evaluation | Concrete orchestration, routing or distributed-serving requirement | Planned |
| 7. KEDA experiment | Verified scaling signal and load-driven policy | Planned |
| 8. AWS GPU extension | Explicit budget approval, maximum spend and cleanup plan | Not provisioned |
| 9. Fault injection | Reproducible failure, RCA and recovery runbook | Planned |

See [architecture decisions](docs/architecture.md). Technologies are introduced when
measurements justify them, rather than as disconnected demonstrations.
