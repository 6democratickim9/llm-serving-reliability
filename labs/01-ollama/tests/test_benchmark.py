"""Deterministic tests: no live model, external network, or timing-dependent thresholds."""
import base64
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import http.client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchlib as b
import cold_warm
import concurrency
import analyze

VALID = {"done": True, "response": "answer", "total_duration": 3_000_000_000,
         "load_duration": 1_000_000_000, "prompt_eval_duration": 500_000_000,
         "prompt_eval_count": 12, "eval_duration": 1_500_000_000, "eval_count": 30}


class Response(io.BytesIO):
    status = 200


def good(latency=10):
    return {"success": True, "error": None, "http_status": 200, "latency_ms": latency,
            "response": copy.deepcopy(VALID), "metrics": b.generation_metrics(VALID)}


class MetricsTests(unittest.TestCase):
    def test_duration_units_and_generation_denominator(self):
        m = b.generation_metrics(VALID)
        self.assertEqual(m["total_ms"], 3000)
        self.assertEqual(m["load_ms"], 1000)
        self.assertEqual(m["generation_tokens_per_sec"], 20)

    def test_percentiles(self):
        self.assertIsNone(b.percentile([], 95))
        self.assertEqual(b.percentile([7], 95), 7)
        self.assertEqual(b.percentile([40, 10, 20, 30], 50), 25)
        self.assertAlmostEqual(b.percentile([40, 10, 20, 30], 95), 38.5)
        self.assertEqual(b.percentile([1, 2], 0), 1)
        self.assertEqual(b.percentile([1, 2], 100), 2)
        with self.assertRaises(ValueError):
            b.percentile([1], 101)

    def test_failures_do_not_inflate_goodput_or_success_latency(self):
        s = b.summarize([good(10), good(30), {"success": False, "latency_ms": 1000}], 4)
        self.assertEqual(s["attempted"], 3)
        self.assertEqual(s["successful"], 2)
        self.assertEqual(s["p50_ms"], 20)
        self.assertEqual(s["requests_per_sec"], .5)
        self.assertEqual(s["attempted_requests_per_sec"], .75)
        self.assertEqual(s["output_tokens_per_sec"], 15)
        self.assertAlmostEqual(s["error_rate"], 1/3)

    def test_no_successes_and_invalid_duration(self):
        s = b.summarize([{"success": False}], 1)
        self.assertIsNone(s["p95_ms"])
        self.assertEqual(s["error_rate"], 1)
        self.assertEqual(s["requests_per_sec"], 0)
        self.assertIsNone(b.summarize([], 1)["error_rate"])
        for duration in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                b.summarize([], duration)

    def test_reject_invalid_generation(self):
        samples = [[], {}, {**VALID, "done": False}, {**VALID, "done": 1},
                   {**VALID, "error": "model unavailable"}, {**VALID, "response": None}]
        for field in (*b.DURATIONS, "eval_count", "prompt_eval_count"):
            for value in [None, -1, "10", True, float("nan")]:
                samples.append({**VALID, field: value})
        for field in ["total_duration", "eval_duration", "eval_count"]:
            samples.append({**VALID, field: 0})
        for value in samples:
            with self.subTest(value=value), self.assertRaises(ValueError):
                b.generation_metrics(value)


class HttpTests(unittest.TestCase):
    def test_success_latency_raw_body_and_request_options(self):
        raw = json.dumps(VALID).encode()
        with patch.object(b.urllib.request, "urlopen", return_value=Response(raw)) as open_, \
             patch.object(b.time, "perf_counter", side_effect=[10, 10.25]):
            r = b.http_call("http://localhost:11434", "/api/generate", {"stream": False}, 17, True)
        self.assertTrue(r["success"])
        self.assertEqual(r["latency_ms"], 250)
        self.assertEqual(r["http_status"], 200)
        self.assertEqual(base64.b64decode(r["raw_body_base64"]), raw)
        self.assertEqual(json.loads(open_.call_args.args[0].data), {"stream": False})
        self.assertEqual(open_.call_args.kwargs["timeout"], 17)
        open_.assert_called_once()  # retries disabled

    def test_http_error_keeps_status_and_body(self):
        error = urllib.error.HTTPError("http://local", 503, "busy", {}, io.BytesIO(b'{"error":"busy"}'))
        with patch.object(b.urllib.request, "urlopen", side_effect=error):
            r = b.http_call("http://local", "/api/generate", {}, generation=True)
        self.assertFalse(r["success"])
        self.assertEqual(r["http_status"], 503)
        self.assertEqual(r["response"], {"error": "busy"})
        self.assertEqual(r["error"]["type"], "HTTPError")

    def test_timeout_connection_and_truncated_body(self):
        for error in [TimeoutError("timed out"), urllib.error.URLError("refused"),
                      http.client.IncompleteRead(b'partial')]:
            with self.subTest(error=error), patch.object(b.urllib.request, "urlopen", side_effect=error) as open_:
                r = b.http_call("http://local", "/api/generate", {}, generation=True)
                self.assertFalse(r["success"])
                self.assertIsNone(r["http_status"])
                self.assertIsNotNone(r["error"])
                open_.assert_called_once()

    def test_invalid_and_incomplete_json(self):
        for raw in [b"not json", b"\xff", b"[]", b'{"done":false}', b'{"error":"oops"}']:
            with self.subTest(raw=raw), patch.object(b.urllib.request, "urlopen", return_value=Response(raw)):
                r = b.http_call("http://local", "/api/generate", {}, generation=True)
                self.assertFalse(r["success"])
                self.assertEqual(r["http_status"], 200)
                self.assertEqual(base64.b64decode(r["raw_body_base64"]), raw)


class ExperimentTests(unittest.TestCase):
    def make_experiment(self, path):
        args = b.parser("test").parse_args(["--output-dir", path])
        with patch.object(b, "environment", return_value={"test_fixture": True}):
            return b.Experiment(args, "test")

    def test_serialization_unique_directories_and_journal(self):
        with tempfile.TemporaryDirectory() as d:
            one, two = self.make_experiment(d), self.make_experiment(d)
            self.assertNotEqual(one.path, two.path)
            one.record(good())
            one.report["runs"].append({"summary": b.summarize([good()], 1)})
            one.save()
            result = json.loads((one.path / "summary.json").read_text())
            self.assertEqual(result["runs"][0]["summary"]["output_tokens"], 30)
            self.assertEqual(json.loads((one.path / "requests.jsonl").read_text())["response"], VALID)
            self.assertFalse((one.path / "summary.json.tmp").exists())

    def test_bounded_concurrency_and_complete_journal(self):
        active = 0
        peak = 0
        lock = threading.Lock()
        def call(*args):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.005)
            with lock:
                active -= 1
            return good()
        with tempfile.TemporaryDirectory() as d:
            e = self.make_experiment(d)
            with patch.object(b, "http_call", side_effect=call):
                run = b.concurrency_run(e, 2, 1, 7)
            self.assertLessEqual(peak, 2)
            self.assertEqual(run["summary"]["successful"], 7)
            rows = [json.loads(x) for x in (e.path / "requests.jsonl").read_text().splitlines()]
            self.assertEqual(sorted(r["request_id"] for r in rows), list(range(7)))

    def test_cold_warm_protocol_and_failed_unload(self):
        for still_resident in [False, True]:
            calls = []
            def http(base, path, payload=None, *args, **kwargs):
                calls.append((path, payload))
                if path == "/api/ps":
                    return {**good(), "response": {"models": [{"name": b.MODEL}] if still_resident else []}}
                return good()
            with tempfile.TemporaryDirectory() as d, \
                 patch.object(b, "environment", return_value={}), \
                 patch.object(b, "http_call", side_effect=http), \
                 patch.object(cold_warm, "http_call", side_effect=http):
                code = cold_warm.main(["--output-dir", d, "--repeats", "1"])
                report = json.loads(next(Path(d).glob("*/summary.json")).read_text())
                self.assertEqual(code, int(still_resident))
                self.assertEqual(calls[0][1]["keep_alive"], 0)
                generations = [p for _, p in calls if p and p.get("prompt")]
                self.assertEqual(len(generations), 0 if still_resident else 3)
                self.assertEqual(report["status"], "aborted" if still_resident else "completed")

    def test_failed_warmup_aborts_with_evidence(self):
        failure = {**good(), "success": False, "error": {"type": "TimeoutError", "message": "test"}}
        with tempfile.TemporaryDirectory() as d, patch.object(b, "environment", return_value={}), \
             patch.object(b, "http_call", return_value=failure):
            code = concurrency.main(["--output-dir", d])
            report = json.loads(next(Path(d).glob("*/summary.json")).read_text())
            self.assertEqual(code, 1)
            self.assertEqual(report["status"], "aborted")
            self.assertEqual(report["runs"], [])
            self.assertTrue(next(Path(d).glob("*/requests.jsonl")).exists())

    def test_repeat_rotation_and_measurement_failure_exit(self):
        def run(e, workers, repeat, count):
            return {"concurrency": workers, "repeat": repeat,
                    "summary": b.summarize([good(), {"success": False}], 1)}
        with tempfile.TemporaryDirectory() as d, patch.object(b, "environment", return_value={}), \
             patch.object(b, "http_call", side_effect=lambda *a, **kw: good()), \
             patch.object(concurrency, "concurrency_run", side_effect=run):
            code = concurrency.main(["--output-dir", d])
            report = json.loads(next(Path(d).glob("*/summary.json")).read_text())
            self.assertEqual(code, 1)
            self.assertEqual(report["status"], "completed_with_errors")
            self.assertEqual([r["concurrency"] for r in report["runs"]], [1, 2, 4, 2, 4, 1, 4, 1, 2])

    def test_cli_rejects_invalid_limits(self):
        for flag, value in [("--repeats", "0"), ("--timeout", "nan"), ("--num-ctx", "-1")]:
            with self.subTest(flag=flag), self.assertRaises(SystemExit):
                b.parser("test").parse_args([flag, value])


class ReanalysisTests(unittest.TestCase):
    def fixture(self, directory):
        records = [{**good(10), "label": "measurement", "repeat": 1, "concurrency": 1, "request_id": 0},
                   {**good(30), "label": "measurement", "repeat": 1, "concurrency": 1, "request_id": 1}]
        report = {"kind": "concurrency", "status": "completed",
                  "configuration": {"requests": 2, "concurrency": [1], "repeats": 1},
                  "runs": [{"repeat": 1, "concurrency": 1, "summary": b.summarize(records, 2)}]}
        b.write_json(directory / "summary.json", report)
        (directory / "requests.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return report

    def test_recompute_and_detect_changed_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            report = self.fixture(path)
            result = analyze.analyze(path)
            self.assertEqual(result["pooled_by_concurrency"][0]["p50_ms"], 20)
            self.assertEqual(result["pooled_by_concurrency"][0]["requests_per_sec"], 1)
            report["runs"][0]["summary"]["p50_ms"] = 900
            b.write_json(path / "summary.json", report)
            with self.assertRaises(ValueError):
                analyze.analyze(path)

    def test_reject_incomplete_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.fixture(path)
            (path / "requests.jsonl").write_text("")
            with self.assertRaises(ValueError):
                analyze.analyze(path)

    def test_reject_incomplete_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            report = self.fixture(path)
            report["status"] = "running"
            b.write_json(path / "summary.json", report)
            with self.assertRaises(ValueError):
                analyze.analyze(path)


if __name__ == "__main__":
    unittest.main()
