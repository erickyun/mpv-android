from pathlib import Path

project = Path('project.yml')
text = project.read_text()
old = '        ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME: AccentColor\n'
new = old + '        INFOPLIST_KEY_UILaunchStoryboardName: LaunchScreen\n'
if old not in text:
    raise SystemExit('Expected XcodeGen settings anchor was not found')
project.write_text(text.replace(old, new, 1))
print('Pinned UILaunchStoryboardName=LaunchScreen in Xcode build settings.')
