"""Keep incompatible GDAL/netCDF wheel libraries separate without needing a Mac."""

import os
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BUILD = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/build_desktop.py")
)


class MacOSBundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / "UARC"
        self.bundle.mkdir()
        self.specs = {}
        self.imports = {}
        self.sources = []
        for package in ("netCDF4", "rasterio"):
            source = self.root / "installed" / package
            library = source / ".dylibs/libhdf5.310.dylib"
            library.parent.mkdir(parents=True)
            extension = source / "_native.so"
            for path in (library, extension):
                path.write_bytes(f"{package}: original {path.name}".encode())
                self.sources.append(path)
            self.specs[package] = SimpleNamespace(origin=str(source / "__init__.py"))
            self.imports[str(extension)] = [
                ("@loader_path/.dylibs/libhdf5.310.dylib", str(library))
            ]
            self.imports[str(library)] = [("/usr/lib/libSystem.B.dylib", None)]
        dependencies = SimpleNamespace(
            get_imports=lambda path: self.imports.get(path, [])
        )
        patches = (
            patch("importlib.util.find_spec", side_effect=self.specs.get),
            patch.dict("sys.modules", {"PyInstaller.depend.bindepend": dependencies}),
            patch("subprocess.run", return_value=SimpleNamespace(returncode=0)),
        )
        for patcher in patches:
            mock = patcher.start()
            self.addCleanup(patcher.stop)
        self.sign = mock

    def test_extensions_and_same_named_dylibs_keep_their_own_originals(self):
        common = self.bundle / "_internal/libhdf5.310.dylib"
        common.parent.mkdir()
        common.write_bytes(b"the conflicting collected library")
        alias = self.bundle / "_internal/netCDF4/.dylibs/libhdf5.310.dylib"
        alias.parent.mkdir(parents=True)
        if os.name == "nt":
            alias.write_bytes(b"the conflicting collected library")
        else:
            alias.symlink_to(common)

        BUILD["preserve_macos_wheel_libraries"](self.bundle)

        for source in self.sources:
            target = (
                self.bundle / "_internal" / source.relative_to(self.root / "installed")
            )
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertFalse(target.is_symlink())
        self.assertEqual(common.read_bytes(), b"the conflicting collected library")
        self.assertEqual(self.sign.call_count, len(self.sources))
        for call in self.sign.call_args_list:
            self.assertEqual(
                call.args[0][:5],
                ["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none"],
            )

    def test_external_or_missing_dependencies_fail_before_replacing_files(self):
        extension = self.sources[-1]
        for dependency in (None, "/opt/homebrew/lib/libhdf5.310.dylib"):
            with self.subTest(dependency=dependency):
                self.imports[str(extension)] = [
                    ("@rpath/libhdf5.310.dylib", dependency)
                ]
                with self.assertRaisesRegex(RuntimeError, "non-private dependency"):
                    BUILD["preserve_macos_wheel_libraries"](self.bundle)
                self.assertFalse((self.bundle / "_internal").exists())
                self.sign.assert_not_called()

    @unittest.skipIf(
        os.name == "nt", "Unix library symlinks need no Windows privileges"
    )
    def test_destination_parent_cannot_redirect_writes_outside_the_bundle(self):
        outside = self.root / "keep"
        outside.mkdir()
        (self.bundle / "_internal").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "escapes the bundle"):
            BUILD["preserve_macos_wheel_libraries"](self.bundle)
        self.assertEqual(list(outside.iterdir()), [])
        self.sign.assert_not_called()

    def test_signing_failure_stops_the_build(self):
        self.sign.return_value = SimpleNamespace(returncode=1, stderr="signing failed")
        with self.assertRaisesRegex(RuntimeError, "signing failed"):
            BUILD["preserve_macos_wheel_libraries"](self.bundle)


if __name__ == "__main__":
    unittest.main()
