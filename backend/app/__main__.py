"""Frozen and module entry point; divert spawned children before heavy imports."""

from multiprocessing import freeze_support


def main() -> None:
    freeze_support()
    import os
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in {"--simulate", "--data"}:
        os.environ["MPLBACKEND"] = "Agg"
    if len(sys.argv) > 1 and sys.argv[1] == "--simulate":
        del sys.argv[1]
        from app.simulation.__main__ import main as launch
    elif len(sys.argv) > 1 and sys.argv[1] == "--data":
        del sys.argv[1]
        from app.cli import main as launch
    else:
        from app.main import main as launch
    launch()


if __name__ == "__main__":
    main()
