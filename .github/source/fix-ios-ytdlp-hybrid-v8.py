from pathlib import Path

ROOT = Path('MPVTorBox')
PROJECT = Path('project.yml')


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'Expected pattern not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1))


ytdlp = ROOT / 'YTDLPService.swift'

replace_once(
    ytdlp,
    '''        case webKitPluginRequiresRestart

        var errorDescription: String? {
''',
    '''        case webKitPluginRequiresRestart
        case extractionAlreadyRunning

        var errorDescription: String? {
'''
)
replace_once(
    ytdlp,
    '''            case .webKitPluginRequiresRestart:
                return "The Apple WebKit JavaScript provider was installed. Close and reopen MPV once, then try YouTube again."
            }
''',
    '''            case .webKitPluginRequiresRestart:
                return "The Apple WebKit JavaScript provider was installed. Close and reopen MPV once, then try YouTube again."
            case .extractionAlreadyRunning:
                return "A yt-dlp extraction is already running. Wait for it to finish or fully close and reopen MPV."
            }
'''
)
replace_once(
    ytdlp,
    '''            case .extractionTimedOut:
                return "yt-dlp did not finish within 25 seconds. Close and reopen MPV, update yt-dlp, and try again."
''',
    '''            case .extractionTimedOut:
                return "yt-dlp did not finish within 60 seconds. Fully close and reopen MPV before trying again."
'''
)
replace_once(
    ytdlp,
    '''    private var youtubeDL: YoutubeDL?
    private let defaults = UserDefaults.standard
''',
    '''    private var youtubeDL: YoutubeDL?
    private var extractionInProgress = false
    private let defaults = UserDefaults.standard
'''
)
replace_once(
    ytdlp,
    '''    ) async throws -> ResolvedSource {
        try prepareRuntimeDirectories()
''',
    '''    ) async throws -> ResolvedSource {
        guard !extractionInProgress else { throw YTDLPError.extractionAlreadyRunning }
        extractionInProgress = true
        defer { extractionInProgress = false }

        try prepareRuntimeDirectories()
'''
)
replace_once(
    ytdlp,
    '''        await status("Starting local Python and yt-dlp on the iOS main run loop…")
        let bridge = getBridge()
        appendNativeLog("Starting extraction: \\(url.absoluteString)")
        await status("Solving the website URL with yt-dlp and Apple WebKit…")

        let result: ([Format], Info)
        do {
            result = try await bridge.extractInfo(url: url)
            appendNativeLog("Extraction completed successfully")
        } catch {
            appendNativeLog("Extraction failed: \\(String(reflecting: error))")
            throw error
        }
''',
    '''        await status("Initializing Python on the iOS main actor…")
        let bridge = getBridge()
        appendNativeLog("Starting hybrid extraction: \\(url.absoluteString)")
        await status("Running yt-dlp on a worker thread; WebKit callbacks stay on the main run loop…")

        let result: ([Format], Info)
        do {
            result = try await runWithTimeout(seconds: 60) {
                try await bridge.extractInfo(url: url)
            }
            appendNativeLog("Hybrid extraction completed successfully")
        } catch {
            appendNativeLog("Hybrid extraction failed: \\(String(reflecting: error))")
            throw error
        }
'''
)

advanced = ROOT / 'AdvancedSettingsView.swift'
text = advanced.read_text()
text = text.replace(
    'The Python runtime and Apple WebKit JavaScript provider are bundled. Python initialization and WebKit challenge solving run on the iOS main run loop. Detailed extraction output is saved in Files → On My iPhone → MPV → Logs → yt-dlp.log.',
    'The Python runtime and Apple WebKit JavaScript provider are bundled. Python initializes on the main actor, while yt-dlp extraction runs on a worker thread so WebKit callbacks can use the main run loop. Detailed checkpoints are saved in Files → On My iPhone → MPV → Logs → yt-dlp.log.',
    1,
)
advanced.write_text(text)

project_text = PROJECT.read_text()
project_text = project_text.replace('        MARKETING_VERSION: 1.7.0\n', '        MARKETING_VERSION: 1.8.0\n', 1)
project_text = project_text.replace('        CURRENT_PROJECT_VERSION: 17\n', '        CURRENT_PROJECT_VERSION: 18\n', 1)
PROJECT.write_text(project_text)

print('Applied hybrid Python initialization, worker extraction, single-flight guard, and 60-second watchdog.')
