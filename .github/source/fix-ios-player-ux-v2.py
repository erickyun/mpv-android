from pathlib import Path

ROOT = Path('MPVTorBox')


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'Expected source pattern not found in {path}: {old[:140]!r}')
    path.write_text(text.replace(old, new, 1))


def replace_optional(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old in text:
        path.write_text(text.replace(old, new, 1))


# 1) Make the CAMetalLayer follow every size/orientation transition immediately.
controller = ROOT / 'Player' / 'MPVMetalViewController.swift'
replace_once(
    controller,
    '''        metalLayer.backgroundColor = UIColor.black.cgColor
        view.layer.addSublayer(metalLayer)
''',
    '''        metalLayer.backgroundColor = UIColor.black.cgColor
        metalLayer.needsDisplayOnBoundsChange = true
        metalLayer.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        view.layer.addSublayer(metalLayer)
'''
)
replace_once(
    controller,
    '''    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        becomeFirstResponder()
    }
''',
    '''    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        becomeFirstResponder()
        refreshVideoSurface(reconfigure: true)
    }
'''
)
replace_once(
    controller,
    '''    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        metalLayer.frame = view.bounds
        CATransaction.commit()
    }
''',
    '''    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        refreshVideoSurface()
    }

    override func viewSafeAreaInsetsDidChange() {
        super.viewSafeAreaInsetsDidChange()
        refreshVideoSurface()
    }

    override func viewWillTransition(
        to size: CGSize,
        with coordinator: UIViewControllerTransitionCoordinator
    ) {
        super.viewWillTransition(to: size, with: coordinator)
        coordinator.animate(alongsideTransition: { [weak self] _ in
            self?.refreshVideoSurface()
        }, completion: { [weak self] _ in
            self?.refreshVideoSurface(reconfigure: true)
        })
    }

    func refreshVideoSurface(reconfigure: Bool = false) {
        guard isViewLoaded else { return }
        let bounds = view.bounds
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

        if reconfigure {
            command("video-reconfig", args: [])
        }
    }
'''
)
replace_once(
    controller,
    '''        NotificationCenter.default.addObserver(
            self,
            selector: #selector(willEnterForeground),
            name: UIApplication.willEnterForegroundNotification,
            object: nil
        )
''',
    '''        NotificationCenter.default.addObserver(
            self,
            selector: #selector(willEnterForeground),
            name: UIApplication.willEnterForegroundNotification,
            object: nil
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(deviceOrientationDidChange),
            name: UIDevice.orientationDidChangeNotification,
            object: nil
        )
'''
)
replace_once(
    controller,
    '''    @objc private func willEnterForeground() {
        setString("vid", value: "auto")
    }
''',
    '''    @objc private func willEnterForeground() {
        setString("vid", value: "auto")
        DispatchQueue.main.async { [weak self] in
            self?.refreshVideoSurface(reconfigure: true)
        }
    }

    @objc private func deviceOrientationDidChange() {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.view.setNeedsLayout()
            self.view.layoutIfNeeded()
            self.refreshVideoSurface(reconfigure: true)
        }
    }
'''
)

representable = ROOT / 'Player' / 'MPVMetalPlayerView.swift'
replace_once(
    representable,
    '''        if let source = coordinator.pendingSource {
            coordinator.pendingSource = nil
            uiViewController.loadSource(source)
        }
''',
    '''        if let source = coordinator.pendingSource {
            coordinator.pendingSource = nil
            uiViewController.loadSource(source)
        }
        uiViewController.refreshVideoSurface()
'''
)

# 2) Any single tap in the video area reveals controls. Double-tap actions remain.
player = ROOT / 'Views' / 'PlayerScreen.swift'
replace_once(
    player,
    '''            }
            .allowsHitTesting(!controlsLocked)
        }
''',
    '''            }
            .allowsHitTesting(!controlsLocked)
            .simultaneousGesture(
                TapGesture(count: 1).onEnded {
                    guard !controlsLocked else { return }
                    showControlsTemporarily()
                }
            )
        }
'''
)

# 3) One stats menu: hidden or the complete information panel.
replace_once(
    player,
    '''    private func cycleStats() {
        statsLevel = (statsLevel + 1) % 4
        showControlsTemporarily()
    }
''',
    '''    private func cycleStats() {
        statsLevel = statsLevel == 0 ? 3 : 0
        showControlsTemporarily()
    }
'''
)

stats = ROOT / 'Views' / 'StatsOverlay.swift'
replace_once(
    stats,
    '''            .accessibilityLabel("Playback statistics level \\(level)")
''',
    '''            .accessibilityLabel("Complete playback statistics")
'''
)

# 4) iOS has no global Files permission. Request a copy of any selected item so
# cloud providers and external locations are selectable and readable by the app.
picker = ROOT / 'Views' / 'DocumentPicker.swift'
replace_once(
    picker,
    '''        let types: [UTType] = [.movie, .audio, .audiovisualContent, .mpeg4Movie, .quickTimeMovie, .data]
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: false)
''',
    '''        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.item], asCopy: true)
'''
)
replace_once(
    picker,
    '''        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.plainText, .text, .data], asCopy: false)
''',
    '''        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.item], asCopy: true)
'''
)

# 5) Explain the bundled extractor accurately; nothing is installed by the user.
advanced = ROOT / 'AdvancedSettingsView.swift'
replace_once(
    advanced,
    '''                  footer: { Text("YouTube and other supported website URLs are resolved locally. The Python module is downloaded on first use.") }
''',
    '''                  footer: { Text("yt-dlp is already bundled in this IPA—nothing else is installed. Enable this switch, paste a supported website page URL on the main screen, then tap Play URL. Direct media links and magnets bypass yt-dlp.") }
'''
)
replace_once(
    advanced,
    '''                    Text("Files → On My iPhone → MPV TorBox → MPVConfig")
''',
    '''                    Text("Files → On My iPhone → MPV → MPVConfig")
'''
)
replace_optional(advanced, '"Erase all MPV TorBox settings?"', '"Erase all MPV settings?"')

resolver = ROOT / 'YTDLPService.swift'
replace_once(
    resolver,
    '''        await status("Starting local yt-dlp…")
''',
    '''        await status("Starting built-in yt-dlp…")
'''
)

content = ROOT / 'ContentView.swift'
replace_once(content, '                    Text("MPV TorBox")\n', '                    Text("MPV")\n')
replace_once(
    content,
    '''                        Label("Three-level playback and frame-drop statistics", systemImage: "waveform.path.ecg")
''',
    '''                        Label("Complete playback and frame-drop statistics in one panel", systemImage: "waveform.path.ecg")
                        Label("Built-in yt-dlp: paste a supported website URL—no installation needed", systemImage: "link")
'''
)

# 6) The visible application name is MPV. Keep the product/bundle identifiers
# unchanged so this update installs over the previous sideloaded app.
info = ROOT / 'Info.plist'
replace_once(info, '<key>CFBundleDisplayName</key><string>MPV TorBox</string>', '<key>CFBundleDisplayName</key><string>MPV</string>')
replace_once(
    info,
    '<key>NSLocalNetworkUsageDescription</key><string>MPV TorBox connects to a TorrServer instance on your local network when enabled.</string>',
    '<key>NSLocalNetworkUsageDescription</key><string>MPV connects to a TorrServer instance on your local network when enabled.</string>'
)

project = Path('project.yml')
replace_once(project, '        MARKETING_VERSION: 1.1.1\n', '        MARKETING_VERSION: 1.2.0\n')
replace_once(project, '        CURRENT_PROJECT_VERSION: 11\n', '        CURRENT_PROJECT_VERSION: 12\n')

print('Applied rotation, controls, local-file, single-stats, yt-dlp help, and MPV naming fixes.')
