"""Desktop entry point; keep the GUI loop on the main thread."""

import argparse
import logging
import sys
from multiprocessing import freeze_support
from pathlib import Path

from app.config import default_data_directory, frontend_entrypoint
from app.desktop_runtime import (
    encode_webview_url,
    log_webview_document,
    prepare_desktop_runtime,
)
from app.windows_runtime import ensure_windows_runtime


def main() -> None:
    freeze_support()
    parser = argparse.ArgumentParser(description="Launch the UARC desktop window.")
    ui = parser.add_mutually_exclusive_group()
    ui.add_argument("--dev-url", help="Local Vite URL, e.g. http://localhost:5173")
    ui.add_argument("--frontend", type=Path, help="Path to a built frontend index.html")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_directory(),
        help="Directory for run history, input snapshots, and results",
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="Maximum simultaneous simulations"
    )
    parser.add_argument(
        "--queue-size", type=int, default=8, help="Additional pending run capacity"
    )
    parser.add_argument(
        "--job-timeout",
        type=float,
        default=300,
        help="Wall-clock seconds per worker, including startup and saving",
    )
    parser.add_argument(
        "--memory-limit-mb",
        type=int,
        default=1024 if sys.platform == "linux" else None,
        help="Per-worker RSS limit on Linux (MiB; 0 disables)",
    )
    args = parser.parse_args()
    try:
        entry = frontend_entrypoint(dev_url=args.dev_url, frontend=args.frontend)
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))

    # Delay GUI imports so --help and input checks also work without a display.
    try:
        if not ensure_windows_runtime():
            return
        prepare_desktop_runtime()
    except RuntimeError as error:
        parser.error(str(error))

    import webview

    from app.bridge import DesktopBridge
    from app.simulation.jobs import JobManager

    try:
        jobs = JobManager(
            args.data_dir,
            max_workers=args.workers,
            max_pending=args.queue_size,
            timeout_seconds=args.job_timeout,
            memory_limit_mb=args.memory_limit_mb if args.memory_limit_mb != 0 else None,
        )
    except (ValueError, OSError, RuntimeError) as error:
        parser.error(str(error))
    try:
        window = webview.create_window(
            "UARC", url=entry, js_api=DesktopBridge(jobs), width=1280, height=800
        )
        window.events.initialized += encode_webview_url
        if logging.getLogger("pywebview").isEnabledFor(logging.DEBUG):
            window.events.loaded += log_webview_document
        renderer = {"linux": "qt", "win32": "edgechromium"}.get(sys.platform)
        webview.start(gui=renderer)
    finally:
        jobs.close()


if __name__ == "__main__":
    main()
