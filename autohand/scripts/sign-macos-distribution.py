#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENGINE_ENTRIES = {
    "LICENSE-CUA.md", "cua-driver", "cua-cursor-theme", "cua_driver_abi.h",
    "cua_driver_node_runtime.node", "libcua_driver_sdk.dylib",
}
NATIVE_ENTRIES = ENGINE_ENTRIES - {"LICENSE-CUA.md", "cua_driver_abi.h"}
METADATA_ENTRIES = {"._."} | {"._" + name for name in ENGINE_ENTRIES}


def validate_engine_archive(path, expected_sha256):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("Engine archive checksum does not match the pinned source")
    with tarfile.open(path, "r:gz") as archive:
        entries = [entry for entry in archive.getmembers() if entry.name not in (".", "./")]
        if any(not entry.isfile() for entry in entries):
            raise ValueError("Engine archive must contain only regular files")
        entries = [entry for entry in entries if entry.name.removeprefix("./") not in METADATA_ENTRIES]
        if {entry.name.removeprefix("./") for entry in entries} != ENGINE_ENTRIES or len(entries) != len(ENGINE_ENTRIES):
            raise ValueError("Engine archive entries do not match the runtime contract")


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def sign(path, identifier, entitlements=None):
    args = ["codesign", "--force", "--timestamp", "--options", "runtime",
            "--sign", os.environ["AUTOHAND_CODESIGN_IDENTITY"], "--identifier", identifier]
    if os.environ.get("AUTOHAND_CODESIGN_KEYCHAIN"):
        args += ["--keychain", os.environ["AUTOHAND_CODESIGN_KEYCHAIN"]]
    if entitlements:
        args += ["--entitlements", str(entitlements)]
    run(*args, path)
    verify(path)


def verify(path):
    run("codesign", "--verify", "--deep", "--strict", path)
    result = run("codesign", "-dv", "--verbose=4", path, capture_output=True, text=True)
    if f"TeamIdentifier={os.environ['APPLE_TEAM_ID']}" not in result.stderr:
        raise ValueError(f"Unexpected signing team for {path}")
    if "Authority=Developer ID Application:" not in result.stderr:
        raise ValueError(f"Developer ID Application signature is missing from {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "macos-engine.json").read_text())
    validate_engine_archive(args.engine_archive, manifest["sha256"])
    required = ["AUTOHAND_CODESIGN_IDENTITY", "APPLE_TEAM_ID", "APPLE_API_KEY_PATH", "APPLE_API_KEY_ID", "APPLE_API_ISSUER"]
    if any(not os.environ.get(name) for name in required):
        raise ValueError("Developer ID and notarization API credentials are required")
    if not os.environ["AUTOHAND_CODESIGN_IDENTITY"].startswith("Developer ID Application:"):
        raise ValueError("Distribution requires Developer ID Application signing")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="autohand-notarize-") as temporary:
        stage = Path(temporary)
        engine = stage / "engine"
        engine.mkdir()
        with tarfile.open(args.engine_archive, "r:gz") as archive:
            for entry in archive.getmembers():
                if entry.name.removeprefix("./") in ENGINE_ENTRIES:
                    archive.extract(entry, engine, filter="data")
        for name in sorted(NATIVE_ENTRIES):
            entitlements = ROOT.parent / "libs/cua-driver/rust/scripts/CuaDriver.entitlements" if name == "cua-driver" else None
            sign(engine / name, "ai.autohand.computer-use." + name.replace("_", "-"), entitlements)
        app = stage / "Autohand Computer Use.app"
        run("bash", ROOT / "scripts/build-macos-host.sh", "--output", app, "--version", manifest["version"], "--arch", "universal")
        verify(app)
        submission = output / "notarization-input.zip"
        run("ditto", "-c", "-k", "--keepParent", stage, submission)
        result = run("xcrun", "notarytool", "submit", submission,
                     "--key", os.environ["APPLE_API_KEY_PATH"], "--key-id", os.environ["APPLE_API_KEY_ID"],
                     "--issuer", os.environ["APPLE_API_ISSUER"], "--wait", "--timeout", "20m", "--output-format", "json",
                     capture_output=True, text=True)
        receipt = json.loads(result.stdout)
        (output / "notarization.json").write_text(json.dumps(receipt, indent=2) + "\n")
        if receipt.get("status") != "Accepted":
            raise ValueError(f"Apple did not accept submission {receipt.get('id')}")
        run("xcrun", "stapler", "staple", app)
        run("xcrun", "stapler", "validate", app)
        run("spctl", "--assess", "--type", "execute", "--verbose=2", app)
        for name in sorted(NATIVE_ENTRIES):
            verify(engine / name)
        engine_archive = output / manifest["asset"]
        with tarfile.open(engine_archive, "w:gz") as archive:
            for name in sorted(ENGINE_ENTRIES):
                archive.add(engine / name, arcname=name)
        host_archive = output / "autohand-computer-use-darwin-universal.tar.gz"
        run("tar", "-czf", host_archive, "-C", stage, app.name)
        checksums = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (engine_archive, host_archive)}
        provenance = {**manifest, "signing_team": os.environ["APPLE_TEAM_ID"], "notarization_id": receipt["id"], "artifacts": checksums}
        (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        (output / "checksums.txt").write_text("".join(f"{digest}  {name}\n" for name, digest in checksums.items()))
        shutil.copytree(app, output / app.name, dirs_exist_ok=True)
        print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
