"""Standard-library, non-streaming Ollama measurements. No retries or model pulls."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import time
import urllib.error
import urllib.request
import uuid

MODEL = "llama3.2:1b"
PROMPT = "Explain Kubernetes readiness probes in three sentences."
DURATIONS = ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")
SETTINGS = ("OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_MAX_QUEUE",
            "OLLAMA_CONTEXT_LENGTH", "OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def ns_to_ms(value):
    return value / 1_000_000


def percentile(values, percent):
    """Linear interpolation at (n-1)*p, including n=1; empty samples -> None."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percent / 100
    lo, hi = math.floor(rank), math.ceil(rank)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def generation_metrics(data):
    if not isinstance(data, dict) or data.get("done") is not True:
        raise ValueError("Expected a completed JSON object (done=true)")
    if data.get("error"):
        raise ValueError("Ollama error: " + str(data["error"]))
    if not isinstance(data.get("response"), str):
        raise ValueError("Missing string response")
    for key in (*DURATIONS, "eval_count", "prompt_eval_count"):
        value = data.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    if data["total_duration"] <= 0 or data["eval_duration"] <= 0 or data["eval_count"] <= 0:
        raise ValueError("Generation must have positive durations and output tokens")
    metrics = {key.replace("_duration", "_ms"): ns_to_ms(data[key]) for key in DURATIONS}
    metrics.update(output_tokens=data["eval_count"], prompt_tokens=data["prompt_eval_count"],
                   generation_tokens_per_sec=data["eval_count"] * 1e9 / data["eval_duration"])
    return metrics


def http_call(base_url, path, payload=None, timeout=120, generation=False):
    """Time request construction through complete body read; exclude JSON parsing.

    urllib timeout is a socket-operation timeout, NOT a strict whole-request deadline.
    raw_body_base64 preserves exact received bytes even for non-UTF8 error pages.
    """
    record = {"started_at": utc_now(), "http_status": None, "success": False,
              "error": None, "raw_body_base64": None, "response": None, "metrics": None}
    start = time.perf_counter()
    raw = None
    try:
        request = urllib.request.Request(base_url.rstrip("/") + path,
                                        data=None if payload is None else json.dumps(payload).encode(),
                                        headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            record["http_status"] = response.status
            raw = response.read()
        record["success"] = 200 <= record["http_status"] < 300
        if not record["success"]:
            record["error"] = {"type": "HTTPError", "message": f"HTTP {record['http_status']}"}
    except urllib.error.HTTPError as exc:
        record["http_status"] = exc.code
        record["error"] = {"type": "HTTPError", "message": str(exc)}
        try:
            raw = exc.read()
        except (OSError, ValueError) as read_error:
            record["error"]["body_read_error"] = str(read_error)
        finally:
            exc.close()
    except (OSError, ValueError, http.client.HTTPException) as exc:
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
    record["latency_ms"] = (time.perf_counter() - start) * 1000
    if raw is not None:
        record["raw_body_base64"] = base64.b64encode(raw).decode("ascii")
        try:
            data = json.loads(raw)
            record["response"] = data
            if record["success"]:
                if not isinstance(data, dict) or data.get("error"):
                    raise ValueError("Expected JSON object without API error")
                if generation:
                    record["metrics"] = generation_metrics(data)
        except (ValueError, UnicodeDecodeError) as exc:
            record["success"] = False
            if record["error"] is None:
                record["error"] = {"type": "InvalidResponse", "message": str(exc)}
    return record


def summarize(records, elapsed_seconds):
    if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0:
        raise ValueError("elapsed_seconds must be finite and positive")
    good = [r for r in records if r["success"]]
    latencies = [r["latency_ms"] for r in good]
    attempted, successful = len(records), len(good)
    return {"attempted": attempted, "successful": successful, "failed": attempted - successful,
            "latency_population": "successful requests only",
            "p50_ms": percentile(latencies, 50), "p95_ms": percentile(latencies, 95),
            "duration_seconds": elapsed_seconds,
            "attempted_requests_per_sec": attempted / elapsed_seconds,
            "requests_per_sec": successful / elapsed_seconds,
            "output_tokens": sum(r["metrics"]["output_tokens"] for r in good),
            "output_tokens_per_sec": sum(r["metrics"]["output_tokens"] for r in good) / elapsed_seconds,
            "error_rate": (attempted - successful) / attempted if attempted else None}


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def command_output(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return {"returncode": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def environment(args):
    lab = Path(__file__).resolve().parent
    api = {name: http_call(args.base_url, "/api/" + name, timeout=args.timeout)
           for name in ("version", "tags", "ps")}
    api["show"] = http_call(args.base_url, "/api/show", {"model": args.model}, args.timeout)
    return {"captured_at": utc_now(), "platform": platform.platform(),
            "machine": platform.machine(), "python": platform.python_version(),
            "logical_cpu_count": os.cpu_count(),
            "hardware": command_output(["sysctl", "-n", "machdep.cpu.brand_string", "hw.memsize"])
                        if platform.system() == "Darwin" else {"note": "Not collected on this OS"},
            "git_head": command_output(["git", "-C", str(lab), "rev-parse", "HEAD"]),
            "git_status": command_output(["git", "-C", str(lab), "status", "--short"]),
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in lab.glob("*.py")},
            "client_environment_only": {k: os.environ.get(k) for k in SETTINGS},
            "server_parallelism": {"effective_OLLAMA_NUM_PARALLEL": None,
                                   "verification": "unknown; client environment is not server evidence"},
            "operator_notes": args.notes, "api": api}


def positive_int(value):
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return n


def positive_float(value):
    n = float(value)
    if not math.isfinite(n) or n <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return n


def parser(description):
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--base-url", default="http://127.0.0.1:11434")
    p.add_argument("--prompt", default=PROMPT)
    p.add_argument("--num-predict", type=positive_int, default=128)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--temperature", type=float, default=0)
    p.add_argument("--num-ctx", type=positive_int, default=4096)
    p.add_argument("--timeout", type=positive_float, default=120)
    p.add_argument("--repeats", type=positive_int, default=3)
    p.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "results/runs")
    p.add_argument("--notes", default="", help="Power mode, competing workloads, thermal conditions, etc.")
    return p


def payload(args):
    return {"model": args.model, "prompt": args.prompt, "stream": False, "keep_alive": "10m",
            "options": {"temperature": args.temperature, "seed": args.seed,
                        "num_predict": args.num_predict, "num_ctx": args.num_ctx}}


class Experiment:
    """Unique run directory, append-only request journal, atomic report checkpoints."""
    def __init__(self, args, kind):
        if not math.isfinite(args.temperature) or args.temperature < 0:
            raise ValueError("temperature must be finite and nonnegative")
        self.args = args
        self.path = args.output_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                                       + "-" + kind + "-" + uuid.uuid4().hex[:8])
        self.path.mkdir(parents=True, exist_ok=False)
        self.request_payload = payload(args)
        self.report = {"schema_version": 1, "kind": kind, "started_at": utc_now(),
                       "status": "running", "configuration": {**vars(args), "output_dir": str(args.output_dir)},
                       "request_payload": self.request_payload, "retries": 0, "runs": []}
        self.save()
        print("Results: " + str(self.path), flush=True)
        write_json(self.path / "environment.json", environment(args))

    def save(self):
        write_json(self.path / "summary.json", self.report)

    def record(self, value):
        with (self.path / "requests.jsonl").open("a") as f:
            f.write(json.dumps(value, allow_nan=False) + "\n")
            f.flush()

    def call(self, label, request_payload=None, generation=True):
        value = http_call(self.args.base_url, "/api/generate",
                          self.request_payload if request_payload is None else request_payload,
                          self.args.timeout, generation)
        value["label"] = label
        self.record(value)
        return value

    def require(self, record):
        if not record["success"]:
            raise RuntimeError(f"{record.get('label', 'request')} failed: {record['error']}")

    def finish(self, status, error=None):
        self.report.update(status=status, finished_at=utc_now(), error=error)
        write_json(self.path / "server-after.json", http_call(self.args.base_url, "/api/ps", timeout=self.args.timeout))
        self.save()


def concurrency_run(experiment, workers, repeat, count):
    records = []
    started_at = utc_now()
    start = time.perf_counter()
    # A closed-loop fixed-batch test, not a fixed-arrival-rate load generator.
    # Queue wait in the client executor is excluded from per-request latency.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(http_call, experiment.args.base_url, "/api/generate",
                               experiment.request_payload, experiment.args.timeout, True): i
                   for i in range(count)}
        for future in as_completed(futures):
            record = future.result()
            record.update(label="measurement", repeat=repeat, concurrency=workers,
                          request_id=futures[future])
            records.append(record)
            experiment.record(record)
    elapsed = time.perf_counter() - start
    return {"repeat": repeat, "concurrency": workers, "started_at": started_at,
            "summary": summarize(records, elapsed)}
