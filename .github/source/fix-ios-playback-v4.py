from pathlib import Path

ROOT = Path('MPVTorBox')

def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'Expected pattern not found in {path}: {old[:160]!r}')
    path.write_text(text.replace(old, new, 1))

# --- yt-dlp: timeout, explicit failures, delete support ---
ytdlp = ROOT / 'YTDLPService.swift'
ytdlp.write_text(r'''import Foundation
import Darwin
import YoutubeDL

private final class YTDLPContinuationGate<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Value, Error>?

    init(_ continuation: CheckedContinuation<Value, Error>) {
        self.continuation = continuation
    }

    func finish(_ result: Result<Value, Error>) {
        lock.lock()
        guard let continuation else {
            lock.unlock()
            return
        }
        self.continuation = nil
        lock.unlock()
        continuation.resume(with: result)
    }
}

actor YTDLPService {
    static let shared = YTDLPService()

    struct ModuleStatus: Sendable {
        let installed: Bool
        let version: String?
        let restartRequired: Bool

        var displayVersion: String {
            guard installed else { return "Not installed" }
            return version ?? "Installed — version unavailable"
        }
    }

    enum YTDLPError: LocalizedError {
        case noPlayableFormat
        case invalidURL
        case invalidDownload
        case versionUnavailable
        case extractionTimedOut

        var errorDescription: String? {
            switch self {
            case .noPlayableFormat: return "yt-dlp did not return a playable audio/video format."
            case .invalidURL: return "The yt-dlp result contained an invalid media URL."
            case .invalidDownload: return "The downloaded yt-dlp module could not be installed."
            case .versionUnavailable: return "yt-dlp was installed, but its version could not be detected."
            case .extractionTimedOut: return "yt-dlp did not finish within 45 seconds. Close and reopen MPV, update yt-dlp, and try again."
            }
        }
    }

    private enum Keys {
        static let installedVersion = "ytdlp_installed_version"
    }

    private var youtubeDL: YoutubeDL?
    private let defaults = UserDefaults.standard

    func moduleStatus() async -> ModuleStatus {
        let moduleURL = YoutubeDL.pythonModuleURL
        guard FileManager.default.fileExists(atPath: moduleURL.path) else {
            defaults.removeObject(forKey: Keys.installedVersion)
            return ModuleStatus(installed: false, version: nil, restartRequired: false)
        }

        if let stored = defaults.string(forKey: Keys.installedVersion), !stored.isEmpty {
            return ModuleStatus(installed: true, version: stored, restartRequired: false)
        }

        let version = await discoverLoadedVersion()
        if let version { defaults.set(version, forKey: Keys.installedVersion) }
        return ModuleStatus(installed: true, version: version, restartRequired: false)
    }

    func deleteModule(
        status: @escaping @MainActor (String) -> Void
    ) async throws -> ModuleStatus {
        try prepareRuntimeDirectories()
        let runtimeWasLoaded = youtubeDL?.version != nil
        await status("Deleting the downloaded yt-dlp module…")

        let fileManager = FileManager.default
        let moduleURL = YoutubeDL.pythonModuleURL
        let parent = moduleURL.deletingLastPathComponent()
        let backupURL = parent.appendingPathComponent("yt_dlp.previous")
        let cacheURL = fileManager.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("yt-dlp", isDirectory: true)

        if fileManager.fileExists(atPath: moduleURL.path) { try fileManager.removeItem(at: moduleURL) }
        try? fileManager.removeItem(at: backupURL)
        try? fileManager.removeItem(at: cacheURL)
        youtubeDL = nil
        defaults.removeObject(forKey: Keys.installedVersion)
        await status("yt-dlp was deleted.")

        return ModuleStatus(installed: false, version: nil, restartRequired: runtimeWasLoaded)
    }

    func updateModule(
        status: @escaping @MainActor (String) -> Void
    ) async throws -> ModuleStatus {
        try prepareRuntimeDirectories()
        let oldStatus = await moduleStatus()
        let runtimeWasLoaded = youtubeDL?.version != nil

        await status("Downloading the latest yt-dlp module…")
        let (temporaryURL, response) = try await URLSession.shared.download(from: YoutubeDL.latestDownloadURL)
        let downloadedVersion = releaseVersion(from: response)

        let fileManager = FileManager.default
        let moduleURL = YoutubeDL.pythonModuleURL
        let parent = moduleURL.deletingLastPathComponent()
        let backupURL = parent.appendingPathComponent("yt_dlp.previous")
        try fileManager.createDirectory(at: parent, withIntermediateDirectories: true)
        try? fileManager.removeItem(at: backupURL)

        await status("Replacing the previous yt-dlp module…")
        if fileManager.fileExists(atPath: moduleURL.path) {
            try fileManager.moveItem(at: moduleURL, to: backupURL)
        }

        do {
            try fileManager.moveItem(at: temporaryURL, to: moduleURL)
            try? fileManager.removeItem(at: backupURL)
        } catch {
            try? fileManager.removeItem(at: moduleURL)
            if fileManager.fileExists(atPath: backupURL.path) {
                try? fileManager.moveItem(at: backupURL, to: moduleURL)
            }
            throw YTDLPError.invalidDownload
        }

        youtubeDL = nil
        if let downloadedVersion, !downloadedVersion.isEmpty {
            defaults.set(downloadedVersion, forKey: Keys.installedVersion)
        } else {
            defaults.removeObject(forKey: Keys.installedVersion)
        }

        let oldVersion = oldStatus.version ?? "unknown"
        let newVersion = downloadedVersion ?? "version detected on next use"
        await status("yt-dlp updated: \(oldVersion) → \(newVersion)")

        return ModuleStatus(installed: true, version: downloadedVersion, restartRequired: runtimeWasLoaded)
    }

    func resolve(
        url: URL,
        status: @escaping @MainActor (String) -> Void
    ) async throws -> ResolvedSource {
        try prepareRuntimeDirectories()
        await status("Starting the local Python and yt-dlp runtime…")

        let bridge = getBridge()
        await status("Extracting the website URL with yt-dlp (45 second timeout)…")
        let result: ([Format], Info) = try await runWithTimeout(seconds: 45) {
            try await bridge.extractInfo(url: url)
        }
        let selectedFormats = result.0
        let info = result.1

        if let version = bridge.version, !version.isEmpty {
            defaults.set(version, forKey: Keys.installedVersion)
        }
        await status("Selecting the best progressive audio/video stream…")

        var formats = info.formats
        formats.append(contentsOf: selectedFormats)

        let playableProtocols = ["http", "https", "m3u8", "m3u8_native"]
        let progressive = formats
            .filter { format in
                let hasVideo = format.vcodec != nil && format.vcodec != "none"
                let hasAudio = format.acodec != nil && format.acodec != "none"
                return hasVideo && hasAudio && playableProtocols.contains(format.protocol)
            }
            .max { lhs, rhs in
                let left = (lhs.height ?? 0, lhs.tbr ?? 0)
                let right = (rhs.height ?? 0, rhs.tbr ?? 0)
                return left < right
            }

        guard let format = progressive else { throw YTDLPError.noPlayableFormat }
        guard let playableURL = URL(string: format.url) else { throw YTDLPError.invalidURL }

        return ResolvedSource(
            url: playableURL,
            provider: "yt-dlp",
            title: info.title,
            httpHeaders: format.http_headers
        )
    }

    private func runWithTimeout<Value>(
        seconds: Double,
        operation: @escaping () async throws -> Value
    ) async throws -> Value {
        try await withCheckedThrowingContinuation { continuation in
            let gate = YTDLPContinuationGate(continuation)

            Task.detached(priority: .userInitiated) {
                do { gate.finish(.success(try await operation())) }
                catch { gate.finish(.failure(error)) }
            }

            Task.detached {
                try? await Task.sleep(for: .seconds(seconds))
                gate.finish(.failure(YTDLPError.extractionTimedOut))
            }
        }
    }

    private func getBridge() -> YoutubeDL {
        if let youtubeDL { return youtubeDL }
        let bridge = YoutubeDL()
        youtubeDL = bridge
        return bridge
    }

    private func discoverLoadedVersion() async -> String? {
        do { try prepareRuntimeDirectories() }
        catch { return defaults.string(forKey: Keys.installedVersion) }

        let bridge = getBridge()
        if let version = bridge.version, !version.isEmpty { return version }
        return defaults.string(forKey: Keys.installedVersion)
    }

    private func releaseVersion(from response: URLResponse) -> String? {
        guard let components = response.url?.pathComponents,
              let downloadIndex = components.firstIndex(of: "download"),
              components.indices.contains(downloadIndex + 1) else { return nil }
        let candidate = components[downloadIndex + 1]
        return candidate.isEmpty ? nil : candidate
    }

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
''')

resolver = ROOT / 'SourceResolver.swift'
replace_once(resolver, '        case torBoxFailed(String)\n', '        case torBoxFailed(String)\n        case ytdlpFailed(String)\n')
replace_once(resolver, '            case .torBoxFailed(let message): return "TorBox failed: \\(message)"\n', '            case .torBoxFailed(let message): return "TorBox failed: \\(message)"\n            case .ytdlpFailed(let message): return "yt-dlp failed: \\(message)"\n')
replace_once(resolver, '''        if settings.ytdlpEnabled, !looksLikeDirectMedia(url) {
            do {
                return try await ytdlp.resolve(url: url, status: status)
            } catch {
                await status("yt-dlp failed; trying the URL directly…")
            }
        }

        await status("Opening media URL…")
''', '''        if settings.ytdlpEnabled, !looksLikeDirectMedia(url) {
            do {
                return try await ytdlp.resolve(url: url, status: status)
            } catch {
                throw ResolverError.ytdlpFailed(error.localizedDescription)
            }
        }

        await status("Opening media URL…")
''')

advanced = ROOT / 'AdvancedSettingsView.swift'
replace_once(advanced, '    @State private var isUpdatingYTDLP = false\n    @State private var mpvVersion = "Checking…"\n', '    @State private var isUpdatingYTDLP = false\n    @State private var showingDeleteYTDLPConfirmation = false\n    @State private var mpvVersion = "Checking…"\n')
replace_once(advanced, '''                    .disabled(isUpdatingYTDLP)

                    if let ytdlpMessage {
''', '''                    .disabled(isUpdatingYTDLP)

                    Button("Delete downloaded yt-dlp", role: .destructive) {
                        showingDeleteYTDLPConfirmation = true
                    }
                    .disabled(isUpdatingYTDLP || ytdlpVersion == "Not installed")

                    if let ytdlpMessage {
''')
replace_once(advanced, '''            .confirmationDialog(
                "Erase all MPV settings?",
''', '''            .confirmationDialog(
                "Delete downloaded yt-dlp?",
                isPresented: $showingDeleteYTDLPConfirmation,
                titleVisibility: .visible
            ) {
                Button("Delete yt-dlp", role: .destructive) { deleteYTDLP() }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("The downloaded yt-dlp module and cache will be removed. The bundled Python runtime remains installed.")
            }
            .confirmationDialog(
                "Erase all MPV settings?",
''')
replace_once(advanced, '    private func updateYTDLP() {\n', '''    private func deleteYTDLP() {
        isUpdatingYTDLP = true
        ytdlpMessage = "Deleting yt-dlp…"

        Task { @MainActor in
            defer { isUpdatingYTDLP = false }
            do {
                let status = try await YTDLPService.shared.deleteModule { message in
                    ytdlpMessage = message
                }
                ytdlpVersion = status.displayVersion
                if status.restartRequired {
                    ytdlpMessage = "yt-dlp was deleted. Close and reopen MPV once to unload the Python module."
                }
            } catch {
                ytdlpMessage = "Delete failed: \(error.localizedDescription)"
                refreshVersions()
            }
        }
    }

    private func updateYTDLP() {
''')

stats_overlay = ROOT / 'Views' / 'StatsOverlay.swift'
stats_overlay.write_text(r'''import SwiftUI

struct StatsOverlay: View {
    let page: Int
    let stats: MPVStats
    let tracks: [MPVTrack]
    let position: Double
    let duration: Double
    let speed: Double
    let volume: Double

    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: .medium, design: .monospaced))
            .foregroundStyle(.white)
            .padding(10)
            .background(Color.black.opacity(0.78), in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white.opacity(0.15), lineWidth: 1))
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityLabel("Playback statistics page \(page)")
    }

    private var text: String {
        switch page {
        case 2:
            return """
            PAGE 2 — VIDEO RENDERING
            Resolution: \(stats.resolution)
            Video: \(stats.videoCodec)  \(stats.pixelFormat)
            Decoder: \(stats.hardwareDecoder)
            Video FPS: \(stats.videoFPS)
            Display: \(stats.displayFPS)
            Decoder drops: \(stats.decoderDrops)
            Output drops: \(stats.outputDrops)
            Mistimed / delayed: \(stats.mistimedFrames) / \(stats.delayedFrames)
            A/V sync: \(stats.avSync)
            """
        case 3:
            return """
            PAGE 3 — CACHE & NETWORK
            Cache duration: \(stats.cacheDuration)
            Cache speed: \(stats.cacheSpeed)
            Video bitrate: \(stats.videoBitrate)
            Audio bitrate: \(stats.audioBitrate)
            Position: \(formatTime(position)) / \(formatTime(duration))
            Speed: \(String(format: "%.2fx", speed))
            """
        case 4:
            return """
            PAGE 4 — ACTIVE CONTROLS
            Tap: show / hide controls
            Bottom drag: seek
            Upper-left drag: brightness
            Upper-right drag: volume
            SPACE: pause
            LEFT / RIGHT: seek
            i / Shift+i: official stats.lua
            1–5: stats pages
            """
        case 5:
            let selected = tracks.filter(\.selected)
            let lines = selected.isEmpty
                ? "No selected track information"
                : selected.map { "\($0.kind.title): \($0.displayName)" }.joined(separator: "\n")
            return "PAGE 5 — SELECTED TRACKS\n\(lines)"
        default:
            return """
            PAGE 1 — GENERAL PLAYBACK
            \(stats.mediaTitle)
            Container: \(stats.container)  Size: \(stats.fileSize)
            Resolution: \(stats.resolution)
            Video: \(stats.videoCodec)  \(stats.pixelFormat)
            Decoder: \(stats.hardwareDecoder)
            Audio: \(stats.audioCodec)  \(stats.audioLayout)  \(stats.sampleRate)
            FPS: \(stats.videoFPS)  Display: \(stats.displayFPS)
            Bitrate V/A: \(stats.videoBitrate) / \(stats.audioBitrate)
            Drops decoder/VO: \(stats.decoderDrops) / \(stats.outputDrops)
            Position: \(formatTime(position)) / \(formatTime(duration))
            Volume: \(Int(volume))%  Speed: \(String(format: "%.2fx", speed))
            """
        }
    }

    private func formatTime(_ value: Double) -> String {
        guard value.isFinite, value >= 0 else { return "00:00" }
        let total = Int(value.rounded())
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let seconds = total % 60
        if hours > 0 { return String(format: "%d:%02d:%02d", hours, minutes, seconds) }
        return String(format: "%02d:%02d", minutes, seconds)
    }
}
''')

player = ROOT / 'Views' / 'PlayerScreen.swift'
replace_once(player, '    @State private var forcedLandscape = false\n', '    @State private var forcedLandscape = false\n    @State private var nativeStatsPage = 0\n    @State private var nativeStatsPersistent = false\n    @State private var nativeStatsHideTask: Task<Void, Never>?\n')
replace_once(player, '''                MPVMetalPlayerView(coordinator: coordinator)
                    .play(source)
''', '''                MPVMetalPlayerView(coordinator: coordinator, viewportSize: geometry.size)
                    .play(source)
''')
replace_once(player, '''                if let gestureMessage {
                    Text(gestureMessage)
                        .font(.headline.monospacedDigit())
                        .foregroundStyle(.white)
                        .padding(.horizontal, 18)
                        .padding(.vertical, 12)
                        .background(Color.black.opacity(0.72), in: Capsule())
                }

                if controlsVisible && !controlsLocked {
''', '''                if let gestureMessage {
                    Text(gestureMessage)
                        .font(.headline.monospacedDigit())
                        .foregroundStyle(.white)
                        .padding(.horizontal, 18)
                        .padding(.vertical, 12)
                        .background(Color.black.opacity(0.72), in: Capsule())
                }

                if nativeStatsPage > 0 {
                    VStack {
                        HStack {
                            StatsOverlay(
                                page: nativeStatsPage,
                                stats: coordinator.stats,
                                tracks: coordinator.tracks,
                                position: coordinator.position,
                                duration: coordinator.duration,
                                speed: coordinator.speed,
                                volume: coordinator.volume
                            )
                            .frame(maxWidth: min(geometry.size.width * 0.72, 560), alignment: .leading)
                            Spacer()
                        }
                        Spacer()
                    }
                    .padding(.top, 58)
                    .padding(.horizontal, 12)
                    .allowsHitTesting(false)
                }

                if controlsVisible && !controlsLocked {
''')
replace_once(player, '            hideControlsTask?.cancel()\n            OrientationManager.restore()\n', '            hideControlsTask?.cancel()\n            nativeStatsHideTask?.cancel()\n            OrientationManager.restore()\n')
text = player.read_text()
start = text.index('    private func gestureLayer(size: CGSize) -> some View {')
end = text.index('\n    private func controls(size: CGSize) -> some View {', start)
new_gesture = r'''    private func gestureLayer(size: CGSize) -> some View {
        Color.clear
            .contentShape(Rectangle())
            .onTapGesture {
                guard !controlsLocked else { return }
                hideControlsTask?.cancel()
                withAnimation(.easeInOut(duration: 0.15)) {
                    controlsVisible.toggle()
                }
                if controlsVisible { showControlsTemporarily() }
            }
            .gesture(
                LongPressGesture(minimumDuration: 0.12, maximumDistance: 24)
                    .sequenced(before: DragGesture(minimumDistance: 0))
                    .onChanged { value in
                        guard !controlsLocked else { return }
                        if case .second(true, let drag?) = value {
                            handleDragChanged(drag, size: size)
                        }
                    }
                    .onEnded { value in
                        guard !controlsLocked else { return }
                        if case .second(true, _) = value { handleDragEnded() }
                    }
            )
    }
'''
player.write_text(text[:start] + new_gesture + text[end:])
text = player.read_text()
text = text.replace('                coordinator.showStatsTemporarily()\n                showControlsTemporarily()\n', '                showNativeStatsTemporarily()\n                showControlsTemporarily()\n', 1)
text = text.replace('                coordinator.toggleStats()\n                showControlsTemporarily()\n', '                toggleNativeStats()\n                showControlsTemporarily()\n', 1)
text = text.replace('                    coordinator.showStatsPage(page)\n                    showControlsTemporarily()\n', '                    showNativeStatsPage(page)\n                    showControlsTemporarily()\n', 1)
player.write_text(text)
replace_once(player, '''            if abs(value.translation.width) > abs(value.translation.height) {
                gestureMode = .seek
            } else {
                gestureMode = value.startLocation.x < size.width / 2 ? .brightness : .volume
            }
''', '''            let seekRegionStartsAt = size.height * 0.56
            if value.startLocation.y >= seekRegionStartsAt {
                gestureMode = .seek
            } else {
                gestureMode = value.startLocation.x < size.width / 2 ? .brightness : .volume
            }
''')
replace_once(player, '    private func flash(_ text: String) {\n', '''    private func showNativeStatsTemporarily() {
        nativeStatsHideTask?.cancel()
        nativeStatsPersistent = false
        nativeStatsPage = 1
        nativeStatsHideTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled, !nativeStatsPersistent else { return }
            nativeStatsPage = 0
        }
    }

    private func toggleNativeStats() {
        nativeStatsHideTask?.cancel()
        if nativeStatsPage > 0 && nativeStatsPersistent {
            nativeStatsPage = 0
            nativeStatsPersistent = false
        } else {
            nativeStatsPage = max(nativeStatsPage, 1)
            nativeStatsPersistent = true
        }
    }

    private func showNativeStatsPage(_ page: Int) {
        nativeStatsHideTask?.cancel()
        nativeStatsPage = min(max(page, 1), 5)
        nativeStatsPersistent = true
    }

    private func flash(_ text: String) {
''')

bridge = ROOT / 'Player' / 'MPVMetalPlayerView.swift'
replace_once(bridge, '    @ObservedObject var coordinator: Coordinator\n', '    @ObservedObject var coordinator: Coordinator\n    var viewportSize: CGSize = .zero\n')
replace_once(bridge, '        uiViewController.refreshVideoSurface()\n', '        uiViewController.refreshVideoSurface(viewportSize: viewportSize, reconfigure: true)\n        DispatchQueue.main.async {\n            uiViewController.refreshVideoSurface(viewportSize: viewportSize, reconfigure: true)\n        }\n')

metal = ROOT / 'Player' / 'MPVMetalViewController.swift'
replace_once(metal, '''    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        refreshVideoSurface()
    }
''', '''    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        refreshVideoSurface(reconfigure: true)
    }
''')
replace_once(metal, '''        coordinator.animate(alongsideTransition: { [weak self] _ in
            self?.refreshVideoSurface()
        }, completion: { [weak self] _ in
            self?.refreshVideoSurface(reconfigure: true)
        })
''', '''        coordinator.animate(alongsideTransition: { [weak self] _ in
            self?.refreshVideoSurface(viewportSize: size, reconfigure: true)
        }, completion: { [weak self] _ in
            self?.scheduleSurfaceRefreshes(preferredSize: size)
        })
''')
replace_once(metal, '''    func refreshVideoSurface(reconfigure: Bool = false) {
        guard isViewLoaded else { return }
        let bounds = view.bounds
        guard bounds.width > 1, bounds.height > 1 else { return }
''', '''    func refreshVideoSurface(viewportSize: CGSize? = nil, reconfigure: Bool = false) {
        guard isViewLoaded else { return }
        let requestedSize = viewportSize.flatMap { $0.width > 1 && $0.height > 1 ? $0 : nil }
        let currentSize = requestedSize ?? view.window?.bounds.size ?? view.bounds.size
        let bounds = CGRect(origin: .zero, size: currentSize)
        guard bounds.width > 1, bounds.height > 1 else { return }
''')
replace_once(metal, '''        if reconfigure {
            command("video-reconfig", args: [])
        }
    }
''', '''        if reconfigure || sizeChanged {
            command("video-reconfig", args: [])
        }
    }

    private func scheduleSurfaceRefreshes(preferredSize: CGSize? = nil) {
        for delay in [0.0, 0.05, 0.15, 0.35, 0.70] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                guard let self else { return }
                self.view.setNeedsLayout()
                self.view.layoutIfNeeded()
                self.refreshVideoSurface(viewportSize: preferredSize, reconfigure: true)
            }
        }
    }
''')
replace_once(metal, '            check(mpv_set_option_string(context, "script", statsScript.path))\n', '            check(mpv_set_option_string(context, "scripts", statsScript.path))\n')
replace_once(metal, '''    @objc private func deviceOrientationDidChange() {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.view.setNeedsLayout()
            self.view.layoutIfNeeded()
            self.refreshVideoSurface(reconfigure: true)
        }
    }
''', '''    @objc private func deviceOrientationDidChange() {
        scheduleSurfaceRefreshes(preferredSize: view.window?.bounds.size)
    }
''')

project = Path('project.yml')
replace_once(project, '        MARKETING_VERSION: 1.3.0\n        CURRENT_PROJECT_VERSION: 13\n', '        MARKETING_VERSION: 1.4.0\n        CURRENT_PROJECT_VERSION: 14\n')

print('Applied yt-dlp timeout/delete, native stats fallback, rotation retries, tap toggle, and regional gestures.')
