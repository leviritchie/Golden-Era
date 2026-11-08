#!/usr/bin/env python3
"""
Smoke: CHGOBL group-11 frame_00 → Meshy generate+rig texture matrix → nearest-bone retarget → preview.

Auth: MESHY_API_KEY from env or repo-root .env.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
DEFAULT_BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
SPRITE = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11/frame_00.png"
MASTER = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/Meshy_AI_Character_output.glb"
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_meshy_frame00_smoke"

sys.path.insert(0, str(TOOL))
from meshy_client import (  # noqa: E402
    create_image_to_3d,
    create_rigging,
    download_url,
    file_to_data_uri,
    load_api_key,
    poll_task,
    task_error_message,
)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print("Running:", " ".join(str(c) for c in cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True)
    for line in (proc.stdout or "").splitlines():
        if any(k in line for k in ("ok", "Error", "Traceback", "texture_for_rig", "meshy", "mapped")):
            print(line, flush=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-6000:] if proc.stderr else "")
        sys.stderr.write((proc.stdout or "")[-4000:])
        raise RuntimeError(f"command failed rc={proc.returncode}")


def _blender_texture(blender: Path, mode: str, inp: Path, out: Path, sprite: Path, master: Path) -> None:
    cmd = [
        str(blender),
        "--background",
        "--python",
        str(TOOL / "texture_for_rig.py"),
        "--",
        "--mode",
        mode,
        "--input",
        str(inp),
        "--output",
        str(out),
    ]
    if mode == "sprite":
        cmd.extend(["--sprite", str(sprite)])
    if mode == "master":
        cmd.extend(["--master", str(master)])
    _run(cmd)


def _extract_glb_url(task: dict) -> str | None:
    """Fail-closed URL extraction for image-to-3D task objects."""
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


def _try_rig_input_task(api_key: str, task_id: str, out_dir: Path, label: str) -> dict:
    rec: dict = {"option": label, "rigInput": "input_task_id", "inputTaskId": task_id}
    try:
        rid = create_rigging(api_key, input_task_id=task_id, height_meters=1.7)
        rec["rigTaskId"] = rid
        task = poll_task(api_key, "rigging", rid, timeout_s=900)
        rec["status"] = task.get("status")
        rec["consumedCredits"] = task.get("consumed_credits")
        if task.get("status") != "SUCCEEDED":
            rec["ok"] = False
            rec["error"] = task_error_message(task)
            return rec
        url = (task.get("result") or {}).get("rigged_character_glb_url")
        if not url:
            rec["ok"] = False
            rec["error"] = "SUCCEEDED but missing rigged_character_glb_url"
            return rec
        dest = out_dir / f"{label}_rigged.glb"
        download_url(url, dest)
        rec["ok"] = True
        rec["riggedGlb"] = str(dest).replace("\\", "/")
        return rec
    except Exception as e:
        rec["ok"] = False
        rec["error"] = str(e)
        return rec


def _try_rig_model_url(api_key: str, glb: Path, out_dir: Path, label: str) -> dict:
    rec: dict = {"option": label, "rigInput": "model_url", "modelGlb": str(glb).replace("\\", "/")}
    try:
        rid = create_rigging(api_key, model_url=file_to_data_uri(glb), height_meters=1.7)
        rec["rigTaskId"] = rid
        task = poll_task(api_key, "rigging", rid, timeout_s=900)
        rec["status"] = task.get("status")
        rec["consumedCredits"] = task.get("consumed_credits")
        if task.get("status") != "SUCCEEDED":
            rec["ok"] = False
            rec["error"] = task_error_message(task)
            return rec
        url = (task.get("result") or {}).get("rigged_character_glb_url")
        if not url:
            rec["ok"] = False
            rec["error"] = "SUCCEEDED but missing rigged_character_glb_url"
            return rec
        dest = out_dir / f"{label}_rigged.glb"
        download_url(url, dest)
        rec["ok"] = True
        rec["riggedGlb"] = str(dest).replace("\\", "/")
        return rec
    except Exception as e:
        rec["ok"] = False
        rec["error"] = str(e)
        return rec


def run_texture_matrix(api_key: str, blender: Path, out_dir: Path) -> tuple[dict | None, list[dict]]:
    """
    Test texture options in plan order. Stop at first SUCCEEDED rig.
    Returns (winning_record_or_None, all_attempt_records).
    """
    attempts: list[dict] = []
    gen_dir = out_dir / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)

    # Option 1: Meshy textured generate → rig via input_task_id
    print("=== Option 1: Meshy textured generate + input_task_id rig ===", flush=True)
    opt1: dict = {"option": "1_meshy_textured"}
    try:
        tid = create_image_to_3d(
            api_key,
            image_path=SPRITE,
            should_texture=True,
            target_polycount=4000,
            model_type="smart-topology",
            ai_model="meshy-t2",
        )
        opt1["imageTaskId"] = tid
        task = poll_task(api_key, "image-to-3d", tid, timeout_s=1200)
        opt1["imageStatus"] = task.get("status")
        opt1["imageCredits"] = task.get("consumed_credits")
        if task.get("status") != "SUCCEEDED":
            opt1["ok"] = False
            opt1["error"] = task_error_message(task)
            attempts.append(opt1)
        else:
            glb_url = _extract_glb_url(task)
            if glb_url:
                download_url(glb_url, gen_dir / "opt1_textured.glb")
                opt1["generatedGlb"] = str((gen_dir / "opt1_textured.glb").resolve()).replace("\\", "/")
            else:
                opt1["glbUrlWarning"] = f"no glb url in task keys={list(task.keys())}"
            rig_rec = _try_rig_input_task(api_key, tid, gen_dir, "opt1")
            opt1.update({k: v for k, v in rig_rec.items() if k != "option"})
            opt1["ok"] = bool(rig_rec.get("ok"))
            attempts.append(opt1)
            if opt1["ok"]:
                return opt1, attempts
    except Exception as e:
        opt1["ok"] = False
        opt1["error"] = str(e)
        attempts.append(opt1)

    # Shared untextured generate for options 2–4
    print("=== Shared untextured generate for options 2–4 ===", flush=True)
    untex: dict = {"option": "untextured_generate"}
    untex_glb = gen_dir / "untextured.glb"
    try:
        tid_u = create_image_to_3d(
            api_key,
            image_path=SPRITE,
            should_texture=False,
            target_polycount=4000,
            model_type="smart-topology",
            ai_model="meshy-t2",
        )
        untex["imageTaskId"] = tid_u
        task_u = poll_task(api_key, "image-to-3d", tid_u, timeout_s=1200)
        untex["imageStatus"] = task_u.get("status")
        untex["imageCredits"] = task_u.get("consumed_credits")
        if task_u.get("status") != "SUCCEEDED":
            untex["ok"] = False
            untex["error"] = task_error_message(task_u)
            attempts.append(untex)
            return None, attempts
        glb_url = _extract_glb_url(task_u)
        if not glb_url:
            raise RuntimeError(f"untextured SUCCEEDED but no glb url; keys={list(task_u.keys())} result_keys={list((task_u.get('result') or {}).keys())}")
        download_url(glb_url, untex_glb)
        untex["ok"] = True
        untex["generatedGlb"] = str(untex_glb.resolve()).replace("\\", "/")
        attempts.append(untex)
    except Exception as e:
        untex["ok"] = False
        untex["error"] = str(e)
        attempts.append(untex)
        return None, attempts

    for label, mode in (
        ("2_sprite_albedo", "sprite"),
        ("3_master_project", "master"),
        ("4_solid_limbs", "solid"),
    ):
        print(f"=== Option {label}: offline {mode} texture + model_url rig ===", flush=True)
        rec: dict = {"option": label, "textureMode": mode}
        try:
            packed = gen_dir / f"{label}_textured.glb"
            _blender_texture(blender, mode, untex_glb, packed, SPRITE, MASTER)
            rec["texturedGlb"] = str(packed.resolve()).replace("\\", "/")
            rig_rec = _try_rig_model_url(api_key, packed, gen_dir, label)
            rec.update({k: v for k, v in rig_rec.items() if k not in {"option"}})
            rec["ok"] = bool(rig_rec.get("ok"))
            attempts.append(rec)
            if rec["ok"]:
                return rec, attempts
        except Exception as e:
            rec["ok"] = False
            rec["error"] = str(e)
            attempts.append(rec)

    return None, attempts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--blender", type=Path, default=Path(os.environ.get("HOMM3_POSE_FIT_BLENDER", str(DEFAULT_BLENDER))))
    ap.add_argument("--skip-meshy", action="store_true", help="Reuse existing winning rigged GLB if present")
    ap.add_argument("--max-dist", type=float, default=0.35)
    args = ap.parse_args()

    if not SPRITE.is_file():
        print(f"missing sprite: {SPRITE}", file=sys.stderr)
        return 2
    if not MASTER.is_file():
        print(f"missing master: {MASTER}", file=sys.stderr)
        return 2
    if not args.blender.is_file():
        print(f"missing blender: {args.blender}", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    api_key = load_api_key()

    matrix_path = OUT / "texture_matrix_report.json"
    winner = None
    attempts: list[dict] = []

    if args.skip_meshy and matrix_path.is_file():
        prior = json.loads(matrix_path.read_text(encoding="utf-8"))
        attempts = prior.get("attempts") or []
        for a in attempts:
            if a.get("ok") and a.get("riggedGlb") and Path(a["riggedGlb"]).is_file():
                winner = a
                break
        print(f"reuse winner={winner.get('option') if winner else None}", flush=True)
    else:
        winner, attempts = run_texture_matrix(api_key, args.blender, OUT)
        matrix_path.write_text(
            json.dumps(
                {
                    "frame": "canonical_group_11/frame_00.png",
                    "attempts": attempts,
                    "winner": winner.get("option") if winner else None,
                    "proof": "generated artifact validated — Meshy texture-matrix smoke; not OE runtime proven",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    if not winner or not winner.get("riggedGlb"):
        verdict = {
            "verdict": "meshy_rig_failed_all_texture_options",
            "attempts": attempts,
            "proof": "generated artifact validated — all texture options failed auto-rig",
        }
        (OUT / "pilot_verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
        print(json.dumps(verdict, indent=2))
        return 1

    donor = Path(winner["riggedGlb"])
    posed = OUT / "master_frame00_retargeted.glb"
    bone_map = OUT / "bone_map.json"
    fit_report = OUT / "fit_report.json"

    _run(
        [
            str(args.blender),
            "--background",
            "--python",
            str(TOOL / "retarget_nearest_bones.py"),
            "--",
            "--master",
            str(MASTER),
            "--donor",
            str(donor),
            "--output",
            str(posed),
            "--map-json",
            str(bone_map),
            "--report",
            str(fit_report),
            "--max-dist",
            str(args.max_dist),
        ]
    )

    preview_dir = OUT / "preview"
    frames_dir = preview_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    cam_json = OUT / "camera.json"
    cam_json.write_text(
        json.dumps({"distance": 3.0, "height": 0.85, "orthoScale": 2.6, "rootYawDeg": 0.0}, indent=2),
        encoding="utf-8",
    )
    mesh_png = frames_dir / "mesh_00.png"
    _run(
        [
            str(args.blender),
            "--background",
            "--python",
            str(TOOL / "render_smoke_preview.py"),
            "--",
            "--master-posed",
            str(posed),
            "--output-png",
            str(mesh_png),
            "--camera-json",
            str(cam_json),
        ]
    )

    from PIL import Image, ImageDraw

    sprite = Image.open(SPRITE).convert("RGBA")
    mesh_im = Image.open(mesh_png).convert("RGBA")
    side = 512
    canvas_s = Image.new("RGBA", (side, side), (20, 20, 20, 255))
    sp = sprite.copy()
    sp.thumbnail((side - 40, side - 40), Image.NEAREST)
    canvas_s.paste(sp, ((side - sp.width) // 2, (side - sp.height) // 2), sp)
    canvas_m = mesh_im.resize((side, side), Image.BILINEAR)
    combo = Image.new("RGBA", (side * 2 + 24, side + 48), (10, 10, 10, 255))
    draw = ImageDraw.Draw(combo)
    draw.text((12, 8), "HoMM3 sprite frame 00", fill=(220, 220, 220, 255))
    draw.text((side + 36, 8), "Master nearest-bone retarget", fill=(220, 220, 220, 255))
    combo.paste(canvas_s, (8, 36))
    combo.paste(canvas_m, (side + 16, 36))
    side_path = frames_dir / "side_00.png"
    combo.convert("RGB").save(side_path)
    gif_path = preview_dir / "frame00_side_by_side.gif"
    combo.convert("RGB").save(gif_path, save_all=True, duration=800, loop=0)

    verdict = {
        "unitSid": "h3_hobgoblin",
        "clipId": "attack_g11_frame00_smoke",
        "verdict": "tooling_ok_attack_read_unproven",
        "winningTextureOption": winner.get("option"),
        "riggedGlb": winner.get("riggedGlb"),
        "retargetedGlb": str(posed).replace("\\", "/"),
        "textureMatrixReport": str(matrix_path).replace("\\", "/"),
        "preview": str((preview_dir / "frame00_side_by_side.gif").resolve()).replace("\\", "/"),
        "proof": "generated artifact validated — Meshy per-frame smoke + nearest-bone retarget; attack-read not proven",
        "attemptsSummary": [
            {"option": a.get("option"), "ok": a.get("ok"), "error": a.get("error"), "credits": a.get("consumedCredits") or a.get("imageCredits")}
            for a in attempts
        ],
    }
    (OUT / "pilot_verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
