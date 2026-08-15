from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-raw-options.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()

old = '''        if let rawFormat = getenv("MPV_YTDL_FORMAT") {
            let requestedFormat = String(cString: rawFormat)
            if !requestedFormat.isEmpty && requestedFormat != "ytdl" {
                effectiveOptions["format"] = requestedFormat.pythonObject
                mpvYTDLPBridgeLog("using MPV ytdl-format: \\(requestedFormat)")
            }
        }

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
'''
new = '''        if let rawFormat = getenv("MPV_YTDL_FORMAT") {
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

        # MPV-iOS private option. It is consumed by the bridge and deliberately
        # removed before yt-dlp's CLI parser sees the remaining raw options.
        safe_metadata = _mpv_ios_truthy(raw.pop('mpv-ios-safe-metadata', False))
        os.environ.pop('MPV_IOS_SAFE_METADATA', None)
        if safe_metadata:
            os.environ['MPV_IOS_SAFE_METADATA'] = '1'
            # Playback never needs metadata sidecar files. Force the risky
            # thumbnail/file-writing paths off while safe mode is enabled.
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

        # MPV iOS has a few non-yt-dlp defaults. Preserve stock CLI semantics
        # for flags that explicitly reset one of those values to yt-dlp's normal
        # default, even though such a value would not differ from the baseline.
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
'''

if old not in text:
    raise SystemExit('MPV ytdl-format anchor was not found')
text = text.replace(old, new, 1)

old_extract = '''        print(#function, url)
        mpvYTDLPBridgeLog("python extract_info begin; main=\\(Thread.isMainThread)")
        let info = try pythonObject.extract_info.throwing.dynamicallyCall(withKeywordArguments: ["": url.absoluteString, "download": false, "process": true])
        mpvYTDLPBridgeLog("python extract_info complete")
        print(info)
'''
new_extract = '''        print(#function, url)
        mpvYTDLPBridgeLog("python extract_info begin; main=\\(Thread.isMainThread)")
        var info = try pythonObject.extract_info.throwing.dynamicallyCall(withKeywordArguments: ["": url.absoluteString, "download": false, "process": true])
        mpvYTDLPBridgeLog("python extract_info complete")

        if getenv("MPV_IOS_SAFE_METADATA") != nil {
            let builtins = Python.import("builtins")
            let mainModule = Python.import("__main__")
            let sanitizerSource = #"""
def _mpv_ios_safe_metadata(ydl, info):
    try:
        try:
            cleaned = ydl.sanitize_info(info, remove_private_keys=True)
        except TypeError:
            cleaned = ydl.sanitize_info(info)
    except BaseException:
        cleaned = info

    def scrub(value):
        if isinstance(value, dict):
            # These fields are not needed for playback and have historically
            # contained malformed URLs/extensions or huge/non-JSON payloads.
            for key in (
                'thumbnail', 'thumbnails', 'comments', 'heatmap',
                'automatic_captions', '__post_extractor',
                'requested_downloads', 'requested_subtitles',
            ):
                value.pop(key, None)
            for child in list(value.values()):
                if isinstance(child, (dict, list, tuple)):
                    scrub(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                if isinstance(child, (dict, list, tuple)):
                    scrub(child)
        return value

    return scrub(cleaned)
"""#
            _ = builtins.exec(sanitizerSource, mainModule.__dict__)
            info = mainModule._mpv_ios_safe_metadata(pythonObject, info)
            mpvYTDLPBridgeLog("safe metadata protection sanitized extract_info result")
        }
        print(info)
'''

if old_extract not in text:
    raise SystemExit('extract_info anchor was not found for safe metadata protection')
text = text.replace(old_extract, new_extract, 1)

path.write_text(text)
print(f'Patched {path}: generic mpv ytdl-raw-options plus opt-in safe metadata protection.')
