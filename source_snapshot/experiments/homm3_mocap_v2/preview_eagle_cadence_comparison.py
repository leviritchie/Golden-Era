"""Render original versus held-twice Eagle movement cadence captures."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from donor_eagle import bind_world_matrices, inverse_bind_matrices, load_donor_package
from eagle_preview import _mesh
from native_donor_coordinates import apply_pose_to_native
from native_donor_position_replay import replay_native_donor
from pin import sha256_file
from preview_eagle_reference_comparison import reference_conversion
from run_eagle_reference_capture_comparison import verify_source_identity
from run_eagle_cadence_comparison import context_mapping
from run_native_donor_capture_comparison import SIZE, frozen_camera, grid, labeled, validate_capture, write_preview
from vendor_reference import load_complete_package

CLIP = "g00_move"
REF_SEQ = "Eagle#Eagle-Landing/y15"
POLICIES = ("original", "hold2")


def _load_old(corpus: dict, row: dict) -> tuple[dict, dict, Path]:
    provenance = corpus.get("provenance", {})
    old_path = Path(provenance["oldCorpus"])
    if sha256_file(old_path) != provenance["oldCorpusSha256"]:
        raise ValueError("original corpus hash drift")
    old = json.loads(old_path.read_text(encoding="utf-8"))
    rows = {item["key"]: item for item in old.get("captures", [])}
    if CLIP not in rows or len(rows) != len(old['captures']):
        raise ValueError("old corpus must contain unique clips including g00_move")
    old_row = rows[CLIP]
    if row["frames"] != old_row["frames"]:
        raise ValueError("authored frame paths changed")
    return old, old_row, old_path


def _verify_mapping(
    policy: str,
    mapping: list[int],
    new_row: dict,
    old_row: dict,
    old_raw: Path,
    new_raw: Path,
    context_hashes: list[str],
) -> None:
    if policy not in POLICIES:
        raise ValueError(f"unsupported cadence policy: {policy!r}")
    expected_indices = np.asarray(old_row['sourceIndices']) * (1 if policy == 'original' else 2)
    if not np.array_equal(new_row['sourceIndices'], expected_indices):
        raise ValueError("authored source indices do not match cadence policy")
    old_frames = sorted(old_raw.parent.parent.joinpath("frames").glob("*.png"))
    new_frames = sorted(new_raw.parent.parent.joinpath("frames").glob("*.png"))
    if len(mapping) != len(new_frames) or len(old_frames) != len(context_hashes):
        raise ValueError("mapping, source-frame hashes, and numbered frames disagree")
    if not np.array_equal(mapping, context_mapping(len(old_frames), policy)):
        raise ValueError("mapping does not implement declared cadence policy")
    if any(p.name != f'{i:06d}.png' for i,p in enumerate(new_frames)):
        raise ValueError('output PNG numbering differs')
    for destination, source in zip(new_frames, mapping):
        if source < 0 or source >= len(old_frames):
            raise ValueError("mapping points outside original context")
        if sha256_file(destination) != context_hashes[source]:
            raise ValueError("numbered PNG hash differs from original mapped context")
    authored = np.asarray(new_row["sourceIndices"], dtype=np.int64)
    if not np.array_equal(np.asarray(mapping, dtype=np.int64)[authored], np.asarray(old_row["sourceIndices"], dtype=np.int64)):
        raise ValueError("authored output selection does not map to original authored frames")


def run(input_report: Path, output: Path) -> dict:
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    input_payload = json.loads(input_report.read_text(encoding="utf-8"))
    output_paths = [Path(value) for value in input_payload.get("outputs", [])]
    if len(output_paths) != 4:
        raise ValueError("cadence report must contain exactly four corpus outputs")

    donor = load_donor_package()
    native = donor["package"]
    bind = bind_world_matrices(native["offsets"], native["parents"])
    inverse = inverse_bind_matrices(bind)
    package = load_complete_package("zoo", REF_SEQ)
    if package["jointNames"] != native["jointNames"] or not np.array_equal(package["parents"], native["parents"]):
        raise ValueError("y15 reference hierarchy differs from native donor")
    if not np.array_equal(package["offsets"], native["offsets"]):
        raise ValueError("y15 reference offsets differ from native donor")
    conversion = reference_conversion(package)
    cases: dict[tuple[str, str], tuple[dict, np.ndarray, dict]] = {}
    hashes = {str(input_report.resolve()): sha256_file(input_report)}

    for corpus_path in output_paths:
        hashes[str(corpus_path.resolve())] = sha256_file(corpus_path)
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        if corpus.get("package", {}).get("refSeq") != REF_SEQ:
            raise ValueError("cadence corpus does not use y15")
        rows = {row["key"]: row for row in corpus.get("captures", [])}
        if set(rows) != {CLIP} or len(corpus['captures']) != 1:
            raise ValueError("each cadence corpus must contain only g00_move")
        row = rows[CLIP]
        policy = corpus.get("provenance", {}).get("policy")
        if policy not in POLICIES:
            raise ValueError(f"missing or unsupported exact policy: {policy!r}")
        old, old_row, old_path = _load_old(corpus, row)
        if corpus['unit'] != old['unit']:
            raise ValueError('unit identity differs from original')
        old_raw = Path(old_row["capture"])
        raw_path = Path(row["capture"])
        hashes[str(old_path.resolve())] = sha256_file(old_path)
        hashes[str(old_raw.resolve())] = sha256_file(old_raw)
        hashes[str(raw_path.resolve())] = sha256_file(raw_path)
        if hashes[str(old_raw.resolve())] != old_row['captureSha256'] or hashes[str(raw_path.resolve())] != row['captureSha256']:
            raise ValueError('raw capture hash drift')
        with np.load(old_raw, allow_pickle=False) as old_data:
            old_embed = np.asarray(old_data["image_embed"]).copy()
            old_pred = np.asarray(old_data["pred_position"]).copy()
        identity = verify_source_identity(old,old_row)
        mapping = corpus['provenance']['samplingIndices']
        if np.asarray(mapping).dtype.kind not in 'iu':
            raise ValueError('mapping must contain integer indices')
        _verify_mapping(policy, mapping, row, old_row, old_raw, raw_path, identity["contextSha256"])
        with np.load(raw_path, allow_pickle=False) as raw:
            if not np.array_equal(raw['ref_image_embed'],package['refImageEmbed']):
                raise ValueError('reference embedding drift')
            if not np.array_equal(raw["image_embed"], old_embed[np.asarray(mapping, dtype=np.int64)]):
                raise ValueError("capture embeddings differ from mapped original embeddings")
            if policy == "original" and not np.array_equal(raw["pred_position"], old_pred):
                raise ValueError("original prediction is not exact")
            positions = validate_capture(raw, row, native)
            positions = apply_pose_to_native(positions, conversion, bind[0, :3, 3])
            replay = replay_native_donor(
                captured_positions=positions,
                donor_offsets=native["offsets"],
                parents=native["parents"],
                names=native["jointNames"],
                vertices=donor["obj"]["vertices"],
                weights=donor["weights"],
                inverse_bind=inverse,
            )
        key = (corpus["unit"], CLIP)
        if (key[0], policy) in cases:
            raise ValueError(f"duplicate {key[0]} {policy} case")
        cases[(key[0], policy)] = (row, positions, replay)

    units = {unit for unit, _ in cases}
    if units != {"h3_thunderbird", "h3_shahrokh"}:
        raise ValueError("requires Thunderbird and Shahrokh")
    for unit in units:
        if {(unit, policy) for policy in POLICIES} - set(cases):
            raise ValueError(f"missing cadence policy for {unit}")

    camera = frozen_camera([replay["meshes"] for _, _, replay in cases.values()])
    obj = donor["obj"]
    corners = obj["faces"].reshape(-1)
    triangles = np.arange(len(corners)).reshape(-1, 3)
    uvs = obj["uvs"][obj["faceUvs"].reshape(-1)]
    with Image.open(donor["texturePath"]) as image:
        texture = np.asarray(image.convert("RGB"))

    output.mkdir(parents=True)
    result = {
        "schema": "homm3.eagle-cadence-preview.v1",
        "accepted": False,
        "proof": "generated native donor preview only",
        "reference": REF_SEQ,
        "inputReport": str(input_report.resolve()),
        "inputHashes": hashes,
        "camera": camera,
        "donorFileHashes": donor["fileSha256"],
        "referencePackageHashes": package['fileSha256'],
        "conversion": conversion,
        "cameraNote": "DEF camera independent; no pixel alignment claim",
        "implementationHashes": {name:sha256_file(Path(__file__).parent/name) for name in
            ('preview_eagle_cadence_comparison.py','run_eagle_cadence_comparison.py',
             'preview_eagle_reference_comparison.py','run_eagle_reference_capture_comparison.py',
             'native_donor_coordinates.py','native_donor_position_replay.py',
             'run_native_donor_capture_comparison.py','direction_retarget.py',
             'donor_eagle.py','eagle_preview.py','mesh_preview.py','shared_camera.py')},
        "cases": {},
    }
    for unit in sorted(units):
        directory = output / unit
        directory.mkdir(exist_ok=True)
        original_row, _, _ = cases[(unit, "original")]
        sprites = [Image.open(Path(path)).convert("RGBA") for path in original_row["frames"]]
        scale = 0.9 * min(SIZE / max(sprite.width for sprite in sprites), SIZE / max(sprite.height for sprite in sprites))
        frames = []
        for index, sprite in enumerate(sprites):
            source = Image.new("RGB", (SIZE, SIZE), (245, 245, 247))
            resized = sprite.resize((round(sprite.width * scale), round(sprite.height * scale)), Image.Resampling.NEAREST)
            source.paste(resized, ((SIZE - resized.width) // 2, (SIZE - resized.height) // 2), resized)
            panels = []
            for view in ('front','side'):
                panels.append(labeled(source, 'DEF / independent camera'))
                for policy in POLICIES:
                    replay = cases[(unit, policy)][2]
                    panel = _mesh(camera, view, replay["meshes"][index][corners], triangles, uvs, texture)
                    panels.append(labeled(panel, f"{policy} / {view}"))
            frames.append(grid(panels, 3))
        write_preview(directory / CLIP, frames)
        metrics = {}
        arrays = {}
        original_positions = cases[(unit, "original")][1]
        for policy in POLICIES:
            positions = cases[(unit, policy)][1]
            replay = cases[(unit, policy)][2]
            metrics[policy] = {
                "frameCount": int(len(positions)),
                "meanPositionDifferenceFromOriginal": float(np.linalg.norm(positions - original_positions, axis=-1).mean()),
                "maxPositionDifferenceFromOriginal": float(np.linalg.norm(positions - original_positions, axis=-1).max()),
                "jointExcursionFromFrame0Max": {name:float(np.linalg.norm(positions[:,j]-positions[0,j],axis=-1).max())
                    for j,name in enumerate(native['jointNames'])},
            }
            arrays[f"{policy}_positions"] = positions
            arrays[f"{policy}_joint_world"] = replay["jointWorld"]
        np.savez_compressed(directory / f"{CLIP}.npz", **arrays)
        result["cases"][f"{unit}:{CLIP}"] = metrics
    result["elapsedSeconds"] = time.perf_counter() - started
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.input_report, args.output), indent=2))
