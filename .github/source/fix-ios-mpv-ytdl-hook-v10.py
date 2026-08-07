from pathlib import Path

ROOT = Path('MPVTorBox')
PROJECT = Path('project.yml')


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: expected pattern not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1))

# 1) Route supported website URLs into mpv itself. A ytdl:// marker is added only
# when the URL is handed to libmpv, so SourceResolver keeps a normal Foundation URL.
resolver = ROOT / 'SourceResolver.swift'
replace_once(
    resolver,
    '    private let torBox = TorBoxService()\n    private let ytdlp = YTDLPService.shared\n',
    '    private let torBox = TorBoxService()\n',
    'remove pre-resolver yt-dlp instance',
)
replace_once(
    resolver,
    '''        if settings.ytdlpEnabled, shouldUseYTDLP(url) {
            await status("Resolving supported website URL with yt-dlp…")
            do {
                return try await ytdlp.resolve(url: url, status: status)
            } catch {
                throw ResolverError.ytdlpFailed(error.localizedDescription)
            }
        }
''',
    '''        if settings.ytdlpEnabled, shouldUseYTDLP(url) {
            await status("Opening website through MPV's embedded yt-dlp hook…")
            return ResolvedSource(
                url: url,
                provider: "MPV yt-dlp hook",
                usesEmbeddedYTDLHook: true
            )
        }
''',
    'route website to mpv hook',
)
replace_once(
    resolver,
    '''    var httpHeaders: [String: String] = [:]
    var securityAccess: SecurityScopedAccess? = nil
''',
    '''    var httpHeaders: [String: String] = [:]
    var securityAccess: SecurityScopedAccess? = nil
    var usesEmbeddedYTDLHook: Bool = false
''',
    'add hook marker',
)

# 2) Make mpv.conf's ytdl-format effective for both fresh and existing installs.
config = ROOT / 'Utilities' / 'MPVConfigManager.swift'
replace_once(
    config,
    '    private static let statsBindingsMarker = "# MPV iOS managed stats.lua bindings v1"\n',
    '''    private static let statsBindingsMarker = "# MPV iOS managed stats.lua bindings v1"
    private static let ytdlFormatMarker = "# MPV iOS managed embedded yt-dlp format v1"
    private static let defaultYTDLFormat = "bv*[height<=1080]+ba/b[height<=1080]"
''',
    'config constants',
)
replace_once(
    config,
    '''            hwdec=videotoolbox
            subs-match-os-language=yes
''',
    '''            hwdec=videotoolbox
            ytdl-format=bv*[height<=1080]+ba/b[height<=1080]
            subs-match-os-language=yes
''',
    'default ytdl format',
)
replace_once(
    config,
    '''        )

        writeIfMissing(
            to: inputConfig,
''',
    '''        )
        ensureYTDLFormat(in: mpvConfig)

        writeIfMissing(
            to: inputConfig,
''',
    'ensure existing config format',
)
replace_once(
    config,
    '''    private static func ensureStatsBindings(in url: URL) {
''',
    '''    private static func ensureYTDLFormat(in url: URL) {
        let existing = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
        let hasActiveFormat = existing.split(separator: "\\n", omittingEmptySubsequences: false).contains { rawLine in
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.hasPrefix("#") else { return false }
            return line.hasPrefix("ytdl-format=") || line.hasPrefix("ytdl-format ")
        }
        guard !hasActiveFormat else { return }

        let block = """

        \\(ytdlFormatMarker)
        ytdl-format=\\(defaultYTDLFormat)
        """
        append(block, to: url)
    }

    private static func ensureStatsBindings(in url: URL) {
''',
    'ensure format helper',
)
replace_once(
    config,
    '''        guard let data = block.data(using: .utf8),
              let handle = try? FileHandle(forWritingTo: url) else { return }
        defer { try? handle.close() }
        do {
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
        } catch { }
    }

    private static func writeIfMissing(to url: URL, content: String) {
''',
    '''        append(block, to: url)
    }

    private static func append(_ content: String, to url: URL) {
        guard let data = content.data(using: .utf8),
              let handle = try? FileHandle(forWritingTo: url) else { return }
        defer { try? handle.close() }
        do {
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
        } catch { }
    }

    private static func writeIfMissing(to url: URL, content: String) {
''',
    'shared append helper',
)
replace_once(
    config,
    '''            MPV reads mpv.conf and input.conf from this folder every time the player starts.
            Existing files are not replaced. The app only appends a marked stats.lua binding block when it is missing.
            Close and reopen the player after editing these files.
''',
    '''            MPV reads mpv.conf and input.conf from this folder every time the player starts.
            Existing files are not replaced. If ytdl-format is absent, the app appends a managed 1080p + best-audio default.
            You can replace ytdl-format with any normal yt-dlp format selector. Close and reopen the player after editing these files.
''',
    'config readme',
)

# 3) Add the in-process result type and resolver. The actual selector is consumed by
# the embedded YoutubeDL-iOS bridge, not reimplemented in Swift.
ytdlp = ROOT / 'YTDLPService.swift'
replace_once(
    ytdlp,
    '''    struct ModuleStatus: Sendable {
''',
    '''    struct MPVHookFormat: Codable, Sendable {
        let url: String
        let formatID: String
        let vcodec: String?
        let acodec: String?
        let width: Int?
        let height: Int?
        let fps: Double?
        let tbr: Double?
        let abr: Double?
    }

    struct MPVHookResponse: Codable, Sendable {
        let ok: Bool
        let title: String?
        let formats: [MPVHookFormat]
        let httpHeaders: [String: String]
        let selector: String?
        let error: String?

        static func failure(_ message: String) -> MPVHookResponse {
            MPVHookResponse(ok: false, title: nil, formats: [], httpHeaders: [:], selector: nil, error: message)
        }
    }

    struct ModuleStatus: Sendable {
''',
    'hook response types',
)
replace_once(
    ytdlp,
    '''    func resolve(
        url: URL,
        status: @escaping @MainActor (String) -> Void
    ) async throws -> ResolvedSource {
''',
    '''    func resolveForMPVHook(url: URL, formatSelector: String) async throws -> MPVHookResponse {
        guard !extractionInProgress else { throw YTDLPError.extractionAlreadyRunning }
        extractionInProgress = true
        defer { extractionInProgress = false }

        try prepareRuntimeDirectories()
        let pluginInstalledNow = try installBundledWebKitPlugin()
        if pluginInstalledNow, youtubeDL != nil {
            youtubeDL = nil
            throw YTDLPError.webKitPluginRequiresRestart
        }

        let selector = formatSelector.trimmingCharacters(in: .whitespacesAndNewlines)
        let effectiveSelector = (selector.isEmpty || selector == "ytdl")
            ? "bv*[height<=1080]+ba/b[height<=1080]"
            : selector

        setenv("MPV_YTDL_FORMAT", effectiveSelector, 1)
        defer { unsetenv("MPV_YTDL_FORMAT") }

        // Recreate YoutubeDL so edits to mpv.conf take effect after reopening the player
        // and each hook request is guaranteed to use the selector supplied by mpv.
        youtubeDL = nil
        let bridge = getBridge()
        appendNativeLog("MPV hook extraction: \\(url.absoluteString); format=\\(effectiveSelector)")

        let result: ([Format], Info)
        do {
            result = try await runWithTimeout(seconds: 60) {
                try await bridge.extractInfo(url: url)
            }
        } catch {
            appendNativeLog("MPV hook extraction failed: \\(String(reflecting: error))")
            throw error
        }

        if let version = bridge.version, !version.isEmpty {
            defaults.set(version, forKey: Keys.installedVersion)
        }
        defaults.set(Self.webKitPluginVersion, forKey: Keys.webKitPluginVersion)

        let playableProtocols = ["http", "https", "m3u8", "m3u8_native"]
        let selected = result.0.filter { playableProtocols.contains($0.protocol) && !$0.url.isEmpty }
        guard !selected.isEmpty else { throw YTDLPError.noPlayableFormat }

        let hookFormats = selected.map { format in
            MPVHookFormat(
                url: format.url,
                formatID: format.format_id,
                vcodec: format.vcodec,
                acodec: format.acodec,
                width: format.width,
                height: format.height,
                fps: format.fps,
                tbr: format.tbr,
                abr: format.abr
            )
        }
        let headers = selected.first?.http_headers ?? [:]
        appendNativeLog("MPV hook selected \\(hookFormats.count) stream(s): \\(hookFormats.map(\\.formatID).joined(separator: "+"))")

        return MPVHookResponse(
            ok: true,
            title: result.1.title,
            formats: hookFormats,
            httpHeaders: headers,
            selector: effectiveSelector,
            error: nil
        )
    }

    func resolve(
        url: URL,
        status: @escaping @MainActor (String) -> Void
    ) async throws -> ResolvedSource {
''',
    'hook resolver',
)

# 4) Bundle a small mpv on_load hook. It mirrors mpv's ytdl_hook architecture but
# replaces the forbidden external subprocess with a script-message to the Swift host.
resources = ROOT / 'Resources'
resources.mkdir(parents=True, exist_ok=True)
hook = resources / 'ios_ytdl_hook.lua'
hook.write_text(r'''local mp = require 'mp'
local msg = require 'mp.msg'
local utils = require 'mp.utils'

local pending = {}
local next_id = 0

local function edl_escape(value)
    return "%" .. #value .. "%" .. value
end

local function set_http_headers(headers)
    if type(headers) ~= "table" then return end
    local fields = {}
    for name, value in pairs(headers) do
        local lower = string.lower(name)
        if lower == "user-agent" then
            mp.set_property("file-local-options/user-agent", value)
        elseif lower == "referer" or lower == "referrer" then
            mp.set_property("file-local-options/referrer", value)
        elseif lower ~= "cookie" then
            fields[#fields + 1] = name .. ": " .. value
        end
    end
    if #fields > 0 then
        mp.set_property_native("file-local-options/http-header-fields", fields)
    end
end

local function formats_to_stream(formats)
    if type(formats) ~= "table" or #formats == 0 then return nil end
    if #formats == 1 then return formats[1].url end

    local streams = {}
    for _, format in ipairs(formats) do
        if type(format.url) == "string" and format.url ~= "" then
            local has_video = format.vcodec and format.vcodec ~= "none"
            local has_audio = format.acodec and format.acodec ~= "none"
            local header = {"!new_stream", "!no_clip", "!no_chapters"}
            if has_video and not has_audio then
                header[#header + 1] = "!delay_open,media_type=video"
            elseif has_audio and not has_video then
                header[#header + 1] = "!delay_open,media_type=audio"
            end
            streams[#streams + 1] = table.concat(header, ";") .. ";" .. edl_escape(format.url)
        end
    end
    if #streams == 0 then return nil end
    if #streams == 1 then return formats[1].url end
    return "edl://" .. table.concat(streams, ";")
end

local function finish(id, payload)
    local request = pending[id]
    if not request then return end
    pending[id] = nil
    if request.timer then request.timer:kill() end

    local result, parse_error = utils.parse_json(payload)
    if not result or not result.ok then
        local reason = result and result.error or parse_error or "unknown embedded yt-dlp error"
        msg.error("embedded yt-dlp failed: " .. tostring(reason))
        mp.osd_message("yt-dlp failed: " .. tostring(reason), 6)
        mp.set_property("stream-open-filename", "memory://")
        request.hook:cont()
        return
    end

    local stream = formats_to_stream(result.formats)
    if not stream then
        msg.error("embedded yt-dlp returned no playable stream")
        mp.osd_message("yt-dlp returned no playable stream", 6)
        mp.set_property("stream-open-filename", "memory://")
        request.hook:cont()
        return
    end

    set_http_headers(result.httpHeaders)
    if result.title and result.title ~= "" then
        mp.set_property("file-local-options/force-media-title", result.title)
    end
    mp.set_property("user-data/mpv/ios-ytdl-format", result.selector or "")
    mp.set_property("stream-open-filename", stream)
    msg.info("embedded yt-dlp selected " .. tostring(#result.formats) .. " stream(s) with format: " .. tostring(result.selector))
    request.hook:cont()
end

mp.register_script_message("ios-ytdl-response", finish)

mp.add_hook("on_load", 5, function(hook)
    local marked = mp.get_property("stream-open-filename", "")
    if not string.find(marked, "^ytdl://") then return end

    local url = string.sub(marked, 8)
    local format = mp.get_property("options/ytdl-format", "")
    if mp.get_property("options/vid", "auto") == "no" and format == "" then
        format = "bestaudio/best"
    end

    next_id = next_id + 1
    local id = tostring(next_id)
    hook:defer()
    local timer = mp.add_timeout(65, function()
        local request = pending[id]
        if not request then return end
        pending[id] = nil
        msg.error("embedded yt-dlp request timed out")
        mp.osd_message("yt-dlp request timed out", 6)
        mp.set_property("stream-open-filename", "memory://")
        request.hook:cont()
    end)
    pending[id] = {hook = hook, timer = timer}
    mp.commandv("script-message", "ios-ytdl-request", id, url, format)
end)
''')

# 5) Connect Lua script-message events to the Swift embedded extractor and feed the
# result back to the deferred hook.
controller = ROOT / 'Player' / 'MPVMetalViewController.swift'
replace_once(
    controller,
    '''        if let statsScript = Bundle.main.url(forResource: "stats", withExtension: "lua") {
            check(mpv_set_option_string(context, "scripts", statsScript.path))
        } else {
            print("Official stats.lua is missing from the app bundle.")
        }
''',
    '''        var bundledScripts: [String] = []
        if let statsScript = Bundle.main.url(forResource: "stats", withExtension: "lua") {
            bundledScripts.append(statsScript.path)
        } else {
            print("Official stats.lua is missing from the app bundle.")
        }
        if let ytdlHook = Bundle.main.url(forResource: "ios_ytdl_hook", withExtension: "lua") {
            bundledScripts.append(ytdlHook.path)
        } else {
            print("Embedded iOS yt-dlp hook is missing from the app bundle.")
        }
        if !bundledScripts.isEmpty {
            check(mpv_set_option_string(context, "scripts", bundledScripts.joined(separator: ":")))
        }
''',
    'load bundled scripts',
)
replace_once(
    controller,
    '''        command("loadfile", args: [source.url.absoluteString, "replace"])
''',
    '''        let target = source.usesEmbeddedYTDLHook
            ? "ytdl://" + source.url.absoluteString
            : source.url.absoluteString
        command("loadfile", args: [target, "replace"])
''',
    'mark yt-dlp URL for mpv hook',
)
replace_once(
    controller,
    '''                case MPV_EVENT_LOG_MESSAGE:
''',
    '''                case MPV_EVENT_CLIENT_MESSAGE:
                    guard let data = event.pointee.data else { continue }
                    let message = data.assumingMemoryBound(to: mpv_event_client_message.self).pointee
                    guard let rawArgs = message.args, message.num_args > 0 else { continue }
                    var args: [String] = []
                    for index in 0..<Int(message.num_args) {
                        if let raw = rawArgs[index] { args.append(String(cString: raw)) }
                    }
                    self.handleClientMessage(args)

                case MPV_EVENT_LOG_MESSAGE:
''',
    'client-message event',
)
replace_once(
    controller,
    '''    private func publishPlayback() {
''',
    '''    private func handleClientMessage(_ args: [String]) {
        guard args.count >= 4, args[0] == "ios-ytdl-request" else { return }
        let requestID = args[1]
        guard let url = URL(string: args[2]) else {
            sendYTDLHookResponse(requestID: requestID, response: .failure("Invalid website URL"))
            return
        }
        let selector = args[3]

        Task { [weak self] in
            let response: YTDLPService.MPVHookResponse
            do {
                response = try await YTDLPService.shared.resolveForMPVHook(
                    url: url,
                    formatSelector: selector
                )
            } catch {
                response = .failure(error.localizedDescription)
            }
            self?.sendYTDLHookResponse(requestID: requestID, response: response)
        }
    }

    private func sendYTDLHookResponse(
        requestID: String,
        response: YTDLPService.MPVHookResponse
    ) {
        guard let data = try? JSONEncoder().encode(response),
              let payload = String(data: data, encoding: .utf8) else { return }
        command("script-message-to", args: ["ios_ytdl_hook", "ios-ytdl-response", requestID, payload])
    }

    private func publishPlayback() {
''',
    'client message handler',
)

# 6) Explain the new source of truth in settings and bump the app version.
advanced = ROOT / 'AdvancedSettingsView.swift'
text = advanced.read_text()
text = text.replace(
    'The Python runtime and Apple WebKit JavaScript provider are bundled. Python initializes on the main actor, while yt-dlp extraction runs on a worker thread so WebKit callbacks can use the main run loop. Detailed checkpoints are saved in Files → On My iPhone → MPV → Logs → yt-dlp.log.',
    'Website URLs now enter MPV through an iOS-native ytdl hook. The hook reads ytdl-format directly from MPVConfig/mpv.conf, then uses the embedded Python + yt-dlp + Apple WebKit JSI runtime without launching an external executable. Detailed checkpoints are saved in Files → On My iPhone → MPV → Logs → yt-dlp.log.',
    1,
)
text = text.replace(
    'The default profile is high-quality. mpv.conf and input.conf are loaded whenever the player starts.',
    'The default profile is high-quality. mpv.conf and input.conf are loaded whenever the player starts. ytdl-format controls embedded yt-dlp exactly like normal MPV format selection.',
    1,
)
advanced.write_text(text)

project = PROJECT.read_text()
if 'MARKETING_VERSION: 1.9.0' not in project or 'CURRENT_PROJECT_VERSION: 19' not in project:
    raise SystemExit('Expected MPV iOS 1.9.0 build 19 markers were not found')
project = project.replace('MARKETING_VERSION: 1.9.0', 'MARKETING_VERSION: 2.0.0', 1)
project = project.replace('CURRENT_PROJECT_VERSION: 19', 'CURRENT_PROJECT_VERSION: 20', 1)
PROJECT.write_text(project)

print('Applied MPV on_load embedded yt-dlp bridge with mpv.conf ytdl-format control.')
