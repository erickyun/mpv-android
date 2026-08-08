from pathlib import Path

ROOT = Path('MPVTorBox')
METAL = ROOT / 'Player' / 'MPVMetalViewController.swift'
REPRESENTABLE = ROOT / 'Player' / 'MPVMetalPlayerView.swift'
PLAYER = ROOT / 'Views' / 'PlayerScreen.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label} anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# UIKit owns the actual drawable geometry. During rotation the device orientation
# notification can arrive before UIWindow/SwiftUI publishes its new landscape
# size. The old code captured that early portrait size and replayed it in every
# delayed retry, leaving the Metal layer portrait-sized inside a landscape view.
# Always sample the controller's *current* local bounds at execution time.
replace_once(
    METAL,
    '''    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        refreshVideoSurface(reconfigure: true)
    }
''',
    '''    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        // view.bounds is authoritative after UIKit has completed this layout
        // pass. refreshVideoSurface itself reconfigures mpv only when the
        // drawable dimensions really changed.
        refreshVideoSurface()
    }
''',
    'layout surface refresh',
)

replace_once(
    METAL,
    '''    override func viewWillTransition(
        to size: CGSize,
        with coordinator: UIViewControllerTransitionCoordinator
    ) {
        super.viewWillTransition(to: size, with: coordinator)
        coordinator.animate(alongsideTransition: { [weak self] _ in
            self?.refreshVideoSurface(viewportSize: size, reconfigure: true)
        }, completion: { [weak self] _ in
            self?.scheduleSurfaceRefreshes(preferredSize: size)
        })
    }

    func refreshVideoSurface(viewportSize: CGSize? = nil, reconfigure: Bool = false) {
        guard isViewLoaded else { return }
        let requestedSize = viewportSize.flatMap { $0.width > 1 && $0.height > 1 ? $0 : nil }
        let currentSize = requestedSize ?? view.window?.bounds.size ?? view.bounds.size
        let bounds = CGRect(origin: .zero, size: currentSize)
        guard bounds.width > 1, bounds.height > 1 else { return }

        let scale = view.window?.screen.nativeScale ?? UIScreen.main.nativeScale
        let targetDrawableSize = CGSize(
            width: bounds.width * scale,
            height: bounds.height * scale
        )
        let sizeChanged = metalLayer.frame != bounds || metalLayer.drawableSize != targetDrawableSize

        if sizeChanged {
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            metalLayer.contentsScale = scale
            metalLayer.frame = bounds
            metalLayer.drawableSize = targetDrawableSize
            CATransaction.commit()
            metalLayer.setNeedsDisplay()
        }

        if reconfigure || sizeChanged {
            command("video-reconfig", args: [])
        }
    }

    private func scheduleSurfaceRefreshes(preferredSize: CGSize? = nil) {
        for delay in [0.0, 0.05, 0.15, 0.35, 0.70] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                guard let self else { return }
                self.view.setNeedsLayout()
                self.view.layoutIfNeeded()
                self.refreshVideoSurface(viewportSize: preferredSize, reconfigure: true)
            }
        }
    }
''',
    '''    override func viewWillTransition(
        to size: CGSize,
        with coordinator: UIViewControllerTransitionCoordinator
    ) {
        super.viewWillTransition(to: size, with: coordinator)

        // Do not write `size` directly into the Metal layer. SwiftUI/UIKit can
        // still be presenting the previous controller bounds while the
        // transition callback is running. Let layout establish the real bounds,
        // then sample those live bounds in every retry.
        coordinator.animate(alongsideTransition: { [weak self] _ in
            self?.view.setNeedsLayout()
        }, completion: { [weak self] _ in
            self?.scheduleSurfaceRefreshes()
        })
    }

    func refreshVideoSurface(reconfigure: Bool = false) {
        guard isViewLoaded else { return }

        // A CALayer added to `view.layer` uses the view's local coordinate
        // system. `view.bounds` is therefore the only size that should drive
        // both its frame and CAMetalLayer drawableSize. UIWindow bounds and
        // SwiftUI GeometryReader snapshots can be one rotation behind.
        let bounds = view.bounds.integral
        guard bounds.width > 1, bounds.height > 1 else { return }

        let scale = view.window?.screen.nativeScale ?? UIScreen.main.nativeScale
        let targetDrawableSize = CGSize(
            width: bounds.width * scale,
            height: bounds.height * scale
        )
        let sizeChanged = metalLayer.frame != bounds || metalLayer.drawableSize != targetDrawableSize

        if sizeChanged {
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            metalLayer.contentsScale = scale
            metalLayer.frame = bounds
            metalLayer.drawableSize = targetDrawableSize
            CATransaction.commit()
            metalLayer.setNeedsDisplay()
        }

        if reconfigure || sizeChanged {
            command("video-reconfig", args: [])
        }
    }

    private func scheduleSurfaceRefreshes() {
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
''',
    'rotation and live-bounds renderer sizing',
)

replace_once(
    METAL,
    '''    @objc private func deviceOrientationDidChange() {
        scheduleSurfaceRefreshes(preferredSize: view.window?.bounds.size)
    }
''',
    '''    @objc private func deviceOrientationDidChange() {
        // Never snapshot UIWindow bounds here. This notification commonly fires
        // before UIKit has swapped portrait/landscape dimensions.
        scheduleSurfaceRefreshes()
    }
''',
    'orientation notification live sizing',
)

# The representable used to pass GeometryReader snapshots into the renderer and
# then captured the same snapshot in an async closure. An old portrait update
# could therefore run after the new landscape update and overwrite it. UIKit
# controller bounds now remain the single source of truth.
replace_once(
    REPRESENTABLE,
    '''struct MPVMetalPlayerView: UIViewControllerRepresentable {
    @ObservedObject var coordinator: Coordinator
    var viewportSize: CGSize = .zero
''',
    '''struct MPVMetalPlayerView: UIViewControllerRepresentable {
    @ObservedObject var coordinator: Coordinator
''',
    'remove external viewport snapshot',
)

replace_once(
    REPRESENTABLE,
    '''        uiViewController.refreshVideoSurface(viewportSize: viewportSize, reconfigure: true)
        DispatchQueue.main.async {
            uiViewController.refreshVideoSurface(viewportSize: viewportSize, reconfigure: true)
        }
''',
    '''        uiViewController.refreshVideoSurface()
        DispatchQueue.main.async { [weak uiViewController] in
            // Re-read the controller's live bounds on the next run-loop turn;
            // never replay a captured SwiftUI geometry value.
            uiViewController?.refreshVideoSurface()
        }
''',
    'representable live viewport refresh',
)

replace_once(
    PLAYER,
    '                MPVMetalPlayerView(coordinator: coordinator, viewportSize: geometry.size)\n',
    '                MPVMetalPlayerView(coordinator: coordinator)\n',
    'PlayerScreen remove viewport snapshot',
)

print('Fixed landscape renderer sizing by making live UIView bounds the sole Metal viewport authority.')
