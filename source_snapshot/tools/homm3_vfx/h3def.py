"""Minimal HoMM3 LOD + DEF reader that keeps palette indices.

Used by the VFX experiments (docs/homm3_vfx_experiments.md). Unlike the PNG
extracts under homm3_unity_work, this keeps the raw indexed frames so special
palette slots (0 transparent, 1/4 shadow, 5 selection, 6/7 shadow-under-selection)
and any cycling ranges can be measured instead of guessed.
"""
from __future__ import annotations

import pathlib
import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

DEFAULT_LODS = [
    pathlib.Path(r"V:/Games/Olden Era Playtest Tweak/HoMM 3 Complete/Data/H3sprite.lod"),
    pathlib.Path(r"V:/Games/Olden Era Playtest Tweak/HoMM 3 Complete/Data/H3ab_spr.lod"),
]


def lod_index(path: pathlib.Path) -> dict[str, tuple[int, int, int]]:
    with open(path, "rb") as f:
        if f.read(4) != b"LOD\0":
            raise ValueError(f"not a LOD: {path}")
        f.seek(8)
        (total,) = struct.unpack("<I", f.read(4))
        f.seek(92)
        out = {}
        for _ in range(total):
            name = f.read(16).split(b"\0", 1)[0].decode("latin-1").lower()
            off, size, _typ, csize = struct.unpack("<IIII", f.read(16))
            out[name] = (off, size, csize)
    return out


def lod_read(name: str, lods=DEFAULT_LODS) -> bytes:
    name = name.lower()
    for lod in lods:
        idx = lod_index(lod)
        if name in idx:
            off, size, csize = idx[name]
            with open(lod, "rb") as f:
                f.seek(off)
                raw = f.read(csize or size)
            return zlib.decompress(raw) if csize else raw
    raise FileNotFoundError(name)


@dataclass
class Frame:
    name: str
    fmt: int
    full: tuple[int, int]
    size: tuple[int, int]
    left: int
    top: int
    idx: np.ndarray  # full-canvas uint8 palette indices


@dataclass
class Def:
    name: str
    typ: int
    size: tuple[int, int]
    palette: np.ndarray  # (256,3) uint8
    groups: dict[int, list[Frame]] = field(default_factory=dict)


def _decode(data: bytes, off: int) -> Frame:
    size, fmt, fw, fh, w, h, left, top = struct.unpack_from("<IIIIIIii", data, off)
    base = off + 32
    canvas = np.zeros((fh, fw), np.uint8)
    img = np.zeros((h, w), np.uint8)
    if fmt == 0:
        img[:] = np.frombuffer(data, np.uint8, w * h, base).reshape(h, w)
    elif fmt == 1:
        offs = struct.unpack_from(f"<{h}I", data, base)
        for y in range(h):
            p = base + offs[y]
            x = 0
            while x < w:
                code, ln = data[p], data[p + 1] + 1
                p += 2
                if code == 0xFF:
                    img[y, x:x + ln] = np.frombuffer(data, np.uint8, ln, p)
                    p += ln
                else:
                    img[y, x:x + ln] = code
                x += ln
    elif fmt in (2, 3):
        step = 1 if fmt == 2 else max(1, w // 32)
        for y in range(h):
            (lo,) = struct.unpack_from("<H", data, base + y * 2 * step)
            p = base + lo
            x = 0
            while x < w:
                b = data[p]
                p += 1
                code, ln = b >> 5, (b & 31) + 1
                if code == 7:
                    img[y, x:x + ln] = np.frombuffer(data, np.uint8, min(ln, w - x), p)[: ln]
                    p += ln
                else:
                    img[y, x:x + ln] = code
                x += ln
    else:
        raise ValueError(f"unknown DEF frame format {fmt}")
    canvas[top:top + h, left:left + w] = img
    return Frame("", fmt, (fw, fh), (w, h), left, top, canvas)


def read_def(name: str, lods=DEFAULT_LODS) -> Def:
    data = lod_read(name, lods)
    typ, w, h, nblocks = struct.unpack_from("<IIII", data, 0)
    pal = np.frombuffer(data, np.uint8, 768, 16).reshape(256, 3).copy()
    d = Def(name, typ, (w, h), pal)
    p = 16 + 768
    for _ in range(nblocks):
        gid, count, _u1, _u2 = struct.unpack_from("<IIII", data, p)
        p += 16
        names = [data[p + i * 13:p + i * 13 + 13].split(b"\0", 1)[0].decode("latin-1") for i in range(count)]
        p += 13 * count
        offs = struct.unpack_from(f"<{count}I", data, p)
        p += 4 * count
        frames = []
        for n, o in zip(names, offs):
            fr = _decode(data, o)
            fr.name = n
            frames.append(fr)
        d.groups[gid] = frames
    return d


# HoMM3 creature-DEF special slots, as the engine treats them (VCMI's reading):
SPECIAL = {0: "transparent", 1: "shadow_border(~25%)", 2: "unused/shadow", 3: "unused/shadow",
           4: "shadow_body(~50%)", 5: "selection_outline", 6: "shadow_body_under_selection",
           7: "shadow_border_under_selection"}
SPECIAL_ALPHA = {0: 0, 1: 64, 2: 0, 3: 0, 4: 128, 5: 0, 6: 128, 7: 64}


def to_rgba(frame: Frame, pal: np.ndarray, special=True) -> np.ndarray:
    rgba = np.zeros(frame.idx.shape + (4,), np.uint8)
    rgba[..., :3] = pal[frame.idx]
    rgba[..., 3] = 255
    if special:
        for i, a in SPECIAL_ALPHA.items():
            m = frame.idx == i
            rgba[m, :3] = 0
            rgba[m, 3] = a
    return rgba
