# Autohand Computer Use distribution

This directory contains the Autohand-owned product layer around the cross-platform
computer-use engine in `libs/cua-driver`.

The engine supports macOS, Linux, and Windows. Autohand release assets are built
for the following targets:

| Operating system | Architectures | Runtime |
| --- | --- | --- |
| macOS | arm64, x64 | universal engine plus `Autohand Computer Use.app` |
| Linux | arm64, x64 | native engine and Wayland helpers |
| Windows | arm64, x64 | native engine and UI Automation helper |

The macOS host owns the stable permission identity shown in System Settings:

- product name: `Autohand Computer Use`
- bundle identifier: `ai.autohand.computer-use`

The host launches the Rust engine in embedded mode. Accessibility and Screen
Recording permission requests therefore belong to Autohand Computer Use rather
than the engine's upstream bundle identity.

## Build the macOS host

```sh
AUTOHAND_BUILD_VERSION=0.9.9-alpha.local \
  ./autohand/scripts/build-macos-host.sh
```

The build writes `autohand/dist/Autohand Computer Use.app`. Set
`AUTOHAND_CODESIGN_IDENTITY` to a Developer ID Application identity for a
production build. Local builds use ad hoc signing.

## Distribution boundary

Autohand Code pins an immutable commit from this repository during its build.
Its installers download checksum-pinned engine archives from this repository's
`computer-use-v*` component releases. A Code release and a Computer Use release
remain separate artifacts and version streams.

The upstream project remains available as the `upstream` Git remote. Keep its
MIT license and attribution when synchronizing engine changes. The Autohand host
files in this directory use the license headers present in each source file.
