"""Build a PyInstaller folder bundle; frontend assets must already be built."""

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


def build_arguments(root: Path, frontend: Path | None, output: Path) -> list[str]:
    if frontend is not None and not (frontend / "index.html").is_file():
        raise ValueError("Build the frontend first, then pass its dist directory.")
    if (output / "UARC").exists():
        raise FileExistsError(
            "The UARC output directory exists; choose a new --output directory."
        )
    arguments = [
        "--noconfirm",
        "--onedir",
        "--name",
        "UARC",
        "--distpath",
        str(output),
        "--workpath",
        str(output / "work"),
        "--specpath",
        str(output / "spec"),
        "--paths",
        str(root),
        "--collect-data",
        "rocketpy",
        "--add-data",
        f"{root / 'app' / 'materials.json'}:app",
        # SciPy's vendored NumPy namespace imports fft/linalg dynamically.
        "--collect-submodules",
        "scipy._external.array_api_compat.numpy",
        "--copy-metadata",
        "rocketpy",
        "--copy-metadata",
        "numpy",
        "--copy-metadata",
        "scipy",
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "PyQt5",
        "--exclude-module",
        "PyQt6",
        "--exclude-module",
        "PySide2",
        "--add-data",
        f"{root.parent / 'Licenses'}:Licenses",
        "--add-data",
        f"{root.parent / 'LICENSE'}:.",
        "--add-data",
        f"{root.parent / 'examples'}:examples",
        "--add-data",
        f"{root.parent / 'docs'}:docs",
    ]
    if frontend is None:
        arguments.extend(
            [
                "--exclude-module",
                "webview",
                "--exclude-module",
                "PySide6",
                "--exclude-module",
                "shiboken6",
            ]
        )
    else:
        arguments.extend(
            ["--add-data", f"{frontend}:frontend/dist", "--collect-data", "webview"]
        )
        if sys.platform == "linux":
            arguments.extend(["--hidden-import", "webview.platforms.qt"])
        elif sys.platform == "win32":
            arguments.extend(["--hidden-import", "webview.platforms.edgechromium"])
    arguments.append(str(root / "app" / "__main__.py"))
    return arguments


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Build backend-only --simulate/--data commands",
    )
    parser.add_argument(
        "--frontend", type=Path, default=root.parent / "frontend" / "dist"
    )
    parser.add_argument("--output", type=Path, default=root.parent / "dist" / "desktop")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print and validate the build plan without building",
    )
    args = parser.parse_args()
    try:
        arguments = build_arguments(
            root,
            None if args.headless else args.frontend.resolve(),
            args.output.resolve(),
        )
        if args.check:
            print(
                json.dumps(
                    {
                        "pyinstaller_available": importlib.util.find_spec("PyInstaller")
                        is not None,
                        "arguments": arguments,
                    }
                )
            )
            return
        if importlib.util.find_spec("PyInstaller") is None:
            raise RuntimeError(
                "Install the build tool with: uv run --with 'pyinstaller==6.14.2' python scripts/build_desktop.py (plus your build options)."
            )
        import PyInstaller.__main__

        if args.headless:
            os.environ["MPLBACKEND"] = "Agg"
        PyInstaller.__main__.run(arguments)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
