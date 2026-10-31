"""Verify a final desktop archive, the shipping UI, normal exit, and persistence."""

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from uuid import uuid4

from smoke_gui import launch_desktop, stop_desktop

UI_TIMEOUT_SECONDS = 180


def extract_archive(archive: Path, destination: Path) -> Path:
    """Extract into a new directory; reject paths outside the application folder."""
    destination.mkdir(exist_ok=False)

    def check_name(name: str):
        path = PurePosixPath(name.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or path.parts[:1] != ("UARC",):
            raise ValueError(f"Unsafe archive path: {name}")

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                check_name(member.filename)
                if member.external_attr >> 16 & 0o170000 == 0o120000:
                    raise ValueError("ZIP symlinks are not supported.")
            source.extractall(destination)
    elif archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as source:
            for member in source.getmembers():
                check_name(member.name)
            # Keep PyInstaller's internal Unix links and permissions. The data
            # filter rejects external link targets, devices, and path escapes.
            source.extractall(destination, filter="data")
    else:
        raise ValueError("Expected a desktop .zip or .tar.gz archive.")
    bundle = destination / "UARC"
    executable = bundle / ("UARC.exe" if sys.platform == "win32" else "UARC")
    for path in (executable, bundle / "_internal/frontend/dist/index.html"):
        if not path.is_file() or not path.resolve().is_relative_to(bundle.resolve()):
            raise ValueError(f"Missing or external application file: {path}")
    return executable


def local_design(bundle: Path) -> dict:
    """Use the shipped example with a small local grid, without online services."""
    design = json.loads((bundle / "_internal/examples/design.json").read_bytes())
    design["environment"].update(
        latitude=0,
        longitude=0,
        elevation=120,
        elevation_mode="terrain",
        elevation_reference="ellipsoid",
        geoid_undulation_m=0,
        terrain_mode="terrain",
        terrain={
            "south": -0.05,
            "north": 0.05,
            "west": -0.05,
            "east": 0.05,
            "heights": [[120, 120], [120, 120]],
            "reference": "ellipsoid",
            "provider": "local",
            "source": "Local CI terrain fixture",
            "source_resolution_m": 1000,
            "sampling_distance_m": 1000,
        },
    )
    return design


def run_ui(executable: Path, output: Path, scenario: dict) -> dict:
    phase = scenario["phase"]
    script = output / f"{phase}.js"
    report = output / f"{phase}.json"
    source = (
        Path(__file__)
        .with_name(
            {
                "graphics": "probe_webgl.js",
                "diagnostics": "diagnostics_check.js",
            }.get(phase, "desktop_check.js")
        )
        .read_text(encoding="utf-8")
    )
    script.write_text(
        source.replace("/* SCENARIO */ {}", json.dumps(scenario)), encoding="utf-8"
    )
    environment = dict(
        os.environ,
        PYTHONPATH="",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        PYTHONUNBUFFERED="1",
        PYWEBVIEW_LOG="DEBUG",
    )
    environment.pop("PYTHONHOME", None)
    command = [
        str(executable),
        "--data-dir",
        str(
            output
            / (
                f"{phase}-data"
                if phase in {"graphics", "diagnostics"}
                else "사용자 데이터"
            )
        ),
        "--check-ui",
        str(output / "design.json"),
        str(script),
        str(report),
    ]
    if phase == "graphics":
        page = output / "graphics.html"
        page.write_text(
            '<!doctype html><meta charset="utf-8"><title>Native WebGL check</title>',
            encoding="utf-8",
        )
        command.extend(["--frontend", str(page)])
    with (output / f"{phase}.log").open("w", encoding="utf-8") as log:
        # Windows CI's parent stdout can be cp1252 even when the child is UTF-8.
        print(f"Desktop UI: {phase}, launcher={str(executable)!a}", flush=True)
        process = launch_desktop(
            command,
            output,
            environment,
            log,
        )
        try:
            code = process.wait(timeout=UI_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            # Forced cleanup is always a failure, never evidence of normal exit.
            stop_desktop(process)
            raise RuntimeError(
                f"{phase}: GUI did not close normally; see {log.name}"
            ) from error
    value = json.loads(report.read_bytes()) if report.is_file() else {}
    if code != 0 or value.get("ok") is not True or value.get("phase") != phase:
        details = (output / f"{phase}.log").read_text(
            encoding="utf-8", errors="replace"
        )
        raise RuntimeError(f"{phase}: exit={code}, report={value}\n{details[-12000:]}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "archive", type=Path, help="Archive or folder containing one archive"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New diagnostics directory"
    )
    args = parser.parse_args()
    archive = args.archive.resolve(strict=True)
    if archive.is_dir():
        archives = [*archive.glob("*.zip"), *archive.glob("*.tar.gz")]
        if len(archives) != 1:
            parser.error("Pass exactly one native desktop archive.")
        archive = archives[0]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="UARC 설치 한글 ") as temporary:
        executable = extract_archive(archive, Path(temporary) / "압축 해제 폴더")
        with (output / "bundle.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("smoke_bundle.py")),
                    str(executable),
                    "--output",
                    str(output / "bundle-checks"),
                ],
                stdout=log,
                stderr=log,
                check=True,
                timeout=600,
            )
        design = local_design(executable.parent)
        (output / "design.json").write_text(json.dumps(design), encoding="utf-8")
        run_ui(executable, output, {"phase": "graphics"})
        run_ui(executable, output, {"phase": "diagnostics"})
        diagnostics = (output / "diagnostics-data/uarc.log").read_text(encoding="utf-8")
        for marker in (
            "UARC diagnostic probe window",
            "UARC diagnostic probe rejection",
            "WebGL context lost",
            "Bridge failed method=validate_config",
            "Application started component=desktop",
            "Application stopped component=desktop",
        ):
            if marker not in diagnostics:
                raise RuntimeError(
                    f"Missing persisted frontend/IPC diagnostic: {marker}"
                )
        name = f"CI 한글 설계 {uuid4().hex[:12]}"
        first = run_ui(executable, output, {"phase": "first", "name": name})
        reopened = run_ui(
            executable,
            output,
            {"phase": "reopen", "name": name, "run_id": first["run_id"]},
        )
        if (
            first["run_id"] != reopened["run_id"]
            or first["summary"] != reopened["summary"]
        ):
            raise RuntimeError("Reopened result differs from the original simulation.")
        data = output / "사용자 데이터"
        log = (data / "uarc.log").read_text(encoding="utf-8")
        if log.count("Application stopped component=desktop") < 2:
            raise RuntimeError("Application log did not survive normal relaunch.")
        solver = (data / "runs" / first["run_id"] / "solver.log").read_text(
            encoding="utf-8"
        )
        if "Worker started" not in solver or "Worker succeeded" not in solver:
            raise RuntimeError(
                "Successful simulation has no durable solver diagnostics."
            )
    print(
        "Desktop archive verified: relocated CLI, actual UI, 3D, normal exit, persisted design/result and diagnostics."
    )


if __name__ == "__main__":
    main()
