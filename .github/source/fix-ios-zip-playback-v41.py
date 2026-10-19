from pathlib import Path
import re
import plistlib

ROOT = Path("MPVTorBox")
PROJECT = Path("project.yml")
CONTENT = ROOT / "ContentView.swift"
RESOLVER = ROOT / "SourceResolver.swift"
INFO = ROOT / "Info.plist"

def replace_once(path, old, new, label):
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"ZIP support: missing {label} anchor in {path}")
    path.write_text(text.replace(old, new, 1))

service = r'''import Foundation
import ZIPFoundation

@MainActor
final class ZIPPlaybackService {
    static let shared = ZIPPlaybackService()

    enum ZIPError: LocalizedError {
        case empty
        case tooManyEntries
        case fileTooLarge
        case invalidSelection
        case lowDiskSpace

        var errorDescription: String? {
            switch self {
            case .empty: return "No playable video or audio files were found in this ZIP archive."
            case .tooManyEntries: return "This ZIP archive has too many entries."
            case .fileTooLarge: return "The selected archive item exceeds the 12 GB safety limit."
            case .invalidSelection: return "ZIP selection expired. Open the archive again."
            case .lowDiskSpace: return "There is not enough free storage to open this ZIP video."
            }
        }
    }

    private struct ZIPItem: Sendable {
        let path: String
        let size: Int64
        let name: String
    }

    private struct ImportedZIP: Sendable {
        let url: URL
        let videos: [ZIPItem]
        let subtitles: [ZIPItem]
        let root: URL
    }

    private var opened: [String: ImportedZIP] = [:]
    private let videoExtensions: Set<String> = [
        "mp4", "m4v", "mov", "mkv", "avi", "webm", "ts", "m2ts",
        "mpg", "mpeg", "wmv", "flv", "ogv", "3gp", "mp3", "m4a",
        "aac", "flac", "wav", "ogg", "opus"
    ]
    private let subtitleExtensions: Set<String> = ["srt", "ass", "ssa", "vtt", "sub", "smi"]
    private let maxItemSize: Int64 = 12 * 1024 * 1024 * 1024

    private init() {}

    func importArchive(_ incomingURL: URL) throws -> MediaPlaylistSelection {
        let fm = FileManager.default
        let root = fm.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MPVZIP", isDirectory: true)
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)

        // DocumentPicker's copy may only be temporary; keep a sandbox copy for
        // playlist selection, subsequent seeking, and multiple video choices.
        let zipURL = root.appendingPathComponent("Archive.zip")
        try fm.copyItem(at: incomingURL, to: zipURL)

        let archive = try Archive(url: zipURL, accessMode: .read)
        var videos: [ZIPItem] = []
        var subtitles: [ZIPItem] = []
        var count = 0
        for entry in archive {
            count += 1
            guard count <= 20000 else { throw ZIPError.tooManyEntries }
            guard entry.type == .file else { continue } // Ignore symlinks and folders.
            let name = URL(fileURLWithPath: entry.path).lastPathComponent
            guard name != "." && name != ".." && !name.isEmpty else { continue }
            let item = ZIPItem(
                path: entry.path,
                size: Int64(entry.uncompressedSize),
                name: name
            )
            let ext = URL(fileURLWithPath: name).pathExtension.lowercased()
            if videoExtensions.contains(ext) {
                videos.append(item)
            } else if subtitleExtensions.contains(ext) {
                subtitles.append(item)
            }
        }
        guard !videos.isEmpty else { throw ZIPError.empty }
        videos.sort { $0.path.localizedStandardCompare($1.path) == .orderedAscending }
        let identifier = UUID().uuidString.lowercased()
        opened[identifier] = ImportedZIP(url: zipURL, videos: videos, subtitles: subtitles, root: root)

        return MediaPlaylistSelection(
            id: "zip:\(identifier)",
            title: incomingURL.deletingPathExtension().lastPathComponent,
            provider: "ZIP Archive",
            items: videos.enumerated().map { index, item in
                MediaPlaylistItem(
                    id: "zip:\(identifier):\(index)",
                    title: item.name,
                    input: "zipmedia://\(identifier)/\(index)",
                    duration: nil,
                    index: index + 1,
                    detail: ByteCountFormatter.string(fromByteCount: item.size, countStyle: .file)
                )
            }
        )
    }

    func resolve(_ token: String) async throws -> URL {
        guard let parsed = URL(string: token),
              parsed.scheme?.lowercased() == "zipmedia",
              let identifier = parsed.host,
              let index = Int(parsed.lastPathComponent),
              let record = opened[identifier],
              record.videos.indices.contains(index) else {
            throw ZIPError.invalidSelection
        }
        let video = record.videos[index]
        guard video.size >= 0 && video.size <= maxItemSize else { throw ZIPError.fileTooLarge }
        let folder = record.root.appendingPathComponent("Video-\(index)", isDirectory: true)
        let destination = folder.appendingPathComponent(video.name)

        // Extraction can be expensive for large movies. Keep it off the main
        // actor and preserve the extracted file while the mpv player uses it.
        return try await Task.detached(priority: .userInitiated) {
            let fm = FileManager.default
            try fm.createDirectory(at: folder, withIntermediateDirectories: true)
            if fm.fileExists(atPath: destination.path) { return destination }

            let free = (try? record.root.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]))
                ?.volumeAvailableCapacityForImportantUsage
            if let free, free < video.size + (64 * 1024 * 1024) {
                throw ZIPError.lowDiskSpace
            }

            let zip = try Archive(url: record.url, accessMode: .read)
            guard let entry = zip[video.path], entry.type == .file else {
                throw ZIPError.invalidSelection
            }
            try zip.extract(entry, to: destination)

            // Copy matching subtitles beside the movie for mpv subtitle auto-loading.
            let stem = (video.name as NSString).deletingPathExtension.lowercased()
            for sub in record.subtitles.prefix(300) {
                guard sub.size >= 0 && sub.size < 64 * 1024 * 1024 else { continue }
                let subStem = (sub.name as NSString).deletingPathExtension.lowercased()
                guard subStem == stem || subStem.hasPrefix(stem + ".") else { continue }
                guard let subEntry = zip[sub.path], subEntry.type == .file else { continue }
                let subURL = folder.appendingPathComponent(sub.name)
                if !fm.fileExists(atPath: subURL.path) {
                    try? zip.extract(subEntry, to: subURL)
                }
            }
            return destination
        }.value
    }
}
'''
(ROOT / "ZIPPlaybackService.swift").write_text(service)

# Register SwiftPM ZIPFoundation with the XcodeGen target. Nothing in
# MPVKit/libmpv's existing audio, video, GPU, or yt-dlp pipeline is changed.
text = PROJECT.read_text()
if "  ZIPFoundation:" not in text:
    if "\npackages:\n" in text:
        text = text.replace("\npackages:\n", "\npackages:\n  ZIPFoundation:\n    url: https://github.com/weichsel/ZIPFoundation.git\n    from: 0.9.19\n", 1)
    else:
        marker = "\ntargets:\n"
        if marker not in text:
            raise SystemExit("ZIP support: XcodeGen targets section not found")
        text = text.replace(marker, "\npackages:\n  ZIPFoundation:\n    url: https://github.com/weichsel/ZIPFoundation.git\n    from: 0.9.19\n" + marker, 1)
target = re.search(r"(?m)^  MPVTorBox:\n", text)
if target is None:
    raise SystemExit("ZIP support: XcodeGen MPVTorBox target not found")
start = target.end()
endMatch = re.search(r"(?m)^  [A-Za-z_][^\n]*:\n", text[start:])
end = start + endMatch.start() if endMatch else len(text)
part = text[start:end]
if "- package: ZIPFoundation" not in part:
    dependency = re.search(r"(?m)^    dependencies:\s*\n", part)
    if dependency:
        at = dependency.end()
        part = part[:at] + "      - package: ZIPFoundation\n" + part[at:]
    else:
        part = "    dependencies:\n      - package: ZIPFoundation\n" + part
text = text[:start] + part + text[end:]
PROJECT.write_text(text)

# ZIPs selected via Files use the existing searchable playlist picker. A
# single-video ZIP opens immediately, while multi-video archives show a list.
replace_once(
    CONTENT,
    "    private func openLocalFile(_ url: URL) {\n",
    '''    private func openLocalFile(_ url: URL) {
        if url.pathExtension.lowercased() == "zip" {
            isResolving = true
            statusText = "Reading ZIP archive…"
            Task {
                do {
                    let selection = try ZIPPlaybackService.shared.importArchive(url)
                    activePlaylist = selection
                    currentPlaylistItemID = nil
                    if selection.items.count > 1 {
                        playlistSelection = selection
                        statusText = "Choose a video from the ZIP archive."
                        isResolving = false
                    } else if let first = selection.items.first {
                        sourceText = first.input
                        openSource(skipPlaylistPicker: true)
                    } else {
                        isResolving = false
                    }
                } catch {
                    errorMessage = error.localizedDescription
                    statusText = "Could not open ZIP archive."
                    isResolving = false
                }
            }
            return
        }
''',
    "ContentView.openLocalFile",
)

# Resolve selected ZIP entries only when picked (not the entire ZIP).
replace_once(
    RESOLVER,
    "        guard !source.isEmpty else { throw ResolverError.emptySource }\n",
    '''        guard !source.isEmpty else { throw ResolverError.emptySource }

        if source.lowercased().hasPrefix("zipmedia://") {
            await status("Extracting selected ZIP video…")
            let url = try await ZIPPlaybackService.shared.resolve(source)
            return ResolvedSource(url: url, provider: "ZIP Archive")
        }
''',
    "SourceResolver.resolve",
)

# Register ZIP in iOS Files "Open in MPV" as well as the existing .item picker.
with INFO.open("rb") as stream:
    info = plistlib.load(stream)
types = info.setdefault("CFBundleDocumentTypes", [])
if not any("public.zip" in d.get("LSItemContentTypes", []) for d in types):
    types.append({
        "CFBundleTypeName": "ZIP Archive",
        "CFBundleTypeRole": "Viewer",
        "LSHandlerRank": "Alternate",
        "LSItemContentTypes": ["public.zip"]
    })
with INFO.open("wb") as stream:
    plistlib.dump(info, stream)

print("ZIP playback enabled: selected-entry extraction, subtitles, playlist picker, Files association.")
