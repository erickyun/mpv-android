from pathlib import Path

ROOT = Path('MPVTorBox')
PROJECT = Path('project.yml')


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'Expected pattern not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1))


resolver = ROOT / 'SourceResolver.swift'
replace_once(
    resolver,
    r'''        if settings.ytdlpEnabled, !looksLikeDirectMedia(url) {
            do {
                return try await ytdlp.resolve(url: url, status: status)
            } catch {
                throw ResolverError.ytdlpFailed(error.localizedDescription)
            }
        }

        await status("Opening media URL…")
''',
    r'''        if settings.ytdlpEnabled, shouldUseYTDLP(url) {
            await status("Resolving supported website URL with yt-dlp…")
            do {
                return try await ytdlp.resolve(url: url, status: status)
            } catch {
                throw ResolverError.ytdlpFailed(error.localizedDescription)
            }
        }

        await status(settings.ytdlpEnabled
            ? "Opening URL directly — yt-dlp is not needed for this address…"
            : "Opening media URL…")
'''
)
replace_once(
    resolver,
    r'''    private func looksLikeDirectMedia(_ url: URL) -> Bool {
        let extensions = ["mkv", "mp4", "mov", "m4v", "webm", "avi", "ts", "m2ts", "mp3", "m4a", "flac", "opus", "ogg", "wav", "m3u8", "mpd"]
        return extensions.contains(url.pathExtension.lowercased())
    }
''',
    r'''    private func looksLikeDirectMedia(_ url: URL) -> Bool {
        let extensions = ["mkv", "mp4", "mov", "m4v", "webm", "avi", "ts", "m2ts", "mp3", "m4a", "flac", "opus", "ogg", "wav", "m3u8", "mpd", "aac", "ac3", "eac3", "mka", "flv"]
        if extensions.contains(url.pathExtension.lowercased()) { return true }

        let lower = url.absoluteString.lowercased()
        let mediaHints = [
            "application/vnd.apple.mpegurl", "video/", "audio/", ".m3u8?", ".mpd?",
            "manifest.m3u8", "master.m3u8", "playlist.m3u8", "videoplayback?",
            "mime=video", "mime=audio", "content-type=video", "content-type=audio"
        ]
        return mediaHints.contains { lower.contains($0) }
    }

    private func shouldUseYTDLP(_ url: URL) -> Bool {
        if looksLikeDirectMedia(url) { return false }
        guard var host = url.host?.lowercased(), !host.isEmpty else { return false }
        if host.hasPrefix("www.") { host.removeFirst(4) }

        let websiteHosts = [
            "youtube.com", "youtu.be", "youtube-nocookie.com",
            "vimeo.com", "dailymotion.com", "dai.ly",
            "twitch.tv", "clips.twitch.tv",
            "tiktok.com", "instagram.com",
            "twitter.com", "x.com",
            "reddit.com", "redd.it",
            "soundcloud.com", "facebook.com", "fb.watch",
            "bilibili.com", "b23.tv", "nicovideo.jp",
            "crunchyroll.com", "rumble.com", "odysee.com"
        ]
        return websiteHosts.contains { host == $0 || host.hasSuffix("." + $0) }
    }
'''
)

# Direct URLs now bypass yt-dlp entirely; supported website extraction gets a
# shorter safety ceiling so a broken extractor cannot hold the UI indefinitely.
ytdlp = ROOT / 'YTDLPService.swift'
text = ytdlp.read_text()
text = text.replace('within 45 seconds', 'within 20 seconds')
text = text.replace('yt-dlp (45 second timeout)', 'yt-dlp')
text = text.replace('runWithTimeout(seconds: 45)', 'runWithTimeout(seconds: 20)')
ytdlp.write_text(text)

metal = ROOT / 'Player' / 'MPVMetalViewController.swift'
replace_once(
    metal,
    r'''    func loadSource(_ source: ResolvedSource) {
        playSource = source
        if source.httpHeaders.isEmpty {
            setString("http-header-fields", value: "")
        } else {
            let fields = source.httpHeaders.map { "\($0.key): \($0.value)" }.joined(separator: ",")
            setString("http-header-fields", value: fields)
        }
        command("loadfile", args: [source.url.absoluteString, "replace"])
    }
''',
    r'''    func loadSource(_ source: ResolvedSource) {
        playSource = source

        setString("http-header-fields", value: "")
        setString("user-agent", value: "")
        setString("referrer", value: "")

        var extraHeaders: [String] = []
        for (name, value) in source.httpHeaders {
            switch name.lowercased() {
            case "user-agent":
                setString("user-agent", value: value)
            case "referer", "referrer":
                setString("referrer", value: value)
            default:
                extraHeaders.append(escapeMPVListItem("\(name): \(value)"))
            }
        }
        if !extraHeaders.isEmpty {
            setString("http-header-fields", value: extraHeaders.joined(separator: ","))
        }

        command("loadfile", args: [source.url.absoluteString, "replace"])
    }
'''
)
replace_once(
    metal,
    r'''    private func formatNumber(_ value: Double?, suffix: String, decimals: Int = 2) -> String {
''',
    r'''    private func escapeMPVListItem(_ value: String) -> String {
        value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: ",", with: "\\,")
    }

    private func optionString(_ name: String, fallback: String = "—") -> String {
        let value = getString("options/\(name)") ?? getString(name)
        guard let value, !value.isEmpty else { return fallback }
        return value
    }

    private func formatDebandSettings() -> String {
        let enabled = optionString("deband", fallback: "no")
        guard enabled != "no" else { return "no" }
        return "yes · iterations \(optionString("deband-iterations")) · threshold \(optionString("deband-threshold")) · range \(optionString("deband-range")) · grain \(optionString("deband-grain"))"
    }

    private func formatShaderList() -> String {
        let raw = optionString("glsl-shaders", fallback: "")
        guard !raw.isEmpty, raw != "[]" else { return "None" }
        let separators = CharacterSet(charactersIn: ":;,")
        let names = raw
            .components(separatedBy: separators)
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .map {
                let name = URL(fileURLWithPath: $0).lastPathComponent
                return name.isEmpty ? $0 : name
            }
        return names.isEmpty ? raw : names.joined(separator: ", ")
    }

    private func formatNumber(_ value: Double?, suffix: String, decimals: Int = 2) -> String {
'''
)

models = ROOT / 'Models' / 'PlayerModels.swift'
replace_once(
    models,
    r'''    var hardwareDecoder = "—"
    var videoFPS = "—"
''',
    r'''    var hardwareDecoder = "—"
    var videoOutput = "—"
    var gpuAPI = "—"
    var gpuContext = "—"
    var rendererProfile = "—"
    var scaler = "—"
    var chromaScaler = "—"
    var downscaler = "—"
    var interpolation = "—"
    var videoSync = "—"
    var deband = "—"
    var toneMapping = "—"
    var dithering = "—"
    var shaders = "None"
    var videoFPS = "—"
'''
)
replace_once(
    metal,
    r'''        stats.hardwareDecoder = getString("hwdec-current") ?? "software"
        stats.videoFPS = formatNumber(getDouble("estimated-vf-fps"), suffix: " fps")
''',
    r'''        stats.hardwareDecoder = getString("hwdec-current") ?? optionString("hwdec", fallback: "software")
        stats.videoOutput = getString("current-vo") ?? optionString("vo")
        stats.gpuAPI = optionString("gpu-api", fallback: "auto")
        stats.gpuContext = optionString("gpu-context", fallback: "auto")
        stats.rendererProfile = optionString("profile", fallback: "high-quality")
        stats.scaler = optionString("scale")
        stats.chromaScaler = optionString("cscale")
        stats.downscaler = optionString("dscale")
        stats.interpolation = optionString("interpolation", fallback: "no")
        stats.videoSync = optionString("video-sync", fallback: "audio")
        stats.deband = formatDebandSettings()
        stats.toneMapping = optionString("tone-mapping", fallback: "auto")
        stats.dithering = "depth \(optionString("dither-depth", fallback: "auto")) · algo \(optionString("dither", fallback: "auto"))"
        stats.shaders = formatShaderList()
        stats.videoFPS = formatNumber(getDouble("estimated-vf-fps"), suffix: " fps")
'''
)

stats = ROOT / 'Views' / 'StatsOverlay.swift'
replace_once(
    stats,
    r'''            PAGE 2 — VIDEO RENDERING
            Resolution: \(stats.resolution)
            Video: \(stats.videoCodec)  \(stats.pixelFormat)
            Decoder: \(stats.hardwareDecoder)
            Video FPS: \(stats.videoFPS)
            Display: \(stats.displayFPS)
            Decoder drops: \(stats.decoderDrops)
            Output drops: \(stats.outputDrops)
            Mistimed / delayed: \(stats.mistimedFrames) / \(stats.delayedFrames)
            A/V sync: \(stats.avSync)
''',
    r'''            PAGE 2 — GPU RENDERING & SHADERS
            Resolution: \(stats.resolution)
            Video: \(stats.videoCodec)  \(stats.pixelFormat)
            Decoder: \(stats.hardwareDecoder)
            VO: \(stats.videoOutput)
            GPU API / context: \(stats.gpuAPI) / \(stats.gpuContext)
            Profile: \(stats.rendererProfile)
            Scale / cscale / dscale: \(stats.scaler) / \(stats.chromaScaler) / \(stats.downscaler)
            Interpolation / sync: \(stats.interpolation) / \(stats.videoSync)
            Deband: \(stats.deband)
            Tone mapping: \(stats.toneMapping)
            Dithering: \(stats.dithering)
            GLSL shaders: \(stats.shaders)
            Video FPS: \(stats.videoFPS)  Display: \(stats.displayFPS)
            Decoder / output drops: \(stats.decoderDrops) / \(stats.outputDrops)
            Mistimed / delayed: \(stats.mistimedFrames) / \(stats.delayedFrames)
            A/V sync: \(stats.avSync)
'''
)

advanced = ROOT / 'AdvancedSettingsView.swift'
replace_once(
    advanced,
    r'''                Section("MPV configuration") {
''',
    r'''                Section("Renderer diagnostics") {
                    LabeledContent("Default VO", value: "gpu-next")
                    LabeledContent("Default GPU path", value: "Vulkan / MoltenVK")
                    LabeledContent("Default hardware decoder", value: "VideoToolbox")
                    Text("Open Stats → Page 2 during playback to see the effective VO, GPU API/context, scaler chain, deband parameters, tone mapping, dithering, and loaded GLSL shader filenames.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Section("MPV configuration") {
'''
)
replace_once(
    advanced,
    r'''                Section("Provider priority") {
                    Text("TorBox → TorrServer fallback → yt-dlp → Direct media URL")
''',
    r'''                Section("Provider priority") {
                    Text("TorBox → TorrServer fallback → known website hosts through yt-dlp → all other HTTP URLs directly in MPV")
'''
)

project_text = PROJECT.read_text()
project_text = project_text.replace('        MARKETING_VERSION: 1.3.0\n', '        MARKETING_VERSION: 1.5.0\n', 1)
project_text = project_text.replace('        CURRENT_PROJECT_VERSION: 13\n', '        CURRENT_PROJECT_VERSION: 15\n', 1)
PROJECT.write_text(project_text)

print('Applied direct URL routing, yt-dlp header handoff, and renderer/shader diagnostics.')
