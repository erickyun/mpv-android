from pathlib import Path

ROOT = Path('MPVTorBox')
METAL = ROOT / 'Player' / 'MPVMetalViewController.swift'

text = METAL.read_text()
start = text.find('    func takeScreenshot() -> Bool {\n')
end = text.find('    @objc private func didEnterBackground()', start)
if start < 0 or end < 0:
    raise SystemExit('screenshot block anchors not found')

replacement = '''    func takeScreenshot() -> Bool {
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
        let file = directory.appendingPathComponent("MPV_\\(formatter.string(from: Date())).png")

        // screenshot-to-file can be rejected by libmpv render embedding on iOS.
        // screenshot-raw is explicitly intended for client API users, so copy
        // the frame from mpv memory and let UIKit encode a real PNG instead.
        eventQueue.async { [weak self] in
            guard let self else { return }
            if self.captureRawPNG(to: file, flags: "subtitles") ||
               self.captureRawPNG(to: file, flags: "video") {
                self.command("show-text", args: ["PNG saved → Files / MPV / Screenshots / \\(file.lastPathComponent)", "3500"])
            } else {
                self.command("show-text", args: ["PNG screenshot failed", "3500"])
            }
        }
        return true
    }

    private func captureRawPNG(to file: URL, flags: String) -> Bool {
        guard let mpv else { return false }

        let strings = ["screenshot-raw", flags, "rgba"]
        var pointers: [UnsafePointer<CChar>?] = strings.map { value in
            guard let duplicated = strdup(value) else { return nil }
            return UnsafePointer<CChar>(duplicated)
        }
        pointers.append(nil)
        defer {
            for pointer in pointers.compactMap({ $0 }) {
                free(UnsafeMutablePointer(mutating: pointer))
            }
        }

        var result = mpv_node()
        let status = pointers.withUnsafeMutableBufferPointer { buffer in
            mpv_command_ret(mpv, buffer.baseAddress, &result)
        }
        guard status >= 0 else {
            print("screenshot-raw error: \\(String(cString: mpv_error_string(status)))")
            return false
        }
        defer { mpv_free_node_contents(&result) }

        guard result.format == MPV_FORMAT_NODE_MAP,
              let list = result.u.list,
              let keys = list.pointee.keys,
              let values = list.pointee.values else {
            return false
        }

        var width: Int64?
        var height: Int64?
        var stride: Int64?
        var format: String?
        var rgbaData: Data?

        for index in 0..<Int(list.pointee.num) {
            guard let keyPointer = keys[index] else { continue }
            let key = String(cString: keyPointer)
            let node = values[index]

            switch key {
            case "w" where node.format == MPV_FORMAT_INT64:
                width = node.u.int64
            case "h" where node.format == MPV_FORMAT_INT64:
                height = node.u.int64
            case "stride" where node.format == MPV_FORMAT_INT64:
                stride = node.u.int64
            case "format" where node.format == MPV_FORMAT_STRING:
                if let pointer = node.u.string { format = String(cString: pointer) }
            case "data" where node.format == MPV_FORMAT_BYTE_ARRAY:
                if let byteArray = node.u.ba, let dataPointer = byteArray.pointee.data {
                    rgbaData = Data(bytes: dataPointer, count: Int(byteArray.pointee.size))
                }
            default:
                break
            }
        }

        guard let width, let height, let stride, let rgbaData,
              width > 0, height > 0,
              format?.lowercased() == "rgba" else {
            return false
        }

        let w = Int(width)
        let h = Int(height)
        let sourceStride = Int(stride)
        let rowBytes = w * 4
        guard w > 0, h > 0, rowBytes > 0, abs(sourceStride) >= rowBytes else { return false }

        var packed = Data(count: rowBytes * h)
        let copied = rgbaData.withUnsafeBytes { sourceBuffer -> Bool in
            guard let sourceBase = sourceBuffer.baseAddress else { return false }
            return packed.withUnsafeMutableBytes { destinationBuffer -> Bool in
                guard let destinationBase = destinationBuffer.baseAddress else { return false }
                for y in 0..<h {
                    let sourceOffset = sourceStride >= 0
                        ? y * sourceStride
                        : (h - 1 - y) * (-sourceStride)
                    guard sourceOffset >= 0,
                          sourceOffset + rowBytes <= sourceBuffer.count else { return false }
                    memcpy(
                        destinationBase.advanced(by: y * rowBytes),
                        sourceBase.advanced(by: sourceOffset),
                        rowBytes
                    )
                }
                return true
            }
        }
        guard copied else { return false }

        guard let provider = CGDataProvider(data: packed as CFData) else { return false }
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let bitmapInfo = CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue)
        guard let image = CGImage(
            width: w,
            height: h,
            bitsPerComponent: 8,
            bitsPerPixel: 32,
            bytesPerRow: rowBytes,
            space: colorSpace,
            bitmapInfo: bitmapInfo,
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        ), let png = UIImage(cgImage: image).pngData() else {
            return false
        }

        do {
            try png.write(to: file, options: .atomic)
            return png.count > 8
        } catch {
            print("PNG write error: \\(error)")
            return false
        }
    }

'''

METAL.write_text(text[:start] + replacement + text[end:])
print('Applied v23: libmpv screenshot-raw to UIKit PNG encoder.')
