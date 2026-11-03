import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[2]


class MacOSEngineBuildTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("engine_build", ROOT / "autohand/scripts/build-macos-engine.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def seed(self):
        source = self.root / "source"
        native = self.root / "native"
        native.mkdir()
        header = source / "libs/cua-driver/rust/include/cua_driver_abi.h"
        header.parent.mkdir(parents=True)
        header.write_text("fixture ABI")
        (source / "LICENSE.md").write_text("fixture license")
        for name in self.module.NATIVE_FILES:
            (native / name).write_bytes(name.encode())
        return source, native

    def test_source_archive_matches_the_signing_and_installer_contract(self):
        source, native = self.seed()
        output = self.root / "input.tar.gz"
        digest = self.module.package_engine(source, native, output)
        self.assertEqual(digest, hashlib.sha256(output.read_bytes()).hexdigest())
        with tarfile.open(output) as archive:
            self.assertEqual(set(archive.getnames()), set(self.module.NATIVE_FILES) | {"LICENSE-CUA.md", "cua_driver_abi.h"})
            self.assertTrue(all(entry.isfile() for entry in archive.getmembers()))
            self.assertEqual(archive.extractfile("LICENSE-CUA.md").read(), b"fixture license")

    def test_archive_rejects_missing_or_linked_native_payloads(self):
        source, native = self.seed()
        driver = native / "cua-driver"
        driver.unlink()
        with self.assertRaisesRegex(ValueError, "regular native file"):
            self.module.package_engine(source, native, self.root / "missing.tar.gz")
        driver.symlink_to(source / "LICENSE.md")
        with self.assertRaisesRegex(ValueError, "regular native file"):
            self.module.package_engine(source, native, self.root / "linked.tar.gz")

    def test_source_pin_rejects_wrong_or_modified_checkouts(self):
        with patch.object(self.module, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="a" * 40 + "\n")
            with self.assertRaisesRegex(ValueError, "pinned source revision"):
                self.module.verify_source(self.root, "b" * 40)
            run.side_effect = [run.return_value, subprocess.CalledProcessError(1, "git diff")]
            with self.assertRaises(subprocess.CalledProcessError):
                self.module.verify_source(self.root, "a" * 40)

    def test_rejects_an_older_sdk_before_any_compilation(self):
        with patch.object(self.module, "verify_source"), patch.object(self.module, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="15.5\n")
            with self.assertRaisesRegex(ValueError, "macOS 26 SDK"):
                self.module.build_engine(self.root, self.root / "input.tar.gz", "a" * 40)
            self.assertEqual(run.call_count, 1)

    def test_source_pin_rejects_untracked_build_inputs(self):
        with patch.object(self.module, "run") as run:
            run.side_effect = [
                subprocess.CompletedProcess([], 0, stdout="a" * 40 + "\n"),
                subprocess.CompletedProcess([], 0, stdout="?? .cargo/config.toml\n"),
            ]
            with self.assertRaisesRegex(ValueError, "modified or untracked"):
                self.module.verify_source(self.root, "a" * 40)

    def test_builds_both_architectures_without_overriding_the_node_runtime_target_directory(self):
        source, _ = self.seed()
        (source / "libs/cua-driver/rust/Cargo.lock").write_text("fixture lockfile")
        output = self.root / "input.tar.gz"

        def command(*args, **kwargs):
            stdout = ""
            if args[0] == "xcrun":
                stdout = "26.0\n"
            elif args[:2] == ("lipo", "-create"):
                Path(args[-1]).write_bytes(b"universal fixture")
            elif args[:2] == ("lipo", "-archs"):
                stdout = "arm64 x86_64\n"
            elif args[:2] == ("otool", "-l"):
                stdout = "path /usr/lib/swift\npath @loader_path\nminos 13.0\n"
            elif args[:2] == ("otool", "-D"):
                stdout = "@rpath/libcua_driver_sdk.dylib\n"
            elif args[0] == "rustc":
                stdout = "rustc fixture\n"
            return subprocess.CompletedProcess(args, 0, stdout=stdout)

        with patch.dict(os.environ, {"PATH": "fixture"}, clear=True), patch.object(self.module, "verify_source"), patch.object(self.module, "run", side_effect=command) as run:
            receipt = self.module.build_engine(source, output, "a" * 40)
        self.assertEqual(receipt["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
        builds = [call for call in run.call_args_list if call.args[:2] == ("cargo", "build")]
        self.assertEqual({call.args[-1] for call in builds}, set(self.module.TARGETS))
        node_builds = [call for call in run.call_args_list if call.args[0] == "node"]
        self.assertEqual(len(node_builds), 2)
        for call in node_builds:
            self.assertFalse("CARGO_TARGET_DIR" in call.kwargs["env"], "Node runtime must use its own Cargo target directory")

    def test_release_checks_out_and_builds_source_before_importing_signing_keys(self):
        workflow = (ROOT / ".github/workflows/release-autohand-computer-use.yml").read_text()
        self.assertIn("ref: ${{ steps.engine.outputs.sha }}", workflow)
        self.assertIn("--build-receipt engine-build.json", workflow)
        self.assertLess(workflow.index("build-macos-engine.py"), workflow.index("import-apple-signing.sh"))
        self.assertNotIn("Download the pinned engine input", workflow)


if __name__ == "__main__":
    unittest.main()
