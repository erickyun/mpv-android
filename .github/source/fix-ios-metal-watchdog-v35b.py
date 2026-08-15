from pathlib import Path

ROOT = Path('MPVTorBox')
CTRL = ROOT / 'Player' / 'MPVMetalViewController.swift'
LAYER = ROOT / 'Player' / 'MetalLayer.swift'


def replace_optional(path: Path, old: str, new: str) -> bool:
    text = path.read_text()
    if old not in text:
        return False
    path.write_text(text.replace(old, new, 1))
    return True


# Remove both MPVKit CAMetalLayer overrides. The EDR override performed a
# DispatchQueue.main.sync from renderer threads; the drawableSize override also
# mutated CoreAnimation state outside UIKit's view lifecycle. A plain backing
# CAMetalLayer avoids those cross-thread layer mutations entirely.
LAYER.write_text('''import UIKit\n\nfinal class MetalLayer: CAMetalLayer { }\n''')

logger = '''private enum MPVPlayerLifecycleLog {
    private static let queue = DispatchQueue(label: "io.github.erickyun.mpv.player-lifecycle-log")

    private static var enabled: Bool {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let config = documents.appendingPathComponent("MPVConfig", isDirectory: true).appendingPathComponent("mpv.conf")
        guard let text = try? String(contentsOf: config, encoding: .utf8) else { return false }
        for rawLine in text.split(separator: "\\n", omittingEmptySubsequences: false) {
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            if line.isEmpty || line.hasPrefix("#") { continue }
            let lower = line.lowercased().replacingOccurrences(of: " ", with: "")
            if lower.contains("mpv-ios-ytdl-log=yes") || lower.contains("mpv-ios-ytdl-log=true") || lower.contains("mpv-ios-ytdl-log=1") || lower.contains("mpv-ios-player-log=yes") || lower.contains("mpv-ios-player-log=true") || lower.contains("mpv-ios-player-log=1") {
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
            let line = "[\\(ISO8601DateFormatter().string(from: Date()))] [\\(Thread.isMainThread ? "main" : "worker")] \\(message)\\n"
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

'''
text = CTRL.read_text()
anchor = 'private final class MPVMetalHostView: UIView {'
if anchor not in text:
    raise SystemExit('MPVMetalHostView anchor missing after v34')
CTRL.write_text(text.replace(anchor, logger + anchor, 1))

# Early UIKit/libmpv breadcrumbs. All replacements are intentionally optional so
# diagnostics cannot break release builds if an earlier helper changes wording.
replace_optional(
    CTRL,
    '    override func loadView() {\n        let host = MPVMetalHostView(frame: .zero)\n',
    '    override func loadView() {\n        MPVPlayerLifecycleLog.write("loadView enter")\n        let host = MPVMetalHostView(frame: .zero)\n'
)
replace_optional(
    CTRL,
    '        metalLayer = layer\n    }\n\n    override func viewDidLoad() {\n        super.viewDidLoad()\n',
    '        metalLayer = layer\n        MPVPlayerLifecycleLog.write("loadView MetalLayer ready")\n    }\n\n    override func viewDidLoad() {\n        super.viewDidLoad()\n        MPVPlayerLifecycleLog.write("viewDidLoad enter")\n'
)
replace_optional(
    CTRL,
    '        setupMPV()\n        if let playSource { loadSource(playSource) }\n',
    '        MPVPlayerLifecycleLog.write("before setupMPV")\n        setupMPV()\n        MPVPlayerLifecycleLog.write("after setupMPV; context=\\(mpv != nil ? "ready" : "nil")")\n        if let playSource { loadSource(playSource) }\n'
)
replace_optional(
    CTRL,
    '    private func setupMPV() {\n        guard let context = mpv_create() else {\n',
    '    private func setupMPV() {\n        MPVPlayerLifecycleLog.write("setupMPV begin")\n        guard let context = mpv_create() else {\n            MPVPlayerLifecycleLog.write("mpv_create FAILED")\n'
)
replace_optional(
    CTRL,
    '        mpv = context\n\n        let config = MPVConfigManager.prepare()\n',
    '        mpv = context\n        MPVPlayerLifecycleLog.write("mpv_create OK")\n\n        let config = MPVConfigManager.prepare()\n        MPVPlayerLifecycleLog.write("config prepared")\n'
)
replace_optional(
    CTRL,
    '        check(mpv_initialize(context))\n        check(mpv_hook_add(context, 0x49595444, "on_load", -100))\n',
    '        MPVPlayerLifecycleLog.write("before mpv_initialize")\n        let initializeStatus = mpv_initialize(context)\n        MPVPlayerLifecycleLog.write("mpv_initialize status=\\(initializeStatus)")\n        check(initializeStatus)\n        let hookStatus = mpv_hook_add(context, 0x49595444, "on_load", -100)\n        MPVPlayerLifecycleLog.write("hook_add status=\\(hookStatus)")\n        check(hookStatus)\n'
)
replace_optional(
    CTRL,
    '    func loadSource(_ source: ResolvedSource) {\n        playSource = source\n',
    '    func loadSource(_ source: ResolvedSource) {\n        MPVPlayerLifecycleLog.write("loadSource provider=\\(source.provider); host=\\(source.url.host ?? "local")")\n        playSource = source\n'
)
replace_optional(
    CTRL,
    '                case MPV_EVENT_FILE_LOADED:\n                    self.publishTracks()\n',
    '                case MPV_EVENT_FILE_LOADED:\n                    MPVPlayerLifecycleLog.write("MPV_EVENT_FILE_LOADED")\n                    self.publishTracks()\n'
)
replace_optional(
    CTRL,
    '                case MPV_EVENT_HOOK:\n                    guard event.pointee.reply_userdata == 0x49595444,\n',
    '                case MPV_EVENT_HOOK:\n                    MPVPlayerLifecycleLog.write("MPV_EVENT_HOOK received")\n                    guard event.pointee.reply_userdata == 0x49595444,\n'
)
replace_optional(
    CTRL,
    '    private func handleEmbeddedYTDLHook(hookID: UInt64) {\n        let marker = "iosytdl://"\n',
    '    private func handleEmbeddedYTDLHook(hookID: UInt64) {\n        MPVPlayerLifecycleLog.write("handleEmbeddedYTDLHook enter")\n        let marker = "iosytdl://"\n'
)

# Locate the resolver call rather than depending on its surrounding print text.
text = CTRL.read_text()
needle = '''                response = try await YTDLPService.shared.resolveForMPVHook(\n'''
if needle in text:
    text = text.replace(
        needle,
        '''                MPVPlayerLifecycleLog.write("before YTDLPService.resolveForMPVHook")\n''' + needle,
        1,
    )
CTRL.write_text(text)

replace_optional(
    CTRL,
    '            self.finishEmbeddedYTDLHook(hookID: hookID, originalURL: rawURL, response: response)\n',
    '            MPVPlayerLifecycleLog.write("yt-dlp resolver returned; ok=\\(response.ok); formats=\\(response.formats.count)")\n            self.finishEmbeddedYTDLHook(hookID: hookID, originalURL: rawURL, response: response)\n'
)
replace_optional(
    CTRL,
    '    ) {\n        guard let context = mpv else { return }\n\n        guard response.ok else {\n',
    '    ) {\n        MPVPlayerLifecycleLog.write("finishEmbeddedYTDLHook enter; ok=\\(response.ok)")\n        guard let context = mpv else { return }\n\n        guard response.ok else {\n'
)
replace_optional(
    CTRL,
    '    deinit {\n        updateTimer?.setEventHandler {}\n',
    '    deinit {\n        MPVPlayerLifecycleLog.write("controller deinit begin")\n        updateTimer?.setEventHandler {}\n'
)
replace_optional(
    CTRL,
    '            mpv = nil\n            mpv_terminate_destroy(context)\n',
    '            mpv = nil\n            MPVPlayerLifecycleLog.write("before mpv_terminate_destroy")\n            mpv_terminate_destroy(context)\n            MPVPlayerLifecycleLog.write("after mpv_terminate_destroy")\n'
)

print('Applied resilient v35b: plain CAMetalLayer and opt-in player lifecycle logging')
