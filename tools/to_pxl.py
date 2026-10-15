"""Convert a pixel-art PNG into a pxl grid string with a mnemonic palette.

Usage:
  python tools/to_pxl.py samples/ninja/ninja-base.png --keys k=#030104,n=#171b3f,... [--crop x0,y0,x1,y1]

Every opaque pixel maps to the nearest key color; transparent pixels become ".".
Prints `pal({...})` and the grid as a JS template literal, ready to paste into a .px.js file.
"""
import argparse

import numpy as np
from PIL import Image


def parse_keys(s):
    out = {}
    for item in s.split(","):
        k, v = item.split("=")
        v = v.lstrip("#")
        out[k] = tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    return out


def to_grid(a, keys):
    names = list(keys)
    cols = np.array([keys[k] for k in names], int)
    rows = []
    for y in range(a.shape[0]):
        row = ""
        for x in range(a.shape[1]):
            p = a[y, x]
            if p[3] < 128:
                row += "."
            else:
                row += names[int(((cols - p[:3].astype(int)) ** 2).sum(1).argmin())]
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--keys", required=True)
    ap.add_argument("--crop")
    a = ap.parse_args()
    keys = parse_keys(a.keys)
    img = np.asarray(Image.open(a.image).convert("RGBA"))
    if a.crop:
        x0, y0, x1, y1 = map(int, a.crop.split(","))
        img = img[y0:y1, x0:x1]
    print("pal({ " + ", ".join(f'{k}: "#{"%02x%02x%02x" % v}"' for k, v in keys.items()) + " })")
    print("`\n" + "\n".join("  " + r for r in to_grid(img, keys)) + "`")


if __name__ == "__main__":
    main()
