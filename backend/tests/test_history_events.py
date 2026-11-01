"""Committed history notifications and native-window lifecycle, without a GUI."""

import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from threading import Event
from threading import enumerate as threads
from unittest.mock import MagicMock, patch

from test_jobs import simulation_config

from app.design import compile_design
from app.desktop_runtime import attach_history_events
from app.schemas import RocketDesign
from app.storage import RunStore


class HistoryEventTests(unittest.TestCase):
    def test_only_committed_run_and_design_changes_notify(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            closing(RunStore(Path(temporary))) as store,
        ):
            self.assertFalse(store.history_changed.is_set())
            with (
                patch.object(
                    store, "_snapshot_files", side_effect=OSError("disk full")
                ),
                self.assertRaises(OSError),
            ):
                store.create(simulation_config())
            self.assertFalse(store.history_changed.is_set())
            run_id = store.create(simulation_config())
            self.assertTrue(store.history_changed.is_set())
            self.assertEqual(store.list_runs()[0]["state"], "queued")
            store.history_changed.clear()
            store.update(run_id, "failed", error="fixture")
            self.assertTrue(store.history_changed.is_set())
            self.assertEqual(store.get(run_id)["state"], "failed")
            store.history_changed.clear()
            design = RocketDesign.model_validate_json(
                (Path(__file__).parents[2] / "examples/design.json").read_bytes()
            )
            config, _ = compile_design(design)
            saved = store.save_design(design, config)
            self.assertTrue(store.history_changed.is_set())
            self.assertEqual(store.list_designs()[0], saved)

    def test_native_delivery_is_coalesced_starts_once_and_stops_on_close(self):
        window, changed, delivered = MagicMock(), Event(), Event()
        loaded, closed = window.events.loaded, window.events.closed
        window.run_js.side_effect = lambda _: delivered.set()
        stop = attach_history_events(window, changed)
        self.addCleanup(stop)
        start = loaded.__iadd__.call_args.args[0]
        close = closed.__iadd__.call_args.args[0]
        changed.set()
        changed.set()
        window.run_js.assert_not_called()
        start()
        start()
        self.assertTrue(delivered.wait(2))
        window.run_js.assert_called_once_with(
            "window.dispatchEvent(new Event('uarc:history-changed'))"
        )
        window.evaluate_js.assert_not_called()
        close()
        changed.set()
        start()
        stop()
        self.assertEqual(window.run_js.call_count, 1)
        self.assertFalse(any(thread.name == "history-notify" for thread in threads()))


if __name__ == "__main__":
    unittest.main()
