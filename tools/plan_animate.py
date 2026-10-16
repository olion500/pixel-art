"""Plan-driven sprite animation: a per-frame shot list (docs/motion_plan.md) -> image model -> pixel cleanup.

The plan JSON fixes what every frame shows and how long it lasts:
  { "name", "cols", "ground_align", "reference_cell", "rules": [...],
    "frames": [{ "ms": 120, "pose": "..." }, ...] }
- Cell 1 always holds the untouched source sprite (identity + scale calibration).
  With "reference_cell": true it is only a reference and is dropped from the output
  (e.g. a jump that starts from a crouch); otherwise it is frame 0 of the animation.
- The model is asked to draw each cell exactly as described (no improvised choreography).
- Cleanup is gen_animate.postprocess (key, scale calibration on cell 1, native-grid
  downsample, shared palette, frame-0 lock); durations come from the plan.

Usage:
  python tools/plan_animate.py samples/ninja/ninja-base.png samples/ninja/plans/jump.json -o out/plan/ninja_jump
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from gen_animate import api_key, call_gemini, cell_size, load_sprite, make_template, postprocess  # noqa: E402
from rig_animate import kmeans_palette  # noqa: E402


def build_prompt(plan, cols, rows, scale, describe):
    n = len(plan["frames"])
    lines = [
        f"This image is a pixel-art sprite sheet template: {cols} columns x {rows} rows of equal cells on a flat "
        f"magenta (#FF00FF) background. Cell 1 (top-left) already contains a pixel-art character"
        f"{f' ({describe})' if describe else ''} drawn with chunky pixels, each art pixel a {scale}x{scale} block.",
        f"Draw a {plan['name']} animation, side view facing right, filling cells 1 to {n} left to right, top to "
        "bottom, EXACTLY as listed (do not invent other poses):",
    ]
    for i, f in enumerate(plan["frames"]):
        r, c = divmod(i, cols)
        lines.append(f"- Cell {i + 1} (row {r + 1}, column {c + 1}): {f['pose']}.")
    if n < cols * rows:
        lines.append(f"- Cells {n + 1} to {cols * rows}: leave empty (flat magenta).")
    lines.append("Motion rules:")
    lines += [f"- {r}" for r in plan.get("rules", [])]
    lines.append(
        "Style rules: exactly the same character design, outfit, colors, outline, proportions and size in every "
        "cell; same chunky pixel size on the same pixel grid; each character fully inside its own cell, all cells "
        "sharing the same ground line; keep cell 1 unchanged. Flat magenta background, no grid lines, no text, "
        "no numbers, no shadows, no effects, no motion blur, no anti-aliasing.")
    return "\n".join(lines)


def save(frames, durations, cell, out, meta):
    Image.fromarray(np.concatenate(frames, 1)).save(f"{out}_sheet.png")
    big = []
    for f in frames:
        im = Image.new("RGBA", cell, (232, 234, 240, 255))
        fi = Image.fromarray(f)
        im.paste(fi, (0, 0), fi)
        big.append(im.convert("RGB").resize((cell[0] * 6, cell[1] * 6), Image.NEAREST))
    big[0].save(f"{out}.gif", save_all=True, append_images=big[1:], duration=durations, loop=0)
    Path(f"{out}.json").write_text(json.dumps({**meta, "frame_width": cell[0], "frame_height": cell[1],
                                               "frames": len(frames), "durations_ms": durations}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("plan")
    ap.add_argument("--scale", type=int, default=8)
    ap.add_argument("--cell", type=int, default=0)
    ap.add_argument("--colors", type=int, default=16)
    ap.add_argument("--model", default="gemini-3-pro-image")
    ap.add_argument("--describe", default="ninja in a navy suit with a cyan visor and a pink scarf")
    ap.add_argument("--reuse")
    ap.add_argument("--revise", help="JSON list of {cell, pose}: redraw only these cells of the --reuse sheet")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    plan = json.loads(Path(a.plan).read_text())
    sprite = load_sprite(a.image)
    h, w = sprite.shape[:2]
    n, cols = len(plan["frames"]), plan["cols"]
    rows = -(-n // cols)
    cell, aspect = cell_size(a.cell or int(max(h, w) * 1.4), cols, rows)
    template, origin = make_template(sprite, cols, rows, cell, a.scale)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    template.save(f"{out}_template.png")
    prompt = build_prompt(plan, cols, rows, a.scale, a.describe)
    Path(f"{out}_prompt.txt").write_text(prompt)
    if a.reuse and a.revise:
        fixes = json.loads(Path(a.revise).read_text())
        sheet = Image.open(a.reuse).convert("RGB")
        rp = (f"This is a pixel-art sprite sheet, {cols} columns x {rows} rows, of a {plan['name']} animation. "
              "Redraw ONLY the cells listed below so they match their description; keep every other cell exactly as it "
              "is, and keep the same character design, size, pixel size, ground line and flat magenta background:\n"
              + "\n".join(f"- Cell {f['cell']}: {f['pose']}." for f in fixes)
              + "\nMotion rules:\n" + "\n".join(f"- {r}" for r in plan.get("rules", []))
              + "\nNo grid lines, no text, no effects, no anti-aliasing.")
        Path(f"{out}_revise_prompt.txt").write_text(rp)
        t = time.time()
        gen = call_gemini(a.model, rp, sheet, api_key(), aspect)
        print(f"{a.model} revise: {gen.size} in {time.time() - t:.0f}s")
    elif a.reuse:
        gen = Image.open(a.reuse).convert("RGB")
    else:
        t = time.time()
        gen = call_gemini(a.model, prompt, template, api_key(), aspect)
        print(f"{a.model}: {gen.size} in {time.time() - t:.0f}s")
    gen.save(f"{out}_raw.png")

    palette = kmeans_palette(sprite, a.colors)
    frames = postprocess(gen, sprite, cols, rows, cell, n, origin, palette, plan.get("ground_align", True))
    durations = [f["ms"] for f in plan["frames"]]
    if plan.get("reference_cell"):
        frames, durations = frames[1:], durations[1:]
    save(frames, durations, cell, out, {"plan": a.plan, "model": a.model})
    print(f"{len(frames)} frames {cell[0]}x{cell[1]} ({aspect}) -> {out}_sheet.png")


if __name__ == "__main__":
    main()
