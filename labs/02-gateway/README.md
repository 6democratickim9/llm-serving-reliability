# Milestone 2: Local inference gateway

Status: local forwarding, failure handling, admission/recovery, health/readiness,
and response/log correlation have automated coverage. The full suite contains
18 benchmark tests and 13 gateway tests. Manual local observations are recorded
separately below; they are not controlled performance comparisons.

## Customer problem

The baseline measures how inference behaves under concurrent traffic. The next
question is how clients should experience an unavailable or slow inference server.
A gateway provides an explicit failure contract before adding deployment complexity.

## First daily deliverable

Implement non-streaming request forwarding, an upstream deadline, and structured
errors; validate normal responses, connection failure, timeout, and malformed
upstream responses with automated tests and a real Ollama smoke test. Finish with
execution instructions and reviewed changes before committing. Admission control
and health checks belong to subsequent daily deliverables; their presence in a
draft is not evidence of completion.

## Request flow and failure contract

```text
Client request
  -> Gateway receives and validates the request
  -> Gateway forwards it to Ollama
  -> Gateway reads the complete response within the upstream deadline
  -> Gateway returns the response to the client
```

The first iteration uses `stream: false`. This keeps the response contract simple:
the gateway can validate completion before returning success. Streaming requires
separate handling for errors after headers or partial tokens have already reached
the client, and is outside this daily deliverable.

| Condition | Intended gateway response | Engineering reason |
|---|---|---|
| Connection failure / upstream unavailable | 503 | The gateway cannot currently serve inference through its dependency. |
| Upstream deadline exceeded | 504 | Waiting for the dependency exceeded the configured time budget. |
| Malformed or incomplete upstream response | 502 | The dependency returned a response the gateway cannot accept as a completed generation. |

These mappings are this project's API contract, not a claim that every gateway
must classify failures identically. Other upstream HTTP statuses need explicit
mapping and tests rather than being blindly returned as successful responses.

## Engineering insights

### Bound the complete upstream wait

A connection timeout alone does not bound generation time: Ollama may accept the
connection and then take a long time to produce output. The upstream deadline
should cover acquiring a connection, sending the request, and reading the complete
response. It does not by itself bound client upload or downstream delivery time.
An async HTTP client permits waiting without blocking the server's event loop;
it does not increase Ollama's internal model execution parallelism.

Returning 504 bounds the gateway's wait, but does not prove that Ollama stopped
computing. Cancellation propagation and backend recovery require separate evidence.
Automatic retries are disabled so an uncertain timeout does not silently duplicate
expensive inference work or hide the original failure.

### Separate serving success from answer quality

A completed API response can contain an incorrect answer. In a user-reported
manual call, the model described readiness probes as intrusion sensors. That is
not the Kubernetes concept: Kubernetes readiness indicates whether a workload is
ready to receive traffic. The prompt omitted the word Kubernetes; this is a
possible contributor, not a verified root cause. Explicit domain context improves
the experiment design but cannot guarantee factual correctness.

The gateway's transport and completion checks do not evaluate factual accuracy.
Serving reliability and answer quality need distinct evaluation criteria.

### Separate observations from controlled measurements

The same user-reported call returned `total_duration=2488014625` and
`load_duration=1966185917` nanoseconds: about 2.488 seconds overall and 1.966 seconds
loading, or approximately 79% of reported total time. Generation produced 33 tokens
in 0.448278 seconds, approximately 73.6 tokens/second. These are Ollama-reported
internal timings, not client end-to-end latency.

This was a single manually reported response, not an independently reproduced
benchmark or a controlled cold start: no explicit unload preceded the request.
It motivates investigating model residency, but does not establish a performance
regression or a general capacity limit.

## Day 1 validation

Manual checks performed by the project owner against the local gateway:

| Scenario | Observed result |
|---|---|
| Real Ollama generation | HTTP 200 with `done: true` |
| Upstream deadline configured to 0.01 seconds | HTTP 504, `upstream_timeout` |
| Upstream configured to an unavailable local port | HTTP 503, `upstream_unavailable` |

These checks establish basic integration behavior, not a performance benchmark.
The timeout response alone does not prove that backend generation stopped.

Four automated tests passed using a controlled upstream and injected connection
failure: request/response forwarding, timeout mapping, connection-failure mapping,
and invalid upstream JSON mapping. Synthetic responses are test fixtures, not
model-generated results or performance measurements.

### Fault injection must target the correct connection

The test client and gateway both use aiohttp. Initially, mocking all client
requests also broke the test-client-to-gateway connection, so the request never
reached the code under test. Restricting the injected failure to the upstream URL
allows the gateway to receive the request and exercise its error handling.

### Remaining validation

- Admission limits greater than one, cancellation behavior, and readiness probe timeout/malformed-response cases.
- Direct-versus-gateway performance comparison under an equivalent workload.


## Day 2: Admission control and recovery

### Objective

Limit concurrent upstream requests and reject excess traffic without queuing.
With `--max-inflight 1`, one request can await Ollama at a time per gateway
process. This is a concurrency limit, not a requests-per-second limit or an
Ollama parallelism setting. Direct requests to Ollama bypass this control.

### Manual observations

The project owner sent two concurrent requests through the local gateway:

| Request | HTTP status | Client-observed latency |
|---|---:|---:|
| A | 200 | 2964.5 ms |
| B | 429 | 30.8 ms |

The rejected request returned `capacity_exceeded` and `Retry-After: 1`.
A subsequent request returned HTTP 200 with `done: true`, demonstrating
successful admission after the earlier request completed.

These are individual observations, not latency guarantees or capacity estimates.
`Retry-After: 1` advises a retry delay; it does not reserve capacity or guarantee
acceptance after one second.

### Automated validation

Seven gateway tests passed. The three tests added on Day 2 verify:

- An overlapping request receives 429 and never reaches the upstream server;
  a new request succeeds after the accepted request completes.
- A request that times out releases its gateway slot.
- An upstream connection failure releases its gateway slot.

The overlap test waits for the first request to reach the controlled upstream
before sending the second request, avoiding dependence on arbitrary sleeps.

### Engineering insight and limitation

Admission control must recover after both success and failure. Releasing the
slot in `finally` prevents failed requests from permanently consuming capacity.

A released gateway slot does not prove that Ollama stopped computing after a
timeout. Therefore, the gateway counter alone cannot guarantee the number of
active backend generations. Cancellation behavior needs separate investigation.

## Day 3: Health, readiness, and request tracing

See the [current architecture and sequence diagram](../../docs/architecture.md)
and the [root architecture overview](../../README.md#current-local-architecture).

Project-owner manual checks on 2026-11-08 produced these results:

| Configured upstream | `/healthz` | `/readyz` |
|---|---|---|
| Unavailable local port 11435 | 200, `alive: true` | 503, `upstream_unavailable` |
| Local Ollama on port 11434 with configured model installed | 200, `alive: true` | 200, `ready: true` |

Readiness is defined by the check's logic, not by the endpoint name. The current
check verifies reachability and model installation, not residency or generation.
These are owner-reported manual observations, not independently rerun measurements.
### Automated validation

Six tests added on Day 3 verify:

| Scenario | Verified behavior |
|---|---|
| Liveness request | 200 with `alive: true`; upstream helper is never called |
| Configured model installed | 200 with `ready: true`; `/api/tags` is queried once |
| Configured model missing | 503 with `model_not_available` |
| Model list changes from missing to installed | Successive probes return 503 then 200 without restarting the gateway |
| Upstream connection failure | 503 with `upstream_unavailable`; response and error-body request IDs match |
| Request logging | Response `X-Request-ID` matches the structured log, including correct route and status |

Model-list scenarios mock the upstream helper. The connection-failure test injects
an HTTP client error specifically for the upstream model-list URL. These tests
verify gateway behavior, not actual model installation or backend cancellation.

### Manual request tracing

The project owner matched response header `X-Request-ID` and log `request_id`:
`e60d5a34a0ef47d49a392e03190e3baa`. The log recorded `GET /healthz`, status 200,
and approximately 0.100 ms of gateway processing time. This is one reported
observation, not a latency guarantee or client round-trip measurement.

### Operational interpretation

- Readiness is checked on demand. No background probe scheduler exists in this
  deployment; a future Kubernetes readiness probe must be configured explicitly.
- Installing the configured model is reflected on the next readiness request.
  Changing the configured model name requires restarting with the new CLI value.
- Readiness does not gate `/api/generate` in this implementation. Generation is
  handled separately and may fail even after a successful readiness response.
- Liveness stays independent of Ollama so dependency failure is not mistaken for
  failure of the gateway itself. Readiness success does not imply a warm model.
- Request IDs correlate a response with one gateway log entry. This is not
  distributed tracing across Ollama, nor proof of ID uniqueness under every workload.

### Reproduce automated checks

From the repository root, after installing `requirements.txt` in `.venv`:

```bash
make check PYTHON=.venv/bin/python
```

The complete verification runs 31 tests, the legacy shell script syntax check,
and `git diff --check`. Probe deadline behavior, malformed model metadata, and
privacy assertions on inference logs remain candidates for further tests.
