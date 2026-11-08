#!/usr/bin/env python3
"""Town bench contract (docs/town_bench.md): a bench fix is a recipe step, never a second build path.

Static (no raster, no GPU; about a second):
  - town_full3d_recipe.py keeps the "edits" key, its v2-only shape check, and step 5b apply_edits between the content
    step's rows write and the gate, recording res["edits"];
  - every op file under tools/homm3_town_scene_meshes/town_bench/edits/ passes bench_edits' schema check (touches =
    the bins its ops touch, known ops and keys) and is named by its id;
  - every recipe with "edits" equals its base recipe apart from candidate / note / edits (the base itself may carry
    edits whose ops are a prefix of these), lists op files that exist, in their merge order (no conflicting files);
  - a staged candidate of such a recipe records the same op list, each op file's sha256 as it is now, and its
    bakedFrom / base recipe (a changed op file means the candidate no longer is what the recipe says);
  - issue registries (town_bench/issues/*.json) pass bench_issues' schema check.
The GPU parity of the bench's kernels is test_town_bench.py (run on demand / at release, like the certificate's).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "tools" / "homm3_town_scene_meshes"
BENCH = LANE / "town_bench"
RECIPE = LANE / "town_full3d_recipe.py"
RECIPES = LANE / "recipes"
FREE = {"candidate", "note", "edits"}


def errors() -> list[str]:
    errs = []
    sys.path.insert(0, str(BENCH))
    import bench_edits as E
    import bench_issues as I
    src = RECIPE.read_text(encoding="utf-8")
    for needle, why in (('"restOwner", "edits", "note"}', "RECIPE_KEYS must keep \"edits\""),
                        ('fail(f"{path}: edits is a {SCHEMA_V2} step', "the edits key must stay v2-only and checked"),
                        ("edits_rep = apply_edits(S, SM, sc, rows, r, layers_of) if r.get(\"edits\") else None\n"
                         "    # ---- 6. gate on the staged files\n"
                         "    res = gate(S, SC, SM, ZS, sc, r, path, cams, layers_of, work)",
                         "step 5b (apply_edits) must run right before the gate"),
                        ('res["edits"] = edits_rep', "the build result must record the edits"),
                        ("files = E.recipe_edits(r)", "apply_edits must apply the bench's own op files (bench_edits)")):
        if needle not in src:
            errs.append(f"{RECIPE.name}: {why}")
    for p in sorted((BENCH / "edits").glob("*/*.json")):
        try:
            d = E.load_file(p)
            if d["faction"] != p.parent.name:
                errs.append(f"{p.relative_to(ROOT)}: faction {d['faction']} is not its folder")
        except SystemExit as e:
            errs.append(str(e))
    for p in sorted((BENCH / "issues").glob("*.json")):
        try:
            I.load(p.stem)
        except SystemExit as e:
            errs.append(str(e))
    for p in sorted(RECIPES.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        ed = r.get("edits")
        if not ed:
            continue
        where = p.relative_to(ROOT).as_posix()
        bp = ROOT / ed.get("base", "")
        if not bp.is_file():
            errs.append(f"{where}: edits.base {ed.get('base')} is not a recipe file")
            continue
        base = json.loads(bp.read_text(encoding="utf-8"))
        strip = lambda d: {k: v for k, v in d.items() if k not in FREE}
        if strip(r) != strip(base):
            diff = sorted(k for k in set(r) | set(base) if k not in FREE and r.get(k) != base.get(k))
            errs.append(f"{where}: differs from its base {ed['base']} in {diff} (only candidate / note / edits may)")
        bops = (base.get("edits") or {}).get("ops", [])
        if bops != ed.get("ops", [])[:len(bops)]:
            errs.append(f"{where}: the base's edits {bops} are not a prefix of this recipe's")
        try:
            files = E.recipe_edits(r)
        except SystemExit as e:
            errs.append(f"{where}: {e}")
            continue
        for d in files:
            if d["faction"] != r["faction"]:
                errs.append(f"{where}: op {d['id']} is a {d['faction']} op")
        res_p = ROOT / "artifacts" / f"homm3_{r['faction']}_full3d" / "candidates" / r["candidate"] / "work" / \
            "zero_streak_recipe.json"
        if not res_p.is_file():
            print(f"{where}: candidate {r['candidate']} not staged here (op linkage checked statically)")
            continue
        res = json.loads(res_p.read_text(encoding="utf-8"))
        rec = res.get("edits") or {}
        want = [{"id": d["id"], "file": f, "sha256": E.op_file_sha(ROOT / f)} for d, f in zip(files, ed["ops"])]
        got = [{k: o.get(k) for k in ("id", "file", "sha256")} for o in rec.get("ops", [])]
        if got != want:
            errs.append(f"{where}: candidate {r['candidate']} records edits {got} but the recipe's op files are "
                        f"{want} (re-bake / rebuild)")
        if rec.get("base") != ed["base"]:
            errs.append(f"{where}: candidate records base {rec.get('base')}, the recipe {ed['base']}")
    return errs


def main() -> int:
    errs = errors()
    for e in errs:
        print("FAIL", e)
    if errs:
        return 1
    print("town bench contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
