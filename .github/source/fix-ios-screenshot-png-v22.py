from pathlib import Path

ROOT = Path('MPVTorBox')
PLAYER = ROOT / 'Views' / 'PlayerScreen.swift'
METAL = ROOT / 'Player' / 'MPVMetalViewController.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label}: anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))

# Do not claim success before libmpv has actually written the file. Keep these
# replacements independent of the toolbar's indentation/layout from v21.
replace_once(
    PLAYER,
    'flash("Saved to Files → On My iPhone → MPV → Screenshots")',
    'flash("Saving PNG…")',
    'screenshot success label',
)
replace_once(
    PLAYER,
    'flash("Could not create the Screenshots folder")',
    'flash("Could not start PNG screenshot")',
    'screenshot failure label',
)

# Force a real PNG, include subtitles, verify that the file appears, and retry
# using the renderer path if software screenshot conversion did not write it.
replace_once(
    METAL,
    '''    func takeScreenshot() -> Bool {
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let directory = documents.appendingPathComponent("Screenshots", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            return false
        }

        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss-SSS"
        let file = directory.appendingPathComponent("MPV_\(formatter.string(from: Date())).png")
        command("screenshot-to-file", args: [file.path, "video"])
        return true
    }
''',
    '''    func takeScreenshot() -> Bool {
        guard mpv != nil else { return false }

        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let directory = documents.appendingPathComponent("Screenshots", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            return false
        }

        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss-SSS"
        let file = directory.appendingPathComponent("MPV_\(formatter.string(from: Date())).png")

        // screenshot-to-file guesses the encoder from the extension, but keep
        // these explicit too so normal screenshot bindings are PNG as well.
        setString("screenshot-format", value: "png")
        setString("screenshot-high-bit-depth", value: "no")
        setString("screenshot-png-compression", value: "4")

        // MPVKit uses gpu-next/MoltenVK on iOS. Start with software conversion,
        // which avoids reinitializing the video renderer just for a screenshot.
        setString("screenshot-sw", value: "yes")
        let accepted = command("screenshot-to-file", args: [file.path, "subtitles"]) >= 0
        guard accepted else { return false }

        verifyPNGWrite(file, attempt: 0, usedRendererFallback: false)
        return true
    }

    private func verifyPNGWrite(_ file: URL, attempt: Int, usedRendererFallback: Bool) {
        eventQueue.asyncAfter(deadline: .now() + 0.20) { [weak self] in
            guard let self else { return }

            if let attributes = try? FileManager.default.attributesOfItem(atPath: file.path),
               let size = attributes[.size] as? NSNumber,
               size.intValue > 8 {
                self.command("show-text", args: ["PNG saved → Files / MPV / Screenshots / \(file.lastPathComponent)", "3500"])
                return
            }

            if attempt < 7 {
                self.verifyPNGWrite(file, attempt: attempt + 1, usedRendererFallback: usedRendererFallback)
                return
            }

            // If the software scaler path did not produce a file, retry once
            // through gpu-next. This covers renderer/build-specific screenshot
            // limitations without making the user choose a mode manually.
            if !usedRendererFallback {
                self.setString("screenshot-sw", value: "no")
                let retryAccepted = self.command("screenshot-to-file", args: [file.path, "subtitles"]) >= 0
                if retryAccepted {
                    self.verifyPNGWrite(file, attempt: 0, usedRendererFallback: true)
                    return
                }
            }

            self.command("show-text", args: ["PNG screenshot failed", "3500"])
        }
    }
''',
    'reliable PNG screenshot',
)

# Return the actual libmpv command status so screenshot startup failures can be
# detected instead of always reporting success.
replace_once(
    METAL,
    '''    private func command(_ name: String, args: [String]) {
        guard let mpv else { return }
        let strings = [name] + args
        var pointers: [UnsafePointer<CChar>?] = strings.map { value in
            guard let duplicated = strdup(value) else { return nil }
            return UnsafePointer<CChar>(duplicated)
        }
        pointers.append(nil)
        defer {
            for pointer in pointers.compactMap({ $0 }) { free(UnsafeMutablePointer(mutating: pointer)) }
        }
        pointers.withUnsafeMutableBufferPointer { check(mpv_command(mpv, $0.baseAddress)) }
    }
''',
    '''    @discardableResult
    private func command(_ name: String, args: [String]) -> CInt {
        guard let mpv else { return -1 }
        let strings = [name] + args
        var pointers: [UnsafePointer<CChar>?] = strings.map { value in
            guard let duplicated = strdup(value) else { return nil }
            return UnsafePointer<CChar>(duplicated)
        }
        pointers.append(nil)
        defer {
            for pointer in pointers.compactMap({ $0 }) { free(UnsafeMutablePointer(mutating: pointer)) }
        }
        return pointers.withUnsafeMutableBufferPointer { buffer in
            let status = mpv_command(mpv, buffer.baseAddress)
            check(status)
            return status
        }
    }
''',
    'command result status',
)

print('Applied v22: verified PNG screenshots with subtitles and software/GPU fallback.')
