"""The patch base: a unit's verified export state, retained so a localized fix re-delivers without Blender.

    python tools/homm3_glb_patch/base.py status <unit ...>

fleet_rebuild.py retains the base right after its export (verify_glb + emphasis deliver done, before any delivery
stage): artifacts/homm3_glb_patch/<unit>/base.glb (the canonical GLB at that moment, byte for byte) plus copies of
the two files that describe it -- the emphasis stamp and glb_verify.json -- and base.json with every sha and the
.blend's sha. `fleet_rebuild.py --from-base <unit>` puts that state back and runs only the numpy delivery stages
(patch, deyaw, stride match, move low-pass, densify, prop floor, ground), look.py --stages apply and the idle rollout.
restore() copies the two JSON back and hands the base GLB over as bytes: the delivery stages run on it in memory and
look apply writes the canonical GLB once, at the end (docs/homm3_glb_patch_lane.md, in-memory stage fusion).

A base is valid (base_errors == []) only while it still describes the build: the .blend is the one that exported it,
every retained file hashes to its record, the canonical emphasis stamp is the retained one, and an emphasised stamp
names the base as its emphasisedGlbSha256. fleet_rebuild.py's transaction snapshots and restores this directory with
the delivery, so a failed run leaves the base it found. Anything
else refuses; the full chain (fleet_rebuild.py without --from-base) re-exports and retains a fresh base.
Disk: one GLB plus two small JSON per unit (the next retain replaces them).
Proof tier: generated artifact.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASES = ROOT / "artifacts/homm3_glb_patch"
SCHEMA = "homm3_glb_patch_base.v1"


def sha(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def paths(u: str) -> dict:
    C = ROOT / "artifacts/homm3_def_retarget" / u
    return {"glb": C / f"{u}_def_retarget.glb", "blend": C / f"{u}_def_retarget.blend", "verify": C / "glb_verify.json",
            "emphasis": ROOT / "artifacts/homm3_def_retarget_emphasis" / u / "stamp.json"}


def base_dir(u: str) -> Path:
    return BASES / u


def retain(u: str, route: str) -> dict:
    """Copy the canonical export state into the base dir (atomic per file; base.json last)."""
    p, d = paths(u), base_dir(u)
    d.mkdir(parents=True, exist_ok=True)
    rec = {"schema": SCHEMA, "unit": u, "route": route, "retainedAt": datetime.datetime.now().isoformat(timespec="seconds"),
           "blendSha256": sha(p["blend"]), "files": {}}
    for key, name in (("glb", "base.glb"), ("verify", "glb_verify.json"), ("emphasis", "emphasis_stamp.json")):
        if not p[key].is_file():
            rec["files"][key] = None
            (d / name).unlink(missing_ok=True)
            continue
        tmp = d / (name + ".tmp")
        shutil.copy2(p[key], tmp)
        os.replace(tmp, d / name)
        rec["files"][key] = {"name": name, "sha256": sha(d / name)}
    if rec["files"]["glb"] is None:
        raise RuntimeError(f"{u}: no canonical GLB to retain as the patch base")
    tmp = d / "base.json.tmp"
    tmp.write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, d / "base.json")
    return rec


def load(u: str) -> dict | None:
    f = base_dir(u) / "base.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def base_errors(u: str) -> list[str]:
    rec = load(u)
    if rec is None:
        return [f"{u}: no patch base (run the full chain once: fleet_rebuild.py {u})"]
    if rec.get("schema") != SCHEMA:
        return [f"{u}: base.json schema {rec.get('schema')!r} != {SCHEMA}"]
    p, d = paths(u), base_dir(u)
    bad = []
    if not p["blend"].is_file() or sha(p["blend"]) != rec.get("blendSha256"):
        bad.append(f"{u}: the .blend is no longer the build that exported the base (rebuilt since); run the full chain")
    for key, f in rec.get("files", {}).items():
        if f is None:
            continue
        q = d / f["name"]
        if not q.is_file() or sha(q) != f["sha256"]:
            bad.append(f"{u}: retained {f['name']} is missing or differs from base.json")
    if not rec.get("files", {}).get("glb"):
        bad.append(f"{u}: base.json records no GLB")
    em = rec.get("files", {}).get("emphasis")
    # the canonical emphasis stamp must still be the retained one: a full run that failed after its export used to
    # restore the delivery but keep the base of its own export (fleet_rebuild.py now restores the base too), and the
    # canonical then names another export than the base (2026-09-30 h3_monk / h3_crossbowman)
    if em and p["emphasis"].is_file() and sha(p["emphasis"]) != em["sha256"]:
        bad.append(f"{u}: the canonical emphasis stamp is not the one retained with the base (the delivery is another "
                   "export's); run the full chain")
    elif em and not p["emphasis"].is_file():
        bad.append(f"{u}: the base retained an emphasis stamp but the canonical one is gone; run the full chain")
    if em and not bad:
        st = json.loads((d / em["name"]).read_text(encoding="utf-8"))
        if st.get("decision") == "emphasised" and st.get("emphasisedGlbSha256") != rec["files"]["glb"]["sha256"]:
            bad.append(f"{u}: the retained emphasis stamp's emphasisedGlbSha256 is not the base GLB")
    return bad


def restore(u: str) -> tuple[dict, bytes]:
    """Put the base state back (fail closed on any base error): glb_verify.json and the emphasis stamp over their
    canonical paths, and the base GLB's bytes returned (hashed against the record), never written over the canonical
    GLB -- fleet_rebuild.py's in-memory delivery stages start from them and look apply writes the delivered GLB."""
    bad = base_errors(u)
    if bad:
        raise RuntimeError("; ".join(bad))
    rec, p, d = load(u), paths(u), base_dir(u)
    data = (d / rec["files"]["glb"]["name"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != rec["files"]["glb"]["sha256"]:
        raise RuntimeError(f"{u}: the retained base GLB does not hash to the base record")
    for key in ("verify", "emphasis"):
        f = rec["files"].get(key)
        if f is None:
            continue
        tmp = p[key].with_name(p[key].name + ".base_restore.tmp")
        p[key].parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(d / f["name"], tmp)
        os.replace(tmp, p[key])
        if sha(p[key]) != f["sha256"]:
            raise RuntimeError(f"{u}: restored {p[key].name} does not hash to the base record")
    return {"baseGlbSha256": rec["files"]["glb"]["sha256"], "retainedAt": rec["retainedAt"]}, data


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] != "status":
        raise SystemExit(__doc__)
    bad = 0
    for u in argv[1:]:
        e = base_errors(u)
        r = load(u) or {}
        print(json.dumps({"unit": u, "ok": not e, "errors": e, "retainedAt": r.get("retainedAt"),
                          "baseGlbSha256": ((r.get("files") or {}).get("glb") or {}).get("sha256")}))
        bad += bool(e)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
