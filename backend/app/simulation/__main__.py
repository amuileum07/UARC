"""Run one JSON-configured simulation through the same supervised backend as the UI."""

import argparse
import json
import sys
from multiprocessing import freeze_support
from pathlib import Path
from time import sleep

from app.config import default_data_directory
from app.design import compile_design
from app.schemas import RocketDesign, SimulationConfig
from app.simulation.jobs import JobManager
from app.storage import MAX_PAYLOAD_BYTES, TERMINAL_STATES


def main() -> None:
    freeze_support()
    parser = argparse.ArgumentParser(
        description="Run a UARC simulation without the GUI."
    )
    parser.add_argument("input", type=Path, help="SimulationConfig JSON file")
    parser.add_argument(
        "--design", action="store_true", help="Read a parametric RocketDesign instead"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print design mass properties without running a flight",
    )
    parser.add_argument("--data-dir", type=Path, default=default_data_directory())
    parser.add_argument("--job-timeout", type=float, default=300)
    parser.add_argument(
        "--memory-limit-mb", type=int, default=1024 if sys.platform == "linux" else None
    )
    args = parser.parse_args()
    if args.preview and not args.design:
        parser.error("--preview requires --design")
    try:
        with args.input.open("rb") as stream:
            payload = stream.read(MAX_PAYLOAD_BYTES + 1)
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise ValueError("Simulation input exceeds the 2 MiB payload limit.")
        config = (
            RocketDesign if args.design else SimulationConfig
        ).model_validate_json(payload)
        if args.preview:
            simulation, report = compile_design(config)
            print(
                json.dumps(
                    {
                        "simulation": simulation.model_dump(mode="json"),
                        "mass_properties": report,
                    },
                    allow_nan=False,
                )
            )
            return
        manager = JobManager(
            args.data_dir,
            max_pending=0,
            timeout_seconds=args.job_timeout,
            memory_limit_mb=args.memory_limit_mb if args.memory_limit_mb != 0 else None,
        )
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    with manager:
        try:
            record = (
                manager.submit_design(config) if args.design else manager.submit(config)
            )
            run_id = record["run_id"]
            previous = None
            while record["state"] not in TERMINAL_STATES:
                current = (record["state"], record["stage"])
                if current != previous:
                    print(
                        f"{run_id}: {current[0]} ({current[1]})",
                        file=sys.stderr,
                        flush=True,
                    )
                    previous = current
                sleep(0.1)
                record = manager.get_run(run_id)
            if record["state"] != "succeeded":
                parser.exit(1, f"{run_id}: {record['state']}: {record['error']}\n")
            print(
                json.dumps(
                    {"run_id": run_id, "summary": manager.get_summary(run_id)},
                    allow_nan=False,
                )
            )
        except KeyboardInterrupt:
            parser.exit(130, "Simulation cancelled.\n")
        except (OSError, ValueError, RuntimeError) as error:
            parser.exit(1, f"Simulation failed: {error}\n")


if __name__ == "__main__":
    main()
