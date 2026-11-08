"""Repair only non-conformant trailing JSON padding in generated GLBs.

The operation is byte-local: JSON and BIN payloads are not reserialized, and
animation, meshes, weights, and hashes inside the JSON document are unchanged.
It exists for older candidates written before ``eagle_glb`` used GLB-compliant
space padding for JSON chunks.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


def repair_json_padding(path: Path) -> bool:
    data = bytearray(path.read_bytes())
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB file: {path}")
    offset = 12
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<I4s", data, offset)
        start, end = offset + 8, offset + 8 + int(length)
        if end > len(data):
            raise ValueError(f"truncated GLB chunk: {path}")
        if kind == b"JSON":
            payload = bytes(data[start:end])
            try:
                json.loads(payload.decode("utf-8"))
                return False
            except json.JSONDecodeError:
                stripped = payload.rstrip(b"\x00 \t\r\n")
                padding = payload[len(stripped):]
                if not padding or any(value not in (0, 9, 10, 13, 32) for value in padding):
                    raise ValueError(f"JSON chunk is malformed beyond trailing padding: {path}")
                json.loads(stripped.decode("utf-8"))
                data[start:end] = stripped + b" " * (len(payload) - len(stripped))
                path.write_bytes(data)
                return True
        offset = end
    raise ValueError(f"GLB has no JSON chunk: {path}")


def repair_root(root: Path) -> dict[str, int]:
    scanned = repaired = 0
    for path in sorted(root.glob("*/weights_only_v1/*_candidate.glb")):
        scanned += 1
        repaired += int(repair_json_padding(path))
    return {"scanned": scanned, "repaired": repaired}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("artifacts/homm3_mocap_v2/all_mocap_candidates"))
    args = parser.parse_args()
    print(json.dumps(repair_root(args.root.resolve()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
