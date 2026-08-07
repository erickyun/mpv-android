from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-playlist.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f'YoutubeDL playlist {label} anchor was not found')
    text = text.replace(old, new, 1)


replace_once(
    'public struct Format: Codable {\n',
    '''public struct PlaylistEntryInfo: Codable {
    public var id: String
    public var title: String
    public var url: String
    public var duration: Double?
    public var index: Int
    public var extractor_key: String
}

public struct PlaylistInfo: Codable {
    public var title: String
    public var entries: [PlaylistEntryInfo]
}

public struct Format: Codable {
''',
    'metadata structs',
)

method = r'''    open func extractPlaylistInfo(url: URL) async throws -> PlaylistInfo {
        // Use yt-dlp's flat-playlist mode so a large playlist only fetches its
        // entry metadata. Individual formats are resolved later only for the
        // item the user actually chooses.
        let builtins = Python.import("builtins")
        let playlistOptions = builtins.dict(defaultOptions)
        playlistOptions["extract_flat"] = "in_playlist"
        playlistOptions["noplaylist"] = false
        playlistOptions["skip_download"] = true
        playlistOptions["ignoreerrors"] = true
        playlistOptions["playlistend"] = 500
        playlistOptions["lazy_playlist"] = false

        let playlistObject = try await makePythonObject(playlistOptions)
        let rawInfo = try playlistObject.extract_info.throwing.dynamicallyCall(
            withKeywordArguments: ["": url.absoluteString, "download": false, "process": true]
        )

        // Normalize extractor-specific flat entries into a tiny Codable shape.
        // Filtering None/unavailable entries here keeps Swift decoding robust.
        let mainModule = Python.import("__main__")
        let normalizeSource = #"""
def _mpv_ios_playlist_summary(info):
    result = {
        'title': str(info.get('title') or info.get('id') or 'Playlist'),
        'entries': [],
    }
    for fallback_index, entry in enumerate(info.get('entries') or [], 1):
        if not isinstance(entry, dict):
            continue
        raw_index = entry.get('playlist_index')
        index = int(raw_index) if isinstance(raw_index, (int, float)) else fallback_index
        entry_id = entry.get('id') or ''
        candidate = entry.get('webpage_url') or entry.get('original_url') or entry.get('url') or ''
        extractor_key = entry.get('ie_key') or entry.get('extractor_key') or ''
        result['entries'].append({
            'id': str(entry_id),
            'title': str(entry.get('title') or entry_id or f'Video {index}'),
            'url': str(candidate),
            'duration': entry.get('duration'),
            'index': index,
            'extractor_key': str(extractor_key),
        })
    return result
"""#
        _ = builtins.exec(normalizeSource, mainModule.__dict__)
        let summary = mainModule._mpv_ios_playlist_summary(rawInfo)
        return try PythonDecoder().decode(PlaylistInfo.self, from: summary)
    }

'''

replace_once(
    '    func tryMerge(directory: URL, title: String, timeRange: TimeRange?) -> Bool {\n',
    method + '    func tryMerge(directory: URL, title: String, timeRange: TimeRange?) -> Bool {\n',
    'extractPlaylistInfo method',
)

path.write_text(text)
print(f'Patched {path}: added flat-playlist metadata extraction for the iOS picker.')
