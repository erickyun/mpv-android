from pathlib import Path

ROOT = Path('MPVTorBox')
PROJECT = Path('project.yml')


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'Expected pattern not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1))


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

    static let webKitPluginVersion = "0.1.1"

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
        case missingBundledWebKitPlugin
        case invalidBundledWebKitPlugin
        case webKitPluginRequiresRestart

        var errorDescription: String? {
            switch self {
            case .noPlayableFormat:
                return "yt-dlp did not return a playable audio/video format."
            case .invalidURL:
                return "The yt-dlp result contained an invalid media URL."
            case .invalidDownload:
                return "The downloaded yt-dlp module could not be installed."
            case .versionUnavailable:
                return "yt-dlp was installed, but its version could not be detected."
            case .extractionTimedOut:
                return "yt-dlp did not finish within 25 seconds. Close and reopen MPV, update yt-dlp, and try again."
            case .missingBundledWebKitPlugin:
                return "The bundled Apple WebKit JavaScript provider is missing from this MPV build."
            case .invalidBundledWebKitPlugin:
                return "The bundled Apple WebKit JavaScript provider is invalid."
            case .webKitPluginRequiresRestart:
                return "The Apple WebKit JavaScript provider was installed. Close and reopen MPV once, then try YouTube again."
            }
        }
    }

    private enum Keys {
        static let installedVersion = "ytdlp_installed_version"
        static let webKitPluginVersion = "ytdlp_webkit_plugin_version"
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

        return ModuleStatus(installed: true, version: nil, restartRequired: false)
    }

    func deleteModule(
        status: @escaping @MainActor (String) -> Void
    ) async throws -> ModuleStatus {
        try prepareRuntimeDirectories()
        let runtimeWasLoaded = youtubeDL?.version != nil
        await status("Deleting the downloaded yt-dlp module and WebKit provider…")

        let fileManager = FileManager.default
        let moduleURL = YoutubeDL.pythonModuleURL
        let parent = moduleURL.deletingLastPathComponent()
        let backupURL = parent.appendingPathComponent("yt_dlp.previous")
        let cacheURL = fileManager.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("yt-dlp", isDirectory: true)

        if fileManager.fileExists(atPath: moduleURL.path) { try fileManager.removeItem(at: moduleURL) }
        try? fileManager.removeItem(at: backupURL)
        try? fileManager.removeItem(at: cacheURL)
        try? fileManager.removeItem(at: webKitPluginDestinationURL())
        youtubeDL = nil
        defaults.removeObject(forKey: Keys.installedVersion)
        defaults.removeObject(forKey: Keys.webKitPluginVersion)
        await status("yt-dlp and the Apple WebKit provider were deleted.")

        return ModuleStatus(installed: false, version: nil, restartRequired: runtimeWasLoaded)
    }

    func updateModule(
        status: @escaping @MainActor (String) -> Void
    ) async throws -> ModuleStatus {
        try prepareRuntimeDirectories()
        let oldStatus = await moduleStatus()
        let runtimeWasLoaded = youtubeDL?.version != nil

        await status("Installing the bundled Apple WebKit JavaScript provider…")
        _ = try installBundledWebKitPlugin()

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
        defaults.set(Self.webKitPluginVersion, forKey: Keys.webKitPluginVersion)

        let oldVersion = oldStatus.version ?? "unknown"
        let newVersion = downloadedVersion ?? "version detected on next use"
        await status("yt-dlp updated: \(oldVersion) → \(newVersion). WebKit JSI \(Self.webKitPluginVersion) is ready.")

        return ModuleStatus(installed: true, version: downloadedVersion, restartRequired: runtimeWasLoaded)
    }

    func resolve(
        url: URL,
        status: @escaping @MainActor (String) -> Void
    ) async throws -> ResolvedSource {
        try prepareRuntimeDirectories()
        await status("Preparing Apple WebKit JavaScript challenge support…")
        let pluginInstalledNow = try installBundledWebKitPlugin()
        if pluginInstalledNow, youtubeDL != nil {
            youtubeDL = nil
            throw YTDLPError.webKitPluginRequiresRestart
        }

        await status("Starting the local Python, yt-dlp, and WebKit JSI runtime…")
        let bridge = getBridge()
        await status("Solving the website URL with yt-dlp…")
        let result: ([Format], Info) = try await runWithTimeout(seconds: 25) {
            try await bridge.extractInfo(url: url)
        }
        let selectedFormats = result.0
        let info = result.1

        if let version = bridge.version, !version.isEmpty {
            defaults.set(version, forKey: Keys.installedVersion)
        }
        defaults.set(Self.webKitPluginVersion, forKey: Keys.webKitPluginVersion)
        await status("Selecting the best playable audio/video stream…")

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
            provider: "yt-dlp + Apple WebKit JSI",
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

    private func releaseVersion(from response: URLResponse) -> String? {
        guard let components = response.url?.pathComponents,
              let downloadIndex = components.firstIndex(of: "download"),
              components.indices.contains(downloadIndex + 1) else { return nil }
        let candidate = components[downloadIndex + 1]
        return candidate.isEmpty ? nil : candidate
    }

    private func runtimeRootURL() -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MPV", isDirectory: true)
    }

    private func configHomeURL() -> URL {
        runtimeRootURL().appendingPathComponent("config", isDirectory: true)
    }

    private func webKitPluginDirectoryURL() -> URL {
        configHomeURL()
            .appendingPathComponent("yt-dlp", isDirectory: true)
            .appendingPathComponent("plugins", isDirectory: true)
    }

    private func webKitPluginDestinationURL() -> URL {
        webKitPluginDirectoryURL().appendingPathComponent("yt-dlp-apple-webkit-jsi.zip")
    }

    @discardableResult
    private func installBundledWebKitPlugin() throws -> Bool {
        let fileManager = FileManager.default
        guard let bundledURL = Bundle.main.url(
            forResource: "yt-dlp-apple-webkit-jsi",
            withExtension: "zip"
        ) else {
            throw YTDLPError.missingBundledWebKitPlugin
        }

        let data = try Data(contentsOf: bundledURL, options: [.mappedIfSafe])
        guard data.count > 10_000,
              data[data.startIndex] == 0x50,
              data[data.index(after: data.startIndex)] == 0x4B else {
            throw YTDLPError.invalidBundledWebKitPlugin
        }

        let destination = webKitPluginDestinationURL()
        try fileManager.createDirectory(
            at: destination.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )

        let installedVersion = defaults.string(forKey: Keys.webKitPluginVersion)
        let destinationSize = (try? fileManager.attributesOfItem(atPath: destination.path)[.size] as? NSNumber)?.intValue
        let needsInstall = !fileManager.fileExists(atPath: destination.path)
            || destinationSize != data.count
            || installedVersion != Self.webKitPluginVersion

        guard needsInstall else { return false }

        let temporary = destination.deletingLastPathComponent()
            .appendingPathComponent("yt-dlp-apple-webkit-jsi.installing.zip")
        try? fileManager.removeItem(at: temporary)
        try data.write(to: temporary, options: .atomic)
        try? fileManager.removeItem(at: destination)
        try fileManager.moveItem(at: temporary, to: destination)
        defaults.set(Self.webKitPluginVersion, forKey: Keys.webKitPluginVersion)
        return true
    }

    private func prepareRuntimeDirectories() throws {
        let fileManager = FileManager.default
        let applicationSupport = runtimeRootURL()
        let configHome = configHomeURL()
        let cache = fileManager.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("yt-dlp", isDirectory: true)

        try fileManager.createDirectory(at: applicationSupport, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: configHome, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: webKitPluginDirectoryURL(), withIntermediateDirectories: true)
        try fileManager.createDirectory(at: cache, withIntermediateDirectories: true)

        setenv("HOME", applicationSupport.path, 1)
        setenv("XDG_CONFIG_HOME", configHome.path, 1)
        setenv("XDG_CACHE_HOME", cache.path, 1)
        setenv("TMPDIR", NSTemporaryDirectory(), 1)
    }
}
''')

advanced = ROOT / 'AdvancedSettingsView.swift'
replace_once(
    advanced,
    '                    LabeledContent("Installed version", value: ytdlpVersion)\n',
    '                    LabeledContent("Installed version", value: ytdlpVersion)\n                    LabeledContent("YouTube JS provider", value: "Apple WebKit JSI 0.1.1")\n'
)
replace_once(
    advanced,
    '                  footer: { Text("The Python runtime is bundled. The first use downloads yt-dlp automatically. Update removes the previous downloaded module and installs the latest official release.") }\n',
    '                  footer: { Text("The Python runtime and Apple WebKit JavaScript provider are bundled. The first use downloads yt-dlp automatically. YouTube challenge solving uses the on-device WebKit engine.") }\n'
)

project_text = PROJECT.read_text()
project_text = project_text.replace('        MARKETING_VERSION: 1.5.0\n', '        MARKETING_VERSION: 1.6.0\n', 1)
project_text = project_text.replace('        CURRENT_PROJECT_VERSION: 15\n', '        CURRENT_PROJECT_VERSION: 16\n', 1)
PROJECT.write_text(project_text)

print('Applied bundled Apple WebKit JSI provider for current YouTube yt-dlp extraction.')
