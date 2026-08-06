from pathlib import Path

ROOT = Path('MPVTorBox')
PROJECT = Path('project.yml')


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'Expected pattern not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1))


ytdlp = ROOT / 'YTDLPService.swift'
replace_once(
    ytdlp,
    '''        await status("Starting the local Python, yt-dlp, and WebKit JSI runtime…")
        let bridge = getBridge()
        await status("Solving the website URL with yt-dlp…")
        let result: ([Format], Info) = try await runWithTimeout(seconds: 25) {
            try await bridge.extractInfo(url: url)
        }
        let selectedFormats = result.0
        let info = result.1
''',
    '''        await status("Starting local Python and yt-dlp on the iOS main run loop…")
        let bridge = getBridge()
        appendNativeLog("Starting extraction: \\(url.absoluteString)")
        await status("Solving the website URL with yt-dlp and Apple WebKit…")

        let result: ([Format], Info)
        do {
            result = try await bridge.extractInfo(url: url)
            appendNativeLog("Extraction completed successfully")
        } catch {
            appendNativeLog("Extraction failed: \\(String(reflecting: error))")
            throw error
        }
        let selectedFormats = result.0
        let info = result.1
'''
)

replace_once(
    ytdlp,
    '''    private func runtimeRootURL() -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MPV", isDirectory: true)
    }
''',
    '''    private func visibleLogURL() -> URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MPV", isDirectory: true)
            .appendingPathComponent("Logs", isDirectory: true)
            .appendingPathComponent("yt-dlp.log")
    }

    private func appendNativeLog(_ message: String) {
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

    private func runtimeRootURL() -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MPV", isDirectory: true)
    }
'''
)

replace_once(
    ytdlp,
    '''        try fileManager.createDirectory(at: applicationSupport, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: configHome, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: webKitPluginDirectoryURL(), withIntermediateDirectories: true)
        try fileManager.createDirectory(at: cache, withIntermediateDirectories: true)

        setenv("HOME", applicationSupport.path, 1)
        setenv("XDG_CONFIG_HOME", configHome.path, 1)
        setenv("XDG_CACHE_HOME", cache.path, 1)
        setenv("TMPDIR", NSTemporaryDirectory(), 1)
''',
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
'''
)

advanced = ROOT / 'AdvancedSettingsView.swift'
text = advanced.read_text()
anchor = '                    LabeledContent("YouTube JS provider", value: "Apple WebKit JSI 0.1.1")\n'
if anchor not in text:
    raise SystemExit('Advanced yt-dlp provider row was not found')
text = text.replace(
    anchor,
    anchor + '                    LabeledContent("Diagnostic log", value: "Files → MPV → Logs → yt-dlp.log")\n',
    1,
)
text = text.replace(
    'The Python runtime and Apple WebKit JavaScript provider are bundled. The first use downloads yt-dlp automatically. YouTube challenge solving uses the on-device WebKit engine.',
    'The Python runtime and Apple WebKit JavaScript provider are bundled. Python initialization and WebKit challenge solving run on the iOS main run loop. Detailed extraction output is saved in Files → On My iPhone → MPV → Logs → yt-dlp.log.',
    1,
)
advanced.write_text(text)

project_text = PROJECT.read_text()
project_text = project_text.replace('        MARKETING_VERSION: 1.6.0\n', '        MARKETING_VERSION: 1.7.0\n', 1)
project_text = project_text.replace('        CURRENT_PROJECT_VERSION: 16\n', '        CURRENT_PROJECT_VERSION: 17\n', 1)
PROJECT.write_text(project_text)

print('Applied main-run-loop yt-dlp execution, real error reporting, and visible diagnostics log.')
