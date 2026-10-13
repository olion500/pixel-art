"""Generative sprite animation: first-frame-locked sprite sheet from an image model + pixel cleanup.

Pipeline (mirrors what Sprite Fusion / PixelLab do, see docs section 7):
  1. Template: the source sprite is upscaled by an integer factor and placed in the first
     cell of a cols x rows grid on a flat key-color background.
  2. Generate: an image model (Gemini image models) fills every cell with the frames of the
     requested motion, conditioned on the template.
  3. Clean up, per frame: key out the background, downsample each cell back to the sprite's
     native pixel grid by block majority vote, snap every pixel to one palette shared by the
     whole animation (taken from the source), binarize alpha, fill seams, drop specks.
  4. Lock frame 0 to the untouched source and align every frame on the source's ground line.

Usage:
  GEMINI_API_KEY=... python tools/gen_animate.py samples/ninja/ninja-base.png \
      "long jump: crouch, leap forward with arms extended, land in a crouch" \
      -n 12 --cols 4 -o out/gen/ninja_jump [--model gemini-3-pro-image] [--describe "..."]

Reads the key from $GEMINI_API_KEY or ~/.config/pixel-art/gemini.env.
"""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from rig_animate import drop_specks, fill_seams, kmeans_palette, snap  # noqa: E402

KEY_RGB = (255, 0, 255)
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def api_key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    env = Path.home() / ".config/pixel-art/gemini.env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("set GEMINI_API_KEY or create ~/.config/pixel-art/gemini.env")


def load_sprite(path):
    a = np.asarray(Image.open(path).convert("RGBA")).copy()
    a[..., 3] = np.where(a[..., 3] > 127, 255, 0)
    return a


ASPECTS = {"1:1": 1, "3:2": 1.5, "2:3": 2 / 3, "4:3": 4 / 3, "3:4": 0.75, "5:4": 1.25, "4:5": 0.8,
           "16:9": 16 / 9, "9:16": 9 / 16, "21:9": 21 / 9, "4:1": 4, "1:4": 0.25}


def cell_size(base, cols, rows):
    """Frame size (w, h) in sprite px, with h stretched so the sheet hits an aspect ratio the API accepts."""
    name = min(ASPECTS, key=lambda k: abs(ASPECTS[k] - cols / rows))
    ch = max(base, round(cols * base / (ASPECTS[name] * rows)))
    cw = max(base, round(ASPECTS[name] * rows * ch / cols))
    return (cw, ch), name


def make_template(sprite, cols, rows, cell, scale):
    """cell = (w, h) frame size in sprite pixels; the sprite sits bottom-centered in cell 0."""
    cw, ch = cell
    W, H = cols * cw * scale, rows * ch * scale
    sheet = Image.new("RGB", (W, H), KEY_RGB)
    h, w = sprite.shape[:2]
    x0, y0 = (cw - w) // 2, ch - h - 2
    big = Image.fromarray(sprite).resize((w * scale, h * scale), Image.NEAREST)
    sheet.paste(big, (x0 * scale, y0 * scale), big)
    return sheet, (x0, y0)


def call_gemini(model, prompt, image, key, aspect):
    """image: one PIL image or a list of them (sent in order, before the prompt)."""
    parts = []
    for im in image if isinstance(image, (list, tuple)) else [image]:
        buf = io.BytesIO()
        im.save(buf, "PNG")
        parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(buf.getvalue()).decode()}})
    body = {
        "contents": [{"parts": parts + [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}},
    }
    req = urllib.request.Request(API.format(model=model), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:500]
            if e.code in (429, 500, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise SystemExit(f"Gemini HTTP {e.code}: {msg}")
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inline_data") or part.get("inlineData")
            if inline:
                return Image.open(io.BytesIO(base64.b64decode(inline["data"]))).convert("RGB")
    raise SystemExit("no image in response: " + json.dumps(data)[:800])


def build_prompt(motion, n, cols, rows, scale, describe):
    who = f" ({describe})" if describe else ""
    return (
        f"This image is a pixel-art sprite sheet template: a grid of {cols} columns x {rows} rows of equal cells "
        f"on a flat magenta (#FF00FF) background. The top-left cell already contains frame 1: a pixel-art "
        f"character{who}, drawn with chunky pixels where every art pixel is a {scale}x{scale} block.\n"
        f"Fill ALL {n} cells, left to right then top to bottom, with the consecutive frames of this animation: "
        f"{motion}.\n"
        "Rules: exactly the same character design, outfit, colors, outline and proportions in every frame; "
        "same chunky pixel size, aligned to the same pixel grid; side view facing right; keep each character "
        "fully inside its own cell, bottom-aligned on the same ground line; keep frame 1 unchanged; "
        "the motion should read clearly and loop smoothly. Flat magenta background everywhere, "
        "no grid lines, no text, no numbers, no shadows, no motion blur, no anti-aliasing."
    )


def key_out(cell_rgb, tol=90):
    a = np.asarray(cell_rgb).astype(int)
    d = np.abs(a - np.array(KEY_RGB)).sum(-1)
    # magenta-ish = high red & blue, low green
    magenta = (d < tol) | ((a[..., 0] > 170) & (a[..., 2] > 170) & (a[..., 1] < 110))
    rgba = np.dstack([a.astype(np.uint8), np.where(magenta, 0, 255).astype(np.uint8)])
    return rgba


def majority_downscale(rgba, out_w, out_h):
    h, w = rgba.shape[:2]
    ys = np.linspace(0, h, out_h + 1).round().astype(int)
    xs = np.linspace(0, w, out_w + 1).round().astype(int)
    out = np.zeros((out_h, out_w, 4), np.uint8)
    for i in range(out_h):
        for j in range(out_w):
            # sample the inner part of each block: block borders are where models blur
            y0, y1, x0, x1 = ys[i], ys[i + 1], xs[j], xs[j + 1]
            my, mx = max(0, (y1 - y0) // 4), max(0, (x1 - x0) // 4)
            block = rgba[y0 + my:y1 - my, x0 + mx:x1 - mx].reshape(-1, 4)
            if len(block) == 0 or (block[:, 3] > 0).mean() < 0.5:
                continue
            block = block[block[:, 3] > 0]
            vals, counts = np.unique(block // 8, axis=0, return_counts=True)  # tolerate tiny color noise
            win = vals[counts.argmax()]
            match = block[(block // 8 == win).all(1)]
            out[i, j, :3] = match[:, :3].mean(0).round()
            out[i, j, 3] = 255
    return out


def ground_align(frame, ground_y):
    ys = np.nonzero(frame[..., 3].any(1))[0]
    if len(ys) == 0:
        return frame
    dy = ground_y - ys.max()
    out = np.zeros_like(frame)
    if dy >= 0:
        out[dy:] = frame[:frame.shape[0] - dy]
    else:
        out[:dy] = frame[-dy:]
    return out


def erase_grid_lines(gen, frac=0.9):
    """Models often draw cell borders even when told not to: long dark rows/columns -> key color."""
    a = np.asarray(gen).copy()
    dark = a.astype(int).sum(-1) < 200
    for axis in (0, 1):
        lines = np.nonzero(dark.mean(axis=1 - axis) > frac)[0]
        for i in lines:
            sl = slice(max(0, i - 1), i + 2)
            if axis == 0:
                a[sl, :] = KEY_RGB
            else:
                a[:, sl] = KEY_RGB
    return Image.fromarray(a)


def postprocess(gen, sprite, cols, rows, cell, n, origin, palette, align_ground=True):
    """Cut cells, then rebuild each frame on the native pixel grid.

    Models tend to redraw the whole sheet at a slightly different scale (frame 1 included),
    so the art-pixel size is calibrated on the model's own redraw of frame 1: its height in
    output pixels divided by the source sprite height. Every cell is then downsampled with
    that step, its grid phase anchored on the character's bounding box (outlines sit on pixel
    borders), and placed so the model's frame 1 lands exactly where the source sits.
    """
    gen = erase_grid_lines(gen)
    cw, ch = cell
    gw, gh = gen.width / cols, gen.height / rows
    cells = []
    for k in range(n):
        r, c = divmod(k, cols)
        crop = gen.crop((round(c * gw), round(r * gh), round((c + 1) * gw), round((r + 1) * gh)))
        rgba = key_out(crop)
        rgba = drop_specks(rgba, 40)  # stray key-color noise in output resolution
        cells.append(rgba)

    def bbox(a):
        ys, xs = np.nonzero(a[..., 3])
        return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(ys) else None

    sh, sw = sprite.shape[:2]
    b0 = bbox(cells[0])
    step = (b0[3] - b0[1]) / sh
    ox, oy = origin
    # where the model's frame 1 sits, in native px, vs where the source sits
    corr_x = ox - round(b0[0] / step)
    corr_y = oy - round(b0[1] / step)

    frames = []
    for rgba in cells:
        f = np.zeros((ch, cw, 4), np.uint8)
        b = bbox(rgba)
        if b:
            x0, y0, x1, y1 = b
            ow, oh = max(1, round((x1 - x0) / step)), max(1, round((y1 - y0) / step))
            small = majority_downscale(rgba[y0:y1, x0:x1], ow, oh)
            px, py = round(x0 / step) + corr_x, round(y0 / step) + corr_y
            ys = slice(max(0, py), min(ch, py + oh))
            xs = slice(max(0, px), min(cw, px + ow))
            f[ys, xs] = small[ys.start - py:ys.stop - py, xs.start - px:xs.stop - px]
        frames.append(drop_specks(fill_seams(snap(f, palette)), 6))

    f0 = np.zeros((ch, cw, 4), np.uint8)
    f0[oy:oy + sh, ox:ox + sw] = snap(sprite, palette)
    if align_ground:
        frames = [ground_align(f, oy + sh - 1) for f in frames]
    frames[0] = f0  # first-frame lock
    print(f"art pixel = {step:.2f} output px (template used {gen.width / (cols * cw):.2f})")
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("motion")
    ap.add_argument("-n", "--frames", type=int, default=8)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--cell", type=int, default=0, help="frame size in sprite px (default: 1.4x sprite)")
    ap.add_argument("--scale", type=int, default=8)
    ap.add_argument("--colors", type=int, default=16)
    ap.add_argument("--model", default="gemini-3-pro-image")
    ap.add_argument("--describe", default="")
    ap.add_argument("--no-ground", action="store_true", help="keep generated vertical positions (jumps)")
    ap.add_argument("--reuse", help="skip the API call and post-process this raw generated PNG")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    sprite = load_sprite(a.image)
    h, w = sprite.shape[:2]
    rows = -(-a.frames // a.cols)
    cell, aspect = cell_size(a.cell or int(max(h, w) * 1.4), a.cols, rows)
    template, origin = make_template(sprite, a.cols, rows, cell, a.scale)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    template.save(f"{out}_template.png")

    if a.reuse:
        gen = Image.open(a.reuse).convert("RGB")
    else:
        prompt = build_prompt(a.motion, a.frames, a.cols, rows, a.scale, a.describe)
        t = time.time()
        gen = call_gemini(a.model, prompt, template, api_key(), aspect)
        print(f"{a.model}: {gen.size} in {time.time() - t:.0f}s")
        Path(f"{out}_prompt.txt").write_text(prompt)
    gen.save(f"{out}_raw.png")
    # model output size rarely matches the template exactly; the grid is what matters
    palette = kmeans_palette(sprite, a.colors)
    frames = postprocess(gen, sprite, a.cols, rows, cell, a.frames, origin, palette, not a.no_ground)

    Image.fromarray(np.concatenate(frames, 1)).save(f"{out}_sheet.png")
    big = []
    for f in frames:
        im = Image.new("RGBA", cell, (232, 234, 240, 255))
        fi = Image.fromarray(f)
        im.paste(fi, (0, 0), fi)
        big.append(im.convert("RGB").resize((cell[0] * 6, cell[1] * 6), Image.NEAREST))
    big[0].save(f"{out}.gif", save_all=True, append_images=big[1:], duration=100, loop=0)
    Path(f"{out}.json").write_text(json.dumps({"frame_width": cell[0], "frame_height": cell[1], "frames": len(frames),
                                               "fps": 10, "model": a.model, "motion": a.motion}, indent=2))
    print(f"{len(frames)} frames {cell[0]}x{cell[1]} ({aspect}) -> {out}_sheet.png")


if __name__ == "__main__":
    main()
