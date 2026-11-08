"""Render the original and authored-frame cyclic g00 context captures."""
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
from preview_eagle_reference_comparison import reference_conversion
from run_eagle_reference_capture_comparison import verify_source_identity
from run_eagle_cyclic_context_comparison import context_mapping
from native_donor_position_replay import replay_native_donor
from pin import sha256_file
from run_native_donor_capture_comparison import (
    SIZE,
    frozen_camera,
    grid,
    labeled,
    validate_capture,
    write_preview,
)
from vendor_reference import load_complete_package

CLIP = "g00_move"
REF_SEQ = "Eagle#Eagle-Landing/y15"
POLICIES = ("original", "cyclic")
AUTHORED_INDICES = tuple(range(12, 18))


def _policy(row: dict, corpus: dict) -> str:
    value = corpus.get("provenance", {}).get("policy")
    if value in POLICIES:
        return value
    raise ValueError(f"unsupported context policy: {value!r}")


def _load_old_identity(corpus: dict, row: dict) -> tuple[dict, dict, Path]:
    old_path = Path(corpus["provenance"]["oldCorpus"])
    if sha256_file(old_path) != corpus["provenance"]["oldCorpusSha256"]:
        raise ValueError("original corpus hash drift")
    old = json.loads(old_path.read_text(encoding="utf-8"))
    old_rows = {item["key"]: item for item in old["captures"]}
    if len(old_rows) != len(old['captures']) or CLIP not in old_rows:
        raise ValueError("old corpus does not contain the requested g00_move row")
    return old, old_rows[CLIP], old_path


def _check_source_frames(
    row: dict,
    old_row: dict,
    mapping: list[int],
    old_raw: Path,
    new_raw: Path,
) -> None:
    if row["frames"] != old_row["frames"]:
        raise ValueError("output authored frame paths differ from original corpus")
    if row["sourceIndices"] != old_row["sourceIndices"]:
        raise ValueError("output authored source indices differ from original corpus")
    old_frames = sorted(old_raw.parent.parent.joinpath("frames").glob("*.png"))
    new_frames = sorted(new_raw.parent.parent.joinpath("frames").glob("*.png"))
    if len(old_frames) == 0:
        raise FileNotFoundError("original numbered frame directory is empty")
    if len(mapping) != len(new_frames):
        raise ValueError("context mapping length does not match output numbered frames")
    for destination, source in zip(new_frames, mapping):
        if source < 0 or source >= len(old_frames):
            raise ValueError("cyclic mapping points outside original numbered frames")
        if sha256_file(destination) != sha256_file(old_frames[source]):
            raise ValueError("cyclic numbered PNG differs from mapped original frame")


def run(input_report: Path, output: Path) -> dict:
    started = time.perf_counter()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    report = json.loads(input_report.read_text(encoding="utf-8"))
    output_paths = [Path(value) for value in report.get("outputs", [])]
    if len(output_paths) != 4:
        raise ValueError("input report requires four outputs")

    donor = load_donor_package()
    native = donor["package"]
    bind = bind_world_matrices(native["offsets"], native["parents"])
    inverse = inverse_bind_matrices(bind)
    package = load_complete_package("zoo", REF_SEQ)
    if package["jointNames"] != native["jointNames"]:
        raise ValueError("reference package names differ from native donor")
    if not np.array_equal(package["parents"], native["parents"]):
        raise ValueError("reference package parents differ from native donor")
    if not np.array_equal(package["offsets"], native["offsets"]):
        raise ValueError("reference package offsets differ from native donor")
    conversion = reference_conversion(package)

    cases: dict[tuple[str, str], dict[str, tuple[dict, np.ndarray, dict]]] = {}
    source_hashes: dict[str, str] = {str(input_report.resolve()): sha256_file(input_report)}
    implementation_files = (
        "preview_eagle_cyclic_context_comparison.py",
        "preview_eagle_reference_comparison.py",
        "run_eagle_reference_capture_comparison.py",
        "run_eagle_cyclic_context_comparison.py",
        "native_donor_coordinates.py",
        "native_donor_position_replay.py",
        "run_native_donor_capture_comparison.py",
        "direction_retarget.py",
        "donor_eagle.py",
        "eagle_preview.py",
        "mesh_preview.py",
        "shared_camera.py",
    )

    for corpus_path in output_paths:
        source_hashes[str(corpus_path.resolve())] = sha256_file(corpus_path)
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        if corpus.get("package", {}).get("refSeq") != REF_SEQ:
            raise ValueError("all context cases must use the y15 reference")
        rows = {row["key"]: row for row in corpus.get("captures", [])}
        if set(rows) != {CLIP} or len(corpus['captures']) != 1:
            raise ValueError("each output corpus must contain exactly g00_move")
        row = rows[CLIP]
        policy = _policy(row, corpus)
        old, old_row, old_path = _load_old_identity(corpus, row)
        verify_source_identity(old, old_row)
        if corpus['unit'] != old['unit'] or row['sourceIndices'] != list(AUTHORED_INDICES):
            raise ValueError('unit or authored slice differs from original')
        old_raw = Path(old_row["capture"])
        source_hashes[str(old_path.resolve())] = sha256_file(old_path)
        source_hashes[str(old_raw.resolve())] = sha256_file(old_raw)
        if source_hashes[str(old_raw.resolve())] != old_row['captureSha256']:
            raise ValueError('old raw capture hash drift')
        mapping = corpus['provenance']['mapping']
        raw_path = Path(row["capture"])
        _check_source_frames(row, old_row, mapping, old_raw, raw_path)
        source_hashes[str(raw_path.resolve())] = sha256_file(raw_path)
        if source_hashes[str(raw_path.resolve())] != row['captureSha256']:
            raise ValueError('fresh raw capture hash drift')
        with np.load(raw_path, allow_pickle=False) as raw, np.load(old_raw, allow_pickle=False) as original:
            expected_mapping = context_mapping(len(original['image_embed']), old_row['sourceIndices'], policy)
            if not np.array_equal(mapping, expected_mapping):
                raise ValueError('mapping does not implement declared context policy')
            if not np.array_equal(raw['ref_image_embed'], package['refImageEmbed']):
                raise ValueError('reference embedding drift')
            if list(raw["joint_names"].astype(str)) != native["jointNames"]:
                raise ValueError("capture names differ from native donor")
            if not np.array_equal(raw["parents"], original["parents"]):
                raise ValueError("capture parents differ from original capture")
            if not np.array_equal(raw["offsets"], original["offsets"]):
                raise ValueError("capture offsets differ from original capture")
            expected_embed = original["image_embed"][np.asarray(mapping, dtype=np.int64)]
            if not np.array_equal(raw["image_embed"], expected_embed):
                raise ValueError("capture embeddings do not equal mapped original embeddings")
            if policy == "original" and not np.array_equal(raw["pred_position"], original["pred_position"]):
                raise ValueError("original policy prediction parity failed")
            if policy == "cyclic":
                if mapping[12:18] != list(AUTHORED_INDICES):
                    raise ValueError("cyclic context does not preserve authored g00 slice mapping")
                if not np.array_equal(raw["image_embed"][12:18], original["image_embed"][12:18]):
                    raise ValueError("cyclic authored embedding slice changed")
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
        group = cases.setdefault(key, {})
        if policy in group:
            raise ValueError(f"duplicate {policy} case for {key}")
        group[policy] = (row, positions, replay)

    if {key[0] for key in cases} != {'h3_thunderbird','h3_shahrokh'} or any(set(group) != set(POLICIES) for group in cases.values()):
        raise ValueError("requires original and cyclic g00_move cases for both units")

    arrays_for_camera = []
    for group in cases.values():
        for _, positions, replay in group.values():
            arrays_for_camera.extend((positions, replay["meshes"]))
    camera = frozen_camera(arrays_for_camera)
    obj = donor["obj"]
    corners = obj["faces"].reshape(-1)
    triangles = np.arange(len(corners)).reshape(-1, 3)
    uvs = obj["uvs"][obj["faceUvs"].reshape(-1)]
    with Image.open(donor["texturePath"]) as image:
        texture = np.asarray(image.convert("RGB"))

    output.mkdir(parents=True)
    result = {
        "schema": "homm3.eagle-cyclic-context-preview.v1",
        "accepted": False,
        "proof": "generated native donor preview only",
        "inputReport": str(input_report.resolve()),
        "inputHashes": source_hashes,
        "reference": REF_SEQ,
        "conversion": conversion,
        "referencePackageHashes": package['fileSha256'],
        "cameraNote": "DEF camera independent; no pixel alignment claim",
        "camera": camera,
        "donorFileHashes": donor["fileSha256"],
        "implementationHashes": {name: sha256_file(Path(__file__).parent / name) for name in implementation_files},
        "cases": {},
    }
    for (unit, key), group in cases.items():
        directory = output / unit
        directory.mkdir(exist_ok=True)
        original_row = group["original"][0]
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
                    replay = group[policy][2]
                    panel = _mesh(camera, view, replay["meshes"][index][corners], triangles, uvs, texture)
                    panels.append(labeled(panel, f"{policy} / {view}"))
            frames.append(grid(panels, 3))
        write_preview(directory / key, frames)
        metrics = {}
        arrays = {}
        for policy in POLICIES:
            replay = group[policy][2]
            positions = group[policy][1]
            metrics[policy] = {
                "frameCount": int(len(positions)),
                "endpointResidualMax": float(max(replay["endpointResidualMax"])),
                "lengthErrorMax": float(max(replay["rawLengthErrorMax"])),
                "directionErrorMaxDeg": float(max(replay["directionErrorMaxDeg"])),
                "jointExcursionFromFrame0Max": {
                    name: float(np.linalg.norm(positions[:,j]-positions[0,j],axis=-1).max())
                    for j,name in enumerate(native['jointNames'])},
                "meanJointDifferenceFromOriginal": float(np.linalg.norm(positions-group['original'][1],axis=-1).mean()),
            }
            arrays[f"{policy}_positions"] = positions
            arrays[f"{policy}_joint_world"] = replay["jointWorld"]
        np.savez_compressed(directory / f"{key}.npz", **arrays)
        result["cases"][f"{unit}:{key}"] = metrics
    result["elapsedSeconds"] = time.perf_counter() - started
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.input_report, arguments.output), indent=2))
