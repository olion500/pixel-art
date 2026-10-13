"""Rig-guided generation: the rig decides the motion, the image model draws it.

Same idea as pose-conditioned sprite generation (PixelLab "Animate with skeleton",
Sprite Sheet Diffusion's Pose Guider), done with a general image model:
  1. A rough animation from the rig (tools/rig_animate.py) is laid out as a grid and sent
     as a pose guide, together with the clean source sprite as the identity reference.
  2. The model redraws every cell in the character's real art, keeping the guide's pose.
  3. Cleanup is driven by the guide instead of by the model: the art-pixel size is the
     median of (model bbox height / guide bbox height) over all frames, and every frame is
     placed at the guide frame's position. So the rig owns scale, path and timing and the
     model only owns the drawing.

Usage:
  python tools/guided_animate.py samples/ninja/ninja-base.png out/ninja/ours_jump_sheet.png 44 \
      "long jump" -o out/guided/ninja_jump [--cols 4] [--lock-first]
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from gen_animate import (KEY_RGB, api_key, call_gemini, cell_size, erase_grid_lines,  # noqa: E402
                         key_out, load_sprite, majority_downscale)
from rig_animate import drop_specks, fill_seams, kmeans_palette, snap  # noqa: E402


def bbox(a):
    ys, xs = np.nonzero(a[..., 3])
    return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(ys) else None


def load_guide(path, fw):
    a = np.asarray(Image.open(path).convert("RGBA"))
    return [a[:, i * fw:(i + 1) * fw] for i in range(a.shape[1] // fw)]


def guide_sheet(frames, cols, rows, cell, scale):
    cw, ch = cell
    sheet = Image.new("RGB", (cols * cw * scale, rows * ch * scale), KEY_RGB)
    placed = []
    for k, f in enumerate(frames):
        r, c = divmod(k, cols)
        fh, fw = f.shape[:2]
        ox, oy = (cw - fw) // 2, ch - fh
        big = Image.fromarray(f).resize((fw * scale, fh * scale), Image.NEAREST)
        sheet.paste(big, ((c * cw + ox) * scale, (r * ch + oy) * scale), big)
        b = bbox(f)
        placed.append((b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy))  # guide bbox in cell coords
    return sheet, placed


def reference_image(sprite, scale):
    h, w = sprite.shape[:2]
    pad = 4
    im = Image.new("RGB", ((w + 2 * pad) * scale, (h + 2 * pad) * scale), KEY_RGB)
    big = Image.fromarray(sprite).resize((w * scale, h * scale), Image.NEAREST)
    im.paste(big, (pad * scale, pad * scale), big)
    return im


def build_prompt(motion, n, cols, rows, describe):
    who = f" ({describe})" if describe else ""
    return (
        f"Image 1 is the reference pixel-art character{who}: this is exactly how the character must look "
        "(design, colors, outline, proportions, shading style, chunky pixel size).\n"
        f"Image 2 is a rough POSE GUIDE sprite sheet, {cols} columns x {rows} rows, {n} frames of a {motion} "
        "animation, made by a crude puppet rig of the same character. Its limbs are blocky and its shading is wrong, "
        "but the poses, body angles, positions inside each cell, sizes and timing are correct.\n"
        "Redraw image 2 cell by cell as clean, professional pixel art of the reference character: in every cell keep "
        "the guide's pose, silhouette size, position and ground line, but fix the anatomy (natural bent knees, "
        "elbows, hands, feet), and draw the character's real details and shading from image 1. Keep the same grid, "
        "same chunky pixel size, same flat magenta (#FF00FF) background. No grid lines, no text, no shadows, "
        "no blur, no anti-aliasing."
    )


def postprocess(gen, guide_boxes, cols, rows, cell, palette):
    gen = erase_grid_lines(gen)
    cw, ch = cell
    gw, gh = gen.width / cols, gen.height / rows
    cells, ratios = [], []
    for k, gb in enumerate(guide_boxes):
        r, c = divmod(k, cols)
        crop = gen.crop((round(c * gw), round(r * gh), round((c + 1) * gw), round((r + 1) * gh)))
        rgba = drop_specks(key_out(crop), 40)
        cells.append(rgba)
        b = bbox(rgba)
        if b:
            ratios.append((b[3] - b[1]) / (gb[3] - gb[1]))
    step = float(np.median(ratios))
    frames = []
    for rgba, gb in zip(cells, guide_boxes):
        f = np.zeros((ch, cw, 4), np.uint8)
        b = bbox(rgba)
        if b:
            x0, y0, x1, y1 = b
            ow, oh = max(1, round((x1 - x0) / step)), max(1, round((y1 - y0) / step))
            small = majority_downscale(rgba[y0:y1, x0:x1], ow, oh)
            # anchor on the guide: same horizontal center, same feet line
            px = round((gb[0] + gb[2]) / 2 - ow / 2)
            py = gb[3] - oh
            ys = slice(max(0, py), min(ch, py + oh))
            xs = slice(max(0, px), min(cw, px + ow))
            f[ys, xs] = small[ys.start - py:ys.stop - py, xs.start - px:xs.stop - px]
        frames.append(drop_specks(fill_seams(snap(f, palette)), 6))
    print(f"art pixel = {step:.2f} output px (spread {min(ratios):.2f}..{max(ratios):.2f})")
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("guide")
    ap.add_argument("guide_w", type=int)
    ap.add_argument("motion")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--scale", type=int, default=8)
    ap.add_argument("--colors", type=int, default=16)
    ap.add_argument("--model", default="gemini-3-pro-image")
    ap.add_argument("--describe", default="")
    ap.add_argument("--lock-first", action="store_true", help="frame 0 = guide frame 0 verbatim")
    ap.add_argument("--reuse")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    sprite = load_sprite(a.image)
    guide = load_guide(a.guide, a.guide_w)
    n = len(guide)
    rows = -(-n // a.cols)
    gh, gw = guide[0].shape[:2]
    cell, aspect = cell_size(max(gw, gh), a.cols, rows)
    sheet, boxes = guide_sheet(guide, a.cols, rows, cell, a.scale)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(f"{out}_guide.png")
    if a.reuse:
        gen = Image.open(a.reuse).convert("RGB")
    else:
        prompt = build_prompt(a.motion, n, a.cols, rows, a.describe)
        t = time.time()
        gen = call_gemini(a.model, prompt, [reference_image(sprite, a.scale), sheet], api_key(), aspect)
        print(f"{a.model}: {gen.size} in {time.time() - t:.0f}s")
        Path(f"{out}_prompt.txt").write_text(prompt)
    gen.save(f"{out}_raw.png")

    palette = kmeans_palette(sprite, a.colors)
    frames = postprocess(gen, boxes, a.cols, rows, cell, palette)
    if a.lock_first:
        f0 = np.zeros_like(frames[0])
        g0 = guide[0]
        ox, oy = (cell[0] - gw) // 2, cell[1] - gh
        f0[oy:oy + gh, ox:ox + gw] = g0
        frames[0] = f0

    Image.fromarray(np.concatenate(frames, 1)).save(f"{out}_sheet.png")
    big = []
    for f in frames:
        im = Image.new("RGBA", cell, (232, 234, 240, 255))
        fi = Image.fromarray(f)
        im.paste(fi, (0, 0), fi)
        big.append(im.convert("RGB").resize((cell[0] * 6, cell[1] * 6), Image.NEAREST))
    big[0].save(f"{out}.gif", save_all=True, append_images=big[1:], duration=100, loop=0)
    Path(f"{out}.json").write_text(json.dumps({"frame_width": cell[0], "frame_height": cell[1], "frames": n,
                                               "fps": 10, "model": a.model, "motion": a.motion,
                                               "guide": a.guide}, indent=2))
    print(f"{n} frames {cell[0]}x{cell[1]} -> {out}_sheet.png")


if __name__ == "__main__":
    main()
