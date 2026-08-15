from pathlib import Path

ROOT = Path('MPVTorBox')
PLAYER = ROOT / 'Player' / 'MPVMetalViewController.swift'
SERVICE = ROOT / 'YTDLPService.swift'
CONFIG = ROOT / 'Utilities' / 'MPVConfigManager.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))

replace_once(
    PLAYER,
    '''        print("[ios-ytdl-native] on_load request: \\(url.absoluteString); format=\\(selector)")
        Task { [weak self] in
''',
    '''        let rawOptions = getStringMap("options/ytdl-raw-options")
        let rawOptionKeys = rawOptions.keys.sorted().joined(separator: ",")
        print("[ios-ytdl-native] on_load request: \\(url.absoluteString); format=\\(selector); raw-option-keys=\\(rawOptionKeys)")
        Task { [weak self] in
''',
    'read raw options',
)
replace_once(
    PLAYER,
    '''                response = try await YTDLPService.shared.resolveForMPVHook(
                    url: url,
                    formatSelector: selector
                )
''',
    '''                response = try await YTDLPService.shared.resolveForMPVHook(
                    url: url,
                    formatSelector: selector,
                    rawOptions: rawOptions
                )
''',
    'pass raw options',
)
replace_once(
    PLAYER,
    '''    private func getString(_ name: String) -> String? {
        guard let mpv, let value = mpv_get_property_string(mpv, name) else { return nil }
        defer { mpv_free(value) }
        return String(cString: value)
    }

''',
    '''    private func getString(_ name: String) -> String? {
        guard let mpv, let value = mpv_get_property_string(mpv, name) else { return nil }
        defer { mpv_free(value) }
        return String(cString: value)
    }

    private func getStringMap(_ name: String) -> [String: String] {
        guard let mpv else { return [:] }
        var result = mpv_node()
        guard mpv_get_property(mpv, name, MPV_FORMAT_NODE, &result) >= 0 else { return [:] }
        defer { mpv_free_node_contents(&result) }

        guard result.format == MPV_FORMAT_NODE_MAP,
              let list = result.u.list,
              let keys = list.pointee.keys,
              let values = list.pointee.values else { return [:] }

        var mapped: [String: String] = [:]
        for index in 0..<Int(list.pointee.num) {
            guard let keyPointer = keys[index] else { continue }
            let key = String(cString: keyPointer)
            let node = values[index]
            switch node.format {
            case MPV_FORMAT_STRING:
                mapped[key] = node.u.string.map { String(cString: $0) } ?? ""
            case MPV_FORMAT_FLAG:
                mapped[key] = node.u.flag != 0 ? "yes" : "no"
            case MPV_FORMAT_INT64:
                mapped[key] = String(node.u.int64)
            case MPV_FORMAT_DOUBLE:
                mapped[key] = String(node.u.double_)
            case MPV_FORMAT_NONE:
                mapped[key] = ""
            default:
                continue
            }
        }
        return mapped
    }

''',
    'string map helper',
)

replace_once(
    SERVICE,
    '''    func resolveForMPVHook(url: URL, formatSelector: String) async throws -> MPVHookResponse {
''',
    '''    func resolveForMPVHook(url: URL, formatSelector: String, rawOptions: [String: String]) async throws -> MPVHookResponse {
''',
    'service signature',
)
replace_once(
    SERVICE,
    '''        setenv("MPV_YTDL_FORMAT", effectiveSelector, 1)
        defer { unsetenv("MPV_YTDL_FORMAT") }

        // Recreate YoutubeDL so edits to mpv.conf take effect after reopening the player
''',
    '''        setenv("MPV_YTDL_FORMAT", effectiveSelector, 1)
        defer { unsetenv("MPV_YTDL_FORMAT") }

        let effectiveRawOptions = normalizedRawOptions(rawOptions)
        if !effectiveRawOptions.isEmpty,
           let data = try? JSONSerialization.data(withJSONObject: effectiveRawOptions, options: []),
           let json = String(data: data, encoding: .utf8) {
            setenv("MPV_YTDL_RAW_OPTIONS_JSON", json, 1)
        } else {
            unsetenv("MPV_YTDL_RAW_OPTIONS_JSON")
        }
        defer { unsetenv("MPV_YTDL_RAW_OPTIONS_JSON") }

        // Recreate YoutubeDL so edits to mpv.conf take effect after reopening the player
''',
    'raw options environment',
)
replace_once(
    SERVICE,
    '''        appendNativeLog("MPV hook extraction: \\(url.absoluteString); format=\\(effectiveSelector)")

        let result: ([Format], Info)
''',
    '''        let rawOptionKeys = effectiveRawOptions.keys.sorted().joined(separator: ",")
        appendNativeLog("MPV hook extraction: \\(url.absoluteString); format=\\(effectiveSelector); raw-option-keys=\\(rawOptionKeys)")

        let result: ([Format], Info)
''',
    'safe raw option logging',
)
replace_once(
    SERVICE,
    '''    func resolveForMPVHook(url: URL, formatSelector: String, rawOptions: [String: String]) async throws -> MPVHookResponse {
''',
    '''    private func normalizedRawOptions(_ rawOptions: [String: String]) -> [String: String] {
        var normalized = rawOptions

        // A relative --cookies path is resolved against the Files-visible MPVConfig
        // directory, so mpv.conf never needs the app's changing sandbox UUID.
        if let cookies = normalized["cookies"]?.trimmingCharacters(in: .whitespacesAndNewlines),
           !cookies.isEmpty {
            let expanded = (cookies as NSString).expandingTildeInPath
            if expanded.hasPrefix("/") {
                normalized["cookies"] = expanded
            } else {
                let configDirectory = MPVConfigManager.prepare().directory
                normalized["cookies"] = configDirectory
                    .appendingPathComponent(expanded)
                    .standardizedFileURL.path
            }
        }
        return normalized
    }

    func resolveForMPVHook(url: URL, formatSelector: String, rawOptions: [String: String]) async throws -> MPVHookResponse {
''',
    'raw options normalization helper',
)

replace_once(
    CONFIG,
    '''    private static let ytdlFormatMarker = "# MPV iOS managed embedded yt-dlp format v1"
    private static let defaultYTDLFormat = "bv*[height<=1080]+ba/b[height<=1080]"
''',
    '''    private static let ytdlFormatMarker = "# MPV iOS managed embedded yt-dlp format v1"
    private static let ytdlRawOptionsDocsMarker = "# MPV iOS yt-dlp raw options v1"
    private static let defaultYTDLFormat = "bv*[height<=1080]+ba/b[height<=1080]"
''',
    'raw options docs marker',
)
replace_once(
    CONFIG,
    '''        writeIfMissing(
            to: readme,
            content: """
            MPV reads mpv.conf and input.conf from this folder every time the player starts.
            Existing files are not replaced. If ytdl-format is absent, the app appends a managed 1080p + best-audio default.
            You can replace ytdl-format with any normal yt-dlp format selector. Close and reopen the player after editing these files.
            """
        )

        return MPVConfigPaths(directory: directory, mpvConfig: mpvConfig, inputConfig: inputConfig)
''',
    '''        writeIfMissing(
            to: readme,
            content: """
            MPV reads mpv.conf and input.conf from this folder every time the player starts.
            Existing files are not replaced. If ytdl-format is absent, the app appends a managed 1080p + best-audio default.
            You can replace ytdl-format with any normal yt-dlp format selector. Close and reopen the player after editing these files.
            """
        )
        ensureYTDLRawOptionsDocumentation(in: readme)

        return MPVConfigPaths(directory: directory, mpvConfig: mpvConfig, inputConfig: inputConfig)
''',
    'ensure raw options docs',
)
replace_once(
    CONFIG,
    '''    private static func ensureStatsBindings(in url: URL) {
''',
    '''    private static func ensureYTDLRawOptionsDocumentation(in url: URL) {
        let existing = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
        guard !existing.contains(ytdlRawOptionsDocsMarker) else { return }
        let block = """

        \\(ytdlRawOptionsDocsMarker)
        ytdl-raw-options in mpv.conf is passed through yt-dlp's own option parser.
        Example: ytdl-raw-options=cookies=cookies.txt,referer=https://example.com/
        Put a Netscape-format cookies.txt beside mpv.conf in this MPVConfig folder.
        Raw option values may contain credentials; do not share mpv.conf or cookies.txt.
        """
        append(block, to: url)
    }

    private static func ensureStatsBindings(in url: URL) {
''',
    'raw options documentation method',
)

print('Applied v24: general ytdl-raw-options passthrough and Files-visible cookies.txt path support.')
