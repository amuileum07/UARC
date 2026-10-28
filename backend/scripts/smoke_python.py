"""Verify installed wheel assets/commands/spawn and rebuild its sdist offline."""

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
import app
from app.bridge import DesktopBridge
from app.config import bundled_file, frontend_entrypoint

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
print(json.dumps({'design': str(design)}))
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
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
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--target",
                str(target),
                str(wheel),
            ],
            check=True,
        )
        # Reuse installed numerical dependencies, but put the wheel FIRST and
        # assert its origin. No cwd/source import may mask missing wheel files.
        environment = dict(
            os.environ,
            PYTHONPATH=str(target),
            PYTHONDONTWRITEBYTECODE="1",
            MPLBACKEND="Agg",
        )
        environment.pop("PYTHONHOME", None)

        def run(*arguments):
            result = subprocess.run(
                [sys.executable, *map(str, arguments)],
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
        "Python distribution verified: installed assets/commands, spawned flight/history, offline sdist rebuild."
    )


if __name__ == "__main__":
    main()
