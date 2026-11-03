"""Model-residency Cold/Warm pairs; OS filesystem caches are not cleared."""
from benchlib import Experiment, http_call, parser


def main(argv=None):
    args = parser(__doc__).parse_args(argv)
    experiment = Experiment(args, "cold-warm")
    try:
        for repeat in range(1, args.repeats + 1):
            unload = experiment.call(f"unload-r{repeat}",
                                     {"model": args.model, "stream": False, "keep_alive": 0}, False)
            experiment.require(unload)
            if unload["response"].get("done") is not True:
                raise RuntimeError("Unload did not return done=true")
            ps = http_call(args.base_url, "/api/ps", timeout=args.timeout)
            ps["label"] = f"verify-unloaded-r{repeat}"
            experiment.record(ps)
            experiment.require(ps)
            models = ps["response"].get("models")
            if not isinstance(models, list):
                raise RuntimeError("Cannot verify model unload: invalid /api/ps models")
            names = {args.model, args.model + ":latest"} if ":" not in args.model else {args.model}
            if any(m.get("name") in names or m.get("model") in names for m in models):
                raise RuntimeError("Model still resident after unload; refusing to label a cold sample")
            cold = experiment.call(f"cold-r{repeat}")
            experiment.require(cold)
            # Explicit warmup independent of the measured cold sample.
            experiment.require(experiment.call(f"warmup-r{repeat}"))
            warm = experiment.call(f"warm-r{repeat}")
            experiment.require(warm)
            experiment.report["runs"].append({"repeat": repeat,
                "cold": {"latency_ms": cold["latency_ms"], **cold["metrics"]},
                "warm": {"latency_ms": warm["latency_ms"], **warm["metrics"]}})
            experiment.save()
            print(f"repeat={repeat} cold_ms={cold['latency_ms']:.2f} warm_ms={warm['latency_ms']:.2f}", flush=True)
        experiment.finish("completed")
    except (RuntimeError, OSError, KeyboardInterrupt) as exc:
        experiment.finish("aborted", f"{type(exc).__name__}: {exc}")
        print("Experiment aborted; inspect saved raw records: " + str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
