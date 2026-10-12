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


def fill_seams(a):
    """Close cracks between independently transformed parts.

    Any transparent pixel not reachable from the canvas border is an interior hole;
    it takes the color of an opaque neighbour (grown inward until the hole is filled).
    """
    out = a.copy()
    m = out[..., 3] > 0
    h, w = m.shape
    outside = np.zeros_like(m)
    stack = [(y, x) for y in range(h) for x in (0, w - 1)] + [(y, x) for x in range(w) for y in (0, h - 1)]
    while stack:
        y, x = stack.pop()
        if 0 <= y < h and 0 <= x < w and not m[y, x] and not outside[y, x]:
            outside[y, x] = True
            stack += [(y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)]
    holes = ~m & ~outside
    while holes.any():
        progressed = False
        for y, x in zip(*np.nonzero(holes)):
            for ny, nx in ((y + 1, x), (y, x + 1), (y - 1, x), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and out[ny, nx, 3] > 0 and not holes[ny, nx]:
                    out[y, x] = out[ny, nx]
                    holes[y, x] = False
                    progressed = True
                    break
        if not progressed:
            break
    return out


def drop_specks(a, min_size=4):
    """Remove tiny detached pixel islands (leftovers from cutting parts apart)."""
    m = a[..., 3] > 0
    seen = np.zeros_like(m)
    out = a.copy()
    h, w = m.shape
    for y0 in range(h):
        for x0 in range(w):
            if not m[y0, x0] or seen[y0, x0]:
                continue
            comp, stack = [], [(y0, x0)]
            seen[y0, x0] = True
            while stack:
                y, x = stack.pop()
                comp.append((y, x))
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < h and 0 <= nx < w and m[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(comp) < min_size:
                for y, x in comp:
                    out[y, x] = 0
    return out


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
        self.sprite = sprite
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

    def stamp(self, name, rot=0.0):
        """Original pixels (shoe, fist...) cut from the source, optionally rotated about their anchor."""
        st = self.spec["stamps"][name]
        x0, y0, x1, y1 = st["rect"]
        img = self.sprite[y0:y1 + 1, x0:x1 + 1].copy()
        ax, ay = st["anchor"][0] - x0, st["anchor"][1] - y0
        if rot:
            pad = 6
            img = np.pad(img, ((pad, pad), (pad, pad), (0, 0)))
            img = rotsprite(img, rot, (ax + pad, ay + pad))
            ax, ay = ax + pad, ay + pad
        return img, (ax, ay)

    def draw_limb(self, pts, width, stamp=None, stamp_rot=0.0):
        """Outlined, shaded capsule chain through pts (canvas coords) with a stamp at the end."""
        c = self.colors
        layer = np.zeros((self.H, self.W, 4), np.uint8)
        segs = list(zip(pts[:-1], pts[1:]))
        for y in range(self.H):
            for x in range(self.W):
                best = None
                for (sx, sy), (ex, ey) in segs:
                    vx, vy = ex - sx, ey - sy
                    L2 = vx * vx + vy * vy or 1
                    k = max(0, min(1, ((x - sx) * vx + (y - sy) * vy) / L2))
                    d = math.hypot(x - (sx + k * vx), y - (sy + k * vy))
                    if best is None or d < best[0]:
                        side = ((x - sx) * -vy + (y - sy) * vx) / math.sqrt(L2)
                        best = (d, side, vy)
                if best and best[0] < width:
                    # light on the side facing up / forward, dark on the other
                    lit = best[1] < -0.4 if best[2] >= 0 else best[1] > 0.4
                    layer[y, x, :3] = c["limb_light"] if lit else c["limb"]
                    layer[y, x, 3] = 255
        outline(layer, c["outline"])
        if stamp:
            img, (ax, ay) = self.stamp(stamp, stamp_rot)
            ex, ey = pts[-1]
            fx, fy = int(round(ex - ax)), int(round(ey - ay))
            st = np.zeros_like(layer)
            h, w = img.shape[:2]
            ys = slice(max(0, fy), min(self.H, fy + h))
            xs = slice(max(0, fx), min(self.W, fx + w))
            st[ys, xs] = img[ys.start - fy:ys.stop - fy, xs.start - fx:xs.stop - fx]
            over(layer, st)
        return layer

    def pose(self, kf, t):
        """kf: per-part transforms + optional torso transform and skeletal limbs; t: loop phase 0..1."""
        g = kf.get("_all", {})
        gdx, gdy = g.get("dx", 0), g.get("dy", 0)
        torso = kf.get("torso", {})
        pivot = self.p(self.spec["pivots"]["torso"])
        trot = torso.get("rot", 0)
        tdx, tdy = torso.get("dx", 0) + gdx, torso.get("dy", 0) + gdy
        hidden = set(kf.get("hide", []))

        def tf(pt):  # sprite coords on the torso -> canvas coords after torso transform
            x, y = self.p(pt) - pivot
            r = math.radians(trot)
            return (pivot[0] + x * math.cos(r) - y * math.sin(r) + tdx,
                    pivot[1] + x * math.sin(r) + y * math.cos(r) + tdy)

        layers = {}
        for name, layer in self.parts.items():
            tr = kf.get(name, {})
            if name in hidden or "hide" in tr:
                continue
            out = layer
            if name in self.spec.get("cloth", {}):
                cl = self.spec["cloth"][name]
                out = self.flutter(out, t + tr.get("phase", 0), tr.get("amp", cl["amp"]),
                                   self.off[0] + cl["root_x"], cl["length"], tr.get("trail", 0))
            if "squash" in tr:
                sy, sx = tr["squash"]
                out = squash(out, sy, sx, self.off[1] + tr.get("anchor_y", self.spec["floor_y"] + 1))
            if tr.get("lean"):  # shift only above the waist so the hips stay connected
                waist = self.off[1] + self.spec["waist_y"]
                top = out.copy(); top[waist:] = 0
                out = out.copy(); out[:waist] = 0
                over(out, shift(top, tr["lean"], 0))
            dx, dy = tr.get("dx", 0), tr.get("dy", 0)
            follow = self.spec.get("follow", {}).get(name)
            if follow:  # ride an anchor on the torso, rotating only by a fraction of the torso (head, cloth)
                anchor, frac = follow
                ax, ay = self.p(self.spec["anchors"][anchor])
                if trot * frac:
                    out = rotsprite(out, trot * frac, (ax, ay))
                fx, fy = tf(self.spec["anchors"][anchor])
                dx, dy = dx + round(fx - ax), dy + round(fy - ay)
            elif name in self.spec["torso_group"]:
                if trot:
                    out = rotsprite(out, trot, pivot)
                dx, dy = dx + tdx, dy + tdy
            else:
                dx, dy = dx + gdx, dy + gdy
            layers[name] = shift(out, dx, dy)

        floor = self.off[1] + self.spec["ankle_floor_y"]
        for lb in kf.get("limbs", []):
            root = tf(self.spec["anchors"][lb["from"]])
            pts = [root] + [(root[0] + rx, root[1] + ry) for rx, ry in lb["rel"]]
            if lb.get("ground"):
                pts[-1] = (pts[-1][0], floor + gdy)
            layer = self.draw_limb(pts, lb.get("width", 1.2), lb.get("stamp"), lb.get("stamp_rot", 0))
            over(layers.setdefault(lb["layer"], np.zeros((self.H, self.W, 4), np.uint8)), layer)

        frame = np.zeros((self.H, self.W, 4), np.uint8)
        for name in self.order:
            if name in layers:
                over(frame, layers[name])
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
        n = len(anim["keyframes"])
        frames = [drop_specks(fill_seams(snap(rig.pose(kf, i / n), palette))) for i, kf in enumerate(anim["keyframes"])]
        export(frames, Path(f"{args.out}_{anim_name}"), anim.get("fps", 10))
        print(f"{anim_name}: {n} frames {anim['canvas'][1]}x{anim['canvas'][0]}, palette {len(palette)}")


if __name__ == "__main__":
    main()
