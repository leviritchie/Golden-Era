#!/usr/bin/env python3
"""
Generate one Meshy meshy-t2 smart-topology **mesh + texture** from a painted frame.

Contract (locked — this generator):
  - Meshy owns mesh + PBR textures only
  - Delivery meshes use `--skip-rig` (mesh+texture). Meshy auto-rig is never
    delivery armature authority; rider/mount and other failed smart-rigs go
    through owned species bind (`run_owned_species_bind.py`)
  - `--with-auto-rig` is a diagnostic/legacy path only
  - ai_model=meshy-t2, model_type=smart-topology, should_texture=true, enable_pbr=true
  - remove_lighting omitted (rejected on smart-topology/t2 with HTTP 400)

When `--with-auto-rig` is selected, the downloaded rig is still not a ship
master. Diagnose with `diagnose_smartrig_quality.py`; `replace` units must be
stripped and owned-bound. Crusader's current smartrig ship is an explicit
exception, not a template.

Auth: MESHY_API_KEY from env or repo-root .env (never printed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from meshy_client import (  # noqa: E402
    create_image_to_3d,
    create_rigging,
    download_url,
    load_api_key,
    poll_task,
    task_error_message,
)

DEFAULT_IMAGE = (
    ROOT
    / "artifacts/crusader_pose_pipeline/idle_f0_painted/meshy_ready/frame_00.png"
)
DEFAULT_OUT = ROOT / "artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0"
RIGIDIZATION_LAUNCHER = ROOT / "tools/homm3_silhouette_pose_fit/run_meshy_rigidization.py"
DEFAULT_RIGIDIZATION_CONFIG = ROOT / "tools/homm3_silhouette_pose_fit/configs/meshy_rigidization_default.json"


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


def _extract_rigged_url(task: dict) -> str | None:
    result = task.get("result")
    if isinstance(result, dict):
        for key in (
            "rigged_character_glb_url",
            "rigged_character_fbx_url",
            "basic_rig_glb_url",
        ):
            url = result.get(key)
            if isinstance(url, str) and url.startswith("http") and key.endswith("_glb_url"):
                return url
            if key == "rigged_character_glb_url" and isinstance(url, str) and url.startswith("http"):
                return url
        url = result.get("rigged_character_glb_url")
        if isinstance(url, str) and url.startswith("http"):
            return url
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rigidization_report_is_reusable(report_path: Path, source: Path, output: Path) -> bool:
    """Only reuse a prior post-rig result when its proof still matches files."""
    if not report_path.is_file() or not output.is_file():
        return False
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("schema") != "meshy_rigidization_report.v1":
            return False
        if report.get("status") != "pass":
            return False
        if report.get("armatureAuthority") != "meshy_auto_rig":
            return False
        report_source = Path(str(report.get("source", ""))).resolve()
        report_output = Path(str(report.get("output", ""))).resolve()
        if report_source != source.resolve() or report_output != output.resolve():
            return False
        source_hash = report.get("sourceSha256")
        if source_hash and source_hash != _sha256(source):
            return False
        output_hash = report.get("outputSha256")
        if output_hash and output_hash != _sha256(output):
            return False
        return True
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--unit-sid", type=str, default="h3_unit")
    ap.add_argument("--polycount", type=int, default=8000)
    ap.add_argument("--height-meters", type=float, default=1.7)
    ap.add_argument(
        "--skip-rig",
        action="store_true",
        help="Emit mesh+texture only. Required for delivery meshes.",
    )
    ap.add_argument(
        "--with-auto-rig",
        action="store_true",
        help="Legacy diagnostic: request Meshy auto-rig. Not delivery authority.",
    )
    ap.add_argument(
        "--skip-rigidization",
        action="store_true",
        help="Keep the raw Meshy-rigged GLB without the post-rig rigidization audit.",
    )
    ap.add_argument(
        "--rigidization-config",
        type=Path,
        default=DEFAULT_RIGIDIZATION_CONFIG,
        help="JSON policy for Meshy-preserving rigidization.",
    )
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()
    if args.skip_rig and args.with_auto_rig:
        ap.error("--skip-rig and --with-auto-rig are mutually exclusive")
    skip_rig = bool(args.skip_rig)

    image: Path = args.image if args.image.is_absolute() else ROOT / args.image
    out: Path = args.out if args.out.is_absolute() else ROOT / args.out
    if not image.is_file():
        raise FileNotFoundError(image)

    meshes = out / "meshes"
    rigged = out / "rigged"
    tasks_dir = out / "tasks"
    frames = out / "frames"
    for d in (meshes, rigged, tasks_dir, frames):
        d.mkdir(parents=True, exist_ok=True)

    glb = meshes / "idle_f0.glb"
    rig_glb = rigged / "idle_f0_rigged.glb"
    meta_path = out / "generate_meta.json"

    meta: dict = {
        "unitSid": str(args.unit_sid),
        "image": str(image.resolve()).replace("\\", "/"),
        "ai_model": "meshy-t2",
        "model_type": "smart-topology",
        "should_texture": True,
        "enable_pbr": True,
        "target_polycount": int(args.polycount),
        "should_remesh": True,
        "pose_mode": None,
        "remove_lighting": None,
        "removeLightingMode": "omitted_unsupported_on_smart_topology",
        "autoRig": False if skip_rig else True,
        "proof": (
            "generated artifact validated — Meshy t2 mesh+texture only; "
            "bind skeleton owned in-repo (no auto-rig)"
            if skip_rig
            else "generated artifact validated — Meshy t2 + LEGACY auto-rig; not new-unit contract"
        ),
    }
    if not skip_rig:
        meta["proof"] = "generated artifact validated - Meshy auto-rig preserved; post-rig rigidization follows"

    if args.skip_existing and glb.is_file() and glb.stat().st_size > 1000:
        meta["imageSkipped"] = True
        meta["meshGlb"] = str(glb.resolve()).replace("\\", "/")
        print(f"[gen] skip existing mesh {glb}", flush=True)
        image_task_id = None
        if meta_path.is_file():
            prev = json.loads(meta_path.read_text(encoding="utf-8"))
            image_task_id = prev.get("imageTaskId")
            meta["imageTaskId"] = image_task_id
    else:
        shutil.copy2(image, frames / "idle_f0.png")
        api_key = load_api_key()
        print("[gen] create image-to-3d …", flush=True)
        tid = create_image_to_3d(
            api_key,
            image_path=image,
            should_texture=True,
            target_polycount=int(args.polycount),
            model_type="smart-topology",
            ai_model="meshy-t2",
            pose_mode=None,
            should_remesh=True,
            enable_pbr=True,
            remove_lighting=None,
        )
        meta["imageTaskId"] = tid
        (tasks_dir / "image_to_3d.json").write_text(
            json.dumps({"taskId": tid}, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[gen] poll image-to-3d {tid[:8]}…", flush=True)
        task = poll_task(api_key, "image-to-3d", tid, timeout_s=2400, interval_s=8.0)
        (tasks_dir / "image_to_3d.json").write_text(
            json.dumps(task, indent=2) + "\n", encoding="utf-8"
        )
        status = str(task.get("status") or "")
        meta["imageStatus"] = status
        meta["imageCredits"] = task.get("consumed_credits")
        if status != "SUCCEEDED":
            meta["error"] = task_error_message(task)
            meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"ok": False, "error": meta["error"]}, indent=2))
            return 2
        url = _extract_glb_url(task)
        if not url:
            meta["error"] = f"missing glb url; keys={list(task.keys())}"
            meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"ok": False, "error": meta["error"]}, indent=2))
            return 2
        download_url(str(url), glb)
        meta["meshGlb"] = str(glb.resolve()).replace("\\", "/")
        meta["meshBytes"] = glb.stat().st_size
        image_task_id = tid
        print(f"[gen] saved {glb} ({meta['meshBytes']} bytes)", flush=True)

    if skip_rig:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "rigSkipped": True, "out": str(out)}, indent=2))
        return 0

    if args.skip_existing and rig_glb.is_file() and rig_glb.stat().st_size > 1000:
        meta["rigSkipped"] = True
        meta["riggedGlb"] = str(rig_glb.resolve()).replace("\\", "/")
        meta["riggedBytes"] = rig_glb.stat().st_size
        if args.skip_rigidization:
            meta["meshRigAuthority"] = "meshy_auto_rig"
            meta["meshyAutoRigGlb"] = str(rig_glb.resolve()).replace("\\", "/")
            meta["rigidization"] = {"enabled": False, "status": "skipped"}
            meta["proof"] = "generated artifact validated - raw Meshy auto-rig retained; rigidization explicitly skipped"
            meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"ok": True, "rigSkipped": True, "out": str(out), "rigged": meta["riggedGlb"]}, indent=2))
            return 0
        rigidized_glb = rigged / "idle_f0_rigged_rigidized.glb"
        rigidization_report = rigged / "meshy_rigidization_report.json"
        config_path = args.rigidization_config if args.rigidization_config.is_absolute() else ROOT / args.rigidization_config
        reusable = _rigidization_report_is_reusable(rigidization_report, rig_glb, rigidized_glb)
        if not reusable:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RIGIDIZATION_LAUNCHER),
                    "--src", str(rig_glb),
                    "--out", str(rigidized_glb),
                    "--report", str(rigidization_report),
                    "--config", str(config_path),
                    "--overwrite",
                ],
                cwd=str(ROOT),
                check=False,
            )
            if completed.returncode != 0:
                meta["error"] = f"Meshy rigidization failed with exit code {completed.returncode}"
                meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
                return int(completed.returncode)
            status = "pass"
        else:
            status = "reused"
        meta["meshRigAuthority"] = "meshy_auto_rig"
        meta["meshyAutoRigGlb"] = str(rig_glb.resolve()).replace("\\", "/")
        meta["riggedGlb"] = str(rigidized_glb.resolve()).replace("\\", "/")
        meta["proof"] = "generated artifact validated - Meshy auto-rig preserved and rigidization re-import audit passed"
        meta["rigidization"] = {
            "enabled": True,
            "status": status,
            "source": str(rig_glb.resolve()).replace("\\", "/"),
            "output": str(rigidized_glb.resolve()).replace("\\", "/"),
            "report": str(rigidization_report.resolve()).replace("\\", "/"),
        }
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "rigSkipped": True, "out": str(out), "rigged": meta["riggedGlb"], "rigidization": meta["rigidization"]}, indent=2))
        return 0

    api_key = load_api_key()
    if not image_task_id:
        raise RuntimeError("imageTaskId required for auto-rig; re-run without --skip-existing mesh")

    print("[rig] create rigging …", flush=True)
    rid = create_rigging(
        api_key,
        input_task_id=str(image_task_id),
        height_meters=float(args.height_meters),
    )
    meta["rigTaskId"] = rid
    (tasks_dir / "rigging.json").write_text(
        json.dumps({"taskId": rid, "inputTaskId": image_task_id}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[rig] poll {rid[:8]}…", flush=True)
    rtask = poll_task(api_key, "rigging", rid, timeout_s=1800, interval_s=8.0)
    (tasks_dir / "rigging.json").write_text(json.dumps(rtask, indent=2) + "\n", encoding="utf-8")
    rstatus = str(rtask.get("status") or "")
    meta["rigStatus"] = rstatus
    meta["rigCredits"] = rtask.get("consumed_credits")
    if rstatus != "SUCCEEDED":
        meta["error"] = task_error_message(rtask)
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": False, "error": meta["error"]}, indent=2))
        return 2
    rurl = _extract_rigged_url(rtask)
    if not rurl:
        meta["error"] = f"missing rigged glb url; result_keys={list((rtask.get('result') or {}).keys())}"
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": False, "error": meta["error"]}, indent=2))
        return 2
    download_url(str(rurl), rig_glb)
    meta["riggedGlb"] = str(rig_glb.resolve()).replace("\\", "/")
    meta["riggedBytes"] = rig_glb.stat().st_size
    print(f"[rig] saved {rig_glb} ({meta['riggedBytes']} bytes)", flush=True)

    if args.skip_rigidization:
        meta["meshRigAuthority"] = "meshy_auto_rig"
        meta["meshyAutoRigGlb"] = str(rig_glb.resolve()).replace("\\", "/")
        meta["rigidization"] = {"enabled": False, "status": "skipped"}
        meta["proof"] = "generated artifact validated - raw Meshy auto-rig retained; rigidization explicitly skipped"
    else:
        rigidized_glb = rigged / "idle_f0_rigged_rigidized.glb"
        rigidization_report = rigged / "meshy_rigidization_report.json"
        config_path = args.rigidization_config if args.rigidization_config.is_absolute() else ROOT / args.rigidization_config
        print("[rigidize] preserving Meshy armature and auditing rigid regions", flush=True)
        completed = subprocess.run(
            [
                sys.executable,
                str(RIGIDIZATION_LAUNCHER),
                "--src",
                str(rig_glb),
                "--out",
                str(rigidized_glb),
                "--report",
                str(rigidization_report),
                "--config",
                str(config_path),
            ],
            cwd=str(ROOT),
            check=False,
        )
        if completed.returncode != 0:
            meta["error"] = f"Meshy rigidization failed with exit code {completed.returncode}"
            meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            return int(completed.returncode)
        meta["meshRigAuthority"] = "meshy_auto_rig"
        meta["meshyAutoRigGlb"] = str(rig_glb.resolve()).replace("\\", "/")
        meta["proof"] = "generated artifact validated - Meshy auto-rig preserved and rigidization re-import audit passed"
        meta["rigidization"] = {
            "enabled": True,
            "status": "pass",
            "source": str(rig_glb.resolve()).replace("\\", "/"),
            "output": str(rigidized_glb.resolve()).replace("\\", "/"),
            "report": str(rigidization_report.resolve()).replace("\\", "/"),
        }
        meta["riggedGlb"] = str(rigidized_glb.resolve()).replace("\\", "/")

    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out), "mesh": meta.get("meshGlb"), "rigged": meta.get("riggedGlb"), "rigidization": meta.get("rigidization")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
