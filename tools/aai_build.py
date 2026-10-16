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


def dust(layer, x, y, stage, color_w, color_s):
    for s in (-1, 1):
        if stage == 0:
            for dx, dy in [(2, -1), (3, -1), (2, 0), (3, 0)]:
                fx.put(layer, x + s * dx, y + dy, color_w)
        elif stage == 1:
            for dx, dy in [(4, -2), (5, -2), (4, -1), (5, -1), (6, -1), (3, 0), (4, 0), (5, 0), (6, 0)]:
                fx.put(layer, x + s * dx, y + dy, color_w if dy < 0 else color_s)
        elif stage == 2:
            for dx, dy in [(7, -2), (8, 0)]:
                fx.put(layer, x + s * dx, y + dy, color_s)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag")
    ap.add_argument("plan")
    ap.add_argument("storyboard", help="prefix of plan_animate output")
    ap.add_argument("--base", default="samples/ninja/ninja-base.png")
    ap.add_argument("--waist", type=int, default=0, help="frame row splitting upper/legs layers (0 = single body layer)")
    ap.add_argument("--head-err", type=int, default=120)
    ap.add_argument("--pad", type=int, default=8)
    ap.add_argument("--save", required=True, help="output prefix for .aseprite/.png/.gif written by Aseprite")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    plan = json.loads(Path(a.plan).read_text())
    meta = json.loads(Path(a.storyboard + ".json").read_text())
    fw, fh = meta["frame_width"], meta["frame_height"]
    sheet = np.asarray(Image.open(a.storyboard + "_sheet.png").convert("RGBA"))
    frames = [np.pad(sheet[:, i * fw:(i + 1) * fw], ((0, 0), (0, a.pad), (0, 0))) for i in range(sheet.shape[1] // fw)]
    W = fw + a.pad
    specs = plan["frames"][1:] if plan.get("reference_cell") else plan["frames"]
    durations = meta["durations_ms"]

    base = np.asarray(Image.open(a.base).convert("RGBA")).copy()
    base[..., 3] = np.where(base[..., 3] > 127, 255, 0)
    pal = kmeans_palette(base, 16)
    frames, report = lock_heads(frames, snap(base, pal), HEAD, ((fw - 33) // 2, fh - 35), a.head_err)

    # body edits (smear / flash) and the fx layer, from the plan's "fx" tags
    fx_layers, tip = [], None
    for f, spec in zip(frames, specs):
        layer = np.zeros_like(f)
        kind = spec.get("fx")
        if kind in ("smear", "smear2", "impact"):
            tip = fx.fist_tip(f)
        if kind == "smear":
            fx.smear(f, tip)
        elif kind == "smear2":                          # thinner second smear: 1px streak behind the arm
            x1, y = tip
            for x in range(x1 - 12, x1 - 5):
                if f[y + 1, x, 3] == 0:
                    f[y + 1, x] = fx.H
        elif kind == "impact":
            fx.flash(f, tip)
            fx.spark(layer, tip[0] + 3, tip[1], 0)
            fx.speed_lines(layer, f, tip[0] - 14, tip[0] - 3, [tip[1] - 4, tip[1] + 4])
        elif kind == "spark1":
            fx.spark(layer, tip[0] + 3, tip[1], 1)
        elif kind == "spark2":
            fx.spark(layer, tip[0] + 2, tip[1], 2)
        elif kind == "spark3":
            fx.spark(layer, tip[0] + 1, tip[1], 3)
        elif kind and kind.startswith("dust"):
            ys = np.nonzero(f[..., 3].any(1))[0]
            xs = np.nonzero(f[..., 3].any(0))[0]
            dust(layer, int(xs.mean()), fh - 3, int(kind[-1]), fx.W, (140, 187, 203, 255))
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
    for i, (src, dx) in moved.items():
        calls += [
            {"tool": "cel", "args": {"op": "copy", "layer": "upper", "frame": src, "toFrame": i + 1}},
            {"tool": "cel", "args": {"op": "move", "layer": "upper", "frame": i + 1, "dx": dx, "dy": 0}},
            {"tool": "cel", "args": {"op": "copy", "layer": "legs", "frame": src, "toFrame": i + 1}},
        ]
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
