"""Desktop entry point; keep the GUI loop on the main thread."""

import argparse
import logging
import sys
from multiprocessing import freeze_support
from pathlib import Path

from app.config import default_data_directory, frontend_entrypoint
from app.desktop_runtime import (
    attach_ui_check,
    encode_webview_url,
    log_webview_document,
    prepare_desktop_runtime,
)
from app.logging import application_logging
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
    parser.add_argument(
        "--check-ui",
        nargs=3,
        type=Path,
        metavar=("DESIGN", "SCRIPT", "REPORT"),
        help="Run a trusted UI acceptance script with a local design, report, and close",
    )
    args = parser.parse_args()
    initial_design = None
    check_script = None
    check_result = None
    if args.check_ui:
        if args.data_dir.resolve() == default_data_directory().resolve():
            parser.error("--check-ui requires a separate --data-dir.")
        from app.design_files import validate_design_file
        from app.storage import MAX_PAYLOAD_BYTES

        design, script, report = args.check_ui
        try:
            if report.exists() or report.is_symlink():
                raise FileExistsError("UI-check report already exists.")
            with design.open("rb") as stream:
                initial_design = validate_design_file(
                    stream.read(MAX_PAYLOAD_BYTES + 1)
                )
            with script.open("rb") as stream:
                payload = stream.read(MAX_PAYLOAD_BYTES + 1)
            if len(payload) > MAX_PAYLOAD_BYTES:
                raise ValueError("UI-check script exceeds 2 MiB.")
            check_script = payload.decode("utf-8")
            if not check_script.strip():
                raise ValueError("UI-check script is empty.")
        except (OSError, ValueError, UnicodeError) as error:
            parser.error(str(error))
    try:
        with application_logging(args.data_dir, "desktop"):
            entry = frontend_entrypoint(dev_url=args.dev_url, frontend=args.frontend)
            # Delay GUI imports so --help and input checks also work without a display.
            if not ensure_windows_runtime():
                return
            prepare_desktop_runtime()

            import webview

            from app.bridge import DesktopBridge
            from app.simulation.jobs import JobManager

            jobs = JobManager(
                args.data_dir,
                max_workers=args.workers,
                max_pending=args.queue_size,
                timeout_seconds=args.job_timeout,
                memory_limit_mb=(
                    args.memory_limit_mb if args.memory_limit_mb != 0 else None
                ),
            )
            try:
                window = webview.create_window(
                    "UARC",
                    url=entry,
                    js_api=DesktopBridge(jobs, initial_design=initial_design),
                    width=1280,
                    height=800,
                )
                window.events.initialized += encode_webview_url
                if logging.getLogger("pywebview").isEnabledFor(logging.DEBUG):
                    window.events.loaded += log_webview_document
                if check_script is not None:
                    check_result = attach_ui_check(
                        window, check_script, args.check_ui[2]
                    )
                renderer = {"linux": "qt", "win32": "edgechromium"}.get(sys.platform)
                webview.start(gui=renderer)
                logging.getLogger(__name__).info("Native webview event loop stopped")
            finally:
                jobs.close()
            if check_result is not None and check_result.get("ok") is not True:
                logging.getLogger(__name__).error(
                    "UI acceptance failed: %s", check_result
                )
                parser.exit(1, f"UI acceptance failed: {check_result}\n")
    except (ValueError, OSError, RuntimeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
