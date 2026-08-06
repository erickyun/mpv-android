from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-mainthread.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()

old_options = '''public let defaultOptions: PythonObject = [
    "format": "bestvideo,bestaudio[ext=m4a]/best",
    "nocheckcertificate": true,
    "verbose": true,
]
'''
new_options = '''public let defaultOptions: PythonObject = [
    "format": "bestvideo,bestaudio[ext=m4a]/best",
    "nocheckcertificate": true,
    "verbose": true,
    "socket_timeout": 12,
    "retries": 1,
    "extractor_retries": 1,
    "fragment_retries": 1,
    "noplaylist": true,
]
'''
if old_options not in text:
    raise SystemExit('YoutubeDL defaultOptions anchor was not found')
text = text.replace(old_options, new_options, 1)

old_extract = '''    open func extractInfo(url: URL) async throws -> ([Format], Info) {
        let pythonObject: PythonObject
        if let _pythonObject = self.pythonObject {
            pythonObject = _pythonObject
        } else {
            pythonObject = try await makePythonObject()
        }

        print(#function, url)
        let info = try pythonObject.extract_info.throwing.dynamicallyCall(withKeywordArguments: ["": url.absoluteString, "download": false, "process": true])
        print(info)
//        print(#function, "throttled:", pythonObject.throttled)
        
        let format_selector = pythonObject.build_format_selector(options!["format"])
        let formats_to_download = format_selector(info)
        var formats: [Format] = []
        let decoder = PythonDecoder()
        for format in formats_to_download {
            let format = try decoder.decode(Format.self, from: format)
            formats.append(format)
        }
        
        return (formats, try decoder.decode(Info.self, from: info))
    }
'''

new_extract = '''    private func makePythonObjectOnMainThread(_ suppliedOptions: PythonObject? = nil) throws -> PythonObject {
        precondition(Thread.isMainThread, "Embedded yt-dlp and WebKit must initialize on the iOS main thread")

        if let existing = self.pythonObject {
            return existing
        }

        if Py_IsInitialized() == 0 {
            PythonSupport.initialize()
        }

        guard FileManager.default.fileExists(atPath: Self.pythonModuleURL.path) else {
            throw YoutubeDLError.noPythonModule
        }

        let sys = try Python.attemptImport("sys")
        if !(Array(sys.path) ?? []).contains(Self.pythonModuleURL.path) {
            injectFakePopen(handler: popenHandler)
            sys.path.insert(1, Self.pythonModuleURL.path)
        }

        if let rawLogPath = getenv("YTDLP_LOG_PATH") {
            let logPath = String(cString: rawLogPath)
            let escaped = logPath
                .replacingOccurrences(of: "\\\\", with: "\\\\\\\\")
                .replacingOccurrences(of: "\"", with: "\\\\\"")
            runSimpleString("""
                import os, sys, threading
                try:
                    _mpv_ytdlp_log = open("\\(escaped)", "a", buffering=1)
                    sys.stdout = _mpv_ytdlp_log
                    sys.stderr = _mpv_ytdlp_log
                    print("\\n[Python] yt-dlp runtime initialization")
                    print("[Python] main thread:", threading.current_thread() is threading.main_thread())
                    print("[Python] XDG_CONFIG_HOME:", os.environ.get("XDG_CONFIG_HOME"))
                    print("[Python] XDG_CACHE_HOME:", os.environ.get("XDG_CACHE_HOME"))
                    try:
                        import ssl
                        print("[Python] OpenSSL:", ssl.OPENSSL_VERSION)
                        _ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                        print("[Python] SSLContext creation: OK")
                    except BaseException as _ssl_error:
                        print("[Python] SSLContext creation failed:", repr(_ssl_error))
                except BaseException:
                    pass
                """)
        }

        let pythonModule = try Python.attemptImport("yt_dlp")
        version = String(pythonModule.version.__version__)
        runSimpleString("""
            try:
                from yt_dlp.plugins import load_all_plugins
                load_all_plugins()
                print("[Python] yt-dlp plugin loading completed")
            except BaseException as _plugin_error:
                print("[Python] yt-dlp plugin loading failed:", repr(_plugin_error))
            """)

        let effectiveOptions = suppliedOptions ?? defaultOptions
        let object = pythonModule.YoutubeDL(effectiveOptions)
        self.pythonObject = object
        self.options = effectiveOptions
        return object
    }

    open func extractInfo(url: URL) async throws -> ([Format], Info) {
        if !FileManager.default.fileExists(atPath: Self.pythonModuleURL.path) {
            try await Self.downloadPythonModule()
        }

        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.main.async {
                do {
                    let pythonObject = try self.makePythonObjectOnMainThread()
                    print(#function, url, "main thread:", Thread.isMainThread)
                    let info = try pythonObject.extract_info.throwing.dynamicallyCall(
                        withKeywordArguments: ["": url.absoluteString, "download": false, "process": true]
                    )
                    print(info)

                    let formatSelector = pythonObject.build_format_selector(self.options!["format"])
                    let formatsToDownload = formatSelector(info)
                    var formats: [Format] = []
                    let decoder = PythonDecoder()
                    for pythonFormat in formatsToDownload {
                        formats.append(try decoder.decode(Format.self, from: pythonFormat))
                    }

                    continuation.resume(returning: (
                        formats,
                        try decoder.decode(Info.self, from: info)
                    ))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }
'''

if old_extract not in text:
    raise SystemExit('YoutubeDL extractInfo implementation was not found')
text = text.replace(old_extract, new_extract, 1)
path.write_text(text)
print(f'Patched {path} for main-thread Python/WebKit extraction and diagnostics.')
