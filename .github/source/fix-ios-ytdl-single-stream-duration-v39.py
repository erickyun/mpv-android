from pathlib import Path

ROOT = Path('MPVTorBox')
METAL = ROOT / 'Player' / 'MPVMetalViewController.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# v13 carries yt-dlp Info.duration into the native bridge. For one selected
# progressive stream, preserve direct playback when duration is unknown. When
# duration is known, use the same EDL stream header shape as mpv's stock
# ytdl_hook.lua: !new_stream;!no_clip;!no_chapters;URL,length=...
#
# v38 omitted !new_stream, which made the EDL invalid/ambiguous and could make
# YouTube fall back to the original /watch URL instead of opening the selected
# media stream.
replace_once(
    METAL,
    '''        let playable = formats.filter { !$0.url.isEmpty }\n        guard !playable.isEmpty else { return nil }\n        if playable.count == 1 { return playable[0].url }\n\n        // Match mpv's normal requested_formats EDL path: selected audio/video\n''',
    '''        let playable = formats.filter { !$0.url.isEmpty }\n        guard !playable.isEmpty else { return nil }\n        if playable.count == 1 {\n            let url = playable[0].url\n            guard let duration, duration.isFinite, duration > 0 else {\n                return url\n            }\n            return "edl://!new_stream;!no_clip;!no_chapters;"\n                + edlEscape(url)\n                + ",length=\\(duration)"\n        }\n\n        // Match mpv's normal requested_formats EDL path: selected audio/video\n''',
    'single-stream MPV EDL header',
)

print('Applied v39: single-stream duration EDL now uses MPV stock !new_stream header.')
