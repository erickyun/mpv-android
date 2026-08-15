from pathlib import Path

ROOT = Path('MPVTorBox')
SERVICE = ROOT / 'YTDLPService.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))

# v14 intentionally turned the native logger into a no-op. Re-enable it, but
# only when YTDLP_LOG_PATH has already been opted into for the current request.
replace_once(
    SERVICE,
    '''    private func appendNativeLog(_ message: String) {
        // Intentionally disabled. Retaining this no-op keeps the proven runtime
        // path unchanged while avoiding persistent diagnostic files.
        _ = message
    }
''',
    '''    private func appendNativeLog(_ message: String) {
        guard let rawPath = getenv("YTDLP_LOG_PATH") else { return }
        let url = URL(fileURLWithPath: String(cString: rawPath))
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let stamp = ISO8601DateFormatter().string(from: Date())
        let line = "[\\(stamp)] [Native] \\(message)\\n"
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

    private func rawOptionTruthy(_ value: String?) -> Bool {
        guard let value else { return false }
        switch value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "1", "yes", "true", "on", "enable", "enabled": return true
        default: return false
        }
    }

    private func prepareEarlyYTDLPLog(rawOptions: [String: String], url: URL) {
        let enabled = rawOptionTruthy(rawOptions["mpv-ios-ytdl-log"])
            || rawOptionTruthy(rawOptions["mpv-ios-logs"])
        guard enabled else {
            unsetenv("YTDLP_LOG_PATH")
            return
        }

        guard let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            return
        }
        let logURL = documents
            .appendingPathComponent("Logs", isDirectory: true)
            .appendingPathComponent("yt-dlp.log")
        try? FileManager.default.createDirectory(
            at: logURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try? FileManager.default.removeItem(at: logURL)
        setenv("YTDLP_LOG_PATH", logURL.path, 1)
        appendNativeLog("resolver entered; host=\\(url.host ?? "unknown"); raw-option-keys=\\(rawOptions.keys.sorted().joined(separator: ","))")
    }
''',
    'restore conditional native logger',
)

# This anchor is before YoutubeDL is recreated / Python extraction begins. Set
# up the breadcrumb file here so even PythonSupport.initialize/plugin crashes
# leave a visible file behind.
replace_once(
    SERVICE,
    '''        setenv("MPV_YTDL_FORMAT", effectiveSelector, 1)
        defer { unsetenv("MPV_YTDL_FORMAT") }

        let effectiveRawOptions = normalizedRawOptions(rawOptions)
''',
    '''        prepareEarlyYTDLPLog(rawOptions: rawOptions, url: url)
        appendNativeLog("format selector prepared: \\(effectiveSelector)")

        setenv("MPV_YTDL_FORMAT", effectiveSelector, 1)
        defer { unsetenv("MPV_YTDL_FORMAT") }

        let effectiveRawOptions = normalizedRawOptions(rawOptions)
''',
    'prepare early log before Python',
)

# Add breadcrumbs immediately around the extraction result boundary. The bridge
# itself logs Python initialization/import/plugin/selector stages once the path
# exists, while these native lines tell us whether control returned to Swift.
replace_once(
    SERVICE,
    '''        let result: ([Format], Info)
''',
    '''        appendNativeLog("about to start embedded yt-dlp extraction")
        let result: ([Format], Info)
''',
    'pre extraction breadcrumb',
)

# Use a broad anchor that exists after all earlier routing patches.
text = SERVICE.read_text()
needle = '''        return MPVHookResponse(
'''
if needle not in text:
    raise SystemExit('response return anchor not found in YTDLPService.swift')
text = text.replace(
    needle,
    '''        appendNativeLog("extraction returned to native layer; selected-formats=\\(result.0.count)")
        return MPVHookResponse(
''',
    1,
)
SERVICE.write_text(text)

print('Applied v32: pre-Python opt-in yt-dlp breadcrumb log plus native extraction checkpoints.')
