"""Custom walker battle ground speed is normalized to vanilla Olden Era references; the Move is stride matched to it.

    python tools/validate_unit_move_speed_normalization_contract.py [--repo-root R] [--core-zip Z] [--require-installed]

Contract (docs/homm3_stride_match.md, "Move speed normalization"):
  * custom_factions/unit_move_speed_normalization.json maps a custom game unit sid to a class; each class names vanilla
    OE reference units (similar body plan, size and role) and a non-empty reason, and pins targetMoveSpeed, which must
    equal round(mean(refs' installed moveSpeed), 3). Refs are vanilla view rows, never custom ones.
  * Only `units` is consumed (the Core overlay writes the target into the unit's view row; stride_match_glb.py matches
    the Move stride to it). `proposed` is the reviewed-next mapping; a sid is in at most one of them.
  * Fliers only in a flier class: every class declares moveType "walk" or "fly"; its refs' Core units_logics
    stats.moveType must agree (fly iff "fly"), and so must each listed unit's own Core logic row and, where the unit has
    a DEF-retarget lab unit, reference/homm3_fliers.json. A unit whose two sources disagree cannot be listed.
    stride_match_glb.py never stride matches a flier (no planted contact; OE has no wing-cadence coupling).
  * The slow-down path is gone: no homm3_import.json entry carries battleMoveStrideBindUnits / battleMoveCycleSeconds /
    battleStrideMatch (the runtime used them to rewrite UnitViewConfig.moveSpeed down to a measured DEF stride), and no
    plugin source calls DeobfInteropCompat.TrySetUnitViewConfigMoveSpeed.
  * --require-installed: every `units` sid's installed Core view row already carries its target (deployed-payload
    readback; without it a pending overlay run is not a failure).
Loader helpers (load_table, adopted_targets) are shared with the consumers so both read one table the same way.
Proof tier: source/static (+ installed readback with --require-installed).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "custom_factions/unit_move_speed_normalization.json"
SCHEMA = "homm3_unit_move_speed_normalization.v1"
CORE_ZIP = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
                "/HeroesOldenEra_Data/StreamingAssets/Core.zip")
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
IMPORT = PLUGIN / "homm3_import.json"
FLIERS = ROOT / "tools/homm3_def_retarget_delivery/reference/homm3_fliers.json"
SLOWDOWN_KEYS = ("battleMoveStrideBindUnits", "battleMoveCycleSeconds", "battleStrideMatch")
CUSTOM_PREFIXES = ("h3_", "toa_", "hota_")


def load_table(path: Path | None = None) -> dict:
    path = path or TABLE
    t = json.loads(path.read_text(encoding="utf-8"))
    if t.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: schema must be {SCHEMA}, got {t.get('schema')}")
    return t


def adopted_targets(path: Path | None = None) -> dict[str, dict]:
    """sid -> {class, targetMoveSpeed, refs, reason} for the consumed (`units`) map only."""
    t = load_table(path)
    out = {}
    for sid, cls in t.get("units", {}).items():
        c = t["classes"].get(cls)
        if c is None:
            raise SystemExit(f"{path or TABLE}: unit {sid} names unknown class {cls}")
        out[sid] = {"class": cls, "targetMoveSpeed": float(c["targetMoveSpeed"]), "refs": list(c["refs"]),
                    "reason": c["reason"]}
    return out


def core_view_rows(core_zip: Path) -> dict[str, dict]:
    rows = {}
    with zipfile.ZipFile(core_zip) as z:
        for n in z.namelist():
            if n.startswith("DB/units/units_views/") and n.endswith("_v.json"):
                try:
                    doc = json.loads(z.read(n).decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                for a in doc.get("array", []) if isinstance(doc, dict) else []:
                    if isinstance(a, dict) and a.get("id"):
                        rows[a["id"]] = {**a, "_path": n}
    return rows


def core_move_types(core_zip: Path) -> dict[str, str]:
    """sid -> Core units_logics stats.moveType ("fly", or "walk" when absent / anything else)."""
    out = {}
    with zipfile.ZipFile(core_zip) as z:
        for n in z.namelist():
            if n.startswith("DB/units/units_logics/") and n.endswith("_l.json"):
                try:
                    doc = json.loads(z.read(n).decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                for a in doc.get("array", []) if isinstance(doc, dict) else []:
                    if isinstance(a, dict) and a.get("id"):
                        out[a["id"]] = "fly" if (a.get("stats") or {}).get("moveType") == "fly" else "walk"
    return out


def is_custom_row(sid: str, row: dict) -> bool:
    return sid.startswith(CUSTOM_PREFIXES) or str(row.get("mesh", "")).startswith("homm3_import/")


def errors(core_zip: Path, require_installed: bool) -> list[str]:
    err: list[str] = []
    t = load_table()
    views = core_view_rows(core_zip)
    moves = core_move_types(core_zip)
    classes = t.get("classes") or {}
    if not classes:
        err.append("no classes")
    for name, c in classes.items():
        refs = c.get("refs") or []
        if c.get("moveType") not in ("walk", "fly"):
            err.append(f"class {name}: moveType must be walk or fly, got {c.get('moveType')}")
        for r in refs:
            if r in moves and moves[r] != c.get("moveType"):
                err.append(f"class {name} ({c.get('moveType')}): ref {r} is Core moveType {moves[r]}")
        if not refs:
            err.append(f"class {name}: no refs")
            continue
        if not (isinstance(c.get("reason"), str) and c["reason"].strip()):
            err.append(f"class {name}: empty reason")
        speeds = []
        for r in refs:
            row = views.get(r)
            if row is None:
                err.append(f"class {name}: ref {r} has no installed view row")
            elif is_custom_row(r, row):
                err.append(f"class {name}: ref {r} is a custom unit, not a vanilla OE reference")
            elif not isinstance(row.get("moveSpeed"), (int, float)) or row["moveSpeed"] <= 0:
                err.append(f"class {name}: ref {r} has no positive moveSpeed")
            else:
                speeds.append(float(row["moveSpeed"]))
        if len(speeds) == len(refs):
            want = round(sum(speeds) / len(speeds), 3)
            if abs(float(c.get("targetMoveSpeed", -1)) - want) > 1e-9:
                err.append(f"class {name}: targetMoveSpeed {c.get('targetMoveSpeed')} != round(mean{tuple(speeds)}, 3) = {want}")
    units, proposed = t.get("units") or {}, t.get("proposed") or {}
    for sid in set(units) & set(proposed):
        err.append(f"{sid}: in both units and proposed")
    imp = json.loads(IMPORT.read_text(encoding="utf-8-sig"))["entries"]
    fliers = json.loads(FLIERS.read_text(encoding="utf-8"))["units"]
    for sid, cls in {**proposed, **units}.items():
        if cls not in classes:
            err.append(f"{sid}: unknown class {cls}")
        if sid not in views:
            err.append(f"{sid}: no installed Core view row")
        labs = {str(e.get("battlePrefabAssetPath") or "").split("/")[3:4][0] for e in imp
                if sid in (e.get("gameUnitSids") or []) and len(str(e.get("battlePrefabAssetPath") or "").split("/")) > 3}
        want = (classes.get(cls) or {}).get("moveType")
        if sid in moves and moves[sid] != want:
            err.append(f"{sid}: Core moveType {moves[sid]} in {want} class {cls} (fliers only in a flier class)")
        for lab in labs:
            rec = fliers.get(lab) or {}
            if rec.get("flier") is not None and ("fly" if rec["flier"] else "walk") != want:
                err.append(f"{sid}: lab unit {lab} is HoMM3 {'flier' if rec['flier'] else 'walker'} in {want} class {cls} "
                           "(fliers only in a flier class)")
    for i, e in enumerate(imp):
        bad = [k for k in SLOWDOWN_KEYS if k in e]
        if bad:
            err.append(f"homm3_import.json entry {i} ({e.get('battleResPath')}): {bad} (runtime moveSpeed slow-down path)")
    call = re.compile(r"TrySetUnitViewConfigMoveSpeed\s*\(")
    for cs in PLUGIN.glob("*.cs"):
        src = cs.read_text(encoding="utf-8", errors="replace")
        for m in call.finditer(src):
            line = src.count("\n", 0, m.start()) + 1
            if not re.search(r"static\s+bool\s+TrySetUnitViewConfigMoveSpeed", src.splitlines()[line - 1]):
                err.append(f"{cs.name}:{line}: calls TrySetUnitViewConfigMoveSpeed (runtime moveSpeed rewrite)")
    if require_installed:
        for sid, cls in units.items():
            row = views.get(sid) or {}
            tgt = (classes.get(cls) or {}).get("targetMoveSpeed")
            if row.get("moveSpeed") is None or abs(float(row["moveSpeed"]) - float(tgt)) > 1e-6:
                err.append(f"{sid}: installed moveSpeed {row.get('moveSpeed')} != target {tgt} ({cls})")
    return err


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    ap.add_argument("--core-zip", type=Path, default=CORE_ZIP)
    ap.add_argument("--require-installed", action="store_true")
    a = ap.parse_args(argv)
    if a.repo_root.resolve() != ROOT:
        raise SystemExit(f"--repo-root {a.repo_root} is not this checkout ({ROOT})")
    err = errors(a.core_zip, a.require_installed)
    for e in err:
        print("FAIL", e)
    t = load_table()
    print(("OK" if not err else "FAILED") + f" unit move speed normalization: {len(t.get('units', {}))} adopted, "
          f"{len(t.get('proposed', {}))} proposed, {len(t.get('classes', {}))} classes")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
