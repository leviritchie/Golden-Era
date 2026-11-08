"""Validate the float64 Corrective Smooth bake contract (docs/homm3_cs_bake_float64.md).

    python tools/validate_homm3_cs_bake_contract.py [--repo-root R] [--unit U ...]
    python tools/validate_homm3_cs_bake_contract.py --prune-legacy      # drop legacy shas no GLB carries any more
    python tools/validate_homm3_cs_bake_contract.py --init-legacy       # once: record today's legacy bakes
    python tools/validate_homm3_cs_bake_contract.py --init-superseded   # once: record today's v2 (pre-fill) bakes
    python tools/validate_homm3_cs_bake_contract.py --init-stale-rekey  # once: record today's v3 bakes without re-key

Static (always):
- bake_cs.py computes the morphs with tools/homm3_glb_patch/cs_numpy.py (Weld.from_groups, corrective, solve,
  skin_dense) and records cs_numpy.BAKE_STAMP on the scene; it creates no Blender CORRECTIVE_SMOOTH modifier;
- export_glb.py writes the scene record into asset.extras; build_unit.py and bl_deliver.py exec bake_cs.py with
  __file__ (it locates cs_numpy by it);
- cs_numpy's rule constants are the documented ones and its unit tests pass (test_cs_numpy.py); cs_rekey_glb's held-key
  and orphan-target rules pass test_cs_rekey_glb.py.
Generated (per GLB present locally; GLBs are not in git):
- a canonical GLB (artifacts/homm3_def_retarget/<u>/<u>_def_retarget.glb) or a frozen selection GLB
  (<slice>/<unit>/inputs/look_delivered.glb of every tools/homm3_def_retarget_delivery/*_slice_v*.json row) that
  carries CS_ morph targets must carry the current bake record (cs_numpy.BAKE_SCHEMA, rule equal to cs_numpy.rule(),
  a rest round trip <= 1e-9, shapeKeys equal to its CS_ targets), or be listed by sha256 for that unit in
  tools/homm3_def_retarget/cs_bake_legacy.json: "glbSha256" for a legacy float32 bake (no record), "supersededSha256"
  for a float64 bake of a superseded schema (cs_numpy.SUPERSEDED_SCHEMAS: v2, undefined groups at S, no fill). Both
  lists only shrink: a new unlisted bake of either kind fails (re-run the unit's full chain,
  tools/homm3_def_retarget_delivery/fleet_rebuild.py), and listed shas no GLB carries any more are notes until
  --prune-legacy removes them.
- re-keyed clips (tools/homm3_def_retarget_delivery/cs_rekey_glb.py): a current-rule GLB that ran the delivery chain
  (it carries the ground stage's stamp) must carry the re-key record in its bake record and the cs_rekey stage stamp,
  with a status (rebaked / rigid / unchanged, measured against the post-patch export) for every clip with CS_ targets,
  every clip a re-keying stage stamps (stride match, Move low-pass: Unit_Move; densify, prop floor: their clips)
  among them (cs_rekey_glb.record_errors). The only exception is a sha in "staleRekeySha256" (recorded once, before
  the stage existed; shrink-only like the other lists). Static: fleet_rebuild.py runs cs_rekey after prop floor and
  before ground, and DELIVERY_STAGES has it there.
Proof tier of what it checks: source/static + generated artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

LEGACY_SCHEMA = "homm3_def_retarget.cs_bake_legacy.v1"


def glb_json(p: Path) -> dict:
    with open(p, "rb") as f:
        head = f.read(20)
        return json.loads(f.read(struct.unpack_from("<I", head, 12)[0]))


def cs_targets(js: dict) -> int:
    """CS_ morph targets on the skinned body (bake_cs names them CS_<action>_<frame>)."""
    n = 0
    for m in js.get("meshes", []):
        names = (m.get("extras") or {}).get("targetNames") or []
        n = max(n, sum(1 for t in names if str(t).startswith("CS_")))
    return n


class ShaCache:
    """sha256 of large GLBs keyed by (path, size, mtime_ns), kept under artifacts/ (not in git)."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.d = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self.d = {}
        self.dirty = False

    def sha(self, p: Path) -> str:
        st = p.stat()
        k = str(p.resolve())
        e = self.d.get(k)
        if e and e[0] == st.st_size and e[1] == st.st_mtime_ns:
            return e[2]
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""):
                h.update(b)
        self.d[k] = [st.st_size, st.st_mtime_ns, h.hexdigest()]
        self.dirty = True
        return self.d[k][2]

    def save(self):
        if self.dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, indent=0), encoding="utf-8")
            os.replace(tmp, self.path)


def stamp_errors(st, CS, n_targets: int) -> list[str]:
    if not isinstance(st, dict):
        return ["no bake record"]
    bad = []
    if st.get("schema") != CS.BAKE_SCHEMA:
        bad.append(f"schema {st.get('schema')!r} != {CS.BAKE_SCHEMA}")
    if st.get("rule") != CS.rule():
        bad.append(f"rule {st.get('rule')} != cs_numpy.rule() {CS.rule()}")
    rt = st.get("restRoundTripOverScale")
    if not isinstance(rt, (int, float)) or rt > 1e-9:
        bad.append(f"rest round trip {rt!r} > 1e-9 (CS must return the rest mesh at rest)")
    if st.get("shapeKeys") != n_targets:
        bad.append(f"record says {st.get('shapeKeys')} shape keys, the GLB has {n_targets} CS_ targets")
    return bad


def glbs(root: Path, units: list[str] | None):
    """(unit, kind, path, pinned sha or None) for canonical and frozen GLBs."""
    out = []
    ret = root / "artifacts/homm3_def_retarget"
    for d in sorted(ret.iterdir()) if ret.is_dir() else []:
        p = d / f"{d.name}_def_retarget.glb"
        if p.is_file() and (units is None or d.name in units):
            out.append((d.name, "canonical", p, None))
    for sel in sorted((root / "tools/homm3_def_retarget_delivery").glob("*_slice_v*.json")):
        js = json.loads(sel.read_text(encoding="utf-8"))
        for r in js.get("units", []):
            u = r.get("labSid")
            if not u or (units is not None and u not in units):
                continue
            p = root / "artifacts/homm3_def_retarget_delivery" / js.get("slice", sel.stem) / u / "inputs/look_delivered.glb"
            out.append((u, f"frozen:{sel.stem}", p, (r.get("frozen") or {}).get("lookDeliveredGlbSha256")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    ap.add_argument("--unit", action="append")
    ap.add_argument("--prune-legacy", action="store_true")
    ap.add_argument("--init-legacy", action="store_true")
    ap.add_argument("--init-superseded", action="store_true")
    ap.add_argument("--init-stale-rekey", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    a = ap.parse_args()
    root = Path(a.repo_root).resolve()
    sys.path.insert(0, str(root / "tools/homm3_glb_patch"))
    import cs_numpy as CS  # noqa: E402
    sys.path.insert(0, str(root / "tools/homm3_def_retarget_delivery"))
    sys.path.insert(0, str(root / "tools"))
    import cs_rekey_glb as RK  # noqa: E402
    from validate_homm3_def_retarget_emphasis_contract import DELIVERY_STAGES  # noqa: E402
    errors, notes = [], []
    GROUND = "homm3DefRetargetDeliveryGround"

    # ---- static
    rt = root / "tools/homm3_def_retarget"
    bake = (rt / "bake_cs.py").read_text(encoding="utf-8")
    code = "\n".join(l.split("#")[0] for l in bake.splitlines())
    if "'CORRECTIVE_SMOOTH'" in code or '"CORRECTIVE_SMOOTH"' in code:
        errors.append("bake_cs.py creates a Blender CORRECTIVE_SMOOTH modifier; the bake is cs_numpy float64 only")
    for need in ("import cs_numpy", "Weld.from_groups(", "weld.corrective(", "CSN.solve(", "CSN.skin_dense(",
                 "sc[CSN.BAKE_STAMP]", "CSN.rule()"):
        if need not in code:
            errors.append(f"bake_cs.py lost {need!r} (the float64 bake and its record)")
    exp = (rt / "export_glb.py").read_text(encoding="utf-8")
    if f'"{CS.BAKE_STAMP}"' not in exp or "write_glb_extras(OUT, _CS_STAMP" not in exp:
        errors.append("export_glb.py must write the scene's CS bake record into asset.extras")
    bu = (rt / "build_unit.py").read_text(encoding="utf-8")
    if '"__file__": _bcs' not in bu:
        errors.append("build_unit.py must exec bake_cs.py with __file__")
    bd = (root / "tools/homm3_def_retarget_emphasis/bl_deliver.py").read_text(encoding="utf-8")
    if '"__file__": os.path.join(RT, script)' not in bd:
        errors.append("bl_deliver.py run_shared must exec bake_cs.py with __file__")
    if (CS.DEGEN_CORNER_HEIGHT, CS.ITERATIONS, CS.FACTOR, CS.CS_SIGMA_MIN, CS.SCALE_MIN, CS.BAKE_SCHEMA) != \
            (1e-9, 30, 0.7, 0.25, 0.9, "homm3_def_retarget.cs_bake.v3") or \
            tuple(CS.SUPERSEDED_SCHEMAS) != ("homm3_def_retarget.cs_bake.v2",) or CS.FILL_COMPONENT_MAX != 6000:
        errors.append("cs_numpy rule constants changed without the doc (docs/homm3_cs_bake_float64.md)")
    # the CS re-bake device switch (docs/town_gpu_kernels.md, "CS re-bake"): cuda is the bit-identical port, cpu the
    # reference; both must stay, with no fallback between them
    gp = root / "tools/homm3_glb_patch"
    cst = (gp / "cs_torch.py").read_text(encoding="utf-8") if (gp / "cs_torch.py").is_file() else ""
    pgs = (gp / "patch_glb.py").read_text(encoding="utf-8")
    if tuple(getattr(CS, "DEVICES", ())) != ("cpu", "cuda") or not hasattr(CS, "resolve_device"):
        errors.append("cs_numpy must keep DEVICES ('cpu', 'cuda') and resolve_device (the CS re-bake device switch)")
    if "def offsets_batch" not in cst or "def edge_stretch" not in cst or "raise SystemExit" not in cst:
        errors.append("cs_torch.py must provide offsets_batch and edge_stretch and fail closed without CUDA")
    if 'CS.resolve_device() == "cuda"' not in pgs or "    X = np.c_[body.V + D" not in pgs:
        errors.append("patch_glb.edge_stretch must keep the cuda dispatch and its numpy reference")
    if not (gp / "test_cs_device_parity.py").is_file():
        errors.append("tools/homm3_glb_patch/test_cs_device_parity.py (the cpu/cuda byte-parity test) is missing")
    order = [k for k, _ in DELIVERY_STAGES]
    if (RK.STAMP, "cs_rekey") not in DELIVERY_STAGES or not (
            order.index("homm3DefRetargetDeliveryPropFloor") < order.index(RK.STAMP) < order.index(GROUND)):
        errors.append("DELIVERY_STAGES must hold the cs_rekey stage after prop floor and before ground")
    fr = (root / "tools/homm3_def_retarget_delivery/fleet_rebuild.py").read_text(encoding="utf-8")
    fs = fr[fr.index("def fused_delivery_stages("):fr.index("\nREBUILD_NOTE")] if "def fused_delivery_stages(" in fr else ""
    try:
        if not (fs.index('ref = cur') < fs.index('fused("prop_floor apply"') < fs.index('fused("cs_rekey apply"')
                < fs.index('fused("ground apply"')) or fs.index('ref = cur') < fs.index('fused("glb patch apply"'):
            raise ValueError("order")
        if 'M["cs_rekey"].apply_bytes(u, b, ref, glb)' not in fs:
            raise ValueError("reference")
    except ValueError as e:
        errors.append(f"fleet_rebuild.py: the fused stages must take the post-patch reference and run cs_rekey after "
                      f"prop floor and before ground ({e})")
    if not a.skip_tests:
        r = subprocess.run([sys.executable, str(root / "tools/homm3_glb_patch/test_cs_numpy.py")],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            errors.append("test_cs_numpy.py failed: " + (r.stderr or r.stdout)[-600:])
        r = subprocess.run([sys.executable, "-m", "unittest", str(root / "tools/homm3_def_retarget_delivery/test_cs_rekey_glb.py")],
                           capture_output=True, text=True, timeout=300, cwd=str(root))
        if r.returncode != 0:
            errors.append("test_cs_rekey_glb.py failed: " + (r.stderr or r.stdout)[-600:])
        r = subprocess.run([sys.executable, str(root / "tools/homm3_glb_patch/test_cs_device_parity.py")],
                           capture_output=True, text=True, timeout=1200, cwd=str(root))
        notes += ["test_cs_device_parity.py: " + x for x in (r.stdout or "").splitlines() if x.startswith("SKIP")]
        if r.returncode != 0:
            errors.append("test_cs_device_parity.py (cpu vs cuda CS re-bake bytes) failed: "
                          + (r.stdout + r.stderr)[-600:])

    # ---- generated
    lp = rt / "cs_bake_legacy.json"
    legacy = json.loads(lp.read_text(encoding="utf-8")) if lp.is_file() else None
    if legacy is None and not a.init_legacy:
        errors.append(f"missing {lp.relative_to(root)}")
        legacy = {"schema": LEGACY_SCHEMA, "units": {}}
    elif legacy is not None and legacy.get("schema") != LEGACY_SCHEMA:
        errors.append(f"{lp.name} schema {legacy.get('schema')!r} != {LEGACY_SCHEMA}")
    if legacy is not None and a.init_legacy:
        errors.append(f"--init-legacy refused: {lp.name} exists (the list only shrinks; use --prune-legacy)")
    if a.init_superseded and (legacy is None or legacy.get("supersededInitialised")):
        errors.append("--init-superseded refused: the superseded list was recorded once already (it only shrinks)")
    lu = (legacy or {}).get("units", {})
    cache = ShaCache(root / "artifacts/homm3_cs_bake/_sha_cache.json")
    seen_legacy: dict[str, set] = {}
    seen_sup: dict[str, set] = {}
    seen_rk: dict[str, set] = {}
    found_rk: dict[str, set] = {}
    rk_n = 0
    found: dict[str, set] = {}
    found_sup: dict[str, set] = {}
    v2 = legacy_n = sup_n = absent = 0
    for u, kind, p, pinned in glbs(root, a.unit):
        if not p.is_file():
            absent += 1
            continue
        js = glb_json(p)
        n = cs_targets(js)
        if n == 0:
            continue
        st = (js.get("asset", {}).get("extras") or {}).get(CS.BAKE_STAMP)
        if isinstance(st, dict) and st.get("schema") in CS.SUPERSEDED_SCHEMAS:
            s = pinned if (pinned and kind != "canonical") else cache.sha(p)
            found_sup.setdefault(u, set()).add(s)
            if a.init_superseded:
                continue
            if s in set((lu.get(u) or {}).get("supersededSha256", [])):
                sup_n += 1
                seen_sup.setdefault(u, set()).add(s)
            else:
                errors.append(f"{u} {kind}: CS morphs from a superseded float64 bake ({st.get('schema')}) not listed in "
                              f"{lp.name} supersededSha256 ({s[:12]}): re-run the unit's full chain (fleet_rebuild.py)")
            continue
        if st is not None:
            bad = stamp_errors(st, CS, n)
            if bad:
                errors.append(f"{u} {kind}: CS bake record: {'; '.join(bad)}")
            v2 += 1
            ex = js.get("asset", {}).get("extras") or {}
            if not bad and GROUND in ex:
                rbad = RK.record_errors(ex, RK.clip_targets(js))
                if rbad:
                    s = pinned if (pinned and kind != "canonical") else cache.sha(p)
                    found_rk.setdefault(u, set()).add(s)
                    if s in set((lu.get(u) or {}).get("staleRekeySha256", [])):
                        rk_n += 1
                        seen_rk.setdefault(u, set()).add(s)
                    elif not a.init_stale_rekey:
                        errors.append(f"{u} {kind}: {'; '.join(rbad)} ({s[:12]})")
            continue
        s = pinned if (pinned and kind != "canonical") else cache.sha(p)
        found.setdefault(u, set()).add(s)
        if s in set((lu.get(u) or {}).get("glbSha256", [])):
            legacy_n += 1
            seen_legacy.setdefault(u, set()).add(s)
        else:
            errors.append(f"{u} {kind}: {n} CS_ morph targets from a legacy float32 bake (no {CS.BAKE_STAMP}) that is "
                          f"not in {lp.name} ({s[:12]}): re-run the unit's full chain (fleet_rebuild.py) so bake_cs.py "
                          "bakes it in float64")
    cache.save()
    if a.init_legacy and legacy is None:
        lp.write_text(json.dumps({
            "schema": LEGACY_SCHEMA,
            "note": "GLBs whose Corrective Smooth morphs were baked by Blender's float32 modifier before the float64 bake "
                    "(docs/homm3_cs_bake_float64.md). This list only shrinks: a unit leaves it when its full chain "
                    "re-bakes it (fleet_rebuild.py); tools/validate_homm3_cs_bake_contract.py --prune-legacy drops "
                    "shas no GLB carries any more.",
            "units": {u: {"glbSha256": sorted(s)} for u, s in sorted(found.items())}}, indent=1) + "\n",
            encoding="utf-8")
        print(f"wrote {lp} with {sum(len(s) for s in found.values())} legacy shas over {len(found)} units")
        return 0
    if a.init_superseded and not errors:
        for u, s_ in found_sup.items():
            lu.setdefault(u, {})["supersededSha256"] = sorted(s_)
        legacy["supersededInitialised"] = True
        legacy["supersededNote"] = ("supersededSha256: GLBs baked by the float64 v2 rule (undefined groups at S, no "
                                    "harmonic fill) during the first rollout, 2026-09-30; shrink-only like glbSha256.")
        lp.write_text(json.dumps(legacy, indent=1) + "\n", encoding="utf-8")
        print(f"recorded {sum(len(s_) for s_ in found_sup.values())} superseded v2 shas over {len(found_sup)} units")
        return 0
    if a.init_stale_rekey:
        if legacy is None or legacy.get("staleRekeyInitialised"):
            errors.append("--init-stale-rekey refused: the stale re-key list was recorded once already (it only shrinks)")
        if errors:
            for e in errors:
                print("ERROR", e)
            return 1
        for u, s_ in found_rk.items():
            lu.setdefault(u, {})["staleRekeySha256"] = sorted(s_)
        legacy["staleRekeyInitialised"] = True
        legacy["staleRekeyNote"] = ("staleRekeySha256: current-rule GLBs delivered before cs_rekey_glb.py re-baked the CS "
                                    "morphs of re-keyed clips (2026-09-30); shrink-only like glbSha256.")
        lp.write_text(json.dumps(legacy, indent=1) + "\n", encoding="utf-8")
        print(f"recorded {sum(len(s_) for s_ in found_rk.values())} stale re-key shas over {len(found_rk)} units")
        return 0
    KEYS = ("glbSha256", "supersededSha256", "staleRekeySha256")
    stale = {}
    for u, e in lu.items():
        st_ = {"glbSha256": sorted(set(e.get("glbSha256", [])) - seen_legacy.get(u, set())),
               "supersededSha256": sorted(set(e.get("supersededSha256", [])) - seen_sup.get(u, set())),
               "staleRekeySha256": sorted(set(e.get("staleRekeySha256", [])) - seen_rk.get(u, set()))}
        st_ = {k: v for k, v in st_.items() if v}
        if st_:
            stale[u] = st_
    n_stale = sum(len(v) for st_ in stale.values() for v in st_.values())
    if a.unit is None and stale:
        if a.prune_legacy:
            for u, st_ in stale.items():
                for k, v in st_.items():
                    keep = sorted(set(lu[u][k]) - set(v))
                    if keep:
                        lu[u][k] = keep
                    else:
                        del lu[u][k]
                if not any(k in lu[u] for k in KEYS):
                    del lu[u]
            lp.write_text(json.dumps(legacy, indent=1) + "\n", encoding="utf-8")
            notes.append(f"pruned {n_stale} listed shas ({len(stale)} units)")
        else:
            notes.append(f"{n_stale} listed shas are carried by no GLB any more "
                         f"({', '.join(sorted(stale)[:12])}{' ...' if len(stale) > 12 else ''}): --prune-legacy")
    for n_ in notes:
        print("NOTE", n_)
    for e in errors:
        print("ERROR", e)
    print(f"cs bake contract: {'FAIL' if errors else 'OK'} (current-rule GLBs {v2}, listed legacy {legacy_n}, listed "
          f"superseded v2 {sup_n}, listed stale re-key {rk_n}, listed units left {len(lu)}, frozen GLBs not present locally {absent})")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
