from pathlib import Path

path = Path("MPVTorBox/Player/MPVMetalViewController.swift")
text = path.read_text()

replacements = {
    "private let metalLayer = MetalLayer()": "private var metalLayer = MetalLayer()",
    "var pointers: [UnsafePointer<CChar>?] = strings.map { strdup($0).map(UnsafePointer.init) }": """var pointers: [UnsafePointer<CChar>?] = strings.map { value in
            guard let duplicated = strdup(value) else { return nil }
            return UnsafePointer<CChar>(duplicated)
        }""",
}

for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"Expected Swift source pattern not found: {old}")
    text = text.replace(old, new, 1)

path.write_text(text)
