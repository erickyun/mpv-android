from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-raw-options.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f'YoutubeDL raw-options {label} anchor was not found')
    text = text.replace(old, new, 1)


# 1) General mpv ytdl-raw-options passthrough + one private MPV-iOS switch.
# The private switch is removed before yt-dlp's own parser sees the rest.
replace_once(
    '''        if let rawFormat = getenv("MPV_YTDL_FORMAT") {
            let requestedFormat = String(cString: rawFormat)
            if !requestedFormat.isEmpty && requestedFormat != "ytdl" {
                effectiveOptions["format"] = requestedFormat.pythonObject
                mpvYTDLPBridgeLog("using MPV ytdl-format: \\(requestedFormat)")
            }
        }

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
''',
    '''        if let rawFormat = getenv("MPV_YTDL_FORMAT") {
            let requestedFormat = String(cString: rawFormat)
            if !requestedFormat.isEmpty && requestedFormat != "ytdl" {
                effectiveOptions["format"] = requestedFormat.pythonObject
                mpvYTDLPBridgeLog("using MPV ytdl-format: \\(requestedFormat)")
            }
        }

        if let rawOptionsPointer = getenv("MPV_YTDL_RAW_OPTIONS_JSON") {
            let rawOptionsJSON = String(cString: rawOptionsPointer)
            let builtins = Python.import("builtins")
            let mainModule = Python.import("__main__")
            let rawOptionsSource = #"""
import json
import os

def _mpv_ios_truthy(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'yes', 'true', 'on', 'enable', 'enabled'}

def _mpv_ios_apply_raw_options(base, raw_json):
    try:
        from yt_dlp import parse_options
        raw = json.loads(raw_json)
        if not isinstance(raw, dict):
            return {'ok': False, 'error': 'ytdl-raw-options is not a map', 'keys': []}

        # Private MPV-iOS safety switch. Never pass this key to yt-dlp.
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
        explicit = set()
        for key, value in raw.items():
            key = str(key).strip().lstrip('-')
            if not key:
                continue
            explicit.add(key)
            argv.append('--' + key)
            value = '' if value is None else str(value)
            # Match mpv's stock hook: empty values are flag-only, except proxy
            # where an explicit empty string is meaningful.
            if value != '' or key == 'proxy':
                argv.append(value)

        baseline = parse_options([]).ydl_opts
        parsed = parse_options(argv).ydl_opts
        changed = []
        for key, value in parsed.items():
            try:
                different = value != baseline.get(key)
            except Exception:
                different = True
            if different:
                base[key] = value
                changed.append(key)

        # Preserve explicit CLI reset semantics for options whose parsed value is
        # equal to yt-dlp's baseline but differs from this app's defaults.
        if 'yes-playlist' in explicit:
            base['noplaylist'] = False
            changed.append('noplaylist')
        if 'no-playlist' in explicit:
            base['noplaylist'] = True
            changed.append('noplaylist')
        if 'check-certificates' in explicit:
            base['nocheckcertificate'] = False
            changed.append('nocheckcertificate')
        if 'no-check-certificates' in explicit:
            base['nocheckcertificate'] = True
            changed.append('nocheckcertificate')
        if safe_metadata:
            changed.append('mpv-ios-safe-metadata')

        return {'ok': True, 'error': '', 'keys': sorted(set(changed))}
    except BaseException as exc:
        return {
            'ok': False,
            'error': f'{type(exc).__name__}: {exc}',
            'keys': [],
        }
"""#
            _ = builtins.exec(rawOptionsSource, mainModule.__dict__)
            let rawResult = mainModule._mpv_ios_apply_raw_options(effectiveOptions, rawOptionsJSON)
            let ok = Bool(rawResult["ok"]) ?? false
            if !ok {
                let error = String(rawResult["error"]) ?? "unknown raw-option parsing error"
                throw NSError(
                    domain: "YoutubeDL.RawOptions",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "Invalid ytdl-raw-options: \\(error)"]
                )
            }
            let changedKeys = Array<String>(rawResult["keys"]) ?? []
            mpvYTDLPBridgeLog("applied ytdl-raw-options keys: \\(changedKeys.joined(separator: ","))")
        } else {
            unsetenv("MPV_IOS_SAFE_METADATA")
        }

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
''',
    'option parsing',
)

# 2) In safe mode, do not let an arbitrary Python exception cross PythonKit's
# dynamicCall boundary. Convert it to a normal NSError instead.
replace_once(
    '''        print(#function, url)
        mpvYTDLPBridgeLog("python extract_info begin; main=\\(Thread.isMainThread)")
        let info = try pythonObject.extract_info.throwing.dynamicallyCall(withKeywordArguments: ["": url.absoluteString, "download": false, "process": true])
        mpvYTDLPBridgeLog("python extract_info complete")
        print(info)
''',
    '''        print(#function, url)
        mpvYTDLPBridgeLog("python extract_info begin; main=\\(Thread.isMainThread)")
        let safeMetadata = getenv("MPV_IOS_SAFE_METADATA") != nil
        let info: PythonObject
        if safeMetadata {
            let builtins = Python.import("builtins")
            let mainModule = Python.import("__main__")
            let safeExtractSource = #"""
def _mpv_ios_safe_extract(ydl, url):
    try:
        return {
            'ok': True,
            'info': ydl.extract_info(url, download=False, process=True),
            'error': '',
        }
    except BaseException as exc:
        return {
            'ok': False,
            'info': None,
            'error': f'{type(exc).__name__}: {exc}',
        }
"""#
            _ = builtins.exec(safeExtractSource, mainModule.__dict__)
            let safeResult = mainModule._mpv_ios_safe_extract(pythonObject, url.absoluteString)
            let ok = Bool(safeResult["ok"]) ?? false
            if !ok {
                let error = String(safeResult["error"]) ?? "unknown yt-dlp extraction error"
                throw NSError(
                    domain: "YoutubeDL.SafeExtract",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: error]
                )
            }
            info = safeResult["info"]
        } else {
            info = try pythonObject.extract_info.throwing.dynamicallyCall(
                withKeywordArguments: ["": url.absoluteString, "download": false, "process": true]
            )
        }
        mpvYTDLPBridgeLog("python extract_info complete")
        if !safeMetadata { print(info) }
''',
    'safe extract wrapper',
)

# 3) Safe mode must never use YoutubeDL-iOS 0.0.9's PythonDecoder. That decoder
# contains fatalError() and force unwraps for unexpected Python shapes. Instead,
# normalize only playback-relevant primitives in Python, JSON-serialize them,
# and decode them using Foundation.JSONDecoder. With safe mode OFF the original
# PythonDecoder path remains byte-for-byte equivalent in behavior.
old_decode = '''        var formats: [Format] = []
        let decoder = PythonDecoder()
        for selectedFormat in flattenedFormats {
            let decoded = try decoder.decode(Format.self, from: selectedFormat)
            formats.append(decoded)
        }
        
        let decodedInfo = try decoder.decode(Info.self, from: info)
        mpvYTDLPBridgeLog("extractInfo decoded \\(formats.count) selected formats and \\(decodedInfo.formats.count) total formats")
        return (formats, decodedInfo)
'''
new_decode = '''        if safeMetadata {
            let builtins = Python.import("builtins")
            let mainModule = Python.import("__main__")
            let payloadSource = #"""
import json

def _mpv_ios_number(value, integer=False):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if integer else float(value)
    return None

def _mpv_ios_text(value, fallback=''):
    if value is None:
        return fallback
    try:
        return str(value)
    except BaseException:
        return fallback

def _mpv_ios_headers(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if key is None or item is None:
            continue
        result[_mpv_ios_text(key)] = _mpv_ios_text(item)
    return result

def _mpv_ios_format(item):
    if not isinstance(item, dict):
        return None
    url = _mpv_ios_text(item.get('url'))
    if not url:
        return None
    acodec = item.get('acodec')
    vcodec = item.get('vcodec')
    ext = _mpv_ios_text(item.get('ext'), 'unknown')
    result = {
        'format_id': _mpv_ios_text(item.get('format_id'), 'unknown'),
        'url': url,
        'ext': ext,
        'protocol': _mpv_ios_text(item.get('protocol'), 'https'),
        'audio_ext': _mpv_ios_text(item.get('audio_ext'), 'none' if acodec == 'none' else ext),
        'video_ext': _mpv_ios_text(item.get('video_ext'), 'none' if vcodec == 'none' else ext),
        'format': _mpv_ios_text(item.get('format'), _mpv_ios_text(item.get('format_id'), 'unknown')),
        'http_headers': _mpv_ios_headers(item.get('http_headers')),
    }
    string_keys = (
        'format_note', 'language', 'vcodec', 'acodec', 'dynamic_range',
        'container', 'resolution',
    )
    for key in string_keys:
        value = item.get(key)
        if value is not None:
            result[key] = _mpv_ios_text(value)
    int_keys = ('asr', 'filesize', 'height', 'width', 'language_preference')
    for key in int_keys:
        value = _mpv_ios_number(item.get(key), integer=True)
        if value is not None:
            result[key] = value
    float_keys = ('fps', 'quality', 'tbr', 'abr', 'vbr')
    for key in float_keys:
        value = _mpv_ios_number(item.get(key))
        if value is not None:
            result[key] = value
    return result

def _mpv_ios_chapters(value):
    if not isinstance(value, (list, tuple)):
        return None
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        chapter = {}
        if item.get('title') is not None:
            chapter['title'] = _mpv_ios_text(item.get('title'))
        start = _mpv_ios_number(item.get('start_time'))
        end = _mpv_ios_number(item.get('end_time'))
        if start is not None:
            chapter['start_time'] = start
        if end is not None:
            chapter['end_time'] = end
        result.append(chapter)
    return result

def _mpv_ios_safe_payload(info, selected):
    selected_formats = []
    for item in selected:
        normalized = _mpv_ios_format(item)
        if normalized is not None:
            selected_formats.append(normalized)

    if not isinstance(info, dict):
        info = {}
    video_id = _mpv_ios_text(info.get('id'), 'video')
    title = _mpv_ios_text(info.get('title'), video_id)
    summary = {
        'id': video_id,
        'title': title,
        'formats': selected_formats,
        'webpage_url_basename': _mpv_ios_text(
            info.get('webpage_url_basename'),
            _mpv_ios_text(info.get('display_id'), video_id),
        ),
    }

    duration = _mpv_ios_number(info.get('duration'))
    if duration is not None:
        summary['duration'] = duration
    chapters = _mpv_ios_chapters(info.get('chapters'))
    if chapters is not None:
        summary['chapters'] = chapters

    for key in (
        'webpage_url', 'original_url', 'extractor', 'extractor_key',
        'display_id', 'uploader', 'uploader_id', 'uploader_url',
        'channel', 'channel_id', 'channel_url', 'availability', 'live_status',
    ):
        value = info.get(key)
        if value is not None:
            summary[key] = _mpv_ios_text(value)
    for key in ('is_live', 'was_live', 'playable_in_embed', '__has_drm'):
        value = info.get(key)
        if isinstance(value, bool):
            summary[key] = value
    for key in ('view_count', 'age_limit', 'like_count', 'release_timestamp'):
        value = _mpv_ios_number(info.get(key), integer=True)
        if value is not None:
            summary[key] = value

    return json.dumps(
        {'formats': selected_formats, 'info': summary},
        ensure_ascii=False,
        separators=(',', ':'),
    )
"""#
            _ = builtins.exec(payloadSource, mainModule.__dict__)
            let payloadObject = mainModule._mpv_ios_safe_payload(info, flattenedFormats)
            guard let payloadJSON = String(payloadObject),
                  let payloadData = payloadJSON.data(using: .utf8) else {
                throw NSError(
                    domain: "YoutubeDL.SafeDecode",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "Could not serialize safe yt-dlp payload"]
                )
            }

            struct SafePayload: Decodable {
                let formats: [Format]
                let info: Info
            }
            let payload = try JSONDecoder().decode(SafePayload.self, from: payloadData)
            mpvYTDLPBridgeLog("safe decode produced \\(payload.formats.count) selected formats")
            return (payload.formats, payload.info)
        }

        var formats: [Format] = []
        let decoder = PythonDecoder()
        for selectedFormat in flattenedFormats {
            let decoded = try decoder.decode(Format.self, from: selectedFormat)
            formats.append(decoded)
        }
        
        let decodedInfo = try decoder.decode(Info.self, from: info)
        mpvYTDLPBridgeLog("extractInfo decoded \\(formats.count) selected formats and \\(decodedInfo.formats.count) total formats")
        return (formats, decodedInfo)
'''
replace_once(old_decode, new_decode, 'safe JSON decode')

path.write_text(text)
print(f'Patched {path}: general raw options plus opt-in exception shielding and Foundation JSON safe decode.')
