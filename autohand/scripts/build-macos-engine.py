#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

NATIVE_FILES = ("cua-driver", "cua-cursor-theme", "libcua_driver_sdk.dylib", "cua_driver_node_runtime.node")
TARGETS = ("aarch64-apple-darwin", "x86_64-apple-darwin")


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def verify_source(source, expected_revision):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_revision):
        raise ValueError("The source revision must be a full commit SHA")
    actual = run("git", "-C", source, "rev-parse", "HEAD", capture_output=True, text=True).stdout.strip()
    if actual != expected_revision:
        raise ValueError("The checkout does not match the pinned source revision")
    changes = run("git", "-C", source, "status", "--porcelain", "--untracked-files=normal", capture_output=True, text=True).stdout
    if changes.strip():
        raise ValueError("The source checkout contains modified or untracked files")


def package_engine(source, native_directory, output):
    entries = {name: native_directory / name for name in NATIVE_FILES}
    entries["LICENSE-CUA.md"] = source / "LICENSE.md"
    entries["cua_driver_abi.h"] = source / "libs/cua-driver/rust/include/cua_driver_abi.h"
    if any(not path.is_file() or path.is_symlink() for path in entries.values()):
        raise ValueError("The source build is missing a regular native file, license, or ABI header")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for name, path in sorted(entries.items()):
            archive.add(path, arcname=name, recursive=False)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def build_engine(source, output, expected_revision):
    source = source.resolve()
    verify_source(source, expected_revision)
    sdk = run("xcrun", "--sdk", "macosx", "--show-sdk-version", capture_output=True, text=True).stdout.strip()
    if int(sdk.split(".")[0]) < 26:
        raise ValueError("The native engine requires the macOS 26 SDK; use the macos-26 release runner")
    driver = source / "libs/cua-driver"
    rust = driver / "rust"
    target_directory = rust / "target"
    environment = {**os.environ, "MACOSX_DEPLOYMENT_TARGET": "13.0", "CARGO_TARGET_DIR": str(target_directory)}
    for target in TARGETS:
        run("cargo", "build", "--locked", "-p", "cua-driver", "-p", "cursor-theme-cli", "-p", "cua-driver-sdk",
            "--release", "--target", target, cwd=rust, env=environment)
    run("npm", "--prefix", "typescript", "ci", "--ignore-scripts", cwd=driver)
    node_environment = {key: value for key, value in environment.items() if key != "CARGO_TARGET_DIR"}
    for target in TARGETS:
        run("node", "scripts/build-node-runtime.mjs", "--target", target,
            "--output", target_directory / target / "release/cua_driver_node_runtime.node", cwd=driver, env=node_environment)
    universal = target_directory / "autohand-universal"
    universal.mkdir(parents=True, exist_ok=True)
    for name in NATIVE_FILES:
        destination = universal / name
        run("lipo", "-create", *(target_directory / target / "release" / name for target in TARGETS), "-output", destination)
        architectures = run("lipo", "-archs", destination, capture_output=True, text=True).stdout.split()
        if set(architectures) != {"arm64", "x86_64"}:
            raise ValueError(f"Unexpected native architectures in {name}")
    sdk_library = universal / "libcua_driver_sdk.dylib"
    load_commands = run("otool", "-l", sdk_library, capture_output=True, text=True).stdout
    install_names = run("otool", "-D", sdk_library, capture_output=True, text=True).stdout.splitlines()
    if ("@rpath/libcua_driver_sdk.dylib" not in install_names
            or "path /usr/lib/swift" not in load_commands or "path @loader_path" not in load_commands
            or set(re.findall(r"\bminos\s+(\d+\.\d+)", load_commands)) != {"13.0"}):
        raise ValueError("The SDK library does not meet the macOS 13 runtime loading contract")
    digest = package_engine(source, universal, output)
    return {
        "source_commit": expected_revision,
        "sha256": digest,
        "build": {
            "rustc": run("rustc", "--version", capture_output=True, text=True).stdout.strip(),
            "macos_sdk": sdk,
            "cargo_lock_sha256": hashlib.sha256((rust / "Cargo.lock").read_bytes()).hexdigest(),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest.get("source_kind") != "git":
        raise ValueError("Source builds require a Git revision manifest")
    receipt = build_engine(args.source, args.output.resolve(), manifest["source_commit"])
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
