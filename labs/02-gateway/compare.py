"""Recompute the curated Day 4 comparison; no server or model is contacted."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB.parent / "01-ollama"))
from analyze import analyze


def compare(root):
    manifest = json.loads((root / "manifest.json").read_text())
    output = []
    for item in manifest["runs"]:
        path = root / item["directory"]
        for filename, expected in item["sha256"].items():
            if hashlib.sha256((path / filename).read_bytes()).hexdigest() != expected:
                raise ValueError(f"Evidence hash mismatch: {path / filename}")
        if item["include_in_comparison"] is False:
            continue
        result = analyze(path)  # Validate each summary against the raw journal.
        samples = [json.loads(line) for line in (path / "requests.jsonl").read_text().splitlines()]
        for pooled in result["pooled_by_concurrency"]:
            selected = [r for r in samples if r.get("label") == "measurement"
                        and r["concurrency"] == pooled["concurrency"]]
            statuses = Counter(str(r.get("http_status")) for r in selected)
            rejected = statuses.get("429", 0)
            output.append({"route": item["route"], **pooled,
                           "http_status_counts": dict(statuses),
                           "rejected_429": rejected,
                           "rejection_rate": rejected / pooled["attempted"],
                           "other_failures": pooled["failed"] - rejected})
    return {"results": output,
            "notes": "Warmups excluded. RPS uses successes divided by summed batch durations. "
                     "Successful-request percentiles only; gateway load groups have only three "
                     "successful samples each. Fixed batches do not establish sustained capacity."}


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else LAB / "results/verified/day4-20261112"
    print(json.dumps(compare(root), indent=2, allow_nan=False))
