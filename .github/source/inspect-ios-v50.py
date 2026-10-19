from pathlib import Path
import re
files=[
("PLAYER",Path("MPVTorBox/Views/PlayerScreen.swift"),[
    "private func controls(", "private var top", "private func top", "info.circle",
    "MPVMetalPlayerView(coordinator:", "GeometryReader", "private var body",
]),
("METAL",Path("MPVTorBox/Player/MPVMetalViewController.swift"),[
    "func loadSource(", "func refreshVideoSurface(", "func scheduleSurfaceRefreshes(",
    "func scheduleVideoTrackReopenAfterRotation(", "override func viewDidLayoutSubviews(",
    "override func viewWillTransition(", "private func setupMPV(",
]),
("RENDERABLE",Path("MPVTorBox/Player/MPVMetalPlayerView.swift"),[
    "func makeUIViewController", "func updateUIViewController", "func play(",
]),
("CONFIG",Path("MPVTorBox/Utilities/MPVConfigManager.swift"),[
    "static func prepare()", "profile=high-quality", "cache=",
]) ]
for tag,path,needles in files:
    data=path.read_text()
    print("=== INSPECT",tag,path,"len",len(data),"===")
    for needle in needles:
        idx=data.find(needle)
        if idx>=0:
            print("INSPECT_MARK",needle,idx)
            print(data[max(0,idx-550):min(len(data),idx+4200)])
        else:
            print("INSPECT_MISSING",needle)
