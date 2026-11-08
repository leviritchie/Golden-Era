#!/usr/bin/env python3
"""Launcher for host_fit (GPU) that prepares targets like run_pseudo_rig_fit.py"""
import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
SILHOUETTE = TOOL.parent / "homm3_silhouette_pose_fit"
DEFAULT_BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
DEFAULT_CONFIG = TOOL / "configs/h3_crusader_combat_core_pseudo_rig.json"
DEFAULT_CONFIG_V1 = TOOL / "configs/h3_crusader_combat_core_pseudo_rig_v1.json"

def load_job(path: Path) -> dict:
    job=json.loads(path.read_text(encoding='utf-8'))
    def resolve(p: str) -> str:
        pp=Path(p)
        if pp.is_absolute(): return str(pp)
        return str((ROOT/pp).resolve())
    job["masterGlb"]=resolve(job["masterGlb"])
    job["outputDir"]=resolve(job["outputDir"])
    if job.get("exportDir"): job["exportDir"]=resolve(job["exportDir"])
    if job.get("handleCatalog"): job["handleCatalog"]=resolve(job["handleCatalog"])
    for fr in job["frames"]:
        fr["path"]=resolve(fr["path"])
    return job

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--v1", action="store_true")
    ap.add_argument("--blender", type=Path, default=Path(DEFAULT_BLENDER))
    ap.add_argument("--python", type=Path, default=Path(sys.executable))
    ap.add_argument("--skip-targets", action="store_true")
    ap.add_argument("--force-targets", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--clips", type=str, default="")
    ap.add_argument("--device", type=str, default="cuda")
    ap.add_argument("--frames", type=str, default="", help="comma list of global frame indices to run host only subset")
    args=ap.parse_args()
    if args.config is None:
        args.config=DEFAULT_CONFIG_V1 if args.v1 else DEFAULT_CONFIG
    raw=args.config if args.config.is_file() else (ROOT/args.config)
    if not raw.is_file():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 2
    job=load_job(raw)
    is_v1=args.v1 or str(job.get("targetVersion","")).lower() in {"v1","edge","clip_shared"}
    if args.clips.strip():
        want={c.strip() for c in args.clips.split(",") if c.strip()}
        job["frames"]=[f for f in job["frames"] if str(f.get("clipId")) in want]
        job["clips"]=[c for c in job.get("clips") or [] if str(c.get("clipId")) in want]
        if not job["frames"]:
            print(f"no frames left after --clips {want}", file=sys.stderr)
            return 2
        tag="_".join(sorted(want))
        suffix=f"out_fit_v1_{tag}" if is_v1 else f"out_fit_{tag}"
        exp=f"export_v1_{tag}" if is_v1 else f"export_{tag}"
        out=Path(job["outputDir"]).parent / suffix
        # Ensure absolute
        job["outputDir"]=str(out.resolve())
        job["exportDir"]=str((out.parent / exp).resolve())
        args.force_targets=True
    # Mark for host that we use absolute but also keep original for blender bake helper resolution
    # Keep host placement bold: absolute (no warp) unless job says normalize
    # For bold experiment, enforce clip_rest placement (no sim2D cheating) regardless of v0 normalize
    # User wants bold, so force predPlacement to clip_rest for host
    job["predPlacement"]="clip_rest"
    # Also ensure targetVersion v1 for framing etc
    # Config overrides for fast
    if args.smoke:
        job.setdefault("optimizer",{})
        job["optimizer"]["method"]="smoke"
        job["optimizer"]["stageBPasses"]=0
    elif args.fast:
        job.setdefault("optimizer",{})
        job["optimizer"]["method"]="nelder"
        job["optimizer"]["blockSize"]=4
        job["optimizer"]["randomProbesPerBlock"]=8
        job["optimizer"]["simplexBoundFrac"]=0.40
        job["optimizer"]["polishIters"]=48
        job["optimizer"]["stageBPasses"]=1
        job["optimizer"]["stageBPolishIters"]=24
    # Host does fast raster so we can tolerate more iters but we cut for demo

    out_dir=Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    # Write resolved for both host and blender bake helper
    resolved=out_dir/"job.resolved.json"
    # Need to store both relative and absolute: host expects outputDir_abs etc but we write absolute paths directly? Host recomputes resolve from masterGlb/outputDir containing absolute -> will treat as absolute and keep. So write absolute.
    # Also write aliases for host keys
    job["outputDir_abs"]=job["outputDir"]
    job["masterGlb_abs"]=job["masterGlb"]
    if job.get("exportDir"):
        job["exportDir_abs"]=job["exportDir"]
    if job.get("handleCatalog"):
        job["handleCatalog_abs"]=job["handleCatalog"]
    for fr in job["frames"]:
        fr["path_abs"]=fr["path"]
    resolved.write_text(json.dumps(job, indent=2), encoding='utf-8')
    print(f"[run_host] resolved {resolved}")

    py=args.python if args.python.is_file() else Path(sys.executable)
    if not args.skip_targets:
        if is_v1:
            cmd=[str(py), str(TOOL/"prepare_targets_v1.py"), "--config", str(resolved)]
        else:
            cmd=[str(py), str(SILHOUETTE/"prepare_targets.py"), "--config", str(resolved)]
        if args.force_targets or bool(job.get("cullDefSoftShadows",False)):
            cmd.append("--force")
        print("Running:", " ".join(cmd), flush=True)
        cwd=str(TOOL if is_v1 else SILHOUETTE)
        rc=subprocess.run(cmd, cwd=cwd).returncode
        if rc!=0:
            print("prepare_targets failed", file=sys.stderr)
            return rc
    # Run host fit
    host_py=TOOL/"host_fit.py"
    cmd=[str(py), str(host_py), "--job", str(resolved), "--device", args.device]
    if args.frames.strip():
        cmd+=["--frames", args.frames]
    print("Running host fit:", " ".join(cmd), flush=True)
    rc=subprocess.run(cmd, cwd=str(ROOT)).returncode
    if rc!=0:
        print("host_fit failed", file=sys.stderr)
        return rc
    report=out_dir/"fit_report.json"
    if not report.is_file():
        print(f"missing fit report: {report}", file=sys.stderr)
        return 2
    print(f"fit report: {report}", flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
