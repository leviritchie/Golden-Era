#!/usr/bin/env python3
"""Disassemble the installed game's compiled ``Hex/Lit`` pixel shaders (read-only).

Finds the Hex/Lit Shader object in ``resources.assets``, decompresses its program blobs,
cuts out every embedded DXBC container and runs Windows ``D3DDisassemble``
(d3dcompiler_47.dll) on the pixel shaders. Writes the shortest few Lit-pass pixel
shaders to ``artifacts/homm3_prebaked_lighting/hex_lit_ps/`` so the runtime lighting
model can be read directly instead of guessed.

Proof tier: source/static (compiled shader bytecode). It shows what the shader computes
given its inputs; it does not show the per-frame values the game feeds it.
"""
from __future__ import annotations

import argparse
import ctypes
import struct
import sys
from pathlib import Path

import UnityPy

ROOT = Path(__file__).resolve().parents[2]
GAME = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")
OUT = ROOT / "artifacts/homm3_prebaked_lighting/hex_lit_ps"


def lz4_block(src: bytes, size: int) -> bytes:
    import lz4.block
    return lz4.block.decompress(src, uncompressed_size=size)


def disassemble(dxbc: bytes) -> str:
    lib = ctypes.WinDLL("d3dcompiler_47.dll")
    blob = ctypes.c_void_p()
    rc = lib.D3DDisassemble(dxbc, len(dxbc), 0, None, ctypes.byref(blob))
    if rc != 0:
        return ""
    vt = ctypes.cast(ctypes.cast(blob, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    get_ptr = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(vt[3])
    get_size = ctypes.WINFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p)(vt[4])
    ptr, size = get_ptr(blob), get_size(blob)
    return ctypes.string_at(ptr, size).decode("latin-1")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shader", default="Hex/Lit", help="installed shader name (e.g. Hidden/Hex/ContourLines)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--all-ps", action="store_true",
                    help="keep every pixel shader, not only lit-shaped ones (post effects have no light dp3)")
    args = ap.parse_args()
    out_dir = args.out
    env = UnityPy.load(str(GAME / "resources.assets"))
    shader = None
    for obj in env.objects:
        if obj.type.name == "Shader":
            data = obj.read()
            if data.m_ParsedForm.m_Name == args.shader:
                shader = data
                break
    if shader is None:
        raise SystemExit(f"{args.shader} not found")
    blobs = []
    offsets = shader.offsets if isinstance(shader.offsets[0], list) else [shader.offsets]
    csizes = shader.compressedLengths if isinstance(shader.compressedLengths[0], list) else [shader.compressedLengths]
    dsizes = shader.decompressedLengths if isinstance(shader.decompressedLengths[0], list) else [shader.decompressedLengths]
    raw = bytes(shader.compressedBlob)
    for plat, (offs, cs, ds) in enumerate(zip(offsets, csizes, dsizes)):
        for off, c, d in zip(offs, cs, ds):
            blobs.append(lz4_block(raw[off:off + c], d))
    out_dir.mkdir(parents=True, exist_ok=True)
    found = []
    for bi, blob in enumerate(blobs):
        start = 0
        while True:
            i = blob.find(b"DXBC", start)
            if i < 0:
                break
            size = struct.unpack_from("<I", blob, i + 24)[0]
            dx = blob[i:i + size]
            start = i + 4
            text = disassemble(dx)
            # Unity strips reflection names, so select by shape: a pixel shader that
            # samples a texture and takes a dot product against a constant (a light).
            if text and "\nps_" in text and "sample" in text and "dp3" in text:
                found.append(f"// blob {bi} offset {i}\n" + text)
            if len(found) > 4000:
                break
    found.sort(key=len)
    print("lit-shaped pixel shaders:", len(found))
    for n, text in enumerate(found[:6]):
        (out_dir / f"ps_{n:02d}.txt").write_text(text, encoding="utf-8")
    if found:
        (out_dir / "ps_longest.txt").write_text(found[-1], encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
