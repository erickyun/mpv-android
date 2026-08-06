from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-mainthread.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f'YoutubeDL {label} anchor was not found')
    text = text.replace(old, new, 1)


replace_once(
    '''public let defaultOptions: PythonObject = [
    "format": "bestvideo,bestaudio[ext=m4a]/best",
    "nocheckcertificate": true,
    "verbose": true,
]
''',
    '''public let defaultOptions: PythonObject = [
    "format": "bestvideo,bestaudio[ext=m4a]/best",
    "nocheckcertificate": true,
    "verbose": true,
    "socket_timeout": 12,
    "retries": 1,
    "extractor_retries": 1,
    "fragment_retries": 1,
    "noplaylist": true,
]
''',
    'defaultOptions',
)

# PythonKit, CPython, and the Apple WebKit JSI provider must all be created and
# used on the iOS main actor. Keep the library's existing tested implementation
# and only add actor isolation instead of replacing the method bodies.
replace_once(
    '    func loadPythonModule(downloadPythonModule: Bool = true) async throws -> PythonObject {\n',
    '''    // Embedded yt-dlp and WebKit must initialize on the iOS main thread.
    // SSLContext creation remains inside Python; failures propagate as the real Python error.
    @MainActor
    func loadPythonModule(downloadPythonModule: Bool = true) async throws -> PythonObject {
''',
    'loadPythonModule',
)
replace_once(
    '    func makePythonObject(_ options: PythonObject? = nil, initializePython: Bool = true) async throws -> PythonObject {\n',
    '    @MainActor\n    func makePythonObject(_ options: PythonObject? = nil, initializePython: Bool = true) async throws -> PythonObject {\n',
    'makePythonObject',
)
replace_once(
    '    open func extractInfo(url: URL) async throws -> ([Format], Info) {\n',
    '    @MainActor\n    open func extractInfo(url: URL) async throws -> ([Format], Info) {\n',
    'extractInfo',
)

# Explicitly load current yt-dlp plugins after importing the downloaded module.
# This makes the bundled Apple WebKit JSI provider visible before YoutubeDL()
# builds its extractor registry.
replace_once(
    '''        let pythonModule = try Python.attemptImport("yt_dlp")
        version = String(pythonModule.version.__version__)
        return pythonModule
''',
    '''        let pythonModule = try Python.attemptImport("yt_dlp")
        version = String(pythonModule.version.__version__)
        let plugins = try Python.attemptImport("yt_dlp.plugins")
        _ = plugins.load_all_plugins()
        return pythonModule
''',
    'plugin loading',
)

path.write_text(text)
print(f'Patched {path}: Python, plugin loading, and extract_info are isolated to MainActor.')
