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

# Apply the MPV on_load -> Swift -> embedded yt-dlp bridge after the verified v9
# runtime fixes. The release workflow remains on 1.9.0/build 19 for compatibility.
helper = Path(__file__).with_name('fix-ios-mpv-ytdl-hook-v10.py')
runpy.run_path(str(helper), run_name='__main__')
project = PROJECT.read_text()
project = project.replace('MARKETING_VERSION: 2.0.0', 'MARKETING_VERSION: 1.9.0', 1)
project = project.replace('CURRENT_PROJECT_VERSION: 20', 'CURRENT_PROJECT_VERSION: 19', 1)
PROJECT.write_text(project)

print('Updated MPV iOS 1.9.0 build 19 with the embedded MPV ytdl hook bridge.')
