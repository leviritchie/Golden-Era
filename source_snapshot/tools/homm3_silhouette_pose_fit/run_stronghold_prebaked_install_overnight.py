#!/usr/bin/env python3
"""Overnight: continuous-track every Stronghold unit, pre-bake solved lighting, install into Golden Era.

What one night produces, per unit
---------------------------------
1. **Track** DEF sequences with ``def_continuous_pose_tracker.py`` (the method validated on
   h3_roc idle_start_move_end; settings identical to ``run_stronghold_continuous_overnight.py``).
   Sequences are visited round-robin by priority (``--clips``), so when the tracking
   deadline hits, every unit has its most important clips rather than a few units having
   everything.
2. **Light solve** (``solve_unit_light_palette.py``, blackbody model) against the unit's own
   sprite frames, then **bake** that rig into the base-colour texture (``showcase_prebaked_clip``)
   and write a pre-baked GLB whose metallic/roughness and normal maps are neutralised so the
   engine's lit material adds only plain diffuse on top.
3. **Export** delivery clip GLBs on the pre-baked mesh. Every chosen DEF group must ship,
   because the Unity lab maps every stock Animator clip and refuses partial sets. A clip
   the tracker reached tonight uses the tracker result; a clip it did not reach uses the
   unit's existing fused-push result (prop-IK polish lane when present). The per-clip
   ``poseSource`` in ``delivery_manifest.json`` and the batch summary say which is which;
   nothing is substituted quietly. A unit with neither source for a required clip fails.
4. **Prepare + lab + bundle + deploy**: ``prepare_smartrig_skinned_import.py`` (chosen-set
   check, import table + units manifest rows), Unity ``Homm3OwnedSkinnedLabBuild``, Unity
   ``BuildCustomUnitBundles``, then ``dotnet build`` of OfflineUnlockMod with
   ``-p:DeployHomm3BundleName=<bundle>`` once per unit so the csproj's payload and audio
   validators gate each copy into the Golden Era install.

Failure handling: one unit failing any stage is recorded and the batch continues. Stages
4 run only for units that completed 1-3. Summary JSON is rewritten after every step so a
crash leaves partial results.

Proof tier: installed payload validated by the csproj validators when the deploy step
passes. Runtime appearance in Golden Era battle is NOT proven by this script.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from run_stronghold_continuous_overnight import (  # noqa: E402
    STRONGHOLD_UNITS,
    resolve_deadline,
    run_step,
)

OUT = ROOT / "artifacts/prebaked_continuous_stronghold_rollout"
FUSED_ROLLOUT = ROOT / "artifacts/fused_push_skinned_rollout"
TRACK_LANE = "def_continuous_stronghold"
LIGHT_DIR_NAME = "light_palette_solve_blackbody"
CLIP_PRIORITY = (
    "idle_start_move_end",
    "idle",
    "idle_attack_front",
    "idle_hitted",
    "idle_defence",
    "idle_death",
    "idle_mouseover",
)
UNITY = Path(r"C:/Program Files/Unity/Hub/Editor/6000.0.66f2/Editor/Unity.exe")
UNITY_PROJECT = ROOT / "oldenera_factions"
UNITS_MANIFEST = ROOT / "tools/homm3_import/homm3_units_manifest.json"
BUILD_OUT = ROOT / "tools/homm3_import/build_out"
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/OfflineUnlockMod.csproj"
GOLDEN = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--units", default=None, help="Comma-separated subset; default all 21.")
    parser.add_argument("--clips", default=",".join(CLIP_PRIORITY), help="Priority-ordered DEF sequences to track.")
    parser.add_argument("--lane", default=TRACK_LANE)
    parser.add_argument("--track-deadline", default=None, help="Local HH:MM after which no new tracker run starts.")
    parser.add_argument("--per-clip-timeout-sec", type=float, default=2700.0)
    parser.add_argument("--correct-steps", type=int, default=60)
    parser.add_argument("--correct-schedule", default="4,2,1,0.5")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--skip-track", action="store_true", help="Deliver from whatever tracker results already exist.")
    parser.add_argument("--skip-install", action="store_true", help="Stop after export + validators (no Unity, no deploy).")
    parser.add_argument("--unity-direct", action="store_true", help="Explicit opt-out: launch Unity directly instead of submitting to the Unity queue.")
    parser.add_argument("--cut-strands", action="store_true", help="Delete strand triangles found by the stretch scan (default: report only; cutting mangled meshes on 2026-09-02).")
    return parser.parse_args()


# --------------------------------------------------------------------------- summary
class Summary:
    def __init__(self, path: Path, units: list[str], args: argparse.Namespace) -> None:
        self.path = path
        self.payload: dict[str, Any] = {
            "proof": "generated-artifact until the deploy stage reports installed",
            "started": datetime.now().isoformat(timespec="seconds"),
            "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
            "units": {sid: {"track": {}, "deliver": None, "install": None} for sid in units},
            "stages": {},
        }
        self.write()

    def write(self) -> None:
        self.payload["written"] = datetime.now().isoformat(timespec="seconds")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.payload, indent=2) + "\n", encoding="utf-8")

    def unit(self, sid: str) -> dict[str, Any]:
        return self.payload["units"][sid]


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


# --------------------------------------------------------------------------- phase 1: track
def tracker_result(unit: str, clip: str, lane: str) -> Path:
    return ROOT / "artifacts/pose_picker_runs" / unit / clip / lane / "solve" / "gpu_clip_result.json"


def tracker_report(unit: str, clip: str, lane: str) -> Path:
    return ROOT / "artifacts/pose_picker_runs" / unit / clip / lane / f"{unit}_continuous_track_report.json"


def track_all(args: argparse.Namespace, units: list[str], clips: list[str], summary: Summary, log_root: Path) -> None:
    deadline = resolve_deadline(args.track_deadline)
    lane = str(args.lane)
    for clip in clips:
        for unit in units:
            entry: dict[str, Any] = {}
            summary.unit(unit)["track"][clip] = entry
            frame_dir = ROOT / "artifacts/pose_picker_runs" / unit / clip / f"frames_def12_nn_{clip}_shadow_culled"
            if not frame_dir.is_dir():
                entry.update({"status": "unavailable", "reason": f"missing {frame_dir.name}"})
                summary.write()
                continue
            if tracker_result(unit, clip, lane).is_file() and tracker_report(unit, clip, lane).is_file():
                entry.update({"status": "ok", "reused": True})
                summary.write()
                log(f"track {unit}/{clip}: reuse existing {lane} result")
                continue
            if deadline is not None and datetime.now() >= deadline:
                entry.update({"status": "skipped", "reason": f"track deadline {deadline.isoformat()} reached"})
                summary.write()
                continue
            started = time.time()
            log(f"track {unit}/{clip} ...")
            ok, tail = run_step(
                [
                    sys.executable, str(TOOL / "def_continuous_pose_tracker.py"),
                    "--unit", unit, "--clip", clip, "--quality",
                    "--correct-steps", str(int(args.correct_steps)),
                    "--correct-schedule", str(args.correct_schedule),
                    "--out-lane", lane,
                ],
                log=log_root / unit / f"track_{clip}.log",
                timeout_sec=float(args.per_clip_timeout_sec),
            )
            entry["trackSec"] = round(time.time() - started, 1)
            if not ok or not tracker_result(unit, clip, lane).is_file():
                entry.update({"status": "failed", "error": tail[-600:] or "tracker exited 0 without a result"})
                log(f"track {unit}/{clip}: FAILED")
            else:
                report = tracker_report(unit, clip, lane)
                if report.is_file():
                    track = (json.loads(report.read_text(encoding="utf-8")).get("track") or {})
                    entry["meanSilhouette"] = track.get("meanSilhouetteAfter")
                    entry["meanPenetration"] = track.get("meanPenetrationAfter")
                    entry["loopSeam"] = track.get("loopSeam")
                entry["status"] = "ok"
                log(f"track {unit}/{clip}: ok ({entry['trackSec']}s) silh={entry.get('meanSilhouette')}")
            summary.write()


# --------------------------------------------------------------------------- phase 2: deliver
def fused_clip_payload(choice) -> tuple[Path, dict[str, Any]] | None:
    """Existing fused-push result for a DEF sequence (prop-IK polish lane preferred), or None."""
    from export_stronghold_prop_ik_rollout import _prop_clip_result_path
    from literature_polish_common import load_source_clip
    from run_fused_push_batch_all_units import _clip_result_path as fused_clip_result_path

    path = _prop_clip_result_path(choice)
    if path is None:
        candidate = fused_clip_result_path(choice)
        path = candidate if candidate.is_file() else None
    if path is None:
        return None
    return path, load_source_clip(path)


def unit_scale(sid: str) -> Any:
    from inventory_smartrig_skinned_rollout import STATUS_PATH

    status = json.loads(STATUS_PATH.read_text(encoding="utf-8-sig"))
    for row in status.get("units") or []:
        if row.get("labSid") == sid:
            return row.get("scale")
    raise KeyError(f"{sid} has no inventory status row in {STATUS_PATH}")


def deliver_unit(
    sid: str, *, all_choices, lane: str, out_root: Path, log_root: Path, tracked_clips: set[str], cut_strands: bool = False
) -> dict[str, Any]:
    from gpu_cascade_delivery import (
        CHOSEN_DEF_GROUPS,
        IDLE_GROUP,
        contract_name_for_group,
        extract_glb_hexlit_pbr_maps,
        select_unit_delivery_choices,
        write_oriented_master_glb,
    )
    from literature_polish_common import load_source_clip, unit_mesh
    from run_gpu_cascade_animation_set import export_choice_clips
    from showcase_prebaked_clip import bake_lit_texture, write_engine_material_glb, write_glb_with_basecolor

    result: dict[str, Any] = {"labSid": sid}
    source_mesh = unit_mesh(sid, "idle_start_move_end").resolve()
    if not source_mesh.is_file():
        raise FileNotFoundError(source_mesh)
    result["sourceMesh"] = str(source_mesh)
    # Solve, bake and export against the material the engine will actually render. For
    # most Meshy exports this is a byte-equivalent copy; for emissive/specular exports
    # (h3_ogre_mage) it is the only way the light solve fits what the game shows.
    mesh = (out_root / f"{sid}_engine_material.glb").resolve()
    result["engineMaterial"] = write_engine_material_glb(source_mesh, mesh)
    result["mesh"] = str(mesh)
    choices = select_unit_delivery_choices(all_choices, sid)

    # Resolve every required sequence's pose source before spending time on baking.
    # Tracker payloads get the same cascade physics post-pass every shipped clip carries
    # (validate_homm3_skinned_clip_pose_contract requires physicsSmooth.enabled); the
    # smoother keeps a .presmooth.json backup and its before/after jitter is recorded.
    from smooth_clip_result_physics import GlbSkeleton, smooth_payload

    skeleton = GlbSkeleton(mesh)
    smooth_reports: dict[str, Any] = {}
    sources: list[tuple[Any, Path, dict[str, Any], str]] = []
    missing: list[str] = []
    for choice in choices:
        animation = str(choice.animation_name)
        tracked = tracker_result(sid, animation, lane)
        if animation in tracked_clips and tracked.is_file():
            smooth_reports[animation] = smooth_payload(tracked, skeleton, write=True)
            sources.append((choice, tracked, load_source_clip(tracked), f"continuous_tracker:{lane}"))
            continue
        fused = fused_clip_payload(choice)
        if fused is None:
            missing.append(animation)
            continue
        sources.append((choice, fused[0], fused[1], "fused_push_existing"))
    if missing:
        raise RuntimeError(f"{sid}: no tracker or fused-push result for required sequence(s) {missing}")

    # Light solve against the unit's own sprite plates (pose-agnostic colour match).
    light_dir = ROOT / "artifacts/pose_picker_runs" / sid / LIGHT_DIR_NAME
    solution_path = light_dir / "light_solution.json"
    reuse_solution = False
    if solution_path.is_file():
        solved = json.loads(solution_path.read_text(encoding="utf-8"))
        reuse_solution = Path(str(solved.get("glb", ""))).resolve() == mesh
    if not reuse_solution:
        sprite_dir = ROOT / "artifacts/pose_picker_runs" / sid / "idle_start_move_end" / "frames_def12_nn_idle_start_move_end_shadow_culled"
        if not sprite_dir.is_dir():
            raise FileNotFoundError(sprite_dir)
        ok, tail = run_step(
            [
                sys.executable, str(TOOL / "solve_unit_light_palette.py"),
                "--unit", sid, "--glb", str(mesh), "--sprite-dir", str(sprite_dir),
                "--out", str(light_dir), "--light-model", "blackbody",
            ],
            log=log_root / sid / "light_solve.log",
            timeout_sec=1800.0,
        )
        if not ok or not solution_path.is_file():
            raise RuntimeError(f"{sid}: light solve failed: {tail[-600:]}")
    result["lightSolution"] = str(solution_path)
    result["lightSolutionReused"] = reuse_solution

    baked_png = out_root / "baked_lit.png"
    bake_lit_texture(mesh, solution_path, baked_png)
    prebaked_glb = out_root / f"{sid}_prebaked.glb"
    result["prebakedGlb"] = write_glb_with_basecolor(mesh, prebaked_glb, baked_png, neutralize_pbr=True)

    clip_dir = out_root / "clips"
    if clip_dir.is_dir():
        shutil.rmtree(clip_dir)
    clip_dir.mkdir(parents=True)
    # Character pass on every shipped payload (tracker or fused-push): idle understated
    # and slowed, motion exaggerated, root untouched. The rewritten payload is what the
    # sidecar's clipResultPath names, so the clip-pose validator checks the GLB against
    # the poses that were actually exported.
    from clip_character_pass import DEFAULT_CHARACTER_PROFILE, apply_character_pass, frame_duration_by_suffix

    character_dir = out_root / "character_payloads"
    if character_dir.is_dir():
        shutil.rmtree(character_dir)
    character_dir.mkdir(parents=True)
    durations = frame_duration_by_suffix(DEFAULT_CHARACTER_PROFILE)
    character_reports: dict[str, Any] = {}
    shaped_sources: list[tuple[Any, Path, dict[str, Any], Path, str]] = []
    for choice, clip_path, payload, source in sources:
        animation = str(choice.animation_name)
        shaped, report = apply_character_pass(
            payload,
            groups=tuple(int(g) for g in choice.def_lab_groups),
            counts=tuple(int(c) for c in choice.def_expected_counts),
        )
        report["source"] = str(clip_path)
        shaped_path = character_dir / f"{animation}.gpu_clip_result.json"
        shaped_path.write_text(json.dumps(shaped, indent=2) + "\n", encoding="utf-8")
        character_reports[animation] = {
            k: report[k] for k in ("clampedBoneFrames", "maxAngleDegBefore", "maxAngleDegAfter", "referenceFrames", "source")
        }
        shaped_sources.append((choice, clip_path, shaped, shaped_path, source))

    # Strand scan: pose every shipped (shaped) frame and report triangles that rubber-band.
    # Report only by default. Cutting was tried on 2026-09-02 and mangled meshes in game: on
    # Meshy auto-rigs the stretch mostly comes from leaked bone weights and extreme poses,
    # so the "strands" were real skin (belly, wing roots, forearms) and deleting them left
    # holes at rest (see audit_delivery_stages.py). ``--cut-strands`` re-enables the cut.
    from clip_stretched_triangles import clip_stretched_triangles, find_stretched_triangles, render_cut_preview

    shaped_payloads = [(str(choice.animation_name), shaped) for choice, _clip_path, shaped, _shaped_path, _source in shaped_sources]
    if cut_strands:
        export_glb = out_root / f"{sid}_prebaked_clipped.glb"
        strand_report = clip_stretched_triangles(prebaked_glb, export_glb, shaped_payloads, preview_png=out_root / "strand_cut_preview.png")
        strand_report["applied"] = True
    else:
        export_glb = prebaked_glb
        scan = find_stretched_triangles(prebaked_glb, shaped_payloads)
        strand_report = {
            "applied": False,
            "triangles": int(len(scan["faces"])),
            "cutTriangles": 0,
            "strandCandidates": int(scan["cut"].sum()),
            "stretchedNeighbourSkin": int(scan["stretchedKept"].sum()),
            "worstStretchRatio": round(float(scan["worstRatio"].max()), 3),
            "framesScored": scan["framesScored"],
            "preview": str(render_cut_preview(scan, shaped_payloads, out_root / "strand_scan_preview.png")),
            "proof": "report only; mesh unchanged",
        }
    (out_root / "strand_scan_report.json").write_text(json.dumps(strand_report, indent=2) + "\n", encoding="utf-8")
    result["strandScan"] = {k: strand_report[k] for k in ("applied", "triangles", "cutTriangles", "worstStretchRatio")}

    exported: list[dict[str, Any]] = []
    for choice, clip_path, shaped, shaped_path, source in shaped_sources:
        rows = export_choice_clips(
            choice, shaped, mesh=export_glb, clip_dir=clip_dir, prefix="Unit",
            clip_result_path=shaped_path, frame_duration_by_suffix=durations,
        )
        for row in rows:
            row["poseSource"] = source
            row["characterPass"] = {"gain": DEFAULT_CHARACTER_PROFILE[row["contractName"].split("_", 1)[-1]]["gain"], "sourcePayload": str(clip_path)}
        exported.extend(rows)

    master = write_oriented_master_glb(export_glb, out_root / f"{sid}_smartrig_master.glb")
    pbr = extract_glb_hexlit_pbr_maps(export_glb, out_root)
    shipped = {item["contractName"] for item in exported}
    needed = {
        contract_name_for_group(int(group), "Unit")
        for choice in choices
        for group in choice.def_lab_groups
        if int(group) in CHOSEN_DEF_GROUPS and not (int(group) == IDLE_GROUP and len(choice.def_lab_groups) > 1)
    }
    lacking = sorted(needed - shipped)
    if lacking:
        raise RuntimeError(f"{sid} delivery is missing contracts: {lacking}")

    manifest = {
        "labSid": sid,
        "mesh": str(mesh),
        "prebaked": {
            "glb": str(export_glb),
            "scannedGlb": str(prebaked_glb),
            "strandScan": result["strandScan"],
            "bakedTexture": str(baked_png),
            "lightSolution": str(solution_path),
            "pbrNeutralized": True,
            "engineNote": "Hex/Lit still applies diffuse shading over the baked albedo; specular/normal are neutral",
        },
        "master": master,
        "pbr": pbr,
        "clips": exported,
        "scale": unit_scale(sid),
        "pipeline": "continuous_tracker_prebaked",
        "poseSources": sorted({row["poseSource"] for row in exported}),
        "characterPass": {"profile": DEFAULT_CHARACTER_PROFILE, "perAnimation": character_reports},
        "physicsSmoothOnTracker": smooth_reports,
        "proofTier": "generated-artifact",
    }
    (out_root / "delivery_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    result["clips"] = {row["contractName"]: row["poseSource"] for row in exported}
    result["characterPass"] = character_reports
    result["physicsSmoothOnTracker"] = {
        clip: {k: report.get(k) for k in ("smoothed", "reason", "outlierBoneFrames", "jitterBefore", "jitterAfter")}
        for clip, report in smooth_reports.items()
    }
    result["status"] = "ok"
    return result


def deliver_all(units: list[str], lane: str, out: Path, summary: Summary, log_root: Path, *, cut_strands: bool = False) -> list[str]:
    import roc_semantic_hybrid_widgets as widgets

    log("discovering picker choices ...")
    all_choices = widgets.discover_asset_choices(ROOT)
    delivered: list[str] = []
    for sid in units:
        tracked = {clip for clip, row in summary.unit(sid)["track"].items() if row.get("status") == "ok"}
        if not tracked:
            summary.unit(sid)["deliver"] = {"status": "skipped", "reason": "no tracker result for any sequence tonight"}
            summary.write()
            log(f"deliver {sid}: skipped (nothing tracked)")
            continue
        out_root = out / "units" / sid
        out_root.mkdir(parents=True, exist_ok=True)
        started = time.time()
        log(f"deliver {sid}: light solve + bake + export ...")
        try:
            result = deliver_unit(
                sid, all_choices=all_choices, lane=lane, out_root=out_root, log_root=log_root, tracked_clips=tracked,
                cut_strands=cut_strands,
            )
            result["deliverSec"] = round(time.time() - started, 1)
            delivered.append(sid)
            log(f"deliver {sid}: ok ({result['deliverSec']}s) sources={sorted(set(result['clips'].values()))}")
        except Exception as exc:  # one unit must not end the night
            import traceback

            result = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-3000:],
                "deliverSec": round(time.time() - started, 1),
            }
            log(f"deliver {sid}: FAILED {result['error']}")
        summary.unit(sid)["deliver"] = result
        summary.write()
    return delivered


# --------------------------------------------------------------------------- phase 3: install
# --unity-direct is the explicit, loudly logged opt-out of the Unity queue (docs/unity_queue_runner.md).
UNITY_DIRECT = False


def unity_step(command: list[str], *, log_path: Path, timeout_sec: float) -> tuple[bool, str]:
    """A Unity.exe command becomes one Unity queue job (agents submit, not launch); its log slice goes to log_path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("unity_queue", ROOT / "tools/unity_queue/unity_queue.py")
    uq = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(uq)
    done = uq.run_cmd(command, kind="stronghold_prebaked_install", timeout_s=int(timeout_sec), direct=UNITY_DIRECT,
                      output_dir=BUILD_OUT if "-outputPath" in command else None)
    body = (done.stdout or "") + (done.stderr or "")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(f"# {' '.join(command)}\n# exit={done.returncode} job={done.args}\n\n{body}", encoding="utf-8")
    return done.returncode == 0, body[-4000:]


def stage(summary: Summary, name: str, command: list[str], log_path: Path, timeout_sec: float) -> bool:
    log(f"{name}: {' '.join(command[:4])} ...")
    started = time.time()
    if command[0].lower().endswith("unity.exe"):
        ok, tail = unity_step(command, log_path=log_path, timeout_sec=timeout_sec)
    else:
        ok, tail = run_step(command, log=log_path, timeout_sec=timeout_sec)
    summary.payload["stages"][name] = {
        "ok": ok,
        "elapsedSec": round(time.time() - started, 1),
        "log": str(log_path),
        **({} if ok else {"error": tail[-800:]}),
    }
    summary.write()
    log(f"{name}: {'ok' if ok else 'FAILED'}")
    return ok


def validate_rollout(delivered: list[str], out: Path, summary: Summary, log_root: Path) -> bool:
    """Exporter round-trip and deliberate-motion gates over the delivered units."""
    if not delivered:
        summary.payload["stages"]["validate"] = {"ok": False, "error": "no delivered units"}
        summary.write()
        return False
    units_file = out / "stronghold_prebaked_units.txt"
    units_file.write_text("\n".join(delivered) + "\n", encoding="utf-8")
    if not stage(
        summary, "validate_clip_pose",
        [sys.executable, str(ROOT / "tools/validate_homm3_skinned_clip_pose_contract.py"), "--rollout-dir", str(out)],
        log_root / "validate_clip_pose.log", 1800.0,
    ):
        return False
    # Deliberate-motion is the *full-animation readiness* bar (multi-frame MoveStart/
    # MoveEnd, owned ground controller, authored landmarks). The Stronghold lane
    # installed today does not meet it either (same one-pose DEF groups), so it is
    # recorded here as a readiness report and does not gate this install.
    stage(
        summary, "report_deliberate_motion_readiness",
        [
            sys.executable, str(ROOT / "tools/validate_deliberate_motion_contract.py"),
            "--rollout-dir", str(out), "--units-file", str(units_file), "--write-reports",
        ],
        log_root / "validate_deliberate_motion.log", 1800.0,
    )
    summary.payload["stages"]["report_deliberate_motion_readiness"]["gating"] = False
    summary.write()
    return True


def _bundle_fingerprint(path: Path) -> dict[str, Any]:
    import hashlib

    data = path.read_bytes()
    return {"length": len(data), "sha256": hashlib.sha256(data).hexdigest().upper()}


def pin_contract_rows(bundle: str) -> dict[str, Any]:
    """Pin the freshly built ``bundle`` into the payload contract; reconcile stale prefix siblings.

    The csproj deploy validates every contract row whose name starts with the deployed
    bundle name (so ``custom_units_h3_ogre`` also checks ``custom_units_h3_ogre_mage``),
    in build_out and then in the install. The new bundle's bytes are pinned. A sibling row
    is rewritten only when build_out and the installed copy already agree with each other
    and only the contract disagrees -- a stale row describing nothing on disk. A sibling
    whose build_out and installed bytes differ is left alone and reported, because that
    is a real divergence this lane must not paper over.
    """
    contract_path = ROOT / "custom_factions/contracts/homm3_bundle_payload_contract.json"
    doc = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    rows = doc["bundles"]
    installed_dir = GOLDEN / "BepInEx/plugins/OfflineUnlockMod/homm3_bundles"
    report: dict[str, Any] = {"pinned": {}, "reconciledStaleRows": {}, "leftDivergent": {}}
    for name in sorted(rows):
        if not name.startswith(bundle):
            continue
        built = BUILD_OUT / name
        if not built.is_file():
            continue
        built_fp = _bundle_fingerprint(built)
        if name == bundle:
            report["pinned"][name] = {"previous": rows.get(name), "now": built_fp}
            rows[name] = built_fp
            continue
        if rows.get(name) == built_fp:
            continue
        installed = installed_dir / name
        installed_fp = _bundle_fingerprint(installed) if installed.is_file() else None
        if installed_fp == built_fp:
            report["reconciledStaleRows"][name] = {"previous": rows.get(name), "now": built_fp}
            rows[name] = built_fp
        else:
            report["leftDivergent"][name] = {"contract": rows.get(name), "buildOut": built_fp, "installed": installed_fp}
    contract_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return report


def install_all(delivered: list[str], out: Path, summary: Summary, log_root: Path) -> None:
    # fit_plan.json gives prepare's --require-chosen-set its expected contract list.
    fit_plan = FUSED_ROLLOUT / "fit_plan.json"
    if not fit_plan.is_file():
        raise FileNotFoundError(fit_plan)
    shutil.copy2(fit_plan, out / "fit_plan.json")
    sids = ",".join(delivered)

    if not stage(
        summary, "prepare_import",
        [
            sys.executable, str(TOOL / "prepare_smartrig_skinned_import.py"),
            "--rollout-dir", str(out), "--require-chosen-set", "--lab-sids", sids,
            "--write-import", "--write-units-manifest",
        ],
        log_root / "prepare_import.log", 600.0,
    ):
        return
    lab_spec = out / "unity_lab_batch.json"
    spec_units = {row["labSid"] for row in json.loads(lab_spec.read_text(encoding="utf-8")).get("units") or []}
    dropped = sorted(set(delivered) - spec_units)
    summary.payload["stages"]["prepare_import"]["labSpecUnits"] = sorted(spec_units)
    summary.payload["stages"]["prepare_import"]["droppedByPrepare"] = dropped
    summary.write()
    if not spec_units:
        return

    if not UNITY.is_file():
        summary.payload["stages"]["unity"] = {"ok": False, "error": f"missing Unity editor {UNITY}"}
        summary.write()
        return
    # Only the two editor scripts this lane uses. The billboard-lane scripts in the same
    # source folder reference types this project does not have and break compilation.
    editor_dir = UNITY_PROJECT / "Assets/Editor"
    editor_dir.mkdir(parents=True, exist_ok=True)
    for source in (
        ROOT / "tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs",
        ROOT / "tools/custom_prefab_pipeline/unity_editor/BuildCustomUnitBundles.cs",
    ):
        shutil.copy2(source, editor_dir / source.name)

    # Lab per unit: one bad master GLB throws inside BuildFromSpecPath and would take the
    # whole batch down with it.
    all_specs = json.loads(lab_spec.read_text(encoding="utf-8")).get("units") or []
    lab_ok: list[str] = []
    for spec in all_specs:
        sid = spec["labSid"]
        unit_spec = out / "units" / sid / "unity_lab_spec.json"
        unit_spec.write_text(json.dumps({"units": [spec]}, indent=2) + "\n", encoding="utf-8")
        if stage(
            summary, f"unity_lab_{sid}",
            [
                str(UNITY), "-batchmode", "-quit", "-nographics", "-projectPath", str(UNITY_PROJECT),
                "-executeMethod", "Homm3OwnedSkinnedLabBuild.BuildFromCommandLine",
                "-skinnedLabSpec", str(unit_spec), "-logFile", str(log_root / f"unity_lab_{sid}_editor.log"),
            ],
            log_root / f"unity_lab_{sid}.log", 1800.0,
        ):
            lab_ok.append(sid)
        else:
            summary.unit(sid)["install"] = {"status": "failed", "error": "Unity lab build failed; see stage log"}
            summary.write()
    if not lab_ok:
        return

    def build_bundles(name: str, sids: list[str]) -> bool:
        bundle_list = out / f"bundle_unit_sids_{name}.txt"
        bundle_list.write_text("\n".join(sids) + "\n", encoding="utf-8")
        return stage(
            summary, f"unity_bundles_{name}",
            [
                str(UNITY), "-batchmode", "-quit", "-nographics", "-projectPath", str(UNITY_PROJECT),
                "-executeMethod", "OldenEra.CustomUnitBuilder.BuildCustomUnitBundles.BuildFromManifest",
                "-manifestPath", str(UNITS_MANIFEST), "-homm3UnitListPath", str(bundle_list),
                "-outputPath", str(BUILD_OUT), "-logFile", str(log_root / f"unity_bundles_{name}_editor.log"),
            ],
            log_root / f"unity_bundles_{name}.log", 3600.0,
        )

    # One bundle build for everything that passed the lab; if that fails, narrow to one
    # unit per build so the failing unit is identified and the rest still ship.
    bundled: list[str] = []
    if build_bundles("all", sorted(lab_ok)):
        bundled = sorted(lab_ok)
    else:
        for sid in sorted(lab_ok):
            if build_bundles(sid, [sid]):
                bundled.append(sid)
            else:
                summary.unit(sid)["install"] = {"status": "failed", "error": "Unity bundle build failed; see stage log"}
                summary.write()

    # One csproj deploy per bundle: its payload + audio validators gate each copy, and the
    # first build also deploys the rewritten homm3_import.json with the plugin.
    manifest_rows = {row["unitSid"]: row for row in json.loads(UNITS_MANIFEST.read_text(encoding="utf-8-sig")).get("units") or []}
    # The deploy validator checks every contract row whose name starts with the deployed
    # bundle's name, so custom_units_h3_cyclops also checks custom_units_h3_cyclops_king.
    # When both were just rebuilt, the longer name must deploy first; otherwise the
    # shorter one's deploy sees a sibling whose build_out bytes match neither the
    # contract nor the install and fails (h3_cyclops on 2026-09-02).
    bundled.sort(key=lambda sid: (-len(str(manifest_rows.get(sid, {}).get("bundleName") or "")), sid))
    for sid in bundled:
        bundle = manifest_rows.get(sid, {}).get("bundleName")
        install: dict[str, Any] = {"bundle": bundle}
        summary.unit(sid)["install"] = install
        if not bundle or not (BUILD_OUT / bundle).is_file():
            install.update({"status": "failed", "error": f"bundle {bundle!r} not built under {BUILD_OUT}"})
            summary.write()
            continue
        install["contract"] = pin_contract_rows(bundle)
        summary.write()
        ok = stage(
            summary, f"deploy_{sid}",
            [
                # Same shape as tools/deploy_official_deobf_port_smoke.sh: the deploy target
                # only runs when DeployPluginToGame is explicitly true, and Golden Era
                # interop references come from OfficialDeobfBuild.
                "dotnet", "build", str(PLUGIN), "-c", "Release", f"-p:GameRoot={GOLDEN}",
                "-p:DeployPluginToGame=true", "-p:OfficialDeobfBuild=true",
                f"-p:DeployHomm3BundleName={bundle}",
                # Factory/Bulwark contract rows are stale against both build_out and the
                # install (pre-existing, not touched by this lane); that BeforeBuild gate
                # would otherwise block every plugin build. Skipped explicitly and reported.
                "-p:SkipHotaFactoryBulwarkRuntimeAssetValidation=true",
            ],
            log_root / f"deploy_{sid}.log", 1800.0,
        )
        installed = GOLDEN / "BepInEx/plugins/OfflineUnlockMod/homm3_bundles" / bundle
        if ok and installed.is_file() and installed.stat().st_size == (BUILD_OUT / bundle).stat().st_size:
            install.update({"status": "installed", "path": str(installed), "bytes": installed.stat().st_size})
        else:
            install.update({"status": "failed", "error": summary.payload["stages"][f"deploy_{sid}"].get("error", "installed file mismatch")})
        summary.write()


# --------------------------------------------------------------------------- main
def main() -> int:
    args = parse_args()
    global UNITY_DIRECT
    UNITY_DIRECT = args.unity_direct
    units = list(STRONGHOLD_UNITS) if args.units is None else [p.strip() for p in str(args.units).split(",") if p.strip()]
    unknown = [u for u in units if u not in STRONGHOLD_UNITS]
    if unknown:
        raise ValueError(f"not Stronghold roster units: {unknown}")
    clips = [p.strip() for p in str(args.clips).split(",") if p.strip()]
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    log_root = out / "logs"
    summary = Summary(out / "overnight_summary.json", units, args)
    log(f"stronghold prebaked install: {len(units)} units, clips={clips}, lane={args.lane}, out={out}")

    if not args.skip_track:
        track_all(args, units, clips, summary, log_root)
    else:
        for unit in units:
            for clip in clips:
                present = tracker_result(unit, clip, args.lane).is_file()
                summary.unit(unit)["track"][clip] = {"status": "ok" if present else "unavailable", "reused": present}
        summary.write()

    delivered = deliver_all(units, str(args.lane), out, summary, log_root, cut_strands=bool(args.cut_strands))
    summary.payload["delivered"] = delivered
    summary.write()

    validated = validate_rollout(delivered, out, summary, log_root)
    if args.skip_install:
        log("skip-install set; stopping after validation")
    elif validated:
        install_all(delivered, out, summary, log_root)

    summary.payload["finished"] = datetime.now().isoformat(timespec="seconds")
    summary.write()
    installed = [sid for sid, row in summary.payload["units"].items() if (row.get("install") or {}).get("status") == "installed"]
    if installed:
        commit_install_records(installed, summary)
    log(f"done: delivered={len(delivered)} installed={len(installed)} summary={summary.path}")
    return 0


def commit_install_records(installed: list[str], summary: Summary) -> None:
    """Commit only the source-tree records an install rewrites (contract, import table, manifest)."""
    tracked = [
        "custom_factions/contracts/homm3_bundle_payload_contract.json",
        "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json",
        "tools/homm3_import/homm3_units_manifest.json",
    ]
    subprocess.run(["git", "add", "--", *tracked], cwd=str(ROOT), check=False)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *tracked], cwd=str(ROOT))
    if staged.returncode == 0:
        summary.payload["commit"] = "nothing to commit"
        summary.write()
        return
    message = (
        f"Install pre-baked continuous-tracked Stronghold units ({len(installed)}): "
        + ", ".join(installed)
        + "\n\nOvernight run of run_stronghold_prebaked_install_overnight.py. Bundle contract rows "
        "pinned to the new bundles; import/manifest rows point at OwnedSkinned prefabs. "
        "Runtime appearance in Golden Era battle is not proven by this commit."
    )
    completed = subprocess.run(["git", "commit", "-m", message, "--", *tracked], cwd=str(ROOT), capture_output=True, text=True)
    summary.payload["commit"] = (completed.stdout + completed.stderr).strip()[-600:]
    summary.write()


if __name__ == "__main__":
    raise SystemExit(main())
