"""Import original built-in artwork from the user's installed Codex app, read-only.

The renderer is authored in Swift. No executable code from Codex is copied.
"""
import hashlib
import json
import pathlib
import plistlib
import re
import struct
import sys

app = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '/Applications/ChatGPT.app')
target = pathlib.Path(__file__).resolve().parent.parent / 'Resources/Pets'
names = [('codex', 'Codex'), ('dewey', 'Dewey'), ('fireball', 'Fireball'),
         ('hoots', 'Hoots'), ('rocky', 'Rocky'), ('seedy', 'Seedy'),
         ('stacky', 'Stacky'), ('bsod', 'BSOD'), ('null-signal', 'Null Signal')]
with (app / 'Contents/Resources/app.asar').open('rb') as source:
    header = struct.unpack('<4I', source.read(16))
    index = json.loads(source.read(header[3]))
    base = 8 + header[1]
    assets = index['files']['webview']['files']['assets']['files']
    target.mkdir(parents=True, exist_ok=True)
    entries = []
    for pet_id, name in names:
        candidates = [n for n in assets if re.fullmatch(re.escape(pet_id) + r'-spritesheet-v\d+-[a-f0-9]+\.webp', n)]
        if len(candidates) != 1:
            raise RuntimeError('Expected exactly one original atlas for ' + pet_id)
        original = candidates[0]
        entry = assets[original]
        source.seek(base + int(entry['offset']))
        data = source.read(entry['size'])
        (target / (pet_id + '.webp')).write_bytes(data)
        entries.append(dict(id=pet_id, name=name, file=pet_id + '.webp', original=original,
                            sha256=hashlib.sha256(data).hexdigest(), rows=11))
info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
(target / 'manifest.json').write_text(json.dumps(dict(source='Installed Codex desktop app',
    source_version=info['CFBundleShortVersionString'], cell_width=192, cell_height=208,
    columns=8, pets=entries), indent=2) + '\n')
print('Imported', len(entries), 'original pet atlases from Codex', info['CFBundleShortVersionString'])
