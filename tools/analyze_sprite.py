"""Inspect a pixel-art image or animation: size, frames, colors, alpha, per-frame change.

Usage: python tools/analyze_sprite.py <image> [--sheet out.png] [--scale 4]

--sheet writes a contact sheet of sampled frames composited over a checkerboard,
which makes the alpha channel and the step-by-step evolution visible.
"""
import argparse

import numpy as np
from PIL import Image


def frame_stats(im):
    prev = None
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        a = np.asarray(im.convert("RGBA")).astype(int)
        colors = len(np.unique(a.reshape(-1, 4), axis=0))
        alpha_levels = len(np.unique(a[..., 3]))
        transparent = (a[..., 3] == 0).mean()
        delta = 0.0 if prev is None else np.abs(a - prev).mean()
        prev = a
        yield i, colors, alpha_levels, transparent, delta


def checker(w, h, cell=4):
    ck = np.indices((h, w)).sum(0) // cell % 2
    return Image.fromarray(np.where(ck[..., None] == 1, 200, 240).repeat(3, 2).astype("uint8"))


def contact_sheet(im, n=8, scale=4):
    total = getattr(im, "n_frames", 1)
    idx = sorted({round(k * (total - 1) / max(n - 1, 1)) for k in range(n)})
    w, h = im.size
    sheet = Image.new("RGB", (w * len(idx), h))
    for k, i in enumerate(idx):
        im.seek(i)
        f = im.convert("RGBA")
        bg = checker(w, h)
        bg.paste(f, (0, 0), f)
        sheet.paste(bg, (k * w, 0))
    return sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST), idx


def main():
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("--sheet")
    p.add_argument("--scale", type=int, default=4)
    args = p.parse_args()

    im = Image.open(args.image)
    print(f"{args.image}: size={im.size} mode={im.mode} frames={getattr(im, 'n_frames', 1)}")
    print("frame  colors  alpha_levels  transparent  mean_abs_delta")
    for i, c, al, tr, d in frame_stats(im):
        print(f"{i:5d}  {c:6d}  {al:12d}  {tr:11.2f}  {d:14.1f}")

    if args.sheet:
        sheet, idx = contact_sheet(im, scale=args.scale)
        sheet.save(args.sheet)
        print(f"contact sheet of frames {idx} -> {args.sheet}")


if __name__ == "__main__":
    main()
