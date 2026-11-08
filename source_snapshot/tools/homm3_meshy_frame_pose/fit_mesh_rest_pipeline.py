"""Fit a mesh rest rig, retarget saved capture, and optionally render a review reel.

No generation or mocap inference is run. A batch manifest contains explicit jobs rather than
assuming every roster member is a T-pose biped. Outputs never replace the source assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "artifacts/homm3_owned_bind"))
from bind_meshy71_candidate import load_pose, plain
from reel_meshy71_candidate import load_similarity
from owned_rerig.exact_bind import ExactBindParams, bone_tails, provisional_labels, skin_by_position_field
from owned_rerig.glb_io import load_mesh, load_render_surface, read_glb, write_skinned_mesh
from owned_rerig.mesh_rest_fit import fit_mesh_rest
from owned_rerig.rest_retarget import corresponding_source_rest, retarget_motion, outgoing_skin_transforms
from owned_rerig.prop_attachment import repair_prop_attachments
from owned_rerig.smartrig_biped import extract_smartrig_biped_heads
from owned_rerig.authored_skin import transfer_authored_skin
from owned_rerig.retarget_clearance import apply_hand_clearance
from owned_rerig.prop_orientation import load_orientation_evidence, augment_source_prop_motion
from owned_rerig.tpose import tpose_joint_track

PREVIEW_FILES = (
    "rest_overlay.png",
    "keyframes.png",
    "first_frame.png",
    "animation_reel.gif",
    "detail_reel.gif",
    "detail_keyframes.png",
)


def _content_crop(images, *, padding):
    """Return one stable crop around the rendered mesh across the saved frames."""
    pixels = np.stack([np.asarray(image) for image in images], axis=0)
    background = np.asarray(images[0], dtype=np.int16)[0, 0]
    delta = pixels.astype(np.int16) - background
    mask = np.any(np.linalg.norm(delta, axis=-1) > 6, axis=0)
    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return (0, 0, images[0].width, images[0].height)
    width, height = images[0].size
    return (
        max(0, int(xs.min()) - int(padding)),
        max(0, int(ys.min()) - int(padding)),
        min(width, int(xs.max()) + 1 + int(padding)),
        min(height, int(ys.max()) + 1 + int(padding)),
    )


def record_incomplete(out, record):
    """Keep directory handoffs consistent with the current attempt, including failed refits."""
    out.mkdir(parents=True, exist_ok=True)
    for filename in PREVIEW_FILES:
        (out / filename).unlink(missing_ok=True)
    (out / "report.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def skin(values, joints, weights, rotations, offsets=None):
    result = np.zeros_like(values, dtype=float)
    for slot in range(joints.shape[1]):
        ids = joints[:, slot]
        moved = np.einsum("nij,nj->ni", rotations[ids], values)
        if offsets is not None:
            moved += offsets[ids]
        result += moved * weights[:, slot, None]
    return result


def retarget_reference(body_plan, registered_rest, heads, parents, names):
    if body_plan == "smartrig-biped":
        return corresponding_source_rest(registered_rest, heads, parents, names)
    if body_plan == "biped-tpose":
        return tpose_joint_track(rest=registered_rest, parents=parents, joint_names=names)["joints"]
    raise ValueError(f"Unsupported rest-reference body plan: {body_plan}")


def load_owned_bind(path):
    """Read an owned candidate bind without borrowing its vendor skeleton."""
    mesh = load_mesh(Path(path))
    if mesh.joints is None or mesh.weights is None or not mesh.skin_joints:
        raise ValueError("ownedBind must contain an emitted owned skin")
    doc = read_glb(Path(path))["json"]
    bone_nodes = list(mesh.skin_joints)
    node_to_bone = {node: i for i, node in enumerate(bone_nodes)}
    parents = [None] * len(bone_nodes)
    for node_index, node in enumerate(doc.get("nodes") or []):
        for child in node.get("children") or []:
            if int(child) in node_to_bone and node_index in node_to_bone:
                parents[node_to_bone[int(child)]] = node_to_bone[node_index]
    world = np.zeros((len(bone_nodes), 3), dtype=np.float64)
    for bone, node_index in enumerate(bone_nodes):
        chain = []
        current = node_index
        while current in node_to_bone:
            chain.append(current)
            parent = parents[node_to_bone[current]]
            if parent is None:
                break
            current = bone_nodes[parent]
        for current in reversed(chain):
            bone = node_to_bone[current]
            parent = parents[bone]
            translation = np.asarray((doc["nodes"][current].get("translation") or [0, 0, 0]), dtype=np.float64)
            world[bone] = translation if parent is None else world[parent] + translation
    names = [str(doc["nodes"][node].get("name") or f"bone{i}") for i, node in enumerate(bone_nodes)]
    return {"mesh": mesh, "heads": world, "parents": parents, "names": names}


def render_preview(
    out,
    surface,
    positions,
    heads,
    parents,
    names,
    joints,
    weights,
    motion,
    frame_labels,
    *,
    reel=True,
    preview_scale=1,
):
    import exp_tpose as render
    from PIL import Image, ImageDraw

    if int(preview_scale) < 1:
        raise ValueError("preview_scale must be at least 1")
    render.PANEL = (360 * int(preview_scale), 520 * int(preview_scale))
    rotations, offsets = motion["rotations"], motion["offsets"]
    frames = [skin(positions, joints, weights, r, t) for r, t in zip(rotations, offsets)]
    cloud = np.concatenate([positions] + frames)
    view = render.camera(25, cloud)
    rest_panels = []
    for yaw in (0, 90):
        rest_view = render.camera(yaw, np.concatenate([positions, heads]))
        panel = render.textured(rest_view, deformed=positions, normals=surface["normals"], surface=surface, indices=surface["indices"])
        image = Image.fromarray(np.clip(panel, 0, 255).astype("uint8"))
        draw = ImageDraw.Draw(image)
        xy = np.column_stack([heads @ rest_view["right"], heads @ rest_view["down"]]) * rest_view["k"] + rest_view["off"]
        for i, parent in enumerate(parents):
            if parent is not None:
                draw.line([tuple(xy[parent]), tuple(xy[i])], fill=(255, 80, 70), width=2)
        draw.text((6, 5), f"Fitted rest skeleton | yaw {yaw}", fill="white")
        rest_panels.append(np.asarray(image))
    Image.fromarray(np.concatenate(rest_panels, axis=1)).save(out / "rest_overlay.png")
    key_indices = []
    for clip in ("g02_idle", "g00_move", "g12_attack_front", "g15_shoot_front", "g05_death"):
        indices = [i for i, label in enumerate(frame_labels) if label.endswith(clip)]
        if indices:
            key_indices.append(indices[len(indices) // 2])
    images = {}
    raw_images = {}
    for index in (range(len(frames)) if reel else sorted(set([0] + key_indices))):
        points, rotation = frames[index], rotations[index]
        normals = skin(surface["normals"], joints, weights, rotation)
        normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
        panel = render.textured(view, deformed=points, normals=normals, surface=surface, indices=surface["indices"])
        raw_images[index] = Image.fromarray(np.clip(panel, 0, 255).astype("uint8"))
        render.label(panel, frame_labels[index])
        images[index] = Image.fromarray(np.clip(panel, 0, 255).astype("uint8"))
    if reel:
        images[0].save(out / "animation_reel.gif", save_all=True, append_images=list(images.values())[1:], duration=100, loop=0, optimize=False)
        left, top, right, bottom = _content_crop(list(raw_images.values()), padding=24 * int(preview_scale))
        detail_images = []
        for index, image in raw_images.items():
            detail = image.crop((left, top, right, bottom))
            ImageDraw.Draw(detail).text((6, 5), frame_labels[index], fill="white")
            detail_images.append(detail)
        detail_images[0].save(
            out / "detail_reel.gif",
            save_all=True,
            append_images=detail_images[1:],
            duration=100,
            loop=0,
            optimize=False,
        )
        selected_detail = [detail_images[index] for index in key_indices if index in raw_images]
        if selected_detail:
            detail_keyframes = Image.new(
                "RGB",
                (sum(image.width for image in selected_detail), max(image.height for image in selected_detail)),
            )
            offset = 0
            for image in selected_detail:
                detail_keyframes.paste(image, (offset, 0))
                offset += image.width
            detail_keyframes.save(out / "detail_keyframes.png")
    images[0].save(out / "first_frame.png")
    selected = [np.asarray(images[index]) for index in key_indices]
    if selected:
        Image.fromarray(np.concatenate(selected, axis=1)).save(out / "keyframes.png")


def job_fingerprint(job):
    """Shared cache identity for fitting and read-only evidence provenance checks."""
    run_dir = Path(job["runDir"])
    inputs = [Path(job["mesh"]), Path(job["sourceReport"]), Path(__file__),
              Path(__file__).parent / "owned_rerig/mesh_rest_fit.py",
              Path(__file__).parent / "owned_rerig/rest_retarget.py",
              Path(__file__).parent / "owned_rerig/exact_bind.py",
              Path(__file__).parent / "owned_rerig/glb_io.py",
              Path(__file__).parent / "owned_rerig/smartrig_biped.py",
              Path(__file__).parent / "owned_rerig/pose_source.py",
              Path(__file__).parent / "owned_rerig/tpose.py",
              Path(__file__).parent / "bind_meshy71_candidate.py",
              Path(__file__).parent / "reel_meshy71_candidate.py",
              ROOT / "artifacts/homm3_owned_bind/exp_tpose.py",
              run_dir / "linked_master/capture/capture/raw_capture.npz",
              run_dir / "linked_master/master_sequence/master_sequence.json"]
    if job.get("propAttachments"):
        inputs += [Path(job["propAttachments"]), Path(__file__).parent / "owned_rerig/prop_attachment.py"]
    if job.get("authoredSkinMap"):
        inputs += [Path(job["authoredSkinMap"]), Path(__file__).parent / "owned_rerig/authored_skin.py"]
    if job.get("handClearance"):
        inputs += [Path(job["handClearance"]), Path(__file__).parent / "owned_rerig/retarget_clearance.py"]
    if job.get("propOrientation"):
        inputs += [Path(job["propOrientation"]), Path(__file__).parent / "owned_rerig/prop_orientation.py"]
        # Reject changed source plates even on an otherwise valid cached replay.
        load_orientation_evidence(job["propOrientation"],
                                  run_dir / "linked_master/master_sequence/master_sequence.json", job["sourceReport"])
    if job.get("ownedBind"):
        inputs += [Path(job["ownedBind"])]
    for registration in (run_dir / "linked_master_remaining_scale/idle0_registration.json",
                         run_dir / "linked_master/idle0_registration.json"):
        if registration.is_file():
            inputs.append(registration)
    digest = hashlib.sha256(json.dumps(job, sort_keys=True).encode())
    for path in inputs:
        digest.update(str(path.resolve()).encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1048576), b""):
                digest.update(chunk)
    return digest.hexdigest()


def run_job(job, preview=False, review=False, preview_scale=1):
    start = time.perf_counter()
    if job["bodyPlan"] not in ("biped-tpose", "smartrig-biped", "owned-reference"):
        return {"unit": job["unit"], "status": "needs_body_plan_adapter", "bodyPlan": job["bodyPlan"]}
    out = Path(job["out"])
    out.mkdir(parents=True, exist_ok=True)
    run_dir = Path(job["runDir"])
    fingerprint = job_fingerprint(job)
    report_path = out / "report.json"
    if report_path.is_file():
        cached = json.loads(report_path.read_text(encoding="utf-8"))
        outputs = [out / "fitted_bind.glb", out / "retargeted_motion.npz"]
        if preview or review:
            outputs += [out / "rest_overlay.png", out / "keyframes.png", out / "first_frame.png"]
        if preview:
            outputs += [out / "animation_reel.gif", out / "detail_reel.gif", out / "detail_keyframes.png"]
        if (cached.get("fingerprint") == fingerprint and all(p.is_file() for p in outputs)
                and (not (preview or review) or int(cached.get("previewScale", 1)) == int(preview_scale))
                and (not preview or cached.get("preview"))
                and (not review or cached.get("review") or cached.get("preview"))):
            print(json.dumps({"unit": job["unit"], "status": "cached", "seconds": time.perf_counter() - start, "out": str(out.resolve())}), flush=True)
            return cached
    # A fast refit must not leave an older recipe's reel looking like its current result.
    record_incomplete(out, {"unit": job["unit"], "status": "running", "inputs": job, "outputs": {}})
    surface = load_render_surface(Path(job["mesh"]))
    positions = surface["positions"]
    pose = load_pose(run_dir, "g02_idle")
    similarity = load_similarity(Path(job["sourceReport"]))
    source_rest = similarity.apply(pose.capture_positions[pose.bind_index()])
    names = [str(n).rsplit(":", 1)[-1] for n in pose.joint_names]
    owned_bind = load_owned_bind(job["ownedBind"]) if job.get("ownedBind") else None
    if job["bodyPlan"] == "owned-reference":
        if owned_bind is None:
            raise ValueError("owned-reference requires an explicit ownedBind")
        if len(owned_bind["mesh"].positions) != len(positions):
            raise ValueError("ownedBind vertex count does not match mesh source")
        heads = owned_bind["heads"]
        names = owned_bind["names"]
        pose.parents = owned_bind["parents"]
        fitted = {
            "schema": "owned_reference_fit.v1",
            "source": str(Path(job["ownedBind"]).resolve()),
            "jointCount": len(names),
            "jointNames": names,
        }
    elif job["bodyPlan"] == "smartrig-biped":
        fitted = extract_smartrig_biped_heads(Path(job["mesh"]), source_rest, names)
        heads = fitted["heads"]
    else:
        fitted = fit_mesh_rest(positions=positions, reference_heads=source_rest, parents=pose.parents, names=names)
        heads = fitted["heads"]
    fit_seconds = time.perf_counter() - start
    if owned_bind is not None:
        field = {"joints": np.asarray(owned_bind["mesh"].joints, dtype=np.int64),
                 "weights": np.asarray(owned_bind["mesh"].weights, dtype=np.float64),
                 "report": {"source": "ownedBind", "path": str(Path(job["ownedBind"]).resolve())}}
    elif job.get("authoredSkinMap"):
        config = json.loads(Path(job["authoredSkinMap"]).read_text(encoding="utf-8"))
        field = transfer_authored_skin(Path(job["mesh"]), positions, names, config)
    else:
        labels = provisional_labels(positions=positions, heads=heads)
        tails = bone_tails(positions=positions, parents=pose.parents, heads=heads, labels=labels)
        field = skin_by_position_field(positions=positions, mesh_indices=surface["indices"], heads=heads, tails=tails, parents=pose.parents, bone_names=names, params=ExactBindParams())
    tracks = similarity.apply(pose.capture_positions)
    reference = heads if job["bodyPlan"] == "owned-reference" else retarget_reference(job["bodyPlan"], source_rest, heads, pose.parents, names)
    motion = retarget_motion(source_rest=reference, target_rest=heads, parents=pose.parents, names=names, source_frames=tracks)
    if job.get("handClearance"):
        config = json.loads(Path(job["handClearance"]).read_text(encoding="utf-8"))
        motion = apply_hand_clearance(motion, heads, pose.parents, names, config, surface["sourceSha256"])
    motion = outgoing_skin_transforms(motion, heads, pose.parents, names)
    motion["sourceRestConvention"] = ("authored_direction_correspondence" if job["bodyPlan"] == "smartrig-biped"
                                      else "canonical_tpose")
    attachment_report = None
    output_parents = pose.parents
    if job.get("propAttachments"):
        config = json.loads(Path(job["propAttachments"]).read_text(encoding="utf-8"))
        repaired = repair_prop_attachments(surface=surface, joints=field["joints"], weights=field["weights"], heads=heads, names=names, config=config)
        surface = repaired["surface"]
        positions = surface["positions"]
        field["joints"], field["weights"] = repaired["joints"], repaired["weights"]
        attachment_report = repaired["report"]
    if job.get("propOrientation"):
        orientation, camera = load_orientation_evidence(
            job["propOrientation"], run_dir / "linked_master/master_sequence/master_sequence.json", job["sourceReport"])
        if not job.get("propAttachments"):
            raise ValueError("propOrientation requires an explicit rigid prop attachment")
        if orientation.get("propAttachmentsSha256") != hashlib.sha256(Path(job["propAttachments"]).read_bytes()).hexdigest():
            raise ValueError("propOrientation attachment recipe hash mismatch")
        matching = [i for i, prop in enumerate(config["props"])
                    if prop["bone"] == orientation["owner"] and prop["name"] == orientation["prop"]]
        if len(matching) != 1:
            raise ValueError("propOrientation requires one matching named prop/owner")
        motion, heads, output_parents, names, field["joints"] = augment_source_prop_motion(
            motion, heads, pose.parents, names, field["joints"], repaired["propOwners"], matching[0],
            orientation, surface["sourceSha256"], camera, positions, field["weights"],
            surface["indices"])
    write_skinned_mesh(
        out / "fitted_bind.glb", positions=positions, indices=surface["indices"], bone_names=names,
        parents=output_parents, heads=heads, joints=field["joints"], weights=field["weights"],
        source_glb=Path(job["mesh"]), uvs=surface.get("uvs"), normals=surface.get("normals"),
        extras={
            "experimentalPipeline": (
                "mesh_rest_fit.v1" if job["bodyPlan"] == "biped-tpose"
                else ("owned_reference_bind.v1" if job["bodyPlan"] == "owned-reference"
                      else "smartrig_biped_adapter.v1")
            ),
            "unit": job["unit"],
            "bodyPlan": job["bodyPlan"],
        },
    )
    np.savez_compressed(out / "retargeted_motion.npz", **{key: motion[key] for key in ("frame_joints", "rotations", "offsets")})
    core_seconds = time.perf_counter() - start
    master = json.loads((run_dir / "linked_master/master_sequence/master_sequence.json").read_text(encoding="utf-8"))
    frame_labels = [f'{job["unit"]} | {f["clipKey"]}' for f in master["frames"]]
    if preview or review:
        render_preview(
            out,
            surface,
            positions,
            heads,
            output_parents,
            names,
            field["joints"],
            field["weights"],
            motion,
            frame_labels,
            reel=preview,
            preview_scale=preview_scale,
        )
    report = {"unit": job["unit"], "status": "experimental_candidate", "inputs": job, "fit": fitted, "fitSeconds": fit_seconds, "coreSeconds": core_seconds, "totalSeconds": time.perf_counter() - start, "frames": len(tracks), "motion": {k: v for k, v in motion.items() if k not in ("frame_joints", "rotations", "offsets")}, "preview": preview}
    report["fingerprint"] = fingerprint
    report["attachments"] = attachment_report
    report["skinTransfer"] = field.get("report") if job.get("authoredSkinMap") else None
    report["review"] = review or preview
    report["previewScale"] = int(preview_scale)
    report["outputs"] = {p.name: str(p.resolve()) for p in (
        out / "fitted_bind.glb", out / "retargeted_motion.npz", out / "rest_overlay.png",
        out / "keyframes.png", out / "first_frame.png", out / "animation_reel.gif", out / "detail_reel.gif",
        out / "detail_keyframes.png") if p.is_file()}
    (out / "report.json").write_text(json.dumps(report, indent=2, default=plain) + "\n", encoding="utf-8")
    print(json.dumps({**{k: report[k] for k in ("unit", "status", "fitSeconds", "coreSeconds", "totalSeconds", "frames")}, "out": str(out.resolve())}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--review", action="store_true", help="Render rest overlay and five keyframes, without the full reel")
    parser.add_argument("--preview-scale", type=int, default=1)
    parser.add_argument("--units", nargs="+")
    args = parser.parse_args()
    jobs = json.loads(args.manifest.read_text(encoding="utf-8"))["jobs"]
    available = [job["unit"] for job in jobs]
    if len(set(available)) != len(available):
        parser.error("Manifest contains duplicate unit IDs")
    unknown = set(args.units or []) - set(available)
    if unknown:
        parser.error("Units absent from manifest: " + ", ".join(sorted(unknown)))
    failures = []
    results = []
    for job in jobs:
        if not args.units or job["unit"] in args.units:
            try:
                # Repository-relative inputs work regardless of the caller's current directory.
                job = dict(job)
                for key in ("mesh", "runDir", "sourceReport", "out", "propAttachments", "authoredSkinMap", "handClearance", "propOrientation", "ownedBind"):
                    if key in job:
                        path = Path(job[key])
                        job[key] = str(path if path.is_absolute() else ROOT / path)
                result = run_job(job, preview=args.preview, review=args.review, preview_scale=args.preview_scale)
                results.append({"unit": job["unit"], "status": result["status"]})
                if result["status"] == "needs_body_plan_adapter":
                    print(json.dumps(result), flush=True)
            except (ValueError, OSError, KeyError) as error:
                failure = {"unit": job.get("unit"), "status": "error", "error": str(error)}
                if job.get("out"):
                    try:
                        record_incomplete(Path(job["out"]), {**failure, "inputs": job, "outputs": {}})
                    except OSError as write_error:
                        failure["reportWriteError"] = str(write_error)
                failures.append(failure)
                print(json.dumps(failure), flush=True)
    print(json.dumps({"completed": results, "failures": failures}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
