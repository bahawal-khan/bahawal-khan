#!/usr/bin/env python3
"""
Rotating 3D contribution skyline (animated GIF) for a GitHub profile README.

Your last 12 weeks of contributions become green 3D towers (taller = more
contributions) on a dark plate that slowly spins forever.

Why a GIF? It animates everywhere - desktop browsers and the GitHub mobile app -
with no JavaScript/CSS needed.

Needs Pillow:  pip install pillow
Usage (Actions): GITHUB_TOKEN=... USERNAME=... python skyline.py
Local preview  : python skyline.py --demo
"""
import hashlib
import math
import os
import sys
from datetime import timedelta

from PIL import Image, ImageDraw

# reuse the data code from generate_stats.py (same folder)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_stats import demo_days, fetch_days  # noqa: E402

OUT_DIR = os.environ.get("OUT_DIR", "profile-stats")

# ---- look & feel ----------------------------------------------------------- #
W, H = 560, 340           # final GIF size
SS = 2                    # supersampling for smooth edges
WEEKS = 12                # weeks shown
CELL = 14                 # world size of one day-cell
BAR = 0.74                # bar footprint relative to cell
MAX_H = 62                # tallest tower (world units)
PITCH = math.radians(50)  # camera tilt
SCALE = 1.85              # world -> pixels
FRAMES = 90               # 90 frames * 4 degrees = one full turn
FRAME_MS = 100

BG = (13, 17, 23)
PLATE_TOP = (22, 29, 38)
PLATE_SIDE = (14, 19, 26)
TILE = (31, 40, 52)
LEVEL_RGB = [(31, 40, 52), (14, 90, 52), (0, 140, 70), (38, 190, 70), (57, 230, 90)]


def window(days):
    last = max(days)
    start = last - timedelta(days=(last.weekday() + 1) % 7 + (WEEKS - 1) * 7)
    cells = []
    for w in range(WEEKS):
        for dow in range(7):
            d = start + timedelta(days=w * 7 + dow)
            if d > last:
                continue
            count, level = days.get(d, (0, 0))
            cells.append((w, dow, count, level))
    return cells


def shade(rgb, k):
    return tuple(max(0, min(255, int(c * k))) for c in rgb)


def render_frame(cells, maxc, yaw):
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    sin_p, cos_p = math.sin(PITCH), math.cos(PITCH)
    cx, cy = W * SS / 2, H * SS * 0.60
    k = SCALE * SS

    def proj(x, y, z):
        xr = x * cos_y - y * sin_y
        yr = x * sin_y + y * cos_y
        return (cx + k * xr, cy - k * (yr * sin_p + z * cos_p)), yr

    img = Image.new("RGB", (W * SS, H * SS), BG)
    dr = ImageDraw.Draw(img)

    # plate
    half_x, half_y = WEEKS * CELL / 2 + 6, 7 * CELL / 2 + 6
    corners = [(-half_x, -half_y), (half_x, -half_y), (half_x, half_y), (-half_x, half_y)]
    PT = 5  # plate thickness
    top = [proj(x, y, 0)[0] for x, y in corners]
    # plate side faces that face the camera
    for (x1, y1), (x2, y2) in zip(corners, corners[1:] + corners[:1]):
        nx, ny = (y2 - y1), -(x2 - x1)           # outward normal (unnormalised)
        if (nx * sin_y + ny * cos_y) < 0:        # faces camera
            quad = [proj(x1, y1, 0)[0], proj(x2, y2, 0)[0], proj(x2, y2, -PT)[0], proj(x1, y1, -PT)[0]]
            dr.polygon(quad, fill=PLATE_SIDE)
    dr.polygon(top, fill=PLATE_TOP)

    # towers, drawn far -> near
    boxes = []
    for (w, dow, count, level) in cells:
        x = (w - (WEEKS - 1) / 2) * CELL
        y = (dow - 3) * CELL
        _, depth = proj(x, y, 0)
        boxes.append((depth, x, y, count, level))
    boxes.sort(key=lambda b: -b[0])

    half = CELL * BAR / 2
    for _, x, y, count, level in boxes:
        if count == 0:
            h, base = 0.8, TILE
        else:
            h = 7 + MAX_H * (count / maxc) ** 0.6
            base = LEVEL_RGB[max(1, level)]
        pts = [(x - half, y - half), (x + half, y - half), (x + half, y + half), (x - half, y + half)]
        # visible side faces
        for i in range(4):
            (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % 4]
            nx, ny = (y2 - y1), -(x2 - x1)
            nlen = math.hypot(nx, ny) or 1
            nx, ny = nx / nlen, ny / nlen
            if (nx * sin_y + ny * cos_y) < 0:
                nxr = nx * cos_y - ny * sin_y
                quad = [proj(x1, y1, 0.4)[0], proj(x2, y2, 0.4)[0], proj(x2, y2, h)[0], proj(x1, y1, h)[0]]
                dr.polygon(quad, fill=shade(base, 0.68 - 0.24 * nxr))
        dr.polygon([proj(px, py, h)[0] for px, py in pts], fill=base)

    return img.resize((W, H), Image.LANCZOS)


def build_gif(cells, path):
    maxc = max((c for _, _, c, _ in cells), default=1) or 1
    frames = [render_frame(cells, maxc, math.radians(i * 360 / FRAMES + 25)) for i in range(FRAMES)]

    # one shared palette (keeps the file small) + transparent rounded corners
    pal_src = frames[len(frames) // 3].quantize(colors=62, method=Image.Quantize.MEDIANCUT)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=14, fill=255)
    out = []
    for f in frames:
        p = f.quantize(palette=pal_src, dither=Image.Dither.NONE)
        px = p.load()
        mpx = mask.load()
        for y in range(H):
            for x in range(W):
                if mpx[x, y] < 128:
                    px[x, y] = 63
        out.append(p)
    pal = pal_src.getpalette()[: 62 * 3]
    pal += [0, 0, 0] * (63 - len(pal) // 3) + [255, 0, 255]
    for p in out:
        p.putpalette(pal)
    out[0].save(
        path,
        save_all=True,
        append_images=out[1:],
        duration=FRAME_MS,
        loop=0,
        transparency=63,
        disposal=2,
        optimize=False,
    )


def main():
    login = os.environ.get("USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "octocat"
    if "--demo" in sys.argv:
        days = demo_days()
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            sys.exit("GITHUB_TOKEN is missing")
        days = fetch_days(token, login)
    if not days:
        sys.exit("No contribution data returned - keeping the existing skyline")

    cells = window(days)
    os.makedirs(OUT_DIR, exist_ok=True)
    gif_path = os.path.join(OUT_DIR, "skyline.gif")
    hash_path = os.path.join(OUT_DIR, "skyline.hash")

    # only re-render (and re-commit a ~1MB file) when the numbers actually changed
    digest = hashlib.md5(repr(cells).encode()).hexdigest()
    if os.path.exists(gif_path) and os.path.exists(hash_path) and open(hash_path).read().strip() == digest:
        print("skyline unchanged - skipping")
        return

    build_gif(cells, gif_path)
    with open(hash_path, "w") as f:
        f.write(digest)
    print(f"wrote {gif_path} ({os.path.getsize(gif_path) // 1024} KB) for @{login}")


if __name__ == "__main__":
    main()
