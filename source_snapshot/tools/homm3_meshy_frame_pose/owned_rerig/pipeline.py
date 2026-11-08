"""End-to-end owned re-rig: diagnose, strip, partition, bind, audit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .audit import audit_owned_bind, lbs_delta_after_bone_rotate
from .bind import bind_species_mesh, template_part_names
from .diagnose import diagnose_smartrig_quality
from .glb_io import load_mesh, write_skinned_mesh, z_up_to_y_up
from .part_map import apply_part_map, load_part_map
from .preview import render_ortho_ppm, render_turntable_ppms
from .species import load_species_template
from .strip import strip_armature
from .synthetic import authored_part_map_for_fixture, write_mixamo_rider_mount_fixture

ROOT = Path(__file__).resolve().parents[3]


def locate_cavalier_mesh(repo: Path | None = None) -> dict[str, Any]:
    root = Path(repo) if repo is not None else ROOT
    candidates = [
        root / "artifacts" / "meshy_downloads" / "h3_cavalier_smartrigged.glb",
        root / "artifacts" / "meshy_downloads" / "h3_cavalier.glb",
        root / "artifacts" / "cavalier_pose_pipeline" / "source" / "h3_cavalier.glb",
    ]
    found = next((path for path in candidates if path.is_file()), None)
    return {
        "schema": "cavalier_mesh_source.v1",
        "found": found is not None,
        "path": None if found is None else str(found.resolve()).replace("\\", "/"),
        "searched": [str(path).replace("\\", "/") for path in candidates],
        "note": "Cavalier Meshy GLB is not in this worktree; synthetic Mixamo-on-mount fixture is the generated-artifact stand-in until the mesh is located or re-exported with --skip-rig.",
    }


def run_owned_rerig_pipeline(
    *,
    dest_dir: Path,
    src_glb: Path | None = None,
    part_map_path: Path | None = None,
    species: str = "rider_mount",
    unit_sid: str = "h3_cavalier",
    allow_synthetic_fixture: bool = False,
    repo: Path | None = None,
    landmarks_3d: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    locate = locate_cavalier_mesh(repo)
    used_synthetic = False
    if src_glb is None:
        if locate["found"]:
            src_glb = Path(locate["path"])
        elif allow_synthetic_fixture:
            src_glb = dest / "fixture_mixamo_rider_mount.glb"
            write_mixamo_rider_mount_fixture(src_glb)
            used_synthetic = True
        else:
            raise FileNotFoundError(
                "Cavalier mesh is missing. Locate the August 12 download or re-export mesh+texture with generate_meshy_t2_unit_master.py --skip-rig. Do not buy another Smart Rig."
            )
    quality = diagnose_smartrig_quality(src_glb, expected_species=species)
    (dest / "smartrig_quality.json").write_text(json.dumps(quality, indent=2) + "\n", encoding="utf-8")
    (dest / "mesh_source.json").write_text(json.dumps({**locate, "usedSyntheticFixture": used_synthetic, "sourceUsed": str(Path(src_glb).resolve()).replace("\\", "/")}, indent=2) + "\n", encoding="utf-8")
    if quality["verdict"] != "replace":
        raise RuntimeError(f"owned re-rig refuses a keep verdict: {quality}")

    stripped = dest / "mesh_stripped.glb"
    strip_armature(src_glb, stripped)
    template = load_species_template(species)
    if part_map_path is None:
        if not used_synthetic:
            raise FileNotFoundError("authored part map is required for a real unit mesh")
        part_map_path = dest / "part_map_authored.json"
        part_map_path.write_text(json.dumps(authored_part_map_for_fixture(), indent=2) + "\n", encoding="utf-8")
    authored = load_part_map(part_map_path)
    mesh = load_mesh(stripped)
    part_names = template_part_names(template)
    labels = apply_part_map(
        mesh.positions,
        mesh.indices,
        authored,
        min_share=template.get("minShare") or {},
        max_share=template.get("maxShare"),
        parts=part_names,
    )
    bind = bind_species_mesh(
        mesh.positions,
        labels,
        template,
        landmarks_3d=landmarks_3d,
    )
    audit = audit_owned_bind(
        template=template,
        bone_names=bind["boneNames"],
        positions=mesh.positions,
        labels=labels,
        joints=bind["joints"],
        weights=bind["weights"],
        heads=bind["heads"],
        parents=bind["parents"],
    )
    (dest / "owned_bind_audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    if not audit["ok"]:
        raise RuntimeError(f"owned bind audit failed: {audit['issues']}")
    (dest / "part_labels.json").write_text(
        json.dumps({"schema": "owned_bind_part_labels.v1", "labels": [int(v) for v in labels]}, indent=2) + "\n",
        encoding="utf-8",
    )
    turntable = render_turntable_ppms(mesh.positions, dest / "turntable")
    name_index = {name: i for i, name in enumerate(bind["boneNames"])}
    proof_bone = str((template.get("audit") or {}).get("rotateBone") or "")
    if proof_bone and proof_bone in name_index:
        delta = lbs_delta_after_bone_rotate(
            mesh.positions,
            bind["joints"],
            bind["weights"],
            bind["heads"],
            bind["parents"],
            name_index[proof_bone],
            np.array([1.0, 0.0, 0.0]),
            float(np.deg2rad(30.0)),
        )
        render_ortho_ppm(dest / "proof_leg_rotate_rest.ppm", mesh.positions, axis="side")
        render_ortho_ppm(
            dest / "proof_leg_rotate_posed.ppm",
            mesh.positions + delta,
            axis="side",
            color=(220, 80, 80),
        )
    master = dest / "owned_bind" / f"{unit_sid}_master.glb"
    write_skinned_mesh(
        master,
        positions=mesh.positions,
        indices=mesh.indices,
        bone_names=bind["boneNames"],
        parents=bind["parents"],
        heads=bind["heads"],
        joints=bind["joints"],
        weights=bind["weights"],
        extras={
            "species": species,
            "unitSid": unit_sid,
            "ownedBind": True,
            "syntheticFixture": used_synthetic,
            "bindOrientation": "z_up",
        },
        source_glb=stripped if Path(stripped).is_file() else None,
    )
    master_yup = dest / "owned_bind" / f"{unit_sid}_master_yup.glb"
    write_skinned_mesh(
        master_yup,
        positions=z_up_to_y_up(mesh.positions),
        indices=mesh.indices,
        bone_names=bind["boneNames"],
        parents=bind["parents"],
        heads=z_up_to_y_up(bind["heads"]),
        joints=bind["joints"],
        weights=bind["weights"],
        extras={
            "species": species,
            "unitSid": unit_sid,
            "ownedBind": True,
            "syntheticFixture": used_synthetic,
            "bindOrientation": "y_up_pose_pipeline",
        },
        source_glb=stripped if Path(stripped).is_file() else None,
    )
    report = {
        "schema": "owned_rerig_pipeline.v1",
        "unitSid": unit_sid,
        "species": species,
        "source": str(Path(src_glb).resolve()).replace("\\", "/"),
        "stripped": str(stripped.resolve()).replace("\\", "/"),
        "partMap": str(Path(part_map_path).resolve()).replace("\\", "/"),
        "master": str(master.resolve()).replace("\\", "/"),
        "masterYUp": str(master_yup.resolve()).replace("\\", "/"),
        "quality": quality,
        "audit": audit,
        "usedSyntheticFixture": used_synthetic,
        "proof": "generated-artifact",
        "bones": bind["boneNames"],
    }
    (dest / "pipeline_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
