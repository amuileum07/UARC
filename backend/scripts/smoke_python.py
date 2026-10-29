"""Verify wheel installation/commands/spawn and rebuild its sdist offline."""

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

_PROBE = """
import json
import sys
from importlib.metadata import distribution
from pathlib import Path
import numpy as np
from netCDF4 import Dataset
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
import app
from app.bridge import DesktopBridge
from app.config import bundled_file, frontend_entrypoint
from app.schemas import launch_time

target = Path(sys.argv[1]).resolve()
assert Path(app.__file__).resolve().is_relative_to(target), app.__file__
dist = distribution('uarc-simulator')
assert Path(dist.locate_file('app')).resolve().is_relative_to(target)
commands = {entry.name: entry.value for entry in dist.entry_points}
assert commands['uarc'] == 'app.__main__:main'
assert commands['uarc-data'] == 'app.cli:main'
frontend = Path(frontend_entrypoint())
assert frontend.is_relative_to(target) and frontend.is_file()
design = bundled_file('examples/design.json')
assert design.is_relative_to(target) and design.is_file()
assert DesktopBridge().get_example_design()['components']
assert DesktopBridge().get_material_catalog()['materials']
if sys.platform == 'darwin':
    import AppKit
    import Foundation
    import WebKit
assert launch_time((2025, 1, 1, 0), 'UTC').isoformat() == '2025-01-01T00:00:00+00:00'
assert launch_time((2025, 1, 1, 9), 'Asia/Seoul').isoformat() == '2025-01-01T00:00:00+00:00'
# Exercise both native stacks in one process, including GDAL's data/PROJ lookup.
with MemoryFile() as memory:
    with memory.open(driver='GTiff', width=2, height=2, count=1, dtype='float64',
                     crs='EPSG:4326', transform=from_origin(129, 36, 0.01, 0.01)) as raster:
        raster.write(np.full((1, 2, 2), 123.0))
    with memory.open() as raster:
        assert raster.crs.to_epsg() == 4326
        assert np.all(raster.read(1) == 123.0)
with Dataset(target.parent / 'probe.nc', 'w', format='NETCDF4') as dataset:
    dataset.createDimension('level', 2)
    dataset.createVariable('height', 'f8', ('level',), zlib=True)[:] = [0, 100]
with Dataset(target.parent / 'probe.nc') as dataset:
    assert list(dataset['height'][:]) == [0, 100]
print(json.dumps({'design': str(design)}))
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Resolve wheel dependencies online in a new isolated virtual environment",
    )
    parser.add_argument(
        "--gui", action="store_true", help="Also open the installed desktop"
    )
    args = parser.parse_args()
    if args.gui and not args.fresh:
        parser.error("--gui requires --fresh so the installed launcher is isolated.")
    wheels, sources = (
        list(args.directory.glob("*.whl")),
        list(args.directory.glob("*.tar.gz")),
    )
    if len(wheels) != 1 or len(sources) != 1:
        parser.error("Expected one wheel and one sdist.")
    wheel, source = wheels[0].resolve(strict=True), sources[0].resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="uarc-python-smoke-") as temporary:
        root = Path(temporary)
        target = root / "installed"
        python = Path(sys.executable)
        environment = dict(
            os.environ,
            PYTHONPATH=str(target),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONTZPATH="",
            MPLBACKEND="Agg",
        )
        environment.pop("PYTHONHOME", None)
        if args.fresh:
            subprocess.run(
                ["uv", "venv", "--python", str(python), str(target)],
                cwd=root,
                env=environment,
                check=True,
            )
            python = target / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            installation = [
                "--python",
                str(python),
                "--only-binary",
                "rasterio",
                "--only-binary",
                "netcdf4",
            ]
        else:
            # Offline asset checks reuse installed dependencies. --fresh checks
            # dependency resolution without source/system site-packages masking it.
            installation = ["--offline", "--no-deps", "--target", str(target)]
        subprocess.run(
            ["uv", "pip", "install", *installation, str(wheel)],
            cwd=root,
            env=environment,
            check=True,
        )

        def run(*arguments):
            result = subprocess.run(
                [str(python), *map(str, arguments)],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
            )
            if result.returncode:
                raise RuntimeError(
                    f"Installed package command failed: {arguments}\n{result.stderr}"
                )
            return result.stdout

        details = json.loads(run("-c", _PROBE, target))
        run("-m", "app", "--help")
        run("-c", "from app.cli import main; main()", "--help")
        flight = json.loads(
            run(
                "-m",
                "app",
                "--simulate",
                details["design"],
                "--design",
                "--data-dir",
                root / "data",
            )
        )
        assert flight["summary"]["landed"]
        history = json.loads(
            run("-m", "app", "--data", "--data-dir", root / "data", "list-runs")
        )
        assert history[0]["state"] == "succeeded"
        if args.gui:
            launcher = target / ("Scripts/uarc.exe" if os.name == "nt" else "bin/uarc")
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("smoke_gui.py")),
                    str(launcher),
                ],
                env=environment,
                check=True,
                timeout=90,
            )
        unpacked = root / "sdist"
        with tarfile.open(source) as archive:
            archive.extractall(unpacked, filter="data")
        source_tree = unpacked / source.name.removesuffix(".tar.gz")
        rebuilt = root / "rebuilt"
        subprocess.run(
            [
                "uv",
                "build",
                "--wheel",
                "--offline",
                "--no-sources",
                "--out-dir",
                str(rebuilt),
            ],
            cwd=source_tree,
            check=True,
        )
        with (
            zipfile.ZipFile(wheel) as original,
            zipfile.ZipFile(next(rebuilt.glob("*.whl"))) as restored,
        ):
            assert set(original.namelist()) == set(restored.namelist())
            for name in original.namelist():
                assert original.read(name) == restored.read(name), name
    print(
        "Python distribution verified: installed assets/commands, GDAL/NetCDF4 I/O, spawned flight/history, offline sdist rebuild."
    )


if __name__ == "__main__":
    main()
