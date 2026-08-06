from pathlib import Path

project = Path('project.yml')
text = project.read_text()
old = '        ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME: AccentColor\n'
new = old + '        INFOPLIST_KEY_UILaunchStoryboardName: LaunchScreen\n'
if old not in text:
    raise SystemExit('Expected XcodeGen settings anchor was not found')
project.write_text(text.replace(old, new, 1))
print('Pinned UILaunchStoryboardName=LaunchScreen in Xcode build settings.')

# Run the follow-up player UX patch from the same build working directory.
player_patch = Path(__file__).with_name('fix-ios-player-ux-v2.py')
if not player_patch.is_file():
    raise SystemExit(f'Missing player UX patch: {player_patch}')
source = player_patch.read_text()
source = source.replace(
    '        metalLayer.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]\n',
    ''
)
namespace = {'__name__': '__main__', '__file__': str(player_patch)}
exec(compile(source, str(player_patch), 'exec'), namespace)

# Save screenshots in Files, preserve the complete custom Info.plist, and keep
# the Python symbols that YoutubeDL-iOS resolves dynamically in Release builds.
ytdlp_patch = Path(__file__).with_name('fix-ios-screenshot-ytdlp.py')
if not ytdlp_patch.is_file():
    raise SystemExit(f'Missing screenshot/yt-dlp patch: {ytdlp_patch}')
namespace = {'__name__': '__main__', '__file__': str(ytdlp_patch)}
exec(compile(ytdlp_patch.read_text(), str(ytdlp_patch), 'exec'), namespace)

# Add the yt-dlp update/version interface, official stats.lua controls, and
# runtime mpv version reporting after the earlier compatibility patches.
features_patch = Path(__file__).with_name('fix-ios-ytdlp-stats-versions.py')
if not features_patch.is_file():
    raise SystemExit(f'Missing yt-dlp/stats/version patch: {features_patch}')
namespace = {'__name__': '__main__', '__file__': str(features_patch)}
exec(compile(features_patch.read_text(), str(features_patch), 'exec'), namespace)

# Apply playback fixes: bounded yt-dlp extraction, delete support, native stats
# fallback, reliable rotation resizing, tap toggle, and regional gestures.
playback_patch = Path(__file__).with_name('fix-ios-playback-v4.py')
if not playback_patch.is_file():
    raise SystemExit(f'Missing playback v4 patch: {playback_patch}')
namespace = {'__name__': '__main__', '__file__': str(playback_patch)}
exec(compile(playback_patch.read_text(), str(playback_patch), 'exec'), namespace)

# Preserve the previous public identity before applying the latest revision.
text = project.read_text()
text = text.replace('        MARKETING_VERSION: 1.4.0\n', '        MARKETING_VERSION: 1.3.0\n', 1)
text = text.replace('        CURRENT_PROJECT_VERSION: 14\n', '        CURRENT_PROJECT_VERSION: 13\n', 1)
project.write_text(text)

# Route only supported website pages through yt-dlp, hand its HTTP headers to
# mpv correctly, and expose gpu-next/deband/shader details in native Stats.
renderer_patch = Path(__file__).with_name('fix-ios-routing-renderer-v5.py')
if not renderer_patch.is_file():
    raise SystemExit(f'Missing routing/renderer v5 patch: {renderer_patch}')
namespace = {'__name__': '__main__', '__file__': str(renderer_patch)}
exec(compile(renderer_patch.read_text(), str(renderer_patch), 'exec'), namespace)
