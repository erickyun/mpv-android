from pathlib import Path

ROOT = Path('MPVTorBox')
RESOLVER = ROOT / 'SourceResolver.swift'
TORBOX = ROOT / 'TorBoxService.swift'
CONTENT = ROOT / 'ContentView.swift'
PLAYER = ROOT / 'Views' / 'PlayerScreen.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label} anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


def replace_between(path: Path, start_marker: str, end_marker: str, replacement: str, label: str) -> None:
    text = path.read_text()
    try:
        start = text.index(start_marker)
        end = text.index(end_marker, start)
    except ValueError as exc:
        raise SystemExit(f'{label} anchor not found in {path}: {exc}')
    path.write_text(text[:start] + replacement + text[end:])


# Generic playlist models live next to ResolvedSource so TorBox, yt-dlp, and the
# player UI all use one representation. Internal provider-specific playback
# tokens never contain credentials.
replace_once(
    RESOLVER,
    'struct ResolvedSource: @unchecked Sendable {\n',
    '''struct MediaPlaylistItem: Identifiable, Sendable {
    let id: String
    let title: String
    let input: String
    let duration: Double?
    let index: Int
    var detail: String? = nil
}

struct MediaPlaylistSelection: Identifiable, Sendable {
    let id: String
    let title: String
    let provider: String
    let items: [MediaPlaylistItem]
}

struct ResolvedSource: @unchecked Sendable {
''',
    'generic playlist models',
)

playlist_discovery = r'''    func playlistSelection(
        _ input: String,
        settings: ProviderSettings,
        status: @escaping @MainActor (String) -> Void
    ) async throws -> MediaPlaylistSelection? {
        let source = normalizedSource(input)
        guard !source.isEmpty else { return nil }

        if isMagnet(source) {
            guard settings.torBoxEnabled, !settings.torBoxAPIKey.isEmpty else { return nil }
            return try await torBox.playlistSelection(
                magnet: source,
                apiKey: settings.torBoxAPIKey,
                status: status
            )
        }

        guard settings.ytdlpEnabled,
              let url = URL(string: source),
              let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme),
              shouldUseYTDLP(url),
              let selection = try await YTDLPService.shared.playlistSelection(url: url) else {
            return nil
        }

        return MediaPlaylistSelection(
            id: "ytdlp:\(selection.id)",
            title: selection.title,
            provider: "yt-dlp",
            items: selection.items.map { item in
                MediaPlaylistItem(
                    id: "ytdlp:\(item.id)",
                    title: item.title,
                    input: item.url.absoluteString,
                    duration: item.duration,
                    index: item.index
                )
            }
        )
    }

'''
replace_once(
    RESOLVER,
    '    func resolve(\n',
    playlist_discovery + '    func resolve(\n',
    'generic playlist discovery method',
)

# A TorBox playlist entry resolves through an internal credential-free token.
# This lets the same picker work both before playback and from inside the player.
replace_once(
    RESOLVER,
    '''        guard !source.isEmpty else { throw ResolverError.emptySource }\n\n        if isMagnet(source) {\n''',
    '''        guard !source.isEmpty else { throw ResolverError.emptySource }

        if let reference = torBoxFileReference(source) {
            guard settings.torBoxEnabled, !settings.torBoxAPIKey.isEmpty else {
                throw ResolverError.noTorrentProvider
            }
            await status("Requesting selected TorBox file…")
            let url = try await torBox.resolve(
                torrentID: reference.torrentID,
                fileID: reference.fileID,
                apiKey: settings.torBoxAPIKey,
                status: status
            )
            return ResolvedSource(url: url, provider: "TorBox")
        }

        if isMagnet(source) {
''',
    'TorBox playlist item routing',
)

replace_once(
    RESOLVER,
    '''    private func isMagnet(_ source: String) -> Bool {\n''',
    '''    private func torBoxFileReference(_ source: String) -> (torrentID: Int, fileID: Int)? {
        guard let url = URL(string: source),
              url.scheme?.lowercased() == "torboxfile",
              let host = url.host,
              let torrentID = Int(host),
              let filePart = url.pathComponents.last,
              let fileID = Int(filePart) else {
            return nil
        }
        return (torrentID, fileID)
    }

    private func isMagnet(_ source: String) -> Bool {
''',
    'TorBox token parser',
)

# TorBox already receives the complete file array from /mylist. Preserve it,
# cache the prepared torrent ID so a one-file preflight does not add the magnet
# twice, and expose every playable video file as a generic playlist.
replace_once(
    TORBOX,
    '''    private let videoExtensions = Set([\n        "mkv", "mp4", "m4v", "mov", "avi", "webm", "ts", "m2ts",\n        "mpg", "mpeg", "flv", "wmv", "ogv"\n    ])\n''',
    '''    private let videoExtensions = Set([
        "mkv", "mp4", "m4v", "mov", "avi", "webm", "ts", "m2ts",
        "mpg", "mpeg", "flv", "wmv", "ogv"
    ])
    private var preparedTorrentIDs: [String: Int] = [:]
''',
    'TorBox prepared torrent cache',
)

replace_once(
    TORBOX,
    '        let torrentID = try await createTorrent(magnet: magnet, apiKey: token)\n',
    '        let torrentID = try await prepareTorrentID(magnet: magnet, apiKey: token)\n',
    'reuse prepared TorBox torrent',
)

torbox_playlist_methods = r'''    func playlistSelection(
        magnet: String,
        apiKey: String,
        status: @escaping @MainActor (String) -> Void
    ) async throws -> MediaPlaylistSelection? {
        let token = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else { throw ServiceError.invalidAPIKey }

        await status("Reading TorBox torrent files…")
        let torrentID = try await prepareTorrentID(magnet: magnet, apiKey: token)

        for attempt in 1...30 {
            await status("Reading TorBox files \(attempt)/30…")
            do {
                let item = try await fetchTorrent(id: torrentID, apiKey: token)
                let files = playableFiles(from: item)
                if !files.isEmpty {
                    guard files.count > 1 else { return nil }
                    let title = torrentTitle(from: item) ?? "TorBox torrent"
                    let items = files.enumerated().map { offset, file in
                        MediaPlaylistItem(
                            id: "torbox:\(torrentID):\(file.id)",
                            title: file.name,
                            input: "torboxfile://\(torrentID)/\(file.id)",
                            duration: nil,
                            index: offset + 1,
                            detail: file.size > 0
                                ? ByteCountFormatter.string(fromByteCount: file.size, countStyle: .file)
                                : nil
                        )
                    }
                    return MediaPlaylistSelection(
                        id: "torbox:\(torrentID)",
                        title: title,
                        provider: "TorBox",
                        items: items
                    )
                }
            } catch {
                if attempt == 30 { throw error }
            }
            try await Task.sleep(nanoseconds: 3_000_000_000)
        }

        throw ServiceError.timedOut
    }

    func resolve(
        torrentID: Int,
        fileID: Int,
        apiKey: String,
        status: @escaping @MainActor (String) -> Void
    ) async throws -> URL {
        let token = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else { throw ServiceError.invalidAPIKey }

        for attempt in 1...30 {
            await status("Preparing selected TorBox file \(attempt)/30…")
            do {
                return try await requestDownload(
                    torrentID: torrentID,
                    fileID: fileID,
                    apiKey: token
                )
            } catch {
                if attempt == 30 { throw error }
            }
            try await Task.sleep(nanoseconds: 3_000_000_000)
        }
        throw ServiceError.timedOut
    }

    private func prepareTorrentID(magnet: String, apiKey: String) async throws -> Int {
        if let existing = preparedTorrentIDs[magnet] { return existing }
        let torrentID = try await createTorrent(magnet: magnet, apiKey: apiKey)
        preparedTorrentIDs[magnet] = torrentID
        return torrentID
    }

'''
replace_once(
    TORBOX,
    '    private func createTorrent(magnet: String, apiKey: String) async throws -> Int {\n',
    torbox_playlist_methods + '    private func createTorrent(magnet: String, apiKey: String) async throws -> Int {\n',
    'TorBox playlist methods',
)

old_select = '''    private func selectPlayableFile(from object: Any) -> MediaFile? {
        let fileObjects = arrays(named: "files", in: object).flatMap { $0 }
        let files = fileObjects.compactMap(parseMediaFile)

        let videos = files.filter {
            videoExtensions.contains(URL(fileURLWithPath: $0.name).pathExtension.lowercased())
        }

        return (videos.isEmpty ? files : videos).max { $0.size < $1.size }
    }
'''
new_select = '''    private func playableFiles(from object: Any) -> [MediaFile] {
        let fileObjects = arrays(named: "files", in: object).flatMap { $0 }
        var unique: [Int: MediaFile] = [:]
        for file in fileObjects.compactMap(parseMediaFile) {
            if let existing = unique[file.id], existing.size >= file.size { continue }
            unique[file.id] = file
        }

        let files = Array(unique.values)
        let videos = files.filter {
            videoExtensions.contains(URL(fileURLWithPath: $0.name).pathExtension.lowercased())
        }
        let candidates = videos.isEmpty ? files : videos
        return candidates.sorted {
            $0.name.localizedStandardCompare($1.name) == .orderedAscending
        }
    }

    private func selectPlayableFile(from object: Any) -> MediaFile? {
        playableFiles(from: object).max { $0.size < $1.size }
    }

    private func torrentTitle(from object: Any) -> String? {
        guard let dictionary = object as? [String: Any] else { return nil }
        return string(in: dictionary, keys: ["name", "title", "torrent_name", "filename"])
    }
'''
replace_once(TORBOX, old_select, new_select, 'TorBox playable file enumeration')

# ContentView now asks the resolver for any provider playlist. The active
# selection survives after playback starts so the same list can be reopened
# from PlayerScreen and another item can be resolved without leaving video.
replace_once(
    CONTENT,
    '''    @State private var playlistSelection: YTDLPService.PlaylistSelection?\n    @State private var pendingPlaylistItem: YTDLPService.PlaylistItem?\n\n    private let resolver = SourceResolver()\n    private let ytdlp = YTDLPService.shared\n''',
    '''    @State private var playlistSelection: MediaPlaylistSelection?
    @State private var pendingPlaylistItem: MediaPlaylistItem?
    @State private var activePlaylist: MediaPlaylistSelection?
    @State private var currentPlaylistItemID: String?

    private let resolver = SourceResolver()
''',
    'generic ContentView playlist state',
)

old_sheet = '''            .sheet(item: $playlistSelection, onDismiss: {
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
                if let currentSource {
                    PlayerScreen(source: currentSource, coordinator: playerCoordinator, isPresented: $showingPlayer)
                }
            }
'''
new_sheet = '''            .sheet(item: $playlistSelection, onDismiss: {
                if let item = pendingPlaylistItem {
                    pendingPlaylistItem = nil
                    openPlaylistItem(item)
                }
            }) { selection in
                PlaylistPickerView(selection: selection, selectedItemID: currentPlaylistItemID) { item in
                    pendingPlaylistItem = item
                    playlistSelection = nil
                }
            }
            .fullScreenCover(isPresented: $showingPlayer) {
                if let currentSource {
                    PlayerScreen(
                        source: currentSource,
                        coordinator: playerCoordinator,
                        isPresented: $showingPlayer,
                        playlist: activePlaylist,
                        selectedPlaylistItemID: currentPlaylistItemID,
                        onSelectPlaylistItem: { item in
                            openPlaylistItem(item)
                        }
                    )
                }
            }
'''
replace_once(CONTENT, old_sheet, new_sheet, 'playlist state passed into player')

new_open = r'''    private func openSource(skipPlaylistPicker: Bool = false) {
        let input = sourceText
        let providerSettings = settings.snapshot()
        isResolving = true
        statusText = "Resolving source…"

        Task {
            do {
                if !skipPlaylistPicker {
                    do {
                        if let selection = try await resolver.playlistSelection(
                            input,
                            settings: providerSettings,
                            status: { message in statusText = message }
                        ) {
                            activePlaylist = selection
                            currentPlaylistItemID = nil
                            playlistSelection = selection
                            statusText = "Choose one of \(selection.items.count) items."
                            isResolving = false
                            return
                        }
                    } catch {
                        statusText = "Playlist unavailable; opening the source normally…"
                    }
                }

                let resolved = try await resolver.resolve(input, settings: providerSettings) { message in
                    statusText = message
                }
                activePlaylist = nil
                currentPlaylistItemID = nil
                play(resolved)
                statusText = "Playing through \(resolved.provider)."
            } catch {
                errorMessage = error.localizedDescription
                statusText = "Unable to resolve source."
            }
            isResolving = false
        }
    }

    private func openPlaylistItem(_ item: MediaPlaylistItem) {
        let providerSettings = settings.snapshot()
        sourceText = item.input
        isResolving = true
        statusText = "Opening \(item.title)…"

        Task {
            do {
                var resolved = try await resolver.resolve(item.input, settings: providerSettings) { message in
                    statusText = message
                }
                resolved.title = item.title
                currentPlaylistItemID = item.id
                currentSource = resolved
                playerCoordinator.play(resolved)
                showingPlayer = true
                if let playlist = activePlaylist {
                    statusText = "Playing \(item.index)/\(playlist.items.count) through \(resolved.provider)."
                } else {
                    statusText = "Playing through \(resolved.provider)."
                }
            } catch {
                errorMessage = error.localizedDescription
                statusText = "Unable to open playlist item."
            }
            isResolving = false
        }
    }

'''
replace_between(
    CONTENT,
    '    private func openSource(skipPlaylistPicker: Bool = false) {\n',
    '    private func openLocalFile(_ url: URL) {\n',
    new_open,
    'generic playlist open flow',
)

# Reuse the same searchable picker from both ContentView and PlayerScreen.
replace_once(
    CONTENT,
    '''private struct PlaylistPickerView: View {\n    let selection: YTDLPService.PlaylistSelection\n    let onSelect: (YTDLPService.PlaylistItem) -> Void\n''',
    '''struct PlaylistPickerView: View {
    let selection: MediaPlaylistSelection
    var selectedItemID: String? = nil
    let onSelect: (MediaPlaylistItem) -> Void
''',
    'generic playlist picker types',
)
replace_once(
    CONTENT,
    '    private var filteredItems: [YTDLPService.PlaylistItem] {\n',
    '    private var filteredItems: [MediaPlaylistItem] {\n',
    'generic filtered playlist items',
)
replace_once(
    CONTENT,
    '''                            if let duration = item.duration, duration > 0 {\n                                Text(formatDuration(duration))\n                                    .font(.caption.monospacedDigit())\n                                    .foregroundStyle(.secondary)\n                            }\n''',
    '''                            if let duration = item.duration, duration > 0 {
                                Text(formatDuration(duration))
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            } else if let detail = item.detail, !detail.isEmpty {
                                Text(detail)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
''',
    'playlist item metadata',
)
replace_once(
    CONTENT,
    '                        Image(systemName: "play.circle.fill")\n',
    '                        Image(systemName: item.id == selectedItemID ? "checkmark.circle.fill" : "play.circle.fill")\n',
    'selected playlist row icon',
)
CONTENT.write_text(
    CONTENT.read_text()
        .replace('Text("No matching videos")', 'Text("No matching items")')
        .replace('Text("\\(selection.items.count) videos")', 'Text("\\(selection.items.count) items")')
)

# PlayerScreen exposes a Playlist control only when the current source actually
# belongs to a multi-item selection. Choosing an entry resolves it through the
# same ContentView/SourceResolver path and keeps the full-screen player open.
replace_once(
    PLAYER,
    '''    @ObservedObject var coordinator: MPVMetalPlayerView.Coordinator\n    @Binding var isPresented: Bool\n''',
    '''    @ObservedObject var coordinator: MPVMetalPlayerView.Coordinator
    @Binding var isPresented: Bool
    let playlist: MediaPlaylistSelection?
    let selectedPlaylistItemID: String?
    let onSelectPlaylistItem: (MediaPlaylistItem) -> Void
''',
    'PlayerScreen playlist inputs',
)
replace_once(
    PLAYER,
    '''    @State private var showingPlaybackSettings = false\n''',
    '''    @State private var showingPlaybackSettings = false
    @State private var showingPlaylistPicker = false
''',
    'PlayerScreen playlist state',
)
replace_once(
    PLAYER,
    '''        .sheet(isPresented: $showingPlaybackSettings) {\n            PlaybackSettingsSheet(coordinator: coordinator)\n        }\n        .onAppear {\n''',
    '''        .sheet(isPresented: $showingPlaybackSettings) {
            PlaybackSettingsSheet(coordinator: coordinator)
        }
        .sheet(isPresented: $showingPlaylistPicker) {
            if let playlist {
                PlaylistPickerView(
                    selection: playlist,
                    selectedItemID: selectedPlaylistItemID
                ) { item in
                    showingPlaylistPicker = false
                    onSelectPlaylistItem(item)
                    showControlsTemporarily()
                }
            }
        }
        .onAppear {
''',
    'in-player playlist sheet',
)
replace_once(
    PLAYER,
    '''                subtitleMenu\n\n                Button { showingPlaybackSettings = true } label: {\n''',
    '''                subtitleMenu

                if let playlist, playlist.items.count > 1 {
                    Button {
                        showingPlaylistPicker = true
                        hideControlsTask?.cancel()
                    } label: {
                        toolbarLabel(icon: "list.bullet.rectangle", text: "Playlist")
                    }
                }

                Button { showingPlaybackSettings = true } label: {
''',
    'in-player playlist button',
)

print('Added generic yt-dlp/TorBox playlists and an in-player playlist selector.')
