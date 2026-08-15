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
new = '''        # Private MPV-iOS switches. Never pass these keys to yt-dlp.
        # Safe mode is requested globally here; the optional site allow-list is
        # evaluated later against the actual URL in extractInfo().
        safe_metadata = _mpv_ios_truthy(raw.pop('mpv-ios-safe-metadata', False))
        raw_sites = raw.pop('mpv-ios-safe-metadata-sites', None)
        log_enabled = _mpv_ios_truthy(
            raw.pop('mpv-ios-ytdl-log', raw.pop('mpv-ios-logs', False))
        )

        sites = []
        if raw_sites is not None:
            for token in str(raw_sites).replace(';', ',').replace('|', ',').split(','):
                token = token.strip().lower()
                if token.startswith('http://') or token.startswith('https://'):
                    try:
                        from urllib.parse import urlsplit
                        token = (urlsplit(token).hostname or '').lower()
                    except BaseException:
                        token = ''
                token = token.lstrip('*.').strip('.')
                if token and '.' in token and token not in sites:
                    sites.append(token)

            # mpv string-map itself is comma-separated. With the requested syntax
            #   mpv-ios-safe-metadata-sites=xhamster.com,pornhub.com
            # later domains may arrive as empty option keys. Consume only values
            # that clearly look like bare hostnames.
            for key, value in list(raw.items()):
                candidate = str(key).strip().lower()
                empty_value = value is None or str(value).strip() == ''
                looks_like_host = (
                    empty_value and '.' in candidate and '/' not in candidate
                    and '=' not in candidate
                    and all(ch.isalnum() or ch in '.-*' for ch in candidate)
                )
                if looks_like_host:
                    candidate = candidate.lstrip('*.').strip('.')
                    if candidate and candidate not in sites:
                        sites.append(candidate)
                    raw.pop(key, None)

        for name in (
            'MPV_IOS_SAFE_METADATA',
            'MPV_IOS_SAFE_METADATA_REQUESTED',
            'MPV_IOS_SAFE_METADATA_SITES',
            'MPV_IOS_YTDL_LOG',
        ):
            os.environ.pop(name, None)

        if safe_metadata:
            os.environ['MPV_IOS_SAFE_METADATA_REQUESTED'] = '1'
        if sites:
            os.environ['MPV_IOS_SAFE_METADATA_SITES'] = ','.join(sites)
        if log_enabled:
            os.environ['MPV_IOS_YTDL_LOG'] = '1'
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
        if raw_sites is not None or sites:
            changed.append('mpv-ios-safe-metadata-sites')
        if log_enabled:
            changed.append('mpv-ios-ytdl-log')

        return {'ok': True, 'error': '', 'keys': sorted(set(changed))}
'''
if old not in text:
    raise SystemExit('private changed-keys block not found')
text = text.replace(old, new, 1)

old = '''            let changedKeys = Array<String>(rawResult["keys"]) ?? []
            mpvYTDLPBridgeLog("applied ytdl-raw-options keys: \\(changedKeys.joined(separator: ","))")
        } else {
            unsetenv("MPV_IOS_SAFE_METADATA")
        }

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
'''
new = '''            let changedKeys = Array<String>(rawResult["keys"]) ?? []

            if getenv("MPV_IOS_YTDL_LOG") != nil {
                if let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first {
                    let logURL = documents
                        .appendingPathComponent("Logs", isDirectory: true)
                        .appendingPathComponent("yt-dlp.log")
                    try? FileManager.default.createDirectory(
                        at: logURL.deletingLastPathComponent(),
                        withIntermediateDirectories: true
                    )
                    try? FileManager.default.removeItem(at: logURL)
                    setenv("YTDLP_LOG_PATH", logURL.path, 1)
                }
            } else {
                unsetenv("YTDLP_LOG_PATH")
            }

            mpvYTDLPBridgeLog("applied ytdl-raw-options keys: \\(changedKeys.joined(separator: ","))")
        } else {
            unsetenv("MPV_IOS_SAFE_METADATA")
            unsetenv("MPV_IOS_SAFE_METADATA_REQUESTED")
            unsetenv("MPV_IOS_SAFE_METADATA_SITES")
            unsetenv("MPV_IOS_YTDL_LOG")
            unsetenv("YTDLP_LOG_PATH")
        }

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
'''
if old not in text:
    raise SystemExit('Swift raw-option/log block not found')
text = text.replace(old, new, 1)

path.write_text(text)
print(f'Patched {path}: bridge-native site-scoped safe mode and opt-in Files-visible logging.')
