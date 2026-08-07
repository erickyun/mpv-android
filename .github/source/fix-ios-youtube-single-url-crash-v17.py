from pathlib import Path

RESOLVER = Path('MPVTorBox/SourceResolver.swift')


def replace_once(old: str, new: str, label: str) -> None:
    text = RESOLVER.read_text()
    if old not in text:
        raise SystemExit(f'{label} anchor not found in {RESOLVER}')
    RESOLVER.write_text(text.replace(old, new, 1))


# v16 made generic playlist discovery run for every yt-dlp-capable URL. That
# means even an ordinary youtube.com/watch?v=... URL constructs the flat-playlist
# Python bridge before the proven native playback hook. On iOS/WebKit that extra
# bridge path can terminate the process instead of throwing a Swift error.
#
# Only preflight URLs that visibly describe a collection. A YouTube watch URL
# that is *inside a playlist* still contains ?list=... and therefore keeps the
# playlist picker, while a normal single-video URL goes straight to the native
# yt-dlp/mpv hook exactly as it did before playlists were added.
replace_once(
    '''              ["http", "https"].contains(scheme),\n              shouldUseYTDLP(url),\n              let selection = try await YTDLPService.shared.playlistSelection(url: url) else {\n''',
    '''              ["http", "https"].contains(scheme),
              shouldUseYTDLP(url),
              isLikelyPlaylistURL(url),
              let selection = try await YTDLPService.shared.playlistSelection(url: url) else {
''',
    'playlist preflight guard',
)

helper = r'''    private func isLikelyPlaylistURL(_ url: URL) -> Bool {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return false
        }

        // Covers YouTube watch?v=...&list=..., plus providers that use an
        // explicit collection identifier in the query string.
        let playlistQueryNames: Set<String> = [
            "list", "playlist", "playlist_id", "album", "album_id",
            "set", "set_id", "collection", "collection_id", "series"
        ]
        if components.queryItems?.contains(where: { item in
            playlistQueryNames.contains(item.name.lowercased()) &&
                !(item.value ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }) == true {
            return true
        }

        let host = (url.host ?? "").lowercased()
        let path = url.path.lowercased()

        // Explicit YouTube collection/channel video pages. Intentionally do
        // not classify /watch as a playlist unless the list query above exists.
        if host == "youtube.com" || host.hasSuffix(".youtube.com") || host == "youtu.be" {
            if path == "/playlist" || path.contains("/playlists/") { return true }
            if path.hasSuffix("/videos") && (
                path.contains("/@") || path.contains("/channel/") ||
                path.contains("/user/") || path.contains("/c/")
            ) {
                return true
            }
            return false
        }

        // Common collection-shaped routes used by yt-dlp-supported sites.
        let playlistPathHints = [
            "/playlist", "/playlists/", "/sets/", "/showcase/",
            "/album/", "/albums/", "/collection/", "/collections/",
            "/series/", "/videos"
        ]
        return playlistPathHints.contains(where: { path.contains($0) })
    }

'''
replace_once(
    '    private func torBoxFileReference(_ source: String) -> (torrentID: Int, fileID: Int)? {\n',
    helper + '    private func torBoxFileReference(_ source: String) -> (torrentID: Int, fileID: Int)? {\n',
    'playlist URL classifier',
)

print('Fixed single-video YouTube crash: playlist preflight now runs only for collection-like URLs.')
