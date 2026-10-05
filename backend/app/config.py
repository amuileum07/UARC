"""Resolve the desktop UI entry point without depending on the working directory."""

from pathlib import Path
from urllib.parse import urlsplit


def frontend_entrypoint(*, dev_url: str | None = None, frontend: Path | None = None) -> str:
    if dev_url is not None:
        parsed = urlsplit(dev_url)
        if (
            parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username is not None or parsed.password is not None
        ):
            raise ValueError("The development URL must be a local HTTP server.")
        return dev_url

    entry = frontend if frontend is not None else (
        Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
    )
    entry = entry.expanduser().resolve()
    if not entry.is_file():
        raise FileNotFoundError(
            f"Frontend entry point not found: {entry}. Build the frontend first, "
            "or use --dev-url http://localhost:5173 while Vite is running."
        )
    return str(entry)
