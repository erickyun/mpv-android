from pathlib import Path

ROOT = Path('MPVTorBox')
PLAYER = ROOT / 'Views' / 'PlayerScreen.swift'
METAL = ROOT / 'Player' / 'MPVMetalViewController.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))

# Center bottom toolbar in landscape when it fits; keep horizontal scrolling
# when the toolbar is wider than the current viewport.
replace_once(
    PLAYER,
    '''            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 18) {
                    trackMenu(kind: .video, icon: "film", label: "Video")
                    trackMenu(kind: .audio, icon: "waveform", label: "Audio")
                    subtitleMenu

                    if !coordinator.chapters.isEmpty {
                        chapterMenu
                    }

                    if let playlist, playlist.items.count > 1 {
                    Button {
                        showingPlaylistPicker = true
                        hideControlsTask?.cancel()
                    } label: {
                        toolbarLabel(icon: "list.bullet.rectangle", text: "Playlist")
                    }
                }

                Button { showingPlaybackSettings = true } label: {
                    toolbarLabel(icon: "slider.horizontal.3", text: "Playback")
                }

                    Button {
                        if coordinator.takeScreenshot() {
                            flash("Saved to Files → On My iPhone → MPV → Screenshots")
                        } else {
                            flash("Could not create the Screenshots folder")
                        }
                    } label: {
                        toolbarLabel(icon: "camera", text: "Shot")
                    }
                }
                .font(.caption)
            }
''',
    '''            GeometryReader { geometry in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 18) {
                        trackMenu(kind: .video, icon: "film", label: "Video")
                        trackMenu(kind: .audio, icon: "waveform", label: "Audio")
                        subtitleMenu

                        if !coordinator.chapters.isEmpty {
                            chapterMenu
                        }

                        if let playlist, playlist.items.count > 1 {
                            Button {
                                showingPlaylistPicker = true
                                hideControlsTask?.cancel()
                            } label: {
                                toolbarLabel(icon: "list.bullet.rectangle", text: "Playlist")
                            }
                        }

                        Button { showingPlaybackSettings = true } label: {
                            toolbarLabel(icon: "slider.horizontal.3", text: "Playback")
                        }

                        Button {
                            if coordinator.takeScreenshot() {
                                flash("Saved to Files → On My iPhone → MPV → Screenshots")
                            } else {
                                flash("Could not create the Screenshots folder")
                            }
                        } label: {
                            toolbarLabel(icon: "camera", text: "Shot")
                        }
                    }
                    .font(.caption)
                    .frame(minWidth: geometry.size.width, alignment: .center)
                }
            }
            .frame(height: 58)
''',
    'landscape bottom toolbar centering',
)

# Bind deband sliders directly to the observed coordinator state instead of an
# immutable snapshot value.
replace_once(
    PLAYER,
    '''                    if coordinator.deband.enabled {
                        debandSlider(title: "Iterations", value: coordinator.deband.iterations, range: 0...16, set: coordinator.setDebandIterations)
                        debandSlider(title: "Threshold", value: coordinator.deband.threshold, range: 0...4096, set: coordinator.setDebandThreshold)
                        debandSlider(title: "Range", value: coordinator.deband.range, range: 1...64, set: coordinator.setDebandRange)
                        debandSlider(title: "Grain", value: coordinator.deband.grain, range: 0...4096, set: coordinator.setDebandGrain)
                        Button("Reset deband defaults") { coordinator.resetDeband() }
                    }
''',
    '''                    if coordinator.deband.enabled {
                        debandSlider(title: "Iterations", value: { coordinator.deband.iterations }, range: 0...16, set: coordinator.setDebandIterations)
                        debandSlider(title: "Threshold", value: { coordinator.deband.threshold }, range: 0...4096, set: coordinator.setDebandThreshold)
                        debandSlider(title: "Range", value: { coordinator.deband.range }, range: 1...64, set: coordinator.setDebandRange)
                        debandSlider(title: "Grain", value: { coordinator.deband.grain }, range: 0...4096, set: coordinator.setDebandGrain)
                        Button("Reset deband defaults") { coordinator.resetDeband() }
                    }
''',
    'live deband sheet bindings',
)
replace_once(
    PLAYER,
    '''    private func debandSlider(
        title: String,
        value: Int,
        range: ClosedRange<Int>,
        set: @escaping (Int) -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title)
                Spacer()
                Text(String(value)).monospacedDigit().foregroundStyle(.secondary)
            }
            Slider(
                value: Binding(
                    get: { Double(value) },
                    set: { set(Int($0.rounded())) }
                ),
                in: Double(range.lowerBound)...Double(range.upperBound),
                step: 1
            )
        }
    }
''',
    '''    private func debandSlider(
        title: String,
        value: @escaping () -> Int,
        range: ClosedRange<Int>,
        set: @escaping (Int) -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title)
                Spacer()
                Text(String(value())).monospacedDigit().foregroundStyle(.secondary)
            }
            Slider(
                value: Binding(
                    get: { Double(value()) },
                    set: { set(min(max(Int($0.rounded()), range.lowerBound), range.upperBound)) }
                ),
                in: Double(range.lowerBound)...Double(range.upperBound),
                step: 1
            )
        }
    }
''',
    'dynamic deband slider helper',
)

replace_once(
    METAL,
    '    private var embeddedChapters: [MPVChapter] = []\n',
    '    private var embeddedChapters: [MPVChapter] = []\n    private var currentDebandSettings = MPVDebandSettings()\n',
    'deband state cache',
)

# Use mpv's documented runtime `set` command and publish optimistic values
# immediately, followed by an effective-property readback.
replace_once(
    METAL,
    '''    func setDebandEnabled(_ value: Bool) {
        setString("deband", value: value ? "yes" : "no")
        publishDeband()
    }

    func setDebandIterations(_ value: Int) {
        setString("deband-iterations", value: String(min(max(value, 0), 16)))
        publishDeband()
    }

    func setDebandThreshold(_ value: Int) {
        setString("deband-threshold", value: String(min(max(value, 0), 4096)))
        publishDeband()
    }

    func setDebandRange(_ value: Int) {
        setString("deband-range", value: String(min(max(value, 1), 64)))
        publishDeband()
    }

    func setDebandGrain(_ value: Int) {
        setString("deband-grain", value: String(min(max(value, 0), 4096)))
        publishDeband()
    }

    func resetDeband() {
        setString("deband", value: "yes")
        setString("deband-iterations", value: "1")
        setString("deband-threshold", value: "48")
        setString("deband-range", value: "16")
        setString("deband-grain", value: "32")
        publishDeband()
    }
''',
    '''    func setDebandEnabled(_ value: Bool) {
        applyDebandOption("deband", value: value ? "yes" : "no") { $0.enabled = value }
    }

    func setDebandIterations(_ value: Int) {
        let clamped = min(max(value, 0), 16)
        applyDebandOption("deband-iterations", value: String(clamped)) { $0.iterations = clamped }
    }

    func setDebandThreshold(_ value: Int) {
        let clamped = min(max(value, 0), 4096)
        applyDebandOption("deband-threshold", value: String(clamped)) { $0.threshold = clamped }
    }

    func setDebandRange(_ value: Int) {
        let clamped = min(max(value, 1), 64)
        applyDebandOption("deband-range", value: String(clamped)) { $0.range = clamped }
    }

    func setDebandGrain(_ value: Int) {
        let clamped = min(max(value, 0), 4096)
        applyDebandOption("deband-grain", value: String(clamped)) { $0.grain = clamped }
    }

    func resetDeband() {
        let settings = MPVDebandSettings(enabled: true, iterations: 1, threshold: 48, range: 16, grain: 32)
        currentDebandSettings = settings
        publishDebandSettings(settings)
        command("set", args: ["deband", "yes"])
        command("set", args: ["deband-iterations", "1"])
        command("set", args: ["deband-threshold", "48"])
        command("set", args: ["deband-range", "16"])
        command("set", args: ["deband-grain", "32"])
        scheduleDebandReadback()
    }
''',
    'runtime deband commands',
)

replace_once(
    METAL,
    '''    private func publishDeband() {
        let enabledText = optionString("deband", fallback: "no").lowercased()
        let settings = MPVDebandSettings(
            enabled: ["yes", "true", "1"].contains(enabledText),
            iterations: Int(optionString("deband-iterations", fallback: "1")) ?? 1,
            threshold: Int(optionString("deband-threshold", fallback: "48")) ?? 48,
            range: Int(optionString("deband-range", fallback: "16")) ?? 16,
            grain: Int(optionString("deband-grain", fallback: "32")) ?? 32
        )
        Task { @MainActor [weak self] in self?.playDelegate?.playerDidUpdateDeband(settings) }
    }
''',
    '''    private func applyDebandOption(
        _ name: String,
        value: String,
        update: (inout MPVDebandSettings) -> Void
    ) {
        update(&currentDebandSettings)
        publishDebandSettings(currentDebandSettings)
        command("set", args: [name, value])
        scheduleDebandReadback()
    }

    private func scheduleDebandReadback() {
        eventQueue.asyncAfter(deadline: .now() + 0.08) { [weak self] in self?.publishDeband() }
    }

    private func publishDebandSettings(_ settings: MPVDebandSettings) {
        Task { @MainActor [weak self] in self?.playDelegate?.playerDidUpdateDeband(settings) }
    }

    private func publishDeband() {
        let enabledText = runtimeOptionString("deband", fallback: currentDebandSettings.enabled ? "yes" : "no").lowercased()
        let settings = MPVDebandSettings(
            enabled: ["yes", "true", "1"].contains(enabledText),
            iterations: Int(runtimeOptionString("deband-iterations", fallback: String(currentDebandSettings.iterations))) ?? currentDebandSettings.iterations,
            threshold: Int(runtimeOptionString("deband-threshold", fallback: String(currentDebandSettings.threshold))) ?? currentDebandSettings.threshold,
            range: Int(runtimeOptionString("deband-range", fallback: String(currentDebandSettings.range))) ?? currentDebandSettings.range,
            grain: Int(runtimeOptionString("deband-grain", fallback: String(currentDebandSettings.grain))) ?? currentDebandSettings.grain
        )
        currentDebandSettings = settings
        publishDebandSettings(settings)
    }
''',
    'deband optimistic state and readback',
)

replace_once(
    METAL,
    '''    private func optionString(_ name: String, fallback: String = "—") -> String {
        let value = getString("options/\\(name)") ?? getString(name)
        guard let value, !value.isEmpty else { return fallback }
        return value
    }
''',
    '''    private func runtimeOptionString(_ name: String, fallback: String = "—") -> String {
        let value = getString(name) ?? getString("options/\\(name)")
        guard let value, !value.isEmpty else { return fallback }
        return value
    }

    private func optionString(_ name: String, fallback: String = "—") -> String {
        runtimeOptionString(name, fallback: fallback)
    }
''',
    'prefer effective runtime property readback',
)

print('Applied v21: centered landscape toolbar and reliable live deband threshold/range/grain controls.')
