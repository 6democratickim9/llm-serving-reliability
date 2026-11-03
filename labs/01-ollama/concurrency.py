"""Bounded closed-loop concurrency experiment; see README.md for metric semantics."""
from benchlib import Experiment, concurrency_run, parser, positive_int

REQUESTS_PER_RUN = 12
CONCURRENCY_LEVELS = [1, 2, 4]
REPEAT_COUNT = 3


def main(argv=None):
    p = parser(__doc__)
    p.add_argument("--requests", type=positive_int, default=REQUESTS_PER_RUN)
    p.add_argument("--concurrency", type=positive_int, nargs="+", default=CONCURRENCY_LEVELS)
    p.set_defaults(repeats=REPEAT_COUNT)
    args = p.parse_args(argv)
    experiment = Experiment(args, "concurrency")
    failed = False
    try:
        # Rotate order across repeats to reduce (not eliminate) order/temperature bias.
        for repeat in range(1, args.repeats + 1):
            offset = (repeat - 1) % len(args.concurrency)
            levels = args.concurrency[offset:] + args.concurrency[:offset]
            for workers in levels:
                experiment.require(experiment.call(f"warmup-r{repeat}-c{workers}"))
                result = concurrency_run(experiment, workers, repeat, args.requests)
                experiment.report["runs"].append(result)
                failed |= result["summary"]["failed"] > 0
                experiment.save()
                s = result["summary"]
                print(f"repeat={repeat} concurrency={workers} successful={s['successful']}/{s['attempted']} "
                      f"p95_ms={s['p95_ms']} rps={s['requests_per_sec']:.3f}", flush=True)
        experiment.finish("completed_with_errors" if failed else "completed")
    except (RuntimeError, OSError, KeyboardInterrupt) as exc:
        experiment.finish("aborted", f"{type(exc).__name__}: {exc}")
        print("Experiment aborted; inspect saved raw records: " + str(exc))
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
