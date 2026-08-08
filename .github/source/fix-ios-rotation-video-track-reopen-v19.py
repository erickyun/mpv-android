from pathlib import Path

ROOT = Path('MPVTorBox')
METAL = ROOT / 'Player' / 'MPVMetalViewController.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label} anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# The normal CAMetalLayer resize + video-reconfig path is not sufficient on the
# iOS libmpv backend used by this app. The user's reliable manual recovery is to
# disable the current video track and select it again. Do exactly that after the
# rotation has settled, without reloading the file or touching audio/subtitles.
replace_once(
    METAL,
    '''    private var timerTick = 0
    private var subtitleAccesses: [SecurityScopedAccess] = []
''',
    '''    private var timerTick = 0
    private var subtitleAccesses: [SecurityScopedAccess] = []
    private var rotationVideoRefreshGeneration = 0
''',
    'rotation video refresh generation state',
)

replace_once(
    METAL,
    '''        coordinator.animate(alongsideTransition: { [weak self] _ in
            self?.view.setNeedsLayout()
        }, completion: { [weak self] _ in
            self?.scheduleSurfaceRefreshes()
        })
''',
    '''        coordinator.animate(alongsideTransition: { [weak self] _ in
            self?.view.setNeedsLayout()
        }, completion: { [weak self] _ in
            self?.scheduleSurfaceRefreshes()
            self?.scheduleVideoTrackReopenAfterRotation()
        })
''',
    'schedule hard video refresh after transition',
)

replace_once(
    METAL,
    '''    private func scheduleSurfaceRefreshes() {
        // Rotation/layout delivery is asynchronous across UIKit and SwiftUI.
        // Crucially, no size is captured here: each retry re-reads the current
        // view.bounds after that point in the transition.
        for delay in [0.0, 0.03, 0.10, 0.25, 0.50, 0.85] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                guard let self else { return }
                self.view.setNeedsLayout()
                self.view.layoutIfNeeded()
                self.refreshVideoSurface(reconfigure: true)
            }
        }
    }

    deinit {
''',
    '''    private func scheduleSurfaceRefreshes() {
        // Rotation/layout delivery is asynchronous across UIKit and SwiftUI.
        // Crucially, no size is captured here: each retry re-reads the current
        // view.bounds after that point in the transition.
        for delay in [0.0, 0.03, 0.10, 0.25, 0.50, 0.85] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                guard let self else { return }
                self.view.setNeedsLayout()
                self.view.layoutIfNeeded()
                self.refreshVideoSurface(reconfigure: true)
            }
        }
    }

    private func scheduleVideoTrackReopenAfterRotation() {
        // Debounce the orientation notification and transition callback into a
        // single hard refresh. Waiting briefly is intentional: the manual
        // Video -> None -> Video workaround succeeds because it happens after
        // UIKit/SwiftUI have fully committed the new landscape geometry.
        rotationVideoRefreshGeneration &+= 1
        let generation = rotationVideoRefreshGeneration

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.32) { [weak self] in
            guard let self,
                  generation == self.rotationVideoRefreshGeneration else { return }

            self.view.setNeedsLayout()
            self.view.layoutIfNeeded()
            self.refreshVideoSurface(reconfigure: true)

            guard let videoTrackID = self.selectedVideoTrackID() else { return }

            // This is deliberately the same state transition that fixes the
            // renderer from the in-player Video menu. It does not loadfile,
            // seek, re-run yt-dlp, or modify the selected audio/subtitle track.
            self.setString("vid", value: "no")

            DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) { [weak self] in
                guard let self,
                      generation == self.rotationVideoRefreshGeneration else { return }
                self.setString("vid", value: String(videoTrackID))
                self.refreshVideoSurface(reconfigure: true)
            }
        }
    }

    private func selectedVideoTrackID() -> Int64? {
        let count = Int(getInt("track-list/count") ?? 0)
        guard count > 0 else { return nil }

        for index in 0..<count {
            let prefix = "track-list/\\(index)"
            guard getString("\\(prefix)/type") == "video",
                  getFlag("\\(prefix)/selected"),
                  let id = getInt("\\(prefix)/id") else { continue }
            return id
        }
        return nil
    }

    deinit {
''',
    'hard rotation video track reopen helper',
)

replace_once(
    METAL,
    '''    @objc private func deviceOrientationDidChange() {
        // Never snapshot UIWindow bounds here. This notification commonly fires
        // before UIKit has swapped portrait/landscape dimensions.
        scheduleSurfaceRefreshes()
    }
''',
    '''    @objc private func deviceOrientationDidChange() {
        // Never snapshot UIWindow bounds here. This notification commonly fires
        // before UIKit has swapped portrait/landscape dimensions.
        scheduleSurfaceRefreshes()
        scheduleVideoTrackReopenAfterRotation()
    }
''',
    'orientation notification hard video refresh',
)

print('Added a debounced post-rotation Video None -> same track reopen to rebuild the iOS libmpv video output.')
