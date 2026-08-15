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

        // This player only extracts playback URLs. Explicitly disable thumbnail
        // writes so a site's broken thumbnail metadata can never enter yt-dlp's
        // file-extension/write pipeline. Do not use allow-unsafe-ext here.
        effectiveOptions["writethumbnail"] = PythonObject(false)
        effectiveOptions["write_all_thumbnails"] = PythonObject(false)
        mpvYTDLPBridgeLog("external JS runtimes disabled; Apple WebKit JSI + official ejs:github enabled")

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
'''
if old not in text:
    raise SystemExit('effectiveOptions anchor was not found')
text = text.replace(old, new, 1)

plugin_old = '''        mpvYTDLPBridgeLog("load_all_plugins complete; Apple WebKit provider should now be registered")
        return pythonModule
'''
plugin_new = '''        mpvYTDLPBridgeLog("load_all_plugins complete; Apple WebKit provider should now be registered")

        // yt-dlp 2026.07.04 still has an open xHamster extractor bug where the
        // thumbnail CDN suffix can be interpreted as an unsafe extension. MPV
        // never uses website thumbnails, so strip only those metadata fields at
        // the extractor boundary. Video/audio formats remain untouched.
        let builtins = Python.import("builtins")
        let mainModule = Python.import("__main__")
        let xhamsterGuardSource = #"""
def _mpv_ios_install_xhamster_guard():
    try:
        from yt_dlp.extractor.xhamster import XHamsterIE
        if getattr(XHamsterIE, '_mpv_ios_thumbnail_guard', False):
            return 'already-installed'
        original = XHamsterIE._real_extract
        def guarded_real_extract(self, url):
            result = original(self, url)
            if isinstance(result, dict):
                result.pop('thumbnail', None)
                result.pop('thumbnails', None)
            return result
        XHamsterIE._real_extract = guarded_real_extract
        XHamsterIE._mpv_ios_thumbnail_guard = True
        return 'installed'
    except Exception as exc:
        return f'failed:{type(exc).__name__}:{exc}'
"""#
        _ = builtins.exec(xhamsterGuardSource, mainModule.__dict__)
        let xhamsterGuardStatus = String(mainModule._mpv_ios_install_xhamster_guard())
        mpvYTDLPBridgeLog("xHamster thumbnail metadata guard: \\(xhamsterGuardStatus)")
        return pythonModule
'''
if plugin_old not in text:
    raise SystemExit('plugin-load anchor was not found')
text = text.replace(plugin_old, plugin_new, 1)

path.write_text(text)
print(f'Patched {path}: disabled external runtimes, enabled WebKit JSI/EJS, and guarded xHamster thumbnail metadata.')

# Extend the same bridge with MPV's native ytdl-format selector and flatten
# bv+ba requested_formats into separate streams for libmpv's EDL input.
helper = Path(__file__).with_name('patch-youtubedl-ios-mpv-format.py')
runpy.run_path(str(helper), run_name='__main__')