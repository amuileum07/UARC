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


def forecast_design(design: Path, source: Path) -> dict:
    """Synthetic local NetCDF4/HDF5 weather; no network or live forecast changes."""
    import numpy as np
    from netCDF4 import Dataset

    payload = json.loads(design.read_bytes())
    environment = payload["environment"]
    with Dataset(source, "w", format="NETCDF4") as dataset:
        for name, values in (
            ("time", [0, 6]),
            ("lev", [1000, 800, 300, 50]),
            ("lat", [environment["latitude"] - 0.25, environment["latitude"] + 0.25]),
            ("lon", [environment["longitude"] - 0.25, environment["longitude"] + 0.25]),
        ):
            dataset.createDimension(name, len(values))
            coordinate = dataset.createVariable(name, "f8", (name,))
            coordinate[:] = values
        dataset.variables["time"].units = "hours since 2025-01-01 00:00:00"
        dataset.variables["lev"].units = "hPa"
        for name, values in (
            ("hgtprs", [0, 2000, 9000, 20000]),
            ("tmpprs", [288, 275, 230, 220]),
            ("ugrdprs", [5, 5, 5, 5]),
            ("vgrdprs", [2, 2, 2, 2]),
        ):
            variable = dataset.createVariable(
                name, "f8", ("time", "lev", "lat", "lon"), zlib=True
            )
            variable[:] = np.asarray(values)[None, :, None, None]
    environment.update(
        atmosphere_type="forecast",
        atmosphere_file=str(source),
        atmosphere_dictionary={
            "time": "time",
            "latitude": "lat",
            "longitude": "lon",
            "level": "lev",
            "temperature": "tmpprs",
            "geopotential_height": "hgtprs",
            "geopotential": None,
            "surface_geopotential_height": None,
            "u_wind": "ugrdprs",
            "v_wind": "vgrdprs",
        },
        pressure_conversion_factor="hPa",
        date=[2025, 1, 1, 0],
    )
    return payload


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
        # Import through the public CLI, then read compressed HDF5 in a frozen
        # worker. An import-only check can miss broken native I/O dependencies.
        source = directory / "forecast.nc"
        weather = forecast_design(design, source)
        imported = run("--data", "--data-dir", data, "import-file", source)
        weather["environment"]["atmosphere_file"] = str(
            data / "inputs" / imported["path"]
        )
        forecast = directory / "forecast.json"
        forecast.write_text(json.dumps(weather), encoding="utf-8")
        weather_flight = run("--simulate", forecast, "--design", "--data-dir", data)
        assert weather_flight["summary"]["landed"]
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
        checks = "preview, spawned flights, compressed NetCDF4 weather, history, saved designs, OpenRocket import, CSV export"
        if sys.platform == "linux":
            checks += ", Linux cancellation/reaping"
        print(f"Bundle verified: {checks}.")


if __name__ == "__main__":
    main()
