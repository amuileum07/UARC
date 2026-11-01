"""Native startup capture and descriptor recovery in isolated processes."""

import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class NativeOutputTests(unittest.TestCase):
    def test_startup_rotation_and_cached_console_handlers_stop_writing_the_log(self):
        code = """
import faulthandler
import os
import sys
from pathlib import Path
from app.native_output import desktop_native_output
root = Path(sys.argv[1])
if sys.argv[2] == 'consoleless':
    sys.stdout = sys.stderr = None
    os.close(1)
    os.close(2)
for index in range(5):
    with desktop_native_output(root) as restore:
        cached = sys.stderr
        print(f'Python startup marker {index}')
        os.write(2, b'native startup marker\\n')
        restore()
        restore()
        assert faulthandler.is_enabled()
        cached.write('runtime-only marker\\n')
        cached.flush()
        if sys.argv[2] == 'consoleless':
            assert sys.stdout is None and sys.stderr is None
assert not faulthandler.is_enabled()
"""
        with tempfile.TemporaryDirectory() as temporary:
            for mode in ("console", "consoleless"):
                with self.subTest(mode=mode):
                    root = Path(temporary) / mode
                    result = subprocess.run(
                        [sys.executable, "-B", "-c", code, str(root), mode],
                        capture_output=True,
                        encoding="utf-8",
                        timeout=20,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    files = list(root.glob("native.log*"))
                    self.assertEqual(len(files), 4)
                    for path in files:
                        content = path.read_text(encoding="utf-8")
                        self.assertIn("native startup marker", content)
                        self.assertNotIn("runtime-only marker", content)
                    self.assertIn(
                        "Python startup marker 4", (root / "native.log").read_text()
                    )
                    if mode == "console":
                        self.assertEqual(result.stderr.count("runtime-only marker"), 5)

    @unittest.skipIf(
        os.name == "nt", "Requires a POSIX fatal signal without a crash dialog"
    )
    def test_fatal_trace_keeps_its_file_after_console_restore(self):
        code = """
import os, resource, sys
from pathlib import Path
from app.native_output import desktop_native_output
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
with desktop_native_output(Path(sys.argv[1])) as restore:
    restore()
    os.write(2, b'after-load console marker\\n')
    os.abort()
"""
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, "-B", "-c", code, temporary],
                capture_output=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, -signal.SIGABRT)
            content = (Path(temporary) / "native.log").read_text(encoding="utf-8")
            self.assertIn("Fatal Python error", content)
            self.assertNotIn("after-load console marker", content)
            self.assertIn(b"after-load console marker", result.stderr)

    @unittest.skipIf(
        os.name == "nt", "Requires a POSIX fatal signal without a crash dialog"
    )
    def test_gui_initialization_abort_preserves_native_message_and_python_trace(self):
        code = """
import os
import resource
import sys
from unittest.mock import patch
from app.main import main
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
def fail():
    os.write(2, b'native GUI initialization failed marker\\n')
    os.abort()
with patch('app.main.ensure_windows_runtime', return_value=True), \\
     patch('app.main.prepare_desktop_runtime', side_effect=fail):
    sys.argv = ['uarc', '--dev-url', 'http://localhost:5173', '--data-dir', sys.argv[1]]
    main()
"""
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, "-B", "-c", code, temporary],
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, -signal.SIGABRT, result.stderr)
            content = (Path(temporary) / "native.log").read_text(encoding="utf-8")
            self.assertIn("native GUI initialization failed marker", content)
            self.assertIn("Fatal Python error", content)
            self.assertIn("fail", content)
            self.assertNotIn(b"native GUI initialization failed marker", result.stderr)


if __name__ == "__main__":
    unittest.main()
