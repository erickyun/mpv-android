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
