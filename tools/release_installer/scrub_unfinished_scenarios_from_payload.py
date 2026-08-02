#!/usr/bin/env python3
"""Remove unfinished/test scenario files from the public release payload zip."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

SRC = Path("release_inputs/golden_era_release_payload.zip")
DST = Path("release_inputs/golden_era_release_payload.scrubbed.zip")
TOKENS = (
    "layered_atlas",
    "zone_atlas",
    "approach_cell",
    "single_layer",
    "underground_slice",
    "handedit",
    "_poc",
    "vanilla_stock",
    "water_example",
    "proc_exploration_",
    "proc_objective_chain_",
    ".procedural_scenarios",
    "broken",
)


def forbidden(name: str) -> bool:
    full = name.replace("\\", "/").lower()
    if not full.startswith("payload/streaming_assets/"):
        return False
    leaf = Path(full).name
    if any(token in full for token in TOKENS):
        return True
    if leaf.startswith("proc_") and leaf.endswith((".map", ".json")):
        return True
    return False


def main() -> int:
    if not SRC.is_file():
        raise SystemExit(f"missing {SRC}")

    # Prefer scrubbing the pre-scrub backup if a failed scrub already replaced nothing useful.
    source = SRC
    backup_existing = SRC.with_suffix(".zip.prescrub")
    if backup_existing.is_file() and backup_existing.stat().st_size >= SRC.stat().st_size:
        source = backup_existing
        print(f"using backup source: {source}")

    removed: list[str] = []
    kept = 0
    if DST.exists():
        DST.unlink()

    print(f"scrubbing {source} -> {DST}")
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(DST, "w") as zout:
        for index, info in enumerate(zin.infolist(), start=1):
            if info.is_dir():
                continue
            if forbidden(info.filename):
                removed.append(info.filename.replace("\\", "/"))
                continue

            data = zin.read(info.filename)
            out_info = zipfile.ZipInfo(filename=info.filename.replace("\\", "/"))
            out_info.date_time = info.date_time
            out_info.external_attr = info.external_attr
            # Preserve store-vs-deflate; use fastest deflate when compressing.
            if info.compress_type == zipfile.ZIP_STORED or info.file_size == info.compress_size:
                out_info.compress_type = zipfile.ZIP_STORED
                zout.writestr(out_info, data)
            else:
                out_info.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(out_info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)
            kept += 1
            if index % 2000 == 0:
                print(f"  processed {index} source entries; kept={kept} removed={len(removed)}")

    digest = hashlib.sha256(DST.read_bytes()).hexdigest()
    print(f"kept={kept} removed={len(removed)}")
    print(f"old_size={source.stat().st_size} new_size={DST.stat().st_size}")
    print(f"sha256={digest}")
    for path in removed:
        print(" REM", path)

    final_backup = SRC.with_suffix(".zip.prescrub")
    if source.resolve() != final_backup.resolve():
        if final_backup.exists():
            final_backup.unlink()
        SRC.replace(final_backup)
    elif SRC.exists() and SRC.resolve() != final_backup.resolve():
        SRC.unlink()
    DST.replace(SRC)
    SRC.with_suffix(".zip.sha256").write_text(f"{digest}  {SRC.name}\n", encoding="ascii")
    print(f"replaced {SRC}")
    print(f"backup at {final_backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
