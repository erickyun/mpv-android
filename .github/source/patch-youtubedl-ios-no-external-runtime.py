from pathlib import Path
import runpy
import sys

# Wrapper for the verified iOS bridge patches. Touching this file intentionally
# retriggers the release workflow after selector/runtime fixes.

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
        // The downloaded yt-dlp zip does not bundle the optional yt-dlp-ejs
        // distribution. Permit only yt-dlp's official EJS component download;
        // Apple WebKit JSI executes it on-device without an external runtime.
        effectiveOptions["remote_components"] = builtins.set(["ejs:github"])
        effectiveOptions["verbose"] = false
        mpvYTDLPBridgeLog("external JS runtimes disabled; Apple WebKit JSI + official ejs:github enabled")

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
'''
if old not in text:
    raise SystemExit('effectiveOptions anchor was not found')
text = text.replace(old, new, 1)

path.write_text(text)
print(f'Patched {path}: disabled external runtimes, enabled WebKit JSI and official EJS component.')

# Extend the same bridge with MPV's native ytdl-format selector and flatten
# bv+ba requested_formats into separate streams for libmpv's EDL input.
helper = Path(__file__).with_name('patch-youtubedl-ios-mpv-format.py')
runpy.run_path(str(helper), run_name='__main__')
