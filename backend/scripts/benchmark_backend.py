"""Measure bounded worker throughput, RSS, and host status-query latency."""

import argparse
import json
import os
import sys
import tempfile
from collections import deque
from multiprocessing import freeze_support
from pathlib import Path
from time import perf_counter, sleep

from app.cli import read_payload
from app.schemas import RocketDesign, SimulationConfig
from app.simulation.jobs import JobManager
from app.storage import TERMINAL_STATES, atomic_json


def main() -> None:
    freeze_support()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--design", action="store_true")
    parser.add_argument("--runs", type=int, default=4)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.runs <= 1000 or not 1 <= args.workers <= 64:
        parser.error("Use 1..1000 runs and 1..64 workers.")
    try:
        config = (
            RocketDesign if args.design else SimulationConfig
        ).model_validate_json(read_payload(args.input))
        # Bound diagnostic memory for long runs. P95 covers the last 10,000
        # queries; use a streaming histogram if whole-run quantiles are needed.
        latencies, finished, pending = deque(maxlen=10_000), [], set()
        maximum_latency = 0.0
        host_peak = 0
        started = perf_counter()
        # Benchmark runs are isolated from application history and removed on exit.
        with (
            tempfile.TemporaryDirectory(prefix="uarc-benchmark-") as temporary,
            JobManager(
                Path(temporary), max_workers=args.workers, max_pending=0
            ) as manager,
        ):
            submitted = 0
            while submitted < args.runs or pending:
                while submitted < args.runs and len(pending) < args.workers:
                    record = (
                        manager.submit_design(config)
                        if args.design
                        else manager.submit(config)
                    )
                    pending.add(record["run_id"])
                    submitted += 1
                for run_id in list(pending):
                    query_start = perf_counter()
                    record = manager.get_run(run_id)
                    latency = (perf_counter() - query_start) * 1000
                    latencies.append(latency)
                    maximum_latency = max(maximum_latency, latency)
                    if record["state"] in TERMINAL_STATES:
                        pending.remove(run_id)
                        finished.append(record)
                if sys.platform == "linux":
                    for line in (
                        Path(f"/proc/{os.getpid()}/status").read_text().splitlines()
                    ):
                        if line.startswith("VmRSS:"):
                            host_peak = max(host_peak, int(line.split()[1]) * 1024)
                sleep(0.02)
            elapsed = perf_counter() - started
        latencies = sorted(latencies)
        failures = [record for record in finished if record["state"] != "succeeded"]
        report = {
            "runs": args.runs,
            "workers": args.workers,
            "elapsed_s": elapsed,
            "succeeded": args.runs - len(failures),
            "failures": failures,
            "runs_per_second": args.runs / elapsed,
            "status_query_p95_ms": latencies[int((len(latencies) - 1) * 0.95)],
            "status_query_max_ms": maximum_latency,
            "status_latency_window_samples": len(latencies),
            "host_sampled_peak_rss_bytes": host_peak
            if sys.platform == "linux"
            else None,
            "worker_sampled_peak_rss_bytes": max(
                record["peak_rss_bytes"] for record in finished
            )
            if sys.platform == "linux"
            else None,
        }
        if args.output:
            atomic_json(args.output, report, overwrite=False)
        print(json.dumps(report, allow_nan=False))
        if failures:
            raise SystemExit(1)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
