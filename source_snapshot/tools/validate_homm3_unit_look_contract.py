"""Contract validator for the HoMM3 unit look pipeline (lighting + VFX), docs/homm3_unit_look_pipeline.md.

    python tools/validate_homm3_unit_look_contract.py [--repo-root R] [--unit U ...] [--require-delivered] [--deep]

Always, for every spec in tools/homm3_unit_look/units/: schema, the light double-counting rule,
layer references, clip/DEF-frame ranges (when the build's frames are present), defEffects classes and
module import. Warnings (non-fatal): file-based effect masks that are not in git.

For every ``look`` unit that has been applied (a stamp exists) and whose GLB is present locally:
the GLB is the stamped delivery (a rebuild that was not re-applied fails here: its base colour is the
un-prebaked one), the embedded base colour is the stamped prebake, the spec and knobs have not changed
since apply, the un-prebaked original sits under _superseded_do_not_use/, the VFX manifest and its
assets match, and every clip and anchor bone the spec names exists in the GLB.

A rawAccepted stamp (look.py --accept-raw) delivers the un-prebaked GLB: it must pass spec.raw_accepted_errors
(a reason, every mode tried, raw strictly better than each), and raw_basecolor.png must be the GLB's own image.
A unit with a spec but no stamp is "not applied yet" and passes (the rollout is partial) unless
--require-delivered. GLBs are not in git, so a missing GLB is skipped unless --require-delivered.
The GLB hash is recomputed only when its size/mtime differ from the stamp's, or with --deep.
Exit 0 = pass, 1 = violations.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--unit", nargs="*", default=None)
    ap.add_argument("--require-delivered", action="store_true")
    ap.add_argument("--deep", action="store_true", help="always rehash GLBs")
    a = ap.parse_args()
    root = a.repo_root.resolve()
    sys.path.insert(0, str(root / "tools/homm3_unit_look"))
    import spec as S  # noqa: E402
    from glbpatch import Glb, sha256_bytes, sha256_file  # noqa: E402

    spec_dir = root / "tools/homm3_unit_look/units"
    if not spec_dir.is_dir():
        print(f"FAIL: {spec_dir} missing")
        return 1
    files = sorted(spec_dir.glob("*.json"))
    if a.unit:
        files = [spec_dir / f"{u}.json" for u in a.unit]
    errors, warns, notes = [], [], []
    applied = pending = excluded = 0
    for f in files:
        u = f.stem
        if not f.is_file():
            errors.append(f"{u}: no spec {f}")
            continue
        try:
            spec = json.loads(f.read_text(encoding="utf-8"))
        except Exception as ex:  # noqa: BLE001
            errors.append(f"{u}: spec is not valid JSON: {ex}")
            continue
        try:
            clips = S.clip_segments(u)
        except (FileNotFoundError, KeyError):
            clips = None
        w: list[str] = []
        errs = S.validate(spec, u, clips, w, S.build_info(u) if clips is not None else None)
        errors += [f"{u}: {x}" for x in errs]
        warns += [f"{u}: {x}" for x in w]
        if errs:
            continue
        if spec["status"] == "excluded":
            excluded += 1
            continue
        outd = S.out_dir(u)
        stp = outd / "stamp.json"
        glb = S.glb_path(u)
        if not stp.is_file():
            pending += 1
            if a.require_delivered:
                errors.append(f"{u}: not applied (no stamp); run look.py {u}")
            continue
        applied += 1
        st = json.loads(stp.read_text())
        if st.get("schema") != S.STAMP_SCHEMA or st.get("unit") != u:
            errors.append(f"{u}: stamp schema/unit mismatch")
            continue
        raw_ok = st.get("kind") == S.RAW_ACCEPTED
        if st.get("kind") not in (None, S.RAW_ACCEPTED):
            errors.append(f"{u}: unknown stamp kind {st.get('kind')!r}")
            continue
        if raw_ok:
            errors += [f"{u}: {x}" for x in S.raw_accepted_errors(st)]
            rb = outd / S.RAW_BASECOLOR
            if not rb.is_file() or sha256_file(rb) != st["basecolorSha256"]:
                errors.append(f"{u}: {S.RAW_BASECOLOR} missing or not the stamped raw base colour")
            tc = st.get("rawTranscode")
            if isinstance(tc, dict) and rb.is_file():
                # a JPEG raw image shipped as PNG: the kept source must decode to exactly the shipped pixels
                src_img = outd / S.RAW_SOURCE_IMAGE
                if not src_img.is_file() or sha256_file(src_img) != tc.get("sourceImageSha256"):
                    errors.append(f"{u}: {S.RAW_SOURCE_IMAGE} missing or not the stamped source image")
                elif not (S.image_pixels_sha256(src_img.read_bytes()) == S.image_pixels_sha256(rb.read_bytes())
                          == tc.get("pixelsSha256")):
                    errors.append(f"{u}: {S.RAW_BASECOLOR} is not a pixel-identical transcode of {S.RAW_SOURCE_IMAGE}")
        if st["specSha256"] != S.canonical_sha(spec):
            errors.append(f"{u}: spec changed since the look was applied; rerun look.py {u}")
        if st["knobsSha256"] != S.knobs_sha(spec):
            errors.append(f"{u}: lighting knobs changed since the look was applied; rerun look.py {u}")
        if spec["lighting"].get("metal") and not raw_ok:
            # lighting.metal (metal.py) is delivered only when it beats the unmetalled grade on its own region
            mpath = outd / "metrics.json"
            mt = (json.loads(mpath.read_text()).get("lighting", {}).get("fit", {}).get("metal")
                  if mpath.is_file() else None)
            rl = (mt or {}).get("regionLhist") or {}
            if not mt or rl.get("before") is None or rl.get("after") is None:
                errors.append(f"{u}: lighting.metal is applied but metrics.json records no metal fit / region metric")
            elif rl["after"] >= rl["before"]:
                errors.append(f"{u}: lighting.metal does not improve its DEF metal region "
                              f"(L-hist {rl['before']} -> {rl['after']}); remove it or retune")
        if not glb.is_file():
            (errors if a.require_delivered else notes).append(f"{u}: stamped, but no GLB here ({glb})")
            continue
        stat = glb.stat()
        fast = (not a.deep and st.get("deliveredGlbStat") == {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns})
        if not fast:
            data = glb.read_bytes()
            if sha256_bytes(data) != st["deliveredGlbSha256"]:
                errors.append(f"{u}: GLB is not the stamped delivery (rebuilt or edited after apply; it ships the "
                              f"un-prebaked base colour); run: python tools/homm3_unit_look/look.py {u} --stages apply"
                              if not raw_ok else
                              f"{u}: GLB is not the rawAccepted delivery (rebuilt since); rerun look.py {u} --try-modes, "
                              f"--stages bake,fit,vfx,review, then --accept-raw")
                continue
            g = Glb(data)
            if sha256_bytes(g.image_bytes(g.body_base_color_image())) != st["basecolorSha256"]:
                errors.append(f"{u}: embedded base colour is not the stamped {'raw base colour' if raw_ok else 'prebake'}")
            names, joints = set(g.animation_names()), g.joint_names()
        else:
            names = set(st.get("glbAnimations", []))
            joints = set(st.get("glbJoints", []))
        sup = outd / (st["superseded"] or "")
        if raw_ok:
            pass   # a rawAccepted delivery is its own source; nothing is superseded
        elif not sup.is_file() or not sup.name.endswith(S.UNPREBAKED_EXT) or S.SUPERSEDED not in sup.parts:
            errors.append(f"{u}: un-prebaked original missing or misplaced ({sup})")
        elif not fast and sha256_file(sup) != st["sourceGlbSha256"]:
            errors.append(f"{u}: superseded original does not match the stamp")
        man = outd / "vfx/vfx_manifest.json"
        if not man.is_file() or sha256_file(man) != st["vfxManifestSha256"]:
            errors.append(f"{u}: vfx_manifest.json missing or changed since apply")
        else:
            mj = json.loads(man.read_text())
            for name, sha in mj.get("assets", {}).items():
                p = man.parent / name
                if not p.is_file() or sha256_file(p) != sha:
                    errors.append(f"{u}: VFX asset {name} missing or changed")
            want = {ly["id"] for ly in spec["vfx"]["layers"] if ly["type"] != "uvAtlas"}
            if want - set(mj.get("layers", {})):
                errors.append(f"{u}: manifest lacks layers {sorted(want - set(mj.get('layers', {})))}")
            # opt-in depth-aware renders (vfx_depth.py): every clip entry carries its block and its sheets are assets
            for ly in spec["vfx"]["layers"]:
                r = ly.get("render")
                if ly["type"] != "defFlipbook" or r not in ("unitPlane", "trail") or ly["id"] not in mj.get("layers", {}):
                    continue
                for cn, ent in mj["layers"][ly["id"]].get("clips", {}).items():
                    if ent.get("sheet") is None and ent.get("keys") and all(k.get("cell", -1) < 0 for k in ent["keys"]):
                        continue  # a light-only liveness entry
                    blk = ent.get(r)
                    if ent.get("render") != r or not isinstance(blk, dict):
                        errors.append(f"{u}: layer {ly['id']} {cn}: manifest entry lacks its {r} block")
                        continue
                    sheets = [blk.get("ramp")] if r == "trail" else \
                        [blk.get("sheet"), (blk.get("displaced") or {}).get("sheet")]
                    sheets = [x for x in sheets if x]
                    if not sheets or any(x not in mj.get("assets", {}) for x in sheets):
                        errors.append(f"{u}: layer {ly['id']} {cn}: {r} sheets {sheets} missing from the manifest assets")
            # opt-in volumetricFire (volfire.py): every system sheet and the emitter mask are manifest assets
            for ly in spec["vfx"]["layers"]:
                if ly["type"] != "volumetricFire" or ly["id"] not in mj.get("layers", {}):
                    continue
                ent = mj["layers"][ly["id"]]
                need = [sy.get("sheet") for sy in ent.get("systems", {}).values()] + \
                    ([ent["emitter"]["mask"]] if (ent.get("emitter") or {}).get("mask") else [])
                if set(ent.get("systems", {})) != set(ly.get("systems", {})) or any(x not in mj.get("assets", {}) for x in need):
                    errors.append(f"{u}: layer {ly['id']}: volumetricFire systems/sheets {need} do not match the spec or the assets")
        for ly in spec["vfx"]["layers"]:
            for cn in list(ly.get("clips", {}) if isinstance(ly.get("clips"), dict) else []) + \
                    list(ly.get("intensity", {})) + ([ly["clip"]] if ly.get("clip") else []):
                if names and cn not in names:
                    errors.append(f"{u}: layer {ly['id']} names clip {cn!r} that the GLB lacks")
            b = (ly.get("anchor") or {}).get("bone")
            if b and joints and b not in joints:
                errors.append(f"{u}: layer {ly['id']} anchor bone {b!r} is not a GLB joint")
            tb = (ly.get("trail") or {}).get("bone") if isinstance(ly.get("trail"), dict) else None
            if tb and joints and tb not in joints:
                errors.append(f"{u}: layer {ly['id']} trail bone {tb!r} is not a GLB joint")
    for x in notes:
        print("NOTE", x)
    for x in warns:
        print("WARN", x)
    for x in errors:
        print("FAIL", x)
    print(f"homm3 unit look contract: {len(files)} specs, {applied} applied, {pending} not applied yet, "
          f"{excluded} excluded, {len(warns)} warnings, {len(errors)} violations")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
