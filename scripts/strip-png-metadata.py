"""Strip PNG descriptive metadata without decoding or changing image pixels."""
from pathlib import Path
import sys

KEEP = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND", b"sRGB", b"gAMA", b"cHRM", b"iCCP"}
for argument in sys.argv[1:]:
    path = Path(argument)
    for image in sorted(path.rglob("*.png")) if path.is_dir() else [path]:
        data = image.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Not a PNG: " + str(image))
        result = bytearray(data[:8])
        offset = 8
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset:offset+4], "big")
            if offset + size + 12 > len(data):
                raise ValueError("Truncated PNG: " + str(image))
            if data[offset+4:offset+8] in KEEP:
                result.extend(data[offset:offset+size+12])
            offset += size + 12
        if offset != len(data):
            raise ValueError("Unexpected trailing PNG data: " + str(image))
        image.write_bytes(result)
