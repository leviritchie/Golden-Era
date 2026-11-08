"""<glb>.<stage>.json beside a delivery-stage output: the stage's source and output GLB sha256, so the emphasis gate's
delivery chain (validate_homm3_def_retarget_emphasis_contract.delivery_chain_errors) links every stage to the next
one instead of only checking that each ran on a new input. ground_glb.py and prop_floor_glb.py write the same keys.

StageResult is what every delivery stage's apply_bytes returns: the exact GLB bytes the stage writes, their sha, and
the sidecar it records. The stage CLIs commit() one result to disk; fleet_rebuild.py passes the bytes on to the next
stage in memory (the sha links are those same bytes' hashes) and writes the final GLB once
(docs/homm3_glb_patch_lane.md, in-memory stage fusion).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import NamedTuple


class StageResult(NamedTuple):
    data: bytes          # the GLB the stage writes, byte for byte
    source_sha: str      # sha256 of the stage's input bytes
    output_sha: str      # sha256 of data
    suffix: str          # the sidecar suffix (<glb>.<suffix>.json), a DELIVERY_STAGES entry
    sidecar: dict        # the sidecar's content
    report: dict         # the stage's one-line summary (what its CLI prints)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def record(schema: str, unit: str, out_glb: Path, source_sha: str, output_sha: str) -> dict:
    return {"schema": schema, "unit": unit, "outputGlb": str(out_glb), "sourceGlbSha256": source_sha,
            "outputGlbSha256": output_sha}


def result(data: bytes, source: bytes, suffix: str, sidecar: dict, report: dict) -> StageResult:
    """A StageResult whose recorded sha pair is checked against the bytes themselves (fail closed)."""
    rs, os_ = sha(source), sha(data)
    if sidecar.get("sourceGlbSha256") != rs or sidecar.get("outputGlbSha256") != os_:
        raise SystemExit(f"{suffix}: the sidecar's sha pair is not the stage's own input/output bytes")
    return StageResult(bytes(data), rs, os_, suffix, sidecar, report)


def sidecar_path(out_glb: Path, suffix: str) -> Path:
    return Path(str(out_glb) + f".{suffix}.json")


def write_sidecar(out_glb: Path, suffix: str, sidecar: dict) -> Path:
    p = sidecar_path(out_glb, suffix)
    p.write_text(json.dumps(sidecar, indent=1) + "\n", encoding="utf-8")
    return p


def commit(out_glb: Path, res: StageResult) -> None:
    """A stage CLI's write: the GLB (tmp + atomic replace), then its sidecar."""
    out_glb = Path(out_glb)
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_glb.with_name(out_glb.name + f".{res.suffix}.tmp")
    tmp.write_bytes(res.data)
    os.replace(tmp, out_glb)
    write_sidecar(out_glb, res.suffix, res.sidecar)


def write(out_glb: Path, suffix: str, schema: str, unit: str, source_sha: str, output_sha: str) -> Path:
    return write_sidecar(out_glb, suffix, record(schema, unit, out_glb, source_sha, output_sha))
