"""Build a rigged, timed, tagged Aseprite animation from storyboard frames via aseprite-ai-artist tool calls.

Pipeline (their animate skill, headless):
  storyboard frames (plan_animate output) -> head lock (grid-loop fix, tools/head_lock.py)
  -> sprite with the ninja palette -> layers  [legs, upper, fx]  (or [body, fx])
  -> one `draw` kind 'grid' per layer per frame
  -> rule-based frames made by moving cels, not redrawing (copy + cel move):
       "copy:<from>:<dx>" in the plan's "cel" field -> upper copied from frame <from> moved dx, legs copied unmoved
  -> FX on the fx layer from tools/fx_overlay (smear and fist flash edit the body; sparks/dust on fx)
  -> durations, tag, filmstrip + onion + validate(expect), export spritesheet/gif/.aseprite

Usage:
  python tools/aai_build.py cross samples/ninja/plans/cross_v2.json out/plan2/ninja_cross -o out/aai/cross_calls.json
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import fx_overlay as fx  # noqa: E402
from head_lock import lock_heads  # noqa: E402
from rig_animate import kmeans_palette, snap  # noqa: E402

HEAD = (15, 0, 27, 8)


def hexc(c):
    return "#%02x%02x%02x" % tuple(int(v) for v in c[:3])


def to_grid(img, legend_of):
    rows = []
    for y in range(img.shape[0]):
        rows.append("".join(legend_of[hexc(p)] if p[3] else "." for p in img[y]))
    return rows


DUST_L, DUST_D = (184, 184, 200, 255), (128, 128, 146, 255)


def dust(layer, x, y, stage, *_):
    """Flattened grey puffs spreading outward from the feet (rule 43.11), not shoe-coloured blocks."""
    puffs = {0: [(3, 0, 1)], 1: [(5, -1, 2), (8, 0, 1)], 2: [(9, -1, 1), (11, 0, 0)]}[stage]
    for s in (-1, 1):
        for dx, dy, r in puffs:
            cx, cy = x + s * dx, y + dy
            for yy in range(cy - r, cy + 1):
                for xx in range(cx - r - 1, cx + r + 2):
                    if (xx - cx) ** 2 / (r + 1.5) ** 2 + (yy - cy) ** 2 / (r + 0.5) ** 2 <= 1:
                        fx.put(layer, xx, yy, DUST_L if yy < cy else DUST_D)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag")
    ap.add_argument("plan")
    ap.add_argument("storyboard", help="prefix of plan_animate output")
    ap.add_argument("--base", default="samples/ninja/ninja-base.png")
    ap.add_argument("--waist", type=int, default=0, help="frame row splitting upper/legs layers (0 = single body layer)")
    ap.add_argument("--head-err", type=int, default=120)
    ap.add_argument("--pad", type=int, default=8, help="extra px on the right (sparks, forward travel)")
    ap.add_argument("--top-pad", type=int, default=0, help="extra px on top (jump apex)")
    ap.add_argument("--align-front-shoe", action="store_true",
                    help="translate every frame so the front shoe matches frame 1 (ground pivot, rule 43.6)")
    ap.add_argument("--save", required=True, help="output prefix for .aseprite/.png/.gif written by Aseprite")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    plan = json.loads(Path(a.plan).read_text())
    meta = json.loads(Path(a.storyboard + ".json").read_text())
    fw, fh = meta["frame_width"], meta["frame_height"]
    sheet = np.asarray(Image.open(a.storyboard + "_sheet.png").convert("RGBA"))
    frames = [np.pad(sheet[:, i * fw:(i + 1) * fw], ((a.top_pad, 0), (0, a.pad), (0, 0))) for i in range(sheet.shape[1] // fw)]
    W = fw + a.pad
    fh += a.top_pad
    specs = plan["frames"][1:] if plan.get("reference_cell") else plan["frames"]
    durations = [f["ms"] for f in specs]

    base = np.asarray(Image.open(a.base).convert("RGBA")).copy()
    base[..., 3] = np.where(base[..., 3] > 127, 255, 0)
    pal = kmeans_palette(base, 16)
    frames, report = lock_heads(frames, snap(base, pal), HEAD, ((fw - 33) // 2, fh - 35), a.head_err)

    def shift(img, dx, dy):
        out = np.zeros_like(img)
        h, w = img.shape[:2]
        ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
        xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
        out[yd, xd] = img[ys, xs]
        return out

    def front_shoe_right(img):
        al = img[..., 3] > 0
        shoe = al & (img[..., 0] > 110) & (img[..., 1] > 150) & (img[..., 2] > 160)
        shoe[:img.shape[0] - 12] = False
        xs = np.nonzero(shoe.any(0))[0]
        return int(xs.max()) if len(xs) else None

    if a.align_front_shoe:
        ref = front_shoe_right(frames[0])
        frames = [shift(f, ref - front_shoe_right(f), 0) if front_shoe_right(f) else f for f in frames]
    # per-frame grid-loop edits from the plan: copy another frame's drawing, recolor tucked shins, translate
    src = [f.copy() for f in frames]
    for i, spec in enumerate(specs):
        f = src[spec["copy"] - 1].copy() if "copy" in spec else frames[i]
        if spec.get("navy_shins"):                       # white stockings -> navy legs, keep the lowest 3 rows (boots)
            al = np.nonzero(f[..., 3].any(1))[0]
            bottom = al.max()
            light = (f[..., 3] > 0) & (f[..., :3].astype(int).sum(-1) > 450)
            light[bottom - 2:] = False
            light[:bottom - 9] = False
            f[light] = (39, 57, 97, 255)
        if "shift" in spec:
            f = shift(f, *spec["shift"])
        frames[i] = f

    # body edits (smear / flash) and the fx layer, from the plan's "fx" tags
    fx_layers, tip = [], None
    frames_index = lambda img: next(k for k, g in enumerate(frames) if g is img)
    for f, spec in zip(frames, specs):
        layer = np.zeros_like(f)
        kind = spec.get("fx")
        if kind in ("smear", "smear2", "impact"):
            tip = fx.fist_tip(f)
        if kind in ("smear", "smear2"):
            # rule 44.5: opaque streak in the arm's two brightest colours, from where the fist was (chin)
            # to where it will be (next frame's reach); the first smear is the widest, the second a thin trail
            nxt = fx.fist_tip(frames[min(len(frames) - 1, frames_index(f) + 1)])
            x0, y0 = tip[0] - 5, tip[1]
            x1, y1 = max(nxt[0], tip[0]), nxt[1]
            if kind == "smear":
                x1 = x0 + round(0.6 * (x1 - x0))
            half = 1 if kind == "smear" else 0
            for x in range(x0, x1 + 1):
                t = (x - x0) / max(1, x1 - x0)
                yc = round(y0 + (y1 - y0) * t)
                for yy in range(yc - half, yc + half + 1):
                    if 0 <= yy < f.shape[0] and 0 <= x < f.shape[1]:
                        f[yy, x] = (59, 141, 172, 255) if yy < yc or (half == 0) else (39, 57, 97, 255)
            if kind == "smear":
                for x in range(x1 - 3, x1 + 1):         # leading edge = fist at full reach, outlined
                    for yy in (y1 - 2, y1 + 2):
                        if 0 <= yy < f.shape[0]:
                            f[yy, x] = (3, 1, 4, 255)
        elif kind == "impact":
            fx.flash(f, tip)
            fx.spark(layer, tip[0] + 3, tip[1], 0)
            col = np.nonzero(f[:, tip[0] - 4, 3])[0]
            arm = [y for y in col if abs(y - tip[1]) <= 4]
            fx.speed_lines(layer, f, tip[0] - 14, tip[0] - 3, [min(arm) - 1, max(arm) + 1])
        elif kind == "spark1":
            fx.spark(layer, tip[0] + 3, tip[1], 1)
        elif kind == "spark2":
            fx.spark(layer, tip[0] + 2, tip[1], 2)
        elif kind == "spark3":
            fx.spark(layer, tip[0] + 1, tip[1], 3)
        elif kind and kind.startswith("dust"):
            ys = np.nonzero(f[..., 3].any(1))[0]
            xs = np.nonzero(f[..., 3].any(0))[0]
            ground = int(np.nonzero(frames[0][..., 3].any(1))[0].max())   # the ground line, not the airborne feet
            dust(layer, int(xs.mean()), ground, int(kind[-1]))
            layer[f[..., 3] > 0] = 0
        fx_layers.append(layer)

    # palette + legend shared by every grid
    colors = sorted({hexc(p) for f in frames + fx_layers for p in f.reshape(-1, 4) if p[3]})
    glyphs = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    legend_of = {c: glyphs[i] for i, c in enumerate(colors)}
    legend = {g: c for c, g in legend_of.items()}

    layers = ["legs", "upper", "fx"] if a.waist else ["body", "fx"]
    n = len(frames)
    calls = [
        {"tool": "preflight"},
        {"tool": "sprite_manage", "args": {"op": "new", "width": W, "height": fh, "colorMode": "rgb"}},
        {"tool": "palette", "args": {"op": "set", "colors": colors, "replace": True}},
        {"tool": "layer", "args": {"op": "rename", "name": "Layer 1", "newName": layers[0]}},
    ] + [{"tool": "layer", "args": {"op": "create", "name": l}} for l in layers[1:]] + [
        {"tool": "frame", "args": {"op": "add", "count": n - 1}},
        {"tool": "frame", "args": {"op": "set_duration", "durations": durations}},
    ]
    moved = {}
    for i, (f, spec) in enumerate(zip(frames, specs)):
        cel = spec.get("cel", "")
        if cel.startswith("copy:") and a.waist:       # rule-based frame: move cels, don't redraw
            _, src, dx = cel.split(":")
            moved[i] = (int(src), int(dx))
            continue
        parts = {"body": f} if not a.waist else {"upper": np.where((np.arange(fh) < a.waist)[:, None, None], f, 0),
                                                 "legs": np.where((np.arange(fh) >= a.waist)[:, None, None], f, 0)}
        for lname, img in parts.items():
            calls.append({"tool": "draw", "label": f"{lname}_f{i + 1}", "args": {
                "layer": lname, "frame": i + 1,
                "ops": [{"kind": "grid", "x": 0, "y": 0, "legend": legend, "rows": to_grid(img, legend_of)}]}})
    for i, spec in enumerate(specs):
        if spec.get("upper_dx") and a.waist:
            calls.append({"tool": "cel", "args": {"op": "move", "layer": "upper", "frame": i + 1, "dx": spec["upper_dx"], "dy": 0}})
    for i, (src, dx) in moved.items():
        calls += [
            {"tool": "cel", "args": {"op": "copy", "layer": "upper", "frame": src, "toFrame": i + 1}},
            {"tool": "cel", "args": {"op": "move", "layer": "upper", "frame": i + 1, "dx": dx, "dy": 0}},
            {"tool": "cel", "args": {"op": "copy", "layer": "legs", "frame": src, "toFrame": i + 1}},
        ]
    if plan.get("link_legs") and a.waist:      # rule 43.6: one leg cel shared by every frame = feet never move
        calls.append({"tool": "cel", "args": {"op": "link", "layer": "legs", "frame": 1, "frames": list(range(1, n + 1))}})
    for i, layer in enumerate(fx_layers):
        if layer[..., 3].any():
            calls.append({"tool": "draw", "label": f"fx_f{i + 1}", "args": {
                "layer": "fx", "frame": i + 1,
                "ops": [{"kind": "grid", "x": 0, "y": 0, "legend": legend, "rows": to_grid(layer, legend_of), "transparent": "skip"}]}})
    fx_frames = [i + 1 for i, l in enumerate(fx_layers) if l[..., 3].any()]
    expect = {"layerFrames": {"fx": [[min(fx_frames), max(fx_frames)]]}} if fx_frames else {}
    save = str(Path(a.save).resolve())
    calls += [
        {"tool": "tag", "args": {"op": "create", "name": a.tag, "from": 1, "to": n, "direction": "forward"}},
        {"tool": "look", "label": "filmstrip", "args": {"op": "filmstrip"}},
        {"tool": "validate", "args": {"expect": expect} if expect else {}, "stopOnError": False},
        {"tool": "export", "args": {"op": "spritesheet", "path": save + "_sheet.png", "includeJson": True}, "stopOnError": False},
        {"tool": "export", "args": {"op": "gif", "path": save + ".gif", "scale": 6}, "stopOnError": False},
        {"tool": "export", "args": {"op": "aseprite", "path": save + ".aseprite"}, "stopOnError": False},
    ]
    for c in calls:
        c.setdefault("args", {})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(calls, indent=1))
    print(f"{len(calls)} calls -> {a.out}; head lock: " + ", ".join(f"f{r[0] + 1}:{r[4][:6]}" for r in report))


if __name__ == "__main__":
    main()
