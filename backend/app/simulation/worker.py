"""Spawn entry point: build, solve, and save one run without GUI imports."""

import os
import sys
import traceback
from importlib.metadata import version
from multiprocessing import parent_process
from pathlib import Path
from threading import Thread
from time import sleep


def _watch_parent() -> None:
    parent = parent_process()
    if parent is not None:
        while parent.is_alive():
            sleep(0.5)
        # The host died; abandon partial output rather than leave an orphan solver.
        os._exit(1)


def run_worker(directory_name: str) -> None:
    Thread(target=_watch_parent, name="parent-watch", daemon=True).start()
    # Import numerical libraries only in the child, after thread limits are set.
    from app.schemas import SimulationConfig
    from app.simulation.engine import build_simulation, run_simulation, summarize_flight
    from app.storage import atomic_json, save_result

    directory = Path(directory_name)
    try:
        atomic_json(
            directory / "runtime.json",
            {
                "python": sys.version,
                "rocketpy": version("rocketpy"),
                "numpy": version("numpy"),
                "scipy": version("scipy"),
            },
        )
        atomic_json(directory / "progress.json", {"stage": "building"})
        config = SimulationConfig.model_validate_json(
            (directory / "input.json").read_text(encoding="utf-8")
        )
        rocket, environment = build_simulation(config)
        atomic_json(directory / "progress.json", {"stage": "simulating"})
        flight = run_simulation(rocket, environment, config.flight)
        atomic_json(directory / "progress.json", {"stage": "saving"})
        summary = summarize_flight(flight)
        save_result(directory, flight.solution_array, summary)
    except Exception as error:
        atomic_json(
            directory / "error.json",
            {
                "message": f"{type(error).__name__}: {error}"[:4096],
                "traceback": traceback.format_exc()[-32_768:],
            },
        )
        raise SystemExit(1) from error
