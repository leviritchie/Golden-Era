#!/usr/bin/env python3
"""Regenerate a unit's Meshy mesh whose identity is wrong (e.g. h3_centaur held the captain design).

    python tools/homm3_meshy_frame_pose/regenerate_wrong_identity.py --start --unit h3_centaur [--unit ...]
    python tools/homm3_meshy_frame_pose/regenerate_wrong_identity.py --poll  --unit h3_centaur [--unit ...]
    ... --start --unit U --source prepared_concept.png --texture-prompt "..." --reason "..."   (one unit)

Source: artifacts/creature_aaa_3d_upscale/<unit>.png (the unit's concept image), or --source (a prepared
concept, e.g. an edit from meshy_restyle.py concept-edit); --texture-prompt adds Meshy texture guidance. Policy: the same
Meshy-7 settings as generate_missing_meshy7.py. Writes artifacts/meshy_downloads/identity_regen/<unit>/
(source.png, tasks/image_to_3d.json, mesh.glb, textures, generate_meta.json). A queued or finished
task is never re-created, so a rerun of --start cannot be charged twice. Installing the mesh as
<unit>_smartrigged.glb is a separate step (tools/homm3_def_retarget/install_mesh.py --force).
Proof tier: generated artifact.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_missing_meshy7 as G  # noqa: E402
from meshy_client import create_image_to_3d, load_api_key, poll_task  # noqa: E402,F401

OUT = ROOT / "artifacts/meshy_downloads/identity_regen"
SRC = ROOT / "artifacts/creature_aaa_3d_upscale"


def start(api_key, sid, source=None, texture_prompt=None, reason=None):
    dest = OUT / sid
    (dest / "tasks").mkdir(parents=True, exist_ok=True)
    tf = dest / "tasks/image_to_3d.json"
    if tf.is_file():
        meta = json.loads(tf.read_text(encoding="utf-8"))
        return {"unitSid": sid, "status": "already_queued", "taskId": meta.get("taskId") or meta.get("id")}
    src = Path(source) if source else SRC / f"{sid}.png"
    if not src.is_file():
        raise SystemExit(f"{sid}: no concept image {src}")
    shutil.copy2(src, dest / "source.png")
    task_id = create_image_to_3d(api_key, image_path=dest / "source.png", should_texture=True, target_polycount=None,
                                 model_type="standard", ai_model="meshy-7", should_remesh=True, enable_pbr=True,
                                 remove_lighting=False, texture_resolution="4k", decimation_mode=3, image_enhancement=False,
                                 texture_prompt=texture_prompt)
    tf.write_text(json.dumps({"taskId": task_id, "unitSid": sid, "source": src.as_posix(), "texturePrompt": texture_prompt,
                              "reason": reason or "wrong identity in meshy_downloads/<unit>_smartrigged.glb"},
                             indent=2) + "\n", encoding="utf-8")
    return {"unitSid": sid, "status": "queued", "taskId": task_id}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--poll", action="store_true")
    ap.add_argument("--unit", action="append", required=True)
    ap.add_argument("--source")
    ap.add_argument("--texture-prompt")
    ap.add_argument("--reason")
    a = ap.parse_args()
    if a.start == a.poll:
        ap.error("select exactly one of --start or --poll")
    if (a.source or a.texture_prompt or a.reason) and len(a.unit) != 1:
        ap.error("--source/--texture-prompt/--reason apply to exactly one --unit")
    key = load_api_key()
    G._unit_dir = lambda sid: OUT / sid  # reuse the proven poll/download path, pointed at this lane's folder
    for sid in a.unit:
        r = start(key, sid, a.source, a.texture_prompt, a.reason) if a.start else G._poll_one(key, {"unitSid": sid})
        print(json.dumps(r, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
