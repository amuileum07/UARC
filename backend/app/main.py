"""Desktop entry point; keep the GUI loop on the main thread."""

import argparse
from multiprocessing import freeze_support
from pathlib import Path
import sys

from app.bridge import DesktopBridge
from app.config import frontend_entrypoint


def main() -> None:
    freeze_support()
    parser = argparse.ArgumentParser(description="Launch the UARC desktop window.")
    ui = parser.add_mutually_exclusive_group()
    ui.add_argument("--dev-url", help="Local Vite URL, e.g. http://localhost:5173")
    ui.add_argument("--frontend", type=Path, help="Path to a built frontend index.html")
    args = parser.parse_args()
    try:
        entry = frontend_entrypoint(dev_url=args.dev_url, frontend=args.frontend)
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))

    # Delay GUI imports so --help and input checks also work without a display.
    import webview

    webview.create_window("UARC", url=entry, js_api=DesktopBridge(), width=1280, height=800)
    webview.start(gui="qt" if sys.platform == "linux" else None)


if __name__ == "__main__":
    main()
