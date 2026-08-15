from pathlib import Path

ROOT = Path('MPVTorBox')
SERVICE = ROOT / 'YTDLPService.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


old_method = '''    private func normalizedRawOptions(_ rawOptions: [String: String]) -> [String: String] {
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
'''

new_method = '''    private func rawOptionTruthy(_ value: String?) -> Bool {
        guard let value else { return false }
        return ["1", "yes", "true", "on", "enable", "enabled"].contains(
            value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        )
    }

    private func normalizedSafeSite(_ raw: String) -> String? {
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !value.isEmpty else { return nil }
        if value.hasPrefix("http://") || value.hasPrefix("https://") {
            if let host = URL(string: value)?.host?.lowercased() {
                value = host
            }
        }
        if let slash = value.firstIndex(of: "/") {
            value = String(value[..<slash])
        }
        while value.hasPrefix("*.") { value.removeFirst(2) }
        while value.hasPrefix(".") { value.removeFirst() }
        while value.hasSuffix(".") { value.removeLast() }
        guard !value.isEmpty, value.contains(".") else { return nil }
        return value
    }

    private func looksLikeBareHostnameKey(_ key: String, value: String) -> Bool {
        guard value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        let candidate = key.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard candidate.contains("."), !candidate.contains("="), !candidate.contains("/") else { return false }
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyz0123456789.-*")
        return candidate.unicodeScalars.allSatisfy { allowed.contains($0) }
    }

    private func host(_ host: String, matchesSafeSite site: String) -> Bool {
        let host = host.lowercased()
        let site = site.lowercased()
        return host == site || host.hasSuffix("." + site)
    }

    private func normalizedRawOptions(_ rawOptions: [String: String], for url: URL) -> [String: String] {
        var normalized = rawOptions

        // mpv string-map uses commas between options. For the private sites option
        // the requested syntax is intentionally also comma-separated:
        // mpv-ios-safe-metadata-sites=xhamster.com,pornhub.com
        // mpv may therefore expose later domains as empty map keys. Reassemble
        // those hostname-looking keys here before the map reaches yt-dlp.
        if let rawSites = normalized["mpv-ios-safe-metadata-sites"] {
            var siteCandidates = rawSites
                .components(separatedBy: CharacterSet(charactersIn: ",;| \t\r\n"))
                .compactMap(normalizedSafeSite)

            let straySiteKeys = normalized
                .filter { key, value in looksLikeBareHostnameKey(key, value: value) }
                .map(\.key)
            for key in straySiteKeys {
                if let site = normalizedSafeSite(key) {
                    siteCandidates.append(site)
                    normalized.removeValue(forKey: key)
                }
            }

            var seen = Set<String>()
            let sites = siteCandidates.filter { seen.insert($0).inserted }
            normalized["mpv-ios-safe-metadata-sites"] = sites.joined(separator: ",")
        }

        // Safe mode is global when enabled and no site list is present. If a list
        // exists, convert the private yes/no value to the decision for THIS URL.
        // The bridge therefore remains generic and legacy mode is truly preserved
        // for non-matching sites.
        if rawOptionTruthy(normalized["mpv-ios-safe-metadata"]) {
            let sites = (normalized["mpv-ios-safe-metadata-sites"] ?? "")
                .split(separator: ",")
                .compactMap { normalizedSafeSite(String($0)) }
            if sites.isEmpty {
                normalized["mpv-ios-safe-metadata"] = "yes"
            } else {
                let currentHost = url.host?.lowercased() ?? ""
                let matched = sites.contains { host(currentHost, matchesSafeSite: $0) }
                normalized["mpv-ios-safe-metadata"] = matched ? "yes" : "no"
            }
        } else if normalized["mpv-ios-safe-metadata"] != nil {
            normalized["mpv-ios-safe-metadata"] = "no"
        }

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
'''
replace_once(SERVICE, old_method, new_method, 'safe-site raw option normalization')

replace_once(
    SERVICE,
    '''        let effectiveRawOptions = normalizedRawOptions(rawOptions)
        if !effectiveRawOptions.isEmpty,
''',
    '''        let effectiveRawOptions = normalizedRawOptions(rawOptions, for: url)

        // Diagnostic logging is opt-in and Files-visible. Setting either alias to
        // yes enables both bridge checkpoints and yt-dlp's own logger. With the
        // option absent/no, the old log-free behavior remains unchanged.
        let logEnabled = rawOptionTruthy(effectiveRawOptions["mpv-ios-ytdl-log"])
            || rawOptionTruthy(effectiveRawOptions["mpv-ios-logs"])
        let logURL = visibleLogURL()
        if logEnabled {
            try? FileManager.default.createDirectory(
                at: logURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            setenv("YTDLP_LOG_PATH", logURL.path, 1)
        } else {
            unsetenv("YTDLP_LOG_PATH")
            try? FileManager.default.removeItem(at: logURL)
        }
        defer { unsetenv("YTDLP_LOG_PATH") }

        if !effectiveRawOptions.isEmpty,
''',
    'log toggle and URL-aware normalization',
)

print('Applied v30: global/site-scoped safe metadata mode plus opt-in Files-visible yt-dlp logging.')
