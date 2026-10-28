"""Stage desktop assets temporarily, then build a self-contained wheel and sdist."""

import argparse
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build_distributions(root: Path, output: Path) -> None:
    if not (root / "frontend/dist/index.html").is_file():
        raise ValueError(
            "Build frontend/dist before packaging the Python distribution."
        )
    if (root / "LICENSE").read_bytes() != (root / "backend/LICENSE").read_bytes():
        raise ValueError("Keep backend/LICENSE identical to the repository LICENSE.")
    assets = root / "backend/app/_assets"
    if assets.exists() or assets.is_symlink():
        raise FileExistsError(
            "The generated app/_assets directory already exists; refusing to replace it."
        )
    if output.exists() and (any(output.glob("*.whl")) or any(output.glob("*.tar.gz"))):
        raise FileExistsError(
            "Python distributions already exist in the output directory."
        )
    assets.mkdir()
    try:
        for relative in ("frontend/dist", "examples", "Licenses", "docs"):
            shutil.copytree(root / relative, assets / relative)
        subprocess.run(
            ["uv", "build", "--no-sources", "--out-dir", str(output.resolve())],
            cwd=root / "backend",
            check=True,
        )
    finally:
        shutil.rmtree(assets)  # Only this invocation's generated assets are removed.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/python")
    args = parser.parse_args()
    try:
        build_distributions(ROOT, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
