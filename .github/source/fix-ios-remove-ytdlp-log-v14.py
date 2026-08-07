from pathlib import Path

ROOT = Path('MPVTorBox')
SERVICE = ROOT / 'YTDLPService.swift'
ADVANCED = ROOT / 'AdvancedSettingsView.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label} anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# The runtime is now stable, so stop creating the user-visible yt-dlp.log.
# Keep the old helper name so all existing debug call sites remain harmless and
# do not risk touching the working extraction/playback code.
replace_once(
    SERVICE,
    '''    private func appendNativeLog(_ message: String) {
        let url = visibleLogURL()
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let line = "[\\(ISO8601DateFormatter().string(from: Date()))] [Swift] \\(message)\\n"
        guard let data = line.data(using: .utf8) else { return }
        if FileManager.default.fileExists(atPath: url.path),
           let handle = try? FileHandle(forWritingTo: url) {
            defer { try? handle.close() }
            try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        } else {
            try? data.write(to: url, options: .atomic)
        }
    }
''',
    '''    private func appendNativeLog(_ message: String) {
        // Intentionally disabled. Retaining this no-op keeps the proven runtime
        // path unchanged while avoiding persistent diagnostic files.
        _ = message
    }
''',
    'disable Swift yt-dlp file logger',
)

# Stop exporting YTDLP_LOG_PATH. The patched YoutubeDL-iOS bridge checks this
# variable before attaching either its Swift logger or yt-dlp's Python logger,
# so unsetting it disables both without changing extraction behavior.
replace_once(
    SERVICE,
    '''        let logURL = visibleLogURL()
        try fileManager.createDirectory(at: applicationSupport, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: configHome, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: webKitPluginDirectoryURL(), withIntermediateDirectories: true)
        try fileManager.createDirectory(at: cache, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)

        setenv("HOME", applicationSupport.path, 1)
        setenv("XDG_CONFIG_HOME", configHome.path, 1)
        setenv("XDG_CACHE_HOME", cache.path, 1)
        setenv("TMPDIR", NSTemporaryDirectory(), 1)
        setenv("YTDLP_LOG_PATH", logURL.path, 1)
        setenv("OPENSSL_CONF", "/dev/null", 1)
        setenv("PYTHONUNBUFFERED", "1", 1)
''',
    '''        let logURL = visibleLogURL()
        try fileManager.createDirectory(at: applicationSupport, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: configHome, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: webKitPluginDirectoryURL(), withIntermediateDirectories: true)
        try fileManager.createDirectory(at: cache, withIntermediateDirectories: true)

        // Remove diagnostics left by older builds and make sure the bridge does
        // not attach its optional file logger in this process.
        unsetenv("YTDLP_LOG_PATH")
        try? fileManager.removeItem(at: logURL)

        setenv("HOME", applicationSupport.path, 1)
        setenv("XDG_CONFIG_HOME", configHome.path, 1)
        setenv("XDG_CACHE_HOME", cache.path, 1)
        setenv("TMPDIR", NSTemporaryDirectory(), 1)
        setenv("OPENSSL_CONF", "/dev/null", 1)
        setenv("PYTHONUNBUFFERED", "1", 1)
''',
    'remove YTDLP_LOG_PATH export',
)

# Remove obsolete diagnostics UI/help text. These are intentionally tolerant
# because wording changed across earlier runtime patches.
text = ADVANCED.read_text()
text = text.replace('                    LabeledContent("Diagnostic log", value: "Files → MPV → Logs → yt-dlp.log")\n', '')
text = text.replace(
    'Website URLs now enter MPV through an iOS-native ytdl hook. The hook reads ytdl-format directly from MPVConfig/mpv.conf, then uses the embedded Python + yt-dlp + Apple WebKit JSI runtime without launching an external executable. Detailed checkpoints are saved in Files → On My iPhone → MPV → Logs → yt-dlp.log.',
    'Website URLs enter MPV through an iOS-native ytdl hook. The hook reads ytdl-format directly from MPVConfig/mpv.conf, then uses the embedded Python + yt-dlp + Apple WebKit JSI runtime without launching an external executable.'
)
text = text.replace(
    'The Python runtime and Apple WebKit JavaScript provider are bundled. Python initialization and WebKit challenge solving run on the iOS main run loop. Detailed extraction output is saved in Files → On My iPhone → MPV → Logs → yt-dlp.log.',
    'The Python runtime and Apple WebKit JavaScript provider are bundled. Python initialization and WebKit challenge solving run on the iOS main run loop.'
)
ADVANCED.write_text(text)

print('Disabled persistent yt-dlp.log output and cleanup of logs from older builds.')
