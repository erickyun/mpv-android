from pathlib import Path

R = Path("MPVTorBox/RemoteZIPRangeClient.swift")
M = Path("MPVTorBox/MPVArchiveProtocol.swift")
text = R.read_text()

# The cache limit is not a fill target. Retain the 96 MiB forward window
# PLUS some previous bytes so short reverse seeks can use cached ZIP data.
anchor = "    private let maxCachedBlocks = 96 // <=96 MiB of compressed ZIP bytes"
assert anchor in text, "v53: cache capacity anchor missing"
text = text.replace(anchor,
    "    private let maxCachedBlocks = 160 // 96 MiB ahead plus up to 64 MiB history",
    1)

anchor = "    private var pendingPrefetch: Set<Int64> = []\n"
assert anchor in text
text = text.replace(anchor, anchor + '''    private var failedPrefetch: Set<Int64> = []
    private var prefetchNextBlock: Int64 = -1
    private var prefetchEndByte: Int64 = 0
    private var activePrefetch = 0
    private let aheadBlocks: Int64 = 96
    private let maxConcurrentPrefetch = 3
''', 1)

start = text.find("    /// Keep one or two compressed blocks ahead of the demuxer.")
end = text.find("    func read(at start: Int64, count: Int) throws -> Data {",start)
assert start >= 0 and end > start, "v53: old 2 MiB prefetch not found"

new = r'''    /// Called AFTER a foreground media read begins (or after an explicit
    /// user seek). Playback never waits for this 96 MiB window to fill.
    ///
    /// Values are compressed ZIP offsets for DEFLATE and raw media offsets for
    /// STORE. The requested end bound prevents downloading beyond the movie
    /// for STORE and beyond EOF for compressed ZIP entries.
    func scheduleReadAhead(after offset: Int64, through end: Int64) {
        guard fileSize > 0, offset >= 0, end > offset else { return }
        let cappedEnd = min(end, fileSize)
        let candidate = offset / blockSize
        lock.lock()
        // Reprioritize when the user seeks far away, including backwards.
        if prefetchNextBlock >= 0,
           (candidate < prefetchNextBlock || candidate > prefetchNextBlock + 8) {
            failedPrefetch.removeAll()
        }
        prefetchNextBlock = candidate
        prefetchEndByte = cappedEnd
        lock.unlock()
        pumpReadAhead()
    }

    /// Three background requests, not 96 simultaneous requests. Each
    /// completion schedules the next missing 1 MiB block until the forward
    /// 96 MiB target is filled. The foreground mpv read never waits for them.
    private func pumpReadAhead() {
        while true {
            lock.lock()
            let base = prefetchNextBlock
            let cappedEnd = prefetchEndByte
            guard activePrefetch < maxConcurrentPrefetch,
                  base >= 0,
                  cappedEnd > base * blockSize else {
                lock.unlock()
                return
            }
            let lastMediaBlock = (cappedEnd - 1) / blockSize
            let lastWantedBlock = min(lastMediaBlock, base + aheadBlocks - 1)
            var next: Int64? = nil
            if lastWantedBlock >= base {
                for block in base...lastWantedBlock {
                    if blocks[block] == nil
                        && !pendingPrefetch.contains(block)
                        && !failedPrefetch.contains(block) {
                        next = block
                        break
                    }
                }
            }
            guard let block = next else {
                lock.unlock()
                return
            }
            pendingPrefetch.insert(block)
            activePrefetch += 1
            lock.unlock()

            let firstByte = block * blockSize
            let lastByte = min(firstByte + blockSize, fileSize) - 1
            prefetchQueue.async { [weak self] in
                guard let self else { return }
                let data = try? self.request(start: firstByte, end: lastByte).0
                self.lock.lock()
                if let data {
                    if self.blocks[block] == nil {
                        self.blocks[block] = data
                        self.order.removeAll { $0 == block }
                        self.order.append(block)
                        while self.order.count > self.maxCachedBlocks {
                            let evict = self.order.removeFirst()
                            self.blocks.removeValue(forKey: evict)
                        }
                    }
                } else {
                    // Avoid an infinite background retry storm on a bad server.
                    // Foreground media reads can retry errors normally.
                    self.failedPrefetch.insert(block)
                }
                self.pendingPrefetch.remove(block)
                self.activePrefetch -= 1
                self.lock.unlock()
                self.pumpReadAhead()
            }
        }
    }

'''
text = text[:start] + new + text[end:]
# Only explicit media paths schedule prefetch: ZIP header/central-directory
# probes must not accidentally fetch the entire 96 MiB ZIP tail.
s=text.find("    func read(at start: Int64, count: Int) throws -> Data {")
e=text.find("    private static func u16",s)
assert s >= 0 and e > s
segment=text[s:e]
assert "        prefetch(after: start + desired)\n" in segment
segment=segment.replace("        prefetch(after: start + desired)\n","",1)
text=text[:s]+segment+text[e:]
R.write_text(text)

mpv=M.read_text()
needle = '''                position += Int64(bytes.count)
                return Int64(bytes.count)
'''
assert needle in mpv, "v53: direct STORE read anchor missing"
mpv=mpv.replace(needle,'''                position += Int64(bytes.count)
                if !bytes.isEmpty {
                    remote.scheduleReadAhead(
                        after: start + position,
                        through: start + source.size
                    )
                }
                return Int64(bytes.count)
''',1)

# ZIP compressed DEFLATE entry: libarchive reads compressed bytes via the
# remote cursor, so read-ahead follows that compressed-byte position.
needle = '''        if n > 0 { position += Int64(n) }
        return Int64(n)
'''
assert needle in mpv, "v53: libarchive reader anchor missing"
mpv=mpv.replace(needle,'''        if n > 0 {
            position += Int64(n)
            if let remote = source.remote, let cursor = remoteCursor {
                remote.scheduleReadAhead(
                    after: cursor.currentOffset,
                    through: remote.fileSize
                )
            }
        }
        return Int64(n)
''',1)

needle = '''        if source.remote != nil, source.storedOffset != nil {
            position = target
            return target
        }
'''
assert needle in mpv, "v53: STORE seeking anchor missing"
mpv=mpv.replace(needle,'''        if let remote = source.remote, let start = source.storedOffset {
            position = target
            remote.scheduleReadAhead(
                after: start + target,
                through: start + source.size
            )
            return target
        }
''',1)
M.write_text(mpv)

cursor = R.read_text()
needle = '''    init(client: RemoteZIPRangeClient) { self.client = client }
    deinit { block.deallocate() }
'''
assert needle in cursor, "v53: remote cursor anchor missing"
cursor=cursor.replace(needle,'''    init(client: RemoteZIPRangeClient) { self.client = client }
    var currentOffset: Int64 { location }
    deinit { block.deallocate() }
''',1)
R.write_text(cursor)
print("v53: instant movie startup, 96MiB forward target, 160MiB LRU, 3 background Range workers, prioritized seeks")
