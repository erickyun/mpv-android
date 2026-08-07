from pathlib import Path

ROOT = Path('MPVTorBox')
SERVICE = ROOT / 'YTDLPService.swift'
CONTENT = ROOT / 'ContentView.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label} anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# 1) Small sendable models used by SwiftUI. The bridge returns only flat playlist
# metadata; choosing an item still goes through the existing native MPV yt-dlp
# hook, so mpv.conf ytdl-format and full-duration seeking remain unchanged.
replace_once(
    SERVICE,
    '''    struct ModuleStatus: Sendable {\n''',
    '''    struct PlaylistItem: Identifiable, Sendable {
        let id: String
        let title: String
        let url: URL
        let duration: Double?
        let index: Int
    }

    struct PlaylistSelection: Identifiable, Sendable {
        let id: String
        let title: String
        let items: [PlaylistItem]
    }

    struct ModuleStatus: Sendable {
''',
    'playlist models',
)

playlist_method = r'''    func playlistSelection(url: URL) async throws -> PlaylistSelection? {
        guard !extractionInProgress else { throw YTDLPError.extractionAlreadyRunning }
        extractionInProgress = true
        defer { extractionInProgress = false }

        try prepareRuntimeDirectories()
        let pluginInstalledNow = try installBundledWebKitPlugin()
        if pluginInstalledNow, youtubeDL != nil {
            youtubeDL = nil
            throw YTDLPError.webKitPluginRequiresRestart
        }

        // Always use a fresh bridge here because its Python options are changed
        // to flat-playlist mode. The normal playback hook recreates its own
        // bridge afterwards with mpv.conf's ytdl-format.
        youtubeDL = nil
        let bridge = getBridge()
        let info = try await runWithTimeout(seconds: 60) {
            try await bridge.extractPlaylistInfo(url: url)
        }

        if let version = bridge.version, !version.isEmpty {
            defaults.set(version, forKey: Keys.installedVersion)
        }
        defaults.set(Self.webKitPluginVersion, forKey: Keys.webKitPluginVersion)
        youtubeDL = nil

        let items = info.entries.compactMap { entry -> PlaylistItem? in
            let extractor = entry.extractor_key.lowercased()
            let rawID = entry.id.isEmpty ? entry.url : entry.id

            let itemURL: URL?
            if extractor.contains("youtube"), !rawID.isEmpty {
                var components = URLComponents()
                components.scheme = "https"
                components.host = "www.youtube.com"
                components.path = "/watch"
                components.queryItems = [URLQueryItem(name: "v", value: rawID)]
                itemURL = components.url
            } else if let candidate = URL(string: entry.url),
                      let scheme = candidate.scheme?.lowercased(),
                      ["http", "https"].contains(scheme) {
                itemURL = candidate
            } else {
                itemURL = nil
            }

            guard let itemURL else { return nil }
            return PlaylistItem(
                id: "\(entry.index)-\(entry.id)-\(itemURL.absoluteString)",
                title: entry.title.isEmpty ? "Video \(entry.index)" : entry.title,
                url: itemURL,
                duration: entry.duration,
                index: entry.index
            )
        }

        guard items.count > 1 else { return nil }
        return PlaylistSelection(
            id: url.absoluteString,
            title: info.title.isEmpty ? "Playlist" : info.title,
            items: items
        )
    }

'''

replace_once(
    SERVICE,
    '    func resolveForMPVHook(url: URL, formatSelector: String) async throws -> MPVHookResponse {\n',
    playlist_method + '    func resolveForMPVHook(url: URL, formatSelector: String) async throws -> MPVHookResponse {\n',
    'playlist extraction service',
)

# 2) ContentView state and service.
replace_once(
    CONTENT,
    '''    @State private var showingFilePicker = false\n\n    private let resolver = SourceResolver()\n''',
    '''    @State private var showingFilePicker = false
    @State private var playlistSelection: YTDLPService.PlaylistSelection?
    @State private var pendingPlaylistItem: YTDLPService.PlaylistItem?

    private let resolver = SourceResolver()
    private let ytdlp = YTDLPService.shared
''',
    'ContentView playlist state',
)

# 3) Present a native searchable list before the full-screen player.
replace_once(
    CONTENT,
    '''            .fullScreenCover(isPresented: $showingPlayer) {\n''',
    '''            .sheet(item: $playlistSelection, onDismiss: {
                if let item = pendingPlaylistItem {
                    pendingPlaylistItem = nil
                    sourceText = item.url.absoluteString
                    openSource(skipPlaylistPicker: true)
                }
            }) { selection in
                PlaylistPickerView(selection: selection) { item in
                    pendingPlaylistItem = item
                    playlistSelection = nil
                }
            }
            .fullScreenCover(isPresented: $showingPlayer) {
''',
    'playlist sheet',
)

# 4) Preflight only URLs that visibly look like a playlist. Normal video URLs
# keep their current one-extraction path, avoiding extra startup delay.
old_open = '''    private func openSource() {
        let input = sourceText
        let providerSettings = settings.snapshot()
        isResolving = true
        statusText = "Resolving source…"

        Task {
            do {
                let resolved = try await resolver.resolve(input, settings: providerSettings) { message in
                    statusText = message
                }
                play(resolved)
                statusText = "Playing through \\(resolved.provider)."
            } catch {
                errorMessage = error.localizedDescription
                statusText = "Unable to resolve source."
            }
            isResolving = false
        }
    }
'''

new_open = '''    private func openSource(skipPlaylistPicker: Bool = false) {
        let input = sourceText
        let providerSettings = settings.snapshot()
        isResolving = true
        statusText = "Resolving source…"

        Task {
            do {
                if !skipPlaylistPicker,
                   providerSettings.ytdlpEnabled,
                   let playlistURL = playlistCandidateURL(from: input) {
                    statusText = "Reading playlist with yt-dlp…"
                    if let selection = try await ytdlp.playlistSelection(url: playlistURL) {
                        playlistSelection = selection
                        statusText = "Choose one of \\(selection.items.count) videos."
                        isResolving = false
                        return
                    }
                }

                let resolved = try await resolver.resolve(input, settings: providerSettings) { message in
                    statusText = message
                }
                play(resolved)
                statusText = "Playing through \\(resolved.provider)."
            } catch {
                errorMessage = error.localizedDescription
                statusText = "Unable to resolve source."
            }
            isResolving = false
        }
    }

    private func playlistCandidateURL(from input: String) -> URL? {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        let normalized: String
        if let wrapper = URL(string: trimmed), wrapper.scheme?.lowercased() == "mpvtorbox" {
            normalized = sourceString(from: wrapper)
        } else {
            normalized = trimmed
        }

        guard let url = URL(string: normalized),
              let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme),
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return nil
        }

        let hasListQuery = components.queryItems?.contains { item in
            item.name.lowercased() == "list" && !(item.value ?? "").isEmpty
        } ?? false
        if hasListQuery { return url }

        let path = url.path.lowercased()
        let playlistHints = [
            "/playlist", "/playlists/", "/sets/", "/showcase/",
            "/album/", "/collection/", "/series/"
        ]
        return playlistHints.contains(where: { path.contains($0) }) ? url : nil
    }
'''

replace_once(CONTENT, old_open, new_open, 'playlist-aware openSource')

# 5) Add the picker itself. It intentionally shows only inexpensive metadata
# obtained from --flat-playlist. Search is local and selection dismisses the
# sheet before launching the player.
content_text = CONTENT.read_text()
if 'private struct PlaylistPickerView: View {' in content_text:
    raise SystemExit('PlaylistPickerView already exists')
content_text += r'''

private struct PlaylistPickerView: View {
    let selection: YTDLPService.PlaylistSelection
    let onSelect: (YTDLPService.PlaylistItem) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var searchText = ""

    private var filteredItems: [YTDLPService.PlaylistItem] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return selection.items }
        return selection.items.filter {
            $0.title.localizedCaseInsensitiveContains(query) || String($0.index).contains(query)
        }
    }

    var body: some View {
        NavigationStack {
            List(filteredItems) { item in
                Button {
                    onSelect(item)
                } label: {
                    HStack(spacing: 12) {
                        Text("\(item.index)")
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .frame(width: 34, alignment: .trailing)

                        VStack(alignment: .leading, spacing: 4) {
                            Text(item.title)
                                .foregroundStyle(.primary)
                                .multilineTextAlignment(.leading)
                                .lineLimit(2)
                            if let duration = item.duration, duration > 0 {
                                Text(formatDuration(duration))
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            }
                        }

                        Spacer(minLength: 8)
                        Image(systemName: "play.circle.fill")
                            .font(.title3)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            .overlay {
                if filteredItems.isEmpty {
                    ContentUnavailableView.search(text: searchText)
                }
            }
            .navigationTitle(selection.title)
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $searchText, prompt: "Search playlist")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Text("\(selection.items.count) videos")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func formatDuration(_ seconds: Double) -> String {
        let total = max(0, Int(seconds.rounded()))
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let secs = total % 60
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, secs)
        }
        return String(format: "%d:%02d", minutes, secs)
    }
}
'''
CONTENT.write_text(content_text)

print('Added searchable flat-playlist video picker before native yt-dlp playback.')
