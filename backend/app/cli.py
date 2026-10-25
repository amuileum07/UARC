"""File and history operations available before the graphical editor exists."""

import argparse
import json
from pathlib import Path

from app.config import default_data_directory
from app.schemas import OpenRocketOptions, RocketDesign, TelemetryQuery
from app.simulation.jobs import JobManager
from app.storage import MAX_PAYLOAD_BYTES, atomic_json


def read_payload(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_PAYLOAD_BYTES + 1)
    if len(data) > MAX_PAYLOAD_BYTES:
        raise ValueError("JSON file exceeds the 2 MiB limit.")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage UARC designs, input files, and results."
    )
    parser.add_argument("--data-dir", type=Path, default=default_data_directory())
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("list-runs", "list-designs"):
        command = commands.add_parser(name)
        command.add_argument("--limit", type=int, default=50)
        command.add_argument("--offset", type=int, default=0)
    for name in ("show-run", "summary", "load-design"):
        command = commands.add_parser(name)
        command.add_argument("id")
        command.add_argument("--output", type=Path)
    command = commands.add_parser("telemetry")
    command.add_argument("id")
    command.add_argument("--query", default="{}", help="TelemetryQuery JSON")
    command.add_argument("--output", type=Path)
    command = commands.add_parser("save-design")
    command.add_argument("source", type=Path)
    command = commands.add_parser("import-file")
    command.add_argument("source", type=Path)
    command = commands.add_parser("import-ork")
    command.add_argument("source", type=Path)
    command.add_argument("--options", required=True, type=Path)
    command.add_argument(
        "--output",
        type=Path,
        help="Save only the editable design; warnings go to stderr",
    )
    command = commands.add_parser("export-csv")
    command.add_argument("id")
    command.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        # These commands use the same single-owner data store as the desktop host.
        with JobManager(args.data_dir) as manager:
            match args.command:
                case "list-runs":
                    result = manager.list_runs(args.limit, args.offset)
                case "list-designs":
                    result = manager.list_designs(args.limit, args.offset)
                case "show-run":
                    result = manager.get_run(args.id)
                case "summary":
                    result = manager.get_summary(args.id)
                case "load-design":
                    result = manager.get_saved_design(args.id)
                case "telemetry":
                    if len(args.query.encode("utf-8")) > MAX_PAYLOAD_BYTES:
                        raise ValueError("Telemetry query exceeds 2 MiB.")
                    result = manager.get_telemetry(
                        args.id, TelemetryQuery.model_validate_json(args.query)
                    )
                case "save-design":
                    result = manager.save_design(
                        RocketDesign.model_validate_json(read_payload(args.source))
                    )
                case "import-file":
                    result = manager.import_file(args.source)
                case "import-ork":
                    options = OpenRocketOptions.model_validate_json(
                        read_payload(args.options)
                    )
                    imported = manager.import_file(args.source)
                    result = manager.import_openrocket(imported["path"], options)
                    if args.output is not None:
                        import sys

                        for warning in result["warnings"]:
                            print(warning, file=sys.stderr)
                        result = result["design"]
                case "export-csv":
                    result = {
                        "path": str(manager.export_csv(args.id, args.destination))
                    }
            output = getattr(args, "output", None)
            if output is None:
                print(json.dumps(result, ensure_ascii=False, allow_nan=False))
            else:
                atomic_json(output, result, overwrite=False)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
