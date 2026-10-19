from pathlib import Path

ROOT = Path("MPVTorBox")
CONTENT = ROOT / "ContentView.swift"
SERVICE = ROOT / "ZIPPlaybackService.swift"

def replace_once(path, old, new, label):
    text = path.read_text()
    if old not in text:
        raise SystemExit("Remote ZIP: missing " + label + " in " + str(path))
    path.write_text(text.replace(old, new, 1))

# Do not copy remote downloads a second time: the downloader already owns a
# sandboxed copy in Caches/MPVZIP/<uuid>/Archive.zip.
replace_once(
    SERVICE,
    "    func importArchive(_ incomingURL: URL) throws -> MediaPlaylistSelection {\n",
    "    func importArchive(_ incomingURL: URL, alreadyInCache: Bool = false) throws -> MediaPlaylistSelection {\n",
    "importArchive signature",
)
replace_once(
    SERVICE,
    '''        let fm = FileManager.default
        let root = fm.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MPVZIP", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)

        // DocumentPicker's copy may only be temporary; keep a sandbox copy for
        // playlist selection, subsequent seeking, and multiple video choices.
        let zipURL = root.appendingPathComponent("Archive.zip")
        try fm.copyItem(at: incomingURL, to: zipURL)

        let archive = try Archive(url: zipURL, accessMode: .read)
''',
    '''        let fm = FileManager.default
        let root: URL
        let zipURL: URL
        if alreadyInCache {
            // Remote ZIP was saved by URLSession directly to our private cache.
            root = incomingURL.deletingLastPathComponent()
            zipURL = incomingURL
        } else {
            root = fm.urls(for: .cachesDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("MPVZIP", isDirectory: true)
                .appendingPathComponent(UUID().uuidString, isDirectory: true)
            try fm.createDirectory(at: root, withIntermediateDirectories: true)
            zipURL = root.appendingPathComponent("Archive.zip")
            try fm.copyItem(at: incomingURL, to: zipURL)
        }

        let archive = try Archive(url: zipURL, accessMode: .read)
''',
    "avoid duplicate remote ZIP",
)
replace_once(
    SERVICE,
    "    private init() {}\n",
    '''    private init() {}

    // HTTP URL detection happens before yt-dlp/MPV routing. Do not HEAD-probe
    // unrelated URLs (especially YouTube), since that harms video startup.
    static func remoteZIPURL(from input: String) -> URL? {
        guard let url = URL(string: input.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme),
              url.host != nil else { return nil }

        if ["zip", "cbz"].contains(url.pathExtension.lowercased()) { return url }
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        let recognized = Set(["filename", "file", "name", "attachment", "response-content-disposition"])
        if components?.queryItems?.contains(where: { item in
            recognized.contains(item.name.lowercased()) &&
            (item.value ?? "").lowercased().contains(".zip")
        }) == true {
            return url
        }
        return nil
    }

    func importRemoteArchive(
        _ url: URL,
        status: @escaping @MainActor @Sendable (String) -> Void
    ) async throws -> MediaPlaylistSelection {
        let localURL = try await RemoteZIPDownloader.download(url, status: status)
        status("Reading ZIP file list…")
        return try importArchive(localURL, alreadyInCache: true)
    }
''',
    "remote ZIP import method",
)

downloader = r'''import Foundation

/// Downloads a remote ZIP to a private cache *before* libarchive plays the
/// chosen entry via the existing iosarchive:// mpv custom stream protocol.
/// ZIP is not a progressive video container: arbitrary HTTP ZIP endpoints
/// cannot be passed straight to MPV as movie URLs.
private final class RemoteZIPDownloader: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    enum DownloadError: LocalizedError {
        case server(Int)
        case tooLarge
        case invalidResponse
        case noStorage

        var errorDescription: String? {
            switch self {
            case .server(let status): return "ZIP server returned HTTP \(status). Check the URL or login."
            case .tooLarge: return "Remote ZIP exceeds the 12 GB download limit."
            case .invalidResponse: return "Remote ZIP could not be downloaded."
            case .noStorage: return "Not enough device storage to download this ZIP."
            }
        }
    }

    private static let maxBytes: Int64 = 12 * 1024 * 1024 * 1024
    private let destination: URL
    private let status: @MainActor @Sendable (String) -> Void
    private let lock = NSLock()
    private var continuation: CheckedContinuation<URL, Error>?
    private var result: Result<URL, Error>?
    private weak var session: URLSession?

    private init(
        destination: URL,
        status: @escaping @MainActor @Sendable (String) -> Void,
        continuation: CheckedContinuation<URL, Error>
    ) {
        self.destination = destination
        self.status = status
        self.continuation = continuation
        super.init()
    }

    static func download(
        _ url: URL,
        status: @escaping @MainActor @Sendable (String) -> Void
    ) async throws -> URL {
        let cacheRoot = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MPVZIP", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: cacheRoot, withIntermediateDirectories: true)
        let dest = cacheRoot.appendingPathComponent("Archive.zip")
        do {
            return try await withCheckedThrowingContinuation { continuation in
                let delegate = RemoteZIPDownloader(
                    destination: dest,
                    status: status,
                    continuation: continuation
                )
                let config = URLSessionConfiguration.default
                config.timeoutIntervalForRequest = 45 // no network progress
                config.timeoutIntervalForResource = 3600 // large archives
                config.waitsForConnectivity = false
                let session = URLSession(configuration: config, delegate: delegate, delegateQueue: nil)
                delegate.session = session
                var request = URLRequest(url: url)
                request.setValue("application/zip, application/octet-stream;q=0.9, */*;q=0.8", forHTTPHeaderField: "Accept")
                let task = session.downloadTask(with: request)
                task.resume()
            }
        } catch {
            try? FileManager.default.removeItem(at: cacheRoot)
            throw error
        }
    }

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didWriteData bytesWritten: Int64,
        totalBytesWritten received: Int64,
        totalBytesExpectedToWrite expected: Int64
    ) {
        if received > Self.maxBytes ||
           (expected > Self.maxBytes) {
            lock.lock()
            result = .failure(DownloadError.tooLarge)
            lock.unlock()
            downloadTask.cancel()
            return
        }

        let receivedMB = Double(received) / 1_048_576
        let text: String
        if expected > 0 {
            let percentage = Int((Double(received) / Double(expected) * 100).rounded())
            text = String(format: "Downloading ZIP… %d%% (%.1f / %.1f MB)",
                          min(100, percentage), receivedMB, Double(expected) / 1_048_576)
        } else {
            text = String(format: "Downloading ZIP… %.1f MB received", receivedMB)
        }
        Task { @MainActor in status(text) }
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        let outcome: Result<URL, Error>
        if let http = downloadTask.response as? HTTPURLResponse,
           !(200...299).contains(http.statusCode) {
            outcome = .failure(DownloadError.server(http.statusCode))
        } else {
            do {
                let manager = FileManager.default
                let free = try? destination.deletingLastPathComponent()
                    .resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
                    .volumeAvailableCapacityForImportantUsage
                let size = (try? manager.attributesOfItem(atPath: location.path)[.size] as? NSNumber)?.int64Value ?? 0
                if let free, free < size + 64 * 1024 * 1024 {
                    outcome = .failure(DownloadError.noStorage)
                } else {
                    try manager.moveItem(at: location, to: destination)
                    outcome = .success(destination)
                }
            } catch {
                outcome = .failure(error)
            }
        }
        lock.lock()
        result = outcome
        lock.unlock()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        lock.lock()
        let outcome = result
        result = nil
        let continuation = self.continuation
        self.continuation = nil
        lock.unlock()
        guard let continuation else {
            session.finishTasksAndInvalidate()
            return
        }
        if let outcome {
            continuation.resume(with: outcome)
        } else if let error {
            continuation.resume(throwing: error)
        } else {
            continuation.resume(throwing: DownloadError.invalidResponse)
        }
        session.finishTasksAndInvalidate()
    }
}
'''
# Append only once. No extra Swift target registration is needed with the app
# directory glob in project.yml.
with SERVICE.open("a") as handle:
    handle.write("\n" + downloader)

# Route recognized ZIP URLs before general playlists/ytdlp. Other URL behavior
# is preserved exactly (important for YouTube and site-specific hooks).
replace_once(
    CONTENT,
    '''        Task {
            do {
                if !skipPlaylistPicker {
                    do {
                        if let selection = try await resolver.playlistSelection(
''',
    '''        Task {
            do {
                if !skipPlaylistPicker,
                   let remoteZIP = ZIPPlaybackService.remoteZIPURL(from: input) {
                    statusText = "Connecting to ZIP URL…"
                    let selection = try await ZIPPlaybackService.shared.importRemoteArchive(
                        remoteZIP,
                        status: { message in statusText = message }
                    )
                    activePlaylist = selection
                    currentPlaylistItemID = nil
                    if selection.items.count > 1 {
                        playlistSelection = selection
                        statusText = "Choose a ZIP video (\\(selection.items.count) items)."
                        isResolving = false
                        return
                    }
                    if let first = selection.items.first {
                        var resolved = try await resolver.resolve(
                            first.input, settings: providerSettings
                        ) { message in statusText = message }
                        resolved.title = first.title
                        currentPlaylistItemID = first.id
                        play(resolved)
                        statusText = "Playing ZIP video through libarchive."
                        isResolving = false
                        return
                    }
                }
                if !skipPlaylistPicker {
                    do {
                        if let selection = try await resolver.playlistSelection(
''',
    "ContentView openSource routing",
)
print("Added HTTP/HTTPS ZIP download, progress, timeout, storage checks and libarchive playback.")
