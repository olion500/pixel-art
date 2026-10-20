"""Concept art -> base pixel sprite (the step before any animation, when there is no reference animation).

Follows aseprite-ai-artist's concept skill: the concept owns the design (proportions, pose, colour
masses), never the pixels; downscaling a painting gives mush. So the image model redraws the concept
as a pixel sprite at an explicit size and grid, and cleanup restores the grid and the palette:
  1. concept + spec (height in px, view, outline, colour count) -> Gemini draws ONE pixel sprite at an
     integer block size on flat magenta;
  2. key out the background, detect the art-pixel size from edge-peak spacing (Pixel Snapper idea),
     majority-downsample to the native grid, k-means palette, binary alpha, drop specks, crop.
Writes <out>.png (native) and <out>_x8.png (preview).

Usage:
  python tools/concept_to_sprite.py samples/concepts/stone_boar.png --height 28 --width 44 \
      --describe "stone-shelled boar monster" -o samples/stone_boar/base
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from gen_animate import KEY_RGB, api_key, call_gemini, keep_main, key_out, majority_downscale  # noqa: E402
from rig_animate import drop_specks, fill_seams, kmeans_palette, snap  # noqa: E402


def block_size(rgba):
    a = rgba.astype(float)
    g = (a[..., :3] @ [0.299, 0.587, 0.114]) * (a[..., 3] > 0)
    steps = []
    for prof in (np.abs(np.diff(g, axis=1)).sum(0), np.abs(np.diff(g, axis=0)).sum(1)):
        thr = prof.max() * 0.15
        pk = [i for i in range(1, len(prof) - 1) if prof[i] > thr and prof[i] >= prof[i - 1] and prof[i] > prof[i + 1]]
        d = np.diff(pk)
        d = d[d >= 3]
        if len(d):
            steps.append(float(np.median(d)))
    return float(np.mean(steps)) if steps else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("concept")
    ap.add_argument("--height", type=int, required=True, help="sprite height in art pixels")
    ap.add_argument("--width", type=int, default=0, help="approximate width (0 = let proportions decide)")
    ap.add_argument("--describe", required=True)
    ap.add_argument("--view", default="side view, facing right")
    ap.add_argument("--colors", type=int, default=16)
    ap.add_argument("--block", type=int, default=16, help="output px per art pixel asked from the model")
    ap.add_argument("--model", default="gemini-3-pro-image")
    ap.add_argument("--reuse")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    concept = Image.open(a.concept).convert("RGB")
    size = f"exactly {a.height} art pixels tall" + (f" and about {a.width} art pixels wide" if a.width else "")
    prompt = (
        f"Image 1 is concept art of a {a.describe}. Redraw this exact design as ONE pixel-art game sprite: {a.view}, "
        f"{size}, every art pixel a crisp {a.block}x{a.block} block on one grid, at most {a.colors} colours, "
        "a dark 1-pixel outline, simple 2-3 tone shading per material, no anti-aliasing, no gradients, no dithering. "
        "Keep the concept's proportions, silhouette, key shapes and colour masses; simplify small details that "
        "would be noise at this size. Neutral standing/idle pose, the whole body visible, centred, "
        "on a flat magenta (#FF00FF) background. No text, no shadow, no other objects."
    )
    Path(f"{out}_prompt.txt").write_text(prompt)
    gen = Image.open(a.reuse).convert("RGB") if a.reuse else call_gemini(a.model, prompt, [concept], api_key(), "1:1")
    gen.save(f"{out}_raw.png")

    rgba = keep_main(drop_specks(key_out(gen), 40))
    ys, xs = np.nonzero(rgba[..., 3])
    rgba = rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    step = block_size(rgba) or rgba.shape[0] / a.height
    h, w = rgba.shape[:2]
    nh, nw = max(1, round(h / step)), max(1, round(w / step))
    small = majority_downscale(rgba, nw, nh)
    small[..., 3] = np.where(small[..., 3] > 0, 255, 0)
    pal = kmeans_palette(small, a.colors)
    sprite = drop_specks(fill_seams(snap(small, pal)), 3)
    ys, xs = np.nonzero(sprite[..., 3])
    sprite = sprite[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    Image.fromarray(sprite).save(f"{out}.png")
    prev = Image.new("RGBA", (sprite.shape[1], sprite.shape[0]), (232, 234, 240, 255))
    prev.paste(Image.fromarray(sprite), (0, 0), Image.fromarray(sprite))
    prev.resize((sprite.shape[1] * 8, sprite.shape[0] * 8), Image.NEAREST).save(f"{out}_x8.png")
    print(f"block {step:.1f}px -> sprite {sprite.shape[1]}x{sprite.shape[0]}, {len(pal)} colours -> {out}.png")


if __name__ == "__main__":
    main()
