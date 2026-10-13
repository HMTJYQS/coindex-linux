"""Register generated sprite artwork into coindex's existing 192x208 atlas.

Only slices, scales and packs imagegen artwork; does not draw or synthesize art.
Run using the bundled Python runtime (Pillow and numpy required).
"""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def pack(source, destination):
    image = Image.open(source).convert('RGBA')
    pixels = np.array(image)
    alpha = pixels[:, :, 3]
    height, width = alpha.shape
    core = alpha > 128
    owners = np.zeros(core.shape, dtype=np.int16)
    components = []
    seen = np.zeros(core.shape, dtype=bool)
    for y, x in zip(*np.where(core)):
        if seen[y, x]:
            continue
        queue = deque([(int(y), int(x))])
        seen[y, x] = True
        points = []
        while queue:
            cy, cx = queue.popleft()
            points.append((cy, cx))
            for ny, nx in ((cy-1, cx), (cy+1, cx), (cy, cx-1), (cy, cx+1)):
                if 0 <= ny < height and 0 <= nx < width and core[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    queue.append((ny, nx))
        if len(points) > 1000:
            identifier = len(components) + 1
            ys, xs = np.array(points).T
            owners[ys, xs] = identifier
            components.append({'id': identifier, 'x': float(xs.mean()), 'y': float(ys.mean())})

    # Retain each sprite's connected antialiased fur/whisker pixels while
    # keeping neighboring sprites separate where generated gutters are tight.
    frontier = deque()
    for y, x in zip(*np.where(owners > 0)):
        if any(0 <= ny < height and 0 <= nx < width and alpha[ny, nx] > 0 and owners[ny, nx] == 0
               for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1))):
            frontier.append((int(y), int(x)))
    while frontier:
        y, x = frontier.popleft()
        identifier = owners[y, x]
        for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
            if 0 <= ny < height and 0 <= nx < width and alpha[ny, nx] > 0 and owners[ny, nx] == 0:
                owners[ny, nx] = identifier
                frontier.append((ny, nx))

    # The generated source uses variable row spacing. These cut points are
    # verified gutters, rather than assuming uniform source cells.
    gutters = [0, 124, 240, 357, 495, 615, 752, 895, 1031, 1180, 1330, 1531]
    assert image.size == (1027, 1531), 'Source geometry changed; review row gutters.'
    rows = [[] for _ in range(11)]
    for component in components:
        for row in range(11):
            if gutters[row] <= component['y'] < gutters[row+1]:
                rows[row].append(component)
                break
    for row in rows:
        row.sort(key=lambda value: value['x'])
    assert [len(row) for row in rows] == [5, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8]
    atlas = Image.new('RGBA', (1536, 2288))
    record = []
    required = [6, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8]
    for row_index, row in enumerate(rows):
        sprites = []
        bounds = []
        for component in row:
            identifier = component['id']
            ys, xs = np.where(owners == identifier)
            bbox = (int(xs.min()), int(ys.min()), int(xs.max()+1), int(ys.max()+1))
            piece = pixels[bbox[1]:bbox[3], bbox[0]:bbox[2]].copy()
            piece[owners[bbox[1]:bbox[3], bbox[0]:bbox[2]] != identifier] = 0
            sprites.append(Image.fromarray(piece, 'RGBA'))
            bounds.append(bbox)
        # A repeat of the initial pose closes the five-pose idle loop.
        if row_index == 0:
            sprites.append(sprites[0].copy())
            bounds.append(bounds[0])
        target_height = 164 if row_index not in (1, 2, 4) else 134
        scale = min(target_height / max(sprite.height for sprite in sprites),
                    164 / max(sprite.width for sprite in sprites))
        for column, sprite in enumerate(sprites):
            size = (round(sprite.width*scale), round(sprite.height*scale))
            sprite = sprite.resize(size, Image.Resampling.LANCZOS)
            x = column*192 + (192-sprite.width)//2
            bottom = 190
            if row_index == 4:
                # Preserve the generated takeoff/air/landing
                # displacement, scaled with the artwork.
                bottom -= round((max(box[3] for box in bounds)-bounds[column][3])*scale)
            y = row_index*208 + bottom-sprite.height
            atlas.alpha_composite(sprite, (x, y))
            record.append({'row': row_index, 'column': column, 'sourceBox': bounds[column],
                           'size': list(size), 'destination': [x, y]})
        assert len(sprites) == required[row_index]
    destination.mkdir(parents=True, exist_ok=True)
    atlas_path = destination/'spritesheet.png'
    atlas.save(atlas_path, optimize=True)
    manifest = {
        'id': 'coindex-cat', 'displayName': '小猫',
        'description': '黑白小猫：黑白长毛、粉鼻子、白色额纹和下巴黑斑。',
        'spritesheetPath': 'spritesheet.png', 'spriteVersion': 2,
    }
    (destination/'pet.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    report = {'generator': 'built-in imagegen', 'sourceSize': list(image.size),
              'atlasSize': list(atlas.size), 'cellSize': [192, 208],
              'requiredFrames': required, 'occupiedFrames': sum(required),
              'idleLoopClosure': 'Repeat the first pose after the five generated idle poses.',
              'sourceSHA256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'atlasSHA256': hashlib.sha256(atlas_path.read_bytes()).hexdigest(), 'frames': record}
    (destination/'generation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'frames'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    pack(args.source, args.destination)
