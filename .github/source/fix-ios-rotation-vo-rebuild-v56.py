from pathlib import Path
import re

CTRL=Path("MPVTorBox/Player/MPVMetalViewController.swift")
text=CTRL.read_text()

# The iOS Metal backend of the bundled MPVKit is known to fail to re-layout
# the GPU content after the CAMetalLayer itself is resized. Reload the
# video-output (not the file and not the video track) once UIKit has finished
# the orientation transition and the view pixel dimensions have stabilized.

key = "    private var rotationVideoRefreshGeneration = 0\n"
if key not in text:
    raise SystemExit("v56: v19 rotation-generation state anchor missing")
text=text.replace(key, key+'''    private var displayedViewportPixels: CGSize = .zero
    private var pendingRotationPixels: CGSize = .zero
    private var rotationVORebuildInProgress = false
    private var rotationVORestoring = false
''', 1)

start = text.find("    override func viewDidLayoutSubviews() {\n")
end = text.find("\n    override func viewWillTransition(",start)
if start<0 or end<0:raise SystemExit("v56: layout override not found")
replacement=r'''    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        guard isViewLoaded else { return }
        let scale = view.window?.screen.nativeScale ?? UIScreen.main.nativeScale
        if view.contentScaleFactor != scale {
            view.contentScaleFactor = scale
        }

        // A root-backed CAMetalLayer follows UIKit bounds. MoltenVK needs
        // a matching drawableSize BEFORE its video output is reconstructed.
        // Only mutate the stable root layer on the main/layout thread.
        let pixels = CGSize(
            width: (view.bounds.width * scale).rounded(),
            height: (view.bounds.height * scale).rounded()
        )
        guard pixels.width > 8, pixels.height > 8 else { return }
        if displayedViewportPixels == .zero {
            displayedViewportPixels = pixels // initial layout: no VO interruption
            metalLayer.drawableSize = pixels
            return
        }
        if displayedViewportPixels != pixels {
            scheduleVideoOutputGeometryRecovery()
        }
    }
'''
text=text[:start]+replacement+text[end:]

# Replace the previous 0.32s Video None -> Video logic with one
# geometry-confirmed VIDEO OUTPUT device reconstruction.
start=text.find("    private func scheduleVideoTrackReopenAfterRotation() {\n")
end=text.find("    private func selectedVideoTrackID() -> Int64? {\n",start)
if start<0 or end<0:raise SystemExit("v56: prior rotation track-reopen method not found")
method=r'''    private func scheduleVideoTrackReopenAfterRotation() {
        // Called by transition completion and orientation notifications.
        // Do NOT toggle "vid": it rebuilds decoder tracks but may leave the
        // old MoltenVK swapchain / GPU frame extent alive.
        scheduleVideoOutputGeometryRecovery()
    }

    private func rotationViewportPixels() -> CGSize? {
        guard isViewLoaded, view.window != nil else { return nil }
        let bounds = view.bounds
        let scale = view.window?.screen.nativeScale ?? UIScreen.main.nativeScale
        guard bounds.width > 8, bounds.height > 8 else { return nil }
        return CGSize(
            width: (bounds.width * scale).rounded(),
            height: (bounds.height * scale).rounded()
        )
    }

    private func scheduleVideoOutputGeometryRecovery() {
        guard Thread.isMainThread else {
            DispatchQueue.main.async { [weak self] in
                self?.scheduleVideoOutputGeometryRecovery()
            }
            return
        }
        guard let candidate = rotationViewportPixels() else { return }
        // Do not interrupt playback until we actually have a new pixel size.
        if candidate == displayedViewportPixels { return }
        pendingRotationPixels = candidate
        rotationVideoRefreshGeneration &+= 1
        let generation = rotationVideoRefreshGeneration

        // Geometry can arrive in successive UIKit/SwiftUI passes after the
        // transition callback. This trailing debounce uses real current
        // bounds, not a stale UIScreen/window snapshot or arbitrary rotation.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            guard let self, generation == self.rotationVideoRefreshGeneration,
                  let current = self.rotationViewportPixels() else { return }
            if current != candidate {
                self.scheduleVideoOutputGeometryRecovery()
                return
            }
            if current == self.displayedViewportPixels { return }

            if self.rotationVORebuildInProgress || self.rotationVORestoring {
                // A previous VO restoration is not finished. Try again once
                // its callback completes, avoiding overlapping GPU teardown.
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
                    self?.scheduleVideoOutputGeometryRecovery()
                }
                return
            }

            self.displayedViewportPixels = current
            self.metalLayer.drawableSize = current
            self.view.setNeedsLayout()
            self.view.layoutIfNeeded()

            guard self.selectedVideoTrackID() != nil,
                  self.mpv != nil else { return }

            self.rebuildVideoOutputForRotation(pixels: current)
        }
    }

    private func rebuildVideoOutputForRotation(pixels: CGSize) {
        guard !rotationVORebuildInProgress,
              let context = mpv,
              selectedVideoTrackID() != nil else { return }

        rotationVORebuildInProgress = true
        let requested = (getString("options/vo") ?? "gpu-next")
        let restoreVO = requested == "null" || requested.isEmpty ? "gpu-next" : requested
        MPVPlayerLifecycleLog.write(
            "rotation VO rebuild begin pixels=\\(Int(pixels.width))x\\(Int(pixels.height)) vo=\\(restoreVO)"
        )

        // vo carries UPDATE_VO in mpv's option table; toggling it forces the
        // old Vulkan/MoltenVK swapchain to be destroyed and recreated on the
        // same, UIKit-owned CAMetalLayer. No loadfile, yt-dlp, URL re-request,
        // audio/subtitle reset, or seek is needed.
        let off = mpv_set_property_string(context, "vo", "null")
        MPVPlayerLifecycleLog.write("rotation vo=null status=\\(off)")
        if off < 0 {
            rotationVORebuildInProgress = false
            // Last-resort: request reconfiguration only when switching VO
            // is unavailable in this libmpv binary.
            command("video-reconfig", args: [])
            return
        }
        rotationVORestoring = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) { [weak self] in
            guard let self, let alive = self.mpv else { return }
            let restored = mpv_set_property_string(alive, "vo", restoreVO)
            MPVPlayerLifecycleLog.write("rotation vo restored status=\\(restored)")
            self.rotationVORestoring = false
            self.rotationVORebuildInProgress = false
            if restored < 0 {
                // Do not leave the user with vo=null if preferred backend
                // was rejected. Fall back to the original existing backend.
                _ = mpv_set_property_string(alive, "vo", "gpu-next")
            }
            // Apply any more recent UIKit rotation after the first swapchain
            // is restored. This never runs several VO rebuilds concurrently.
            self.scheduleVideoOutputGeometryRecovery()
        }
    }

'''
text=text[:start]+method+text[end:]

# Avoid mutating CAMetalLayer in stale dispatch retries; all writes now live
# in layout and in a settled, main-thread completion.
CTRL.write_text(text)
print("v56: stable UIKit root Metal drawable + dynamic mpv VIDEO OUTPUT recreation, no video track toggling")
