"""Turn a single sprite image into a pixel-perfect animated sprite.

Usage:
  python tools/animate_sprite.py <image> [-a idle bounce sway float hit walk] [-o out_dir]
                                  [--size 32] [--colors 16] [--frames 8] [--fps 8] [--scale 8]

Pipeline:
  1. Prepare: remove a flat background (flood fill from the border), and if the input is
     a large / AI-made image, snap it down to a pixel grid (block majority vote) and
     quantize colors with k-means. Native pixel art (<=128px) is kept as-is.
  2. Animate: every motion moves whole pixels (integer offsets, nearest-neighbour), so the
     grid and palette never get blurred.
  3. Export per animation: horizontal spritesheet PNG, upscaled GIF preview, and JSON metadata.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

PAD = 4  # transparent margin so motion is not clipped


# ---------------------------------------------------------------- prepare

def remove_flat_background(a, tol=24):
    """Make the border-connected region matching the corner color transparent."""
    if (a[..., 3] < 255).any():
        return a
    h, w = a.shape[:2]
    corners = np.array([a[0, 0, :3], a[0, -1, :3], a[-1, 0, :3], a[-1, -1, :3]], int)
    if np.abs(corners - corners[0]).max() > tol:
        return a  # no single flat background color
    bg = corners.mean(0)
    similar = np.abs(a[..., :3].astype(int) - bg).max(-1) <= tol
    mask = np.zeros((h, w), bool)
    stack = [(y, x) for x in range(w) for y in (0, h - 1)] + [(y, x) for y in range(h) for x in (0, w - 1)]
    while stack:
        y, x = stack.pop()
        if 0 <= y < h and 0 <= x < w and not mask[y, x] and similar[y, x]:
            mask[y, x] = True
            stack += [(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)]
    out = a.copy()
    out[mask, 3] = 0
    return out


def estimate_pixel_size(a):
    """Median spacing between edge peaks (same idea as Pixel Snapper)."""
    g = a[..., :3].astype(float) @ [0.299, 0.587, 0.114] * (a[..., 3] > 0)
    steps = []
    for prof in (np.abs(np.diff(g, axis=1)).sum(0), np.abs(np.diff(g, axis=0)).sum(1)):
        thr = prof.max() * 0.2
        peaks = [i for i in range(1, len(prof) - 1) if prof[i] > thr and prof[i] >= prof[i - 1] and prof[i] > prof[i + 1]]
        clean = [p for k, p in enumerate(peaks) if k == 0 or p - peaks[k - 1] > 3]
        if len(clean) > 2:
            steps.append(float(np.median(np.diff(clean))))
    return max(1.0, float(np.mean(steps))) if steps else None


def kmeans_quantize(a, k, iters=15, seed=42):
    opaque = a[..., 3] > 0
    px = a[opaque][:, :3].astype(float)
    uniq = np.unique(px, axis=0)
    if len(uniq) <= k:
        return a
    rng = np.random.default_rng(seed)
    centers = uniq[rng.choice(len(uniq), k, replace=False)]
    for _ in range(iters):
        labels = ((px[:, None] - centers[None]) ** 2).sum(-1).argmin(1)
        for j in range(k):
            if (labels == j).any():
                centers[j] = px[labels == j].mean(0)
    out = a.copy()
    out[opaque, :3] = np.round(centers[labels]).astype(np.uint8)
    return out


def block_downscale(a, out_w, out_h):
    """Each output pixel = the most common color in its source block (keeps dithering crisp)."""
    h, w = a.shape[:2]
    ys = np.linspace(0, h, out_h + 1).astype(int)
    xs = np.linspace(0, w, out_w + 1).astype(int)
    out = np.zeros((out_h, out_w, 4), np.uint8)
    for i in range(out_h):
        for j in range(out_w):
            block = a[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].reshape(-1, 4)
            if (block[:, 3] > 127).mean() < 0.5:
                continue  # mostly transparent -> transparent
            block = block[block[:, 3] > 127]
            vals, counts = np.unique(block, axis=0, return_counts=True)
            out[i, j] = vals[counts.argmax()]
            out[i, j, 3] = 255
    return out


def crop_to_content(a):
    ys, xs = np.nonzero(a[..., 3])
    if len(ys) == 0:
        raise SystemExit("image is fully transparent")
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def prepare(path, size=None, colors=None):
    a = np.asarray(Image.open(path).convert("RGBA")).copy()
    a = remove_flat_background(a)
    a[..., 3] = np.where(a[..., 3] > 127, 255, 0)  # pixel art uses binary alpha
    big = max(a.shape[:2]) > 128
    if size or big:
        if colors is None:
            colors = 16
        a = kmeans_quantize(a, colors)
        a = crop_to_content(a)
        h, w = a.shape[:2]
        if size:
            s = size / max(h, w)
        else:
            step = estimate_pixel_size(a) or max(h, w) / 64
            s = 1 / step
        a = block_downscale(a, max(1, round(w * s)), max(1, round(h * s)))
    elif colors:
        a = kmeans_quantize(a, colors)
    return crop_to_content(a)


# ---------------------------------------------------------------- animate

def shift_rows(sprite, dx_per_row):
    """Shift each row horizontally by an integer amount (used for sway / walk lean)."""
    out = np.zeros_like(sprite)
    w = sprite.shape[1]
    for y, dx in enumerate(dx_per_row):
        dx = int(dx)
        src = sprite[y, max(0, -dx):w - max(0, dx)]
        out[y, max(0, dx):max(0, dx) + src.shape[0]] = src
    return out


def resize_nearest(sprite, w, h):
    return np.asarray(Image.fromarray(sprite).resize((max(1, w), max(1, h)), Image.NEAREST))


def place(canvas_shape, sprite, dx=0, dy=0):
    """Paste sprite bottom-centered on the canvas, offset by (dx, dy)."""
    H, W = canvas_shape
    c = np.zeros((H, W, 4), np.uint8)
    h, w = sprite.shape[:2]
    x0 = (W - w) // 2 + int(dx)
    y0 = H - PAD - h + int(dy)
    ys, xs = slice(max(0, y0), min(H, y0 + h)), slice(max(0, x0), min(W, x0 + w))
    sub = sprite[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
    m = sub[..., 3] > 0
    c[ys, xs][m] = sub[m]
    return c


def anim_idle(s, n):
    """Breathing: upper body sinks 1px while the feet stay planted."""
    h = s.shape[0]
    waist = int(h * 0.6)
    frames = []
    for i in range(n):
        d = 1 if math.sin(2 * math.pi * i / n) < 0 else 0
        f = s.copy()
        if d:
            f[:waist] = 0
            f[d:waist + d] = np.where(s[:waist, ..., 3:] > 0, s[:waist], f[d:waist + d])
        frames.append((f, 0, 0))
    return frames


def anim_bounce(s, n):
    """Jump with squash on landing and stretch in the air."""
    h, w = s.shape[:2]
    jump = max(2, h // 4)
    frames = []
    for i in range(n):
        t = i / n
        y = -round(jump * math.sin(math.pi * t))
        if i == 0:  # landing squash
            f = resize_nearest(s, w + max(1, w // 8), h - max(1, h // 8))
        elif abs(t - 0.25) < 1 / n or abs(t - 0.75) < 1 / n:  # stretch while moving fast
            f = resize_nearest(s, w - max(1, w // 10), h + max(1, h // 10))
        else:
            f = s
        frames.append((f, 0, y))
    return frames


def anim_sway(s, n):
    """Wind sway: top moves, base anchored (plants, flags, hair)."""
    h = s.shape[0]
    amp = max(1, h // 10)
    frames = []
    for i in range(n):
        k = math.sin(2 * math.pi * i / n)
        dx = [round(amp * k * ((h - 1 - y) / (h - 1)) ** 1.5) for y in range(h)]
        frames.append((shift_rows(s, dx), 0, 0))
    return frames


def anim_float(s, n):
    """Hovering item / pickup: smooth up-down bob."""
    amp = max(1, s.shape[0] // 10)
    return [(s, 0, -amp - round(amp * math.sin(2 * math.pi * i / n))) for i in range(n)]


def anim_hit(s, n):
    """Damage reaction: white flash + knockback, then settle."""
    frames = []
    knock = [0, -2, -3, -2, -1, -1, 0, 0]
    for i in range(n):
        f = s.copy()
        if i in (0, 2):
            f[f[..., 3] > 0, :3] = 255
        frames.append((f, knock[min(i * 8 // n, 7)], 0))
    return frames


def anim_walk(s, n):
    """Cheap walk cycle: 1px bob + alternating lean of the legs (bottom third)."""
    h = s.shape[0]
    legs = int(h * 0.66)
    frames = []
    for i in range(n):
        phase = math.sin(2 * math.pi * i / n)
        lean = round(phase * max(1, h // 16))
        dx = [0] * legs + [round(lean * (y - legs) / max(1, h - 1 - legs)) for y in range(legs, h)]
        f = shift_rows(s, dx)
        bob = -1 if abs(phase) > 0.7 else 0
        frames.append((f, 0, bob))
    return frames


ANIMATIONS = {
    "idle": anim_idle, "bounce": anim_bounce, "sway": anim_sway,
    "float": anim_float, "hit": anim_hit, "walk": anim_walk,
}


# ---------------------------------------------------------------- export

def render(sprite, name, n):
    frames = ANIMATIONS[name](sprite, n)
    H = max(f.shape[0] for f, _, _ in frames) + 2 * PAD + max(0, -min(dy for _, _, dy in frames))
    W = max(f.shape[1] for f, _, _ in frames) + 2 * PAD + 2 * max(abs(dx) for _, dx, _ in frames)
    return [place((H, W), f, dx, dy) for f, dx, dy in frames]


def export(frames, out_dir, stem, name, fps, scale):
    h, w = frames[0].shape[:2]
    sheet = np.concatenate(frames, axis=1)
    sheet_path = out_dir / f"{stem}_{name}_sheet.png"
    Image.fromarray(sheet).save(sheet_path)

    big = [Image.fromarray(f).resize((w * scale, h * scale), Image.NEAREST) for f in frames]
    gif_path = out_dir / f"{stem}_{name}.gif"
    big[0].save(gif_path, save_all=True, append_images=big[1:], duration=round(1000 / fps),
                loop=0, disposal=2, transparency=0, optimize=False)

    meta = {"animation": name, "frame_width": w, "frame_height": h, "frames": len(frames),
            "fps": fps, "sheet": sheet_path.name, "layout": "horizontal"}
    (out_dir / f"{stem}_{name}.json").write_text(json.dumps(meta, indent=2))
    return sheet_path, gif_path


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image")
    p.add_argument("-a", "--anim", nargs="+", default=["idle", "bounce", "sway", "float", "hit", "walk"],
                   choices=ANIMATIONS)
    p.add_argument("-o", "--out", default="out")
    p.add_argument("--size", type=int, help="target sprite size (longest side) for large/AI images")
    p.add_argument("--colors", type=int, help="palette size (default: keep for pixel art, 16 for large images)")
    p.add_argument("--frames", type=int, default=8)
    p.add_argument("--fps", type=int, default=8)
    p.add_argument("--scale", type=int, default=8, help="GIF preview upscale factor")
    args = p.parse_args()

    sprite = prepare(args.image, args.size, args.colors)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.image).stem
    Image.fromarray(sprite).save(out_dir / f"{stem}_base.png")
    n_colors = len(np.unique(sprite[sprite[..., 3] > 0][:, :3], axis=0))
    print(f"sprite {sprite.shape[1]}x{sprite.shape[0]}, {n_colors} colors")
    for name in args.anim:
        sheet, gif = export(render(sprite, name, args.frames), out_dir, stem, name, args.fps, args.scale)
        print(f"{name:7s} -> {sheet}  {gif}")


if __name__ == "__main__":
    main()
