from pathlib import Path
import runpy

ROOT = Path('MPVTorBox')
PROJECT = Path('project.yml')

service = ROOT / 'YTDLPService.swift'
text = service.read_text()
text = text.replace(
    'Preparing embedded Python, yt-dlp, and Apple WebKit JSI…',
    'Preparing embedded Python, yt-dlp, and Apple WebKit JSI…',
)
service.write_text(text)

project = PROJECT.read_text()
if 'MARKETING_VERSION: 1.8.0' not in project or 'CURRENT_PROJECT_VERSION: 18' not in project:
    raise SystemExit('Expected MPV iOS 1.8 version markers were not found')
project = project.replace('MARKETING_VERSION: 1.8.0', 'MARKETING_VERSION: 1.9.0', 1)
project = project.replace('CURRENT_PROJECT_VERSION: 18', 'CURRENT_PROJECT_VERSION: 19', 1)
PROJECT.write_text(project)

# Build the embedded yt-dlp integration in layers. v10 supplies the
# YoutubeDL-iOS format bridge and mpv.conf plumbing; v11 replaces the fragile
# Lua script-message hop with mpv's native C on_load hook and a private marker;
# v12 binds the async completion path to the controller's actual mpv handle;
# v13 opens the selected A/V tracks immediately and propagates Info.duration so
# MPV has the complete seek range before the remote files are buffered; v14
# disables the temporary persistent yt-dlp diagnostics; v15 adds a searchable
# flat-playlist chooser; v16 makes playlist handling provider-neutral, exposes
# TorBox multi-video torrents, and keeps the playlist selectable inside player;
# v17 avoids the flat-playlist Python bridge for ordinary single-video URLs,
# while keeping playlist detection for YouTube watch URLs with ?list=... and
# other visibly collection-shaped URLs; v18 fixes rotation rendering by making
# the UIView controller's live bounds the sole Metal viewport authority instead
# of replaying stale portrait UIWindow/SwiftUI geometry snapshots.
helper = Path(__file__).with_name('fix-ios-mpv-ytdl-hook-v10.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-native-ytdl-hook-v11.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-native-ytdl-hook-v12.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-ytdl-seek-duration-v13.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-remove-ytdlp-log-v14.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-ytdl-playlist-picker-v15.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-general-playlist-v16.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-youtube-single-url-crash-v17.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-landscape-render-resize-v18.py')
runpy.run_path(str(helper), run_name='__main__')

# Keep the public app version unchanged while iterating on the runtime bridge.
project = PROJECT.read_text()
project = project.replace('MARKETING_VERSION: 2.0.0', 'MARKETING_VERSION: 1.9.0', 1)
project = project.replace('CURRENT_PROJECT_VERSION: 20', 'CURRENT_PROJECT_VERSION: 19', 1)
PROJECT.write_text(project)

print('Updated MPV iOS 1.9.0 build 19 with native yt-dlp, playlists, safe YouTube routing, and live landscape Metal resizing.')
