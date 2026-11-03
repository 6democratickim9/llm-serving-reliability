import json
import time
import urllib.request
from pathlib import Path
from statistics import median
from concurrent.futures import ThreadPoolExecutor

API = "http://localhost:11434/api/generate"
MODEL = "llama3.2:1b"
REQUESTS = 12
CONCURRENCY = [1, 2, 4]

payload = {
    "model": MODEL,
    "prompt": "Explain Kubernetes readiness probes in three sentences.",
    "stream": False,
    "keep_alive": "10m",
    "options": {
        "temperature": 0,
        "seed": 42,
        "num_predict": 128,
    },
}

def request():
    start = time.perf_counter()
    try:
        req = urllib.request.Request(
            API,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)

        if not data.get("done"):
            raise RuntimeError("Incomplete response")

        return {
            "latency_ms": (time.perf_counter() - start) * 1000,
            "tokens": data.get("eval_count", 0),
            "success": True,
        }
    except Exception as e:
        return {
            "latency_ms": (time.perf_counter() - start) * 1000,
            "success": False,
            "error": str(e),
        }

# 사전 워밍업
warmup = request()
if not warmup["success"]:
    raise RuntimeError(f"Warmup failed: {warmup}")

results = []

for workers in CONCURRENCY:
    start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(lambda _: request(), range(REQUESTS)))

    elapsed = time.perf_counter() - start
    latencies = sorted(x["latency_ms"] for x in records if x["success"])
    successes = len(latencies)
    tokens = sum(x.get("tokens", 0) for x in records)

    p95 = None
    if latencies:
        idx = 0.95 * (len(latencies) - 1)
        low = int(idx)
        high = min(low + 1, len(latencies) - 1)
        p95 = latencies[low] + (latencies[high] - latencies[low]) * (idx - low)

    summary = {
        "concurrency": workers,
        "requests": REQUESTS,
        "successes": successes,
        "error_rate": (REQUESTS - successes) / REQUESTS,
        "p50_ms": round(median(latencies), 2) if latencies else None,
        "p95_ms": round(p95, 2) if p95 is not None else None,
        "requests_per_sec": round(REQUESTS / elapsed, 2),
        "output_tokens_per_sec": round(tokens / elapsed, 2),
    }
    results.append(summary)
    print(json.dumps(summary, indent=2))

out = Path(__file__).parent / "results"
out.mkdir(exist_ok=True)
(out / "concurrency.json").write_text(json.dumps(results, indent=2))
