"""Re-draw single cells of a generated sprite sheet without touching the others.

Whole-sheet edits make image models redraw everything (good frames included), so each fix
is generated in isolation: a strip [previous cell | empty | next cell] is sent with the
pose description, the model draws only the middle cell, and that cell is pasted back.

Usage:
  python tools/fix_cells.py raw.png --cols 5 --rows 3 --fixes fixes.json -o fixed_raw.png
fixes.json: [{"cell": 2, "pose": "...", "prev": 1, "next": 3} | {"cell": 13, "copy": 2}, ...]  (1-based)
"""
import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from gen_animate import KEY_RGB, api_key, call_gemini  # noqa: E402


def cell_box(sheet, cols, rows, k):
    cw, ch = sheet.width / cols, sheet.height / rows
    r, c = divmod(k - 1, cols)
    return (round(c * cw), round(r * ch), round((c + 1) * cw), round((r + 1) * ch))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw")
    ap.add_argument("--cols", type=int, required=True)
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--fixes", required=True)
    ap.add_argument("--describe", default="ninja in a navy suit with a cyan visor and a pink scarf")
    ap.add_argument("--model", default="gemini-3-pro-image")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    sheet = Image.open(a.raw).convert("RGB")
    key = api_key()
    for fx in json.loads(Path(a.fixes).read_text()):
        box = cell_box(sheet, a.cols, a.rows, fx["cell"])
        size = (box[2] - box[0], box[3] - box[1])
        if "copy" in fx:
            src = sheet.crop(cell_box(sheet, a.cols, a.rows, fx["copy"])).resize(size, Image.NEAREST)
            sheet.paste(src, box[:2])
            print(f"cell {fx['cell']} = copy of cell {fx['copy']}")
            continue
        w, h = size
        H = round(3 * w / (21 / 9))           # 21:9 strip, cells vertically centered
        top = (H - h) // 2
        strip = Image.new("RGB", (3 * w, H), KEY_RGB)
        strip.paste(sheet.crop(cell_box(sheet, a.cols, a.rows, fx["prev"])), (0, top))
        strip.paste(sheet.crop(cell_box(sheet, a.cols, a.rows, fx["next"])), (2 * w, top))
        prompt = (
            f"Three equal panels of a pixel-art animation of a {a.describe}, side view facing right, on flat magenta. "
            "The LEFT panel is the frame before and the RIGHT panel is the frame after. The MIDDLE panel is empty: draw "
            f"exactly one frame there: {fx['pose']}. Same character design, colors, outline, proportions, size and "
            "chunky pixel size as the side panels, standing on the same ground line, fully inside the middle panel. "
            "Keep the left and right panels unchanged. Flat magenta background, no borders, no text, no effects, "
            "no anti-aliasing.")
        t = time.time()
        gen = call_gemini(a.model, prompt, strip, key, "21:9").resize(strip.size, Image.LANCZOS)
        mid = gen.crop((w, top, 2 * w, top + h))
        sheet.paste(mid, box[:2])
        print(f"cell {fx['cell']} redrawn in {time.time() - t:.0f}s")
    sheet.save(a.out)


if __name__ == "__main__":
    main()
