"""Portable archive/version checks without building or publishing a release."""

import hashlib
import json
import os
import runpy
import stat
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/release_desktop.py"
RELEASE = runpy.run_path(str(SCRIPT))


class DesktopReleaseTests(unittest.TestCase):
    def test_automatic_version_increments_use_numeric_releases_and_reset_lower_parts(
        self,
    ):
        for current, tags, bump, expected in (
            ("0.1.0", ["v0.1.0"], "patch", "0.1.1"),
            ("0.1.9", ["v0.1.9"], "minor", "0.2.0"),
            ("0.2.9", ["v0.2.9"], "major", "1.0.0"),
            ("0.1.0", ["v0.9.0", "v0.10.0", "other", "v2.0.0-rc.1"], "patch", "0.10.1"),
            ("0.11.0", ["v0.10.0"], "patch", "0.11.1"),
        ):
            with self.subTest(current=current, tags=tags, bump=bump):
                self.assertEqual(RELEASE["next_version"](current, tags, bump), expected)
        self.assertEqual(
            RELEASE["next_version"]("0.1.0", [], "patch", "v0.1.0"), "0.1.0"
        )
        self.assertEqual(
            RELEASE["next_version"]("0.1.0", ["v0.1.0"], "patch", "0.2.0"), "0.2.0"
        )
        for version in (
            "0.0.9",
            "0.1.0",
            "01.2.0",
            "0.2.0-rc.1",
            "--help",
            "$(whoami)",
        ):
            with self.subTest(version=version), self.assertRaises(ValueError):
                RELEASE["next_version"]("0.1.0", ["v0.1.0"], "patch", version)
        with self.assertRaises(ValueError):
            RELEASE["next_version"]("0.1.0", [], "invalid")

    def test_failed_version_update_restores_all_original_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "backend").mkdir()
            (root / "frontend").mkdir()
            originals = {
                root / "backend/pyproject.toml": b'[project]\nversion = "0.1.0"\n',
                root / "backend/uv.lock": b"original lockfile\n",
                root
                / "frontend/package.json": b'{ "version": "0.1.0", "private": true }\n',
            }
            for path, content in originals.items():
                path.write_bytes(content)

            def fail(command, **kwargs):
                if command[0] == "git":
                    return SimpleNamespace(stdout="v0.1.0\n")
                (root / "backend/pyproject.toml").write_text("partial update")
                (root / "backend/uv.lock").write_text("partial lock")
                raise subprocess.CalledProcessError(1, command, stderr="lock failed")

            with (
                patch("subprocess.run", side_effect=fail),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                RELEASE["prepare_version"]("patch", root=root)
            for path, content in originals.items():
                self.assertEqual(path.read_bytes(), content)

    def test_version_requires_matching_manifests_and_rejects_unsafe_tag_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "backend").mkdir()
            (root / "frontend").mkdir()
            (root / "backend/pyproject.toml").write_text(
                '[project]\nversion = "0.1.0"\n', encoding="utf-8"
            )
            frontend = root / "frontend/package.json"
            frontend.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
            for version in ("0.1.0", "v0.1.0"):
                self.assertEqual(RELEASE["version_tag"](version, root), "v0.1.0")
            for version in (
                "--help",
                "$(whoami)",
                "v0.1.0\nname=bad",
                "../0.1.0",
                "01.1.0",
                "0.1",
                "0.1.0-rc.1",
                "0.2.0",
            ):
                with self.subTest(version=version), self.assertRaises(ValueError):
                    RELEASE["version_tag"](version, root)
            frontend.write_text(json.dumps({"version": "0.2.0"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "match"):
                RELEASE["version_tag"]("0.1.0", root)

    def test_native_platform_and_architecture_are_not_silently_mislabelled(self):
        for system, architecture, target in (
            ("win32", "AMD64", "windows-x86_64"),
            ("linux", "x86_64", "linux-x86_64"),
            ("darwin", "arm64", "macos-arm64"),
            ("darwin", "x86_64", "macos-x86_64"),
            ("linux", "aarch64", None),
        ):
            with (
                self.subTest(system=system, architecture=architecture),
                patch("sys.platform", system),
                patch("platform.machine", return_value=architecture),
            ):
                if target:
                    self.assertEqual(RELEASE["native_target"](), target)
                else:
                    with self.assertRaises(ValueError):
                        RELEASE["native_target"]()

    def test_archives_include_frontend_and_preserve_unix_executables_and_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "UARC"
            frontend = bundle / "_internal/frontend/dist/index.html"
            frontend.parent.mkdir(parents=True)
            frontend.write_text("<title>UARC</title>", encoding="utf-8")
            executable = bundle / "UARC"
            executable.write_bytes(b"synthetic executable")
            executable.chmod(0o755)
            (bundle / "UARC.exe").write_bytes(b"synthetic Windows executable")
            link = bundle / "_internal/alias"
            if os.name != "nt":
                link.symlink_to("frontend/dist/index.html")
            for target in RELEASE["TARGETS"]:
                with self.subTest(target=target):
                    archive = RELEASE["archive_bundle"](
                        bundle, root / "output", "v0.1.0", target
                    )
                    if archive.suffix == ".zip":
                        with zipfile.ZipFile(archive) as package:
                            self.assertEqual(
                                package.read("UARC/_internal/frontend/dist/index.html"),
                                frontend.read_bytes(),
                            )
                            self.assertIn("UARC/UARC.exe", package.namelist())
                    else:
                        with tarfile.open(archive) as package:
                            entry = package.getmember("UARC/UARC")
                            if os.name != "nt":
                                self.assertTrue(entry.mode & stat.S_IXUSR)
                                self.assertTrue(
                                    package.getmember("UARC/_internal/alias").issym()
                                )
                            self.assertEqual(
                                package.extractfile(
                                    "UARC/_internal/frontend/dist/index.html"
                                ).read(),
                                frontend.read_bytes(),
                            )
                    original = archive.read_bytes()
                    with self.assertRaises(FileExistsError):
                        RELEASE["archive_bundle"](
                            bundle, root / "output", "v0.1.0", target
                        )
                    self.assertEqual(archive.read_bytes(), original)
            for name in RELEASE["python_distribution_names"]("v0.1.0"):
                (root / "output" / name).write_bytes(b"Python distribution fixture")
            manifest = RELEASE["write_checksums"](root / "output", "v0.1.0")
            for line in manifest.read_text(encoding="utf-8").splitlines():
                digest, name = line.split("  ")
                self.assertEqual(
                    digest,
                    hashlib.sha256((root / "output" / name).read_bytes()).hexdigest(),
                )

    def test_missing_desktop_assets_and_partial_release_sets_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "UARC"
            bundle.mkdir()
            (bundle / "UARC").write_bytes(b"fake launcher")
            with self.assertRaisesRegex(ValueError, "frontend"):
                RELEASE["archive_bundle"](
                    bundle, root / "output", "v0.1.0", "linux-x86_64"
                )
            output = root / "output"
            output.mkdir()
            for target, suffix in RELEASE["TARGETS"].items():
                path = output / f"UARC-v0.1.0-{target}{suffix}"
                path.write_bytes(b"archive fixture")
            for name in RELEASE["python_distribution_names"]("v0.1.0"):
                (output / name).write_bytes(b"Python distribution fixture")
            one = next(output.iterdir())
            one.write_bytes(b"")
            with self.assertRaises(ValueError):
                RELEASE["write_checksums"](output, "v0.1.0")
            one.unlink()
            with self.assertRaises(ValueError):
                RELEASE["write_checksums"](output, "v0.1.0")
            self.assertFalse((output / "SHA256SUMS.txt").exists())

    def test_failed_archive_is_removed_and_unrelated_files_are_kept(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "UARC"
            frontend = bundle / "_internal/frontend/dist/index.html"
            frontend.parent.mkdir(parents=True)
            frontend.write_text("frontend", encoding="utf-8")
            (bundle / "UARC").write_bytes(b"launcher")
            output = root / "output"
            output.mkdir()
            keep = output / "keep.txt"
            keep.write_text("preserved", encoding="utf-8")
            with (
                patch("tarfile.TarFile.add", side_effect=OSError("disk full")),
                self.assertRaises(OSError),
            ):
                RELEASE["archive_bundle"](bundle, output, "v0.1.0", "linux-x86_64")
            self.assertEqual(list(output.iterdir()), [keep])


if __name__ == "__main__":
    unittest.main()
