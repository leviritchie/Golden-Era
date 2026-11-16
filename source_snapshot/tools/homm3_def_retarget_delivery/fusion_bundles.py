"""Elemental Fusion (Conflux) fused-unit lab prefabs + AssetBundles, built into a scratch output (never installed).

    python tools/homm3_def_retarget_delivery/fusion_bundles.py build [--ship DIR] [--pairs SID,..] [--chunk 15]
    python tools/homm3_def_retarget_delivery/fusion_bundles.py sizes [--ship DIR]
    python tools/homm3_def_retarget_delivery/fusion_bundles.py fragments [--ship DIR]   install fragments (not applied)

Input: tools/homm3_vfx/fusion_fx.py ``assets`` output (units/<sid>/fused.glb + fused_basecolor.png). Each fused unit
reuses its host's frozen delivery: the host's vfx_plan (clip lengths, stock map rules, merged death rubble) with the
merged-master fields moved to the fused GLB (the crest sits after the body vertices, before the rubble), the host's
clips (they are inside the fused GLB), neutral normal / metallic-gloss.

Per chunk: prepare (plans + lab batch) -> lab (Homm3OwnedSkinnedLabBuild through the Unity queue; lab report master
sha must equal the fused GLB) -> stock-controller identity gate -> bundles (BuildCustomUnitBundles with a scratch
inventory and a scratch output dir; the bundle payload contract is NOT touched) -> the chunk's lab assets are pruned
from the Unity project (the bundle and the copied lab report are the outputs).

Outputs under <ship>/: lab/<sid>/{vfx_plan.json, lab_report.json, neutral_*.png}, build_out/custom_units_conflux_
h3_fusion_*, fusion_inventory.json, fusion_bundles.json (sizes, shas, timings). Proof tier: generated bundles; not
installed, not run in game.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
import ship_def_retarget_slice as ship  # noqa: E402
import fusion_fx as FX  # noqa: E402

LAB_ROOT = ship.PROJECT / "Assets/CustomUnits/homm3_lab"


class FusionBundleError(Exception):
    pass


def fused_plan(sid: str, h: str, meta: dict, fused_glb: Path) -> dict:
    plan = json.loads(json.dumps(FX.unit(h)["plan"]))
    plan["unit"] = sid
    plan.pop("displacementMaskGlb", None)       # fused units carry no FLAG ripple (white COLOR_0, see fusion_fx)
    n1 = meta["crest"]["crestVerts"]
    mm = plan.get("mergedMaster")
    if mm:
        if meta["crest"]["crestInsertAt"] != mm["bodyVertices"]:
            raise FusionBundleError(f"{sid}: crest inserted at {meta['crest']['crestInsertAt']}, host body ends at "
                                    f"{mm['bodyVertices']}")
        plan["mergedMaster"] = {**mm, "glb": str(fused_glb), "sha256": ship.sha(fused_glb),
                                "sourceGlbSha256": FX.unit(h)["report"]["masterGlbSha256"],
                                "bodyVertices": mm["bodyVertices"] + n1, "totalVertices": mm["totalVertices"] + n1}
        plan["mergedMeshes"] = [{**m, "firstVertex": m["firstVertex"] + n1} for m in plan["mergedMeshes"]]
    plan["elementalFusion"] = {"host": h, "guest": meta["guest"], "crestVerts": n1,
                               "note": "fusion_bundles.py: the host's frozen plan on the fused mesh"}
    return plan


def prepare(ship_dir: Path, sids: list[str]) -> Path:
    units = []
    for sid in sids:
        h, g = FX.pair_by_sid()[sid]
        ud = ship_dir / "units" / sid
        meta = FX.VSF.load(ud / "build_meta.json")
        glb = ud / "fused.glb"
        if ship.sha(glb) != meta["files"]["fused.glb"]:
            raise FusionBundleError(f"{sid}: fused.glb changed since its build_meta (rerun fusion_fx.py assets)")
        if meta["hostMasterSha256"] != FX.unit(h)["report"]["masterGlbSha256"]:
            raise FusionBundleError(f"{sid}: host {h} delivery changed since the fused build")
        ld = ship_dir / "lab" / sid
        ld.mkdir(parents=True, exist_ok=True)
        plan = fused_plan(sid, h, meta, glb)
        ship.dump(ld / "vfx_plan.json", plan)
        normal, metallic = ld / "neutral_normal.png", ld / "neutral_metallicgloss.png"
        ship.write_png(normal, ship.NEUTRAL_NORMAL)
        ship.write_png(metallic, ship.NEUTRAL_METALLIC_GLOSS)
        clips = []
        for clip in sorted(plan["clipLengths"]):
            if clip not in ship.ROLES:
                raise FusionBundleError(f"{sid}: clip {clip} has no lifecycle role")
            clips.append({"contractName": clip, "sourcePath": "", "sourceAnimation": clip,
                          "lifecycleRole": ship.ROLES[clip], "fps": ship.FPS})
        units.append({"labSid": sid, "clipPrefix": "Unit", "masterGlb": str(glb.resolve()),
                      "albedo": str((ud / "fused_basecolor.png").resolve()), "normal": str(normal.resolve()),
                      "metallicGloss": str(metallic.resolve()), "motionAuthority": "def_retarget",
                      "vfxPlan": str((ld / "vfx_plan.json").resolve()), "placeholderIdleOnly": False, "clips": clips})
    batch = ship_dir / "lab" / "unity_lab_batch.json"
    ship.dump(batch, {"units": units})
    return batch


def inventory_rows(sids: list[str]) -> list[dict]:
    rows = []
    for sid in sids:
        prefab = f"Assets/CustomUnits/homm3_lab/{sid}/OwnedSkinned/owned_skinned.prefab"
        rows.append({"unitSid": sid, "battlePrefabAsset": prefab, "mapPrefabAsset": prefab,
                     "bundleName": FX.bundle_name(sid), "battlePresentationLane": "skinned_mesh"})
    return rows


def prune_lab(sid: str) -> None:
    d = LAB_ROOT / sid
    if not sid.startswith(FX.ELEM["delivery"]["sidPrefix"]):
        raise FusionBundleError(f"refusing to prune {d}")
    if d.exists():
        shutil.rmtree(d)
    m = d.with_name(d.name + ".meta")
    if m.exists():
        m.unlink()


def build_chunk(ship_dir: Path, sids: list[str], tag: str) -> dict:
    logs = ship_dir / "logs"
    t0 = time.time()
    batch = prepare(ship_dir, sids)
    for src in ship.EDITOR_SCRIPTS:
        dst = ship.PROJECT / "Assets/Editor" / src.name
        if not dst.exists() or ship.sha(dst) != ship.sha(src):
            shutil.copy2(src, dst)
    lab = ship.unity("Homm3OwnedSkinnedLabBuild.BuildFromCommandLine", ["-skinnedLabSpec", batch], logs / f"lab_{tag}.log")
    reports = {}
    for sid in sids:
        rp = LAB_ROOT / sid / "OwnedSkinned/owned_skinned_def_retarget_report.json"
        if not rp.is_file():
            raise FusionBundleError(f"{sid}: lab builder wrote no def_retarget report")
        rep = ship.load(rp)
        if rep.get("masterGlbSha256") != ship.sha(ship_dir / "units" / sid / "fused.glb"):
            raise FusionBundleError(f"{sid}: lab report master is not the fused GLB")
        shutil.copy2(rp, ship_dir / "lab" / sid / "lab_report.json")
        reports[sid] = {"stockMap": rep.get("stockMap"), "sha256": ship.sha(rp)}
    inv = ship_dir / f"fusion_inventory_{tag}.json"
    ship.dump(inv, {"formatVersion": 1, "comment": "scratch inventory: Elemental Fusion fused units (fusion_bundles.py)",
                    "units": inventory_rows(sids)})
    # the identity gate's GUID registry must stay the full shipped manifest + this chunk's fused rows
    gate_manifest = ship_dir / f"fusion_gate_manifest_{tag}.json"
    ship.dump(gate_manifest, {"units": ship.load(ship.INVENTORY)["units"] + inventory_rows(sids)})
    ship.run([sys.executable, ROOT / "tools/validate_homm3_stock_controller_identity.py", "--project", ship.PROJECT,
              "--manifest", gate_manifest, *[v for s in sids for v in ("--unit", s)]],
             logs / f"stock_controller_identity_{tag}.log", 300)
    ul = ship_dir / f"fusion_unit_sids_{tag}.txt"
    ul.write_text("\n".join(sids) + "\n", encoding="utf-8")
    out = ship_dir / "build_out"
    out.mkdir(parents=True, exist_ok=True)
    bun = ship.unity("OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest",
                     ["-manifestPath", inv, "-homm3UnitListPath", ul, "-outputPath", out], logs / f"bundles_{tag}.log",
                     output_dir=out)
    built = {}
    for sid in sids:
        b = out / FX.bundle_name(sid)
        if not b.is_file() or b.stat().st_size <= 0:
            raise FusionBundleError(f"{sid}: no bundle {b.name}")
        built[sid] = {"bundle": b.name, "bytes": b.stat().st_size, "sha256": ship.sha(b).upper(),
                      "labReport": reports[sid]}
    for sid in sids:
        prune_lab(sid)
    for p in (inv, ul, gate_manifest):
        p.unlink()
    return {"sids": sids, "lab": lab, "bundles": bun, "built": built, "seconds": round(time.time() - t0, 1)}


def cmd_build(ship_dir: Path, sids: list[str], chunk: int) -> None:
    rec_p = ship_dir / "fusion_bundles.json"
    rec = ship.load(rec_p) if rec_p.exists() else {"schema": "homm3_elemental_fusion_bundles.v1", "units": {}, "chunks": []}
    todo = [s for s in sids if s not in rec["units"]
            or rec["units"][s]["fusedGlbSha256"] != ship.sha(ship_dir / "units" / s / "fused.glb")
            or not (ship_dir / "build_out" / FX.bundle_name(s)).is_file()]
    print(f"bundles: {len(todo)} of {len(sids)} to build, chunks of {chunk}", flush=True)
    for i in range(0, len(todo), chunk):
        part = todo[i:i + chunk]
        tag = f"c{i // chunk:02d}_{time.strftime('%H%M%S')}"
        r = build_chunk(ship_dir, part, tag)
        for sid, b in r["built"].items():
            rec["units"][sid] = {**b, "fusedGlbSha256": ship.sha(ship_dir / "units" / sid / "fused.glb"),
                                 "host": FX.pair_by_sid()[sid][0], "guest": FX.pair_by_sid()[sid][1]}
        rec["chunks"].append({k: r[k] for k in ("sids", "lab", "bundles", "seconds")})
        rec["proof"] = "generated bundles (scratch build_out); not installed, not run in game"
        ship.dump(rec_p, rec)
        print(f"bundles: chunk {tag} {len(part)} units {r['seconds']}s "
              f"{sum(b['bytes'] for b in r['built'].values()) / 2**20:.1f} MiB", flush=True)


def cmd_sizes(ship_dir: Path) -> None:
    rec = ship.load(ship_dir / "fusion_bundles.json")
    sizes = sorted(((u["bytes"], s) for s, u in rec["units"].items()))
    tot = sum(b for b, _ in sizes)
    print(f"{len(sizes)} bundles, total {tot / 2**20:.1f} MiB ({tot / 1e9:.2f} GB); mean {tot / max(len(sizes), 1) / 2**20:.1f} MiB; "
          f"min {sizes[0][0] / 2**20:.1f} ({sizes[0][1]}); max {sizes[-1][0] / 2**20:.1f} ({sizes[-1][1]})")
    by_host = {}
    for b, s in sizes:
        by_host.setdefault(rec["units"][s]["host"], []).append(b)
    for h, bs in sorted(by_host.items()):
        print(f"  host {FX.short(h):10s} {len(bs):3d} units  mean {sum(bs) / len(bs) / 2**20:6.1f} MiB")


def cmd_fragments(ship_dir: Path) -> None:
    """Install fragments under <ship>/install/ for the owning lanes to merge (nothing here touches a tracked file):
    homm3_import entries (plugin lane), units-manifest rows, payload-contract rows, the fusion_units.json ``mesh``
    values (release lane) and the bundle copy list."""
    rec = ship.load(ship_dir / "fusion_bundles.json")
    imp = ship.load(ship.IMPORT)
    by_bundle = {e.get("bundleName"): e for e in imp["entries"]}
    out = ship_dir / "install"
    out.mkdir(parents=True, exist_ok=True)
    entries, manifest, contract, mesh, copy = [], [], {}, {}, []
    missing = [s for s in FX.pair_by_sid() if s not in rec["units"]]
    if missing:
        raise FusionBundleError(f"{len(missing)} fused units have no built bundle (first {missing[:3]})")
    for sid, (h, g) in sorted(FX.pair_by_sid().items()):
        u = rec["units"][sid]
        b = ship_dir / "build_out" / u["bundle"]
        if ship.sha(b).upper() != u["sha256"] or b.stat().st_size != u["bytes"]:
            raise FusionBundleError(f"{sid}: {b.name} differs from fusion_bundles.json")
        host = by_bundle.get(FX.bundle_name(h))
        if host is None:
            raise FusionBundleError(f"{sid}: host bundle {FX.bundle_name(h)} has no homm3_import entry")
        res = "units/homm3_import/conflux/" + sid
        row = inventory_rows([sid])[0]
        e = {"battleResPath": res, "mapResPath": res + "_map"}
        for k in ("battlePresentationResPath", "mapShellResPath", "swapAdventureMap"):
            if k in host:
                e[k] = host[k]
        e.update({"bundleName": u["bundle"], "battlePrefabAssetPath": row["battlePrefabAsset"],
                  "mapPrefabAssetPath": row["mapPrefabAsset"], "audioBundleName": host["bundleName"],
                  "gameUnitSids": [sid],
                  "xHomm3ElementalFusion": f"fusion_bundles.py: host {h} + guest {g}; sounds from the host bundle "
                                           "(audioBundleName needs lane2_audio_bundle_name.patch)"})
        if "battleHeightHexes" in host:
            e["battleHeightHexes"] = host["battleHeightHexes"]
        entries.append(e)
        manifest.append(row)
        contract[u["bundle"]] = {"length": u["bytes"], "sha256": u["sha256"]}
        mesh[sid] = {"mesh": res, "mapMesh": res + "_map"}
        copy.append({"from": str(b), "to": f"<plugin>/{imp['bundleSubdir']}/{u['bundle']}", "bytes": u["bytes"]})
    ship.dump(out / "homm3_import_entries.json", {"target": str(ship.IMPORT.relative_to(ROOT)), "append": entries})
    ship.dump(out / "homm3_units_manifest_rows.json", {"target": str(ship.INVENTORY.relative_to(ROOT)), "append": manifest})
    ship.dump(out / "bundle_contract_rows.json", {"target": str(ship.CONTRACT.relative_to(ROOT)), "bundles": contract})
    ship.dump(out / "fusion_units_mesh.json", {"target": "custom_factions/conflux_fusion/fusion_units.json",
                                               "field": "units.<sid>.mesh", "values": mesh})
    ship.dump(out / "bundle_copy.json", {"totalBytes": sum(c["bytes"] for c in copy), "files": copy})
    print(f"fragments: {len(entries)} units -> {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("build", "sizes", "fragments"))
    ap.add_argument("--ship", type=Path, default=FX.DEFAULT_OUT)
    ap.add_argument("--pairs", default="")
    ap.add_argument("--chunk", type=int, default=15)
    a = ap.parse_args()
    allsids = list(FX.pair_by_sid())
    sids = [s for s in a.pairs.split(",") if s] or allsids
    bad = sorted(set(sids) - set(allsids))
    if bad:
        raise FusionBundleError(f"unknown sids {bad}")
    if a.cmd == "build":
        cmd_build(a.ship, sids, a.chunk)
    elif a.cmd == "sizes":
        cmd_sizes(a.ship)
    else:
        cmd_fragments(a.ship)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FusionBundleError, FX.FusionError, ship.ShipError) as ex:
        print(f"fusion_bundles: {ex}", file=sys.stderr)
        sys.exit(1)
