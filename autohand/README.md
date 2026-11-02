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

Pass `--arch universal` to build both Apple Silicon and Intel slices. Every
slice targets macOS 13 independently of the build runner's OS version.

## Apple distribution

The Autohand macOS release uses `release-autohand-computer-use.yml`, separate
from the upstream Cua release workflow. Upstream's `com.trycua.driver` profile
and pinned Cua signing team are not Autohand's distribution identity.

Configure `CSC_LINK` (base64 Developer ID Application P12), `CSC_KEY_PASSWORD`,
`APPLE_TEAM_ID`, `APPLE_API_KEY` (raw App Store Connect P8), `APPLE_API_KEY_ID`,
and `APPLE_API_ISSUER`. The importer derives the signing identity from the
certificate and verifies its team. Missing credentials stop the release.

`macos-engine.json` pins the original engine archive and its digest. The signing
script verifies that input, signs every native executable and library, builds
the universal permission host, and submits the complete distribution to Apple.
It staples the host and requires Gatekeeper acceptance before packaging.
`provenance.json`, `notarization.json`, and `checksums.txt` bind the output
archives to the Apple submission and original engine revision.

The signed `computer-use-v*-autohand.*` revision is immutable. Linux and Windows
continue using the original engine release. Increment the revision for another
signed distribution; never replace an asset behind an existing checksum pin.
The workflow defaults to artifact verification without publication.

## Distribution boundary

Autohand Code pins an immutable commit from this repository during its build.
Its installers download checksum-pinned engine archives from this repository's
`computer-use-v*` component releases. A Code release and a Computer Use release
remain separate artifacts and version streams.

The upstream project remains available as the `upstream` Git remote. Keep its
MIT license and attribution when synchronizing engine changes. The Autohand host
files in this directory use the license headers present in each source file.
