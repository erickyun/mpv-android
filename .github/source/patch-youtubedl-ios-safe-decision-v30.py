from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-safe-decision-v30.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()

old = '''        let safeMetadata = getenv("MPV_IOS_SAFE_METADATA") != nil

        if safeMetadata {
'''
new = '''        let safeRequested = getenv("MPV_IOS_SAFE_METADATA_REQUESTED") != nil
        let safeSites: [String] = {
            guard let raw = getenv("MPV_IOS_SAFE_METADATA_SITES") else { return [] }
            return String(cString: raw)
                .split(separator: ",")
                .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
                .filter { !$0.isEmpty }
        }()
        let currentHost = (url.host ?? "").lowercased()
        let siteMatched = safeSites.isEmpty || safeSites.contains { site in
            currentHost == site || currentHost.hasSuffix("." + site)
        }
        let safeMetadata = safeRequested && siteMatched

        mpvYTDLPBridgeLog(
            "safe mode decision: requested=\\(safeRequested); active=\\(safeMetadata); host=\\(currentHost); scoped-sites=\\(safeSites.count)"
        )

        if safeMetadata {
            // Apply sidecar/metadata suppression only to URLs where safe mode is
            // actually active. Non-matching sites retain the old behavior.
            pythonObject.params["writethumbnail"] = false
            pythonObject.params["list_thumbnails"] = false
            pythonObject.params["writeinfojson"] = false
            pythonObject.params["writedescription"] = false
            pythonObject.params["getcomments"] = false
            pythonObject.params["embedthumbnail"] = false
'''
if old not in text:
    raise SystemExit('v29 safeMetadata decision anchor not found')
text = text.replace(old, new, 1)

path.write_text(text)
print(f'Patched {path}: safe mode is global by default or scoped by MPV_IOS_SAFE_METADATA_SITES.')
