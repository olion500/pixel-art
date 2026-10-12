"""Side-by-side comparison of a reference spritesheet and ours (PNG grid + synced GIF).

Usage:
  python tools/compare_anim.py ref_sheet.png ref_frame_w our_sheet.png our_frame_w -o out/cmp [--scale 6] [--fps 10]
"""
import argparse

import numpy as np
from PIL import Image, ImageDraw

BG = (232, 234, 240, 255)


def frames(path, fw):
    im = Image.open(path).convert("RGBA")
    return [im.crop((i * fw, 0, (i + 1) * fw, im.height)) for i in range(im.width // fw)]


def on_bg(f, w, h):
    c = Image.new("RGBA", (w, h), BG)
    c.paste(f, ((w - f.width) // 2, h - f.height), f)  # bottom-centered, feet aligned
    return c


def stats(fs):
    a = np.concatenate([np.asarray(f) for f in fs], 1)
    op = a[..., 3] > 0
    return f"{len(fs)}f {fs[0].width}x{fs[0].height} {len(np.unique(a[op][:, :3], axis=0))}c"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref"); ap.add_argument("ref_w", type=int)
    ap.add_argument("ours"); ap.add_argument("ours_w", type=int)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--scale", type=int, default=6)
    ap.add_argument("--fps", type=int, default=10)
    a = ap.parse_args()
    R, O = frames(a.ref, a.ref_w), frames(a.ours, a.ours_w)
    w = max(R[0].width, O[0].width) + 2
    h = max(R[0].height, O[0].height) + 2
    s, label_h = a.scale, 14

    n = max(len(R), len(O))
    grid = Image.new("RGBA", (n * w * s, 2 * h * s + 2 * label_h), (255, 255, 255, 255))
    d = ImageDraw.Draw(grid)
    for row, (name, fs) in enumerate([("Sprite Fusion (reference)  " + stats(R), R), ("ours (rig)  " + stats(O), O)]):
        y = row * (h * s + label_h)
        d.text((4, y + 1), name, fill=(0, 0, 0))
        for i, f in enumerate(fs):
            grid.paste(on_bg(f, w, h).resize((w * s, h * s), Image.NEAREST), (i * w * s, y + label_h))
    grid.convert("RGB").save(f"{a.out}.png")

    gif = []
    for i in range(n):
        c = Image.new("RGB", (2 * w * s + 8, h * s + label_h), (255, 255, 255))
        dd = ImageDraw.Draw(c)
        dd.text((4, 1), "Sprite Fusion", fill=(0, 0, 0)); dd.text((w * s + 12, 1), "ours", fill=(0, 0, 0))
        c.paste(on_bg(R[i % len(R)], w, h).convert("RGB").resize((w * s, h * s), Image.NEAREST), (0, label_h))
        c.paste(on_bg(O[i % len(O)], w, h).convert("RGB").resize((w * s, h * s), Image.NEAREST), (w * s + 8, label_h))
        gif.append(c)
    gif[0].save(f"{a.out}.gif", save_all=True, append_images=gif[1:], duration=round(1000 / a.fps), loop=0)


if __name__ == "__main__":
    main()
