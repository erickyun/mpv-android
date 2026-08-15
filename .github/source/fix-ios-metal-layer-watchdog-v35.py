from pathlib import Path

ROOT = Path('MPVTorBox')
CTRL = ROOT / 'Player' / 'MPVMetalViewController.swift'
LAYER = ROOT / 'Player' / 'MetalLayer.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# The MPVKit layer overrides were workarounds, not requirements. In particular
# wantsExtendedDynamicRangeContent used DispatchQueue.main.sync when CoreAnimation
# or MoltenVK touched the property from a render thread. That can deadlock against
# a main-thread CA transaction and end as a watchdog kill rather than a normal
# crash report. Use an ordinary CAMetalLayer and let UIKit/CoreAnimation own it.
LAYER.write_text('''import UIKit\n\nfinal class MetalLayer: CAMetalLayer { }\n''')

# A tiny persistent breadcrumb logger independent from yt-dlp/Python. It is
# enabled by the already-supported mpv-ios-ytdl-log=yes raw option, and also
# accepts mpv-ios-player-log=yes. It reads mpv.conf directly so logging starts
# before libmpv parses the config or invokes the yt-dlp hook.
replace_once(
    CTRL,
    '''private final class MPVMetalHostView: UIView {
''',
    '''private enum MPVPlayerLifecycleLog {
    private static let queue = DispatchQueue(label: "io.github.erickyun.mpv.player-lifecycle-log")

    private static var enabled: Bool {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let config = documents
            .appendingPathComponent("MPVConfig", isDirectory: true)
            .appendingPathComponent("mpv.conf")
        guard let text = try? String(contentsOf: config, encoding: .utf8) else { return false }

        for rawLine in text.split(separator: "\\n", omittingEmptySubsequences: false) {
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            if line.isEmpty || line.hasPrefix("#") { continue }
            let lower = line.lowercased().replacingOccurrences(of: " ", with: "")
            guard lower.hasPrefix("ytdl-raw-options=") || lower.hasPrefix("ytdl-raw-options") else { continue }
            if lower.contains("mpv-ios-ytdl-log=yes") ||
               lower.contains("mpv-ios-ytdl-log=true") ||
               lower.contains("mpv-ios-ytdl-log=1") ||
               lower.contains("mpv-ios-player-log=yes") ||
               lower.contains("mpv-ios-player-log=true") ||
               lower.contains("mpv-ios-player-log=1") {
                return true
            }
        }
        return false
    }

    static func write(_ message: String) {
        guard enabled else { return }
        queue.sync {
            let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            let directory = documents.appendingPathComponent("Logs", isDirectory: true)
            let file = directory.appendingPathComponent("player-lifecycle.log")
            try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

            let stamp = ISO8601DateFormatter().string(from: Date())
            let thread = Thread.isMainThread ? "main" : "worker"
            let line = "[\\(stamp)] [\\(thread)] \\(message)\\n"
            guard let data = line.data(using: .utf8) else { return }

            if !FileManager.default.fileExists(atPath: file.path) {
                try? data.write(to: file, options: .atomic)
                return
            }
            guard let handle = try? FileHandle(forWritingTo: file) else { return }
            defer { try? handle.close() }
            do {
                try handle.seekToEnd()
                try handle.write(contentsOf: data)
                try handle.synchronize()
            } catch { }
        }
    }
}

private final class MPVMetalHostView: UIView {
''',
    'player lifecycle logger',
)

replace_once(
    CTRL,
    '''    override func loadView() {
        let host = MPVMetalHostView(frame: .zero)
''',
    '''    override func loadView() {
        MPVPlayerLifecycleLog.write("loadView enter")
        let host = MPVMetalHostView(frame: .zero)
''',
    'loadView breadcrumb begin',
)
replace_once(
    CTRL,
    '''        metalLayer = layer
    }

    override func viewDidLoad() {
        super.viewDidLoad()
''',
    '''        metalLayer = layer
        MPVPlayerLifecycleLog.write("loadView MetalLayer ready")
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        MPVPlayerLifecycleLog.write("viewDidLoad enter")
''',
    'loadView/viewDidLoad breadcrumb',
)
replace_once(
    CTRL,
    '''        setupMPV()
        if let playSource { loadSource(playSource) }
''',
    '''        MPVPlayerLifecycleLog.write("viewDidLoad before setupMPV")
        setupMPV()
        MPVPlayerLifecycleLog.write("viewDidLoad after setupMPV; context=\\(mpv != nil ? "ready" : "nil")")
        if let playSource { loadSource(playSource) }
''',
    'setupMPV outer breadcrumbs',
)

replace_once(
    CTRL,
    '''    private func setupMPV() {
        guard let context = mpv_create() else {
            assertionFailure("Unable to create mpv context")
            return
        }
        mpv = context

        let config = MPVConfigManager.prepare()
''',
    '''    private func setupMPV() {
        MPVPlayerLifecycleLog.write("setupMPV begin")
        guard let context = mpv_create() else {
            MPVPlayerLifecycleLog.write("setupMPV mpv_create FAILED")
            assertionFailure("Unable to create mpv context")
            return
        }
        mpv = context
        MPVPlayerLifecycleLog.write("setupMPV mpv_create OK")

        let config = MPVConfigManager.prepare()
        MPVPlayerLifecycleLog.write("setupMPV config prepared")
''',
    'setupMPV creation breadcrumbs',
)
replace_once(
    CTRL,
    '''        check(mpv_initialize(context))
        check(mpv_hook_add(context, 0x49595444, "on_load", -100))
''',
    '''        MPVPlayerLifecycleLog.write("setupMPV before mpv_initialize")
        let initializeStatus = mpv_initialize(context)
        MPVPlayerLifecycleLog.write("setupMPV mpv_initialize status=\\(initializeStatus)")
        check(initializeStatus)
        let hookStatus = mpv_hook_add(context, 0x49595444, "on_load", -100)
        MPVPlayerLifecycleLog.write("setupMPV hook_add status=\\(hookStatus)")
        check(hookStatus)
''',
    'mpv initialize/hook breadcrumbs',
)
replace_once(
    CTRL,
    '''        mpv_set_wakeup_callback(
            context,
''',
    '''        MPVPlayerLifecycleLog.write("setupMPV installing wakeup callback")
        mpv_set_wakeup_callback(
            context,
''',
    'wakeup callback breadcrumb',
)
replace_once(
    CTRL,
    '''        startUpdateTimer()

        NotificationCenter.default.addObserver(
''',
    '''        MPVPlayerLifecycleLog.write("setupMPV wakeup callback installed")
        startUpdateTimer()
        MPVPlayerLifecycleLog.write("setupMPV timer started")

        NotificationCenter.default.addObserver(
''',
    'timer breadcrumb',
)

replace_once(
    CTRL,
    '''    func loadSource(_ source: ResolvedSource) {
        playSource = source
''',
    '''    func loadSource(_ source: ResolvedSource) {
        MPVPlayerLifecycleLog.write("loadSource provider=\\(source.provider); host=\\(source.url.host ?? "local")")
        playSource = source
''',
    'loadSource breadcrumb',
)

replace_once(
    CTRL,
    '''                case MPV_EVENT_FILE_LOADED:
                    self.publishTracks()
''',
    '''                case MPV_EVENT_FILE_LOADED:
                    MPVPlayerLifecycleLog.write("MPV_EVENT_FILE_LOADED")
                    self.publishTracks()
''',
    'file loaded breadcrumb',
)
replace_once(
    CTRL,
    '''                case MPV_EVENT_HOOK:
                    guard event.pointee.reply_userdata == 0x49595444,
''',
    '''                case MPV_EVENT_HOOK:
                    MPVPlayerLifecycleLog.write("MPV_EVENT_HOOK received")
                    guard event.pointee.reply_userdata == 0x49595444,
''',
    'hook event breadcrumb',
)

replace_once(
    CTRL,
    '''    private func handleEmbeddedYTDLHook(hookID: UInt64) {
        let marker = "iosytdl://"
''',
    '''    private func handleEmbeddedYTDLHook(hookID: UInt64) {
        MPVPlayerLifecycleLog.write("handleEmbeddedYTDLHook enter")
        let marker = "iosytdl://"
''',
    'hook handler breadcrumb',
)
replace_once(
    CTRL,
    '''        print("[ios-ytdl-native] on_load request: \\(url.absoluteString); format=\\(selector)")
        Task { [weak self] in
''',
    '''        MPVPlayerLifecycleLog.write("yt-dlp hook URL host=\\(url.host ?? "unknown"); before resolver task")
        print("[ios-ytdl-native] on_load request: \\(url.absoluteString); format=\\(selector)")
        Task { [weak self] in
''',
    'before yt-dlp resolver breadcrumb',
)
replace_once(
    CTRL,
    '''            self.finishEmbeddedYTDLHook(hookID: hookID, originalURL: rawURL, response: response)
        }
''',
    '''            MPVPlayerLifecycleLog.write("yt-dlp resolver returned; ok=\\(response.ok); formats=\\(response.formats.count)")
            self.finishEmbeddedYTDLHook(hookID: hookID, originalURL: rawURL, response: response)
        }
''',
    'yt-dlp resolver returned breadcrumb',
)
replace_once(
    CTRL,
    '''    private func finishEmbeddedYTDLHook(
        hookID: UInt64,
        originalURL: String,
        response: YTDLPService.MPVHookResponse
    ) {
        guard let context = mpv else { return }
''',
    '''    private func finishEmbeddedYTDLHook(
        hookID: UInt64,
        originalURL: String,
        response: YTDLPService.MPVHookResponse
    ) {
        MPVPlayerLifecycleLog.write("finishEmbeddedYTDLHook enter; ok=\\(response.ok)")
        guard let context = mpv else {
            MPVPlayerLifecycleLog.write("finishEmbeddedYTDLHook aborted: mpv context nil")
            return
        }
''',
    'finish hook breadcrumb',
)
replace_once(
    CTRL,
    '''        check(mpv_hook_continue(context, hookID))
    }

    private func isUnsupportedYTDLError''',
    '''        MPVPlayerLifecycleLog.write("finishEmbeddedYTDLHook before final hook_continue")
        check(mpv_hook_continue(context, hookID))
        MPVPlayerLifecycleLog.write("finishEmbeddedYTDLHook hook_continue returned")
    }

    private func isUnsupportedYTDLError''',
    'final hook continuation breadcrumb',
)

replace_once(
    CTRL,
    '''    @discardableResult
    private func command(_ name: String, args: [String]) -> CInt {
        guard let mpv else { return -1 }
''',
    '''    @discardableResult
    private func command(_ name: String, args: [String]) -> CInt {
        guard let mpv else { return -1 }
        let diagnosticCommand = name == "loadfile" || name == "video-reconfig"
        if diagnosticCommand { MPVPlayerLifecycleLog.write("mpv command \\(name) begin") }
''',
    'command begin breadcrumb',
)
replace_once(
    CTRL,
    '''            let status = mpv_command(mpv, buffer.baseAddress)
            check(status)
            return status
''',
    '''            let status = mpv_command(mpv, buffer.baseAddress)
            if diagnosticCommand { MPVPlayerLifecycleLog.write("mpv command \\(name) end status=\\(status)") }
            check(status)
            return status
''',
    'command end breadcrumb',
)

replace_once(
    CTRL,
    '''    deinit {
        updateTimer?.setEventHandler {}
''',
    '''    deinit {
        MPVPlayerLifecycleLog.write("MPVMetalViewController deinit begin")
        updateTimer?.setEventHandler {}
''',
    'deinit begin breadcrumb',
)
replace_once(
    CTRL,
    '''            mpv = nil
            mpv_terminate_destroy(context)
        }
    }
''',
    '''            mpv = nil
            MPVPlayerLifecycleLog.write("deinit before mpv_terminate_destroy")
            mpv_terminate_destroy(context)
            MPVPlayerLifecycleLog.write("deinit after mpv_terminate_destroy")
        }
    }
''',
    'deinit destroy breadcrumbs',
)

print('Applied v35 plain CAMetalLayer plus watchdog-safe player lifecycle breadcrumbs')
