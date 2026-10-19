from pathlib import Path

file = Path("MPVTorBox/RemoteZIPRangeClient.swift")
text = file.read_text()
anchor = "    private var order: [Int64] = []\n"
if anchor not in text:
    raise SystemExit("ZIP prefetch: cache registry anchor not found")
text = text.replace(anchor, anchor+'''    private var pendingPrefetch: Set<Int64> = []
    private let prefetchQueue = DispatchQueue(
        label: "mpv.iosarchive.range-prefetch",
        qos: .utility,
        attributes: .concurrent
    )
''', 1)
anchor = "    func read(at start: Int64, count: Int) throws -> Data {\n"
if anchor not in text:
    raise SystemExit("ZIP prefetch: read method not found")
helper=r'''    /// Keep one or two compressed blocks ahead of the demuxer. Prefetch is
    /// bounded, skipped when already cached/in-flight, and never blocks mpv
    /// on a future block. It can be discarded by the LRU on large seeks.
    private func prefetch(after byteOffset: Int64) {
        guard fileSize > 0, byteOffset >= 0, byteOffset < fileSize else { return }
        let nextBlock = byteOffset / blockSize
        for n in 0..<2 {
            let block = nextBlock + Int64(n)
            let start = block * blockSize
            guard start < fileSize else { continue }
            lock.lock()
            let needed = blocks[block] == nil && !pendingPrefetch.contains(block)
            if needed { pendingPrefetch.insert(block) }
            lock.unlock()
            guard needed else { continue }

            let end = min(start + blockSize, fileSize) - 1
            prefetchQueue.async { [weak self] in
                guard let self else { return }
                let fetched = try? self.request(start: start, end: end).0
                self.lock.lock()
                if let fetched, self.blocks[block] == nil {
                    self.blocks[block] = fetched
                    self.order.removeAll { $0 == block }
                    self.order.append(block)
                    while self.order.count > self.maxCachedBlocks {
                        let evict = self.order.removeFirst()
                        self.blocks.removeValue(forKey: evict)
                    }
                }
                self.pendingPrefetch.remove(block)
                self.lock.unlock()
            }
        }
    }

'''
text=text.replace(anchor,helper+anchor,1)
# Only inject in the read(...) function, which is before the ZIP u16 parser.
s=text.find("    func read(at start: Int64, count: Int) throws -> Data {\n")
e=text.find("    private static func u16",s)
if s<0 or e<0: raise SystemExit("ZIP prefetch: reader boundaries missing")
sub=text[s:e]
if "        return result\n" not in sub: raise SystemExit("ZIP prefetch: reader return not found")
sub=sub.replace("        return result\n", "        prefetch(after: start + desired)\n        return result\n",1)
text=text[:s]+sub+text[e:]
file.write_text(text)
print("ZIP HTTP Range prefetch enabled: two ahead, 1MiB each, bounded 96MiB LRU.")
