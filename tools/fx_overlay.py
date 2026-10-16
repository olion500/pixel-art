"""Add hit FX to a punch sprite sheet as a separate, code-drawn layer (docs/motion_plan.md section 2).

FX per frame come from the plan ("fx": "smear" | "impact" | "spark1" | "spark2" | "spark3").
The fist is found per frame (right-most opaque pixel at upper-body height); effects are drawn
from the character's own light keys (white, pale cyan, cyan), speed lines only on empty pixels.
Writes the combined sheet/GIF plus the FX-only layer so an engine can play them separately.

Usage:
  python tools/fx_overlay.py out/plan/ninja_punch samples/ninja/plans/punch.json --pad 8
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

W, H, C = (207, 238, 242, 255), (116, 253, 244, 255), (6, 231, 219, 255)


def fist_tip(f, rows=(9, 18)):
    """Right-most opaque pixel in the arm band, measured from the top of the character."""
    a = f[..., 3] > 0
    top = int(np.nonzero(a.any(1))[0][0])
    best = None
    for y in range(top + rows[0], top + rows[1]):
        xs = np.nonzero(a[y])[0]
        if len(xs) and (best is None or xs.max() > best[0]):
            best = (xs.max(), y)
    return best


def put(layer, x, y, col):
    if 0 <= y < layer.shape[0] and 0 <= x < layer.shape[1]:
        layer[y, x] = col


def spark(layer, x, y, stage):
    def ray(dx, dy, n, inner, outer, start=1):
        for i in range(start, n + 1):
            put(layer, x + dx * i, y + dy * i, W if i <= inner else outer)
    orth, diag = [(1, 0), (-1, 0), (0, 1), (0, -1)], [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    if stage == 0:
        put(layer, x, y, W)
        for d in orth: ray(*d, 2, 1, H)
        for d in diag: ray(*d, 1, 0, H)
    elif stage == 1:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if abs(dx) + abs(dy) < 2: put(layer, x + dx, y + dy, W)
        for d in orth: ray(*d, 6, 3, H, 2)
        for d in diag: ray(*d, 3, 1, H, 2)
    elif stage == 2:
        for k in range(0, 16, 2):
            a = k * np.pi / 8
            put(layer, x + round(4.5 * np.cos(a)), y + round(4.5 * np.sin(a)), H)
        for dx, dy in orth:
            put(layer, x + dx * 7, y + dy * 7, C)
            put(layer, x + dx * 8, y + dy * 8, C)
    elif stage == 3:
        for dx, dy in [(9, -2), (7, 5), (-1, -8), (2, 8), (10, 1), (-4, 4)]:
            put(layer, x + dx, y + dy, H if dx % 2 else C)


def speed_lines(layer, body, x0, x1, ys):
    for y in ys:
        for x in range(x0, x1 + 1):
            if 0 <= y < body.shape[0] and 0 <= x < body.shape[1] and body[y, x, 3] == 0:
                put(layer, x, y, H if x < (x0 + x1) // 2 else W)


def smear(frame, tip):
    """Streak the arm: lighten it toward the fist in two tones, plus a pale trail behind."""
    x1, y = tip
    for x in range(x1 - 12, x1 + 1):
        for yy in (y - 1, y, y + 1):
            if 0 <= yy < frame.shape[0] and frame[yy, x, 3]:
                if frame[yy, x, :3].sum() > 60:                # keep the black outline
                    frame[yy, x] = H if x > x1 - 6 else (frame[yy, x] * 0.4 + np.array(H) * 0.6).astype(np.uint8)
    for x in range(x1 - 16, x1 - 12):
        if frame[y, x, 3] == 0:
            frame[y, x] = H


def flash(frame, tip):
    x1, y = tip
    for yy in range(y - 2, y + 3):
        for x in range(x1 - 4, x1 + 1):
            if 0 <= yy < frame.shape[0] and frame[yy, x, 3] and frame[yy, x, :3].sum() > 60:
                frame[yy, x] = W


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", help="prefix of a plan_animate output (reads <base>_sheet.png and <base>.json)")
    ap.add_argument("plan")
    ap.add_argument("--pad", type=int, default=8, help="extra px on the right for sparks")
    a = ap.parse_args()
    meta = json.loads(Path(a.base + ".json").read_text())
    plan = json.loads(Path(a.plan).read_text())
    fw, fh = meta["frame_width"], meta["frame_height"]
    sheet = np.asarray(Image.open(a.base + "_sheet.png").convert("RGBA"))
    frames = [np.pad(sheet[:, i * fw:(i + 1) * fw], ((0, 0), (0, a.pad), (0, 0))) for i in range(sheet.shape[1] // fw)]
    tip = None
    out, fx_only = [], []
    for f, spec in zip(frames, plan["frames"]):
        f = f.copy()
        layer = np.zeros_like(f)
        kind = spec.get("fx")
        if kind:
            tip = fist_tip(f) if kind in ("smear", "impact") else tip
            x, y = tip
            if kind == "smear":
                smear(f, tip)
            elif kind == "impact":
                flash(f, tip)
                spark(layer, x + 3, y, 0)
                speed_lines(layer, f, x - 14, x - 3, [y - 4, y + 4])
            elif kind == "spark1":
                spark(layer, x + 3, y, 1)
                speed_lines(layer, f, x - 10, x - 4, [y - 4, y + 4])
            elif kind == "spark2":
                spark(layer, x + 2, y, 2)
            elif kind == "spark3":
                spark(layer, x + 1, y, 3)
        m = layer[..., 3] > 0
        f[m] = layer[m]
        out.append(f)
        fx_only.append(layer)
    prefix = a.base + "_fx"
    Image.fromarray(np.concatenate(out, 1)).save(prefix + "_sheet.png")
    Image.fromarray(np.concatenate(fx_only, 1)).save(prefix + "_layer.png")
    big = []
    for f in out:
        im = Image.new("RGBA", (f.shape[1], f.shape[0]), (232, 234, 240, 255))
        fi = Image.fromarray(f)
        im.paste(fi, (0, 0), fi)
        big.append(im.convert("RGB").resize((f.shape[1] * 6, f.shape[0] * 6), Image.NEAREST))
    durations = meta["durations_ms"]
    big[0].save(prefix + ".gif", save_all=True, append_images=big[1:], duration=durations, loop=0)
    Path(prefix + ".json").write_text(json.dumps({**meta, "frame_width": fw + a.pad, "fx_layer": Path(prefix + "_layer.png").name}, indent=2))
    print(f"{len(out)} frames {fw + a.pad}x{fh} -> {prefix}_sheet.png (+ FX-only layer)")


if __name__ == "__main__":
    main()
