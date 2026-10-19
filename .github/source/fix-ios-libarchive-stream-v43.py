from pathlib import Path
import re

root=Path("MPVTorBox")
project=Path("project.yml")
metal=root/"Player"/"MPVMetalViewController.swift"
service=root/"ZIPPlaybackService.swift"

new=r'''import Foundation
import Libmpv
import libarchive

/// A libarchive-powered mpv read-only stream. Unlike extracting the selected
/// movie, this feeds decompressed bytes directly to the mpv demuxer. Archive
/// seeking may require re-decoding prior bytes on backwards seeks.
final class MPVArchiveProtocol: @unchecked Sendable {
    static let shared = MPVArchiveProtocol()

    struct Source: Sendable {
        let archiveURL: URL
        let entryPath: String
        let size: Int64
    }

    private let lock = NSLock()
    private var sources: [String: Source] = [:]
    private init() {}

    func playbackURL(archiveURL: URL, entryPath: String, size: Int64) -> URL {
        let token = UUID().uuidString.lowercased()
        lock.lock()
        sources[token] = Source(archiveURL: archiveURL, entryPath: entryPath, size: size)
        lock.unlock()
        let ext = URL(fileURLWithPath: entryPath).pathExtension
        // Expose extension for mpv probing without interpreting any archive
        // path supplied by untrusted ZIP metadata as a filesystem location.
        return URL(string: "iosarchive://\(token)/movie.\(ext)")!
    }

    private func source(for token: String) -> Source? {
        lock.lock()
        defer { lock.unlock() }
        return sources[token]
    }

    /// Must be called before mpv_initialize().
    @discardableResult
    static func register(with context: OpaquePointer) -> Int32 {
        mpv_stream_cb_add_ro(context, "iosarchive", nil) { _, uri, info in
            guard let uri, let info,
                  let url = URL(string: String(cString: uri)),
                  url.scheme == "iosarchive",
                  let key = url.host,
                  let source = MPVArchiveProtocol.shared.source(for: key),
                  let session = ArchiveStreamSession(source: source) else {
                return MPV_ERROR_LOADING_FAILED.rawValue
            }
            info.pointee.cookie = Unmanaged.passRetained(session).toOpaque()
            info.pointee.read_fn = { cookie, buffer, bytes in
                guard let cookie, let buffer else { return -1 }
                let session = Unmanaged<ArchiveStreamSession>.fromOpaque(cookie).takeUnretainedValue()
                return session.read(into: buffer, count: Int(bytes))
            }
            info.pointee.seek_fn = { cookie, offset in
                guard let cookie else { return -1 }
                let session = Unmanaged<ArchiveStreamSession>.fromOpaque(cookie).takeUnretainedValue()
                return session.seek(to: offset)
            }
            info.pointee.size_fn = { cookie in
                guard let cookie else { return -1 }
                return Unmanaged<ArchiveStreamSession>.fromOpaque(cookie).takeUnretainedValue().size
            }
            info.pointee.close_fn = { cookie in
                guard let cookie else { return }
                Unmanaged<ArchiveStreamSession>.fromOpaque(cookie).release()
            }
            info.pointee.cancel_fn = nil
            return 0
        }
    }
}

private final class ArchiveStreamSession: @unchecked Sendable {
    private let source: MPVArchiveProtocol.Source
    private var handle: OpaquePointer?
    private let lock = NSLock()
    private(set) var position: Int64 = 0

    var size: Int64 { source.size }

    init?(source: MPVArchiveProtocol.Source) {
        self.source = source
        guard openEntry() else { return nil }
    }

    deinit {
        if let handle { archive_read_free(handle) }
    }

    private func openEntry() -> Bool {
        if let old = handle { archive_read_free(old) }
        handle = archive_read_new()
        guard let handle else { return false }
        archive_read_support_filter_all(handle)
        archive_read_support_format_all(handle)
        let opened = source.archiveURL.path.withCString {
            archive_read_open_filename(handle, $0, 64 * 1024)
        }
        guard opened == ARCHIVE_OK else { return false }
        var entry: OpaquePointer?
        while archive_read_next_header(handle, &entry) == ARCHIVE_OK {
            if let entry, let name = archive_entry_pathname(entry),
               String(cString: name) == source.entryPath {
                position = 0
                return true
            }
            archive_read_data_skip(handle)
        }
        return false
    }

    func read(into buffer: UnsafeMutableRawPointer, count: Int) -> Int64 {
        lock.lock()
        defer { lock.unlock() }
        guard let handle else { return -1 }
        let n = archive_read_data(handle, buffer, max(0, min(count, 1024 * 1024)))
        if n > 0 { position += Int64(n) }
        return Int64(n)
    }

    func seek(to target: Int64) -> Int64 {
        lock.lock()
        defer { lock.unlock() }
        guard target >= 0 && target <= size else { return -1 }
        if target < position && !openEntry() { return -1 }
        var bytes = [UInt8](repeating: 0, count: 64 * 1024)
        while position < target {
            guard let handle else { return -1 }
            let wanted = Int(min(target - position, Int64(bytes.count)))
            let read = bytes.withUnsafeMutableBytes { buffer -> Int in
                Int(archive_read_data(handle, buffer.baseAddress, wanted))
            }
            if read <= 0 { return -1 }
            position += Int64(read)
        }
        return position
    }
}
'''
(root/"MPVArchiveProtocol.swift").write_text(new)

# Pin the dependency rather than tracking an unreviewed moving branch.
p=project.read_text()
if "  libarchive:" not in p:
    p=p.replace("\npackages:\n", "\npackages:\n  libarchive:\n    url: https://github.com/okferret/libarchive.git\n    revision: b84d41ea6ecd1ab0b0cec6d60baa806808589cd5\n", 1)
needle=re.search(r"(?m)^  MPVTorBox:\n",p)
if needle is None: raise SystemExit("Target not found")
a=needle.end()
nxt=re.search(r"(?m)^  [A-Za-z_][^\n]*:\n",p[a:])
b=a+nxt.start() if nxt else len(p)
segment=p[a:b]
if "- package: libarchive" not in segment:
    match=re.search(r"(?m)^    dependencies:\s*\n",segment)
    if match: segment=segment[:match.end()]+"      - package: libarchive\n"+segment[match.end():]
    else: segment="    dependencies:\n      - package: libarchive\n"+segment
p=p[:a]+segment+p[b:]
project.write_text(p)

# Register the mpv stream handler before mpv_initialize, when custom protocols
# are accepted. Any URL with the iosarchive scheme is handled by libarchive.
m=metal.read_text()
match=re.search(r"(?m)^([ \t]*)([^\n]*mpv_initialize\((\w+)\)[^\n]*)$", m)
if not match: raise SystemExit("mpv_initialize(...) call not found")
indent=match.group(1)
handle=match.group(3)
registration=indent+"let archiveStatus = MPVArchiveProtocol.register(with: "+handle+")\n"
registration+=indent+"if archiveStatus < 0 { print(\"[libarchive] protocol registration failed\") }\n"
m=m[:match.start()]+registration+m[match.start():]
metal.write_text(m)

# Keep the existing ZIPFoundation picker, but change playback to on-demand
# libarchive streaming. Retain v42 extraction as a fallback if needed later.
s=service.read_text()
start=s.find("    func resolve(_ token: String) async throws -> URL {")
if start<0: raise SystemExit("ZIP resolve anchor missing")
end=s.rfind("\n}")
if end<=start: raise SystemExit("ZIP class end missing")
newResolve=r'''    func resolve(_ token: String) async throws -> URL {
        guard let parsed = URL(string: token),
              parsed.scheme?.lowercased() == "zipmedia",
              let identifier = parsed.host,
              let index = Int(parsed.lastPathComponent),
              let record = opened[identifier],
              record.videos.indices.contains(index) else {
            throw ZIPError.invalidSelection
        }
        let video = record.videos[index]
        guard video.size >= 0 && video.size <= maxItemSize else {
            throw ZIPError.fileTooLarge
        }
        return MPVArchiveProtocol.shared.playbackURL(
            archiveURL: record.url,
            entryPath: video.path,
            size: video.size
        )
    }
'''
s=s[:start]+newResolve+s[end:]
service.write_text(s)
print("Added on-demand native libarchive stream via mpv custom protocol (iosarchive://).")
