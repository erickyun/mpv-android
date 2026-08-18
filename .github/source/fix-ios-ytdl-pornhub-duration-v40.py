from pathlib import Path

ROOT = Path('MPVTorBox')
METAL = ROOT / 'Player' / 'MPVMetalViewController.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# Restore mpv's stock behavior for ordinary single-stream website playback:
# a single selected media URL should be opened directly, not wrapped in EDL.
# The generic v38/v39 single-stream EDL workaround broke YouTube URLs that
# resolved to one playable stream (title briefly appeared, then fell back to
# "watch" and playback stopped).
#
# Pornhub is the one reported site that needs a duration hint because its
# progressive response can look like a growing file. Keep the known-duration
# EDL workaround scoped only to pornhub.com; all other single-stream sites use
# the direct selected URL exactly as mpv's stock ytdl_hook does.

replace_once(
    METAL,
    '''        guard let stream = makeEmbeddedYTDLStream(\n            response.formats,\n            duration: response.duration\n        ) else {\n''',
    '''        guard let stream = makeEmbeddedYTDLStream(\n            response.formats,\n            duration: response.duration,\n            originalURL: originalURL\n        ) else {\n''',
    'pass original URL to stream builder',
)

replace_once(
    METAL,
    '''    private func makeEmbeddedYTDLStream(\n        _ formats: [YTDLPService.MPVHookFormat],\n        duration: Double?\n    ) -> String? {\n''',
    '''    private func makeEmbeddedYTDLStream(\n        _ formats: [YTDLPService.MPVHookFormat],\n        duration: Double?,\n        originalURL: String\n    ) -> String? {\n''',
    'stream builder signature',
)

replace_once(
    METAL,
    '''        let playable = formats.filter { !$0.url.isEmpty }\n        guard !playable.isEmpty else { return nil }\n        if playable.count == 1 { return playable[0].url }\n\n        // Match mpv's normal requested_formats EDL path: selected audio/video\n''',
    '''        let playable = formats.filter { !$0.url.isEmpty }\n        guard !playable.isEmpty else { return nil }\n        if playable.count == 1 {\n            let directURL = playable[0].url\n            guard isPornhubURL(originalURL),\n                  let duration, duration.isFinite, duration > 0 else {\n                return directURL\n            }\n\n            // Pornhub progressive streams may expose only the downloaded part\n            // as duration. Give mpv the yt-dlp-known VOD length without changing\n            // the selected media URL for any other site.\n            return "edl://!new_stream;!no_clip;!no_chapters;"\n                + edlEscape(directURL)\n                + ",length=\\(duration)"\n        }\n\n        // Match mpv's normal requested_formats EDL path: selected audio/video\n''',
    'site-scoped single stream duration',
)

anchor = '''    private func edlEscape(_ value: String) -> String {\n'''
helper = '''    private func isPornhubURL(_ source: String) -> Bool {\n        guard let host = URL(string: source)?.host?.lowercased() else { return false }\n        return host == "pornhub.com" || host.hasSuffix(".pornhub.com")\n    }\n\n'''
replace_once(METAL, anchor, helper + anchor, 'Pornhub host helper')

print('Applied v40: direct single-stream playback restored globally; Pornhub-only duration EDL retained.')
