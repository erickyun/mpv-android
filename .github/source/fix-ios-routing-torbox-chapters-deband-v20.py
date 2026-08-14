from pathlib import Path

ROOT = Path('MPVTorBox')


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))

# Models: chapters and live deband settings.
models = ROOT / 'Models' / 'PlayerModels.swift'
replace_once(
    models,
    'struct MPVStats: Equatable {\n',
    '''struct MPVChapter: Identifiable, Hashable, Sendable {
    let id: String
    let index: Int
    let title: String
    let startTime: Double
    let endTime: Double?
    let external: Bool

    var displayName: String {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "Chapter \\(index + 1)" : trimmed
    }
}

struct MPVDebandSettings: Equatable, Sendable {
    var enabled = false
    var iterations = 1
    var threshold = 48
    var range = 16
    var grain = 32
}

struct MPVStats: Equatable {
''',
    'chapter/deband models',
)

# Resolver: broad yt-dlp attempt + TorBox dashboard/download URLs.
resolver = ROOT / 'SourceResolver.swift'
replace_once(
    resolver,
    '''        if isMagnet(source) {
            guard settings.torBoxEnabled, !settings.torBoxAPIKey.isEmpty else { return nil }
            return try await torBox.playlistSelection(
                magnet: source,
                apiKey: settings.torBoxAPIKey,
                status: status
            )
        }

        guard settings.ytdlpEnabled,
''',
    '''        if isMagnet(source) {
            guard settings.torBoxEnabled, !settings.torBoxAPIKey.isEmpty else { return nil }
            return try await torBox.playlistSelection(
                magnet: source,
                apiKey: settings.torBoxAPIKey,
                status: status
            )
        }

        if let reference = torBoxDownloadReference(source) {
            guard settings.torBoxEnabled, !settings.torBoxAPIKey.isEmpty else { return nil }
            return try await torBox.playlistSelection(
                torrentID: reference.torrentID,
                apiKey: settings.torBoxAPIKey,
                status: status
            )
        }

        guard settings.ytdlpEnabled,
''',
    'TorBox dashboard playlist routing',
)
replace_once(
    resolver,
    '''        if let reference = torBoxFileReference(source) {
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
    '''        if let reference = torBoxFileReference(source) {
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

        if let reference = torBoxDownloadReference(source) {
            guard settings.torBoxEnabled, !settings.torBoxAPIKey.isEmpty else {
                throw ResolverError.noTorrentProvider
            }
            await status("Opening TorBox dashboard download through the API…")
            do {
                let url = try await torBox.resolve(
                    torrentID: reference.torrentID,
                    apiKey: settings.torBoxAPIKey,
                    status: status
                )
                return ResolvedSource(url: url, provider: "TorBox")
            } catch {
                throw ResolverError.torBoxFailed(error.localizedDescription)
            }
        }

        if isMagnet(source) {
''',
    'TorBox dashboard direct routing',
)
replace_once(
    resolver,
    '''    private func torBoxFileReference(_ source: String) -> (torrentID: Int, fileID: Int)? {
''',
    '''    private func torBoxDownloadReference(_ source: String) -> (torrentID: Int, name: String?)? {
        guard let url = URL(string: source),
              let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme),
              let host = url.host?.lowercased(),
              host == "torbox.app" || host == "www.torbox.app",
              url.path.lowercased() == "/download",
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return nil
        }

        var values: [String: String] = [:]
        for item in components.queryItems ?? [] where values[item.name.lowercased()] == nil {
            values[item.name.lowercased()] = item.value ?? ""
        }
        let type = (values["type"] ?? "").lowercased()
        guard type == "torrents" || type == "torrent",
              let torrentID = Int(values["id"] ?? "") else {
            return nil
        }
        let name = values["name"]?.trimmingCharacters(in: .whitespacesAndNewlines)
        return (torrentID, name?.isEmpty == false ? name : nil)
    }

    private func torBoxFileReference(_ source: String) -> (torrentID: Int, fileID: Int)? {
''',
    'TorBox dashboard parser',
)
text = resolver.read_text()
old_start = '    private func shouldUseYTDLP(_ url: URL) -> Bool {\n'
start = text.find(old_start)
if start < 0:
    raise SystemExit('shouldUseYTDLP start not found')
end = text.find('\n    }\n}', start)
if end < 0:
    raise SystemExit('shouldUseYTDLP end not found')
replacement = '''    private func shouldUseYTDLP(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme) else { return false }
        if looksLikeDirectMedia(url) { return false }
        if torBoxDownloadReference(url.absoluteString) != nil { return false }
        // yt-dlp has a Generic extractor, so a static hostname allow-list loses
        // supported sites. Try every non-direct web URL; the native hook below
        // falls back to the original URL only when yt-dlp reports Unsupported.
        return true
    }
'''
text = text[:start] + replacement + text[end + len('\n    }'):]
resolver.write_text(text)

# TorBox: resolve dashboard torrent IDs directly via mylist + requestdl.
torbox = ROOT / 'TorBoxService.swift'
anchor = '''    func resolve(
        torrentID: Int,
        fileID: Int,
'''
addition = '''    func playlistSelection(
        torrentID: Int,
        apiKey: String,
        status: @escaping @MainActor (String) -> Void
    ) async throws -> MediaPlaylistSelection? {
        let token = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else { throw ServiceError.invalidAPIKey }

        await status("Reading TorBox torrent files…")
        let item = try await fetchTorrent(id: torrentID, apiKey: token)
        let files = playableFiles(from: item)
        guard !files.isEmpty else { throw ServiceError.noPlayableFile }
        guard files.count > 1 else { return nil }

        let title = torrentTitle(from: item) ?? "TorBox torrent"
        return MediaPlaylistSelection(
            id: "torbox:\\(torrentID)",
            title: title,
            provider: "TorBox",
            items: files.enumerated().map { offset, file in
                MediaPlaylistItem(
                    id: "torbox:\\(torrentID):\\(file.id)",
                    title: file.name,
                    input: "torboxfile://\\(torrentID)/\\(file.id)",
                    duration: nil,
                    index: offset + 1,
                    detail: file.size > 0
                        ? ByteCountFormatter.string(fromByteCount: file.size, countStyle: .file)
                        : nil
                )
            }
        )
    }

    func resolve(
        torrentID: Int,
        apiKey: String,
        status: @escaping @MainActor (String) -> Void
    ) async throws -> URL {
        let token = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty else { throw ServiceError.invalidAPIKey }

        for attempt in 1...20 {
            await status("Preparing TorBox dashboard file \\(attempt)/20…")
            do {
                let item = try await fetchTorrent(id: torrentID, apiKey: token)
                guard let file = selectPlayableFile(from: item) else {
                    throw ServiceError.noPlayableFile
                }
                return try await requestDownload(
                    torrentID: torrentID,
                    fileID: file.id,
                    apiKey: token
                )
            } catch {
                if attempt == 20 { throw error }
            }
            try await Task.sleep(nanoseconds: 1_500_000_000)
        }
        throw ServiceError.timedOut
    }

'''
replace_once(torbox, anchor, addition + anchor, 'TorBox ID overloads')

# yt-dlp hook response: preserve site chapters.
ytdlp = ROOT / 'YTDLPService.swift'
replace_once(
    ytdlp,
    '''    struct MPVHookResponse: Codable, Sendable {
''',
    '''    struct MPVHookChapter: Codable, Sendable {
        let title: String?
        let startTime: Double
        let endTime: Double?
    }

    struct MPVHookResponse: Codable, Sendable {
''',
    'yt-dlp chapter response model',
)
replace_once(
    ytdlp,
    '''        let duration: Double?
        let error: String?

        static func failure(_ message: String) -> MPVHookResponse {
            MPVHookResponse(ok: false, title: nil, formats: [], httpHeaders: [:], selector: nil, duration: nil, error: message)
        }
''',
    '''        let duration: Double?
        let chapters: [MPVHookChapter]
        let error: String?

        static func failure(_ message: String) -> MPVHookResponse {
            MPVHookResponse(ok: false, title: nil, formats: [], httpHeaders: [:], selector: nil, duration: nil, chapters: [], error: message)
        }
''',
    'yt-dlp response chapters field',
)
replace_once(
    ytdlp,
    '''            selector: effectiveSelector,
            duration: result.1.duration,
            error: nil
''',
    '''            selector: effectiveSelector,
            duration: result.1.duration,
            chapters: (result.1.chapters ?? []).compactMap { chapter in
                guard let start = chapter.start_time, start.isFinite, start >= 0 else { return nil }
                return MPVHookChapter(
                    title: chapter.title,
                    startTime: start,
                    endTime: chapter.end_time
                )
            },
            error: nil
''',
    'yt-dlp response chapter mapping',
)

# Player delegate + coordinator state.
delegate = ROOT / 'Player' / 'MPVPlayerDelegate.swift'
replace_once(
    delegate,
    '''    func playerDidUpdateTracks(_ tracks: [MPVTrack])
    func playerDidUpdateStats(_ stats: MPVStats)
''',
    '''    func playerDidUpdateTracks(_ tracks: [MPVTrack])
    func playerDidUpdateChapters(_ chapters: [MPVChapter])
    func playerDidUpdateDeband(_ settings: MPVDebandSettings)
    func playerDidUpdateStats(_ stats: MPVStats)
''',
    'delegate chapter/deband methods',
)

player_view = ROOT / 'Player' / 'MPVMetalPlayerView.swift'
replace_once(
    player_view,
    '''        @Published var tracks: [MPVTrack] = []
        @Published var stats = MPVStats()
''',
    '''        @Published var tracks: [MPVTrack] = []
        @Published var chapters: [MPVChapter] = []
        @Published var deband = MPVDebandSettings()
        @Published var stats = MPVStats()
''',
    'coordinator chapter/deband state',
)
replace_once(
    player_view,
    '''        func addSubtitle(_ url: URL) { player?.addSubtitle(url: url) }
        func keypress(_ key: String) { player?.keypress(key) }
''',
    '''        func addSubtitle(_ url: URL) { player?.addSubtitle(url: url) }
        func selectChapter(_ chapter: MPVChapter) { player?.selectChapter(chapter) }
        func setDebandEnabled(_ value: Bool) { player?.setDebandEnabled(value) }
        func setDebandIterations(_ value: Int) { player?.setDebandIterations(value) }
        func setDebandThreshold(_ value: Int) { player?.setDebandThreshold(value) }
        func setDebandRange(_ value: Int) { player?.setDebandRange(value) }
        func setDebandGrain(_ value: Int) { player?.setDebandGrain(value) }
        func resetDeband() { player?.resetDeband() }
        func keypress(_ key: String) { player?.keypress(key) }
''',
    'coordinator chapter/deband commands',
)
replace_once(
    player_view,
    '''        func playerDidUpdateTracks(_ tracks: [MPVTrack]) { self.tracks = tracks }
        func playerDidUpdateStats(_ stats: MPVStats) { self.stats = stats }
''',
    '''        func playerDidUpdateTracks(_ tracks: [MPVTrack]) { self.tracks = tracks }
        func playerDidUpdateChapters(_ chapters: [MPVChapter]) { self.chapters = chapters }
        func playerDidUpdateDeband(_ settings: MPVDebandSettings) { deband = settings }
        func playerDidUpdateStats(_ stats: MPVStats) { self.stats = stats }
''',
    'coordinator delegate handlers',
)

# MPV controller: Unsupported -> direct fallback, chapters, live deband.
metal = ROOT / 'Player' / 'MPVMetalViewController.swift'
replace_once(metal, '    private var rotationVideoRefreshGeneration = 0\n', '    private var rotationVideoRefreshGeneration = 0\n    private var embeddedChapters: [MPVChapter] = []\n', 'embedded chapters')
replace_once(metal, '        observe(MPVProperty.trackList, format: MPV_FORMAT_NONE)\n', '        observe(MPVProperty.trackList, format: MPV_FORMAT_NONE)\n        observe("chapter-list", format: MPV_FORMAT_NONE)\n', 'observe chapters')
replace_once(metal, '    func loadSource(_ source: ResolvedSource) {\n        playSource = source\n\n', '    func loadSource(_ source: ResolvedSource) {\n        playSource = source\n        embeddedChapters = []\n        publishChapters()\n\n', 'reset chapters')
replace_once(
    metal,
    '''    func addSubtitle(url: URL) {
        subtitleAccesses.append(SecurityScopedAccess(url: url))
        command("sub-add", args: [url.path, "select"])
        eventQueue.asyncAfter(deadline: .now() + 0.25) { [weak self] in self?.publishTracks() }
    }

    func setScaleMode(_ mode: VideoScaleMode) {
''',
    '''    func addSubtitle(url: URL) {
        subtitleAccesses.append(SecurityScopedAccess(url: url))
        command("sub-add", args: [url.path, "select"])
        eventQueue.asyncAfter(deadline: .now() + 0.25) { [weak self] in self?.publishTracks() }
    }

    func selectChapter(_ chapter: MPVChapter) {
        seekAbsolute(seconds: chapter.startTime)
    }

    func setDebandEnabled(_ value: Bool) {
        setString("deband", value: value ? "yes" : "no")
        publishDeband()
    }

    func setDebandIterations(_ value: Int) {
        setString("deband-iterations", value: String(min(max(value, 0), 16)))
        publishDeband()
    }

    func setDebandThreshold(_ value: Int) {
        setString("deband-threshold", value: String(min(max(value, 0), 4096)))
        publishDeband()
    }

    func setDebandRange(_ value: Int) {
        setString("deband-range", value: String(min(max(value, 1), 64)))
        publishDeband()
    }

    func setDebandGrain(_ value: Int) {
        setString("deband-grain", value: String(min(max(value, 0), 4096)))
        publishDeband()
    }

    func resetDeband() {
        setString("deband", value: "yes")
        setString("deband-iterations", value: "1")
        setString("deband-threshold", value: "48")
        setString("deband-range", value: "16")
        setString("deband-grain", value: "32")
        publishDeband()
    }

    func setScaleMode(_ mode: VideoScaleMode) {
''',
    'chapter/deband commands',
)
replace_once(metal, '            if self.timerTick % 4 == 0 { self.publishStats() }\n', '            if self.timerTick % 4 == 0 {\n                self.publishStats()\n                self.publishDeband()\n            }\n', 'periodic deband')
replace_once(
    metal,
    '''                    if name == MPVProperty.trackList { self.publishTracks() }
                    self.publishPlayback()

                case MPV_EVENT_FILE_LOADED:
                    self.publishTracks()
                    self.publishPlayback()
                    self.publishStats()
''',
    '''                    if name == MPVProperty.trackList { self.publishTracks() }
                    if name == "chapter-list" { self.publishChapters() }
                    self.publishPlayback()

                case MPV_EVENT_FILE_LOADED:
                    self.publishTracks()
                    self.publishChapters()
                    self.publishDeband()
                    self.publishPlayback()
                    self.publishStats()
''',
    'chapter/deband events',
)
replace_once(
    metal,
    '''            finishEmbeddedYTDLHook(
                hookID: hookID,
                response: .failure("Invalid website URL: \\(rawURL)")
            )
''',
    '''            finishEmbeddedYTDLHook(
                hookID: hookID,
                originalURL: rawURL,
                response: .failure("Invalid website URL: \\(rawURL)")
            )
''',
    'invalid URL original argument',
)
replace_once(metal, '            self.finishEmbeddedYTDLHook(hookID: hookID, response: response)\n', '            self.finishEmbeddedYTDLHook(hookID: hookID, originalURL: rawURL, response: response)\n', 'hook original URL')
replace_once(
    metal,
    '''    private func finishEmbeddedYTDLHook(
        hookID: UInt64,
        response: YTDLPService.MPVHookResponse
    ) {
''',
    '''    private func finishEmbeddedYTDLHook(
        hookID: UInt64,
        originalURL: String,
        response: YTDLPService.MPVHookResponse
    ) {
''',
    'finish hook signature',
)
replace_once(
    metal,
    '''        guard response.ok else {
            let reason = response.error ?? "unknown embedded yt-dlp error"
            print("[ios-ytdl-native] extraction failed: \\(reason)")
            setString("stream-open-filename", value: "memory://")
            command("show-text", args: ["yt-dlp failed: \\(reason)", "6000"])
            check(mpv_hook_continue(context, hookID))
            return
        }
''',
    '''        guard response.ok else {
            let reason = response.error ?? "unknown embedded yt-dlp error"
            print("[ios-ytdl-native] extraction failed: \\(reason)")

            if isUnsupportedYTDLError(reason),
               let directURL = URL(string: originalURL),
               let scheme = directURL.scheme?.lowercased(),
               ["http", "https"].contains(scheme) {
                print("[ios-ytdl-native] unsupported by yt-dlp; falling back to direct URL")
                setString("file-local-options/ytdl", value: "no")
                setString("stream-open-filename", value: originalURL)
                command("show-text", args: ["yt-dlp unsupported — trying directly", "2500"])
                check(mpv_hook_continue(context, hookID))
                return
            }

            setString("stream-open-filename", value: "memory://")
            command("show-text", args: ["yt-dlp failed: \\(reason)", "6000"])
            check(mpv_hook_continue(context, hookID))
            return
        }
''',
    'unsupported direct fallback',
)
replace_once(
    metal,
    '''        guard let stream = makeEmbeddedYTDLStream(
            response.formats,
            duration: response.duration
        ) else {
''',
    '''        embeddedChapters = response.chapters.enumerated().map { index, chapter in
            MPVChapter(
                id: "ytdlp:\\(index):\\(chapter.startTime)",
                index: index,
                title: chapter.title ?? "Chapter \\(index + 1)",
                startTime: chapter.startTime,
                endTime: chapter.endTime,
                external: true
            )
        }
        publishChapters()

        guard let stream = makeEmbeddedYTDLStream(
            response.formats,
            duration: response.duration
        ) else {
''',
    'yt-dlp chapters',
)
replace_once(
    metal,
    '    private func makeEmbeddedYTDLStream(\n',
    '''    private func isUnsupportedYTDLError(_ message: String) -> Bool {
        let value = message.lowercased()
        return value.contains("unsupported url") ||
            value.contains("unsupportederror") ||
            value.contains("unsupported url scheme")
    }

    private func makeEmbeddedYTDLStream(
''',
    'unsupported error helper',
)
replace_once(
    metal,
    '    private func publishStats() {\n',
    '''    private func publishChapters() {
        let chapters: [MPVChapter]
        if !embeddedChapters.isEmpty {
            chapters = embeddedChapters
        } else {
            let count = Int(getInt("chapter-list/count") ?? 0)
            chapters = (0..<count).compactMap { index in
                guard let start = getDouble("chapter-list/\\(index)/time"), start.isFinite else { return nil }
                let title = getString("chapter-list/\\(index)/title") ?? "Chapter \\(index + 1)"
                let end = index + 1 < count ? getDouble("chapter-list/\\(index + 1)/time") : nil
                return MPVChapter(
                    id: "mpv:\\(index):\\(start)",
                    index: index,
                    title: title,
                    startTime: start,
                    endTime: end,
                    external: false
                )
            }
        }
        Task { @MainActor [weak self] in self?.playDelegate?.playerDidUpdateChapters(chapters) }
    }

    private func publishDeband() {
        let enabledText = optionString("deband", fallback: "no").lowercased()
        let settings = MPVDebandSettings(
            enabled: ["yes", "true", "1"].contains(enabledText),
            iterations: Int(optionString("deband-iterations", fallback: "1")) ?? 1,
            threshold: Int(optionString("deband-threshold", fallback: "48")) ?? 48,
            range: Int(optionString("deband-range", fallback: "16")) ?? 16,
            grain: Int(optionString("deband-grain", fallback: "32")) ?? 32
        )
        Task { @MainActor [weak self] in self?.playDelegate?.playerDidUpdateDeband(settings) }
    }

    private func publishStats() {
''',
    'chapter/deband publishers',
)

# Player UI: chapter menu + live deband section.
screen = ROOT / 'Views' / 'PlayerScreen.swift'
replace_once(
    screen,
    '''            HStack(spacing: 18) {
                trackMenu(kind: .video, icon: "film", label: "Video")
                trackMenu(kind: .audio, icon: "waveform", label: "Audio")
                subtitleMenu

                if let playlist, playlist.items.count > 1 {
''',
    '''            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 18) {
                    trackMenu(kind: .video, icon: "film", label: "Video")
                    trackMenu(kind: .audio, icon: "waveform", label: "Audio")
                    subtitleMenu

                    if !coordinator.chapters.isEmpty {
                        chapterMenu
                    }

                    if let playlist, playlist.items.count > 1 {
''',
    'toolbar scroll/chapter start',
)
replace_once(
    screen,
    '''                Button {
                    if coordinator.takeScreenshot() {
                        flash("Saved to Files → On My iPhone → MPV → Screenshots")
                    } else {
                        flash("Could not create the Screenshots folder")
                    }
                } label: {
                    toolbarLabel(icon: "camera", text: "Shot")
                }
            }
            .font(.caption)
''',
    '''                    Button {
                        if coordinator.takeScreenshot() {
                            flash("Saved to Files → On My iPhone → MPV → Screenshots")
                        } else {
                            flash("Could not create the Screenshots folder")
                        }
                    } label: {
                        toolbarLabel(icon: "camera", text: "Shot")
                    }
                }
                .font(.caption)
            }
''',
    'toolbar scroll close',
)
replace_once(
    screen,
    '    private var subtitleMenu: some View {\n',
    '''    private var chapterMenu: some View {
        Menu {
            ForEach(coordinator.chapters) { chapter in
                Button {
                    coordinator.selectChapter(chapter)
                    showControlsTemporarily()
                } label: {
                    Label(
                        "\\(formatTime(chapter.startTime))  \\(chapter.displayName)",
                        systemImage: isCurrentChapter(chapter) ? "checkmark" : "circle"
                    )
                }
            }
        } label: {
            toolbarLabel(icon: "bookmark", text: "Chapters")
        }
    }

    private func isCurrentChapter(_ chapter: MPVChapter) -> Bool {
        guard coordinator.position >= chapter.startTime else { return false }
        if let end = chapter.endTime { return coordinator.position < end }
        if chapter.index + 1 < coordinator.chapters.count {
            return coordinator.position < coordinator.chapters[chapter.index + 1].startTime
        }
        return true
    }

    private var subtitleMenu: some View {
''',
    'chapter menu',
)
replace_once(
    screen,
    '''                Section("Video scaling") {
                    Picker("Scaling", selection: Binding(
                        get: { coordinator.scaleMode },
                        set: { mode in
                            coordinator.scaleMode = mode
                            coordinator.player?.setScaleMode(mode)
                        }
                    )) {
                        ForEach(VideoScaleMode.allCases) { mode in Text(mode.title).tag(mode) }
                    }
                    .pickerStyle(.segmented)
                }
''',
    '''                Section("Video scaling") {
                    Picker("Scaling", selection: Binding(
                        get: { coordinator.scaleMode },
                        set: { mode in
                            coordinator.scaleMode = mode
                            coordinator.player?.setScaleMode(mode)
                        }
                    )) {
                        ForEach(VideoScaleMode.allCases) { mode in Text(mode.title).tag(mode) }
                    }
                    .pickerStyle(.segmented)
                }

                Section("Deband") {
                    Toggle(
                        "Enable deband",
                        isOn: Binding(
                            get: { coordinator.deband.enabled },
                            set: { coordinator.setDebandEnabled($0) }
                        )
                    )
                    if coordinator.deband.enabled {
                        debandSlider(title: "Iterations", value: coordinator.deband.iterations, range: 0...16, set: coordinator.setDebandIterations)
                        debandSlider(title: "Threshold", value: coordinator.deband.threshold, range: 0...4096, set: coordinator.setDebandThreshold)
                        debandSlider(title: "Range", value: coordinator.deband.range, range: 1...64, set: coordinator.setDebandRange)
                        debandSlider(title: "Grain", value: coordinator.deband.grain, range: 0...4096, set: coordinator.setDebandGrain)
                        Button("Reset deband defaults") { coordinator.resetDeband() }
                    }
                    Text("Changes apply immediately. mpv defaults: iterations 1, threshold 48, range 16, grain 32.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
''',
    'live deband playback settings',
)
replace_once(
    screen,
    '''            .navigationTitle("Playback")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
''',
    '''            .navigationTitle("Playback")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }

    @ViewBuilder
    private func debandSlider(
        title: String,
        value: Int,
        range: ClosedRange<Int>,
        set: @escaping (Int) -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title)
                Spacer()
                Text(String(value)).monospacedDigit().foregroundStyle(.secondary)
            }
            Slider(
                value: Binding(
                    get: { Double(value) },
                    set: { set(Int($0.rounded())) }
                ),
                in: Double(range.lowerBound)...Double(range.upperBound),
                step: 1
            )
        }
    }
}
''',
    'deband slider helper',
)

print('Applied v20: generic yt-dlp routing with unsupported direct fallback, TorBox dashboard URLs, chapters, and live deband controls.')
