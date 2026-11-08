"""Regression test for the per-faction grazing drop (stronghold_full3d_solids.SINK_RIM_GRAZE_DROP).

The walled-rim back triangles over a sunk step are kept by default: dropping them opens Cove tbcvnmp2 (orbit y-18
24593 -> 30023 see-through px). Bulwark opts in because one grazing tbbum401 triangle fails its gate by 1 px per
cursor pose. This pins both sides as the stage module reads them (Bulwark on, Cove and every other faction off) and
the grazing predicate itself (a plane containing the camera ray is grazing, one facing the camera is not).

Run: python tools/homm3_town_scene_meshes/test_town_full3d_graze_drop.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OPTED_IN = {"bulwark": {"maxCos": 0.02}}
PROBE = "import stronghold_full3d_solids as SO; print(repr(SO.SINK_RIM_GRAZE_DROP))"


def faction_value(key: str):
    env = {**os.environ, "TOWN_FULL3D_FACTION": key}
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=HERE, env=env, capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise AssertionError(f"{key}: {r.stderr.strip()[-400:]}")
    return eval(r.stdout.strip().splitlines()[-1])


def main() -> int:
    keys = sorted(p.stem for p in (HERE / "town_full3d_factions").glob("*.py") if p.stem != "__init__")
    assert "cove" in keys and "bulwark" in keys, keys
    for k in keys:
        got = faction_value(k)
        assert got == OPTED_IN.get(k), f"{k}: SINK_RIM_GRAZE_DROP {got!r}, expected {OPTED_IN.get(k)!r}"
    os.environ.setdefault("TOWN_FULL3D_FACTION", "stronghold")
    sys.path.insert(0, str(HERE))
    import stronghold_full3d_solids as SO
    cam = np.zeros(3)
    # facing the camera: plane z = 50
    face = np.array([[-1.0, -1.0, 50.0], [1.0, -1.0, 50.0], [0.0, 1.0, 50.0]])
    # grazing: the plane x = 0.1 * z holds the ray to its centroid up to a small tilt
    graze = np.array([[5.0, 0.0, 50.0], [5.05, 1.0, 50.5], [6.0, 0.0, 60.0]])
    P = np.concatenate([face, graze])
    hit = SO.grazing(P, np.array([[0, 1, 2], [3, 4, 5]]), cam, 0.02)
    assert hit.tolist() == [False, True], hit
    print(f"OK graze drop: opted in {sorted(OPTED_IN)}, off for {len(keys) - len(OPTED_IN)} other factions "
          f"(cove included); predicate separates facing from grazing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
