from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-mpv-format.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f'YoutubeDL {label} anchor was not found')
    text = text.replace(old, new, 1)

replace_once(
    '''        mpvYTDLPBridgeLog("external JS runtimes disabled; Apple WebKit JSI + official ejs:github enabled")

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
''',
    '''        mpvYTDLPBridgeLog("external JS runtimes disabled; Apple WebKit JSI + official ejs:github enabled")

        // MPV's iOS on_load hook passes the normal mpv.conf ytdl-format value
        // through the host environment. Keep yt-dlp itself as the selector parser
        // so the full native selector grammar (including +, / and filters) works.
        if let rawFormat = getenv("MPV_YTDL_FORMAT") {
            let requestedFormat = String(cString: rawFormat)
            if !requestedFormat.isEmpty && requestedFormat != "ytdl" {
                effectiveOptions["format"] = requestedFormat
                mpvYTDLPBridgeLog("using MPV ytdl-format: \\(requestedFormat)")
            }
        }

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
''',
    'MPV format injection',
)

replace_once(
    '''        mpvYTDLPBridgeLog("format selector begin")
        let format_selector = pythonObject.build_format_selector(options!["format"])
        let formats_to_download = format_selector(info)
        mpvYTDLPBridgeLog("format selector complete")
        var formats: [Format] = []
        let decoder = PythonDecoder()
        for format in formats_to_download {
            let format = try decoder.decode(Format.self, from: format)
            formats.append(format)
        }
''',
    '''        mpvYTDLPBridgeLog("format selector begin")
        let format_selector = pythonObject.build_format_selector(options!["format"])
        let formats_to_download = format_selector(info)

        // A normal yt-dlp selector such as bv+ba yields a synthetic merged item
        // whose actual network tracks live under requested_formats. Flatten that
        // item before Swift decoding, exactly as mpv's desktop ytdl_hook consumes
        // requested_formats from yt-dlp's JSON output.
        let builtins = Python.import("builtins")
        let mainModule = Python.import("__main__")
        let flattenSource = #"""
def _mpv_ios_flatten_selected_formats(items):
    flattened = []
    for item in items:
        requested = item.get('requested_formats') or item.get('requested_downloads')
        if requested:
            flattened.extend(requested)
        elif item.get('url'):
            flattened.append(item)
    return flattened
"""#
        _ = builtins.exec(flattenSource, mainModule.__dict__)
        let flattenedFormats = mainModule._mpv_ios_flatten_selected_formats(formats_to_download)
        mpvYTDLPBridgeLog("format selector complete; flattened=\\(Python.len(flattenedFormats))")

        var formats: [Format] = []
        let decoder = PythonDecoder()
        for selectedFormat in flattenedFormats {
            let decoded = try decoder.decode(Format.self, from: selectedFormat)
            formats.append(decoded)
        }
''',
    'flatten selected formats',
)

path.write_text(text)
print(f'Patched {path}: MPV ytdl-format injection and requested_formats flattening.')
