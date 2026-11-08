"""town_full3d_motion.py: a looping motion preview of a bundled full-3D town candidate (ambient life review).

The catalog step's work/render_spec.json renders three time samples; this renders the `full` state at 20 samples over
5 s through the same Unity RenderStates (Unity queue), then writes
  renders_motion/motion.gif     the rest view looping at 960 px (what the reviewer plays)
  renders_motion/motion_map.jpg mean frame-to-frame change over a dimmed still: where something moves, how much
  renders_motion/zoom_<i>.gif   optional crops (--zoom x0,y0,x1,y1 in rest px, repeatable) at full resolution

  TOWN_FULL3D_FACTION=<f> TOWN_FULL3D_CANDIDATE=<cand> python town_full3d_motion.py [--frames 20] [--step 0.25]
      [--zoom 600,300,1100,650]
Needs the candidate's bundle (stronghold_full3d_scene.py bundle) and its unity_project.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stronghold_full3d_scene as S  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--step", type=float, default=0.25)
    ap.add_argument("--zoom", action="append", default=[])
    ap.add_argument("--reuse", action="store_true", help="only rebuild the GIFs from existing frames")
    a = ap.parse_args()
    from PIL import Image
    out = S.CAND / "renders_motion"
    frames = [out / f"full3d_full_t{i}.png" for i in range(a.frames)]
    if not a.reuse:
        rs = json.loads((S.WORK / "render_spec.json").read_text(encoding="utf-8"))
        rs["states"] = [dict(s, timed=True) for s in rs["states"] if s["name"] == "full"]
        rs["timeFrames"] = [round(i * a.step, 4) for i in range(a.frames)]
        rs["hires"] = dict(rs.get("hires") or {}, states=[])
        rs["panPoses"] = []
        if rs.get("cloth"):     # cloth sequences name pan poses; the rest one is all a motion preview needs
            rs["cloth"]["seqs"] = [q for q in rs["cloth"].get("seqs") or [] if not q.get("pose")]
        rs["outDir"] = str(out.resolve()).replace("\\", "/")
        spec = S.WORK / "render_spec_motion.json"
        spec.write_text(json.dumps(rs, indent=1), encoding="utf-8")
        out.mkdir(parents=True, exist_ok=True)
        for f in frames:
            f.unlink(missing_ok=True)
        bundle = S.OUT / f"homm3_town_scene3d_{S.SC.FACTION}"
        rc = S.unity("Homm3TownScene3dBundleBuild.RenderStates", ["-scene3dBundle", str(bundle.resolve()),
                     "-scene3dRender", str(spec.resolve())], S.WORK / "unity_render_motion.log", graphics=True,
                     output_dir=out)
        if rc != 0:
            print("motion: RenderStates rc", rc)
            return rc
    missing = [f.name for f in frames if not f.is_file()]
    if missing:
        raise SystemExit(f"motion: frames missing: {missing[:4]}")
    ims = [Image.open(f).convert("RGB") for f in frames]
    ms = int(a.step * 1000)
    small = [im.resize((960, round(960 * im.height / im.width)), Image.LANCZOS) for im in ims]
    small[0].save(out / "motion.gif", save_all=True, append_images=small[1:], duration=ms, loop=0)
    arr = np.stack([np.asarray(im, np.float32) for im in ims])
    d = np.abs(np.diff(arr, axis=0)).mean(axis=(0, 3))
    heat = np.clip(d / max(np.percentile(d, 99.7), 1e-3), 0, 1)
    base = arr[0] * 0.35
    vis = base * (1 - heat[..., None]) + np.array([255, 60, 20], np.float32) * heat[..., None]
    Image.fromarray(vis.astype(np.uint8)).save(out / "motion_map.jpg", quality=88)
    for i, z in enumerate(a.zoom):
        x0, y0, x1, y1 = (int(v) for v in z.split(","))
        sx, sy = ims[0].width / 1920, ims[0].height / 1080
        box = (round(x0 * sx), round(y0 * sy), round(x1 * sx), round(y1 * sy))
        crops = [im.crop(box) for im in ims]
        crops[0].save(out / f"zoom_{i}.gif", save_all=True, append_images=crops[1:], duration=ms, loop=0)
    print(f"motion: {out / 'motion.gif'} + motion_map.jpg ({len(a.zoom)} zooms); moving px "
          f"{float((heat > 0.15).mean()) * 100:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
