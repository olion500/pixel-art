"""Lock the head to the source pixels in every frame where it is upright (identity consistency).

Generated frames redraw the helmet slightly differently each time (visor pattern, width), which reads
as flicker. For each frame, the source head (helmet + visor) is matched over a small window and, where
the match is good (the head is upright and unoccluded), its exact source pixels are stamped back.
This is the aseprite-ai-artist "grid loop" fix done in bulk: change only the characters that are wrong.

Usage (library): lock_heads(frames, sprite, head_rect) -> (frames, report)
"""
import numpy as np


def head_part(sprite, rect):
    x0, y0, x1, y1 = rect
    part = sprite[y0:y1 + 1, x0:x1 + 1]
    return part, (x0, y0)


def match(frame, part, guess, radius=8):
    """Best (x, y, err): mean color error over the part's opaque pixels, transparent target = max error."""
    ph, pw = part.shape[:2]
    m = part[..., 3] > 0
    pc = part[..., :3].astype(int)
    best = None
    gx, gy = guess
    for y in range(gy - radius, gy + radius + 1):
        for x in range(gx - radius, gx + radius + 1):
            if y < 0 or x < 0 or y + ph > frame.shape[0] or x + pw > frame.shape[1]:
                continue
            win = frame[y:y + ph, x:x + pw]
            d = np.abs(win[..., :3].astype(int) - pc).sum(-1)
            d = np.where(win[..., 3] > 0, d, 765)
            err = d[m].mean()
            if best is None or err < best[2]:
                best = (x, y, err)
    return best


def lock_heads(frames, sprite, rect, origin, max_err=120):
    part, (px, py) = head_part(sprite, rect)
    m = part[..., 3] > 0
    out, report = [], []
    prev = (origin[0] + px, origin[1] + py)
    for i, f in enumerate(frames):
        x, y, err = match(f, part, prev)
        g = f.copy()
        if err <= max_err:
            region = g[y:y + part.shape[0], x:x + part.shape[1]]
            region[m] = part[m]
            prev = (x, y)
            report.append((i, x, y, round(err), "locked"))
        else:
            report.append((i, x, y, round(err), "kept (tilted/occluded)"))
        out.append(g)
    return out, report
