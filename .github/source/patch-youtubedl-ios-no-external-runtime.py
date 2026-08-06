from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-no-external-runtime.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()

old = '''        let effectiveOptions = suppliedOptions ?? defaultOptions

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
'''
new = '''        let effectiveOptions = suppliedOptions ?? defaultOptions

        // yt-dlp enables Deno by default. iOS cannot execute external Deno/Node/
        // QuickJS binaries, and probing them during YoutubeDL(options) can block
        // inside the embedded Python subprocess shim. Clear normal JS runtimes;
        // the bundled apple-webkit-jsi plugin remains registered independently.
        let builtins = Python.import("builtins")
        effectiveOptions["js_runtimes"] = builtins.dict()
        effectiveOptions["remote_components"] = builtins.set()
        effectiveOptions["verbose"] = false
        mpvYTDLPBridgeLog("external JS runtimes disabled; Apple WebKit JSI plugin only")

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
'''
if old not in text:
    raise SystemExit('effectiveOptions anchor was not found')
text = text.replace(old, new, 1)

path.write_text(text)
print(f'Patched {path}: disabled external Deno/Node/QuickJS probing and verbose constructor scan.')
