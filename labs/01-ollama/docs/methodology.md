# Benchmark methodology

## Workload and controls

Use `llama3.2:1b`, the prompt "Explain Kubernetes readiness probes in three sentences.",
`stream=false`, temperature 0, seed 42, `num_predict=128`, `num_ctx=4096`, and
`keep_alive=10m`. Record the exact request and model digest. Fixed options reduce
variation but do not guarantee identical token counts or cache behavior.
`num_predict` is a cap, not a forced output length. No response is cached by this client.

Cold is defined by an explicit `keep_alive=0` unload and successful `/api/ps` absence
check before generation. Warm has an additional successful priming generation.
Unload does **not** clear filesystem/page caches, reboot the host or guarantee that
all driver/backend caches are cold. Other clients can reload a model between the
check and the measurement; an idle dedicated server is a prerequisite.

Concurrency is a closed-loop fixed batch: 12 attempts, worker limits 1/2/4, each
repeated three times. Warm up before every run. Rotate level order: 1/2/4, 2/4/1,
4/1/2. Each worker starts its next request only after its preceding call finishes.
This bounds concurrency and reduces order bias but does not model fixed-rate arrivals,
bursty production traffic or a long sustained saturation test. Retries are disabled.

## Metric definitions

| Metric | Definition |
|---|---|
| Client latency (ms) | Monotonic elapsed HTTP request/body-read time x 1000; excludes executor queue wait and JSON parsing |
| Server timing (ms) | Each API `*_duration` in ns divided by 1,000,000 |
| Generation tokens/s | `eval_count * 1,000,000,000 / eval_duration`; not divided by total latency |
| P50/P95 | Sorted successful client samples, linear interpolation at `(n-1)*p` |
| Successful request throughput (RPS) | Successful requests / entire measured run wall seconds |
| Attempt throughput | All attempted requests / same wall seconds |
| Aggregate output tokens/s | Sum of successful output token counts / same wall seconds |
| Error rate | Failed attempts / attempted requests; includes transport, HTTP and malformed/incomplete responses |
| Run duration | Before executor creation to after executor drain and journal writes, excluding warmup |

Per-request token generation speed and aggregate throughput have different denominators.
Failure latencies and bodies remain in raw records, even though successful latency
percentiles exclude failures. Always read percentiles alongside error rate; all-failure
runs have null percentiles and zero useful throughput. Partial tokens from failed
requests do not count as useful completed output.

For combined results, pool raw successful latencies and sum successes/tokens and run
durations. Do not average P95s or average rates without their denominators. Per-run
statistics remain the primary evidence of run-to-run variability.

## Provenance and limits

Metadata captures API responses and client environment variables separately. An
exported `OLLAMA_NUM_PARALLEL` in the client process does not establish the running
server's effective setting; it remains unknown without independently verified server
startup/configuration evidence. Neither worker count nor an API model listing proves
server scheduling capacity. Do not assign server queue time by subtracting timing fields:
client/server timers cover different boundaries and may contain overlapping overhead.

Twelve samples per run, even three repeats, are insufficient for reliable tail latency,
rare-error estimates or an SLO. A higher P95 is consistent with contention, serialization,
thermal throttling, longer outputs or other effects; it is not proof of server queuing.
A zero-error short run is not evidence of zero production failure probability.

The small repeated prompt can heavily reuse prompt/KV caches. Inspect prompt cache
counts, output counts and model load time before attributing changes to concurrency.
Use unique prompts and varied input/output lengths in a follow-up experiment. Longer
runs should include server logs, memory/thermal observations, queue/admission evidence,
and a specified arrival rate. TTFT and inter-token latency require a streaming experiment.

## References

- [Ollama generate API](https://docs.ollama.com/api/generate): fields, durations, options and keep-alive.
- [Ollama FAQ](https://docs.ollama.com/faq): model residency and server configuration.

Runtime observations are authoritative for the specific installed version; documentation
or defaults are not evidence of an individual server's effective configuration.
