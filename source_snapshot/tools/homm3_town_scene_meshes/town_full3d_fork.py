#!/usr/bin/env python3
"""Town full-3D candidate forks: what a candidate seeded from another must inherit (stronghold_full3d_scene.py
candidate-init --seed-from <seed>).

candidate-init copies the seed's Unity project (staged bins) and stage report. A fork also needs the seed's own pins
that later stages and write_catalog read from work/, and the seed's catalog, because the lanes that re-write a catalog
carry over the previous catalog's blocks that write_catalog does not produce (props, sky, water). Without these a
fork silently drops its seed's buildingDepth / seams block (work/building_depth.json), its props block
(work/props/placement.json + the catalog's props) and its closing walls, which is how the zs_v2 dry run on
nfix2_cloth lost them on 2026-10-01.

fork_seed_state copies each SEED_PIN the seed has and verifies the bytes, and writes the seed's catalog without the
bundle keys (BUNDLE_KEYS: they describe the seed's own bundle; this candidate's bundle step writes its own) as the
fork's bundle/catalog.json. It fails closed: a pin the seed has that does not arrive byte-identical refuses the fork.
carry_catalog is the carry-over rule a fork's catalog step applies; catalog_carry is the rule write_catalog(sc,
carry=...) applies on every catalog rewrite (required keyword: no step can drop another lane's block silently).
Test: test_town_full3d_fork.py.
Proof tier: source / unit-test validated.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

# work/ files a later stage or write_catalog reads as the candidate's own pins
SEED_PINS = ("building_depth.json", "props/placement.json", "closing_walls.npz")
# written by the bundle step for a candidate's own bundle: never inherited, never carried
BUNDLE_KEYS = frozenset({"bundleBytes", "bundleSha256"})


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def fork_seed_state(seed: Path, work: Path, out: Path) -> dict:
    """Copy the seed candidate folder's pins into work/ and its catalog (minus BUNDLE_KEYS) into out/catalog.json.
    Returns {"pins": [...], "catalog": bool, "droppedCatalogKeys": [...]}; raises SystemExit on any failed copy."""
    seed, work, out = Path(seed), Path(work), Path(out)
    pins = []
    for rel in SEED_PINS:
        src = seed / "work" / rel
        if not src.is_file():
            continue
        dst = work / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            ok = dst.is_file() and _sha(dst) == _sha(src)
        except OSError as e:
            raise SystemExit(f"candidate-init: seed pin {src} could not be copied to {dst}: {e}")
        if not ok:
            raise SystemExit(f"candidate-init: seed pin {rel} did not arrive byte-identical at {dst}")
        pins.append(rel)
    res = {"pins": pins, "catalog": False, "droppedCatalogKeys": []}
    sc = seed / "bundle" / "catalog.json"
    if sc.is_file():
        try:
            cat = json.loads(sc.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise SystemExit(f"candidate-init: seed catalog {sc} is unreadable: {e}")
        res["droppedCatalogKeys"] = sorted(k for k in cat if k in BUNDLE_KEYS)
        cat = {k: v for k, v in cat.items() if k not in BUNDLE_KEYS}
        try:
            out.mkdir(parents=True, exist_ok=True)
            (out / "catalog.json").write_text(json.dumps(cat, indent=1) + "\n", encoding="utf-8")
        except OSError as e:
            raise SystemExit(f"candidate-init: could not write the forked catalog into {out}: {e}")
        res["catalog"] = True
    return res


def carry_catalog(new: dict, previous: dict) -> list:
    """Carry every block of the previous catalog that new does not produce, never the bundle keys; returns the keys."""
    carried = sorted(k for k in previous if k not in new and k not in BUNDLE_KEYS)
    for k in carried:
        new[k] = previous[k]
    return carried


CARRY_MODES = ("previous", "fresh")


def catalog_carry(new: dict, previous: dict | None, mode: str, owned=(), drop=(), where: str = "write_catalog") -> list:
    """The carry rule write_catalog applies (stronghold_full3d_scene.write_catalog(sc, carry=...)): every step that
    rewrites a catalog declares how its blocks meet the previous one, so no step can silently drop another lane's
    block (redepth used to drop the props block).

    The blocks at stake are the previous catalog's keys that new lacks, minus BUNDLE_KEYS, minus `owned` and minus
    `drop` (keys this step owns and re-decides, such as props when every prop was dropped). `owned` are the opt-in
    blocks write_catalog itself decides (buildingDepth from its pin, ...): never carried stale, and one the previous
    catalog had that new lacks refuses the write in either mode (its input is gone, e.g. a pin a fork did not
    inherit), unless the caller lists it in drop.
    - "previous": the previous catalog must exist (fail closed otherwise); those blocks are carried into new.
    - "fresh": the step writes a whole catalog; a missing previous catalog is fine, but a previous catalog that has
      such blocks refuses the write (they would be lost; re-run the step with carry "previous").
    Returns the carried keys."""
    if mode not in CARRY_MODES:
        raise SystemExit(f"{where}: carry must be one of {CARRY_MODES}, got {mode!r}")
    lost = sorted(k for k in (previous or {}) if k in set(owned) and k not in new and k not in set(drop))
    if lost:
        raise SystemExit(f"{where}: the previous catalog has {lost} but this write no longer produces them (their "
                         "opt-in input is gone); restore the input, or list them in drop to remove them")
    if previous is None:
        if mode == "previous":
            raise SystemExit(f"{where}: carry 'previous' but the candidate has no previous catalog to carry from")
        return []
    at_stake = sorted(k for k in previous if k not in new and k not in BUNDLE_KEYS and k not in set(owned)
                      and k not in set(drop))
    if mode == "fresh":
        if at_stake:
            raise SystemExit(f"{where}: carry 'fresh' would drop the previous catalog's blocks {at_stake}; "
                             "this candidate carries other lanes' blocks, so re-run with carry 'previous'")
        return []
    for k in at_stake:
        new[k] = previous[k]
    return at_stake
