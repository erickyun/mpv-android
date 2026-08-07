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
# MPV has the complete seek range before the remote files are buffered.
helper = Path(__file__).with_name('fix-ios-mpv-ytdl-hook-v10.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-native-ytdl-hook-v11.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-native-ytdl-hook-v12.py')
runpy.run_path(str(helper), run_name='__main__')
helper = Path(__file__).with_name('fix-ios-ytdl-seek-duration-v13.py')
runpy.run_path(str(helper), run_name='__main__')

# Keep the public app version unchanged while iterating on the runtime bridge.
project = PROJECT.read_text()
project = project.replace('MARKETING_VERSION: 2.0.0', 'MARKETING_VERSION: 1.9.0', 1)
project = project.replace('CURRENT_PROJECT_VERSION: 20', 'CURRENT_PROJECT_VERSION: 19', 1)
PROJECT.write_text(project)

print('Updated MPV iOS 1.9.0 build 19 with native yt-dlp full-duration seeking.')
