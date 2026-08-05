from pathlib import Path

ROOT = Path('MPVTorBox')


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'Expected source pattern not found in {path}: {old[:100]!r}')
    path.write_text(text.replace(old, new, 1))


# A real launch storyboard is required for modern full-screen sizing on notched iPhones.
info = ROOT / 'Info.plist'
replace_once(
    info,
    '    <key>UILaunchScreen</key><dict/>\n',
    '    <key>UILaunchStoryboardName</key><string>LaunchScreen</string>\n'
)

storyboard = ROOT / 'LaunchScreen.storyboard'
storyboard.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<document type="com.apple.InterfaceBuilder3.CocoaTouch.Storyboard.XIB" version="3.0" toolsVersion="23094" targetRuntime="iOS.CocoaTouch" propertyAccessControl="none" useAutolayout="YES" launchScreen="YES" useTraitCollections="YES" useSafeAreas="YES" colorMatched="YES" initialViewController="01J-lp-oVM">
    <device id="retina6_12" orientation="portrait" appearance="dark"/>
    <dependencies>
        <deployment identifier="iOS"/>
        <plugIn identifier="com.apple.InterfaceBuilder.IBCocoaTouchPlugin" version="23084"/>
        <capability name="Safe area layout guides" minToolsVersion="9.0"/>
        <capability name="System colors in document resources" minToolsVersion="11.0"/>
        <capability name="documents saved in the Xcode 8 format" minToolsVersion="8.0"/>
    </dependencies>
    <scenes>
        <scene sceneID="EHf-IW-A2E">
            <objects>
                <viewController id="01J-lp-oVM" sceneMemberID="viewController">
                    <view key="view" contentMode="scaleToFill" id="Ze5-6b-2t3">
                        <rect key="frame" x="0.0" y="0.0" width="393" height="852"/>
                        <autoresizingMask key="autoresizingMask" widthSizable="YES" heightSizable="YES"/>
                        <color key="backgroundColor" systemColor="systemBackgroundColor"/>
                        <viewLayoutGuide key="safeArea" id="6Tk-OE-BBY"/>
                    </view>
                </viewController>
                <placeholder placeholderIdentifier="IBFirstResponder" id="iYj-Kq-Ea1" userLabel="First Responder" sceneMemberID="firstResponder"/>
            </objects>
            <point key="canvasLocation" x="53" y="375"/>
        </scene>
    </scenes>
    <resources>
        <systemColor name="systemBackgroundColor">
            <color white="0.0" alpha="1" colorSpace="custom" customColorSpace="genericGamma22GrayColorSpace"/>
        </systemColor>
    </resources>
</document>
''')

# Keychain survives uninstall. Add a service-wide erase operation.
keychain = ROOT / 'KeychainStore.swift'
replace_once(
    keychain,
    '''    static func write(_ value: String, account: String) throws {''',
    '''    static func deleteAll() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service
        ]
        SecItemDelete(query as CFDictionary)
    }

    static func write(_ value: String, account: String) throws {'''
)

# Detect a genuinely fresh install via a UserDefaults marker. The previous build
# had no marker, so installing this update once also clears stale legacy settings.
settings = ROOT / 'AppSettings.swift'
replace_once(
    settings,
    '''        static let ytdlpEnabled = "ytdlp_enabled"\n''',
    '''        static let ytdlpEnabled = "ytdlp_enabled"
        static let installMarker = "installation_marker_v1"
'''
)
replace_once(
    settings,
    '''    init() {
        if defaults.object(forKey: Keys.torBoxEnabled) == nil { defaults.set(true, forKey: Keys.torBoxEnabled) }
''',
    '''    init() {
        if !defaults.bool(forKey: Keys.installMarker) {
            KeychainStore.deleteAll()
            MPVConfigManager.reset()
            if let bundleIdentifier = Bundle.main.bundleIdentifier {
                defaults.removePersistentDomain(forName: bundleIdentifier)
            }
            defaults.set(true, forKey: Keys.installMarker)
        }

        if defaults.object(forKey: Keys.torBoxEnabled) == nil { defaults.set(true, forKey: Keys.torBoxEnabled) }
'''
)
replace_once(
    settings,
    '''    func snapshot() -> ProviderSettings {
''',
    '''    func resetAllSettings() {
        KeychainStore.deleteAll()
        MPVConfigManager.reset()
        if let bundleIdentifier = Bundle.main.bundleIdentifier {
            defaults.removePersistentDomain(forName: bundleIdentifier)
        }
        defaults.set(true, forKey: Keys.installMarker)

        torBoxEnabled = true
        torrServerEnabled = false
        torrServerAddress = "http://127.0.0.1:8090"
        ytdlpEnabled = true
        torBoxAPIKey = ""
    }

    func snapshot() -> ProviderSettings {
'''
)

# Reset custom mpv.conf/input.conf together with provider settings.
config = ROOT / 'Utilities' / 'MPVConfigManager.swift'
replace_once(
    config,
    '''enum MPVConfigManager {
    static func prepare() -> MPVConfigPaths {
''',
    '''enum MPVConfigManager {
    static func reset() {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let directory = documents.appendingPathComponent("MPVConfig", isDirectory: true)
        try? FileManager.default.removeItem(at: directory)
    }

    static func prepare() -> MPVConfigPaths {
'''
)

# Expose a manual reset button too, useful for sideloaders that install over the app.
advanced = ROOT / 'AdvancedSettingsView.swift'
replace_once(
    advanced,
    '''    @State private var saveMessage: String?
''',
    '''    @State private var saveMessage: String?
    @State private var showingResetConfirmation = false
'''
)
replace_once(
    advanced,
    '''                Section("Provider priority") {
                    Text("TorBox → TorrServer fallback → yt-dlp → Direct media URL")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                if let saveMessage {
''',
    '''                Section("Provider priority") {
                    Text("TorBox → TorrServer fallback → yt-dlp → Direct media URL")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Section("Storage and reset") {
                    Text("Provider switches and the TorrServer address are stored in app preferences. The TorBox API key is stored in iOS Keychain.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Button("Erase all settings", role: .destructive) {
                        showingResetConfirmation = true
                    }
                }

                if let saveMessage {
'''
)
replace_once(
    advanced,
    '''            .onAppear { apiKey = settings.torBoxAPIKey }
''',
    '''            .onAppear { apiKey = settings.torBoxAPIKey }
            .confirmationDialog(
                "Erase all MPV TorBox settings?",
                isPresented: $showingResetConfirmation,
                titleVisibility: .visible
            ) {
                Button("Erase all settings", role: .destructive) {
                    settings.resetAllSettings()
                    apiKey = ""
                    saveMessage = "All settings and custom MPV configuration were erased."
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This removes the TorBox API key, provider settings, TorrServer address, mpv.conf, and input.conf.")
            }
'''
)

# Bump metadata so sideloaders do not confuse this IPA with the prior build.
project = Path('project.yml')
replace_once(project, '        MARKETING_VERSION: 1.1.0\n', '        MARKETING_VERSION: 1.1.1\n')
replace_once(project, '        CURRENT_PROJECT_VERSION: 10\n', '        CURRENT_PROJECT_VERSION: 11\n')

print('Applied full-screen launch and reinstall-reset fixes.')
