from pathlib import Path

ROOT = Path('MPVTorBox')


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'Expected source pattern not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1))


# 1) Save screenshots to a user-visible folder in Files instead of mpv's
# process working directory, which is not reliably exposed by iOS.
controller = ROOT / 'Player' / 'MPVMetalViewController.swift'
replace_once(
    controller,
    '''    func takeScreenshot() {
        command("screenshot", args: ["video"])
    }
''',
    '''    func takeScreenshot() -> Bool {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let directory = documents.appendingPathComponent("Screenshots", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            return false
        }

        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss-SSS"
        let file = directory.appendingPathComponent("MPV_\\(formatter.string(from: Date())).png")
        command("screenshot-to-file", args: [file.path, "video"])
        return true
    }
'''
)

bridge = ROOT / 'Player' / 'MPVMetalPlayerView.swift'
replace_once(
    bridge,
    '''        func takeScreenshot() { player?.takeScreenshot() }
''',
    '''        func takeScreenshot() -> Bool { player?.takeScreenshot() ?? false }
'''
)

player = ROOT / 'Views' / 'PlayerScreen.swift'
replace_once(
    player,
    '''                    coordinator.takeScreenshot()
                    flash("Screenshot saved")
''',
    '''                    if coordinator.takeScreenshot() {
                        flash("Saved to Files → On My iPhone → MPV → Screenshots")
                    } else {
                        flash("Could not create the Screenshots folder")
                    }
'''
)

# 2) Prepare Python/yt-dlp in writable sandbox locations and instantiate the
# bridge lazily. The package downloads the current yt-dlp module on first use;
# only the Python runtime is bundled in the IPA.
ytdlp = ROOT / 'YTDLPService.swift'
replace_once(
    ytdlp,
    '''import Foundation
import YoutubeDL
''',
    '''import Foundation
import Darwin
import YoutubeDL
'''
)
replace_once(
    ytdlp,
    '''    private let youtubeDL = YoutubeDL()
''',
    '''    private var youtubeDL: YoutubeDL?
'''
)
replace_once(
    ytdlp,
    '''        await status("Starting built-in yt-dlp…")
        let (selectedFormats, info) = try await youtubeDL.extractInfo(url: url)
''',
    '''        try prepareRuntimeDirectories()
        await status("Starting built-in yt-dlp… Preparing runtime; first use downloads the current module.")

        let bridge: YoutubeDL
        if let youtubeDL {
            bridge = youtubeDL
        } else {
            let created = YoutubeDL()
            youtubeDL = created
            bridge = created
        }

        let (selectedFormats, info) = try await bridge.extractInfo(url: url)
'''
)
replace_once(
    ytdlp,
    '''    }
}
''',
    '''    }

    private func prepareRuntimeDirectories() throws {
        let fileManager = FileManager.default
        let applicationSupport = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MPV", isDirectory: true)
        let cache = fileManager.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("yt-dlp", isDirectory: true)

        try fileManager.createDirectory(at: applicationSupport, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: cache, withIntermediateDirectories: true)

        setenv("HOME", applicationSupport.path, 1)
        setenv("XDG_CACHE_HOME", cache.path, 1)
        setenv("TMPDIR", NSTemporaryDirectory(), 1)
    }
}
'''
)

advanced = ROOT / 'AdvancedSettingsView.swift'
replace_once(
    advanced,
    '''                  footer: { Text("yt-dlp is already bundled in this IPA—nothing else is installed. Enable this switch, paste a supported website page URL on the main screen, then tap Play URL. Direct media links and magnets bypass yt-dlp.") }
''',
    '''                  footer: { Text("The Python runtime is bundled. On first use, MPV downloads the current yt-dlp module, then resolves supported website URLs locally. No manual installation is needed. Direct media links and magnets bypass yt-dlp.") }
'''
)

content = ROOT / 'ContentView.swift'
replace_once(
    content,
    '''                        Label("Built-in yt-dlp: paste a supported website URL—no installation needed", systemImage: "link")
''',
    '''                        Label("yt-dlp: first use downloads its current module automatically", systemImage: "link")
'''
)

# 3) Preserve the hand-written Info.plist. XcodeGen's `info.path` mode generates
# a new minimal plist and discards URL schemes, document types, file sharing,
# local-network text, and orientation keys.
project = Path('project.yml')
replace_once(
    project,
    '''    info:
      path: MPVTorBox/Info.plist
    settings:
      base:
''',
    '''    settings:
      base:
        INFOPLIST_FILE: MPVTorBox/Info.plist
'''
)

# 4) YoutubeDL-iOS loads Python C symbols through dlsym. Release stripping can
# remove those symbols and causes an immediate EXC_BAD_ACCESS on Py_IsInitialized.
# Preserve the symbols and compile Swift without Release-only optimization.
replace_once(
    project,
    '''        SWIFT_VERSION: 5.9
        SWIFT_STRICT_CONCURRENCY: minimal
''',
    '''        SWIFT_VERSION: 5.9
        SWIFT_STRICT_CONCURRENCY: minimal
        SWIFT_OPTIMIZATION_LEVEL: -Onone
        GCC_OPTIMIZATION_LEVEL: 0
        ENABLE_TESTABILITY: YES
        STRIP_STYLE: debugging
        STRIP_INSTALLED_PRODUCT: NO
        COPY_PHASE_STRIP: NO
        DEBUG_INFORMATION_FORMAT: dwarf
'''
)
replace_once(
    project,
    '''        INFOPLIST_KEY_UILaunchStoryboardName: LaunchScreen
''',
    '''        INFOPLIST_KEY_UILaunchStoryboardName: LaunchScreen
        INFOPLIST_KEY_UIFileSharingEnabled: YES
        INFOPLIST_KEY_LSSupportsOpeningDocumentsInPlace: YES
'''
)

print('Applied visible screenshot storage, preserved Info.plist, and yt-dlp Release crash fixes.')
