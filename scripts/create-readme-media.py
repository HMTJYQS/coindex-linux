"""Assemble README screenshots from reviewed demo-window captures.

Requires Pillow. This script does not capture the screen or operate the app.
Capture only the isolated --demo preview, review each image, then run this tool.
"""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--captures", type=Path, default=ROOT/"build/readme-captures")
parser.add_argument("--output", type=Path, default=ROOT/"docs/assets")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)


def read(name):
    image = Image.open(args.captures/name).convert("RGB")
    # Remove the native capture title bar; retain only the application content.
    if name not in ("06-manual-task.png", "07-connections.png"):
        if image.size != (2400, 1640):
            raise ValueError("Unexpected demo window size: " + name)
        bounds = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
        if bounds == (0, 0, 1200, 828):
            image = image.crop((0, 32, 1200, 820))
        elif bounds == (0, 0, 2400, 1640):
            image = image.crop((0, 64, 2400, 1640))
        else:
            raise ValueError("Review unexpected capture bounds: " + name)
    image.info.clear()
    return image


screenshots = {
    "01-overview.png": "overview.png",
    "03-task-detail.png": "task-detail.png",
    "08-conversations.png": "conversations.png",
    "07-connections.png": "connections.png",
}
for source, target in screenshots.items():
    image = read(source)
    image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    image.save(args.output/target, optimize=True)

print(json.dumps({"screenshots": list(screenshots.values()), "output": str(args.output)}, ensure_ascii=False))
