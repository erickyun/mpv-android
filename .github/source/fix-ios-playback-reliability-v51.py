from pathlib import Path
import re

ROOT = Path("MPVTorBox")
CONFIG = ROOT / "Utilities" / "MPVConfigManager.swift"
METAL = ROOT / "Player" / "MPVMetalViewController.swift"
PLAYER = ROOT / "Views" / "PlayerScreen.swift"
RANGE = ROOT / "RemoteZIPRangeClient.swift"
REPRESENTABLE = ROOT / "Player" / "MPVMetalPlayerView.swift"

# 1. Replace 256 KB HTTPS requests with 1 MB chunks; reduce expensive
# URLSession construction/RTT per MB and allow mpv to read ahead. The Range
# cache is capped independently of mpv's demuxer cache.
text = RANGE.read_text()
assert "private let blockSize: Int64 = 256 * 1024" in text
assert "private let maxCachedBlocks = 96" in text
text = text.replace("private let blockSize: Int64 = 256 * 1024",
                    "private let blockSize: Int64 = 1024 * 1024", 1)
text = text.replace("private let maxCachedBlocks = 96 // <=24 MiB of compressed ZIP bytes",
                    "private let maxCachedBlocks = 96 // <=96 MiB of compressed ZIP bytes", 1)
RANGE.write_text(text)

# 2. Genuine mpv demuxer cache options. Users can edit these in Files /
# On My iPhone / MPV / MPVConfig / mpv.conf. Existing active values stay
# unchanged; missing defaults are inserted automatically.
text = CONFIG.read_text()
needle = "        ensureYTDLFormat(in: mpvConfig)\n"
if needle not in text:
    raise SystemExit("v51: MPVConfigManager ensureYTDLFormat anchor missing")
text = text.replace(needle, needle + "        ensureStreamCacheDefaults(in: mpvConfig)\n", 1)
anchor = "    private static func ensureYTDLFormat(in url: URL) {\n"
if anchor not in text:
    raise SystemExit("v51: MPVConfigManager ensureYTDLFormat function missing")
helper = r'''    private static func ensureStreamCacheDefaults(in url: URL) {
        let existing = (try? String(contentsOf: url, encoding: .utf8)) ?? ""
        let activeKeys = Set(existing.split(separator: "\n").compactMap { raw -> String? in
            let line = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.isEmpty, !line.hasPrefix("#") else { return nil }
            guard let key = line.split(separator: "=", maxSplits: 1).first else { return nil }
            return String(key).trimmingCharacters(in: .whitespacesAndNewlines)
        })
        // mpv's actual forward cache is bounded by both time and bytes.
        // A 50-second *target* does not guarantee 50 seconds if bitrate or
        // network throughput exceeds the configured memory budget.
        let defaults: [(String, String)] = [
            ("cache", "yes"),
            ("cache-secs", "50"),
            ("demuxer-readahead-secs", "50"),
            ("demuxer-max-bytes", "256MiB"),
            ("demuxer-max-back-bytes", "64MiB")
        ]
        let lines = defaults.compactMap { key, value -> String? in
            activeKeys.contains(key) ? nil : "\(key)=\(value)"
        }
        guard !lines.isEmpty else { return }
        append("\n# MPV iOS managed streaming cache v51 — values editable\n"
            + lines.joined(separator: "\n") + "\n", to: url)
    }

'''
text = text.replace(anchor, helper + anchor, 1)
CONFIG.write_text(text)

# 3. Rotation: the UIView's backing layer is already a MetalLayer, so UIKit
# owns its frame and drawableSize. The old refreshVideoSurface() still tried
# to mutate both while MoltenVK and UIKit were resizing. Stop doing that.
text = METAL.read_text()
start = text.find("    func refreshVideoSurface(reconfigure: Bool = false) {\n")
end = text.find("    private func scheduleSurfaceRefreshes() {\n", start)
if start < 0 or end < 0:
    raise SystemExit("v51: Metal refreshVideoSurface boundary missing")
text = text[:start] + r'''    func refreshVideoSurface(reconfigure: Bool = false) {
        guard Thread.isMainThread, isViewLoaded else { return }
        guard view.bounds.width > 1, view.bounds.height > 1 else { return }
        // The UIView's root MetalLayer is owned/sized by UIKit. Do not write
        // frame, drawableSize, or setNeedsDisplay on it here.
        let scale = view.window?.screen.nativeScale ?? UIScreen.main.nativeScale
        if view.contentScaleFactor != scale {
            view.contentScaleFactor = scale
        }
        if reconfigure {
            command("video-reconfig", args: [])
        }
    }

''' + text[end:]
# Do not send 6 video-reconfig commands while UIKit is transitioning.
segStart = text.find("    private func scheduleSurfaceRefreshes() {\n")
segEnd = text.find("    private func scheduleVideoTrackReopenAfterRotation() {\n", segStart)
if segStart < 0 or segEnd < 0: raise SystemExit("v51: scheduled refresh boundary missing")
segment = text[segStart:segEnd]
# v34/v35 already replaced the old six-timer Metal mutations with a
# single UIKit layout callback. Preserve the safer implementation as-is.
# Only tune delays when an older source variant still has the retry loop.
if "for delay in [0.0, 0.03, 0.10, 0.25, 0.50, 0.85] {" in segment:
    segment = segment.replace(
        "for delay in [0.0, 0.03, 0.10, 0.25, 0.50, 0.85] {",
        "for delay in [0.0, 0.10, 0.30, 0.65, 0.95] {", 1
    )
    segment = segment.replace("self.refreshVideoSurface(reconfigure: true)",
                              "self.refreshVideoSurface()", 1)
else:
    if "Kept for compatibility with older call sites" not in segment:
        raise SystemExit("v51: unknown Metal retry implementation")
text = text[:segStart] + segment + text[segEnd:]
# Only reopen after all surface refreshes finished and UIKit has committed its
# correct portrait/landscape bounds.
segStart = text.find("    private func scheduleVideoTrackReopenAfterRotation() {\n")
segEnd = text.find("    private func selectedVideoTrackID() -> Int64? {\n", segStart)
if segStart < 0 or segEnd < 0: raise SystemExit("v51: track reopen boundary missing")
segment = text[segStart:segEnd]
if "deadline: .now() + 0.32" not in segment:
    raise SystemExit("v51: expected old rotation delay missing")
segment = segment.replace("deadline: .now() + 0.32",
                          "deadline: .now() + 1.10", 1)
segment = segment.replace("deadline: .now() + 0.08",
                          "deadline: .now() + 0.12", 1)
text = text[:segStart] + segment + text[segEnd:]
METAL.write_text(text)

# 4. SwiftUI: prevent the representable from choosing an intrinsic height from
# a previously rotated UIViewController. UIKit Metal drawing must fill the
# currently proposed SwiftUI player area without recreating libmpv.
text = REPRESENTABLE.read_text()
anchor = "    func makeUIViewController(context: Context) -> MPVMetalViewController {\n"
if anchor not in text:
    raise SystemExit("v51: makeUIViewController method not found")
if "func sizeThatFits(_ proposal: ProposedViewSize" not in text:
    text = text.replace(anchor, r'''    func sizeThatFits(
        _ proposal: ProposedViewSize,
        uiViewController: MPVMetalViewController,
        context: Context
    ) -> CGSize? {
        guard let width = proposal.width, let height = proposal.height,
              width > 1, height > 1 else { return nil }
        return CGSize(width: width, height: height)
    }

''' + anchor, 1)
REPRESENTABLE.write_text(text)

# 5. The Info icon is a Menu in the topBar, not an independent Button.
# Keep the entire toolbar (and every hit target) below Dynamic Island while
# portrait; landscape should retain the existing compact placement.
text = PLAYER.read_text()
anchor = '''    private func controls(size: CGSize) -> some View {
        VStack(spacing: 0) {
            topBar
'''
replacement = '''    private func controls(size: CGSize) -> some View {
        VStack(spacing: 0) {
            topBar
                .padding(.top, size.height > size.width ? 48 : 0)
'''
if anchor not in text:
    raise SystemExit("v51: PlayerScreen topBar placement anchor missing")
PLAYER.write_text(text.replace(anchor, replacement, 1))

print("v51 cache targets, 1MiB ZIP Range blocks, UIKit-owned Metal resizing, settled track refresh and portrait safe-area toolbar placement applied.")
