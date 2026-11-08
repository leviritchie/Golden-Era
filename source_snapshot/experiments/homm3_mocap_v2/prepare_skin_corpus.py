"""Materialize every authentic DEF group on one unchanged source canvas."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

from run_skin_weight_pilot import ROOT, _write_json, sha256_file, EVALUATION_CASES
from materialize_rife_source_frames import inventory_authentic_def_groups, load_nn_upscale_contract, nn_upscale_native_frame, def_group_name
from def_soft_shadow import cull_def_soft_shadow_rgba
from structured_profiles import current_profile_pin, require_profile_pin


def normalized_rgba(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        values, _ = cull_def_soft_shadow_rgba(np.asarray(image.convert("RGBA"), dtype=np.uint8))
        return values


def movement_context(by_group: dict) -> tuple[list[int], dict]:
    """Use only native-present movement groups; absence never invents a clip."""
    chain = [group for group in (20, 0, 21) if group in by_group]
    if chain and 0 not in by_group:
        raise ValueError("native movement transitions require an authored movement cycle")
    return chain, {"presentGroups": chain,
                   "absentTransitionGroups": [g for g in (20, 21) if g not in by_group],
                   "absenceReason": "not present in inventoried native DEF; no frames or clips manufactured"}


def prepare(source, output, canvas, *, unit="h3_roc", known_idle=None):
    """Prepare a corpus for ``unit`` and compare its idle plate byte-for-byte.

    The ROC defaults are retained for existing callers, but are explicit
    compatibility defaults rather than being inferred from the source path.
    New units must provide their own known idle plate.
    """
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    profile_pin = current_profile_pin(unit)
    if not isinstance(unit, str) or not re.fullmatch(r"h3_[A-Za-z0-9][A-Za-z0-9_.-]*", unit):
        raise ValueError(f"unit must match h3_<name>, got {unit!r}")
    if known_idle is None:
        if unit != "h3_roc":
            raise ValueError("known_idle is required for non-ROC units")
        known_idle = Path(EVALUATION_CASES["roc_attack"].idle)
    known_idle = Path(known_idle).resolve()
    if not known_idle.is_file() or known_idle.suffix.lower() != ".png":
        raise ValueError("known_idle must be an existing PNG path")
    groups = inventory_authentic_def_groups(source)
    if 2 not in groups:
        raise ValueError("source has no authored idle group")
    contract = load_nn_upscale_contract(canvas)
    clips, provenance = [], []
    output.mkdir(parents=True)
    for group, paths in sorted(groups.items()):
        # Retain numeric identities even where historical semantic names are uncertain.
        key = f"g{group:02d}_{def_group_name(group)}"
        frames = []
        for index, path in enumerate(paths):
            with Image.open(path) as raw:
                upscaled = nn_upscale_native_frame(raw, contract)
            values, culled = cull_def_soft_shadow_rgba(np.asarray(upscaled, dtype=np.uint8))
            if not np.any(values[..., 3]):
                raise ValueError(f"empty foreground in {path}")
            dest = output / key / f"{index:03d}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(values).save(dest)
            frames.append(str(dest.resolve()))
            provenance.append({"group": group, "frame": index, "source": str(path), "sourceSha256": sha256_file(path),
                               "prepared": str(dest.resolve()), "preparedSha256": sha256_file(dest), "shadowPixelsRemoved": int(culled)})
        clips.append({"key": key, "group": group, "frames": frames})
    by_group = {clip["group"]: clip["frames"] for clip in clips}
    movement_chain, movement_policy = movement_context(by_group)
    idle_frames = by_group[2]
    for clip in clips:
        group = clip["group"]
        before, after = list(idle_frames), [] if group in (5, 6) else list(idle_frames)
        # Movement clips share the actual start -> cycle -> stop context.
        # These extra frames are context, not duplicated fitting targets.
        if group in (0, 20, 21):
            chain = movement_chain
            position = chain.index(group)
            before += [frame for part in chain[:position] for frame in by_group[part]]
            after = [frame for part in chain[position + 1:] for frame in by_group[part]] + list(idle_frames)
        clip["contextBefore"], clip["contextAfter"] = before, after
    idle = idle_frames[0]
    # Historical NN plates retain DEF shadows; compare the same foreground
    # normalization on both sides, never accept other pixel differences.
    if not np.array_equal(normalized_rgba(idle), normalized_rgba(known_idle)):
        raise ValueError("corpus idle differs from known-good registration plate")
    result = {"unit": unit, "idle": idle, "clips": clips, "sourceDirectory": str(source),
              "canvasContract": str(canvas), "canvasSha256": sha256_file(canvas), "frameCount": len(provenance),
              "sourceFrameMs": 1000 / 12, "allGroupsIncluded": True, "frames": provenance,
              "movementContext": movement_policy,
              "transitionPolicy": "retain every authored frame including attack startup/return; no inferred motion frames"}
    require_profile_pin(unit, profile_pin)
    result.update(profile_pin)
    _write_json(output / "manifest.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--unit", default="h3_roc", help="asset unit id (h3_<name>); defaults to h3_roc for compatibility")
    parser.add_argument("--known-idle", type=Path, help="known-good prepared idle PNG; required except for the ROC compatibility default")
    parser.add_argument("--canvas", type=Path, default=ROOT / "artifacts/pose_picker_runs/h3_roc/nn_upscale/upscale_meta.json")
    args = parser.parse_args()
    result = prepare(args.source.resolve(), args.output.resolve(), args.canvas.resolve(), unit=args.unit, known_idle=args.known_idle)
    print(json.dumps({"groups": len(result["clips"]), "frames": result["frameCount"], "manifest": str(args.output / "manifest.json")}))
