"""Diagnostic Eagle cadence comparison using the frozen authored context."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
import shutil

import numpy as np

from capture_candidates import require_frozen_package
from intermediate_capture import run_capture
from model_runner import load_model
from paths import REPO
from pin import sha256_file
from run_eagle_reference_capture_comparison import verify_source_identity
from run_mocap_baseline import _gpu_lock_waiting

CLIP = "g00_move"
POLICIES = ("original", "hold2")
UNITS = {"h3_thunderbird": 30, "h3_shahrokh": 29}


def context_mapping(length, policy):
    """Return source-frame indices for one full context under a cadence policy."""
    if not isinstance(length, (int, np.integer)) or isinstance(length, bool) or length <= 0:
        raise ValueError("length must be a positive integer")
    if policy == "original":
        return np.arange(int(length), dtype=np.int64)
    if policy == "hold2":
        return np.repeat(np.arange(int(length), dtype=np.int64), 2)
    raise ValueError(f"unknown cadence policy: {policy}")


def _load_old(path: Path):
    corpus = json.loads(path.read_text())
    if corpus.get("package", {}).get("refSeq") != "Eagle#Eagle-Landing/y15":
        raise ValueError("old corpus must use frozen Eagle y15")
    if corpus.get("unit") not in UNITS:
        raise ValueError("corpus unit must be Thunderbird or Shahrokh")
    rows = [row for row in corpus.get("captures", []) if row.get("key") == CLIP]
    if len(rows) != 1:
        raise ValueError("corpus must contain exactly one g00_move row")
    row = rows[0]
    identity = verify_source_identity(corpus, row)
    raw_path = Path(row["capture"])
    if sha256_file(raw_path) != row.get("captureSha256"):
        raise ValueError("old raw capture hash drift")
    with np.load(raw_path, allow_pickle=False) as raw:
        embed = np.asarray(raw["image_embed"], dtype=np.float32).copy()
        old_pred = np.asarray(raw["pred_position"]).copy()
        old_ref = np.asarray(raw["ref_image_embed"]).copy()
    numbered = sorted((raw_path.parent.parent / "frames").glob("*.png"))
    expected = UNITS[corpus["unit"]]
    if len(embed) != expected or len(numbered) != expected or row.get("sourceIndices") != list(range(12, 18)):
        raise ValueError("unexpected g00_move context inventory")
    return corpus, row, raw_path, numbered, embed, old_pred, old_ref, identity


def run(corpus_paths, output: Path):
    started = time.perf_counter()
    if len(corpus_paths) != 2:
        raise ValueError("exactly two --corpus inputs are required")
    if output.exists():
        raise FileExistsError("output must be absent")
    loaded = [_load_old(Path(path)) for path in corpus_paths]
    if {item[0]["unit"] for item in loaded} != set(UNITS):
        raise ValueError("requires exactly Thunderbird and Shahrokh corpora")

    import torch
    output.mkdir(parents=True)
    outputs = []
    with _gpu_lock_waiting(REPO):
        model = load_model(torch.device("cuda"))[0]
        for source_path, item in zip(corpus_paths, loaded):
            source_path = Path(source_path)
            corpus, row, raw_path, numbered, embed, old_pred, old_ref, identity = item
            unit = corpus["unit"]
            package = require_frozen_package(unit, role="primary")
            if package.get("refSeq") != corpus["package"]["refSeq"] or not np.array_equal(package["refImageEmbed"], old_ref):
                raise ValueError("frozen y15 package reference differs from original corpus")
            unit_dir = output / unit
            unit_dir.mkdir()
            for policy in POLICIES:
                mapping = context_mapping(len(embed), policy)
                policy_dir = unit_dir / policy
                frame_dir = policy_dir / CLIP / "frames"
                frame_dir.mkdir(parents=True)
                for target_index, source_index in enumerate(mapping.tolist()):
                    target = frame_dir / f"{target_index:06d}.png"
                    shutil.copy2(numbered[source_index], target)
                    if sha256_file(target) != identity["contextSha256"][source_index]:
                        raise ValueError("copied cadence frame hash mismatch")
                features = embed[mapping].copy()
                authored = np.asarray(row["sourceIndices"], dtype=np.int64)
                authored_positions = authored if policy == "original" else authored * 2
                if not np.array_equal(features[authored_positions], embed[authored]):
                    raise ValueError("authored embedding changed under cadence mapping")
                capture_dir = policy_dir / CLIP / "capture"
                report = run_capture(package=package, frames_dir=frame_dir, out_dir=capture_dir,
                                     image_embed=features, preprocess_meta=corpus["preprocess"],
                                     model=model, source_kind="authored_source_frame",
                                     title=f"{CLIP}:{policy}", compare_gt=False)
                fresh = capture_dir / "raw_capture.npz"
                with np.load(fresh, allow_pickle=False) as raw:
                    if not np.array_equal(raw["image_embed"], features):
                        raise ValueError("fresh cadence capture embeddings changed")
                    if not np.array_equal(raw["ref_image_embed"], old_ref):
                        raise ValueError("fresh cadence reference embedding changed")
                    if policy == "original" and not np.array_equal(raw["pred_position"], old_pred):
                        raise ValueError("fresh original baseline is not bit-exact")
                    baseline_error = (float(np.max(np.abs(raw["pred_position"] - old_pred)))
                                      if policy == "original" else None)
                after_count = int(len(mapping) - int(authored_positions[-1]) - 1)
                new_row = {
                    "key": CLIP,
                    "frames": list(row["frames"]),
                    "sourceIndices": authored_positions.tolist(),
                    "referenceIndex": row["referenceIndex"],
                    "contextBeforeCount": int(authored_positions[0]),
                    "contextAfterCount": after_count,
                    "contextFrameCount": int(len(mapping)),
                    "capture": str(fresh.resolve()),
                    "captureSha256": sha256_file(fresh),
                    "report": report,
                    "baselineMaxError": baseline_error,
                }
                new_corpus = {
                    "schema": "homm3.eagle-cadence-diagnostic.v1",
                    "unit": unit,
                    "package": corpus["package"],
                    "preprocess": corpus["preprocess"],
                    "captures": [new_row],
                    "provenance": {
                        "policy": policy,
                        "samplingIndices": mapping.tolist(),
                        "authoredSourceIndices": authored.tolist(),
                        "oldCorpus": str(Path(source_path).resolve()),
                        "oldCorpusSha256": sha256_file(source_path),
                        "oldRawCapture": str(raw_path.resolve()),
                        "oldRawCaptureSha256": sha256_file(raw_path),
                        "sourceIdentity": identity,
                        "diagnosticOnly": True,
                    },
                }
                corpus_out = policy_dir / "corpus.json"
                corpus_out.write_text(json.dumps(new_corpus, indent=2) + "\n")
                outputs.append(str(corpus_out.resolve()))
                print(f"{unit} {policy}: baseline max error {baseline_error}", flush=True)
    result = {
        "outputs": outputs,
        "elapsedSeconds": time.perf_counter() - started,
        "accepted": False,
        "proof": "diagnostic cadence captures only; no production changes",
        "implementationHash": sha256_file(Path(__file__).resolve()),
    }
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.corpus, args.output.resolve()), indent=2))
