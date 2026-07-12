#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path}: found {count}\n{old}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


root = Path(__file__).resolve().parents[1]
activity = root / "app/src/main/java/is/xyz/mpv/MPVActivity.kt"
utils = root / "app/src/main/java/is/xyz/mpv/Utils.kt"
base_view = root / "app/src/main/java/is/xyz/mpv/BaseMPVView.kt"
manifest = root / "app/src/main/AndroidManifest.xml"

# ACTION_SEND text containing magnet: is an opaque URI, so do not reject it
# merely because Android reports it as non-hierarchical.
replace_once(
    activity,
    '''        fun safeResolveUri(u: Uri?): String? {
            return if (u != null && u.isHierarchical && !u.isRelative)
                resolveUri(u)
            else null
        }
''',
    '''        fun safeResolveUri(u: Uri?): String? {
            return u?.let { resolveUri(it) }
        }
''',
)

# Pass torrent URI schemes through the normal intent parser.
replace_once(
    activity,
    '''            "http", "https", "rtmp", "rtmps", "rtp", "rtsp", "mms", "mmst", "mmsh",
            "tcp", "udp", "lavf", "ftp"
            -> data.toString()
''',
    '''            "http", "https", "rtmp", "rtmps", "rtp", "rtsp", "mms", "mmst", "mmsh",
            "tcp", "udp", "lavf", "ftp", "magnet", "torrs"
            -> data.toString()
''',
)

# Resolve the first launch before libmpv sees the magnet URL. This does not
# depend on mpv's Lua script auto-loading behavior.
replace_once(
    activity,
    '''        val filepath = parsePathFromIntent(intent)
''',
    '''        val filepath = parsePathFromIntent(intent)?.let { TorrServer.resolve(this, it) }
''',
)

# Do the same when a magnet is shared while MPVActivity already exists.
replace_once(
    activity,
    '''        val filepath = intent?.let { parsePathFromIntent(it) }
''',
    '''        val filepath = intent?.let { parsePathFromIntent(it) }?.let { TorrServer.resolve(this, it) }
''',
)

# Open URL must accept opaque magnet URIs as well as normal hierarchical URLs.
replace_once(
    utils,
    '''        private fun validate(text: String): Boolean {
            val uri = Uri.parse(text)
            return uri.isHierarchical && !uri.isRelative &&
                    !(uri.host.isNullOrEmpty() && uri.path.isNullOrEmpty()) &&
                    PROTOCOLS.contains(uri.scheme)
        }
''',
    '''        private fun validate(text: String): Boolean {
            val uri = Uri.parse(text.trim())
            if (!PROTOCOLS.contains(uri.scheme))
                return false
            if (uri.scheme == "magnet" || uri.scheme == "torrs")
                return !uri.schemeSpecificPart.isNullOrBlank()
            return uri.isHierarchical && !uri.isRelative &&
                    !(uri.host.isNullOrEmpty() && uri.path.isNullOrEmpty())
        }
''',
)

replace_once(
    utils,
    '''        "rtmp", "rtmps", "rtp", "rtsp", "mms", "mmst", "mmsh", "tcp", "udp", "lavf"
''',
    '''        "rtmp", "rtmps", "rtp", "rtsp", "mms", "mmst", "mmsh", "tcp", "udp", "lavf",
        "magnet", "torrs"
''',
)

# Keep libmpv alive after a failed first load. With idle=once it shuts down and
# MPVActivity immediately finishes, which looks like an application crash.
replace_once(
    base_view,
    '''        MPVLib.setOptionString("idle", "once")
''',
    '''        MPVLib.setOptionString("idle", "yes")
''',
)

# TorrServer commonly runs on localhost or a LAN IP over plain HTTP.
replace_once(
    manifest,
    '''        android:allowBackup="true"
''',
    '''        android:allowBackup="true"
        android:usesCleartextTraffic="true"
''',
)

print("Applied TorrServer direct routing, magnet/Open URL/share/HTTP/idle patches")
