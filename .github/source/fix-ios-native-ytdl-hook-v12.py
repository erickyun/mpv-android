from pathlib import Path

path = Path('MPVTorBox/Player/MPVMetalViewController.swift')
text = path.read_text()
old = 'guard let context else { return }'
count = text.count(old)
if count != 2:
    raise SystemExit(f'Expected exactly 2 native hook context guards, found {count}')
text = text.replace(old, 'guard let context = mpv else { return }')
path.write_text(text)
print('Fixed native yt-dlp hook to use MPVMetalViewController.mpv handle.')
