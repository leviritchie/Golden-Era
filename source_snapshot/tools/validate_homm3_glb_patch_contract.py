"""Validate the Blender-free GLB patch lane (docs/homm3_glb_patch_lane.md).

    python tools/validate_homm3_glb_patch_contract.py [--repo-root R] [--unit U ...]

Always:
- every unit config's "glbPatch" passes patch_glb.spec_errors (known ops and keys, a reason, valid ramps / axes);
- the chain position: the patch stamp is the first entry of the emphasis contract's DELIVERY_STAGES, fleet_rebuild.py
  runs the glb patch after the export and before deyaw, retains the patch base in the full routes, and its
  --from-base route runs no Blender step and re-delivers the look with the apply stage alone (never --force);
- in-memory stage fusion (docs/homm3_glb_patch_lane.md): fleet_rebuild.py runs the delivery stages in process on the
  GLB's bytes (fused_delivery_stages: no subprocess, sidecars then the GLB written once, never on --from-base), the
  --from-base route hands look apply the bytes (look.run_unit(glb_bytes=...)), and only that route's transaction
  snapshot hard-links the delivered GLB;
- cs_numpy's parity limits are the documented ones.
Per unit whose canonical GLB exists locally (GLBs are not in git; absent units are notes):
- a patched GLB's stamp is well formed, its numpy-CS parity on the changed support is inside the limits, and its
  configSha256 equals the current config's glbPatch (an edited patch not re-delivered fails);
- a config that declares glbPatch on a GLB whose delivery chain is current (it carries the ground stamp) but that
  lacks the patch stamp fails (the fix is declared, not delivered);
- the <glb>.patch.json sidecar names the stamp's source;
- a retained base (artifacts/homm3_glb_patch/<unit>/base.json) hashes to its record (a stale base, whose .blend was
  rebuilt since, is a note: --from-base refuses it and the next full run replaces it).
Proof tier of what it checks: source/static + generated artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path


def glb_json(p: Path) -> dict:
    with open(p, "rb") as f:
        head = f.read(20)
        return json.loads(f.read(struct.unpack_from("<I", head, 12)[0]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    ap.add_argument("--unit", action="append")
    a = ap.parse_args()
    root = Path(a.repo_root).resolve()
    sys.path.insert(0, str(root / "tools/homm3_glb_patch"))
    sys.path.insert(0, str(root / "tools"))
    import patch_glb as P  # noqa: E402
    import base as B  # noqa: E402
    from validate_homm3_def_retarget_emphasis_contract import DELIVERY_STAGES  # noqa: E402
    errors, notes = [], []

    # ---- static: chain position and the fleet route
    if DELIVERY_STAGES[0] != (P.STAMP, "patch"):
        errors.append(f"DELIVERY_STAGES must start with ({P.STAMP!r}, 'patch'), got {DELIVERY_STAGES[0]}")
    fr = (root / "tools/homm3_def_retarget_delivery/fleet_rebuild.py").read_text(encoding="utf-8")
    body = fr[fr.index("def rebuild("):fr.index("\nREBUILD_NOTE")]
    try:
        i_export = body.index('rec["deliveryBaseGlbSha256"] = sha_bytes(data)')
        i_retain = body.index("patch_base.retain(u, rec[\"route\"])")
        i_call = body.index("cur = fused_delivery_stages(u, rec, held, cfg, log, step)")
        fs = body[body.index("def fused_delivery_stages("):]
        i_patch = fs.index('fused("glb patch apply"')
        i_deyaw = fs.index('fused("deyaw"')
        if not (i_export < i_retain < i_call and i_patch < i_deyaw):
            errors.append("fleet_rebuild.py: the export, base retain, glb patch and deyaw must run in that order")
        if "run(" in fs or "subprocess" in fs:
            errors.append("fleet_rebuild.py: fused_delivery_stages must run every stage in process (no subprocess)")
        writes = fs[fs.index("for r in done:"):]
        if (fs.count("write_bytes(") != 1 or "if not FROM_BASE[0]:" not in writes
                or writes.index("write_sidecar(") > writes.index("write_bytes(")):
            errors.append("fleet_rebuild.py: the fused stages must write their sidecars, then the GLB once, and no GLB "
                          "on --from-base (look apply writes the delivery)")
        fb = body[body.index('rec["route"] = "from_base"'):body.index("elif stale:")]
        if "run(" in fb or "BLENDER" in fb:
            errors.append("fleet_rebuild.py: the --from-base route must not run any step before the delivery stages")
        look = body[body.index("if FROM_BASE[0]:\n        # the patch lane never changes"):]
        look = look[:look.index("elif prior.get")]
        if 'run_unit(u, ["apply"], glb_bytes=cur)' not in look or "force" in look:
            errors.append("fleet_rebuild.py: --from-base must re-deliver the look with the apply stage alone, on the "
                          "fused stages' bytes")
        if 'snapshot(u, LOGS / "_txn" / u, link=FROM_BASE[0])' not in fr:
            errors.append("fleet_rebuild.py: only the --from-base transaction snapshot may hard-link the delivered GLB")
    except ValueError as e:
        errors.append(f"fleet_rebuild.py: an expected patch-lane step is missing ({e})")
    if (P.PARITY_P99_MAX, P.PARITY_MAX_MAX) != (0.002, 0.02):
        errors.append(f"patch_glb parity limits changed to {(P.PARITY_P99_MAX, P.PARITY_MAX_MAX)} without the doc")

    # ---- per unit
    cfg_dir = root / "tools/homm3_def_retarget/units"
    units = a.unit or sorted(p.stem for p in cfg_dir.glob("*.json"))
    patched = 0
    for u in units:
        cp = cfg_dir / f"{u}.json"
        if not cp.is_file():
            errors.append(f"{u}: no unit config")
            continue
        cfg = json.loads(cp.read_text(encoding="utf-8"))
        spec = cfg.get(P.CONFIG_KEY)
        if spec is not None:
            errors += [f"{u}: {e}" for e in P.spec_errors(spec)]
        glb = root / "artifacts/homm3_def_retarget" / u / f"{u}_def_retarget.glb"
        if glb.is_file():
            ex = glb_json(glb).get("asset", {}).get("extras", {}) or {}
            st = ex.get(P.STAMP)
            if st is not None:
                patched += 1
                errors += [f"{u}: {e}" for e in P.stamp_errors({"asset": {"extras": ex}})]
                if spec is None:
                    errors.append(f"{u}: the GLB is patched but the unit config has no glbPatch (rebuild or restore it)")
                elif st.get("configSha256") != P.canonical_sha(spec):
                    errors.append(f"{u}: glbPatch edited since the GLB was patched; re-deliver "
                                  f"(fleet_rebuild.py --from-base {u})")
                side = Path(str(glb) + ".patch.json")
                if side.is_file():
                    sj = json.loads(side.read_text(encoding="utf-8"))
                    if sj.get("sourceGlbSha256") != st.get("sourceGlbSha256"):
                        errors.append(f"{u}: {side.name} source is not the stamp's")
                else:
                    errors.append(f"{u}: patched GLB without its {side.name} sidecar (the delivery chain's link)")
            elif spec is not None and "homm3DefRetargetDeliveryGround" in ex:
                errors.append(f"{u}: glbPatch is declared but the delivered GLB is not patched (fleet_rebuild.py "
                              f"--from-base {u}, or the full chain)")
            elif spec is not None:
                notes.append(f"{u}: glbPatch declared; the local GLB predates the current delivery chain")
        elif spec is not None:
            notes.append(f"{u}: glbPatch declared, no local GLB")
        if B.load(u) is not None:
            be = B.base_errors(u)
            stale = [e for e in be if "no longer the build" in e]
            errors += [e for e in be if e not in stale]
            notes += [f"{e} (note: --from-base refuses; the next full run retains a fresh base)" for e in stale]

    for n in notes:
        print("NOTE " + n)
    for e in errors:
        print("ERROR " + e)
    print(f"homm3 glb patch contract: {len(units)} unit configs, {patched} patched GLBs, "
          f"{'OK' if not errors else f'{len(errors)} errors'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
