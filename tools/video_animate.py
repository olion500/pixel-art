"""Image-to-video sprite animation: Veo animates the upscaled sprite, then frames are pixel-cleaned.

  1. First frame: the sprite upscaled by an integer factor, centered on a flat key color, 16:9.
  2. Veo (image-to-video) generates a short clip from that frame and a motion prompt
     (static camera, flat background, crisp pixel art).
  3. N frames are sampled evenly from the clip (or from --start/--end seconds), keyed,
     downsampled on the art-pixel grid calibrated from the clip's first frame, snapped to
     the source palette; frame 0 is locked to the source.

Usage:
  python tools/video_animate.py samples/ninja/ninja-base.png "jumps forward ..." -n 12 -o out/video/ninja_jump
"""
import argparse
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from gen_animate import KEY_RGB, api_key, key_out, load_sprite, majority_downscale  # noqa: E402
from rig_animate import drop_specks, fill_seams, kmeans_palette, snap  # noqa: E402

BASE = "https://generativelanguage.googleapis.com/v1beta"


def first_frame(sprite, scale, size=(1280, 720)):
    im = Image.new("RGB", size, KEY_RGB)
    h, w = sprite.shape[:2]
    big = Image.fromarray(sprite).resize((w * scale, h * scale), Image.NEAREST)
    x, y = (size[0] - w * scale) // 2, size[1] - h * scale - 2 * scale * 4
    im.paste(big, (x, y), big)
    return im, (x, y)


def request(url, key, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def generate_video(model, prompt, frame, key, seconds):
    import io
    buf = io.BytesIO()
    frame.save(buf, "PNG")
    body = {"instances": [{"prompt": prompt,
                           "image": {"bytesBase64Encoded": base64.b64encode(buf.getvalue()).decode(),
                                     "mimeType": "image/png"}}],
            "parameters": {"aspectRatio": "16:9", "durationSeconds": seconds}}
    try:
        op = request(f"{BASE}/models/{model}:predictLongRunning", key, body)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Veo HTTP {e.code}: {e.read().decode()[:600]}")
    name = op["name"]
    t = time.time()
    while not op.get("done"):
        time.sleep(8)
        op = request(f"{BASE}/{name}", key)
        if time.time() - t > 600:
            raise SystemExit("timed out waiting for Veo")
    if "error" in op:
        raise SystemExit(f"Veo error: {op['error']}")
    samples = op["response"]["generateVideoResponse"]["generatedSamples"]
    uri = samples[0]["video"]["uri"]
    req = urllib.request.Request(uri, headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read(), time.time() - t


def extract_frames(mp4, n, start=None, end=None):
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "v.mp4"
        src.write_bytes(mp4)
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                             "-of", "csv=p=0", str(src)]).decode())
        s, e = start or 0.0, min(end or dur, dur - 0.05)
        frames = []
        for i, t in enumerate(np.linspace(s, e, n)):
            out = Path(d) / f"f{i}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1",
                            str(out)], check=True)
            frames.append(Image.open(out).convert("RGB"))
        return frames, dur


def bbox(a):
    ys, xs = np.nonzero(a[..., 3])
    return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(ys) else None


def cleanup(video_frames, sprite, cell, origin_native, palette):
    sh, sw = sprite.shape[:2]
    keyed = [drop_specks(key_out(f), 60) for f in video_frames]
    b0 = bbox(keyed[0])
    step = (b0[3] - b0[1]) / sh
    cw, ch = cell
    ox, oy = origin_native
    corr_x, corr_y = ox - round(b0[0] / step), oy - round(b0[1] / step)
    frames = []
    for rgba in keyed:
        f = np.zeros((ch, cw, 4), np.uint8)
        b = bbox(rgba)
        if b:
            x0, y0, x1, y1 = b
            ow, oh = max(1, round((x1 - x0) / step)), max(1, round((y1 - y0) / step))
            small = majority_downscale(rgba[y0:y1, x0:x1], ow, oh)
            px, py = round(x0 / step) + corr_x, round(y0 / step) + corr_y
            ys, xs = slice(max(0, py), min(ch, py + oh)), slice(max(0, px), min(cw, px + ow))
            f[ys, xs] = small[ys.start - py:ys.stop - py, xs.start - px:xs.stop - px]
        frames.append(drop_specks(fill_seams(snap(f, palette)), 10))  # video adds dust particles
    f0 = np.zeros((ch, cw, 4), np.uint8)
    f0[oy:oy + sh, ox:ox + sw] = snap(sprite, palette)
    frames[0] = f0
    print(f"art pixel = {step:.2f} video px")
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("motion")
    ap.add_argument("-n", "--frames", type=int, default=12)
    ap.add_argument("--scale", type=int, default=12)
    ap.add_argument("--seconds", type=int, default=4)
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--model", default="veo-3.1-fast-generate-preview")
    ap.add_argument("--cell", type=int, default=0)
    ap.add_argument("--reuse", help="existing mp4 instead of calling Veo")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    sprite = load_sprite(a.image)
    sh, sw = sprite.shape[:2]
    frame, (fx, fy) = first_frame(sprite, a.scale)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.save(f"{out}_first.png")
    if a.reuse:
        mp4 = Path(a.reuse).read_bytes()
    else:
        prompt = (f"Pixel art game sprite animation. The character {a.motion}. Static camera, fixed perspective, "
                  "side view, the character stays the same size and keeps the exact same pixel-art design, colors "
                  "and chunky pixels. Flat solid magenta background for the whole video, no scenery, no shadows, "
                  "no motion blur, no camera movement, no zoom.")
        mp4, took = generate_video(a.model, prompt, frame, api_key(), a.seconds)
        print(f"{a.model}: {len(mp4) // 1024} KB in {took:.0f}s")
        Path(f"{out}_prompt.txt").write_text(prompt)
    Path(f"{out}.mp4").write_bytes(mp4)

    vframes, dur = extract_frames(mp4, a.frames, a.start, a.end)
    cell = a.cell or int(max(sh, sw) * 1.6)
    cell = (cell, cell)
    origin = ((cell[0] - sw) // 2, cell[1] - sh - 2)
    palette = kmeans_palette(sprite, 16)
    frames = cleanup(vframes, sprite, cell, origin, palette)

    Image.fromarray(np.concatenate(frames, 1)).save(f"{out}_sheet.png")
    big = []
    for f in frames:
        im = Image.new("RGBA", cell, (232, 234, 240, 255))
        fi = Image.fromarray(f)
        im.paste(fi, (0, 0), fi)
        big.append(im.convert("RGB").resize((cell[0] * 6, cell[1] * 6), Image.NEAREST))
    big[0].save(f"{out}.gif", save_all=True, append_images=big[1:], duration=100, loop=0)
    Path(f"{out}.json").write_text(json.dumps({"frame_width": cell[0], "frame_height": cell[1],
                                               "frames": len(frames), "fps": 10, "model": a.model,
                                               "clip_seconds": dur}, indent=2))
    print(f"{len(frames)} frames {cell[0]}x{cell[1]} from {dur:.1f}s clip -> {out}_sheet.png")


if __name__ == "__main__":
    main()
