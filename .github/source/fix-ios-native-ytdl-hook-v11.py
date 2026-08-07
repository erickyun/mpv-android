from pathlib import Path

ROOT = Path('MPVTorBox')
METAL = ROOT / 'Player' / 'MPVMetalViewController.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label} anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# The previous bridge deliberately reused mpv's reserved ytdl:// protocol and
# bounced an on_load hook through Lua script-message events. That has two weak
# points on libmpv/iOS: the bundled ytdl_hook.lua owns ytdl:// too, and the app
# client has to receive/route a broadcast client-message while playback itself
# is suspended in the hook. Register the hook directly on the libmpv client
# instead. This is the native API that mpv exposes for synchronous on_load work.

# 1) Do not load the temporary Lua bridge. Keep stats.lua loaded as before.
replace_once(
    METAL,
    '''        if let ytdlHook = Bundle.main.url(forResource: "ios_ytdl_hook", withExtension: "lua") {
            bundledScripts.append(ytdlHook.path)
        } else {
            print("Embedded iOS yt-dlp hook is missing from the app bundle.")
        }
''',
    '''        // Embedded website extraction is handled by a native libmpv on_load
        // hook below. Do not load the old Lua script-message bridge.
''',
    'remove Lua yt-dlp bridge',
)

# 2) Use a private marker that mpv's stock ytdl_hook.lua will not interpret as
# its own ytdl:// force prefix or as a whitelisted http(s) URL.
replace_once(
    METAL,
    '''        let target = source.usesEmbeddedYTDLHook
            ? "ytdl://" + source.url.absoluteString
            : source.url.absoluteString
''',
    '''        let target = source.usesEmbeddedYTDLHook
            ? "iosytdl://" + source.url.absoluteString
            : source.url.absoluteString
''',
    'private iOS yt-dlp marker',
)

# 3) Register a native on_load hook on the exact mpv_handle whose event loop the
# controller already drains. 0x49595444 == ASCII "IYTD" and lets us distinguish
# this hook from any future native hooks on the same client.
text = METAL.read_text()
initialize_anchor = '        check(mpv_initialize(context))\n'
if initialize_anchor not in text:
    raise SystemExit('mpv_initialize(context) anchor not found in MPVMetalViewController.swift')
text = text.replace(
    initialize_anchor,
    initialize_anchor + '        check(mpv_hook_add(context, 0x49595444, "on_load", -100))\n',
    1,
)
METAL.write_text(text)

# 4) Consume MPV_EVENT_HOOK directly. Client-message handling is left in place
# for backwards compatibility, but the new path does not depend on it.
replace_once(
    METAL,
    '''                case MPV_EVENT_CLIENT_MESSAGE:
''',
    '''                case MPV_EVENT_HOOK:
                    guard event.pointee.reply_userdata == 0x49595444,
                          let data = event.pointee.data else { continue }
                    let hook = data.assumingMemoryBound(to: mpv_event_hook.self).pointee
                    self.handleEmbeddedYTDLHook(hookID: hook.id)

                case MPV_EVENT_CLIENT_MESSAGE:
''',
    'native hook event',
)

# 5) Resolve the marked website with the embedded YoutubeDL-iOS runtime, rewrite
# stream-open-filename to the selected direct stream/EDL, then continue the
# exact hook ID. mpv.conf remains the source of truth through options/ytdl-format.
replace_once(
    METAL,
    '''    private func handleClientMessage(_ args: [String]) {
''',
    '''    private func handleEmbeddedYTDLHook(hookID: UInt64) {
        let marker = "iosytdl://"
        let marked = getString("stream-open-filename") ?? ""

        guard marked.hasPrefix(marker) else {
            guard let context else { return }
            check(mpv_hook_continue(context, hookID))
            return
        }

        let rawURL = String(marked.dropFirst(marker.count))
        guard let url = URL(string: rawURL) else {
            finishEmbeddedYTDLHook(
                hookID: hookID,
                response: .failure("Invalid website URL: \\(rawURL)")
            )
            return
        }

        var selector = getString("options/ytdl-format") ?? ""
        if getString("options/vid") == "no" && selector.isEmpty {
            selector = "bestaudio/best"
        }

        print("[ios-ytdl-native] on_load request: \\(url.absoluteString); format=\\(selector)")
        Task { [weak self] in
            guard let self else { return }
            let response: YTDLPService.MPVHookResponse
            do {
                response = try await YTDLPService.shared.resolveForMPVHook(
                    url: url,
                    formatSelector: selector
                )
            } catch {
                response = .failure(error.localizedDescription)
            }
            self.finishEmbeddedYTDLHook(hookID: hookID, response: response)
        }
    }

    private func finishEmbeddedYTDLHook(
        hookID: UInt64,
        response: YTDLPService.MPVHookResponse
    ) {
        guard let context else { return }

        guard response.ok else {
            let reason = response.error ?? "unknown embedded yt-dlp error"
            print("[ios-ytdl-native] extraction failed: \\(reason)")
            setString("stream-open-filename", value: "memory://")
            command("show-text", args: ["yt-dlp failed: \\(reason)", "6000"])
            check(mpv_hook_continue(context, hookID))
            return
        }

        guard let stream = makeEmbeddedYTDLStream(response.formats) else {
            print("[ios-ytdl-native] extractor returned no playable stream")
            setString("stream-open-filename", value: "memory://")
            command("show-text", args: ["yt-dlp returned no playable stream", "6000"])
            check(mpv_hook_continue(context, hookID))
            return
        }

        // Clear per-file network values first so a previous website cannot leak
        // headers into this one. Cookie is intentionally preserved in the header
        // list; the old Lua bridge accidentally discarded it.
        setString("file-local-options/http-header-fields", value: "")
        setString("file-local-options/user-agent", value: "")
        setString("file-local-options/referrer", value: "")

        var extraHeaders: [String] = []
        for (name, value) in response.httpHeaders {
            switch name.lowercased() {
            case "user-agent":
                setString("file-local-options/user-agent", value: value)
            case "referer", "referrer":
                setString("file-local-options/referrer", value: value)
            default:
                extraHeaders.append(escapeMPVListItem("\\(name): \\(value)"))
            }
        }
        if !extraHeaders.isEmpty {
            setString("file-local-options/http-header-fields", value: extraHeaders.joined(separator: ","))
        }

        if let title = response.title, !title.isEmpty {
            setString("file-local-options/force-media-title", value: title)
        }
        setString("user-data/ios-ytdl-format", value: response.selector ?? "")
        setString("stream-open-filename", value: stream)

        let ids = response.formats.map(\\.formatID).joined(separator: "+")
        print("[ios-ytdl-native] selected \\(response.formats.count) stream(s): \\(ids); format=\\(response.selector ?? "")")
        check(mpv_hook_continue(context, hookID))
    }

    private func makeEmbeddedYTDLStream(
        _ formats: [YTDLPService.MPVHookFormat]
    ) -> String? {
        let playable = formats.filter { !$0.url.isEmpty }
        guard !playable.isEmpty else { return nil }
        if playable.count == 1 { return playable[0].url }

        let streams = playable.map { format -> String in
            let hasVideo = format.vcodec != nil && format.vcodec != "none"
            let hasAudio = format.acodec != nil && format.acodec != "none"
            var header = ["!new_stream", "!no_clip", "!no_chapters"]
            if hasVideo && !hasAudio {
                header.append("!delay_open,media_type=video")
            } else if hasAudio && !hasVideo {
                header.append("!delay_open,media_type=audio")
            }
            return header.joined(separator: ";") + ";" + edlEscape(format.url)
        }
        return "edl://" + streams.joined(separator: ";")
    }

    private func edlEscape(_ value: String) -> String {
        "%\\(value.utf8.count)%\\(value)"
    }

    private func handleClientMessage(_ args: [String]) {
''',
    'native embedded yt-dlp handler',
)

print('Applied native libmpv on_load hook for embedded yt-dlp and isolated iosytdl:// marker.')
