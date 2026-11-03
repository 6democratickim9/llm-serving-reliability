"""Recompute concurrency summaries from saved samples without contacting Ollama."""
import argparse
import json
from pathlib import Path
from benchlib import summarize


def analyze(path):
    report = json.loads((path / "summary.json").read_text())
    if report["status"] not in ("completed", "completed_with_errors"):
        raise ValueError("Run is incomplete; inspect requests.jsonl rather than treating it as a full experiment")
    records = [json.loads(line) for line in (path / "requests.jsonl").read_text().splitlines()]
    if report["kind"] != "concurrency":
        return {"kind": report["kind"], "status": report["status"], "runs": report["runs"]}
    groups = {}
    recomputed = []
    for run in report["runs"]:
        workers, repeat = run["concurrency"], run["repeat"]
        samples = [r for r in records if r.get("label") == "measurement"
                   and r["repeat"] == repeat and r["concurrency"] == workers]
        if len(samples) != report["configuration"]["requests"]:
            raise ValueError("Raw sample count differs from configured requests")
        if len({r["request_id"] for r in samples}) != len(samples):
            raise ValueError("Duplicate request IDs")
        summary = summarize(samples, run["summary"]["duration_seconds"])
        if summary != run["summary"]:
            raise ValueError("Saved summary does not match request samples")
        recomputed.append({"repeat": repeat, "concurrency": workers, **summary})
        group = groups.setdefault(workers, {"samples": [], "duration_seconds": 0, "repeats": []})
        group["samples"].extend(samples)
        group["duration_seconds"] += summary["duration_seconds"]
        group["repeats"].append(repeat)
    if len(recomputed) != len(report["configuration"]["concurrency"]) * report["configuration"]["repeats"]:
        raise ValueError("Missing repeated runs")
    for group in groups.values():
        if sorted(group["repeats"]) != list(range(1, report["configuration"]["repeats"] + 1)):
            raise ValueError("Missing or duplicate repeat")
    return {"kind": "concurrency", "status": report["status"], "per_run": recomputed,
            "pooled_by_concurrency": [{"concurrency": c, **summarize(g["samples"], g["duration_seconds"])}
                                      for c, g in sorted(groups.items())],
            "notes": "Pooled percentiles use all successful samples, not averages of per-run percentiles. "
                     "Throughput uses total successes/tokens divided by sum of measured run durations. "
                     "Warmups and inter-run gaps are excluded. This is not a sustained-capacity claim."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.run_dir), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
