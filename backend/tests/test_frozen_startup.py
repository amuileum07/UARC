"""Frozen entry dispatch must not launch system-font discovery subprocesses."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.__main__ import main


class FrozenStartupTests(unittest.TestCase):
    def test_font_policy_precedes_spawn_dispatch_and_respects_explicit_settings(self):
        for frozen, original, expected in (
            (True, None, "1"),
            (True, "", ""),
            (False, None, None),
        ):
            environment = (
                {} if original is None else {"MPL_IGNORE_SYSTEM_FONTS": original}
            )

            def dispatch(expected=expected):
                self.assertEqual(os.environ.get("MPL_IGNORE_SYSTEM_FONTS"), expected)
                raise SystemExit(0)

            with (
                self.subTest(frozen=frozen, original=original),
                patch("sys.frozen", frozen, create=True),
                patch.dict(os.environ, environment, clear=True),
                patch("app.__main__.freeze_support", side_effect=dispatch),
                self.assertRaises(SystemExit),
            ):
                main()

    def test_cold_matplotlib_import_uses_bundled_fonts_without_system_commands(self):
        code = """
import sys
from pathlib import Path
from unittest.mock import patch
from app.__main__ import main
sys.frozen = True
def dispatch():
    with patch('subprocess.check_output', side_effect=AssertionError('System font scan')):
        import matplotlib.font_manager as fonts
        assert fonts.fontManager.ttflist
        assert Path(fonts.findfont('DejaVu Sans')).is_file()
    raise SystemExit(0)
with patch('app.__main__.freeze_support', side_effect=dispatch):
    main()
"""
        with tempfile.TemporaryDirectory() as temporary:
            environment = dict(os.environ, MPLCONFIGDIR=temporary, MPLBACKEND="Agg")
            environment.pop("MPL_IGNORE_SYSTEM_FONTS", None)
            result = subprocess.run(
                [sys.executable, "-B", "-c", code],
                cwd=temporary,
                env=environment,
                capture_output=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(list(Path(temporary).glob("fontlist-*.json")))


if __name__ == "__main__":
    unittest.main()
