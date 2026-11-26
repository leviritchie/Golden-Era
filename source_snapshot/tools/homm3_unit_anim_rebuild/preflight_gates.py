"""Single deterministic mechanical preflight gate for rebuilt HoMM3 unit GLBs (0 LLM tokens).

Fast default checks (~1-2s per unit) before spending a Blender reel or vision-reviewer turn:
  1. Required out/<unit>.glb and tex/basecolor.png (>= 512x512).
  2. Unit_Move stride & slip gate via check_stride.py (0.78 <= req/act <= 1.35, slip <= 0.40, or flier/serpent).
  3. Calm native-cadence #32 Unit_Idle gate directly on authored out/<unit>.glb.
  4. Fast GLB structural & articulation smoke gates (zero CPU ground_glb skinning by default; pass --full-smoke
     for full in-temp patch_glb + ground_check + freeze_check):
       - Valid Hips/DEF-hips/DEF-pelvis node & single body mesh node ('body' or <unit>)
       - Facing pair Unit_Idle t=0 angle <= 30 deg
       - Zero root-node translation/rotation animation channels on Unit_* clips
       - All required base DEF clips present (when --base-selection provides look_delivered.glb)
       - flyer_articulation.gate(Unit_Move) == [] and max freezeRun <= 1
  5. Latest qc/anim_qc_*.json (auto-running Blender anim_qc.py on game.blend if stale/missing unless
     --no-run-qc): requires vib_verts == 0, verts_below_ground == 0, seam pose_gap_max <= 0.005.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
COORD_DIR = Path("V:/scratch_claude/unit_rebuild/_fortress_coord")
DEFAULT_REBUILD_ROOT = Path("V:/scratch_claude/unit_rebuild")
DEFAULT_BLENDER = Path("V:/Tools/blender-mcp/blender-5.2.2/blender.exe")
ANIM_QC_SCRIPT = REPO_ROOT / "tools/asset_mcp/blender/anim_qc.py"

for _p in (
    COORD_DIR,
    REPO_ROOT / "tools/homm3_def_retarget_delivery",
    REPO_ROOT / "tools/homm3_def_retarget",
    REPO_ROOT / "tools/homm3_unit_look",
    REPO_ROOT / "tools/homm3_idle_cadence",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import assemble_rebuild_slice as ARS  # noqa: E402
import check_stride as CS  # noqa: E402
import flyer_articulation as FA  # noqa: E402
import glbpatch  # noqa: E402
import ground_check as GC  # noqa: E402
import source_mesh_identity  # noqa: E402
import spec as unit_look_spec  # noqa: E402


def _resolve_selection_path(base_selection: str) -> Path:
    deliv_dir = REPO_ROOT / "tools/homm3_def_retarget_delivery"
    p = Path(base_selection)
    if not p.is_absolute():
        p = (deliv_dir / p.name) if (deliv_dir / p.name).is_file() else (REPO_ROOT / p)
    if not p.is_file():
        raise FileNotFoundError(f"Base selection not found: {base_selection}")
    return p


def _resolve_base_row(unit: str, base_selection: str) -> tuple[dict, Path | None]:
    deliv_dir = REPO_ROOT / "tools/homm3_def_retarget_delivery"
    candidates: list[Path] = []
    if base_selection:
        candidates.append(_resolve_selection_path(base_selection))
    else:
        candidates.extend(sorted(deliv_dir.glob("*_slice_v1.json")))
        candidates.extend(sorted(p for p in deliv_dir.glob("*.json") if p not in candidates))

    for jf in candidates:
        try:
            sel = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        for row in sel.get("units", []):
            if row.get("labSid") == unit:
                out_rel = sel.get("out")
                base_out = None
                if out_rel:
                    bo = Path(out_rel)
                    base_out = bo if bo.is_absolute() else (REPO_ROOT / bo)
                return row, base_out
    return {"labSid": unit, "gameSid": unit}, None


def _fast_smoke_check(
    unit: str,
    glb_path: Path,
    spec_unit: str,
    base_look_glb: Path | None,
) -> str:
    g = glbpatch.Glb.load(glb_path)
    js = g.json
    nodes = js["nodes"]
    name_set = {n.get("name", "") for n in nodes}

    if not ({"Hips", "DEF-hips", "DEF-pelvis"} & name_set):
        raise RuntimeError(f"{unit}: neither Hips nor DEF-hips/DEF-pelvis in GLB nodes")

    facing_pair = None
    if "LeftUpLeg" in name_set and "RightUpLeg" in name_set:
        facing_pair = ("LeftUpLeg", "RightUpLeg")
    else:
        for l_name, r_name in ARS.LEGGED_PAIR_CANDIDATES:
            if "wing" in l_name.lower() or "wing" in r_name.lower():
                continue
            if l_name in name_set and r_name in name_set:
                facing_pair = (l_name, r_name)
                break
        if facing_pair is None:
            for l_name, r_name in ARS.ARM_PAIR_CANDIDATES:
                if "wing" in l_name.lower() or "wing" in r_name.lower():
                    continue
                if l_name in name_set and r_name in name_set:
                    facing_pair = (l_name, r_name)
                    break
        if facing_pair is None:
            wing_l = sorted(
                n for n in name_set
                if n.lower().startswith("def-wing") and n.endswith(".L") and (n[:-2] + ".R") in name_set
            )
            if wing_l:
                facing_pair = (wing_l[0], wing_l[0][:-2] + ".R")

    mesh_node_idxs = [i for i, n in enumerate(nodes) if "mesh" in n]
    body_node_idxs = [i for i in mesh_node_idxs if nodes[i].get("name") in ("body", unit)]
    if len(body_node_idxs) != 1 and len(mesh_node_idxs) != 1:
        raise RuntimeError(f"{unit}: expected 1 body mesh node, found {[nodes[i].get('name') for i in mesh_node_idxs]}")

    scene_idx = js.get("scene", 0)
    root_nodes = set(js["scenes"][scene_idx].get("nodes", []))
    for an in js.get("animations", []):
        if not an.get("name", "").startswith("Unit_"):
            continue
        for ch in an.get("channels", []):
            t = ch.get("target", {})
            if t.get("node") in root_nodes and t.get("path") in ("translation", "rotation"):
                raise RuntimeError(f"{unit}: clip {an['name']} animates root node {nodes[t['node']].get('name')!r}")

    facing_deg = ARS.verify_idle0_facing_xz(js, g.bin, facing_pair[0], facing_pair[1]) if facing_pair else None

    if base_look_glb is not None and base_look_glb.is_file():
        b_bytes = base_look_glb.read_bytes()
        jl = struct.unpack_from("<I", b_bytes, 12)[0]
        b_js = json.loads(b_bytes[20:20 + jl])
        base_clips = {a.get("name", "") for a in b_js.get("animations", []) if a.get("name", "").startswith("Unit_")}
        src_clips = {a.get("name", "") for a in js.get("animations", []) if a.get("name", "").startswith("Unit_")}
        missing = sorted(base_clips - src_clips)
        if missing:
            raise RuntimeError(f"{unit}: missing required base DEF clips: {missing}")

    clips = FA.glb_clips(glb_path)
    m = clips.get(FA.GATE_CLIP)
    gbad = FA.gate(m, spec_unit) if m else [f"missing {FA.GATE_CLIP}"]
    if gbad:
        raise RuntimeError(f"articulation gate failed: {gbad}")
    worst_fr = max((v.get("freezeRun", 0) for v in clips.values()), default=0)
    if worst_fr > 1:
        frozen_clips = {k: v.get("freezeRun", 0) for k, v in clips.items() if v.get("freezeRun", 0) > 1}
        raise RuntimeError(f"freezeRun > 1 on authored clips: {frozen_clips}")

    fstr = f"{facing_deg:.2f}" if facing_deg is not None else "None"
    return f"facing={fstr} deg clips={len(clips)} wing=({m.get('wingSwing')},{m.get('wingRange')}) maxFreeze={worst_fr}"


def _run_blender_anim_qc(unit: str, unit_dir: Path, blender: Path) -> Path:
    blend_p = unit_dir / "game.blend"
    if not blend_p.is_file():
        raise FileNotFoundError(f"{unit}: game.blend not found for anim_qc at {blend_p}")
    qc_dir = unit_dir / "qc"
    qc_dir.mkdir(parents=True, exist_ok=True)
    out_json = qc_dir / "anim_qc_preflight.json"

    py_expr = (
        "import bpy, sys, runpy; "
        f"u={unit!r}; "
        "arm = next(o.name for o in bpy.data.objects if o.type=='ARMATURE'); "
        "ms = [o for o in bpy.data.objects if o.type=='MESH' and len(o.data.vertices)>500]; "
        "mesh = next((o.name for o in ms if o.name in ('body', u)), ms[0].name); "
        f"sys.argv = ['blender', '--', mesh, arm, {str(out_json)!r}]; "
        f"runpy.run_path({str(ANIM_QC_SCRIPT)!r}, run_name='__main__')"
    )
    res = subprocess.run(
        [str(blender), "-b", str(blend_p), "--python-exit-code", "1", "--python-expr", py_expr],
        capture_output=True, text=True, check=False,
    )
    if res.returncode != 0 or not out_json.is_file():
        tail = (res.stdout + "\n" + res.stderr)[-2000:]
        raise RuntimeError(f"{unit}: Blender anim_qc failed (exit={res.returncode}):\n{tail}")
    return out_json


def check_anim_qc(unit: str, unit_dir: Path, glb_path: Path, blender: Path, no_run_qc: bool) -> tuple[bool, str]:
    qc_dir = unit_dir / "qc"
    qcs = sorted((qc_dir.glob("anim_qc_*.json") if qc_dir.is_dir() else []), key=lambda p: p.stat().st_mtime)
    glb_mtime = glb_path.stat().st_mtime
    latest = qcs[-1] if qcs else None
    if latest is None or latest.stat().st_mtime + 1.0 < glb_mtime:
        if no_run_qc:
            why = "missing" if latest is None else f"stale ({latest.name} older than {glb_path.name})"
            return False, f"anim_qc {why} and --no-run-qc passed"
        if not (unit_dir / "game.blend").is_file():
            why = "missing" if latest is None else f"stale ({latest.name})"
            return False, f"anim_qc {why} and game.blend missing"
        latest = _run_blender_anim_qc(unit, unit_dir, blender)

    report = json.loads(latest.read_text(encoding="utf-8"))
    clips = report.get("clips") or {}
    if not clips:
        return False, f"{latest.name}: empty clips dict"

    bad_clips: list[str] = []
    for cname, cdata in clips.items():
        tot = cdata.get("totals") or {}
        vib = int(tot.get("vib_verts", 0))
        below = int(tot.get("verts_below_ground", 0))
        seam_gap = float((cdata.get("seam") or {}).get("pose_gap_max", 0.0))
        reasons = []
        if vib != 0:
            reasons.append(f"vib={vib}")
        if below != 0:
            reasons.append(f"below={below}")
        if seam_gap > 0.005:
            reasons.append(f"seam_gap={seam_gap:.4f}>0.005")
        if reasons:
            bad_clips.append(f"{cname}({','.join(reasons)})")
    if bad_clips:
        return False, f"{latest.name} FAILED: {', '.join(bad_clips)}"
    return True, f"{latest.name}: {len(clips)}/{len(clips)} clips vib=0, below=0, seam<=0.005"


def run_preflight(
    unit: str,
    rebuild_root: Path,
    base_selection: str,
    skip_anim_qc: bool,
    no_run_qc: bool,
    full_smoke: bool,
    blender: Path,
) -> tuple[bool, list[tuple[str, bool, str]]]:
    udir = rebuild_root / unit
    glb_path = udir / "out" / f"{unit}.glb"
    tex_path = udir / "tex/basecolor.png"
    results: list[tuple[str, bool, str]] = []

    try:
        if not glb_path.is_file():
            raise FileNotFoundError(f"missing GLB: {glb_path}")
        if not tex_path.is_file():
            raise FileNotFoundError(f"missing basecolor: {tex_path}")
        with Image.open(tex_path) as im:
            if im.width < 512 or im.height < 512:
                raise RuntimeError(f"basecolor too small: {im.size}")
            tex_sz = im.size
        results.append(("files", True, f"{glb_path.name} ({glb_path.stat().st_size // 1024} KiB), tex={tex_sz}"))
    except Exception as exc:
        results.append(("files", False, str(exc)))
        return False, results

    try:
        ok_s, res_s = CS.analyze_unit(unit, glb_path)
        if res_s.get("flier"):
            s_msg = f"FLIER ms={res_s['moveSpeed']:.2f} cyc={res_s['cycleSeconds']:.3f}s"
        elif res_s.get("serpent"):
            s_msg = f"SERPENT ms={res_s['moveSpeed']:.2f} tail={res_s['activeTailBones']}/{res_s['tailBones']}"
        elif "error" in res_s:
            s_msg = res_s["error"]
        else:
            s_msg = f"ms={res_s['moveSpeed']:.2f} req/act={res_s['requiredOverActual']:.2f} slip={res_s['slipRatio']:.2f}"
        results.append(("stride", ok_s, s_msg))
    except Exception as exc:
        results.append(("stride", False, str(exc)))

    try:
        cad, max_nw_pk = ARS._check_calm_idle_cadence_gate(glb_path, unit)
        ang_m = (cad.get("angSpeedDegS") or {}).get("median")
        pk_m = (cad.get("peakAngSpeedDegS") or {}).get("median")
        results.append((
            "calm_idle", True,
            f"len={cad['lengthS']:.2f}s angMed={ang_m:.1f} pkMed={pk_m:.1f} maxNwPk={max_nw_pk:.1f}",
        ))
    except Exception as exc:
        results.append(("calm_idle", False, str(exc)))

    try:
        row, base_out = _resolve_base_row(unit, base_selection)
        base_spec_p = (base_out / unit / "inputs" / f"{unit}.json") if base_out is not None else None
        if base_spec_p is not None and base_spec_p.is_file():
            spec_obj = json.loads(base_spec_p.read_text(encoding="utf-8"))
        else:
            spec_obj = unit_look_spec.load(unit)
        spec_unit = spec_obj["unit"]
        base_look_glb = (base_out / unit / "inputs/look_delivered.glb") if base_out else None

        if not full_smoke:
            sm_msg = _fast_smoke_check(unit, glb_path, spec_unit, base_look_glb)
            results.append(("smoke_gates", True, sm_msg))
        else:
            reviews = source_mesh_identity.load_reviews()
            legacy = source_mesh_identity.load_legacy()
            with tempfile.TemporaryDirectory() as tmp:
                tdir = Path(tmp)
                if base_out is not None and (base_out / unit / "inputs" / f"{unit}.json").is_file():
                    spec_obj, _, _ = ARS.resolve_spec_and_vfx(row, base_out, tdir, unit)
                    spec_unit = spec_obj["unit"]
                look_bytes, retimed_bytes, _, pinfo, _ = ARS.patch_glb(
                    src_glb=glb_path,
                    basecolor_png=tex_path,
                    lab_sid=unit,
                    spec_unit=spec_unit,
                    base_look_glb=base_look_glb if (base_look_glb and base_look_glb.is_file()) else None,
                    reviews=reviews,
                    legacy=legacy,
                )
                look_p = tdir / "look_delivered.glb"
                ret_p = tdir / "delivered_idle_retimed.glb"
                look_p.write_bytes(look_bytes)
                ret_p.write_bytes(retimed_bytes)

                gr_bad, gr_rec = GC.ground_check(spec_unit, retimed_bytes)
                if gr_bad:
                    raise RuntimeError(f"ground_check failed: {gr_bad}")
                fbad, _ = FA.freeze_check(spec_unit, ret_p, look_p)
                if fbad:
                    raise RuntimeError(f"freeze_check failed: {fbad}")
                clips = FA.glb_clips(ret_p)
                m = clips.get(FA.GATE_CLIP)
                gbad = FA.gate(m, spec_unit) if m else [f"missing {FA.GATE_CLIP}"]
                if gbad:
                    raise RuntimeError(f"articulation gate failed: {gbad}")
                ARS._check_calm_idle_cadence_gate(ret_p, unit)
                worst_fr = max(v.get("freezeRun", 0) for v in clips.values())
                fstr = f"{pinfo['facingDeg']:.2f}" if pinfo["facingDeg"] is not None else "None"
                results.append((
                    "smoke_gates", True,
                    f"facing={fstr} deg clips={len(gr_rec['clips'])} wing=({m.get('wingSwing')},{m.get('wingRange')}) maxFreeze={worst_fr}",
                ))
    except Exception as exc:
        results.append(("smoke_gates", False, str(exc)))

    if skip_anim_qc:
        results.append(("anim_qc", True, "SKIPPED (--skip-anim-qc)"))
    else:
        try:
            ok_q, q_msg = check_anim_qc(unit, udir, glb_path, blender=blender, no_run_qc=no_run_qc)
            results.append(("anim_qc", ok_q, q_msg))
        except Exception as exc:
            results.append(("anim_qc", False, str(exc)))

    overall = all(ok for _, ok, _ in results)
    return overall, results


def _run_one_unit(task: tuple) -> tuple[str, bool, list[tuple[str, bool, str]], float]:
    unit, rebuild_root, base_selection, skip_anim_qc, no_run_qc, full_smoke, blender = task
    t0 = time.perf_counter()
    overall, rows = run_preflight(
        unit=unit,
        rebuild_root=rebuild_root,
        base_selection=base_selection,
        skip_anim_qc=skip_anim_qc,
        no_run_qc=no_run_qc,
        full_smoke=full_smoke,
        blender=blender,
    )
    return unit, overall, rows, time.perf_counter() - t0


def _resolve_units(unit_arg: str, units_arg: str, base_selection: str) -> list[str]:
    units: list[str] = []
    if unit_arg:
        units.append(unit_arg.strip())
    if units_arg:
        units.extend(u.strip() for u in units_arg.split(",") if u.strip())
    if not units and base_selection:
        p = _resolve_selection_path(base_selection)
        sel = json.loads(p.read_text(encoding="utf-8"))
        units = [r["labSid"] for r in sel.get("units", [])]
    return units


def _print_unit_result(unit: str, overall: bool, rows: list[tuple[str, bool, str]], elapsed: float) -> None:
    print(f"=== preflight_gates: {unit} -> {'PASS' if overall else 'FAIL'} ({elapsed:.2f}s) ===", flush=True)
    for name, ok, msg in rows:
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag:4s}] {name:12s}: {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--unit", default="", help="Single unit labSid")
    ap.add_argument("--units", default="", help="Comma-separated labSids (or omit with --base-selection for whole slice)")
    ap.add_argument("--base-selection", default="", help="Optional base slice JSON (e.g. dungeon_slice_v1.json)")
    ap.add_argument("--rebuild-root", type=Path, default=DEFAULT_REBUILD_ROOT)
    ap.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    ap.add_argument("--skip-anim-qc", action="store_true")
    ap.add_argument("--no-run-qc", action="store_true", help="Fail instead of running Blender if anim_qc JSON is missing/stale")
    ap.add_argument("--full-smoke", action="store_true", help="Run full CPU ground_glb + ground_check + freeze_check in temp dir (~48s/unit)")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()

    units = _resolve_units(args.unit, args.units, args.base_selection)
    if not units:
        ap.error("Provide --unit, --units, or --base-selection")

    tasks = [
        (u, args.rebuild_root, args.base_selection, args.skip_anim_qc, args.no_run_qc, args.full_smoke, args.blender)
        for u in units
    ]
    any_fail = False
    t_wall = time.perf_counter()
    if len(tasks) > 1 and args.jobs > 1:
        max_w = min(args.jobs, len(tasks), 3 if args.full_smoke else args.jobs)
        by_unit: dict[str, tuple[bool, list[tuple[str, bool, str]], float]] = {}
        with ProcessPoolExecutor(max_workers=max_w) as pool:
            futs = {pool.submit(_run_one_unit, t): t[0] for t in tasks}
            for fut in as_completed(futs):
                u, overall, rows, elapsed = fut.result()
                by_unit[u] = (overall, rows, elapsed)
                if not overall:
                    any_fail = True
                _print_unit_result(u, overall, rows, elapsed)
        passed = sum(1 for v in by_unit.values() if v[0])
        print(f"SUMMARY: {passed}/{len(units)} PASS in {time.perf_counter() - t_wall:.2f}s wall", flush=True)
    else:
        passed = 0
        for t in tasks:
            u, overall, rows, elapsed = _run_one_unit(t)
            if overall:
                passed += 1
            else:
                any_fail = True
            _print_unit_result(u, overall, rows, elapsed)
        if len(tasks) > 1:
            print(f"SUMMARY: {passed}/{len(units)} PASS in {time.perf_counter() - t_wall:.2f}s wall", flush=True)
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
