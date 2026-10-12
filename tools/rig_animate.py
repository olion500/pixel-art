"""Rig-based pixel-art animation: split a sprite into parts and pose each part per frame.

This is the "no generative model" approximation of Sprite Fusion's `animate`:
  1. Quantize the source to a small palette (their outputs carry 13-17 colors).
  2. Cut the sprite into parts with a rig file (JSON): rect masks + pivots.
  3. Each animation is a list of keyframes that move / squash / rotate parts, flutter
     cloth (scarf, cape), and redraw a limb as an outlined thick segment when it has to
     leave its original silhouette (e.g. a punch).
  4. Rotation uses RotSprite-style sampling (Scale2x x3 -> rotate nearest -> center sample),
     then every pixel is snapped back to the palette, so no new colors or blur appear.

Usage:
  python tools/rig_animate.py samples/ninja/ninja-base.png samples/ninja/rig.json -o out/ninja
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


# ------------------------------------------------------------ palette

def kmeans_palette(a, k, iters=20, seed=0):
    px = a[a[..., 3] > 0][:, :3].astype(float)
    uniq = np.unique(px, axis=0)
    if len(uniq) <= k:
        return uniq.astype(np.uint8)
    rng = np.random.default_rng(seed)
    # k-means++ init keeps rare accent colors (visor, scarf) alive
    centers = [uniq[rng.integers(len(uniq))]]
    for _ in range(k - 1):
        d = np.min([((uniq - c) ** 2).sum(1) for c in centers], axis=0)
        centers.append(uniq[rng.choice(len(uniq), p=d / d.sum())])
    centers = np.array(centers)
    for _ in range(iters):
        lab = ((px[:, None] - centers[None]) ** 2).sum(-1).argmin(1)
        for j in range(k):
            if (lab == j).any():
                centers[j] = px[lab == j].mean(0)
    return np.round(centers).astype(np.uint8)


def snap(a, palette):
    out = a.copy()
    m = out[..., 3] > 0
    px = out[m][:, :3].astype(int)
    idx = ((px[:, None] - palette[None].astype(int)) ** 2).sum(-1).argmin(1)
    out[m, :3] = palette[idx]
    out[..., 3] = np.where(m, 255, 0)
    out[~m] = 0
    return out


# ------------------------------------------------------------ pixel ops

def scale2x(a):
    """EPX / Scale2x on RGBA, keeps hard pixel-art edges when upscaling."""
    h, w = a.shape[:2]
    p = np.pad(a, ((1, 1), (1, 1), (0, 0)), mode="edge")
    B, D, E, F, H = p[:-2, 1:-1], p[1:-1, :-2], p[1:-1, 1:-1], p[1:-1, 2:], p[2:, 1:-1]
    eq = lambda x, y: (x == y).all(-1)
    e0 = np.where((eq(D, B) & ~eq(B, F) & ~eq(D, H))[..., None], D, E)
    e1 = np.where((eq(B, F) & ~eq(B, D) & ~eq(F, H))[..., None], F, E)
    e2 = np.where((eq(D, H) & ~eq(D, B) & ~eq(H, F))[..., None], D, E)
    e3 = np.where((eq(H, F) & ~eq(D, H) & ~eq(B, F))[..., None], F, E)
    out = np.zeros((h * 2, w * 2, 4), a.dtype)
    out[0::2, 0::2], out[0::2, 1::2], out[1::2, 0::2], out[1::2, 1::2] = e0, e1, e2, e3
    return out


def rotsprite(a, deg, pivot):
    """Rotate a part around pivot (x, y) without inventing colors (RotSprite-like)."""
    if abs(deg) < 1e-3:
        return a
    big = scale2x(scale2x(scale2x(a)))
    im = Image.fromarray(big).rotate(-deg, resample=Image.NEAREST,
                                     center=((pivot[0] + 0.5) * 8, (pivot[1] + 0.5) * 8))
    return np.asarray(im)[4::8, 4::8].copy()


def shift(a, dx, dy):
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    out[yd, xd] = a[ys, xs]
    return out


def squash(a, sy, sx, anchor_y):
    """Scale a part around a horizontal anchor line (nearest), e.g. legs compressing to the floor."""
    h, w = a.shape[:2]
    ys, xs = np.nonzero(a[..., 3])
    if len(ys) == 0:
        return a
    cx = (xs.min() + xs.max() + 1) / 2
    out = np.zeros_like(a)
    for y in range(h):
        for x in range(w):
            sy_src = anchor_y + (y + 0.5 - anchor_y) / sy
            sx_src = cx + (x + 0.5 - cx) / sx
            iy, ix = int(math.floor(sy_src)), int(math.floor(sx_src))
            if 0 <= iy < h and 0 <= ix < w:
                out[y, x] = a[iy, ix]
    return out


def over(dst, src):
    m = src[..., 3] > 0
    dst[m] = src[m]
    return dst


def outline(layer, color):
    m = layer[..., 3] > 0
    g = np.zeros_like(m)
    g[1:] |= m[:-1]; g[:-1] |= m[1:]; g[:, 1:] |= m[:, :-1]; g[:, :-1] |= m[:, 1:]
    ring = g & ~m
    layer[ring, :3] = color
    layer[ring, 3] = 255
    return layer


# ------------------------------------------------------------ rig

class Rig:
    def __init__(self, sprite, spec, canvas, offset):
        self.spec = spec
        self.H, self.W = canvas
        base = np.zeros((self.H, self.W, 4), np.uint8)
        ox, oy = offset
        h, w = sprite.shape[:2]
        base[oy:oy + h, ox:ox + w] = sprite
        self.off = np.array(offset)
        self.parts = {}
        taken = np.zeros((self.H, self.W), bool)
        for name, rects in spec["parts"].items():  # earlier parts win
            m = np.zeros_like(taken)
            for x0, y0, x1, y1 in rects:
                m[oy + y0:oy + y1 + 1, ox + x0:ox + x1 + 1] = True
            m &= ~taken & (base[..., 3] > 0)
            taken |= m
            layer = np.zeros_like(base)
            layer[m] = base[m]
            self.parts[name] = layer
        rest = np.zeros_like(base)
        rest[~taken] = base[~taken]
        self.parts["body"] = rest
        self.order = spec["draw_order"]
        self.colors = {k: tuple(v) for k, v in spec["colors"].items()}

    def p(self, xy):
        return np.array(xy) + self.off

    def flutter(self, layer, t, amp, root_x, length, trail=0):
        """Cloth wave along x: each column moves vertically, more toward the free end.

        Sampled per destination column (inverse mapping) so trailing never tears the cloth.
        """
        out = np.zeros_like(layer)
        span = np.nonzero(layer[..., 3].any(0))[0]
        if len(span) == 0:
            return out
        for nx in range(self.W):
            d = max(0.0, (root_x - nx) / length)
            x = nx + round(trail * d)
            if not (span.min() <= x <= span.max()):
                continue
            ds = max(0.0, (root_x - x) / length)
            dy = round(amp * ds ** 1.2 * math.sin(2 * math.pi * t - ds * 3.0))
            over(out[:, nx:nx + 1], shift(layer[:, x:x + 1], 0, dy))
        return out

    def limb(self, shoulder, hand, fist, width=1.1):
        """Redraw an arm as an outlined capsule from shoulder to hand and stamp the fist."""
        c = self.colors
        layer = np.zeros((self.H, self.W, 4), np.uint8)
        (sx, sy), (hx, hy) = shoulder, hand
        ex, ey = hx - sx, hy - sy
        L2 = ex * ex + ey * ey or 1
        for y in range(self.H):
            for x in range(self.W):
                k = max(0, min(1, ((x - sx) * ex + (y - sy) * ey) / L2))
                d = math.hypot(x - (sx + k * ex), y - (sy + k * ey))
                if d < width:
                    # light edge on the upper side of the limb
                    nx, ny = -ey, ex
                    side = ((x - sx) * nx + (y - sy) * ny) / math.sqrt(L2)
                    layer[y, x, :3] = c["limb_light"] if side < -0.5 else c["limb"]
                    layer[y, x, 3] = 255
        outline(layer, c["outline"])
        if fist is not None:
            fh, fw = fist.shape[:2]
            fx, fy = int(round(hx - fw / 2)), int(round(hy - fh / 2))
            stamp = np.zeros_like(layer)
            ys, xs = slice(max(0, fy), min(self.H, fy + fh)), slice(max(0, fx), min(self.W, fx + fw))
            stamp[ys, xs] = fist[ys.start - fy:ys.stop - fy, xs.start - fx:xs.stop - fx]
            over(layer, stamp)
        return layer

    def pose(self, kf, t):
        """kf: dict of per-part transforms for this frame; t: loop phase 0..1."""
        layers = {}
        for name, layer in self.parts.items():
            tr = kf.get(name, {})
            g = kf.get("_all", {})
            out = layer
            if name in self.spec.get("cloth", {}):
                cl = self.spec["cloth"][name]
                out = self.flutter(out, t + tr.get("phase", 0), tr.get("amp", cl["amp"]),
                                   self.off[0] + cl["root_x"], cl["length"], tr.get("trail", 0))
            if "hide" in tr:
                out = np.zeros_like(out)
            if "squash" in tr:
                sy, sx = tr["squash"]
                out = squash(out, sy, sx, self.off[1] + tr.get("anchor_y", self.spec["floor_y"] + 1))
            if "rot" in tr:
                out = rotsprite(out, tr["rot"], self.p(tr.get("pivot", self.spec["pivots"].get(name, [16, 16]))))
            if tr.get("lean"):  # shift only above the waist so the hips stay connected
                waist = self.off[1] + self.spec["waist_y"]
                top = out.copy(); top[waist:] = 0
                out = out.copy(); out[:waist] = 0
                over(out, shift(top, tr["lean"], 0))
            dx, dy = tr.get("dx", 0) + g.get("dx", 0), tr.get("dy", 0) + g.get("dy", 0)
            layers[name] = shift(out, dx, dy)
        if "limb" in kf:
            lb = kf["limb"]
            fist = self.fist
            g = kf.get("_all", {})
            sh = self.p(lb["shoulder"]) + [g.get("dx", 0), g.get("dy", 0)]
            hd = self.p(lb["hand"]) + [g.get("dx", 0), g.get("dy", 0)]
            layers[lb.get("layer", "limb")] = self.limb(sh, hd, fist, lb.get("width", 1.1))
        frame = np.zeros((self.H, self.W, 4), np.uint8)
        for name in self.order:
            if name in layers:
                over(frame, layers[name])
        if "_rot" in kf:  # whole-body rotation (jumps, flips)
            frame = rotsprite(frame, kf["_rot"], self.p(self.spec["pivots"]["_center"]))
        return frame


# ------------------------------------------------------------ export

def export(frames, out, fps, scale=6, bg=(232, 234, 240)):
    out.parent.mkdir(parents=True, exist_ok=True)
    h, w = frames[0].shape[:2]
    Image.fromarray(np.concatenate(frames, 1)).save(f"{out}_sheet.png")
    big = []
    for f in frames:
        im = Image.new("RGBA", (w, h), bg + (255,))
        fi = Image.fromarray(f)
        im.paste(fi, (0, 0), fi)
        big.append(im.convert("RGB").resize((w * scale, h * scale), Image.NEAREST))
    big[0].save(f"{out}.gif", save_all=True, append_images=big[1:], duration=round(1000 / fps), loop=0)
    Path(f"{out}.json").write_text(json.dumps(
        {"frame_width": w, "frame_height": h, "frames": len(frames), "fps": fps,
         "sheet": Path(f"{out}_sheet.png").name, "layout": "horizontal"}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("rig")
    ap.add_argument("-o", "--out", default="out/rig")
    ap.add_argument("--anim", nargs="*", help="subset of animations in the rig file")
    args = ap.parse_args()

    spec = json.loads(Path(args.rig).read_text())
    src = np.asarray(Image.open(args.image).convert("RGBA")).copy()
    src[..., 3] = np.where(src[..., 3] > 127, 255, 0)
    palette = kmeans_palette(src, spec.get("colors_k", 16))
    sprite = snap(src, palette)
    for anim_name, anim in spec["animations"].items():
        if args.anim and anim_name not in args.anim:
            continue
        rig = Rig(sprite, spec, anim["canvas"], anim["offset"])
        fx0, fy0, fx1, fy1 = spec["fist_rect"]
        ox, oy = anim["offset"]
        rig.fist = rig.parts.get(spec.get("fist_part", "front_arm"), sprite)[oy + fy0:oy + fy1 + 1, ox + fx0:ox + fx1 + 1].copy() \
            if spec.get("fist_part") else None
        n = len(anim["keyframes"])
        frames = [snap(rig.pose(kf, i / n), palette) for i, kf in enumerate(anim["keyframes"])]
        export(frames, Path(f"{args.out}_{anim_name}"), anim.get("fps", 10))
        print(f"{anim_name}: {n} frames {anim['canvas'][1]}x{anim['canvas'][0]}, palette {len(palette)}")


if __name__ == "__main__":
    main()
