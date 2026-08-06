from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-hybrid.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()


def replace_once(old: str, new: str, label: str) -> None:
    global text
    if old not in text:
        raise SystemExit(f'YoutubeDL {label} anchor was not found')
    text = text.replace(old, new, 1)


replace_once(
    'import Foundation\n',
    '''import Foundation
import Darwin

private func mpvYTDLPBridgeLog(_ message: String) {
    guard let rawPath = getenv("YTDLP_LOG_PATH") else { return }
    let path = String(cString: rawPath)
    let timestamp = ISO8601DateFormatter().string(from: Date())
    let line = "[\\(timestamp)] [Bridge] \\(message)\\n"
    guard let data = line.data(using: .utf8) else { return }
    let url = URL(fileURLWithPath: path)
    try? FileManager.default.createDirectory(
        at: url.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    if FileManager.default.fileExists(atPath: path),
       let handle = try? FileHandle(forWritingTo: url) {
        defer { try? handle.close() }
        try? handle.seekToEnd()
        try? handle.write(contentsOf: data)
    } else {
        try? data.write(to: url, options: .atomic)
    }
}
''',
    'bridge logger',
)

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

replace_once(
    '''    func loadPythonModule(downloadPythonModule: Bool = true) async throws -> PythonObject {
        if Py_IsInitialized() == 0 {
            PythonSupport.initialize()
        }
''',
    '''    // Embedded CPython must initialize on the iOS main actor. The blocking
    // extract_info call intentionally runs on a worker so Apple WebKit callbacks
    // can continue on the main CFRunLoop. SSLContext creation errors are logged.
    @MainActor
    func loadPythonModule(downloadPythonModule: Bool = true) async throws -> PythonObject {
        mpvYTDLPBridgeLog("loadPythonModule enter; main=\\(Thread.isMainThread)")
        if Py_IsInitialized() == 0 {
            mpvYTDLPBridgeLog("PythonSupport.initialize begin")
            PythonSupport.initialize()
            mpvYTDLPBridgeLog("PythonSupport.initialize complete")
        } else {
            mpvYTDLPBridgeLog("Python already initialized")
        }
''',
    'loadPythonModule start',
)

replace_once(
    '''        if !FileManager.default.fileExists(atPath: Self.pythonModuleURL.path) {
            guard downloadPythonModule else {
                throw YoutubeDLError.noPythonModule
            }
            try await Self.downloadPythonModule()
        }
        
        let sys = try Python.attemptImport("sys")
''',
    '''        if !FileManager.default.fileExists(atPath: Self.pythonModuleURL.path) {
            guard downloadPythonModule else {
                mpvYTDLPBridgeLog("yt-dlp module missing and download disabled")
                throw YoutubeDLError.noPythonModule
            }
            mpvYTDLPBridgeLog("yt-dlp module download begin")
            try await Self.downloadPythonModule()
            mpvYTDLPBridgeLog("yt-dlp module download complete")
        } else {
            mpvYTDLPBridgeLog("yt-dlp module exists at \\(Self.pythonModuleURL.path)")
        }

        mpvYTDLPBridgeLog("import sys begin")
        let sys = try Python.attemptImport("sys")
        mpvYTDLPBridgeLog("import sys complete")
''',
    'module and sys import',
)

replace_once(
    '''        let pythonModule = try Python.attemptImport("yt_dlp")
        version = String(pythonModule.version.__version__)
        return pythonModule
''',
    '''        mpvYTDLPBridgeLog("import yt_dlp begin")
        let pythonModule = try Python.attemptImport("yt_dlp")
        version = String(pythonModule.version.__version__)
        mpvYTDLPBridgeLog("import yt_dlp complete; version=\\(version ?? "unknown")")

        mpvYTDLPBridgeLog("load_all_plugins begin")
        let plugins = try Python.attemptImport("yt_dlp.plugins")
        _ = plugins.load_all_plugins()
        mpvYTDLPBridgeLog("load_all_plugins complete; Apple WebKit provider should now be registered")
        return pythonModule
''',
    'plugin loading',
)

replace_once(
    '''    func makePythonObject(_ options: PythonObject? = nil, initializePython: Bool = true) async throws -> PythonObject {
        let pythonModule = try await loadPythonModule()
        let options = options ?? defaultOptions
        pythonObject = pythonModule.YoutubeDL(options)
        self.options = options
        return pythonObject!
    }
''',
    '''    @MainActor
    func makePythonObject(_ suppliedOptions: PythonObject? = nil, initializePython: Bool = true) async throws -> PythonObject {
        mpvYTDLPBridgeLog("makePythonObject enter; main=\\(Thread.isMainThread)")
        let pythonModule = try await loadPythonModule()
        let effectiveOptions = suppliedOptions ?? defaultOptions

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
            let logPath = String(cString: rawLogPath)
            let builtins = Python.import("builtins")
            let mainModule = Python.import("__main__")
            let loggerSource = #"""
import datetime
class _MPVYTDLPLogger:
    def __init__(self, path):
        self.path = path
    def _write(self, level, msg):
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(self.path, 'a', encoding='utf-8') as stream:
            stream.write(f'[{stamp}] [yt-dlp][{level}] {msg}\\n')
    def debug(self, msg): self._write('debug', msg)
    def info(self, msg): self._write('info', msg)
    def warning(self, msg): self._write('warning', msg)
    def error(self, msg): self._write('error', msg)
"""#
            _ = builtins.exec(loggerSource, mainModule.__dict__)
            effectiveOptions["logger"] = mainModule._MPVYTDLPLogger(logPath)
            mpvYTDLPBridgeLog("yt-dlp file logger attached")
        }

        mpvYTDLPBridgeLog("YoutubeDL(options) construction begin")
        pythonObject = pythonModule.YoutubeDL(effectiveOptions)
        self.options = effectiveOptions
        mpvYTDLPBridgeLog("YoutubeDL(options) construction complete")
        return pythonObject!
    }
''',
    'makePythonObject',
)

replace_once(
    '''    open func extractInfo(url: URL) async throws -> ([Format], Info) {
        let pythonObject: PythonObject
''',
    '''    open func extractInfo(url: URL) async throws -> ([Format], Info) {
        mpvYTDLPBridgeLog("extractInfo enter; main=\\(Thread.isMainThread); url=\\(url.absoluteString)")
        let pythonObject: PythonObject
''',
    'extractInfo start',
)

replace_once(
    '''        print(#function, url)
        let info = try pythonObject.extract_info.throwing.dynamicallyCall(withKeywordArguments: ["": url.absoluteString, "download": false, "process": true])
        print(info)
''',
    '''        print(#function, url)
        mpvYTDLPBridgeLog("python extract_info begin; main=\\(Thread.isMainThread)")
        let info = try pythonObject.extract_info.throwing.dynamicallyCall(withKeywordArguments: ["": url.absoluteString, "download": false, "process": true])
        mpvYTDLPBridgeLog("python extract_info complete")
        print(info)
''',
    'extract_info call',
)

replace_once(
    '''        let format_selector = pythonObject.build_format_selector(options!["format"])
        let formats_to_download = format_selector(info)
''',
    '''        mpvYTDLPBridgeLog("format selector begin")
        let format_selector = pythonObject.build_format_selector(options!["format"])
        let formats_to_download = format_selector(info)
        mpvYTDLPBridgeLog("format selector complete")
''',
    'format selector',
)

replace_once(
    '''        return (formats, try decoder.decode(Info.self, from: info))
    }
''',
    '''        let decodedInfo = try decoder.decode(Info.self, from: info)
        mpvYTDLPBridgeLog("extractInfo decoded \\(formats.count) selected formats and \\(decodedInfo.formats.count) total formats")
        return (formats, decodedInfo)
    }
''',
    'extractInfo return',
)

path.write_text(text)
print(f'Patched {path}: main-actor Python init, worker extraction, plugin load, and verbose file diagnostics.')
