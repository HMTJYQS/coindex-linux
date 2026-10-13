"""Assemble README screenshots and a GIF from reviewed demo-window captures.

Requires Pillow. This script does not capture the screen or operate the app.
Capture only the isolated --demo preview, review each image, then run this tool.
"""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--captures", type=Path, default=ROOT/"build/readme-captures")
parser.add_argument("--output", type=Path, default=ROOT/"docs/assets")
parser.add_argument("--font", type=Path, default=Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
font = ImageFont.truetype(str(args.font), 25)
small = ImageFont.truetype(str(args.font), 16)
steps = [
    ("01-overview.png", "查看 Agent 整理后的目标跟进清单"),
    ("08-conversations.png", "统一查看本机与 SSH 来源的多个对话"),
    ("02-review-filter.png", "筛选需要核对结果的目标"),
    ("03-task-detail.png", "查看整体目标、当前进度与下一步"),
    ("04-evidence.png", "核对原文依据和原始对话来源"),
    ("05-search.png", "通过关键词找到待跟进的工作"),
    ("06-manual-task.png", "补充不关联对话的手动跟进事项"),
    ("07-connections.png", "在引导中配置自己的 Codex 与 SSH 来源"),
]


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

frames = []
for i, (name, title) in enumerate(steps, 1):
    frame = Image.new("RGB", (1200, 900), "#eef0f6")
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, 0, 1200, 96), fill="#252b5d")
    draw.text((24, 14), f"{i:02d} / {len(steps):02d}   {title}", font=font, fill="white")
    draw.text((24, 57), "coindex 1.9.0 · 虚构演示数据 · 界面步骤回放", font=small, fill="#d6dbff")
    image = read(name)
    image.thumbnail((1168, 746), Image.Resampling.LANCZOS)
    frame.paste(image, ((1200-image.width)//2, 104+(746-image.height)//2))
    draw.text((24, 869), "演示模式不调用模型、不连接服务器、不发送催办", font=small, fill="#4a5071")
    frames.append(frame.quantize(colors=192, method=Image.Quantize.MEDIANCUT))
frames[0].save(args.output/"workflow-demo.gif", save_all=True, append_images=frames[1:],
               duration=[3200, 2800, 2800, 3600, 3600, 2800, 2800, 3200], loop=0, disposal=2, optimize=True)
print(json.dumps({"screenshots": list(screenshots.values()), "demo_frames": len(frames),
                  "demo_duration_seconds": 24.8, "output": str(args.output)}, ensure_ascii=False))
