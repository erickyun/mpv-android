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

# Build the embedded yt-dlp/player integration in layers. v20 is the public
# feature step: generic yt-dlp routing with Unsupported -> direct fallback,
# TorBox dashboard download links, chapter menus (including yt-dlp chapters),
# and live gpu-next deband controls inside Playback settings.
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
]
for name in helpers:
    helper = Path(__file__).with_name(name)
    runpy.run_path(str(helper), run_name='__main__')

# Earlier internal helpers temporarily use 2.0/20 and the old chain rolled it
# back to 1.9/19. v20 is now the actual public 2.0 release, so normalize and
# assert those final version markers instead of rolling them back.
project = PROJECT.read_text()
if 'MARKETING_VERSION: 1.9.0' in project:
    project = project.replace('MARKETING_VERSION: 1.9.0', 'MARKETING_VERSION: 2.0.0', 1)
if 'CURRENT_PROJECT_VERSION: 19' in project:
    project = project.replace('CURRENT_PROJECT_VERSION: 19', 'CURRENT_PROJECT_VERSION: 20', 1)
if 'MARKETING_VERSION: 2.0.0' not in project or 'CURRENT_PROJECT_VERSION: 20' not in project:
    raise SystemExit('MPV iOS 2.0.0 build 20 version markers were not produced')
PROJECT.write_text(project)

print('Updated MPV iOS 2.0.0 build 20 with generic yt-dlp routing, TorBox dashboard URLs, chapters, live deband, and rotation recovery.')