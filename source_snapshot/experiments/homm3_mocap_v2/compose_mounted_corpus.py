"""Compose two already-captured actor corpora into a mounted candidate.

Preparation NPZ contract (all arrays are explicit, no graph inference):
``mount_names, mount_parents, mount_capture_reference, mount_capture_offsets,
mount_fitted_offsets, rider_names, rider_parents, rider_capture_reference,
rider_capture_offsets, rider_fitted_offsets, combined_names, combined_parents,
combined_offsets, rider_held_indices, rider_held_rest, seat_parent, seat_offset``.
The actor roots are kept separate during reconstruction; only this stage adds
the rider root parent and seated held-lower-body policy.
"""
from __future__ import annotations
import argparse, json, shutil, time
from pathlib import Path
from typing import Any
import numpy as np
from reconstruct_adapted import reconstruct_adapted
from mesh_preview import fk_world_matrices
from pin import sha256_file


def _arr(data: Any, key: str, ndim: int | None = None) -> np.ndarray:
    if key not in data.files:
        raise ValueError(f"preparation is missing {key}")
    value = np.asarray(data[key])
    if ndim is not None and value.ndim != ndim:
        raise ValueError(f"{key} must have rank {ndim}, got {value.shape}")
    return value


def _names(data: Any, key: str) -> list[str]:
    return [str(x) for x in _arr(data, key).reshape(-1)]


def _load_corpus(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != "homm3.skin-corpus.v1":
        raise ValueError(f"unsupported corpus schema: {path}")
    return value


def _capture_rows(corpus: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {str(row["key"]): row for row in corpus.get("captures", [])}
    if not rows or len(rows) != len(corpus["captures"]):
        raise ValueError("corpus has no capture rows")
    return rows


def _check_alignment(mount: dict[str, Any], rider: dict[str, Any]) -> list[str]:
    m, r = _capture_rows(mount), _capture_rows(rider)
    if set(m) != set(r):
        raise ValueError("mount and rider clip keys are not identical")
    for key in m:
        if m[key].get("frames") != r[key].get("frames"):
            raise ValueError(f"mount/rider source frame mapping differs for {key}")
        if m[key].get("sourceIndices") != r[key].get("sourceIndices"):
            raise ValueError(f"mount/rider authored indices differ for {key}")
        for field in ("contextBeforeCount", "contextAfterCount", "referenceIndex"):
            if m[key].get(field) != r[key].get(field):
                raise ValueError(f"mount/rider context differs for {key}")
    return list(m)


def compose_mounted(mount_corpus: Path, rider_corpus: Path, preparation: Path, output: Path, source_manifest: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite output: {output}")
    mount, rider = _load_corpus(mount_corpus), _load_corpus(rider_corpus)
    clips = _check_alignment(mount, rider)
    source = json.loads(source_manifest.read_text())
    source_rows = {row["key"]: row for row in source["clips"]}
    if set(source_rows) != set(clips) or any(source_rows[k]["frames"] != _capture_rows(mount)[k]["frames"] for k in clips):
        raise ValueError("authored manifest timeline differs from actor captures")
    prep = np.load(preparation, allow_pickle=False)
    mn, rn = _names(prep, "mount_names"), _names(prep, "rider_names")
    cn, cp = _names(prep, "combined_names"), _arr(prep, "combined_parents", 1).astype(np.int64)
    mo, ro = _arr(prep, "mount_fitted_offsets", 2), _arr(prep, "rider_fitted_offsets", 2)
    if len(mn) != len(mo) or len(rn) != len(ro) or len(cn) != len(cp):
        raise ValueError("preparation names/parents/offset dimensions disagree")
    seat_parent = int(_arr(prep, "seat_parent").reshape(-1)[0]); seat_offset = _arr(prep, "seat_offset", 1).astype(float).reshape(3)
    held = _arr(prep, "rider_held_indices").astype(np.int64).reshape(-1)
    held_rest = _arr(prep, "rider_held_rest", 2).astype(float)
    if held_rest.shape[0] != len(rn) or np.any(held < 0) or np.any(held >= len(rn)):
        raise ValueError("rider held-rest policy dimensions are invalid")
    if cp[0] != -1 or seat_parent < 0 or seat_parent >= len(mn):
        raise ValueError("combined root/seat parent is invalid")
    output.mkdir(parents=True)
    out_rows = []
    for key in clips:
        mr, rr = _capture_rows(mount)[key], _capture_rows(rider)[key]
        mraw, rraw = np.load(mr["capture"], allow_pickle=False), np.load(rr["capture"], allow_pickle=False)
        if sha256_file(Path(mr["capture"])) != mr.get("captureSha256") or sha256_file(Path(rr["capture"])) != rr.get("captureSha256"):
            raise ValueError(f"capture hash mismatch for {key}")
        for raw, names, prefix in ((mraw, mn, "mount"), (rraw, rn, "rider")):
            if list(raw["joint_names"].astype(str)) != names or not np.array_equal(raw["parents"], prep[prefix+"_parents"]):
                raise ValueError("actor skeleton inventory differs from preparation")
        mrec = reconstruct_adapted(capture_positions=mraw["pred_position"], capture_reference_positions=_arr(prep, "mount_capture_reference", 2), capture_offsets=_arr(prep, "mount_capture_offsets", 2), fitted_offsets=mo, parents=_arr(prep, "mount_parents", 1).astype(np.int64), names=mn, hub_names=tuple(_names(prep, "mount_hubs")))
        rrec = reconstruct_adapted(capture_positions=rraw["pred_position"], capture_reference_positions=_arr(prep, "rider_capture_reference", 2), capture_offsets=_arr(prep, "rider_capture_offsets", 2), fitted_offsets=ro, parents=_arr(prep, "rider_parents", 1).astype(np.int64), names=rn, hub_names=tuple(_names(prep, "rider_hubs")))
        if len(mrec["localRotation"]) != len(rrec["localRotation"]):
            raise ValueError(f"capture frame count differs for {key}")
        local = np.concatenate([mrec["localRotation"], rrec["localRotation"]], axis=1)
        local[:, len(mn), :, :] = np.eye(3); local[:, len(mn) + held, :, :] = np.eye(3)
        offsets = _arr(prep, "combined_offsets", 2).astype(float).copy()
        if not np.allclose(offsets[len(mn)], seat_offset, atol=1e-12, rtol=0):
            raise ValueError('seat offset differs from canonical combined bind offsets')
        # Held authored positions become fixed local rest offsets, not a second
        # position stream; FK remains the sole source of composed positions.
        for rider_index in held:
            combined_index = len(mn) + int(rider_index)
            parent_index = int(_arr(prep, "rider_parents", 1)[int(rider_index)])
            if parent_index >= 0:
                held_offset = held_rest[int(rider_index)] - held_rest[parent_index]
                if not np.allclose(offsets[combined_index], held_offset, atol=1e-12, rtol=0):
                    raise ValueError('held rider rest differs from canonical combined bind offsets')
                # Combined offsets own the bind bytes. Re-subtracting translated
                # rest points introduces rounding differences, not a new pose.
        world = np.stack([fk_world_matrices(local_rotation=local[t], local_translation=offsets, parents=cp, root_world=mrec["jointWorld"][t, 0, :3, 3]) for t in range(len(local))])
        combined = world[:, :, :3, 3]
        frame_dir = output / key / "frames"; frame_dir.mkdir(parents=True)
        full = sorted((Path(mr["capture"]).parents[1] / "frames").glob("*.png"))
        if len(full) != len(local):
            raise ValueError("full context frame inventory differs from capture")
        for index, frame in enumerate(full): shutil.copy2(frame, frame_dir / f"{index:06d}.png")
        dest = output / key / "capture" / "composed_positions.npz"; dest.parent.mkdir(parents=True)
        np.savez(dest, pred_position=combined.astype(np.float64), local_rotation=local.astype(np.float64), joint_world=world.astype(np.float64), mount_joint_world=mrec["jointWorld"].astype(np.float64), rider_joint_world=rrec["jointWorld"].astype(np.float64), joint_names=np.asarray(cn), parents=cp, offsets=offsets, motionRepresentation=np.asarray("fixed_composed_fk_v1"), source_policy=np.asarray("composed_mount_plus_rider_seated"))
        out_rows.append({"key": key, "frames": mr["frames"], "capture": str(dest.resolve()), "captureSha256": sha256_file(dest), "sourceIndices": mr["sourceIndices"], "referenceIndex": mr["referenceIndex"], "contextBeforeCount": mr["contextBeforeCount"], "contextAfterCount": mr["contextAfterCount"]})
    corpus = {"schema": "homm3.skin-corpus.v1", "unit": mount["unit"].removesuffix("_mount"), "manifest": mount.get("manifest"), "manifestSha256": mount.get("manifestSha256"), "sourceFrames": mount.get("sourceFrames", {}), "package": {"kind": "composed", "mountCorpusSha256": sha256_file(mount_corpus), "riderCorpusSha256": sha256_file(rider_corpus), "preparationSha256": sha256_file(preparation)}, "captureCondition": "composed_not_raw_vendor", "motionRepresentation": "fixed_composed_fk_v1", "compositePolicy": "rider_root_parented_to_mount_seat; held_indices_are_authored_seated_rest; upper_body_from_rider_capture", "captures": out_rows, "createdAt": time.time()}
    corpus.update(manifest=str(source_manifest.resolve()), manifestSha256=sha256_file(source_manifest))
    (output / "corpus.json").write_text(json.dumps(corpus, indent=2), encoding="utf-8")
    return {"schema": "homm3.mounted-composition.v1", "corpus": str((output / "corpus.json").resolve()), "corpusSha256": sha256_file(output / "corpus.json"), "clipCount": len(out_rows)}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--mount-corpus", type=Path, required=True); parser.add_argument("--rider-corpus", type=Path, required=True); parser.add_argument("--preparation", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compose_mounted(args.mount_corpus, args.rider_corpus, args.preparation, args.output, args.source_manifest), indent=2))


if __name__ == "__main__": main()
