"""Build a PyInstaller folder bundle; frontend assets must already be built."""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def preserve_macos_wheel_libraries(bundle: Path) -> None:
    """Keep the wheels' private dylib paths and IDs instead of merging basenames."""
    from PyInstaller.depend.bindepend import get_imports

    copies = []
    for package in ("netCDF4", "rasterio"):
        spec = importlib.util.find_spec(package)
        if spec is None or spec.origin is None:
            raise RuntimeError(f"Cannot locate {package} for the macOS bundle.")
        source = Path(spec.origin).parent
        binaries = sorted(
            path for path in source.rglob("*") if path.suffix in {".so", ".dylib"}
        )
        if not (source / ".dylibs").is_dir() or not binaries:
            raise RuntimeError(
                f"macOS builds require a self-contained {package} wheel."
            )
        private = {path.resolve() for path in binaries}
        for path in binaries:
            # Restoring unmodified wheel binaries is safe only when their complete
            # non-system dependency closure lives in the same package. Reject
            # source/Homebrew builds; support those with explicit relocation later.
            for name, resolved in get_imports(str(path)):
                if name.startswith(("/usr/lib/", "/System/Library/")):
                    continue
                if resolved is None or Path(resolved).resolve() not in private:
                    raise RuntimeError(
                        f"{package} has a non-private dependency: {path.name}: {name}"
                    )
            target = bundle / "_internal" / package / path.relative_to(source)
            if not target.parent.resolve().is_relative_to(bundle.resolve()):
                raise ValueError("macOS library destination escapes the bundle.")
            copies.append((path, target))

    # PyInstaller rewrites these wheels' @loader_path references and distinct
    # /DLC/<package>/... IDs to shared @rpath basenames. Restore BOTH extensions
    # and dylibs after collection, so GDAL and netCDF each retain their own HDF5.
    for source, target in copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)  # Never follow a collected library symlink.
        shutil.copy2(source, target)
        result = subprocess.run(
            [
                "/usr/bin/codesign",
                "--force",
                "--sign",
                "-",
                "--timestamp=none",
                str(target),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(f"Cannot sign {target}: {result.stderr}")


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
        # zoneinfo loads its IANA fallback dynamically; its hook collects all zones.
        "--hidden-import",
        "tzdata",
        "--copy-metadata",
        "tzdata",
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
    if frontend is None or sys.platform != "win32":
        arguments.extend(["--exclude-module", "tkinter"])
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
        elif sys.platform == "darwin":
            arguments.extend(["--hidden-import", "webview.platforms.cocoa"])
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
        if not args.headless and sys.platform == "win32":
            try:
                import tkinter

                tkinter.Tcl()  # Validate Tcl resources before freezing the setup UI.
            except (ImportError, RuntimeError) as error:
                raise RuntimeError(
                    "Windows desktop builds need Python with Tcl/Tk support. "
                    "Enable Tcl/Tk in the Python installer, then rebuild."
                ) from error
            except tkinter.TclError as error:
                raise RuntimeError(
                    "Cannot initialize Tcl/Tk for Windows setup."
                ) from error
        import PyInstaller.__main__

        if args.headless:
            os.environ["MPLBACKEND"] = "Agg"
        PyInstaller.__main__.run(arguments)
        if sys.platform == "darwin":
            preserve_macos_wheel_libraries(args.output.resolve() / "UARC")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
