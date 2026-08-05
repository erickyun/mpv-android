# MPV TorBox for iOS

Native SwiftUI iPhone/iPad player using MPVKit and local yt-dlp extraction.

## Features

- Opens `magnet:` and `torrs://` links.
- Resolves YouTube and other supported web URLs locally with yt-dlp.
- Downloads the current yt-dlp Python module on first use.
- TorBox provider with an API key stored in the iOS Keychain.
- TorrServer fallback with a configurable local or remote server address.
- Direct HTTP/HTTPS media URL playback.
- MPVKit/libmpv playback with VideoToolbox hardware decoding.
- English interface.
- GitHub Actions unsigned IPA release.

## Requirements

- iOS 16 or newer.
- Internet access on first yt-dlp use so the Python module can be installed.

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

This sideload-oriented build is not intended for App Store submission because it
includes local yt-dlp extraction.
