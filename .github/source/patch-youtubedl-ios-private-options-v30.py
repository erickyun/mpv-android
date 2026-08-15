from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-private-options-v30.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()

old = '''        # Private MPV-iOS safety switch. Never pass this key to yt-dlp.
        safe_metadata = _mpv_ios_truthy(raw.pop('mpv-ios-safe-metadata', False))
        os.environ.pop('MPV_IOS_SAFE_METADATA', None)
        if safe_metadata:
            os.environ['MPV_IOS_SAFE_METADATA'] = '1'
            # Playback does not need sidecar metadata writes.
            base['writethumbnail'] = False
            base['list_thumbnails'] = False
            base['writeinfojson'] = False
            base['writedescription'] = False
            base['getcomments'] = False
            base['embedthumbnail'] = False
            base['convertthumbnails'] = None

        argv = []
'''
new = '''        # Private MPV-iOS switches. The host has already resolved the optional
        # site allow-list against the current URL, so safe_metadata is the final
        # yes/no decision for this extraction. Never pass private keys to yt-dlp.
        safe_metadata = _mpv_ios_truthy(raw.pop('mpv-ios-safe-metadata', False))
        safe_sites = raw.pop('mpv-ios-safe-metadata-sites', None)
        log_enabled = _mpv_ios_truthy(
            raw.pop('mpv-ios-ytdl-log', raw.pop('mpv-ios-logs', False))
        )

        os.environ.pop('MPV_IOS_SAFE_METADATA', None)
        if safe_metadata:
            os.environ['MPV_IOS_SAFE_METADATA'] = '1'
            # Playback does not need sidecar metadata writes.
            base['writethumbnail'] = False
            base['list_thumbnails'] = False
            base['writeinfojson'] = False
            base['writedescription'] = False
            base['getcomments'] = False
            base['embedthumbnail'] = False
            base['convertthumbnails'] = None

        # When the host enabled the Files-visible log, make yt-dlp verbose too.
        # The actual logger/path is installed by the Swift bridge through
        # YTDLP_LOG_PATH before YoutubeDL(options) is constructed.
        if log_enabled:
            base['verbose'] = True

        argv = []
'''
if old not in text:
    raise SystemExit('private safe metadata block not found')
text = text.replace(old, new, 1)

old = '''        if safe_metadata:
            changed.append('mpv-ios-safe-metadata')

        return {'ok': True, 'error': '', 'keys': sorted(set(changed))}
'''
new = '''        if safe_metadata:
            changed.append('mpv-ios-safe-metadata')
        if safe_sites is not None:
            changed.append('mpv-ios-safe-metadata-sites')
        if log_enabled:
            changed.append('mpv-ios-ytdl-log')

        return {'ok': True, 'error': '', 'keys': sorted(set(changed))}
'''
if old not in text:
    raise SystemExit('private changed-keys block not found')
text = text.replace(old, new, 1)

path.write_text(text)
print(f'Patched {path}: private safe-site and log options are consumed before yt-dlp parsing.')
