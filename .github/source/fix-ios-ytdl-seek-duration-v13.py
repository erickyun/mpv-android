from pathlib import Path

ROOT = Path('MPVTorBox')
SERVICE = ROOT / 'YTDLPService.swift'
METAL = ROOT / 'Player' / 'MPVMetalViewController.swift'


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'{label} anchor not found in {path}')
    path.write_text(text.replace(old, new, 1))


# mpv's stock ytdl_hook does NOT use !delay_open for the normal selected
# requested_formats path. Delaying both selected YouTube streams prevents mpv
# from learning the complete media duration up front, so the UI seek range can
# grow with the downloaded/buffered portion. Carry yt-dlp's Info.duration into
# the native bridge and attach it to the EDL entries explicitly as well.

replace_once(
    SERVICE,
    '''        let selector: String?\n        let error: String?\n\n        static func failure(_ message: String) -> MPVHookResponse {\n            MPVHookResponse(ok: false, title: nil, formats: [], httpHeaders: [:], selector: nil, error: message)\n        }\n''',
    '''        let selector: String?\n        let duration: Double?\n        let error: String?\n\n        static func failure(_ message: String) -> MPVHookResponse {\n            MPVHookResponse(ok: false, title: nil, formats: [], httpHeaders: [:], selector: nil, duration: nil, error: message)\n        }\n''',
    'add hook duration',
)

replace_once(
    SERVICE,
    '''            httpHeaders: headers,\n            selector: effectiveSelector,\n            error: nil\n''',
    '''            httpHeaders: headers,\n            selector: effectiveSelector,\n            duration: result.1.duration,\n            error: nil\n''',
    'return yt-dlp duration',
)

replace_once(
    METAL,
    '''        guard let stream = makeEmbeddedYTDLStream(response.formats) else {\n''',
    '''        guard let stream = makeEmbeddedYTDLStream(\n            response.formats,\n            duration: response.duration\n        ) else {\n''',
    'pass duration to EDL builder',
)

old_builder = '''    private func makeEmbeddedYTDLStream(\n        _ formats: [YTDLPService.MPVHookFormat]\n    ) -> String? {\n        let playable = formats.filter { !$0.url.isEmpty }\n        guard !playable.isEmpty else { return nil }\n        if playable.count == 1 { return playable[0].url }\n\n        let streams = playable.map { format -> String in\n            let hasVideo = format.vcodec != nil && format.vcodec != "none"\n            let hasAudio = format.acodec != nil && format.acodec != "none"\n            var header = ["!new_stream", "!no_clip", "!no_chapters"]\n            if hasVideo && !hasAudio {\n                header.append("!delay_open,media_type=video")\n            } else if hasAudio && !hasVideo {\n                header.append("!delay_open,media_type=audio")\n            }\n            return header.joined(separator: ";") + ";" + edlEscape(format.url)\n        }\n        return "edl://" + streams.joined(separator: ";")\n    }\n'''

new_builder = '''    private func makeEmbeddedYTDLStream(\n        _ formats: [YTDLPService.MPVHookFormat],\n        duration: Double?\n    ) -> String? {\n        let playable = formats.filter { !$0.url.isEmpty }\n        guard !playable.isEmpty else { return nil }\n        if playable.count == 1 { return playable[0].url }\n\n        // Match mpv's normal requested_formats EDL path: selected audio/video\n        // streams are opened immediately. !delay_open is reserved by mpv's\n        // stock hook for the all-formats/quality-selection path.\n        let knownLength: String\n        if let duration, duration.isFinite, duration > 0 {\n            knownLength = ",length=\\(duration)"\n        } else {\n            knownLength = ""\n        }\n\n        let streams = playable.map { format -> String in\n            let header = ["!new_stream", "!no_clip", "!no_chapters"]\n            return header.joined(separator: ";") + ";" + edlEscape(format.url) + knownLength\n        }\n        return "edl://" + streams.joined(separator: ";")\n    }\n'''

replace_once(METAL, old_builder, new_builder, 'replace delayed EDL builder')

print('Removed !delay_open from selected yt-dlp streams and exposed full media duration to EDL seeking.')
