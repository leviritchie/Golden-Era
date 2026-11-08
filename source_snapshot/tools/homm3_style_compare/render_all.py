"""Render every pair (ours + vanilla) under the same Hex/Lit relight, camera and battle scale.

    python tools/homm3_style_compare/render_all.py [--only h3_pikeman,...] [--rerender] [--variants-json V.json]

Our units: the retarget build .blend (read-only, never saved), posed at the first idle frame, base colour =
artifacts/homm3_unit_look/<unit>/basecolor.png, fitted to battleHeightHexes * battleWorldHeightPerHex (the runtime
FitSkinnedBattleMesh rule). Vanilla: extract_native.py output, battle size under the UnitViewConfig.scale rule.
Every Blender launch holds a gpuslot (tools/homm3_unit_look/gpuslot.py), which runs memgate.py inside the slot.
--variants-json {"<unit>": {"<variant>": "<basecolor png>"}} adds A/B base colours for our units.
Writes artifacts/homm3_style_compare/render/<pair>/{ours,vanilla}/...
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "homm3_unit_look"))
import pairs as PR  # noqa: E402
import spec as S  # noqa: E402
import gpuslot  # noqa: E402
from look import BLENDER  # noqa: E402

RENDER = PR.OUT / "render"
RES = 1600


def launch(tag, blend, job, logf):
    jp = Path(job["out"]) / "job.json"
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(job, indent=1))
    cmd = [BLENDER, "-b"] + ([str(blend)] if blend else []) + ["--factory-startup", "-P", str(HERE / "render_unit.py"),
                                                                 "--", "--job", str(jp)]
    with gpuslot.slot(cmd, f"style_compare:{tag}", on_wait=lambda m: print(tag, m, flush=True)):
        with open(logf, "w", encoding="utf-8") as f:
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=1800)
    if r.returncode != 0 or "STYLE_RENDER_OK" not in Path(logf).read_text(encoding="utf-8", errors="replace"):
        raise SystemExit(f"{tag}: Blender render failed, see {logf}")


def first_idle_frame(unit):
    fr = [f["globalIndex"] + 1 for f in S.master_sequence(unit)["frames"] if "idle" in f["clipKey"].lower()]
    return fr[0] if fr else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--rerender", action="store_true")
    ap.add_argument("--variants-json")
    ap.add_argument("--side", choices=["both", "ours", "vanilla"], default="both")
    a = ap.parse_args()
    extra = json.loads(Path(a.variants_json).read_text()) if a.variants_json else {}
    perhex = PR.per_hex()
    only = set(a.only.split(",")) if a.only else None
    for ours, pref, *_ in PR.PAIRS:
        if only and ours not in only:
            continue
        nname = PR.native_name(pref)
        nmeta = json.loads((PR.NATIVE / nname / "meta.json").read_text())
        h_ours = PR.hexes(ours) * perhex
        authored = pref.endswith("@authored")
        h_van = h_ours if authored else nmeta["worldHeight"]
        ortho = 2.3 * max(h_ours, h_van)
        pd = RENDER / ours
        if a.side in ("both", "vanilla") and (a.rerender or not (pd / "vanilla/render_meta.json").is_file()):
            job = {"kind": "native", "out": str(pd / "vanilla"), "native": str(PR.NATIVE / nname), "ortho": ortho,
                   "res": RES, "cond": "sand"}
            if authored:
                job["targetHeight"] = h_ours   # no unit view: shown at our unit's height (labelled on the page)
            launch(f"{ours}/vanilla", None, job, pd / "vanilla.log")
        looks = {"lit": str(S.out_dir(ours) / "basecolor.png"), **extra.get(ours, {})}
        need = a.rerender or not (pd / "ours/render_meta.json").is_file() or \
            any(not (pd / "ours" / f"{k}_battle.png").is_file() for k in looks)
        if a.side in ("both", "ours") and need:
            front = json.loads((S.out_dir(ours) / "metrics.json").read_text())["lighting"]["frontResolved"]["vector"]
            job = {"kind": "ours", "out": str(pd / "ours"), "frame": first_idle_frame(ours), "looks": looks, "front": front,
                   "targetHeight": h_ours, "ortho": ortho, "res": RES, "cond": "sand"}
            launch(f"{ours}/ours", S.blend_path(ours), job, pd / "ours.log")
        (pd / "pair.json").write_text(json.dumps({"ours": ours, "vanilla": nname, "prefab": pref, "ortho": ortho,
                                                  "res": RES, "heightOurs": h_ours, "heightVanilla": h_van,
                                                  "vanillaHeightAuthoredOnly": authored,
                                                  "hexesOurs": PR.hexes(ours), "perHex": perhex}, indent=1))
        print(f"RENDERED {ours} <-> {nname}", flush=True)


if __name__ == "__main__":
    main()
