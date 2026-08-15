from pathlib import Path

ROOT = Path('MPVTorBox')
RESOLVER = ROOT / 'SourceResolver.swift'
CONTENT = ROOT / 'ContentView.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# Diagnostics must exist before a player controller is created.  The previous
# logger lived in MPVMetalViewController, but website URLs can go through the
# playlist preflight first.  Keep this logger opt-in with the existing mpv.conf
# logging switch.
replace_once(
    RESOLVER,
    'import Foundation\n\n',
    '''import Foundation\n\nenum MPVOpenPipelineLog {\n    private static let lock = NSLock()\n\n    private static var enabled: Bool {\n        guard let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {\n            return false\n        }\n        let config = documents\n            .appendingPathComponent("MPVConfig", isDirectory: true)\n            .appendingPathComponent("mpv.conf")\n        guard let text = try? String(contentsOf: config, encoding: .utf8) else { return false }\n\n        for rawLine in text.split(separator: "\\n", omittingEmptySubsequences: false) {\n            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)\n            if line.isEmpty || line.hasPrefix("#") { continue }\n            let lower = line.lowercased().replacingOccurrences(of: " ", with: "")\n            if lower.contains("mpv-ios-ytdl-log=yes") ||\n               lower.contains("mpv-ios-ytdl-log=true") ||\n               lower.contains("mpv-ios-ytdl-log=1") ||\n               lower.contains("mpv-ios-player-log=yes") ||\n               lower.contains("mpv-ios-player-log=true") ||\n               lower.contains("mpv-ios-player-log=1") {\n                return true\n            }\n        }\n        return false\n    }\n\n    static func write(_ message: String) {\n        guard enabled else { return }\n        lock.lock()\n        defer { lock.unlock() }\n\n        guard let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else { return }\n        let directory = documents.appendingPathComponent("Logs", isDirectory: true)\n        let file = directory.appendingPathComponent("open-pipeline.log")\n        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)\n\n        let stamp = ISO8601DateFormatter().string(from: Date())\n        let thread = Thread.isMainThread ? "main" : "worker"\n        let line = "[\\(stamp)] [\\(thread)] \\(message)\\n"\n        guard let data = line.data(using: .utf8) else { return }\n\n        if !FileManager.default.fileExists(atPath: file.path) {\n            try? data.write(to: file, options: .atomic)\n            return\n        }\n        guard let handle = try? FileHandle(forWritingTo: file) else { return }\n        defer { try? handle.close() }\n        do {\n            try handle.seekToEnd()\n            try handle.write(contentsOf: data)\n            try handle.synchronize()\n        } catch { }\n    }\n}\n\n''',
    'insert pre-player diagnostics',
)

# Make the playlist classification explicit and log immediately before entering
# the embedded yt-dlp playlist extractor.  A single xHamster video lives under
# /videos/<slug>; the old generic '/videos' substring rule incorrectly treated
# it as a collection and ran this extractor before the player existed.
old_guard = '''        guard settings.ytdlpEnabled,\n              let url = URL(string: source),\n              let scheme = url.scheme?.lowercased(),\n              ["http", "https"].contains(scheme),\n              shouldUseYTDLP(url),\n              isLikelyPlaylistURL(url),\n              let selection = try await YTDLPService.shared.playlistSelection(url: url) else {\n            return nil\n        }\n\n        return MediaPlaylistSelection(\n'''
new_guard = '''        guard settings.ytdlpEnabled,\n              let url = URL(string: source),\n              let scheme = url.scheme?.lowercased(),\n              ["http", "https"].contains(scheme),\n              shouldUseYTDLP(url) else {\n            return nil\n        }\n\n        let likelyPlaylist = isLikelyPlaylistURL(url)\n        MPVOpenPipelineLog.write("playlist classify host=\\(url.host ?? "unknown") path=\\(url.path) likely=\\(likelyPlaylist)")\n        guard likelyPlaylist else { return nil }\n\n        MPVOpenPipelineLog.write("before YTDLPService.playlistSelection host=\\(url.host ?? "unknown")")\n        guard let selection = try await YTDLPService.shared.playlistSelection(url: url) else {\n            MPVOpenPipelineLog.write("YTDLPService.playlistSelection returned nil")\n            return nil\n        }\n        MPVOpenPipelineLog.write("YTDLPService.playlistSelection returned items=\\(selection.items.count)")\n\n        return MediaPlaylistSelection(\n'''
replace_once(RESOLVER, old_guard, new_guard, 'playlist preflight guard')

old_hints = '''        // Common collection-shaped routes used by yt-dlp-supported sites.\n        let playlistPathHints = [\n            "/playlist", "/playlists/", "/sets/", "/showcase/",\n            "/album/", "/albums/", "/collection/", "/collections/",\n            "/series/", "/videos"\n        ]\n        return playlistPathHints.contains(where: { path.contains($0) })\n'''
new_hints = '''        // Common collection-shaped routes used by yt-dlp-supported sites.\n        // IMPORTANT: never use a generic `path.contains("/videos")` check.\n        // Many sites (xHamster among them) use /videos/<slug> for one video.\n        // Treat a videos route as a collection only when `videos` is the final\n        // path component.  YouTube channel /videos routes were handled above.\n        let genericPathComponents = path.split(separator: "/")\n        if genericPathComponents.last == "videos" { return true }\n\n        let playlistPathHints = [\n            "/playlist", "/playlists/", "/sets/", "/showcase/",\n            "/album/", "/albums/", "/collection/", "/collections/",\n            "/series/"\n        ]\n        return playlistPathHints.contains(where: { path.contains($0) })\n'''
replace_once(RESOLVER, old_hints, new_hints, 'generic videos playlist classification')

# Breadcrumbs around the exact pre-player flow.  These are useful for any future
# site that dies before MPVMetalViewController is presented.
replace_once(
    CONTENT,
    '''    private func openSource(skipPlaylistPicker: Bool = false) {\n        let input = sourceText\n        let providerSettings = settings.snapshot()\n''',
    '''    private func openSource(skipPlaylistPicker: Bool = false) {\n        let input = sourceText\n        let diagnosticURL = URL(string: input.trimmingCharacters(in: .whitespacesAndNewlines))\n        MPVOpenPipelineLog.write("openSource enter host=\\(diagnosticURL?.host ?? "unknown") path=\\(diagnosticURL?.path ?? "") skipPlaylist=\\(skipPlaylistPicker)")\n        let providerSettings = settings.snapshot()\n''',
    'openSource entry breadcrumb',
)
replace_once(
    CONTENT,
    '''                if !skipPlaylistPicker {\n                    do {\n                        if let selection = try await resolver.playlistSelection(\n''',
    '''                if !skipPlaylistPicker {\n                    MPVOpenPipelineLog.write("openSource before playlist preflight")\n                    do {\n                        if let selection = try await resolver.playlistSelection(\n''',
    'playlist preflight entry breadcrumb',
)
replace_once(
    CONTENT,
    '''                            isResolving = false\n                            return\n                        }\n                    } catch {\n                        statusText = "Playlist unavailable; opening the source normally…"\n                    }\n                }\n\n                let resolved = try await resolver.resolve(input, settings: providerSettings) { message in\n''',
    '''                            MPVOpenPipelineLog.write("openSource playlist picker ready items=\\(selection.items.count)")\n                            isResolving = false\n                            return\n                        }\n                        MPVOpenPipelineLog.write("openSource playlist preflight skipped/no collection")\n                    } catch {\n                        MPVOpenPipelineLog.write("openSource playlist preflight error=\\(error.localizedDescription)")\n                        statusText = "Playlist unavailable; opening the source normally…"\n                    }\n                }\n\n                MPVOpenPipelineLog.write("openSource before normal resolve")\n                let resolved = try await resolver.resolve(input, settings: providerSettings) { message in\n''',
    'playlist-to-normal-resolve breadcrumbs',
)
replace_once(
    CONTENT,
    '''                activePlaylist = nil\n                currentPlaylistItemID = nil\n                play(resolved)\n''',
    '''                MPVOpenPipelineLog.write("openSource resolved provider=\\(resolved.provider); presenting player")\n                activePlaylist = nil\n                currentPlaylistItemID = nil\n                play(resolved)\n''',
    'resolved breadcrumb',
)

print('Applied v37: single /videos/<slug> URLs bypass playlist preflight and pre-player diagnostics are available')
