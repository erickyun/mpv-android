from pathlib import Path

ROOT = Path("MPVTorBox")
SERVICE = ROOT / "ZIPPlaybackService.swift"
STREAM = ROOT / "MPVArchiveProtocol.swift"

def replace_once(path, old, new, label):
    original = path.read_text()
    if old not in original:
        raise SystemExit(f"v49 {label} anchor missing in {path}")
    path.write_text(original.replace(old, new, 1))

# A bounded HTTP Range client. Never sends an unbounded GET, and refuses HTTP
# 200 responses to a Range request without reading the full response body.
range_client = r'''import Foundation
import libarchive

struct RemoteZIPEntry: Sendable {
    let path: String
    let size: Int64
    let storedOffset: Int64?
}

/// Network reads are synchronous only from detached tasks / libmpv worker
/// threads. The MPV read/seek callbacks must not wait on the main actor.
final class RemoteZIPRangeClient: @unchecked Sendable {
    enum RangeError: LocalizedError {
        case unavailable
        case invalidZIP
        case unsupportedZIP64
        case invalidResponse
        case networkTimeout
        case tooManyEntries

        var errorDescription: String? {
            switch self {
            case .unavailable:
                return "This ZIP server does not support HTTP Range (206 Partial Content). Streaming without a full download is unavailable."
            case .invalidZIP:
                return "The remote file is not a supported ZIP archive."
            case .unsupportedZIP64:
                return "ZIP64 directory metadata is not yet supported for remote ZIP playback."
            case .invalidResponse:
                return "ZIP server returned an invalid or changed byte range."
            case .networkTimeout:
                return "The ZIP server timed out while fetching a byte range."
            case .tooManyEntries:
                return "Remote ZIP contains too many entries."
            }
        }
    }

    let url: URL
    private(set) var fileSize: Int64 = 0

    private let blockSize: Int64 = 256 * 1024
    private let maxCachedBlocks = 96 // <=24 MiB of compressed ZIP bytes
    private let lock = NSLock()
    private var blocks: [Int64: Data] = [:]
    private var order: [Int64] = []
    private(set) var transferredBytes: Int64 = 0
    var onBytesTransferred: (@Sendable (Int64) -> Void)?

    init(url: URL) { self.url = url }

    func prepare() throws {
        let (bytes, response) = try request(start: 0, end: 0)
        guard bytes.count == 1,
              let (first, last, total) = Self.contentRange(response),
              first == 0, last == 0, total > 0 else {
            throw RangeError.unavailable
        }
        fileSize = total
    }

    private static func contentRange(_ response: HTTPURLResponse) -> (Int64, Int64, Int64)? {
        guard let value = response.value(forHTTPHeaderField: "Content-Range"),
              value.lowercased().hasPrefix("bytes ") else { return nil }
        let body = String(value.dropFirst(6))
        let slash = body.split(separator: "/", omittingEmptySubsequences: false)
        guard slash.count == 2, let total = Int64(slash[1]) else { return nil }
        let bounds = slash[0].split(separator: "-", omittingEmptySubsequences: false)
        guard bounds.count == 2,
              let first = Int64(bounds[0]),
              let last = Int64(bounds[1]),
              total > 0, first >= 0, last >= first, last < total else { return nil }
        return (first, last, total)
    }

    private func request(start: Int64, end: Int64) throws -> (Data, HTTPURLResponse) {
        guard start >= 0, end >= start, end - start <= blockSize else {
            throw RangeError.invalidResponse
        }
        var req = URLRequest(url: url)
        req.setValue("bytes=\(start)-\(end)", forHTTPHeaderField: "Range")
        req.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
        req.cachePolicy = .reloadIgnoringLocalCacheData
        // Request-level delegate aborts HTTP 200 before receiving the body;
        // URLSession.dataTask completion APIs otherwise buffer an entire ZIP.
        let exchange = BoundedHTTPRangeRequest(
            maximumBytes: Int(end - start + 1),
            timeout: 40
        )
        let (bytes, response) = try exchange.perform(req)
        guard response.statusCode == 206 else { throw RangeError.unavailable }
        guard let (first, last, total) = Self.contentRange(response),
              first == start, last == end,
              total == (fileSize > 0 ? fileSize : total),
              bytes.count == Int(end - start + 1) else {
            throw RangeError.invalidResponse
        }
        if let encoding = response.value(forHTTPHeaderField: "Content-Encoding"),
           encoding.lowercased() != "identity" {
            throw RangeError.invalidResponse
        }
        lock.lock()
        transferredBytes += Int64(bytes.count)
        let received = transferredBytes
        let notify = onBytesTransferred
        lock.unlock()
        notify?(received)
        return (bytes, response)
    }

    func read(at start: Int64, count: Int) throws -> Data {
        guard fileSize > 0, start >= 0, start <= fileSize, count >= 0 else {
            throw RangeError.invalidResponse
        }
        let desired = min(Int64(count), fileSize - start)
        if desired == 0 { return Data() }
        var result = Data()
        var offset = start
        while offset < start + desired {
            let block = offset / blockSize
            let blockStart = block * blockSize
            let chunk: Data
            lock.lock()
            if let cached = blocks[block] {
                order.removeAll { $0 == block }
                order.append(block)
                chunk = cached
                lock.unlock()
            } else {
                lock.unlock()
                let last = min(blockStart + blockSize, fileSize) - 1
                let fetched = try request(start: blockStart, end: last).0
                lock.lock()
                blocks[block] = fetched
                order.removeAll { $0 == block }
                order.append(block)
                while order.count > maxCachedBlocks {
                    let evict = order.removeFirst()
                    blocks.removeValue(forKey: evict)
                }
                lock.unlock()
                chunk = fetched
            }
            let index = Int(offset - blockStart)
            let wanted = Int(min(Int64(chunk.count - index), start + desired - offset))
            guard wanted > 0 else { throw RangeError.invalidResponse }
            result.append(contentsOf: chunk[index..<(index + wanted)])
            offset += Int64(wanted)
        }
        return result
    }

    private static func u16(_ data: Data, _ off: Int) -> Int {
        Int(data[off]) | (Int(data[off + 1]) << 8)
    }
    private static func u32(_ data: Data, _ off: Int) -> Int64 {
        Int64(data[off]) | (Int64(data[off + 1]) << 8)
            | (Int64(data[off + 2]) << 16) | (Int64(data[off + 3]) << 24)
    }

    /// The ZIP central directory normally lives at EOF. A few range reads
    /// locate it without downloading movie payloads.
    func videoEntries() throws -> [RemoteZIPEntry] {
        guard fileSize > 22 else { throw RangeError.invalidZIP }
        let tailLength = Int(min(fileSize, 65557))
        let tail = try read(at: fileSize - Int64(tailLength), count: tailLength)
        guard tail.count >= 22 else { throw RangeError.invalidZIP }
        var eocd: Int?
        for index in stride(from: tail.count - 22, through: 0, by: -1) {
            if Self.u32(tail, index) == 0x06054b50,
               index + 22 + Self.u16(tail, index + 20) == tail.count {
                eocd = index
                break
            }
        }
        guard let eocd else { throw RangeError.invalidZIP }
        let entryCount = Self.u16(tail, eocd + 10)
        let dirSize = Self.u32(tail, eocd + 12)
        let dirOffset = Self.u32(tail, eocd + 16)
        if entryCount == 65535 || dirSize == 0xffffffff || dirOffset == 0xffffffff {
            throw RangeError.unsupportedZIP64
        }
        guard entryCount <= 20000, dirSize >= 0, dirSize <= 16 * 1024 * 1024,
              dirOffset >= 0, dirOffset + dirSize <= fileSize else {
            throw RangeError.tooManyEntries
        }
        let directory = try read(at: dirOffset, count: Int(dirSize))
        var offset = 0
        var entries: [RemoteZIPEntry] = []
        let playable = Set([
            "mp4","mkv","mov","m4v","webm","avi","ts","m2ts",
            "flv","wmv","mpg","mpeg","ogv","mp3","m4a","aac",
            "flac","wav","ogg","opus","3gp"
        ])
        for _ in 0..<entryCount {
            guard offset + 46 <= directory.count,
                  Self.u32(directory, offset) == 0x02014b50 else {
                throw RangeError.invalidZIP
            }
            let flags = Self.u16(directory, offset + 8)
            let method = Self.u16(directory, offset + 10)
            let packed = Self.u32(directory, offset + 20)
            let unpacked = Self.u32(directory, offset + 24)
            let nameSize = Self.u16(directory, offset + 28)
            let extraSize = Self.u16(directory, offset + 30)
            let commentSize = Self.u16(directory, offset + 32)
            let localOffset = Self.u32(directory, offset + 42)
            let end = offset + 46 + nameSize + extraSize + commentSize
            guard end <= directory.count else { throw RangeError.invalidZIP }
            let rawName = directory.subdata(in: (offset + 46)..<(offset + 46 + nameSize))
            let name = String(data: rawName, encoding: .utf8)
                ?? String(data: rawName, encoding: .isoLatin1)
                ?? ""
            offset = end
            guard !name.hasSuffix("/"), !name.isEmpty,
                  flags & 1 == 0,
                  method == 0 || method == 8,
                  packed != 0xffffffff, unpacked != 0xffffffff,
                  localOffset != 0xffffffff else { continue }
            let ext = (name as NSString).pathExtension.lowercased()
            guard playable.contains(ext) else { continue }

            var storedOffset: Int64? = nil
            if method == 0 {
                guard localOffset + 30 <= fileSize else { throw RangeError.invalidZIP }
                let header = try read(at: localOffset, count: 30)
                guard header.count == 30, Self.u32(header, 0) == 0x04034b50 else {
                    throw RangeError.invalidZIP
                }
                let nameLen = Self.u16(header, 26)
                let extraLen = Self.u16(header, 28)
                let bodyStart = localOffset + Int64(30 + nameLen + extraLen)
                guard bodyStart + packed <= fileSize, packed == unpacked else {
                    throw RangeError.invalidZIP
                }
                storedOffset = bodyStart
            }
            entries.append(RemoteZIPEntry(path: name, size: unpacked, storedOffset: storedOffset))
        }
        if entries.isEmpty { throw RangeError.invalidZIP }
        return entries.sorted { $0.path.localizedStandardCompare($1.path) == .orderedAscending }
    }
}

/// A complete request with bounded memory, early HTTP 200 rejection, and a
/// 40-second timeout. No server can accidentally cause a multi-GB dataTask.
private final class BoundedHTTPRangeRequest: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let maxBytes: Int
    private let timeout: TimeInterval
    private let wait = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var body = Data()
    private var receivedResponse: HTTPURLResponse?
    private var failure: Error?
    private var completed = false

    init(maximumBytes: Int, timeout: TimeInterval) {
        self.maxBytes = maximumBytes
        self.timeout = timeout
    }

    func perform(_ request: URLRequest) throws -> (Data, HTTPURLResponse) {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.timeoutIntervalForResource = timeout
        config.waitsForConnectivity = false
        let session = URLSession(configuration: config, delegate: self, delegateQueue: nil)
        let task = session.dataTask(with: request)
        task.resume()
        if wait.wait(timeout: .now() + timeout + 2) == .timedOut {
            task.cancel()
            session.invalidateAndCancel()
            throw RemoteZIPRangeClient.RangeError.networkTimeout
        }
        session.finishTasksAndInvalidate()
        lock.lock()
        let data = body
        let response = receivedResponse
        let error = failure
        lock.unlock()
        if let error { throw error }
        guard let response else { throw RemoteZIPRangeClient.RangeError.invalidResponse }
        return (data, response)
    }

    func urlSession(
        _ session: URLSession, dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        guard let http = response as? HTTPURLResponse, http.statusCode == 206 else {
            lock.lock()
            failure = RemoteZIPRangeClient.RangeError.unavailable
            lock.unlock()
            completionHandler(.cancel)
            return
        }
        lock.lock()
        receivedResponse = http
        lock.unlock()
        completionHandler(.allow)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        lock.lock()
        if body.count + data.count > maxBytes {
            failure = RemoteZIPRangeClient.RangeError.invalidResponse
            lock.unlock()
            dataTask.cancel()
        } else {
            body.append(data)
            lock.unlock()
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        lock.lock()
        if failure == nil { failure = error }
        let signal = !completed
        completed = true
        lock.unlock()
        if signal { wait.signal() }
    }
}

/// The client speaks random-access HTTP Range. libarchive sees a seekable
/// stream and can locate central-directory entries without a whole ZIP GET.
final class RemoteArchiveCursor: @unchecked Sendable {
    private let client: RemoteZIPRangeClient
    private let block = UnsafeMutableRawPointer.allocate(byteCount: 128 * 1024, alignment: 16)
    private var location: Int64 = 0

    init(client: RemoteZIPRangeClient) { self.client = client }
    deinit { block.deallocate() }

    func attach(to archive: OpaquePointer) -> Int32 {
        archive_read_set_callback_data(archive, Unmanaged.passUnretained(self).toOpaque())
        archive_read_set_read_callback(archive) { _, cookie, out in
            guard let cookie else { return -1 }
            let object = Unmanaged<RemoteArchiveCursor>.fromOpaque(cookie).takeUnretainedValue()
            return object.read(out: out)
        }
        archive_read_set_seek_callback(archive) { _, cookie, offset, whence in
            guard let cookie else { return -1 }
            return Unmanaged<RemoteArchiveCursor>.fromOpaque(cookie)
                .takeUnretainedValue().seek(offset: offset, whence: whence)
        }
        archive_read_set_skip_callback(archive) { _, cookie, offset in
            guard let cookie, offset >= 0 else { return 0 }
            return Unmanaged<RemoteArchiveCursor>.fromOpaque(cookie)
                .takeUnretainedValue().skip(offset)
        }
        return archive_read_open1(archive)
    }

    private func read(out: UnsafeMutablePointer<UnsafeRawPointer?>?) -> Int {
        guard let out, location < client.fileSize else { return 0 }
        do {
            let count = Int(min(128 * 1024, client.fileSize - location))
            let data = try client.read(at: location, count: count)
            guard !data.isEmpty else { return 0 }
            data.copyBytes(to: block.assumingMemoryBound(to: UInt8.self), count: data.count)
            out.pointee = UnsafeRawPointer(block)
            location += Int64(data.count)
            return data.count
        } catch {
            print("[ZIP Range] read failed: \(error.localizedDescription)")
            return -1
        }
    }

    private func seek(offset: Int64, whence: Int32) -> Int64 {
        let base: Int64
        switch whence {
        case SEEK_SET: base = 0
        case SEEK_CUR: base = location
        case SEEK_END: base = client.fileSize
        default: return -1
        }
        let (newPosition, overflow) = base.addingReportingOverflow(offset)
        guard !overflow, newPosition >= 0, newPosition <= client.fileSize else { return -1 }
        location = newPosition
        return newPosition
    }

    private func skip(_ offset: Int64) -> Int64 {
        let (pos, overflow) = location.addingReportingOverflow(offset)
        guard !overflow, pos <= client.fileSize else { return 0 }
        location = pos
        return offset
    }
}
'''
(ROOT / "RemoteZIPRangeClient.swift").write_text(range_client)

# Remote ZIP is referenced by token, not copied to Caches. Local ZIP handling
# is untouched.
replace_once(
    SERVICE,
    "    private var opened: [String: ImportedZIP] = [:]\n",
    """    private var opened: [String: ImportedZIP] = [:]
    private var remoteClients: [String: RemoteZIPRangeClient] = [:]
""",
    "Remote client registry",
)
replace_once(
    SERVICE,
    '''        let localURL = try await RemoteZIPDownloader.download(url, status: status)
        status("Reading ZIP file list…")
        return try importArchive(localURL, alreadyInCache: true)
''',
    '''        status("Checking HTTP byte-range support…")
        let client = RemoteZIPRangeClient(url: url)
        let entries: [RemoteZIPEntry] = try await Task.detached(priority: .userInitiated) {
            try client.prepare()
            return try client.videoEntries()
        }.value
        let key = UUID().uuidString.lowercased()
        client.onBytesTransferred = { [status] total in
            Task { @MainActor in
                status(String(format: "ZIP Range fetched %.1f MB", Double(total) / 1_048_576))
            }
        }
        remoteClients[key] = client
        let videos = entries.map { item in
            ZIPItem(path: item.path, size: item.size, name: URL(fileURLWithPath: item.path).lastPathComponent)
        }
        let placeholder = URL(fileURLWithPath: "/remote-range/\\(key).zip")
        let root = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        opened[key] = ImportedZIP(url: placeholder, videos: videos, subtitles: [], root: root)
        return MediaPlaylistSelection(
            id: "zip:\\(key)",
            title: url.deletingPathExtension().lastPathComponent,
            provider: "HTTP Range ZIP",
            items: videos.enumerated().map { index, video in
                MediaPlaylistItem(
                    id: "zip:\\(key):\\(index)",
                    title: video.name,
                    input: "zipmedia://\\(key)/\\(index)",
                    duration: nil,
                    index: index + 1,
                    detail: ByteCountFormatter.string(fromByteCount: video.size, countStyle: .file)
                )
            }
        )
''',
    "avoid full ZIP download",
)
# Keep the ZIP metadata offset in the separate RemoteZIPEntry registry rather
# than adding fields to existing ZIPItem, preserving the v41 local parser.
replace_once(
    SERVICE,
    "    private var remoteClients: [String: RemoteZIPRangeClient] = [:]\n",
    """    private var remoteClients: [String: RemoteZIPRangeClient] = [:]
    private var remoteEntries: [String: [RemoteZIPEntry]] = [:]
""",
    "Remote entry registry",
)
replace_once(
    SERVICE,
    "        remoteClients[key] = client\n",
    "        remoteClients[key] = client\n        remoteEntries[key] = entries\n",
    "remember STORE offsets",
)
replace_once(
    SERVICE,
    '''        return MPVArchiveProtocol.shared.playbackURL(
            archiveURL: record.url,
            entryPath: video.path,
            size: video.size
        )
''',
    '''        if let remote = remoteClients[identifier],
           let entry = remoteEntries[identifier]?[index] {
            return MPVArchiveProtocol.shared.playbackRemoteZIP(
                client: remote,
                entryPath: entry.path,
                size: entry.size,
                storedOffset: entry.storedOffset
            )
        }
        return MPVArchiveProtocol.shared.playbackURL(
            archiveURL: record.url,
            entryPath: video.path,
            size: video.size
        )
''',
    "remote seekable movie routing",
)

replace_once(
    STREAM,
    '''        let archiveURL: URL
        let entryPath: String
        let size: Int64
''',
    '''        let archiveURL: URL?
        let remote: RemoteZIPRangeClient?
        let entryPath: String
        let size: Int64
        let storedOffset: Int64?
''',
    "mpv stream source model",
)
replace_once(
    STREAM,
    "sources[token] = Source(archiveURL: archiveURL, entryPath: entryPath, size: size)",
    "sources[token] = Source(archiveURL: archiveURL, remote: nil, entryPath: entryPath, size: size, storedOffset: nil)",
    "local playback unchanged",
)
replace_once(
    STREAM,
    '''    private func source(for token: String) -> Source? {
''',
    '''    func playbackRemoteZIP(
        client: RemoteZIPRangeClient,
        entryPath: String,
        size: Int64,
        storedOffset: Int64?
    ) -> URL {
        let token = UUID().uuidString.lowercased()
        lock.lock()
        sources[token] = Source(
            archiveURL: nil, remote: client,
            entryPath: entryPath, size: size, storedOffset: storedOffset
        )
        lock.unlock()
        let ext = URL(fileURLWithPath: entryPath).pathExtension
        return URL(string: "iosarchive://\\(token)/movie.\\(ext)")!
    }

    private func source(for token: String) -> Source? {
''',
    "MPV direct remote archive URL",
)
replace_once(
    STREAM,
    "    private var handle: OpaquePointer?\n",
    "    private var handle: OpaquePointer?\n    private var remoteCursor: RemoteArchiveCursor?\n",
    "libarchive remote cursor ownership",
)
replace_once(
    STREAM,
    '''        guard openEntry() else { return nil }
''',
    '''        // ZIP method STORE exposes the video byte range directly, so seeks
        // need one HTTP Range request near the requested byte offset.
        if source.remote == nil || source.storedOffset == nil {
            guard openEntry() else { return nil }
        }
''',
    "skip full libarchive for stored entry",
)
replace_once(
    STREAM,
    '''        if let old = handle { archive_read_free(old) }
        handle = archive_read_new()
        guard let handle else { return false }
        archive_read_support_filter_all(handle)
        archive_read_support_format_all(handle)
        let opened = source.archiveURL.path.withCString {
            archive_read_open_filename(handle, $0, 64 * 1024)
        }
''',
    '''        if let old = handle { archive_read_free(old) }
        remoteCursor = nil
        handle = archive_read_new()
        guard let handle else { return false }
        archive_read_support_filter_all(handle)
        archive_read_support_format_zip(handle)
        let opened: Int32
        if let remote = source.remote {
            let cursor = RemoteArchiveCursor(client: remote)
            remoteCursor = cursor
            opened = cursor.attach(to: handle)
        } else if let local = source.archiveURL {
            opened = local.path.withCString {
                archive_read_open_filename(handle, $0, 64 * 1024)
            }
        } else {
            return false
        }
''',
    "remote libarchive HTTP range reads",
)
replace_once(
    STREAM,
    '''        guard let handle else { return -1 }
        let n = archive_read_data(handle, buffer, max(0, min(count, 1024 * 1024)))
''',
    '''        if let remote = source.remote, let start = source.storedOffset {
            guard position < source.size, count > 0 else { return 0 }
            do {
                let bytes = try remote.read(
                    at: start + position,
                    count: min(count, Int(source.size - position))
                )
                bytes.copyBytes(to: buffer.assumingMemoryBound(to: UInt8.self), count: bytes.count)
                position += Int64(bytes.count)
                return Int64(bytes.count)
            } catch {
                print("[ZIP Range] MPV media read failed: \\(error.localizedDescription)")
                return -1
            }
        }
        guard let handle else { return -1 }
        let n = archive_read_data(handle, buffer, max(0, min(count, 1024 * 1024)))
''',
    "direct stored media data read",
)
replace_once(
    STREAM,
    '''        guard target >= 0 && target <= size else { return -1 }
        if target < position && !openEntry() { return -1 }
''',
    '''        guard target >= 0 && target <= size else { return -1 }
        if source.remote != nil, source.storedOffset != nil {
            position = target
            return target
        }
        if target < position && !openEntry() { return -1 }
''',
    "seek immediate for STORE remote ZIP",
)
print("v49 HTTP Range ZIP streaming installed: indexed ZIP, STORE fast seek, DEFLATE libarchive fallback.")
