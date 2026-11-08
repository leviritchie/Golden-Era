#!/usr/bin/env python3
"""
Build A-pose hobgoblin via Meshy API, hand-attach mace from combat master, export assembly.

Steps:
  1. image-to-3d (pose_mode=a-pose) from hobgoblin portrait
  2. Meshy auto-rig (humanoid API)
  3. Extract mace mesh island from Meshy46 combat master (Bone_033 neighborhood)
  4. Parent/skin-attach mace to A-pose strike-hand tip bone
  5. Write master GLB + bone role draft + report

Proof: generated artifact validated — Meshy A-pose + local mace attach; not OE runtime proven.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
POSE_FIT = ROOT / "tools" / "homm3_silhouette_pose_fit"
DEFAULT_BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
PORTRAIT = ROOT / "artifacts/unit_portrait_touchup_pilot/final/h3_goblin_upg.png"
MACE_DONOR = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/Meshy_AI_Character_output_3.glb"
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_apose_mace_attach"

sys.path.insert(0, str(TOOL))
from meshy_client import (  # noqa: E402
    create_image_to_3d,
    create_rigging,
    download_url,
    load_api_key,
    poll_task,
    task_error_message,
)


def _extract_glb_url(task: dict) -> str | None:
    candidates = []
    mu = task.get("model_urls")
    if isinstance(mu, dict):
        candidates.append(mu.get("glb"))
    result = task.get("result")
    if isinstance(result, dict):
        rmu = result.get("model_urls")
        if isinstance(rmu, dict):
            candidates.append(rmu.get("glb"))
        candidates.append(result.get("glb_url"))
        candidates.append(result.get("model_url"))
    candidates.append(task.get("model_url"))
    candidates.append(task.get("glb_url"))
    for c in candidates:
        if isinstance(c, str) and c.startswith("http"):
            return c
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--portrait", type=Path, default=PORTRAIT)
    ap.add_argument("--mace-donor", type=Path, default=MACE_DONOR)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    ap.add_argument("--polycount", type=int, default=12000)
    ap.add_argument("--height-meters", type=float, default=1.6)
    ap.add_argument("--skip-meshy", action="store_true", help="Reuse existing generated/rigged GLBs under --out")
    args = ap.parse_args()

    out = args.out
    gen = out / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "ok": False,
        "portrait": str(args.portrait).replace("\\", "/"),
        "maceDonor": str(args.mace_donor).replace("\\", "/"),
        "proof": "generated artifact validated — A-pose Meshy + hand-attached mace; not OE runtime proven",
    }

    if not args.portrait.is_file():
        print(f"missing portrait: {args.portrait}", file=sys.stderr)
        return 2
    if not args.mace_donor.is_file():
        print(f"missing mace donor: {args.mace_donor}", file=sys.stderr)
        return 2

    ap_glb = gen / "apose_textured.glb"
    rig_glb = gen / "apose_rigged.glb"

    if not args.skip_meshy:
        api_key = load_api_key()
        print("=== Meshy image-to-3d pose_mode=a-pose ===", flush=True)
        tid = create_image_to_3d(
            api_key,
            image_path=args.portrait,
            should_texture=True,
            target_polycount=int(args.polycount),
            model_type="smart-topology",
            ai_model="meshy-t2",
            pose_mode="a-pose",
            should_remesh=True,
        )
        report["imageTaskId"] = tid
        task = poll_task(api_key, "image-to-3d", tid, timeout_s=1800)
        report["imageStatus"] = task.get("status")
        report["imageCredits"] = task.get("consumed_credits")
        if task.get("status") != "SUCCEEDED":
            report["error"] = task_error_message(task)
            (out / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
            return 1
        glb_url = _extract_glb_url(task)
        if not glb_url:
            report["error"] = f"no glb url; keys={list(task.keys())}"
            (out / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            return 1
        download_url(glb_url, ap_glb)
        report["aposeGlb"] = str(ap_glb.resolve()).replace("\\", "/")

        print("=== Meshy auto-rig (humanoid API) ===", flush=True)
        rid = create_rigging(api_key, input_task_id=tid, height_meters=float(args.height_meters))
        report["rigTaskId"] = rid
        rtask = poll_task(api_key, "rigging", rid, timeout_s=1200)
        report["rigStatus"] = rtask.get("status")
        report["rigCredits"] = rtask.get("consumed_credits")
        if rtask.get("status") != "SUCCEEDED":
            # Fallback: try model_url data URI of downloaded apose glb
            print("input_task_id rig failed; trying model_url of a-pose GLB", flush=True)
            report["rigError"] = task_error_message(rtask)
            from meshy_client import file_to_data_uri

            rid2 = create_rigging(
                api_key,
                model_url=file_to_data_uri(ap_glb),
                height_meters=float(args.height_meters),
            )
            report["rigTaskIdModelUrl"] = rid2
            rtask = poll_task(api_key, "rigging", rid2, timeout_s=1200)
            report["rigStatus"] = rtask.get("status")
            report["rigCredits"] = rtask.get("consumed_credits")
            if rtask.get("status") != "SUCCEEDED":
                report["error"] = task_error_message(rtask)
                (out / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print(json.dumps(report, indent=2))
                return 1
        url = (rtask.get("result") or {}).get("rigged_character_glb_url")
        if not url:
            report["error"] = "missing rigged_character_glb_url"
            (out / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            return 1
        download_url(url, rig_glb)
        report["riggedGlb"] = str(rig_glb.resolve()).replace("\\", "/")
    else:
        if not rig_glb.is_file():
            print(f"--skip-meshy but missing {rig_glb}", file=sys.stderr)
            return 2
        report["skippedMeshy"] = True
        report["riggedGlb"] = str(rig_glb.resolve()).replace("\\", "/")

    # Blender: extract mace + attach
    master_out = out / "master" / "hobgoblin_apose_mace_attach.glb"
    roles_out = out / "bone_roles_apose_mace.json"
    attach_report = out / "attach_report.json"
    master_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(args.blender),
        "--background",
        "--python",
        str(TOOL / "attach_mace_to_apose.py"),
        "--",
        "--body",
        str(rig_glb),
        "--mace-donor",
        str(args.mace_donor),
        "--output",
        str(master_out),
        "--roles-out",
        str(roles_out),
        "--report-out",
        str(attach_report),
    ]
    print("Running:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        report["error"] = f"attach_mace_to_apose failed rc={proc.returncode}"
        (out / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return proc.returncode

    report["masterGlb"] = str(master_out.resolve()).replace("\\", "/")
    report["boneRoles"] = str(roles_out.resolve()).replace("\\", "/")
    report["attachReport"] = str(attach_report.resolve()).replace("\\", "/")
    report["ok"] = True
    (out / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Also copy master into pose-pipeline master folder for fit configs
    dest_master = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/hobgoblin_apose_mace_attach.glb"
    dest_master.write_bytes(master_out.read_bytes())
    report["masterCopy"] = str(dest_master).replace("\\", "/")
    (out / "build_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
