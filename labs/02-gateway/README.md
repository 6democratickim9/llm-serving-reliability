# Milestone 2: Local inference gateway

Status: forwarding and error handling passed four automated tests, with manual
local checks for real Ollama success, timeout, and connection failure.
The broader gateway draft is not fully validated; see remaining validation below.

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

- Full repository checks after integrating the gateway tests.
- Admission control and health-check behavior present in the draft.
- Direct-versus-gateway performance comparison under an equivalent workload.
