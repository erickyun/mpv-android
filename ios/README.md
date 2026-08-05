# MPV TorBox for iOS

Native SwiftUI iPhone/iPad player using MPVKit.

## Features

- Opens `magnet:` and `torrs://` links.
- TorBox provider with an API key stored in the iOS Keychain.
- TorrServer fallback with a configurable local or remote server address.
- Direct HTTP/HTTPS media URL playback.
- MPVKit/libmpv playback with VideoToolbox hardware decoding.
- English interface.
- GitHub Actions unsigned IPA release.

## Build locally

1. Install Xcode and XcodeGen.
2. Run:

```bash
cd ios
xcodegen generate
xcodebuild \
  -project MPVTorBox.xcodeproj \
  -scheme MPVTorBox \
  -configuration Release \
  -sdk iphoneos \
  -destination 'generic/platform=iOS' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

## Installing the IPA

The GitHub release contains an **unsigned IPA**. AltStore, SideStore, Sideloadly,
TrollStore, or another signing method must sign it before installation.

For normal Apple installation or TestFlight, archive the project with your Apple
Developer Team and provisioning profile.
