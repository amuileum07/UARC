"""Verify a built executable with real spawn workers and temporary application data."""

import argparse
import csv
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from time import monotonic, sleep


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    root = Path(__file__).resolve().parents[2]
    design = root / "examples" / "design.json"
    environment = dict(os.environ, PYTHONPATH="", PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONHOME", None)
    with tempfile.TemporaryDirectory(prefix="uarc-bundle-smoke-") as temporary:
        directory = Path(temporary)
        data = directory / "data"

        def run(*arguments):
            result = subprocess.run(
                [str(executable), *map(str, arguments)],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode:
                raise RuntimeError(
                    f"Bundle command failed: {arguments}\n{result.stderr}"
                )
            return json.loads(result.stdout) if result.stdout.strip() else None

        preview = run("--simulate", design, "--design", "--preview")
        assert preview["mass_properties"]["effective"]["mass_kg"] > 0
        flight = run("--simulate", design, "--design", "--data-dir", data)
        run_id = flight["run_id"]
        assert flight["summary"]["landed"]
        assert (data / "runs" / run_id / "complete.json").is_file()
        history = run("--data", "--data-dir", data, "list-runs")
        assert history[0]["state"] == "succeeded"
        assert history[0]["worker_pid"] != os.getpid()
        exported = directory / "flight.csv"
        run("--data", "--data-dir", data, "export-csv", run_id, exported)
        with exported.open(newline="") as stream:
            rows = list(csv.reader(stream))
        assert len(rows[0]) == 14 and len(rows) > 2
        assert abs(float(rows[-1][0]) - flight["summary"]["end_time_s"]) < 1e-9
        saved = run("--data", "--data-dir", data, "save-design", design)
        loaded = run("--data", "--data-dir", data, "load-design", saved["design_id"])
        assert loaded["name"] == json.loads(design.read_bytes())["name"]
        converted = directory / "converted.json"
        run(
            "--data",
            "--data-dir",
            data,
            "import-ork",
            root / "backend/tests/fixtures/single-stage.ork",
            "--options",
            root / "examples/openrocket-options.json",
            "--output",
            converted,
        )
        imported_flight = run("--simulate", converted, "--design", "--data-dir", data)
        assert imported_flight["summary"]["landed"]

        if sys.platform == "linux":
            dense = json.loads(design.read_bytes())
            dense["flight"]["max_time_step"] = 1e-6
            dense_path = directory / "dense.json"
            dense_path.write_text(json.dumps(dense))
            cancelled_data = directory / "cancelled"
            with (directory / "cancel.log").open("w") as log:
                process = subprocess.Popen(
                    [
                        str(executable),
                        "--simulate",
                        str(dense_path),
                        "--design",
                        "--data-dir",
                        str(cancelled_data),
                    ],
                    cwd=directory,
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
                try:
                    deadline = monotonic() + 30
                    worker_pid = None
                    while monotonic() < deadline and process.poll() is None:
                        for progress in cancelled_data.glob("runs/*/progress.json"):
                            if (
                                json.loads(progress.read_bytes())["stage"]
                                == "simulating"
                            ):
                                with sqlite3.connect(
                                    cancelled_data / "uarc.sqlite3"
                                ) as connection:
                                    worker_pid = connection.execute(
                                        "SELECT worker_pid FROM runs"
                                    ).fetchone()[0]
                                break
                        if worker_pid is not None:
                            break
                        sleep(0.05)
                    assert worker_pid is not None, (
                        "Frozen worker never reached its solver"
                    )
                    process.send_signal(signal.SIGINT)
                    assert process.wait(timeout=10) == 130
                    with sqlite3.connect(cancelled_data / "uarc.sqlite3") as connection:
                        assert (
                            connection.execute("SELECT state FROM runs").fetchone()[0]
                            == "cancelled"
                        )
                    try:
                        os.kill(worker_pid, 0)
                    except ProcessLookupError:
                        pass
                    else:
                        raise AssertionError("Frozen worker survived cancellation")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
        checks = "preview, spawned flights, history, saved designs, OpenRocket import, CSV export"
        if sys.platform == "linux":
            checks += ", Linux cancellation/reaping"
        print(f"Bundle verified: {checks}.")


if __name__ == "__main__":
    main()
