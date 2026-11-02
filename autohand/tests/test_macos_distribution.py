import hashlib
import importlib.util
import io
import pathlib
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import os

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts/sign-macos-distribution.py"


class MacOSDistributionTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("distribution", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def archive(self, names):
        path = pathlib.Path(self.directory.name) / "engine.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name in names:
                entry = tarfile.TarInfo(name)
                entry.size = 7
                archive.addfile(entry, io.BytesIO(b"fixture"))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_accepts_the_exact_engine_contract(self):
        path, digest = self.archive(self.module.ENGINE_ENTRIES)
        self.module.validate_engine_archive(path, digest)

    def test_accepts_appledouble_metadata_without_installing_it(self):
        path, digest = self.archive(self.module.ENGINE_ENTRIES | {"._."} | {"._" + name for name in self.module.ENGINE_ENTRIES})
        self.module.validate_engine_archive(path, digest)

    def test_rejects_a_changed_archive(self):
        path, _ = self.archive(self.module.ENGINE_ENTRIES)
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.module.validate_engine_archive(path, "0" * 64)

    def test_checks_live_notarization_only_after_apple_acceptance(self):
        with patch.dict(os.environ, {"APPLE_TEAM_ID": "TESTTEAM"}), patch.object(self.module, "run") as run:
            run.return_value = SimpleNamespace(stderr="TeamIdentifier=TESTTEAM\nAuthority=Developer ID Application: Fixture")
            self.module.verify(pathlib.Path("native-tool"), notarized=True)
            self.assertIn("--check-notarization", run.call_args_list[0].args)
            self.assertIn("-R=notarized", run.call_args_list[0].args)
            run.reset_mock()
            self.module.verify(pathlib.Path("native-tool"))
            self.assertNotIn("--check-notarization", run.call_args_list[0].args)

    def test_rejects_unexpected_or_missing_native_code(self):
        for names in [self.module.ENGINE_ENTRIES | {"extra.dylib"}, self.module.ENGINE_ENTRIES - {"cua_driver_node_runtime.node"}]:
            with self.subTest(names=names):
                path, digest = self.archive(names)
                with self.assertRaisesRegex(ValueError, "entries"):
                    self.module.validate_engine_archive(path, digest)

    def test_rejects_paths_that_escape_the_archive(self):
        path, digest = self.archive(self.module.ENGINE_ENTRIES | {"../outside"})
        with self.assertRaisesRegex(ValueError, "entries"):
            self.module.validate_engine_archive(path, digest)

    def test_rejects_a_symlink_disguised_as_an_engine(self):
        path, _ = self.archive(self.module.ENGINE_ENTRIES)
        with tarfile.open(path, "w:gz") as archive:
            for name in self.module.ENGINE_ENTRIES:
                entry = tarfile.TarInfo(name)
                entry.type = tarfile.SYMTYPE
                entry.linkname = "/outside"
                archive.addfile(entry)
        with self.assertRaisesRegex(ValueError, "regular"):
            self.module.validate_engine_archive(path, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
