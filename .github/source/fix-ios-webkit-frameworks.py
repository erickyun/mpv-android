from pathlib import Path

project = Path('project.yml')
text = project.read_text()
anchor = '''      - package: YoutubeDL
        product: YoutubeDL
'''
if anchor not in text:
    raise SystemExit('Expected YoutubeDL dependency anchor was not found')
text = text.replace(
    anchor,
    anchor + '      - sdk: WebKit.framework\n      - sdk: JavaScriptCore.framework\n',
    1,
)
project.write_text(text)
print('Linked WebKit and JavaScriptCore system frameworks.')
