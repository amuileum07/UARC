"""Validate a release version and package native PyInstaller folder bundles."""

import argparse
import hashlib
import json
import platform
import re
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {
    "windows-x86_64": ".zip",
    "linux-x86_64": ".tar.gz",
    "macos-arm64": ".tar.gz",
    "macos-x86_64": ".tar.gz",
}


def version_tag(version: str, root: Path = ROOT) -> str:
    if not re.fullmatch(
        r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version
    ):
        raise ValueError("Use a version such as 0.1.0 or v0.1.0 (X.Y.Z).")
    number = version.removeprefix("v")
    backend = tomllib.loads(
        (root / "backend/pyproject.toml").read_text(encoding="utf-8")
    )
    frontend = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    if backend["project"]["version"] != number or frontend["version"] != number:
        raise ValueError(
            "Release version must match backend/pyproject.toml and frontend/package.json."
        )
    return f"v{number}"


def native_target() -> str:
    system = {"win32": "windows", "linux": "linux", "darwin": "macos"}.get(sys.platform)
    architecture = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(platform.machine().lower())
    target = f"{system}-{architecture}"
    if target not in TARGETS:
        raise ValueError(
            f"Unsupported release platform: {sys.platform}/{platform.machine()}"
        )
    return target


def archive_bundle(bundle: Path, output: Path, tag: str, target: str) -> Path:
    if target not in TARGETS or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Invalid release tag or target.")
    executable = "UARC.exe" if target.startswith("windows-") else "UARC"
    if bundle.name != "UARC" or not (bundle / executable).is_file():
        raise ValueError(
            "Expected a complete PyInstaller UARC folder with its launcher."
        )
    if not (bundle / "_internal/frontend/dist/index.html").is_file():
        raise ValueError("The desktop frontend is missing from the bundle.")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"UARC-{tag}-{target}{TARGETS[target]}"
    stream = destination.open("xb")  # Refuse to replace an existing release asset.
    try:
        with stream:
            if target.startswith("windows-"):
                with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(bundle.rglob("*")):
                        archive.write(path, path.relative_to(bundle.parent))
            else:
                # Tar preserves PyInstaller's Unix symlinks and executable bits.
                with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                    archive.add(bundle, arcname="UARC")
    except BaseException:
        destination.unlink(missing_ok=True)  # Remove only the asset we just created.
        raise
    return destination


def python_distribution_names(tag: str) -> set[str]:
    number = tag.removeprefix("v")
    return {
        f"uarc_simulator-{number}-py3-none-any.whl",
        f"uarc_simulator-{number}.tar.gz",
    }


def write_checksums(output: Path, tag: str) -> Path:
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Invalid release tag.")
    expected = {f"UARC-{tag}-{target}{suffix}" for target, suffix in TARGETS.items()}
    expected.update(python_distribution_names(tag))
    actual = {path.name for path in output.iterdir()}
    if actual != expected or any(
        not (output / name).is_file()
        or (output / name).is_symlink()
        or (output / name).stat().st_size == 0
        for name in expected
    ):
        raise ValueError(
            "Publication requires four native archives, one wheel and one sdist, all nonempty."
        )
    lines = []
    for name in sorted(expected):
        with (output / name).open("rb") as stream:
            lines.append(
                f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {name}\n"
            )
    destination = output / "SHA256SUMS.txt"
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.writelines(lines)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate").add_argument("version")
    archive = commands.add_parser("archive")
    archive.add_argument("version")
    archive.add_argument("--target", choices=TARGETS, required=True)
    archive.add_argument("--bundle", type=Path, default=ROOT / "dist/desktop/UARC")
    archive.add_argument("--output", type=Path, default=ROOT / "dist/release")
    checksums = commands.add_parser("checksums")
    checksums.add_argument("version")
    checksums.add_argument("--output", type=Path, default=ROOT / "dist/release")
    args = parser.parse_args()
    try:
        tag = version_tag(args.version)
        if args.command == "validate":
            print(tag)
        elif args.command == "archive":
            if args.target != native_target():
                raise ValueError(
                    "Build and package the release on its target OS/architecture."
                )
            print(archive_bundle(args.bundle, args.output, tag, args.target))
        else:
            print(write_checksums(args.output, tag))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
