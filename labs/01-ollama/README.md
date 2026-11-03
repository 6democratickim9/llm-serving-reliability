# Experiment 01: Ollama performance and reliability baseline

## Question

For an internal assistant, does increasing client concurrency increase useful throughput,
or mostly increase latency? How much does model residency affect startup latency?
The experiment characterizes the tested workload, not a production capacity guarantee.

## Preserve the starting point

The existing uncommitted `benchmark.sh`, `concurency.py` (original spelling) and
`results/` files are retained byte-for-byte. The tracked `results.txt` was already
deleted in the working tree; its identical content exists at `results/results.txt`.
That text is a generated Kubernetes explanation, not a benchmark. No deletion was
reverted and no original result was overwritten.

The legacy scripts write fixed filenames. **Use the new commands below for new runs.**
They reuse the original model, prompt, deterministic seed, temperature and output cap,
while adding explicit context length, repeats, provenance and error evidence.

## Execute

From the repository root, with Python 3.10+, Ollama running and the model already installed:

```bash
make check
python3 labs/01-ollama/cold_warm.py --model llama3.2:1b --repeats 3
python3 labs/01-ollama/concurrency.py --model llama3.2:1b \
  --requests 12 --concurrency 1 2 4 --repeats 3 --timeout 120
python3 labs/01-ollama/analyze.py labs/01-ollama/results/runs/<concurrency-run>
```

Common flags: `--base-url`, `--model`, `--prompt`, `--num-predict` (128), `--seed` (42),
`--temperature` (0), `--num-ctx` (4096), `--timeout` (120 seconds), `--repeats` (3),
`--output-dir` and `--notes`. `--concurrency` takes space-separated positive integers;
`--requests` is the fixed count **per level per repetition**, not per worker.
`--notes` records power mode, background load and other operator observations.
No command downloads a model, changes server configuration or provisions infrastructure.

Cold/Warm uses 3 unload requests and 9 generations (3 cold, 3 warmups, 3 warm).
The default concurrency experiment uses 108 measured generations plus 9 excluded
warmups. Keep other clients idle; run these experiments sequentially.

## Outputs and failures

Each invocation prints a unique timestamp/UUID directory under `results/runs/`.
This default output is ignored by Git. Deliberately retained real evidence lives
under `results/verified/`; review prompts/responses before sharing data.

| File | Purpose |
|---|---|
| `environment.json` | Platform, hardware, Python, Git head/dirty state, source hashes; raw `/api/version`, `/api/tags`, `/api/show`, `/api/ps` responses |
| `requests.jsonl` | Append-only request records, including warmups/unloads, errors, HTTP status, client latency, parsed API response and exact body as base64 |
| `summary.json` | Configuration, exact payload, status, per-run measurements and duration; atomically checkpointed after each run |
| `server-after.json` | Post-experiment `/api/ps` observation |

Exit 0 means all measured requests and setup succeeded. Exit 1 means an aborted
setup/run or at least one measured failure. Measured failures remain in JSON even
when other requests succeed. Metadata endpoint failures are recorded and do not
fabricate environment values. A failed warmup stops the experiment. Cold measurements
also stop if unload or its `/api/ps` confirmation fails. A process kill can leave
`status=running`; completed journal entries remain available, but this is not a
complete experiment. Filesystem errors are surfaced rather than discarded.

`--timeout` is urllib's socket-operation timeout, **not a hard end-to-end deadline**.
A client timeout does not prove Ollama cancelled generation; stop competing clients
and check server state before rerunning after failures. There are no retries.

## Code and engineering decisions

| Module | Role and important interfaces | Why / limits |
|---|---|---|
| `benchlib.py` | `http_call`, `generation_metrics`, `summarize`, `Experiment`, `concurrency_run` | One implementation of units, validation, provenance and persistence; stdlib keeps setup small. Non-streaming means no TTFT. |
| `cold_warm.py` | `main`: unload, verify absence, measure cold, explicitly prime, measure warm | Defines model-residency cold; does not purge OS caches. Failed prerequisites prevent mislabeled measurements. |
| `concurrency.py` | `main`: warmup each run, rotate levels across repeats, bounded executor | Keeps client concurrency distinct from server parallelism. Rotation reduces order bias; a desktop is not a controlled thermal environment. |
| `analyze.py` | `analyze`: validate saved counts/summary, pool raw successful samples | Reanalysis requires no backend. Pooled percentiles are not averages of per-run percentiles. |
| `tests/test_benchmark.py` | Unit and orchestration tests using mocked HTTP | Verifies calculations, failures, protocol ordering, serialization and worker bound without live inference. |

`http_call` captures `perf_counter()` around the HTTP exchange through body read,
then validates JSON outside that timer. Required durations/counts must be nonnegative
integers; generation needs positive total/evaluation duration and output count.
A complete HTTP 200 body with invalid metrics is a benchmark failure, not a success.
Additional API fields remain in the raw response, including cache counters when provided.

The executor owns at most C simultaneous HTTP calls. Requests queued in the client
executor have no request latency timer yet. Complete run duration includes executor
startup/drain and local record-writing overhead, and excludes warmup. This distinction
is essential when comparing response latency and batch completion time.

## Interpretation and troubleshooting

- Read [methodology](docs/methodology.md) before comparing runs.
- [Analysis](docs/analysis.md) separates supplied observations, inherited local artifacts
  and independently executed evidence. [PoC](docs/poc-report.md) maps evidence to decisions.
- Connection refused: start Ollama, check `curl http://127.0.0.1:11434/api/version`.
- Model missing: inspect `ollama list`; explicitly pull the desired model if appropriate.
- Timeout/HTTP error: inspect the request record and server logs; do not silently retry.
- No model available: run `make check`; live integration remains **Pending validation**
  until the two commands above succeed. Mocked tests are not integration measurements.
- Changing request count or context/output length creates a new workload; label it.
