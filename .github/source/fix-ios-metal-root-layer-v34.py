from pathlib import Path

ROOT = Path('MPVTorBox')
CTRL = ROOT / 'Player' / 'MPVMetalViewController.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# Use the UIView's own backing layer as the mpv/MoltenVK presentation surface.
# This removes the separately-owned CAMetalLayer sublayer that CoreAnimation was
# observed freeing while committing transactions in the device crash report.
replace_once(
    CTRL,
    '''final class MPVMetalViewController: UIViewController {
    private var metalLayer = MetalLayer()
''',
    '''private final class MPVMetalHostView: UIView {
    override class var layerClass: AnyClass { MetalLayer.self }
}

final class MPVMetalViewController: UIViewController {
    private var metalLayer: MetalLayer!
''',
    'root Metal host view',
)

replace_once(
    CTRL,
    '''    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        view.isOpaque = true

        metalLayer.contentsScale = UIScreen.main.nativeScale
        metalLayer.framebufferOnly = true
        metalLayer.backgroundColor = UIColor.black.cgColor
        // CAMetalLayer is presented by MoltenVK/mpv. Do not opt it into UIKit's
        // display invalidation/timing path; that creates extra CoreAnimation
        // transactions while the renderer owns the drawable lifecycle.
        metalLayer.needsDisplayOnBoundsChange = false
        view.layer.addSublayer(metalLayer)

        setupMPV()
''',
    '''    override func loadView() {
        let host = MPVMetalHostView(frame: .zero)
        host.backgroundColor = .black
        host.isOpaque = true
        host.contentScaleFactor = UIScreen.main.nativeScale
        view = host
        guard let layer = host.layer as? MetalLayer else {
            preconditionFailure("MPVMetalHostView did not create MetalLayer")
        }
        metalLayer = layer
    }

    override func viewDidLoad() {
        super.viewDidLoad()

        // The Metal surface is now UIView's backing layer. UIKit owns its frame
        // and CoreAnimation lifetime; mpv/MoltenVK only owns presentation.
        metalLayer.framebufferOnly = true
        metalLayer.backgroundColor = UIColor.black.cgColor
        metalLayer.needsDisplayOnBoundsChange = false

        setupMPV()
''',
    'replace Metal sublayer with UIView backing layer',
)

replace_once(
    CTRL,
    '''    override func viewDidLayoutSubviews() {
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
''',
    '''    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        // No manual CAMetalLayer frame/drawableSize transaction here. Because
        // MetalLayer is the UIView backing layer, UIKit updates its geometry as
        // part of the normal view layout transaction.
        let scale = view.window?.screen.nativeScale ?? UIScreen.main.nativeScale
        if view.contentScaleFactor != scale {
            view.contentScaleFactor = scale
        }
    }
''',
    'remove manual backing-layer transactions',
)

# Pass the layer object's address explicitly as the mpv wid integer instead of
# relying on the in-memory representation of a Swift reference variable.
replace_once(
    CTRL,
    '''        check(mpv_set_option(context, "wid", MPV_FORMAT_INT64, &metalLayer))
''',
    '''        var windowID = Int64(Int(bitPattern: Unmanaged.passUnretained(metalLayer).toOpaque()))
        check(mpv_set_option(context, "wid", MPV_FORMAT_INT64, &windowID))
''',
    'explicit MetalLayer wid pointer',
)

# libmpv holds the wid and an unretained wakeup callback. Tear both down while
# the controller still owns its UIView/MetalLayer, before Swift destroys stored
# properties. This prevents stale callbacks or renderer references from touching
# a layer that CoreAnimation is already releasing.
replace_once(
    CTRL,
    '''    deinit {
        updateTimer?.cancel()
        NotificationCenter.default.removeObserver(self)
        if let mpv { mpv_terminate_destroy(mpv) }
    }
''',
    '''    deinit {
        updateTimer?.setEventHandler {}
        updateTimer?.cancel()
        updateTimer = nil
        NotificationCenter.default.removeObserver(self)

        if let context = mpv {
            mpv_set_wakeup_callback(context, nil, nil)
            mpv = nil
            mpv_terminate_destroy(context)
        }
    }
''',
    'safe mpv teardown before MetalLayer release',
)

print('Applied v34 root Metal backing layer and safe mpv/layer teardown')
