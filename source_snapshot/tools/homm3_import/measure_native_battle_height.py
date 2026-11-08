#!/usr/bin/env python3
"""Calibrate ``battleWorldHeightPerHex`` against stock Olden Era battle units.

Why
---
Owned-skinned HoMM3 units are battle-sized to ``battleHeightHexes * battleWorldHeightPerHex``
(``Homm3ImportVisuals.FitSkinnedBattleMesh``). ``battleHeightHexes`` is the HoMM3 idle-plate body
height over the 42 px HoMM3 hex (``write_battle_height_hexes.py``), so it fixes the *relative*
size between HoMM3 units. ``battleWorldHeightPerHex`` sets the absolute size and was 1.3, a value
read off one orc/blade-dancer log and never measured against a stock unit: ``h3_troglodyte``
(2.071 hexes) stood 2.69 world units tall. The adventure map multiplies the same product by
``adventureMapToBattleHeightRatio`` (``measure_native_map_battle_scale.py``), so this constant
sizes both lanes.

What this measures
------------------
For every stock ``units/<faction>/1prefabs/<unit>`` battle prefab that a Core.zip unit view uses,
the rendered silhouette height at the idle clip's t=0, in the prefab root's space, which is what
``FitSkinnedBattleMesh`` measures on the owned mesh (merged world bounds of every enabled renderer
after ``SampleOwnedSkinnedIdlePose``):

* the first child's ``localScale`` magnitude is replaced by ``UnitViewConfig.scale`` (the spawner
  rule recorded in ``tools/custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md``; the authored
  value is recorded beside it and the report counts mismatches);
* bones driven by the idle clip (``22.Idle`` override) take its t=0 sample, the rest keep the
  prefab pose (``tools/homm3_style_compare/extract_native.clip_sample0``);
* every enabled, active SkinnedMeshRenderer / MeshRenderer under the idle Animator's GameObject is
  skinned and merged (weapons count, as they do in the HoMM3 plate and in the owned fit; VFX
  duplicates parented outside the animated rig, such as the griffin's fresnel ghost, do not).

Stock units are then paired with the HoMM3 import rows that are the *same creature* (``PAIRS``;
no pairing by tier or by donor shell). Each pair gives ``stockWorldHeight / battleHeightHexes``;
the median over pairs is the calibrated ``battleWorldHeightPerHex`` (``--write``). The artifact
also records the spread, a log-log slope of stock height against HoMM3 hexes (1.0 means one global
constant preserves the stock size ordering; well below 1.0 means HoMM3 plates compress big
creatures), and each pair's before/after height.

Proof: static / generated artifact (installed assets read with UnityPy, never written). The pose is
a decoded clip sample, not a runtime capture; the battle parent is assumed identity-scaled (live
``skinned fit source=hex`` meshY equals the map ``currentY`` for crew_mate and gremlin_upg). Runtime
size is proven only by the ``source=hex`` log line plus in-game inspection.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import zlib
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "homm3_style_compare"))
from extract_native import clip_sample0, trs  # noqa: E402

DEFAULT_GAME_DATA = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data"
)
IMPORT_TABLE = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "homm3_import.json"
ARTIFACT = Path(__file__).resolve().parent / "native_battle_height.json"
TABLE_KEY = "battleWorldHeightPerHex"
SCHEMA = "native_battle_height.v1"

# Stock battle prefab (container path under units/) -> HoMM3 import SIDs of the same creature.
# Only true counterparts: same creature or the same faction slot drawn as the same body plan.
PAIRS: dict[str, tuple[str, ...]] = {
    "dungeon/1prefabs/troglodyte": ("h3_troglodyte",),
    "dungeon/1prefabs/troglodyte_upg": ("h3_troglodyte_upg",),
    "dungeon/1prefabs/medusa": ("h3_medusa",),
    "dungeon/1prefabs/medusa_upg": ("h3_medusa_upg",),
    "dungeon/1prefabs/minos": ("h3_minotaur",),
    "dungeon/1prefabs/minos_upg": ("h3_minotaur_upg",),
    "dungeon/1prefabs/hydra": ("h3_hydra",),
    "dungeon/1prefabs/hydra_upg": ("h3_hydra_upg",),
    "dungeon/1prefabs/black_dragon": ("h3_red_dragon",),
    "dungeon/1prefabs/black_dragon_upg": ("h3_red_dragon_upg",),
    "undead/1prefabs/skeleton": ("h3_skeleton",),
    "undead/1prefabs/skeleton_upg": ("h3_skeleton_upg",),
    "undead/1prefabs/vampire": ("h3_vampire",),
    "undead/1prefabs/vampire_upg": ("h3_vampire_upg",),
    "undead/1prefabs/lich": ("h3_lich",),
    "undead/1prefabs/lich_upg": ("h3_lich_upg",),
    "humans/1prefabs/griffin": ("h3_griffin",),
    "humans/1prefabs/griffin_upg": ("h3_griffin_upg",),
    "humans/1prefabs/angel": ("h3_angel",),
    "humans/1prefabs/angel_upg": ("h3_angel_upg",),
    "humans/1prefabs/crossbowman": ("h3_archer",),
    "humans/1prefabs/crossbowman_upg": ("h3_archer_upg",),
    "humans/1prefabs/esquire": ("h3_swordsman",),
    "humans/1prefabs/esquire_upg": ("h3_swordsman_upg",),
    "humans/1prefabs/inquisitor": ("h3_monk",),
    "humans/1prefabs/inquisitor_upg": ("h3_monk_upg",),
    "humans/1prefabs/sunlight_cavalry": ("h3_cavalier",),
    "humans/1prefabs/sunlight_cavalry_upg": ("h3_cavalier_upg",),
    "nature/1prefabs/elf_tracker": ("h3_wood_elf",),
    "nature/1prefabs/elf_tracker_upg": ("h3_grand_elf",),
    "nature/1prefabs/ent": ("h3_dendroid_guard",),
    "nature/1prefabs/ent_upg": ("h3_dendroid_soldier",),
    "nature/1prefabs/phoenix": ("h3_firebird",),
    "nature/1prefabs/phoenix_upg": ("h3_firebird_upg",),
    "neutral/1prefabs/unicorn": ("h3_unicorn",),
    "neutral/1prefabs/halfling": ("h3_halfling",),
    "neutral/1prefabs/pixie": ("h3_pixie",),
    "neutral/1prefabs/ghoul": ("h3_walking_dead",),
    "neutral/1prefabs/coatl": ("h3_couatl",),
    "demons/1prefabs/olgoi": ("h3_olgoi_khorkhoi",),
}
# Big / small reference groups for the proportion check (HoMM3 SIDs).
BIG = ("h3_red_dragon", "h3_red_dragon_upg", "h3_hydra", "h3_hydra_upg", "h3_firebird", "h3_firebird_upg",
       "h3_angel", "h3_angel_upg", "h3_dendroid_guard", "h3_dendroid_soldier", "h3_couatl")
SMALL = ("h3_troglodyte", "h3_troglodyte_upg", "h3_skeleton", "h3_skeleton_upg", "h3_halfling", "h3_pixie",
         "h3_archer", "h3_archer_upg", "h3_swordsman", "h3_swordsman_upg")
EXAMPLES = ("h3_troglodyte", "h3_skeleton", "h3_red_dragon", "h3_bone_dragon", "h3_black_dragon", "h3_giant",
            "h3_giant_upg", "h3_behemoth", "h3_oceanid", "h3_pixie")


def views_by_mesh(core_zip: Path) -> dict[str, list[dict[str, Any]]]:
    import zipfile

    out: dict[str, list[dict[str, Any]]] = {}
    with zipfile.ZipFile(core_zip) as z:
        for n in z.namelist():
            if not (n.startswith("DB/units/units_views/") and n.endswith(".json")) or "/homm3_" in n:
                continue
            try:
                arr = json.loads(z.read(n).decode("utf-8-sig")).get("array", [])
            except (ValueError, UnicodeDecodeError):
                continue
            for v in arr:
                if isinstance(v, dict) and "mesh" in v and v.get("scale") is not None:
                    out.setdefault(str(v["mesh"]).lower(), []).append({"id": v.get("id"), "scale": float(v["scale"])})
    return out


class Prefabs:
    def __init__(self, game_data: Path):
        import UnityPy

        env = UnityPy.load(str(game_data / "globalgamemanagers"), str(game_data / "resources.assets"))
        rm = next(o for o in env.objects if o.type.name == "ResourceManager").read_typetree()
        self.container = {k.lower(): p["m_PathID"] for k, p in rm["m_Container"]}
        self.ra = next(f for n, f in env.files.items() if n.endswith("resources.assets"))

    def comps(self, go_tt: dict) -> list[Any]:
        return [self.ra.objects[c["component"]["m_PathID"]] for c in go_tt["m_Component"]
                if c["component"]["m_FileID"] == 0 and c["component"]["m_PathID"] in self.ra.objects]

    def measure(self, key: str, view_scale: float) -> dict[str, Any]:
        from UnityPy.helpers.MeshHelper import MeshHandler

        ra = self.ra
        nodes: dict[int, dict[str, Any]] = {}

        def visit(tr_pid: int, parent: int | None, active: bool) -> None:
            tt = ra.objects[tr_pid].read_typetree()
            go = ra.objects[tt["m_GameObject"]["m_PathID"]].read_typetree()
            vec = lambda k: [tt[k][c] for c in ("x", "y", "z", "w") if c in tt[k]]  # noqa: E731
            act = active and bool(go.get("m_IsActive", 1))
            nodes[tr_pid] = {"name": go["m_Name"], "t": vec("m_LocalPosition"), "q": vec("m_LocalRotation"),
                             "s": vec("m_LocalScale"), "parent": parent, "active": act, "goTT": go,
                             "children": [c["m_PathID"] for c in tt["m_Children"]]}
            for c in tt["m_Children"]:
                visit(c["m_PathID"], tr_pid, act)

        root_tt = ra.objects[self.container["units/" + key]].read_typetree()
        root_tr = next(c for c in self.comps(root_tt) if c.type.name in ("Transform", "RectTransform"))
        visit(root_tr.path_id, None, True)
        first = nodes[root_tr.path_id]["children"][0]
        authored_first = [float(x) for x in nodes[first]["s"]]
        nodes[first]["s"] = [math.copysign(view_scale, x) for x in authored_first]

        def path_of(pid: int, stop: int) -> str:
            parts = []
            while pid is not None and pid != stop:
                parts.append(nodes[pid]["name"]); pid = nodes[pid]["parent"]
            return "/".join(reversed(parts))

        anim_pid, idle_clip, posed = None, None, 0
        for pid, n in nodes.items():
            for c in self.comps(n["goTT"]):
                if c.type.name != "Animator" or anim_pid is not None:
                    continue
                ctrl = ra.objects.get(c.read_typetree()["m_Controller"]["m_PathID"])
                if ctrl is None or ctrl.type.name != "AnimatorOverrideController":
                    continue
                for cl in ctrl.read_typetree()["m_Clips"]:
                    orig = ra.objects.get(cl["m_OriginalClip"]["m_PathID"])
                    ov = ra.objects.get(cl["m_OverrideClip"]["m_PathID"])
                    if orig is None or ov is None or orig.peek_name() != "22.Idle":
                        continue
                    curves = clip_sample0(ov.read_typetree())
                    anim_pid, idle_clip = pid, ov.peek_name()
                    byhash, stack = {}, [pid]
                    while stack:
                        p = stack.pop(); stack += nodes[p]["children"]
                        if p != pid:
                            byhash[str(zlib.crc32(path_of(p, pid).encode()))] = p
                    for h, attrs in curves.items():
                        if h not in byhash:
                            continue
                        nd = nodes[byhash[h]]
                        if 2 in attrs:
                            q = np.asarray(attrs[2]); q = q / max(float(np.linalg.norm(q)), 1e-9)
                            nd["q"] = [float(x) for x in q]
                        if 1 in attrs:
                            nd["t"] = attrs[1]
                        if 3 in attrs:
                            nd["s"] = attrs[3]
                        posed += 1
                    break
        if anim_pid is None:
            raise ValueError("no Animator with an AnimatorOverrideController mapping 22.Idle")

        world: dict[int, np.ndarray] = {}

        def wm(pid: int) -> np.ndarray:
            if pid not in world:
                n = nodes[pid]
                m = trs(n["t"], n["q"], n["s"])
                world[pid] = m if n["parent"] is None else wm(n["parent"]) @ m
            return world[pid]

        under_anim: set[int] = set()
        stack = [anim_pid]
        while stack:
            p = stack.pop(); under_anim.add(p); stack += nodes[p]["children"]

        points, renderers, excluded = [], [], []
        for pid, n in nodes.items():
            for c in self.comps(n["goTT"]):
                if c.type.name not in ("SkinnedMeshRenderer", "MeshRenderer"):
                    continue
                rtt = c.read_typetree()
                if not rtt.get("m_Enabled", 1) or not n["active"]:
                    continue
                if pid not in under_anim:
                    excluded.append(path_of(pid, root_tr.path_id))
                    continue
                if c.type.name == "SkinnedMeshRenderer":
                    mesh_pid = rtt["m_Mesh"]["m_PathID"]
                else:
                    mf = next((x for x in self.comps(n["goTT"]) if x.type.name == "MeshFilter"), None)
                    mesh_pid = mf.read_typetree()["m_Mesh"]["m_PathID"] if mf else 0
                if mesh_pid not in ra.objects:
                    continue
                mesh = ra.objects[mesh_pid].read()
                h = MeshHandler(mesh); h.process()
                v = np.asarray(h.m_Vertices, dtype=np.float64)[:, :3]
                vh = np.c_[v, np.ones(len(v))]
                if c.type.name == "SkinnedMeshRenderer" and rtt["m_Bones"] and h.m_BoneIndices:
                    bind = [np.array([[getattr(b, f"e{r}{cc}") for cc in range(4)] for r in range(4)])
                            for b in mesh.m_BindPose]
                    bones = [b["m_PathID"] for b in rtt["m_Bones"]]
                    skin = np.stack([wm(b) @ bind[i] if b in nodes else np.eye(4) for i, b in enumerate(bones)])
                    k = max(len(x) for x in h.m_BoneIndices[:64])
                    bi = np.zeros((len(v), 4), dtype=np.int64); bi[:, :k] = np.asarray(h.m_BoneIndices, dtype=np.int64)[:, :4]
                    bw = np.zeros((len(v), 4))
                    if h.m_BoneWeights:
                        w = np.asarray(h.m_BoneWeights, dtype=np.float64); bw[:, :w.shape[1]] = w[:, :4]
                    else:
                        bw[:, 0] = 1.0
                    bw = bw / np.maximum(bw.sum(1, keepdims=True), 1e-9)
                    vw = np.einsum("vij,vj->vi", np.einsum("vk,vkij->vij", bw, skin[bi]), vh)[:, :3]
                else:
                    vw = (wm(pid) @ vh.T).T[:, :3]
                points.append(vw)
                renderers.append({"renderer": n["name"], "mesh": mesh.m_Name, "vertices": int(len(v)),
                                  "height": round(float(np.ptp(vw[:, 1])), 4)})
        if not points:
            raise ValueError("no enabled renderer under the idle Animator")
        pos = np.concatenate(points)
        lo, hi = pos.min(0), pos.max(0)
        body = max(renderers, key=lambda r: r["vertices"])
        return {
            "idleClip": idle_clip,
            "posedCurves": posed,
            "authoredFirstChildScale": round(abs(authored_first[1]), 6),
            "worldHeight": round(float(hi[1] - lo[1]), 4),
            "bodyRendererHeight": body["height"],
            "footprintXZ": [round(float(hi[0] - lo[0]), 4), round(float(hi[2] - lo[2]), 4)],
            "minY": round(float(lo[1]), 4),
            "renderers": renderers,
            "excludedOutsideRig": excluded,
        }


def _pct(sorted_vals: list[float], q: float) -> float:
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def measure(game_data: Path, table: dict[str, Any]) -> dict[str, Any]:
    hexes_by_sid: dict[str, float] = {}
    for e in table["entries"]:
        sid = str(e.get("battleResPath") or "").rsplit("/", 1)[-1]
        # Calibrate on the DEF-measured hex height: a battleHeightScale size verdict (homm3_import.json) is applied
        # on top of the calibrated table, never folded into it.
        hx = e.get("battleHeightHexesMeasured", e.get("battleHeightHexes"))
        if hx is not None:
            hexes_by_sid[sid] = float(hx)
    views = views_by_mesh(game_data / "StreamingAssets" / "Core.zip")
    prefabs = Prefabs(game_data)

    stock: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, str]] = []
    for key in sorted(PAIRS):
        vlist = views.get(key)
        if not vlist or "units/" + key not in prefabs.container:
            skipped.append({"stock": key, "reason": "no Core.zip unit view or no ResourceManager prefab"})
            continue
        name = key.rsplit("/", 1)[-1]
        view = next((v for v in vlist if v["id"] and not str(v["id"]).startswith("h3_")), vlist[0])
        try:
            m = prefabs.measure(key, view["scale"])
        except (ValueError, KeyError, StopIteration) as ex:
            skipped.append({"stock": key, "reason": f"{type(ex).__name__}: {ex}"})
            continue
        stock[key] = {"viewId": view["id"], "viewScale": view["scale"], "prefab": name, **m}

    rows: list[dict[str, Any]] = []
    for key, sids in sorted(PAIRS.items()):
        if key not in stock:
            continue
        for sid in sids:
            if sid not in hexes_by_sid:
                skipped.append({"stock": key, "reason": f"{sid} has no battleHeightHexes in homm3_import.json"})
                continue
            s = stock[key]
            rows.append({"stock": key, "homm3Sid": sid, "battleHeightHexes": hexes_by_sid[sid],
                         "stockWorldHeight": s["worldHeight"], "stockBodyRendererHeight": s["bodyRendererHeight"],
                         "worldPerHex": round(s["worldHeight"] / hexes_by_sid[sid], 4)})
    if len(rows) < 20:
        raise RuntimeError(f"only {len(rows)} stock/HoMM3 pairs measured; refusing to calibrate")
    ratios = sorted(r["worldPerHex"] for r in rows)
    per_hex = round(statistics.median(ratios), 3)
    body_ratios = sorted(r["stockBodyRendererHeight"] / r["battleHeightHexes"] for r in rows)

    x = np.log([r["battleHeightHexes"] for r in rows]); y = np.log([r["stockWorldHeight"] for r in rows])
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (intercept + slope * x)
    for r in rows:
        r["calibratedHeight"] = round(r["battleHeightHexes"] * per_hex, 3)
        r["heightRatioCalibratedOverStock"] = round(r["calibratedHeight"] / r["stockWorldHeight"], 3)

    def group(sids: tuple[str, ...]) -> dict[str, Any]:
        g = [r for r in rows if r["homm3Sid"] in sids]
        return {"pairs": len(g),
                "medianWorldPerHex": round(statistics.median(r["worldPerHex"] for r in g), 4) if g else None,
                "medianCalibratedOverStock": round(statistics.median(r["heightRatioCalibratedOverStock"] for r in g), 3) if g else None}

    big, small = group(BIG), group(SMALL)
    old = float(table.get(TABLE_KEY) or 0)
    examples = {sid: {"hexes": hexes_by_sid[sid], "before": round(hexes_by_sid[sid] * old, 3),
                      "after": round(hexes_by_sid[sid] * per_hex, 3)}
                for sid in EXAMPLES if sid in hexes_by_sid}
    view_mismatch = [{"stock": k, "viewScale": s["viewScale"], "authoredFirstChildScale": s["authoredFirstChildScale"]}
                     for k, s in stock.items() if abs(s["viewScale"] - s["authoredFirstChildScale"]) > 1e-3 * s["viewScale"]]
    return {
        "schema": SCHEMA,
        "gameData": str(game_data).replace("\\", "/"),
        "rule": ("stock idle-t0 silhouette height (view scale on the first child, every enabled renderer under the "
                 "idle Animator) / HoMM3 battleHeightHexes of the same creature; median over pairs"),
        "measuredPairs": len(rows),
        "stockPrefabs": len(stock),
        "median": per_hex,
        "mean": round(statistics.mean(ratios), 4),
        "p10": round(_pct(ratios, 0.1), 4),
        "p90": round(_pct(ratios, 0.9), 4),
        "min": round(ratios[0], 4),
        "max": round(ratios[-1], 4),
        "bodyRendererOnlyMedian": round(statistics.median(body_ratios), 4),
        "previousTableValue": old,
        "logLogSlope": round(float(slope), 3),
        "logLogResidualStd": round(float(np.std(resid)), 3),
        "bigUnits": big,
        "smallUnits": small,
        "examples": examples,
        "viewScaleVsAuthoredMismatches": view_mismatch,
        "pairs": rows,
        "stock": stock,
        "skipped": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game-data", type=Path, default=DEFAULT_GAME_DATA)
    parser.add_argument("--write", action="store_true", help=f"write {TABLE_KEY} (the median) into homm3_import.json")
    args = parser.parse_args(argv)

    raw = IMPORT_TABLE.read_bytes()
    table = json.loads(raw.decode("utf-8-sig"))
    result = measure(args.game_data, table)
    ARTIFACT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{result['measuredPairs']} pairs: median {result['median']} world/hex (p10 {result['p10']}, p90 {result['p90']}, "
        f"min {result['min']}, max {result['max']}); log-log slope {result['logLogSlope']}; "
        f"big {result['bigUnits']['medianWorldPerHex']} small {result['smallUnits']['medianWorldPerHex']}; "
        f"previous {result['previousTableValue']}"
    )
    if args.write:
        table = json.loads(IMPORT_TABLE.read_bytes().decode("utf-8-sig"))
        table[TABLE_KEY] = result["median"]
        out = json.dumps(table, indent=2, ensure_ascii=False) + "\n"
        if b"\r\n" in raw:
            out = out.replace("\n", "\r\n")
        IMPORT_TABLE.write_bytes(out.encode("utf-8"))
        print(f"wrote {TABLE_KEY}={result['median']} into {IMPORT_TABLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
