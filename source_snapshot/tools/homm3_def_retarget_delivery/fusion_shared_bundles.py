"""Elemental Fusion shared-mesh bundles: each fused unit ships only its crest + its own textures; the body mesh,
skeleton, blend shapes, clips and Animator controller load from the host's already-shipped bundle (plugin patch
lane2_fusion_shared_mesh.patch: Entry.meshBundleName / meshPrefabAssetPath / meshAttachBone / meshVertexColorWhite).

    python tools/homm3_def_retarget_delivery/fusion_shared_bundles.py split      [--pairs SID,..]
    python tools/homm3_def_retarget_delivery/fusion_shared_bundles.py build      [--pairs SID,..]
    python tools/homm3_def_retarget_delivery/fusion_shared_bundles.py fragments

split: the fused 2:1 atlases (left half = host UV space, right half = crest UV space; fusion_fx.py) are cut into the
body texture (host UVs, 1024^2) and the crest texture (512^2), for the albedo, the Hex/Lit emission map and the VfxUber
overlay mask; mesh-fx rows are rewritten (emission.crestTexture, overlay source.crestTextures).
build: Homm3FusionCrestBundles (Unity, lab project) cuts the crest out of the previously built full fused bundle and
writes custom_units_conflux_h3_fusion_* crest bundles into <shared>/build_out.
fragments: install fragments for the owning lanes (nothing tracked is touched).

The host bundle mesh must equal the fused body (checked: positions and UVs identical for all 14 hosts). Proof tier:
generated bundles + Unity editor lab; not installed, not run in game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
import ship_def_retarget_slice as ship  # noqa: E402
import fusion_fx as FX  # noqa: E402

FULL = FX.DEFAULT_OUT                                   # fusion_fx assets + the full fused bundles (crest source)
OUT = FULL.parent / "shared"
LAB_PROJECT = ROOT / "oldenera_factions"
CS_SRC = HERE / "unity/Homm3FusionCrestBundles.cs"
CS_DEST = LAB_PROJECT / "Assets/Editor/Homm3VfxLab/Homm3FusionCrestBundles.cs"
BODY, CREST = 1024, 512                                 # albedo / emission sizes; masks are half
ATTACH = "Head"


class SharedError(Exception):
    pass


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def halves(p: Path, body: int, crest: int, mode: str) -> tuple[Image.Image, Image.Image]:
    im = Image.open(p).convert(mode)
    w, h = im.size
    if w != 2 * h:
        raise SharedError(f"{p.name}: {w}x{h} is not a 2:1 atlas")
    left, right = im.crop((0, 0, h, h)), im.crop((h, 0, w, h))
    rs = lambda x, s: x if x.size == (s, s) else x.resize((s, s), Image.LANCZOS)  # noqa: E731
    return rs(left, body), rs(right, crest)


def tex_dir(sid: str) -> Path:
    return OUT / "textures" / sid


def cmd_split(sids: list[str]) -> None:
    rows = json.loads((FULL / "homm3_mesh_fx/fusion_rows.json").read_text(encoding="utf-8"))
    mfx = OUT / "homm3_mesh_fx"
    out_rows = []
    for sid in sids:
        d = tex_dir(sid)
        d.mkdir(parents=True, exist_ok=True)
        b, c = halves(FULL / "units" / sid / "fused_basecolor.png", BODY, CREST, "RGB")
        b.save(d / "owned_skinned_basecolor.png", optimize=True)
        c.save(d / "fusion_crest_basecolor.png", optimize=True)
        b, c = halves(FULL / "homm3_mesh_fx" / FX.emission_name(sid), BODY, CREST, "RGB")
        (mfx / "emission").mkdir(parents=True, exist_ok=True)
        b.save(mfx / f"emission/{sid}__body_emission.png", optimize=True)
        c.save(mfx / f"emission/{sid}__crest_emission.png", optimize=True)
        b, c = halves(FULL / "homm3_mesh_fx" / FX.mask_name(sid), BODY // 2, CREST // 2, "L")
        (mfx / "fusion").mkdir(parents=True, exist_ok=True)
        b.save(mfx / f"fusion/{sid}__body_mask.png", optimize=True)
        c.save(mfx / f"fusion/{sid}__crest_mask.png", optimize=True)
    want = set(sids)
    for r in rows["entries"]:
        sid = r["origin"].split(":", 1)[1]
        if sid not in want:
            continue
        r = json.loads(json.dumps(r))
        if r["lane"] == "battle_emission":
            e = r["emission"]
            e["texture"] = f"emission/{sid}__body_emission.png"
            e["textureSha256"] = sha(mfx / e["texture"])
            e["crestTexture"] = f"emission/{sid}__crest_emission.png"
            e["crestTextureSha256"] = sha(mfx / e["crestTexture"])
        elif r["lane"] == "battle_body_overlay" and r["source"].get("textures"):
            src = r["source"]
            if [t["property"] for t in src["textures"]] != ["_Mask"]:
                raise SharedError(f"{r['id']}: unexpected overlay textures {src['textures']}")
            body, crest = f"fusion/{sid}__body_mask.png", f"fusion/{sid}__crest_mask.png"
            src["textures"] = [{"property": "_Mask", "file": body, "sha256": sha(mfx / body)}]
            src["crestTextures"] = [{"property": "_Mask", "file": crest, "sha256": sha(mfx / crest)}]
        out_rows.append(r)
    p = mfx / "fusion_rows.json"
    prev = json.loads(p.read_text(encoding="utf-8"))["entries"] if p.exists() else []
    keep = [r for r in prev if r["origin"].split(":", 1)[1] not in want]
    allrows = sorted(keep + out_rows, key=lambda r: (r["origin"], r["id"]))
    p.write_text(json.dumps({"schema": rows["schema"], "count": len(allrows), "entries": allrows}, indent=1), encoding="utf-8")
    print(f"split: {len(sids)} units, {len(allrows)} rows -> {mfx}")


def host_vertex_colors() -> dict[str, bool]:
    """Hosts whose mesh carries a COLOR_0 stream (the FLAG displacement mask in r): the VfxUber fusion overlay
    multiplies vertex colour, so those fused units need the plugin's white-colour mesh copy (meshVertexColorWhite)."""
    p = OUT / "host_vertex_colors.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    import UnityPy
    out = {}
    for h in sorted({h for h, _ in FX.pair_by_sid().values()}):
        env = UnityPy.load(str(ship.GOLDEN / "BepInEx/plugins/OfflineUnlockMod/homm3_bundles" / FX.bundle_name(h)))
        from UnityPy.helpers.MeshHelper import MeshHandler
        has = False
        for o in env.objects:
            if o.type.name == "Mesh":
                mh = MeshHandler(o.read())
                mh.process()
                has = has or bool(mh.m_Colors)
        out[h] = has
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def cmd_build(sids: list[str], chunk: int) -> None:
    import vanilla_style_lab as VL
    bo = OUT / "build_out"
    bo.mkdir(parents=True, exist_ok=True)
    rec_p = OUT / "fusion_shared_bundles.json"
    rec = json.loads(rec_p.read_text(encoding="utf-8")) if rec_p.exists() else {"units": {}}
    CS_DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CS_SRC, CS_DEST)
    for ci in range(0, len(sids), chunk):
        part = sids[ci:ci + chunk]
        units = []
        for sid in part:
            meta = json.loads((FULL / "units" / sid / "build_meta.json").read_text(encoding="utf-8"))["crest"]
            src = FULL / "build_out" / FX.bundle_name(sid)
            if not src.is_file():
                raise SharedError(f"{sid}: no full fused bundle to cut the crest from ({src})")
            units.append({"sid": sid, "bundleName": FX.bundle_name(sid), "sourceBundle": str(src),
                          "bodyPng": str(tex_dir(sid) / "owned_skinned_basecolor.png"),
                          "crestPng": str(tex_dir(sid) / "fusion_crest_basecolor.png"), "attachBone": ATTACH,
                          "crestInsertAt": meta["crestInsertAt"], "crestVerts": meta["crestVerts"],
                          "crestTris": meta["crestTris"], "bodyMaxSize": BODY, "crestMaxSize": CREST})
        tag = f"c{ci // chunk:02d}"
        spec = OUT / "logs" / f"crest_spec_{tag}.json"
        spec.parent.mkdir(parents=True, exist_ok=True)
        report = OUT / "logs" / f"crest_report_{tag}.json"
        spec.write_text(json.dumps({"units": units, "outDir": str(bo), "report": str(report)}, indent=1), encoding="utf-8")
        gate = subprocess.run([sys.executable, str(ROOT / "tools/homm3_def_retarget/launch_guard.py")], capture_output=True,
                              text=True, timeout=900)
        if gate.returncode:
            raise SharedError(f"launch_guard refused: {gate.stdout[-300:]} {gate.stderr[-300:]}")
        log = OUT / "logs" / f"crest_unity_{tag}.log"
        cmd = [str(VL.UNITY), "-batchmode", "-quit", "-projectPath", str(LAB_PROJECT), "-fusionCrestSpec", str(spec),
               "-executeMethod", "OldenEra.Homm3Vfx.Homm3FusionCrestBundles.BuildFromCommandLine", "-logFile", str(log)]
        t0 = time.time()
        done = VL.UQ.run_cmd(cmd, kind="vfx_fusion_crest_bundles", timeout_s=3600, direct=VL.UNITY_DIRECT)
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        if done.returncode != 0 or "HOMM3_FUSION_CREST_OK" not in text:
            errs = [ln[:300] for ln in text.splitlines() if "error CS" in ln or "Exception" in ln][:12]
            raise SharedError(f"crest bundle job {tag} failed (exit {done.returncode}): {errs}; see {log}")
        geo = json.loads(report.read_text(encoding="utf-8"))
        for sid in part:
            b = bo / FX.bundle_name(sid)
            rec["units"][sid] = {"bundle": b.name, "bytes": b.stat().st_size, "sha256": sha(b).upper(), "crest": geo[sid]}
        print(f"build {tag}: {len(part)} bundles, {time.time() - t0:.0f}s, "
              f"{sum(rec['units'][s]['bytes'] for s in part) / 2**20:.1f} MiB")
        rec_p.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    rec["totalBytes"] = sum(u["bytes"] for u in rec["units"].values())
    rec_p.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    CS_DEST.unlink(missing_ok=True)
    CS_DEST.with_suffix(".cs.meta").unlink(missing_ok=True)
    for p in bo.glob("*.manifest"):
        p.unlink()
    (bo / "build_out").unlink(missing_ok=True)
    print(f"shared bundles: {len(rec['units'])} units, {rec['totalBytes'] / 2**20:.1f} MiB")


def cmd_fragments() -> None:
    rec = json.loads((OUT / "fusion_shared_bundles.json").read_text(encoding="utf-8"))
    imp = ship.load(ship.IMPORT)
    by_bundle = {e.get("bundleName"): e for e in imp["entries"]}
    colors = host_vertex_colors()
    out = OUT / "install"
    out.mkdir(parents=True, exist_ok=True)
    entries, manifest, contract, mesh, copy = [], [], {}, {}, []
    for sid, (h, g) in sorted(FX.pair_by_sid().items()):
        u = rec["units"].get(sid)
        if u is None:
            raise SharedError(f"{sid}: no shared bundle")
        b = OUT / "build_out" / u["bundle"]
        if sha(b).upper() != u["sha256"]:
            raise SharedError(f"{sid}: {b.name} differs from fusion_shared_bundles.json")
        host = by_bundle.get(FX.bundle_name(h))
        if host is None:
            raise SharedError(f"{sid}: host bundle {FX.bundle_name(h)} has no homm3_import entry")
        res = "units/homm3_import/conflux/" + sid
        crest = f"Assets/CustomUnits/homm3_lab/{sid}/OwnedSkinned/fusion_crest.prefab"
        e = {"battleResPath": res, "mapResPath": res + "_map"}
        for k in ("battlePresentationResPath", "mapShellResPath", "swapAdventureMap"):
            if k in host:
                e[k] = host[k]
        e.update({"bundleName": u["bundle"], "battlePrefabAssetPath": crest, "mapPrefabAssetPath": crest,
                  "meshBundleName": host["bundleName"], "meshPrefabAssetPath": host["battlePrefabAssetPath"],
                  "meshMapPrefabAssetPath": host["mapPrefabAssetPath"], "meshAttachBone": ATTACH,
                  "audioBundleName": host["bundleName"], "gameUnitSids": [sid]})
        if colors.get(h):
            e["meshVertexColorWhite"] = True
        e["xHomm3ElementalFusion"] = (f"fusion_shared_bundles.py: host {h} + guest {g}; body mesh, clips, controller and "
                                      "sounds from the host bundle (needs lane2_audio_bundle_name.patch + "
                                      "lane2_fusion_shared_mesh.patch)")
        if "battleHeightHexes" in host:
            e["battleHeightHexes"] = host["battleHeightHexes"]
        entries.append(e)
        manifest.append({"unitSid": sid, "battlePrefabAsset": crest, "mapPrefabAsset": crest, "bundleName": u["bundle"],
                         "battlePresentationLane": "skinned_mesh", "sharedMeshHostBundle": host["bundleName"]})
        contract[u["bundle"]] = {"length": u["bytes"], "sha256": u["sha256"]}
        mesh[sid] = {"mesh": res, "mapMesh": res + "_map"}
        copy.append({"from": str(b), "to": f"<plugin>/{imp['bundleSubdir']}/{u['bundle']}", "bytes": u["bytes"]})
    mfx = OUT / "homm3_mesh_fx"
    pngs = sorted(p for p in mfx.rglob("*.png"))
    for p in pngs:
        copy.append({"from": str(p), "to": "<plugin>/homm3_mesh_fx/" + p.relative_to(mfx).as_posix(), "bytes": p.stat().st_size})
    ship.dump(out / "homm3_import_entries.json", {"target": str(ship.IMPORT.relative_to(ROOT)), "append": entries})
    ship.dump(out / "homm3_units_manifest_rows.json", {"target": str(ship.INVENTORY.relative_to(ROOT)), "append": manifest})
    ship.dump(out / "bundle_contract_rows.json", {"target": str(ship.CONTRACT.relative_to(ROOT)), "bundles": contract})
    ship.dump(out / "fusion_units_mesh.json", {"target": "custom_factions/conflux_fusion/fusion_units.json",
                                               "field": "units.<sid>.mesh", "values": mesh})
    ship.dump(out / "bundle_copy.json", {"totalBytes": sum(c["bytes"] for c in copy),
                                         "bundleBytes": sum(u["bytes"] for u in rec["units"].values()),
                                         "meshFxPngBytes": sum(p.stat().st_size for p in pngs), "files": copy})
    shutil.copy2(mfx / "fusion_rows.json", out / "homm3_mesh_fx_fusion_rows.json")
    print(f"fragments: {len(entries)} units -> {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("split", "build", "fragments"))
    ap.add_argument("--pairs", default="")
    ap.add_argument("--chunk", type=int, default=35)
    a = ap.parse_args()
    sids = [s for s in a.pairs.split(",") if s] or sorted(FX.pair_by_sid())
    try:
        if a.cmd == "split":
            cmd_split(sids)
        elif a.cmd == "build":
            cmd_build(sids, a.chunk)
        else:
            cmd_fragments()
    except SharedError as ex:
        print("ERROR:", ex)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
