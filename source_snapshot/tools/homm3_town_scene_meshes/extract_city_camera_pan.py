#!/usr/bin/env python3
"""Extract the vanilla town-screen camera motion (BhCityCameraController + SoCityCameraSettings) from the game data.

The town camera is not static: BhCityCameraController moves the MainCamera along a looped list of world positions
(SoCityCameraSettings.positionNodes; the first loop on firstLoopMovementSpeedCurve, later loops on movementSpeedCurve,
capped at maxMovementSpeed) and adds a look offset bounded by deltaHorizontalAngle / deltaVerticalAngle. The scene
component holds lookAtTransform (the CityCamera pivot) and cameraTransform (MainCamera, a child of the pivot).

IL2CPP MonoBehaviours carry no typetree, so both objects are parsed from raw bytes; the layouts were read field by
field against the interop declaration order (tools/release_decomp_20260509/Hex.decompiled.cs: BhCityCameraController
settings, lookAtTransform, cameraTransform, lensFlares; SoCityCameraSettings rotationSpeed, deltaHorizontalAngle,
deltaVerticalAngle, maxMovementSpeed, firstLoopMovementSpeedCurve, movementSpeedCurve, positionNodes,
transitionTime), and a parse must consume the settings object exactly (fail closed otherwise).

Method bodies are not in the interop dump, so the camera's orientation while it moves is not read by this script. The
GameAssembly disassembly (conflux_town_camera_pan.py docstring) shows the free sweep calls Transform.LookAt on the
pivot; consumers still sample the fixed-rotation hypothesis as a margin.

    python tools/homm3_town_scene_meshes/extract_city_camera_pan.py [--out tools/homm3_town_scene_meshes/vanilla_city_camera_pan.json]

Read-only against the installed game. Proof tier: game-asset readback (static), not runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

import UnityPy

ROOT = Path(__file__).resolve().parents[2]
GAME = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data")
OUT = ROOT / "tools" / "homm3_town_scene_meshes" / "vanilla_city_camera_pan.json"
# Build-settings scene index -> level file (globalgamemanagers BuildSettings).
LEVELS = {"cityHuman2": "level67", "CityUndead2": "level69", "cityUnfrozen2": "level72", "cityDungeon": "level39",
          "cityNature": "level38", "cityDemon": "level40"}
MB_HEADER = 32  # m_GameObject PPtr (12) + m_Enabled (4, aligned) + m_Script PPtr (12) + m_Name "" (4)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def parse_settings(raw: bytes) -> dict:
    p = 12 + 4 + 12
    ln = struct.unpack_from("<i", raw, p)[0]
    name = raw[p + 4:p + 4 + ln].decode("utf-8")
    p = (p + 4 + ln + 3) & ~3

    def f():
        nonlocal p
        v = struct.unpack_from("<f", raw, p)[0]
        p += 4
        return v

    def i():
        nonlocal p
        v = struct.unpack_from("<i", raw, p)[0]
        p += 4
        return v

    def curve():
        nonlocal p
        n = i()
        ks = [struct.unpack_from("<ffffiff", raw, p + 28 * k) for k in range(n)]
        p += 28 * n
        pre, post, _rot = i(), i(), i()
        return {"keys": [[round(x, 5) for x in (k[0], k[1], k[2], k[3])] for k in ks], "preWrap": pre, "postWrap": post}

    out = {"name": name, "rotationSpeed": f(), "deltaHorizontalAngle": f(), "deltaVerticalAngle": f(),
           "maxMovementSpeed": f()}
    out["firstLoopMovementSpeedCurve"] = curve()
    out["movementSpeedCurve"] = curve()
    n = i()
    out["positionNodes"] = [[round(c, 4) for c in struct.unpack_from("<fff", raw, p + 12 * k)] for k in range(n)]
    p += 12 * n
    out["transitionTime"] = f()
    if p != len(raw):
        raise SystemExit(f"SoCityCameraSettings {name}: parsed {p} of {len(raw)} bytes (layout drift)")
    return out


def world_pose(t) -> tuple[list, list]:
    """World position / rotation of a Transform by walking m_Father (UnityPy objects)."""
    import numpy as np
    from scipy.spatial.transform import Rotation as R

    pos = np.zeros(3)
    rot = R.identity()
    scale = np.ones(3)
    chain = []
    while t is not None:
        chain.append(t)
        t = t.m_Father.read() if t.m_Father.path_id else None
    for tr in reversed(chain):
        lp = np.array([tr.m_LocalPosition.x, tr.m_LocalPosition.y, tr.m_LocalPosition.z])
        ls = np.array([tr.m_LocalScale.x, tr.m_LocalScale.y, tr.m_LocalScale.z])
        q = tr.m_LocalRotation
        if np.ptp(ls) > 1e-4 * np.abs(ls).max():
            raise SystemExit(f"non-uniform scale on camera chain ({ls})")
        pos = pos + rot.apply(scale * lp)
        rot = rot * R.from_quat([q.x, q.y, q.z, q.w])
        scale = scale * ls
    return pos.round(4).tolist(), [round(x, 6) for x in rot.as_quat()]


def local_pose(t) -> tuple[list[float], list[float]]:
    p, q = t.m_LocalPosition, t.m_LocalRotation
    pos = [float(p.x), float(p.y), float(p.z)]
    rot = [float(q.x), float(q.y), float(q.z), float(q.w)]
    if rot[3] < 0:
        rot = [-v for v in rot]
    return [round(v, 8) for v in pos], [round(v, 8) for v in rot]


def consumed_input_file_names(level: str, settings_file: str) -> set[str]:
    return {level, f"sharedassets{level.replace('level', '')}.assets", "globalgamemanagers.assets",
            Path(settings_file).name}


def extract(scene: str, level: str, settings_cache: dict, game_data_root: Path | None = None) -> dict:
    game_root = Path(game_data_root) if game_data_root is not None else GAME
    sharedassets = f"sharedassets{level.replace('level', '')}.assets"
    env = UnityPy.load(str(game_root / level), str(game_root / sharedassets),
                       str(game_root / "globalgamemanagers.assets"))
    for o in env.objects:
        if o.type.name != "MonoBehaviour" or o.assets_file.name != level:
            continue
        try:
            sc = o.read(check_read=False).m_Script.read()
        except Exception:
            continue
        if sc.m_ClassName != "BhCityCameraController":
            continue
        raw = o.get_raw_data()
        af = o.assets_file
        pp = lambda off: struct.unpack_from("<iq", raw, off)  # noqa: E731
        sfid, spid = pp(MB_HEADER)
        _, look_pid = pp(MB_HEADER + 12)
        _, cam_pid = pp(MB_HEADER + 24)
        sfile = af.externals[sfid - 1].path if sfid else level
        look = af.objects[look_pid].read()
        cam = af.objects[cam_pid].read()
        if scene == "cityHuman2" and cam.m_Father.path_id != look_pid:
            raise SystemExit("cityHuman2 MainCamera is not parented to the CityCamera rest-pose pivot")
        look_pos, look_rot = world_pose(look)
        cam_pos, cam_rot = world_pose(cam)
        cam_local_pos, cam_local_rot = local_pose(cam)
        camera_components = []
        for component in cam.m_GameObject.read().m_Component:
            component_ptr = component.component
            if component_ptr.type.name == "Camera":
                camera_components.append(component_ptr.read())
        if len(camera_components) != 1:
            raise SystemExit(f"{scene}: expected one Camera component on MainCamera, found {len(camera_components)}")
        field_of_view = float(camera_components[0].field_of_view)
        if not math.isfinite(field_of_view) or not 0.0 < field_of_view < 180.0:
            raise SystemExit(f"{scene}: invalid MainCamera field of view {field_of_view!r}")
        key = (sfile, spid)
        if key not in settings_cache:
            res = UnityPy.load(str(game_root / Path(sfile).name))
            rf = [f for f in res.files.values() if hasattr(f, "objects")][0]
            settings_cache[key] = parse_settings(rf.objects[spid].get_raw_data())
        return {"scene": scene, "level": level, "controllerPathId": int(o.path_id),
                "settingsRef": {"file": Path(sfile).name, "pathId": int(spid)},
                "lookAt": {"pathId": int(look_pid), "name": look.m_GameObject.read().m_Name, "worldPos": look_pos,
                           "worldRot": look_rot},
                "camera": {"pathId": int(cam_pid), "name": cam.m_GameObject.read().m_Name,
                           "parentPathId": int(cam.m_Father.path_id),
                           "localPosition": cam_local_pos, "localRotation": cam_local_rot,
                           "fieldOfView": field_of_view,
                           "worldPos": cam_pos, "worldRot": cam_rot},
                "settings": settings_cache[key]}
    raise SystemExit(f"{scene} ({level}): no BhCityCameraController")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--scenes", nargs="*", default=list(LEVELS))
    ap.add_argument("--game-data-root", type=Path, default=None,
                    help="read-only HeroesOldenEra_Data root (defaults to the active Golden Era install)")
    a = ap.parse_args()
    explicit_game_root = a.game_data_root is not None
    game_root = (a.game_data_root or GAME).resolve()
    if not game_root.is_dir():
        raise SystemExit(f"game-data root is not a directory: {game_root}")
    cache: dict = {}
    rows = [extract(s, LEVELS[s], cache, game_data_root=game_root) for s in a.scenes]
    if explicit_game_root:
        consumed_files = set().union(*(consumed_input_file_names(row["level"], row["settingsRef"]["file"])
                                       for row in rows))
        doc = {"schema": "homm3.vanilla_city_camera_pan.v2",
               "source": "selected read-only HeroesOldenEra_Data root (UnityPy raw MonoBehaviour bytes)",
               "gameDataRoot": game_root.as_posix(),
               "gameFiles": {name: sha256(game_root / name) for name in sorted(consumed_files)},
               "orientationDuringPan": "free sweep: Transform.LookAt(pivot) (GameAssembly disassembly); consumers also "
                                       "sample the fixed-rotation hypothesis as a margin",
               "cities": rows}
    else:
        for row in rows:
            row["camera"].pop("fieldOfView", None)
        doc = {"schema": "homm3.vanilla_city_camera_pan.v1",
               "source": "installed Golden Era HeroesOldenEra_Data (UnityPy raw MonoBehaviour bytes; read-only)",
               "gameFiles": {LEVELS[s]: sha256(game_root / LEVELS[s]) for s in a.scenes}
               | {"resources.assets": sha256(game_root / "resources.assets")},
               "orientationDuringPan": "free sweep: Transform.LookAt(pivot) (GameAssembly disassembly); consumers also "
                                       "sample the fixed-rotation hypothesis as a margin",
               "cities": rows}
    a.out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    for r in rows:
        s = r["settings"]
        print(r["scene"], s["name"], "nodes", len(s["positionNodes"]), "cam", r["camera"]["worldPos"],
              "pivot", r["lookAt"]["worldPos"], "dH", s["deltaHorizontalAngle"], "dV", s["deltaVerticalAngle"])
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
