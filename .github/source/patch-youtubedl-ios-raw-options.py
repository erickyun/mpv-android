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

def _mpv_ios_apply_raw_options(base, raw_json):
    try:
        from yt_dlp import parse_options
        raw = json.loads(raw_json)
        if not isinstance(raw, dict):
            return {'ok': False, 'error': 'ytdl-raw-options is not a map', 'keys': []}

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
        }

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
'''

if old not in text:
    raise SystemExit('MPV ytdl-format anchor was not found')
text = text.replace(old, new, 1)
path.write_text(text)
print(f'Patched {path}: generic mpv ytdl-raw-options via yt-dlp parse_options().')
