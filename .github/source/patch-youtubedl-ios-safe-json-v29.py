from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-youtubedl-ios-safe-json-v29.py /path/to/YoutubeDL.swift')

path = Path(sys.argv[1])
text = path.read_text()

start_marker = '    open func extractInfo(url: URL) async throws -> ([Format], Info) {'
end_marker = '    func tryMerge(directory: URL, title: String, timeRange: TimeRange?) -> Bool {'
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit('extractInfo/tryMerge anchors not found')

new_method = r'''    open func extractInfo(url: URL) async throws -> ([Format], Info) {
        mpvYTDLPBridgeLog("extractInfo enter; main=\(Thread.isMainThread); url=\(url.absoluteString)")
        let pythonObject: PythonObject
        if let _pythonObject = self.pythonObject {
            pythonObject = _pythonObject
        } else {
            pythonObject = try await makePythonObject()
        }

        print(#function, url)
        let safeMetadata = getenv("MPV_IOS_SAFE_METADATA") != nil

        if safeMetadata {
            // Keep every extractor object, format selector generator, and arbitrary
            // metadata shape inside Python. Swift receives exactly one UTF-8 JSON
            // string. This avoids YoutubeDL-iOS 0.0.9 PythonDecoder/PythonKit
            // traversals that can fatalError on extractor-specific data shapes.
            let builtins = Python.import("builtins")
            let mainModule = Python.import("__main__")
            let resolverSource = #"""
import json

def _mpv_ios_scalar_text(value, fallback=''):
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return fallback

def _mpv_ios_number(value, integer=False):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if integer else float(value)
    return None

def _mpv_ios_headers(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        key_text = _mpv_ios_scalar_text(key)
        item_text = _mpv_ios_scalar_text(item)
        if key_text and item_text:
            result[key_text] = item_text
    return result

def _mpv_ios_format(item, parent_headers=None):
    if not isinstance(item, dict):
        return None
    url = _mpv_ios_scalar_text(item.get('url'))
    if not url:
        return None

    acodec = item.get('acodec')
    vcodec = item.get('vcodec')
    ext = _mpv_ios_scalar_text(item.get('ext'), 'unknown')
    headers = _mpv_ios_headers(item.get('http_headers'))
    if not headers:
        headers = _mpv_ios_headers(parent_headers)

    result = {
        'format_id': _mpv_ios_scalar_text(item.get('format_id'), 'unknown'),
        'url': url,
        'ext': ext,
        'protocol': _mpv_ios_scalar_text(item.get('protocol'), 'https'),
        'audio_ext': _mpv_ios_scalar_text(item.get('audio_ext'), 'none' if acodec == 'none' else ext),
        'video_ext': _mpv_ios_scalar_text(item.get('video_ext'), 'none' if vcodec == 'none' else ext),
        'format': _mpv_ios_scalar_text(item.get('format'), _mpv_ios_scalar_text(item.get('format_id'), 'unknown')),
        'http_headers': headers,
    }

    for key in ('format_note', 'language', 'vcodec', 'acodec', 'dynamic_range', 'container', 'resolution'):
        value = item.get(key)
        text = _mpv_ios_scalar_text(value)
        if text:
            result[key] = text

    for key in ('asr', 'filesize', 'height', 'width', 'language_preference'):
        value = _mpv_ios_number(item.get(key), integer=True)
        if value is not None:
            result[key] = value

    for key in ('fps', 'quality', 'tbr', 'abr', 'vbr'):
        value = _mpv_ios_number(item.get(key))
        if value is not None:
            result[key] = value

    return result

def _mpv_ios_chapters(value):
    if not isinstance(value, (list, tuple)):
        return None
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        chapter = {}
        title = _mpv_ios_scalar_text(item.get('title'))
        if title:
            chapter['title'] = title
        start = _mpv_ios_number(item.get('start_time'))
        end = _mpv_ios_number(item.get('end_time'))
        if start is not None:
            chapter['start_time'] = start
        if end is not None:
            chapter['end_time'] = end
        result.append(chapter)
    return result

def _mpv_ios_safe_resolve_json(ydl, url):
    try:
        info = ydl.extract_info(url, download=False, process=True)
        if not isinstance(info, dict):
            raise TypeError(f'yt-dlp returned {type(info).__name__}, expected dict')

        format_spec = ydl.params.get('format') or 'bestvideo*+bestaudio/best'
        selector = ydl.build_format_selector(format_spec)
        selected = list(selector(info))

        flattened = []
        for item in selected:
            if not isinstance(item, dict):
                continue
            requested = item.get('requested_formats') or item.get('requested_downloads')
            if isinstance(requested, (list, tuple)) and requested:
                for child in requested:
                    if isinstance(child, dict):
                        flattened.append(child)
            elif item.get('url'):
                flattened.append(item)

        parent_headers = info.get('http_headers')
        formats = []
        for item in flattened:
            normalized = _mpv_ios_format(item, parent_headers)
            if normalized is not None:
                formats.append(normalized)

        if not formats:
            source_formats = info.get('formats')
            if isinstance(source_formats, (list, tuple)):
                for item in reversed(source_formats):
                    normalized = _mpv_ios_format(item, parent_headers)
                    if normalized is not None:
                        formats.append(normalized)
                        break

        video_id = _mpv_ios_scalar_text(info.get('id'), 'video')
        title = _mpv_ios_scalar_text(info.get('title'), video_id)
        summary = {
            'id': video_id,
            'title': title,
            'formats': formats,
            'webpage_url_basename': _mpv_ios_scalar_text(
                info.get('webpage_url_basename'),
                _mpv_ios_scalar_text(info.get('display_id'), video_id),
            ),
        }

        duration = _mpv_ios_number(info.get('duration'))
        if duration is not None:
            summary['duration'] = duration
        chapters = _mpv_ios_chapters(info.get('chapters'))
        if chapters is not None:
            summary['chapters'] = chapters

        for key in (
            'webpage_url', 'original_url', 'extractor', 'extractor_key',
            'display_id', 'uploader', 'uploader_id', 'uploader_url',
            'channel', 'channel_id', 'channel_url', 'availability', 'live_status',
        ):
            value = _mpv_ios_scalar_text(info.get(key))
            if value:
                summary[key] = value

        for key in ('is_live', 'was_live', 'playable_in_embed', '__has_drm'):
            value = info.get(key)
            if isinstance(value, bool):
                summary[key] = value

        for key in ('view_count', 'age_limit', 'like_count', 'release_timestamp'):
            value = _mpv_ios_number(info.get(key), integer=True)
            if value is not None:
                summary[key] = value

        return json.dumps({
            'ok': True,
            'error': '',
            'formats': formats,
            'info': summary,
        }, ensure_ascii=False, separators=(',', ':'))
    except BaseException as exc:
        return json.dumps({
            'ok': False,
            'error': f'{type(exc).__name__}: {exc}',
            'formats': [],
            'info': None,
        }, ensure_ascii=False, separators=(',', ':'))
"""#
            _ = builtins.exec(resolverSource, mainModule.__dict__)
            mpvYTDLPBridgeLog("safe JSON resolver begin")
            let resultObject = mainModule._mpv_ios_safe_resolve_json(pythonObject, url.absoluteString)
            guard let resultJSON = String(resultObject),
                  let resultData = resultJSON.data(using: .utf8) else {
                throw NSError(
                    domain: "YoutubeDL.SafeJSON",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "Safe yt-dlp resolver did not return UTF-8 JSON"]
                )
            }

            struct SafeEnvelope: Decodable {
                let ok: Bool
                let error: String
                let formats: [Format]
                let info: Info?
            }

            let envelope = try JSONDecoder().decode(SafeEnvelope.self, from: resultData)
            guard envelope.ok, let info = envelope.info else {
                throw NSError(
                    domain: "YoutubeDL.SafeJSON",
                    code: 2,
                    userInfo: [NSLocalizedDescriptionKey: envelope.error.isEmpty ? "yt-dlp safe resolver failed" : envelope.error]
                )
            }
            guard !envelope.formats.isEmpty else {
                throw NSError(
                    domain: "YoutubeDL.SafeJSON",
                    code: 3,
                    userInfo: [NSLocalizedDescriptionKey: "yt-dlp returned no playable formats"]
                )
            }
            mpvYTDLPBridgeLog("safe JSON resolver complete; formats=\(envelope.formats.count)")
            return (envelope.formats, info)
        }

        // Safe mode disabled: preserve the pre-v27 behavior exactly.
        mpvYTDLPBridgeLog("python extract_info begin; main=\(Thread.isMainThread)")
        let info = try pythonObject.extract_info.throwing.dynamicallyCall(
            withKeywordArguments: ["": url.absoluteString, "download": false, "process": true]
        )
        mpvYTDLPBridgeLog("python extract_info complete")
        print(info)

        mpvYTDLPBridgeLog("format selector begin")
        let format_selector = pythonObject.build_format_selector(options!["format"])
        let formats_to_download = format_selector(info)

        let builtins = Python.import("builtins")
        let mainModule = Python.import("__main__")
        let flattenSource = #"""
def _mpv_ios_flatten_selected_formats(items):
    flattened = []
    for item in items:
        requested = item.get('requested_formats') or item.get('requested_downloads')
        if requested:
            flattened.extend(requested)
        elif item.get('url'):
            flattened.append(item)
    return flattened
"""#
        _ = builtins.exec(flattenSource, mainModule.__dict__)
        let flattenedFormats = mainModule._mpv_ios_flatten_selected_formats(formats_to_download)
        mpvYTDLPBridgeLog("format selector complete; flattened=\(Python.len(flattenedFormats))")

        var formats: [Format] = []
        let decoder = PythonDecoder()
        for selectedFormat in flattenedFormats {
            let decoded = try decoder.decode(Format.self, from: selectedFormat)
            formats.append(decoded)
        }

        let decodedInfo = try decoder.decode(Info.self, from: info)
        mpvYTDLPBridgeLog("extractInfo decoded \(formats.count) selected formats and \(decodedInfo.formats.count) total formats")
        return (formats, decodedInfo)
    }

'''

text = text[:start] + new_method + text[end:]
path.write_text(text)
print(f'Patched {path}: safe mode now resolves through a single Python->JSON call; legacy mode unchanged.')
