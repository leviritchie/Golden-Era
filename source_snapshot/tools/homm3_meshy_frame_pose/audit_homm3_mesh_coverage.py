#!/usr/bin/env python3
"""Build a fail-closed inventory of HoMM3 mesh and SmartRig coverage.

The import manifest is the source-defined unit roster for this lane.  Exact
``<sid>_smartrigged.glb`` files are the default SmartRig coverage.  A small,
source-pinned semantic alias table handles the known Wolf Rider/Raider
download-name swap; quarantined ``_WRONG``/legacy files are evidence, never
coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tools/homm3_import/homm3_units_manifest.json"
NEUTRAL_CATALOG = ROOT / "tools/homm3_import/faction_concepts/homm3_neutral.json"
DOWNLOADS = ROOT / "artifacts/meshy_downloads"
UPSCALE = ROOT / "artifacts/creature_aaa_3d_upscale"
REMAINING_STILLS = ROOT / "artifacts/meshy_remaining_stills"

# Explicitly ordered candidate paths.  A retry is never selected merely
# because it is newer; it is named here so the inventory records the manual
# Blender hand-authoring lane without silently replacing a primary candidate.
CUSTOM_RIG_PREFERENCES = {
    # Luna's quantization-aware retry is structurally readback-clean, but it
    # remains a candidate until deformation and animation QA are complete.
    "h3_sharpshooter": (
        ("artifacts/homm3_mocap_v2/meshy7_luna_batch/h3_sharpshooter/h3_sharpshooter/h3_sharpshooter_smartrigged.glb",
         "luna_blender_envelope_quantization_retry"),
    ),
    "hota_cove_nix_praetorian": (
        ("artifacts/homm3_mocap_v2/meshy7_astra_batch/retry_nix/hota_cove_nix_praetorian/hota_cove_nix_praetorian_smartrigged.glb",
         "luna_blender_envelope_retry"),
    ),
}

# Units whose canonical SmartRig is not <sid>_smartrigged.glb.  The Wolf Rider /
# Wolf Raider basenames were swapped on disk on 2026-09-27 so each now names its
# own semantic mesh (pre-swap bytes: meshy_downloads/_superseded_do_not_use/
# wolf_identity_swap_20260927.note.json); they need no alias any more.
CANONICAL_MESH_PREFERENCES = {
    # The active Hobgoblin profile is pinned to this rigidized copy; the
    # unmodified download remains a historical comparison input.
    "h3_hobgoblin": "h3_hobgoblin_smartrigged_rigidized.glb",
}

# Filename is not identity. These hashes are confirmed wrong-source meshes
# retained for evidence only; they must not be treated as canonical SmartRig
# coverage until a new generation is verified against the intended image.
REFUSED_CANONICAL_SMARTRIG_SHA256 = {
    # Meshy sample quadruped saved under the Pegasus filename.
    "h3_pegasus": "ffcf635bb9a86be4cfdcdc1870cb32755e2e179416b99ff3d4db65e51467a85a",
    # Coiled snake statue saved under the Factory Mechanic filename.
    "h3_mechanic_upg_alt": "a107ceac38d18b90d4803e8d1cee81ac8989ec218894ae6fdd1c0468ce45b41c",
    # Cartoon bear saved under the Paokai filename.
    "h3_paokai": "8065a5d6387fcc28891c9bbfed3dbcc6ea167f1251f3e1b13080f9b2a3a3bada",
}

# These replacement surfaces were generated from the pinned AAA upscales after
# the canonical SmartRig files were proven to be wrong-source meshes.  They are
# selected source candidates only: they are not SmartRig coverage and do not
# bypass the later owned-bind or animation gates.
VERIFIED_SOURCE_REPLACEMENTS = {
    "h3_mechanic_upg_alt": "artifacts/meshy_downloads/meshy71_repair_candidates/h3_mechanic_upg_alt/source/mesh.glb",
    "h3_paokai": "artifacts/meshy_downloads/meshy71_repair_candidates/h3_paokai/source/mesh.glb",
    "h3_pegasus": "artifacts/meshy_downloads/meshy71_repair_candidates/h3_pegasus/source/mesh.glb",
}


def _profile_mesh(sid: str) -> Path | None:
    """Return an explicitly pinned non-Meshy mesh when the profile owns one."""
    profile = ROOT / "experiments/homm3_mocap_v2/asset_profile_boar_rider.py"
    if sid != "toa_boar_rider" or not profile.is_file():
        return None
    path = ROOT / "artifacts/homm3_mocap_v2/stronghold_takeover_review_v1/boar_rider_t2/generated.glb"
    return path if path.is_file() else None


def _meshy7_mesh(sid: str) -> Path | None:
    """Return a downloaded Meshy-7 mesh that still needs rigging."""
    path = DOWNLOADS / "meshy7_missing" / sid / "mesh.glb"
    return path if path.is_file() else None


def _canonical_smartrig(sid: str) -> tuple[Path, str | None]:
    """Return the semantic SmartRig path and any identity-alias note."""
    default = DOWNLOADS / f"{sid}_smartrigged.glb"
    preferred_name = CANONICAL_MESH_PREFERENCES.get(sid)
    if preferred_name:
        preferred = DOWNLOADS / preferred_name
        if preferred.is_file():
            return preferred, "semantic_filename_alias"
    return default, None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_source_replacement(sid: str, image: Path | None) -> Path | None:
    """Return a task-backed replacement only when its copied source matches the selected image."""
    relative = VERIFIED_SOURCE_REPLACEMENTS.get(sid)
    if not relative or image is None or not image.is_file():
        return None
    mesh = ROOT / relative
    source = mesh.parent / "source.png"
    metadata = mesh.parent / "candidate_meta.json"
    if not mesh.is_file() or not source.is_file() or not metadata.is_file():
        return None
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    policy = payload.get("policy") or {}
    if payload.get("status") != "SUCCEEDED" or policy.get("unitSid") != sid:
        return None
    if _sha256_file(source) != _sha256_file(image):
        return None
    if Path(str(policy.get("sourceImage") or "")).name != image.name:
        return None
    return mesh


def _refused_canonical_smartrig(sid: str, path: Path) -> bool:
    expected = REFUSED_CANONICAL_SMARTRIG_SHA256.get(sid)
    return bool(expected) and path.is_file() and _sha256_file(path) == expected


def _quarantined_demo_mesh(sid: str) -> Path | None:
    matches = sorted(DOWNLOADS.glob(f"_{sid}_smartrigged*.glb"))
    return matches[0] if matches else None


def _quarantine_evidence(sid: str) -> list[str]:
    names = {
        path.name
        for path in DOWNLOADS.iterdir()
        if path.name.startswith(f"_{sid}") and path.suffix.lower() == ".glb"
    }
    canonical = DOWNLOADS / f"{sid}_smartrigged.glb"
    if _refused_canonical_smartrig(sid, canonical):
        names.add(canonical.name)
    return sorted(names)


def _custom_rig(sid: str) -> tuple[Path | None, str | None]:
    """Return a separately authored rig candidate without promoting it."""
    if sid == "toa_boar_rider":
        path = ROOT / "artifacts/homm3_mocap_v2/boar_rider_astra_rig_v1/boar_rider_smartrigged.glb"
        return (path if path.is_file() else None, "astra_blender_envelope")
    path = ROOT / "artifacts/homm3_mocap_v2/meshy7_astra_batch" / sid / f"{sid}_smartrigged.glb"
    if path.is_file():
        return path, "astra_blender_envelope"
    for relative, kind in CUSTOM_RIG_PREFERENCES.get(sid, ()):
        retry = ROOT / relative
        if retry.is_file():
            return retry, kind
    return None, None


def _input_image(sid: str) -> tuple[Path | None, str | None]:
    # Prefer the named AAA upscale whenever it exists.  The extracted frame
    # zero still is a valid fallback for units without an upscale, but it must
    # not silently win just because it was extracted later for a Meshy retry.
    main = UPSCALE / f"{sid}.png"
    if main.is_file():
        return main, "aaa_upscale"
    remaining = REMAINING_STILLS / f"{sid}.png"
    if remaining.is_file():
        return remaining, "meshy_remaining_still"
    # The three Conflux elemental upscales were blocked by the image generator,
    # but the preserved nearest/lanczos source references remain valid Meshy
    # image-to-3D inputs.
    for kind in ("lanczos", "nearest", "orig256", "source"):
        ref = UPSCALE / "refs" / f"{sid}__{kind}.png"
        if ref.is_file():
            return ref, f"refs_{kind}"
    return None, None


def build_inventory() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    units = [str(row["unitSid"]) for row in manifest["units"]]
    neutral = json.loads(NEUTRAL_CATALOG.read_text(encoding="utf-8"))
    # Keep the source-defined neutral catalog in the same audit.  Four neutral
    # entries are already in the import manifest; the set union avoids a
    # duplicate while exposing the thirteen unregistered neutral slots.
    units.extend(str(row["sid"]) for row in neutral.get("units", []))
    units = list(dict.fromkeys(units))
    records: list[dict] = []
    for sid in units:
        smartrig, smartrig_alias = _canonical_smartrig(sid)
        profile_mesh = _profile_mesh(sid)
        meshy7_mesh = _meshy7_mesh(sid)
        custom_rig, custom_rig_kind = _custom_rig(sid)
        image, image_kind = _input_image(sid)
        replacement = _verified_source_replacement(sid, image)
        if replacement is not None:
            status = "mesh_present_smartrig_missing"
            mesh = replacement
            mesh_kind = "meshy7_generated_mesh_replacement"
            smartrig = Path()
            smartrig_alias = "verified_source_candidate"
        elif smartrig.is_file() and not _refused_canonical_smartrig(sid, smartrig):
            status = "smartrig_present"
            mesh = smartrig
            mesh_kind = "canonical_smartrig"
        elif _refused_canonical_smartrig(sid, smartrig) or (
            sid in REFUSED_CANONICAL_SMARTRIG_SHA256 and _quarantined_demo_mesh(sid) is not None
        ):
            status = "mesh_present_smartrig_missing"
            mesh = smartrig if _refused_canonical_smartrig(sid, smartrig) else _quarantined_demo_mesh(sid)
            mesh_kind = "quarantined_meshy_demo"
            smartrig_alias = "refused_meshy_demo"
            smartrig = Path()
        elif profile_mesh is not None:
            status = "mesh_present_smartrig_missing"
            mesh = profile_mesh
            mesh_kind = "pinned_profile_mesh"
        elif meshy7_mesh is not None:
            status = "mesh_present_smartrig_missing"
            mesh = meshy7_mesh
            mesh_kind = "meshy7_generated_mesh"
        else:
            status = "mesh_missing"
            mesh = None
            mesh_kind = None
        records.append(
            {
                "unitSid": sid,
                "status": status,
                "mesh": str(mesh.resolve()).replace("\\", "/") if mesh else None,
                "meshKind": mesh_kind,
                "smartrig": str(smartrig.resolve()).replace("\\", "/") if smartrig.is_file() else None,
                "smartrigIdentity": smartrig_alias,
                "customRig": str(custom_rig.resolve()).replace("\\", "/") if custom_rig else None,
                "customRigKind": custom_rig_kind if custom_rig else None,
                "imageInput": str(image.resolve()).replace("\\", "/") if image else None,
                "imageInputKind": image_kind,
                "quarantineEvidence": _quarantine_evidence(sid),
            }
        )
    counts = {
        "smartrigPresent": sum(r["status"] == "smartrig_present" for r in records),
        "meshPresentSmartrigMissing": sum(r["status"] == "mesh_present_smartrig_missing" for r in records),
        "customRigPresent": sum(bool(r.get("customRig")) for r in records),
        "meshMissing": sum(r["status"] == "mesh_missing" for r in records),
        "meshMissingWithImageInput": sum(bool(r["status"] == "mesh_missing" and r["imageInput"]) for r in records),
        "meshMissingWithoutImageInput": sum(bool(r["status"] == "mesh_missing" and not r["imageInput"]) for r in records),
    }
    return {
        "schema": "homm3-mesh-coverage.v1",
        "proof": "source/static-inventory",
        "manifest": str(MANIFEST.resolve()).replace("\\", "/"),
        "neutralCatalog": str(NEUTRAL_CATALOG.resolve()).replace("\\", "/"),
        "downloadDir": str(DOWNLOADS.resolve()).replace("\\", "/"),
        "unitCount": len(records),
        "counts": counts,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/meshy_downloads/homm3_mesh_coverage.json")
    args = parser.parse_args()
    output = args.out if args.out.is_absolute() else ROOT / args.out
    inventory = build_inventory()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(output), "unitCount": inventory["unitCount"], "counts": inventory["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
