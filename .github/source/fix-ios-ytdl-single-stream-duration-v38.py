from pathlib import Path

ROOT = Path('MPVTorBox')
METAL = ROOT / 'Player' / 'MPVMetalViewController.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# v13 already carries yt-dlp Info.duration into the native bridge and applies it
# to multi-stream EDL (separate video+audio).  The single-stream path, however,
# returned the progressive URL directly and discarded that known duration.
# Some sites (notably Pornhub) then look like a growing/live file to ffmpeg/mpv:
# duration starts near the buffered amount and grows as more bytes arrive.
#
# Preserve direct playback when yt-dlp does not know the duration.  When it does
# know it, wrap even a single stream in a one-entry EDL with an explicit length,
# matching the existing multi-stream duration behavior.  This is site-agnostic.
replace_once(
    METAL,
    '''        let playable = formats.filter { !$0.url.isEmpty }\n        guard !playable.isEmpty else { return nil }\n        if playable.count == 1 { return playable[0].url }\n\n        // Match mpv's normal requested_formats EDL path: selected audio/video\n''',
    '''        let playable = formats.filter { !$0.url.isEmpty }\n        guard !playable.isEmpty else { return nil }\n        if playable.count == 1 {\n            let url = playable[0].url\n            guard let duration, duration.isFinite, duration > 0 else {\n                return url\n            }\n            // A progressive HTTP response may not advertise its final size or\n            // container duration up front.  yt-dlp already knows the webpage's\n            // duration, so expose that immediately to mpv through EDL.  This\n            // gives the UI a stable full seek range from the first frame.\n            return "edl://!no_clip;!no_chapters;"\n                + edlEscape(url)\n                + ",length=\\(duration)"\n        }\n\n        // Match mpv's normal requested_formats EDL path: selected audio/video\n''',
    'single-stream known duration EDL',
)

print('Applied v38: yt-dlp single progressive streams expose known full duration immediately.')
