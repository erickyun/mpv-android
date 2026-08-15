from pathlib import Path

ROOT = Path('MPVTorBox')
CTRL = ROOT / 'Player' / 'MPVMetalViewController.swift'
REP = ROOT / 'Player' / 'MPVMetalPlayerView.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))

# CAMetalLayer is a presentation surface, not a display-backed drawing layer.
replace_once(
    CTRL,
    '''        metalLayer.backgroundColor = UIColor.black.cgColor
        metalLayer.needsDisplayOnBoundsChange = true
        view.layer.addSublayer(metalLayer)
''',
    '''        metalLayer.backgroundColor = UIColor.black.cgColor
        // CAMetalLayer is presented by MoltenVK/mpv. Do not opt it into UIKit's
        // display invalidation/timing path; that creates extra CoreAnimation
        // transactions while the renderer owns the drawable lifecycle.
        metalLayer.needsDisplayOnBoundsChange = false
        view.layer.addSublayer(metalLayer)
''',
    'disable display invalidation',
)

replace_once(
    CTRL,
    '''    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        becomeFirstResponder()
        refreshVideoSurface(reconfigure: true)
    }
''',
    '''    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        becomeFirstResponder()
        view.setNeedsLayout()
    }
''',
    'viewDidAppear surface write',
)

old_layout = '''    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        // view.bounds is authoritative after UIKit has completed this layout
        // pass. refreshVideoSurface itself reconfigures mpv only when the
        // drawable dimensions really changed.
        refreshVideoSurface()
    }

    override func viewSafeAreaInsetsDidChange() {
        super.viewSafeAreaInsetsDidChange()
        refreshVideoSurface()
    }
'''
new_layout = '''    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        updateMetalLayerGeometry()
    }

    private func updateMetalLayerGeometry() {
        // This is the *only* place that mutates CAMetalLayer geometry. Keeping
        // layer writes inside UIKit's layout pass avoids racing CoreAnimation's
        // transaction commit with SwiftUI updates, orientation notifications,
        // delayed retries, and MoltenVK drawable presentation.
        guard Thread.isMainThread, isViewLoaded else { return }
        let bounds = view.bounds.integral
        guard bounds.width > 1, bounds.height > 1 else { return }

        let scale = view.window?.screen.nativeScale ?? UIScreen.main.nativeScale
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        if metalLayer.contentsScale != scale { metalLayer.contentsScale = scale }
        if metalLayer.frame != bounds { metalLayer.frame = bounds }
        CATransaction.commit()

        // Do not set drawableSize here. MoltenVK owns it and MetalLayer already
        // filters the upstream 1x1 presentation workaround.
        // Do not call setNeedsDisplay(); CAMetalLayer is not drawn by UIKit.
    }
'''
replace_once(CTRL, old_layout, new_layout, 'single UIKit layout owner')

old_transition = '''    override func viewWillTransition(
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
            self?.scheduleVideoTrackReopenAfterRotation()
        })
    }
'''
new_transition = '''    override func viewWillTransition(
        to size: CGSize,
        with coordinator: UIViewControllerTransitionCoordinator
    ) {
        super.viewWillTransition(to: size, with: coordinator)
        // UIKit owns geometry. One layout request during the transition and one
        // post-transition renderer refresh are sufficient; never write the Metal
        // layer directly from transition callbacks.
        coordinator.animate(alongsideTransition: { [weak self] _ in
            self?.view.setNeedsLayout()
        }, completion: { [weak self] _ in
            guard let self else { return }
            self.view.setNeedsLayout()
            self.view.layoutIfNeeded()
            self.scheduleVideoTrackReopenAfterRotation()
        })
    }
'''
replace_once(CTRL, old_transition, new_transition, 'transition transaction churn')

start = CTRL.read_text().find('    func refreshVideoSurface(reconfigure: Bool = false) {')
end = CTRL.read_text().find('    private func scheduleVideoTrackReopenAfterRotation() {', start)
if start < 0 or end < 0:
    raise SystemExit('refresh/scheduleSurfaceRefreshes method range not found')
text = CTRL.read_text()
replacement = '''    func refreshVideoSurface(reconfigure: Bool = false) {
        // Compatibility entry point for the SwiftUI wrapper/foreground path.
        // Geometry is intentionally deferred to viewDidLayoutSubviews().
        guard isViewLoaded else { return }
        view.setNeedsLayout()
        if reconfigure { command("video-reconfig", args: []) }
    }

    private func scheduleSurfaceRefreshes() {
        // Kept for compatibility with older call sites, but deliberately does
        // not perform delayed/repeated CALayer mutations.
        DispatchQueue.main.async { [weak self] in
            self?.view.setNeedsLayout()
        }
    }

'''
CTRL.write_text(text[:start] + replacement + text[end:])

# The video-track reopen workaround may still be required after rotation, but it
# must not mutate the CALayer outside a UIKit layout pass.
text = CTRL.read_text()
text = text.replace(
    '''            self.view.setNeedsLayout()
            self.view.layoutIfNeeded()
            self.refreshVideoSurface(reconfigure: true)
''',
    '''            self.view.setNeedsLayout()
            self.view.layoutIfNeeded()
            self.command("video-reconfig", args: [])
''',
    1,
)
text = text.replace(
    '''                self.setString("vid", value: String(videoTrackID))
                self.refreshVideoSurface(reconfigure: true)
''',
    '''                self.setString("vid", value: String(videoTrackID))
                self.view.setNeedsLayout()
                self.command("video-reconfig", args: [])
''',
    1,
)
CTRL.write_text(text)

replace_once(
    CTRL,
    '''    @objc private func willEnterForeground() {
        setString("vid", value: "auto")
        DispatchQueue.main.async { [weak self] in
            self?.refreshVideoSurface(reconfigure: true)
        }
    }

    @objc private func deviceOrientationDidChange() {
        // Never snapshot UIWindow bounds here. This notification commonly fires
        // before UIKit has swapped portrait/landscape dimensions.
        scheduleSurfaceRefreshes()
        scheduleVideoTrackReopenAfterRotation()
    }
''',
    '''    @objc private func willEnterForeground() {
        setString("vid", value: "auto")
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.view.setNeedsLayout()
            self.command("video-reconfig", args: [])
        }
    }

    @objc private func deviceOrientationDidChange() {
        // The interface transition callback performs the renderer reopen. Device
        // orientation notifications can fire without an interface rotation, so
        // they only request a normal UIKit layout pass.
        view.setNeedsLayout()
    }
''',
    'foreground/orientation layer writes',
)

replace_once(
    REP,
    '''        if let source = coordinator.pendingSource {
            coordinator.pendingSource = nil
            uiViewController.loadSource(source)
        }
        uiViewController.refreshVideoSurface()
        DispatchQueue.main.async { [weak uiViewController] in
            // Re-read the controller's live bounds on the next run-loop turn;
            // never replay a captured SwiftUI geometry value.
            uiViewController?.refreshVideoSurface()
        }
''',
    '''        if let source = coordinator.pendingSource {
            coordinator.pendingSource = nil
            uiViewController.loadSource(source)
        }
        // SwiftUI state updates must not mutate CAMetalLayer. UIKit's layout
        // cycle is the sole owner of Metal surface geometry.
''',
    'SwiftUI representable layer writes',
)

print('Applied v33 CoreAnimation/Metal stability patch')
