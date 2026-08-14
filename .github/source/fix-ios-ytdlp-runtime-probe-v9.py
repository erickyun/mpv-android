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

# Build the embedded yt-dlp/player integration in layers. v20 adds generic
# yt-dlp routing with Unsupported -> direct fallback, TorBox dashboard links,
# chapters, and live deband. v21 centers the landscape toolbar and makes every
# deband parameter update through mpv's runtime set command with live readback.
helpers = [
    'fix-ios-mpv-ytdl-hook-v10.py',
    'fix-ios-native-ytdl-hook-v11.py',
    'fix-ios-native-ytdl-hook-v12.py',
    'fix-ios-ytdl-seek-duration-v13.py',
    'fix-ios-remove-ytdlp-log-v14.py',
    'fix-ios-ytdl-playlist-picker-v15.py',
    'fix-ios-general-playlist-v16.py',
    'fix-ios-youtube-single-url-crash-v17.py',
    'fix-ios-landscape-render-resize-v18.py',
    'fix-ios-rotation-video-track-reopen-v19.py',
    'fix-ios-routing-torbox-chapters-deband-v20.py',
    'fix-ios-toolbar-deband-v21.py',
]
for name in helpers:
    helper = Path(__file__).with_name(name)
    runpy.run_path(str(helper), run_name='__main__')

# Keep the current public app version while iterating on feature layers.
project = PROJECT.read_text()
project = project.replace('MARKETING_VERSION: 2.0.0', 'MARKETING_VERSION: 1.9.0', 1)
project = project.replace('CURRENT_PROJECT_VERSION: 20', 'CURRENT_PROJECT_VERSION: 19', 1)
if 'MARKETING_VERSION: 1.9.0' not in project or 'CURRENT_PROJECT_VERSION: 19' not in project:
    raise SystemExit('MPV iOS 1.9.0 build 19 version markers were not produced')
PROJECT.write_text(project)

print('Updated MPV iOS 1.9.0 build 19 with centered landscape controls, generic yt-dlp, TorBox dashboard URLs, chapters, reliable live deband, and rotation recovery.')
