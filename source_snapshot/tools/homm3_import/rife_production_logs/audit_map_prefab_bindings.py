#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

lab = Path(r"V:/homm3_unity_work/Assets/CustomUnits/homm3_lab")
unit_list = Path(
    r"V:/Games/Olden Era Playtest Tweak/tools/homm3_import/rife_production_logs/factory_bulwark_map_rebuild_unit_list.txt"
)
sids = [
    ln.strip()
    for ln in unit_list.read_text(encoding="utf-8").splitlines()
    if ln.strip() and not ln.startswith("#")
]

guid_to_path: dict[str, str] = {}
for meta in Path(r"V:/homm3_unity_work/Assets/CustomUnits").rglob("map_frame_000.mat.meta"):
    text = meta.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^guid:\s*([a-f0-9]{32})", text, re.M)
    if m:
        guid_to_path[m.group(1)] = meta.with_suffix("").as_posix()

stale: list[tuple[str, str]] = []
ok: list[str] = []
missing_prefab: list[str] = []
missing_local_mat: list[str] = []
for sid in sids:
    prefab = lab / sid / "map.prefab"
    local_mat = lab / sid / "Generated" / "MapBillboard" / "Materials" / "map_frame_000.mat"
    if not prefab.is_file():
        missing_prefab.append(sid)
        continue
    if not local_mat.is_file():
        missing_local_mat.append(sid)
    text = prefab.read_text(encoding="utf-8", errors="ignore")
    guids = re.findall(r"2100000, guid: ([a-f0-9]{32})", text)
    if not guids:
        stale.append((sid, "NO_MAT_REF"))
        continue
    path = guid_to_path.get(guids[0], f"UNKNOWN:{guids[0]}")
    expected = f"homm3_lab/{sid}/Generated/MapBillboard/Materials/map_frame_000.mat"
    if expected not in path.replace("\\", "/"):
        stale.append((sid, path))
    else:
        ok.append(sid)

print(f"OK bound to local map_frame_000: {len(ok)}")
print(f"STALE/wrong material: {len(stale)}")
for sid, path in stale:
    print(f"  STALE {sid}: {path}")
print(f"missing prefab: {missing_prefab}")
print(f"missing local mat: {missing_local_mat}")
need = sorted({sid for sid, _ in stale} | set(missing_local_mat) | set(missing_prefab))
out = Path(
    r"V:/Games/Olden Era Playtest Tweak/tools/homm3_import/rife_production_logs/factory_bulwark_map_rebind_unit_list.txt"
)
out.write_text("\n".join(need) + ("\n" if need else ""), encoding="utf-8")
print(f"wrote rebind list ({len(need)}): {out}")
print("sample OK:", ok[:5])
