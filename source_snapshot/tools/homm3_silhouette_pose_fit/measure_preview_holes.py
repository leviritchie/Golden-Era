#!/usr/bin/env python3
"""Measure enclosed background holes in lit preview frames.

Segments the uniform gray background, flood-fills from the image border, and
reports background pixels fully enclosed by mesh (holes). Use to decide whether
"floating armor pieces" gaps exist in the authored poses or only in the game.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image


def analyze(path: Path, bg=(81, 84, 94), tol: int = 14) -> dict:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()

    def is_bg(x: int, y: int) -> bool:
        r, g, b = px[x, y]
        return abs(r - bg[0]) <= tol and abs(g - bg[1]) <= tol and abs(b - bg[2]) <= tol

    # Border flood fill (background only)
    from collections import deque
    visited = [[False] * w for _ in range(h)]
    dq = deque()
    for x in range(w):
        if is_bg(x, 0) and not visited[0][x]:
            visited[0][x] = True
            dq.append((x, 0))
        if is_bg(x, h - 1) and not visited[h - 1][x]:
            visited[h - 1][x] = True
            dq.append((x, h - 1))
    for y in range(h):
        if is_bg(0, y) and not visited[y][0]:
            visited[y][0] = True
            dq.append((0, y))
        if is_bg(w - 1, y) and not visited[y][w - 1]:
            visited[y][w - 1] = True
            dq.append((w - 1, y))
    while dq:
        x, y = dq.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx] and is_bg(nx, ny):
                visited[ny][nx] = True
                dq.append((nx, ny))

    # Enclosed holes: background pixels not reached from border.
    holes: list[int] = []
    seen = [[False] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if is_bg(x, y) and not visited[y][x] and not seen[y][x]:
                stack = [(x, y)]
                seen[y][x] = True
                size = 0
                while stack:
                    cx, cy = stack.pop()
                    size += 1
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and is_bg(nx, ny) and not visited[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
                holes.append(size)

    mesh_px = sum(1 for y in range(0, h, 2) for x in range(0, w, 2) if not is_bg(x, y)) * 4
    return {
        "size": f"{w}x{h}",
        "mesh_px": mesh_px,
        "hole_count": len(holes),
        "hole_px": sum(holes),
        "holes_largest": sorted(holes, reverse=True)[:8],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    args = ap.parse_args()
    for p in args.paths:
        if not p.is_file():
            print(f"{p}: MISSING")
            continue
        print(f"{p.name}: {analyze(p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
