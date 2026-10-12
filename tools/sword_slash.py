"""Give a character a sword and animate an overhead slash, pixel-perfect.

Usage:
  python tools/sword_slash.py samples/hero.png -o out/hero_slash
         [--shoulder 21,18] [--hand 22,23] [--erase-arm 21,17,23,25] [--scale 8]

The input is a native-resolution sprite (e.g. 32x32). An upscaled image is fine too:
it is reduced back to its pixel grid first (pass --pixel-size if auto-detection fails).

How it works:
  * The character's sword arm (--erase-arm box) is removed and redrawn every frame as a
    thick line from --shoulder to the hand, so the arm actually follows the sword.
  * The sword is rasterized procedurally at any angle in sword-local coordinates
    (along/perpendicular to the blade), then given a 1px dark outline - no rotation of a
    bitmap, so no blurry or broken pixels.
  * The slash smear is a crescent between the previous and current blade angle.
  * Frames have per-frame durations (anticipation is held, the swing is fast).
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

OUTLINE = (0, 0, 0)
ARM_FILL, ARM_LIGHT = (80, 80, 96), (144, 152, 168)
FIST, FIST_DARK = (136, 136, 152), (96, 96, 120)
BLADE, BLADE_DARK, BLADE_HI = (216, 224, 240), (128, 136, 168), (255, 255, 255)
GUARD, GUARD_DARK, GRIP = (232, 176, 48), (160, 104, 24), (96, 48, 24)
SMEAR_OUT, SMEAR_IN = (255, 255, 255), (168, 216, 248)

# canvas around the 32x32 character
CANVAS_W, CANVAS_H, OX, OY = 60, 54, 14, 14

# (blade angle deg clockwise from up, hand xy in sprite coords, body lean dx,
#  smear from-angle or None, sword drawn behind body?, duration ms)
KEYFRAMES = [
    (135, (22, 23), 0, None, False, 160),   # ready, sword held low
    (35, (24, 19), 0, None, False, 90),     # raise
    (5, (25, 15), -1, None, False, 90),     # wind-up beside the head
    (-15, (25, 14), -1, None, False, 220),  # anticipation hold
    (55, (25, 17), 1, -15, False, 50),      # swing
    (115, (25, 21), 1, 0, False, 50),       # swing, biggest smear
    (145, (24, 23), 1, 60, False, 90),      # follow-through
    (150, (24, 23), 1, None, False, 140),   # settle
    (135, (23, 23), 0, None, False, 160),   # recover
]


def load_sprite(path, pixel_size=None):
    a = np.asarray(Image.open(path).convert("RGBA"))
    if max(a.shape[:2]) > 64:
        if not pixel_size:
            row = a[a.shape[0] // 2, :, :3].astype(int)
            edges = np.nonzero(np.abs(np.diff(row, axis=0)).sum(1))[0]
            pixel_size = int(np.min(np.diff(edges))) if len(edges) > 1 else 1
        p = pixel_size
        a = a[p // 2::p, p // 2::p]
    a = a.copy()
    a[..., 3] = np.where(a[..., 3] > 127, 255, 0)
    return a


def direction(deg):
    r = math.radians(deg)
    return math.sin(r), -math.cos(r)


def put(layer, x, y, color):
    if 0 <= x < layer.shape[1] and 0 <= y < layer.shape[0]:
        layer[y, x, :3] = color
        layer[y, x, 3] = 255


def add_outline(layer):
    """1px dark outline (4-neighbourhood) around everything opaque in the layer."""
    m = layer[..., 3] > 0
    grow = np.zeros_like(m)
    grow[1:] |= m[:-1]
    grow[:-1] |= m[1:]
    grow[:, 1:] |= m[:, :-1]
    grow[:, :-1] |= m[:, 1:]
    ring = grow & ~m
    layer[ring, :3] = OUTLINE
    layer[ring, 3] = 255
    return layer


def draw_sword(angle, px, py, length=13):
    """Rasterize the sword in blade-local coordinates around the fist center (px, py)."""
    layer = np.zeros((CANVAS_H, CANVAS_W, 4), np.uint8)
    ux, uy = direction(angle)
    vx, vy = -uy, ux  # perpendicular
    for y in range(CANVAS_H):
        for x in range(CANVAS_W):
            dx, dy = x + 0.5 - px, y + 0.5 - py
            t = dx * ux + dy * uy      # along the blade
            s = dx * vx + dy * vy      # across the blade
            c = None
            if -3.2 <= t < -2 and abs(s) < 0.9:
                c = GUARD                                  # pommel
            elif -2 <= t < 1.5 and abs(s) < 0.6:
                c = GRIP
            elif 1.5 <= t < 2.6 and abs(s) < 2.6:
                c = GUARD if s < 0.3 else GUARD_DARK       # cross-guard
            elif 2.6 <= t < length:
                half = 1.0 if t < length - 2 else 1.0 * (length - t) / 2  # tapered tip
                if abs(s) < half:
                    c = BLADE_HI if s < -0.35 else BLADE if s < 0.35 else BLADE_DARK
            if c:
                put(layer, x, y, c)
    return add_outline(layer)


def draw_smear(a0, a1, px, py, length=13):
    """Crescent trail between angles a0 -> a1 (clockwise), thickest next to the blade."""
    layer = np.zeros((CANVAS_H, CANVAS_W, 4), np.uint8)
    span = a1 - a0
    for y in range(CANVAS_H):
        for x in range(CANVAS_W):
            dx, dy = x + 0.5 - px, y + 0.5 - py
            r = math.hypot(dx, dy)
            phi = math.degrees(math.atan2(dx, -dy))
            f = ((phi - a0) % 360) / span
            if not 0 <= f <= 0.97 or r > length + 1.5:
                continue
            thick = 1.5 + 5.5 * f ** 1.2
            depth = length + 1.5 - r
            if depth < thick:
                put(layer, x, y, SMEAR_OUT if depth < thick * 0.45 else SMEAR_IN)
    return layer


def draw_arm(layer, shoulder, hand):
    """Thick outlined segment shoulder -> hand, plus a fist."""
    (sx, sy), (hx, hy) = shoulder, hand
    arm = np.zeros_like(layer)
    for y in range(CANVAS_H):
        for x in range(CANVAS_W):
            ex, ey = hx - sx, hy - sy
            L2 = ex * ex + ey * ey or 1
            k = max(0, min(1, ((x - sx) * ex + (y - sy) * ey) / L2))
            d = math.hypot(x - (sx + k * ex), y - (sy + k * ey))
            if d < 0.75:
                put(arm, x, y, ARM_LIGHT if k < 0.3 else ARM_FILL)
    for fx, fy in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        put(arm, int(hx) + fx - 1, int(hy) + fy - 1, FIST if fy == 0 else FIST_DARK)
    return add_outline(arm)


def over(dst, src):
    m = src[..., 3] > 0
    dst[m] = src[m]
    return dst


def body_layer(sprite, dx, erase):
    """Character without its sword arm; upper body leans by dx, legs stay planted."""
    s = sprite.copy()
    x0, y0, x1, y1 = erase
    s[y0:y1 + 1, x0:x1 + 1] = 0
    layer = np.zeros((CANVAS_H, CANVAS_W, 4), np.uint8)
    legs_from = 25
    h, w = s.shape[:2]
    layer[OY:OY + legs_from, OX + dx:OX + dx + w] = s[:legs_from]
    over(layer[OY + legs_from:OY + h, OX:OX + w], s[legs_from:])
    return layer


def render(sprite, shoulder, erase, scale, out):
    frames, durations = [], []
    for angle, hand, lean, smear_from, behind, ms in KEYFRAMES:
        hx, hy = hand[0] + OX + lean, hand[1] + OY
        sh = (shoulder[0] + OX + lean, shoulder[1] + OY)
        canvas = np.zeros((CANVAS_H, CANVAS_W, 4), np.uint8)
        body = body_layer(sprite, lean, erase)
        sword = draw_sword(angle, hx, hy)
        arm = draw_arm(canvas, sh, (hx, hy))
        if behind:
            over(canvas, sword)
            over(canvas, body)
        else:
            over(canvas, body)
            if smear_from is not None:
                over(canvas, draw_smear(smear_from, angle, hx, hy))
            over(canvas, sword)
        over(canvas, arm)
        frames.append(canvas)
        durations.append(ms)

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet = np.concatenate(frames, axis=1)
    Image.fromarray(sheet).save(f"{out}_sheet.png")
    big = [Image.fromarray(f).resize((CANVAS_W * scale, CANVAS_H * scale), Image.NEAREST) for f in frames]
    big[0].save(f"{out}.gif", save_all=True, append_images=big[1:], duration=durations,
                loop=0, disposal=2, transparency=0)
    Image.fromarray(sheet).resize((sheet.shape[1] * 4, sheet.shape[0] * 4), Image.NEAREST).save(f"{out}_sheet_x4.png")
    meta = {"animation": "sword_slash", "frame_width": CANVAS_W, "frame_height": CANVAS_H,
            "frames": len(frames), "durations_ms": durations, "layout": "horizontal",
            "sheet": Path(f"{out}_sheet.png").name}
    Path(f"{out}.json").write_text(json.dumps(meta, indent=2))
    return frames


def xy(s):
    return tuple(int(v) for v in s.split(","))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image")
    p.add_argument("-o", "--out", default="out/slash")
    p.add_argument("--shoulder", type=xy, default=(21, 18))
    p.add_argument("--erase-arm", type=xy, default=(21, 17, 23, 25), help="x0,y0,x1,y1 of the sword arm")
    p.add_argument("--pixel-size", type=int)
    p.add_argument("--scale", type=int, default=8)
    args = p.parse_args()
    sprite = load_sprite(args.image, args.pixel_size)
    frames = render(sprite, args.shoulder, args.erase_arm, args.scale, Path(args.out))
    print(f"{len(frames)} frames {CANVAS_W}x{CANVAS_H} -> {args.out}.gif / {args.out}_sheet.png")


if __name__ == "__main__":
    main()
