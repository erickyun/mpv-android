from pathlib import Path
import plistlib

# User-supplied URLs may be HTTP or HTTPS->HTTP redirects. URLSession is
# subject to iOS App Transport Security even when libmpv's lower-level HTTP
# backend is not. MPV is a general-purpose URL player, so unknown hosts must
# work (a fixed per-domain exception list is inadequate).
info_path = Path("MPVTorBox/Info.plist")
with info_path.open("rb") as stream:
    info = plistlib.load(stream)

ats = info.setdefault("NSAppTransportSecurity", {})
# iOS 10+ ignores NSAllowsArbitraryLoads when these narrower exception keys
# are also present. Set one unambiguous policy for user-entered HTTP URLs.
for key in (
    "NSAllowsArbitraryLoadsInWebContent",
    "NSAllowsArbitraryLoadsForMedia",
    "NSAllowsLocalNetworking",
):
    ats.pop(key, None)
ats["NSAllowsArbitraryLoads"] = True

with info_path.open("wb") as stream:
    plistlib.dump(info, stream, fmt=plistlib.FMT_XML, sort_keys=False)
assert plistlib.loads(info_path.read_bytes())["NSAppTransportSecurity"]["NSAllowsArbitraryLoads"] is True
print("ATS: enabled ordinary HTTP(S) URLSession playback for user-provided URLs (HTTPS certificate validation unchanged).")
