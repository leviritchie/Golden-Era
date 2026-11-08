#!/usr/bin/env python3
"""Fail-closed census of HoMM3 units shown through a stopgap presentation.

A "stopgap" is any ported unit whose battle or adventure-map presentation is
not its own owned model, or whose owned bundle is incomplete:

* ``donor``     - the unit view points at a vanilla Olden Era prefab and no
                  ``homm3_import.json`` row claims the unit, so the vanilla
                  donor model is shown (e.g. h3_mummy in battle -> graverobber).
* ``borrowed``  - the view points at another ported unit's ``homm3_import``
                  resource path, so the runtime path-keyed swap shows that
                  other unit's model (e.g. h3_mummy on the map -> Walking Dead).
* ``bundle_missing`` - an import row exists but its bundle file is not present.
* ``clips_missing``  - the bundle lacks a required lifecycle clip (idle-only
                  placeholders).
* ``portrait_missing`` - no ``ui_portrait_<sid>`` asset.
* ``inherited_donor_line`` - a neutral clone kept its donor's upgradeSid /
                  baseSid, so it upgrades into (or claims to be) a faction unit.

Every stopgap must be listed in
``custom_factions/contracts/homm3_unit_presentation_stopgaps.json`` with the
exact computed signature. A new stopgap (a silent fallback) fails; a changed
signature fails; a listed unit that is no longer a stopgap fails until the row
is removed (ratchet). Proof tier: generated-artifact (installed Core.zip +
import table + installed bundle manifests). It does not prove runtime visuals.

Mesh-identity problems inside an owned bundle (e.g. a wrong-source Meshy mesh)
cannot be computed from these inputs; they are carried in the ledger's
``declaredMeshIdentity`` section and only checked for referential integrity.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
IMPORT_JSON = PLUGIN / "homm3_import.json"
PORTRAIT_MANIFEST = PLUGIN / "homm3_ui_portraits" / "manifest.json"
LEDGER = ROOT / "custom_factions" / "contracts" / "homm3_unit_presentation_stopgaps.json"
GAME = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
DEFAULT_CORE = GAME / "HeroesOldenEra_Data" / "StreamingAssets" / "Core.zip"
DEFAULT_BUNDLES = GAME / "BepInEx" / "plugins" / "OfflineUnlockMod" / "homm3_bundles"

CUSTOM_PREFIXES = ("h3_", "hota_", "toa_", "temple_")
REQUIRED_CLIPS = ("Idle", "Move", "Hitted", "Death")
ATTACK_CLIPS = ("AttackFront", "ShootFront")
VIEWS_PREFIX = "DB/units/units_views/"
LOGICS_PREFIX = "DB/units/units_logics/"


def _norm(path: str) -> str:
    p = (path or "").replace("\\", "/").strip()
    return p[len("units/"):] if p.startswith("units/") else p


def _rows(zf: zipfile.ZipFile, prefix: str) -> dict[str, tuple[str, dict]]:
    out: dict[str, tuple[str, dict]] = {}
    for name in zf.namelist():
        if not (name.startswith(prefix) and name.endswith(".json")):
            continue
        folder = name[len(prefix):].split("/")[0]
        try:
            doc = json.loads(zf.read(name).decode("utf-8-sig"))
        except Exception as ex:  # malformed row is itself a failure
            raise RuntimeError(f"{name}: unreadable JSON ({ex})") from ex
        for row in doc.get("array") or []:
            if isinstance(row, dict):
                sid = str(row.get("sid") or row.get("id") or "")
                if sid:
                    out[sid] = (folder, row)
    return out


def _clips(bundles: Path, bundle_name: str) -> set[str] | None:
    manifest = bundles / f"{bundle_name}.manifest"
    if not (bundles / bundle_name).is_file() or not manifest.is_file():
        return None
    text = manifest.read_text(encoding="utf-8", errors="replace")
    return {m.split("_", 1)[1] for m in re.findall(r"/([A-Za-z0-9]+_[A-Za-z0-9_]+)\.anim", text)}


def compute(core: Path, bundles: Path | None) -> dict[str, dict]:
    entries = json.loads(IMPORT_JSON.read_text(encoding="utf-8"))["entries"]
    by_sid: dict[str, dict] = {}
    by_battle: dict[str, dict] = {}
    by_map: dict[str, dict] = {}
    for e in entries:
        for s in e.get("gameUnitSids") or []:
            by_sid[s] = e
        by_battle[_norm(e["battleResPath"])] = e
        if e.get("swapAdventureMap"):
            by_map[_norm(e["mapResPath"])] = e
    portraits = set(json.loads(PORTRAIT_MANIFEST.read_text(encoding="utf-8"))["assets"])

    with zipfile.ZipFile(core) as zf:
        views = _rows(zf, VIEWS_PREFIX)
        logics = _rows(zf, LOGICS_PREFIX)

    census: dict[str, dict] = {}
    for sid, (folder, view) in sorted(views.items()):
        mesh = _norm(str(view.get("mesh") or ""))
        map_mesh = _norm(str(view.get("mapMesh") or ""))
        custom = (
            sid.startswith(CUSTOM_PREFIXES)
            or folder.startswith("homm3_")
            or "homm3_import/" in mesh + map_mesh
            or sid in by_sid
        )
        if not custom:
            continue
        own = by_sid.get(sid)
        if own is not None:
            battle = "own"
        elif mesh in by_battle:
            battle = "borrowed:" + by_battle[mesh]["gameUnitSids"][0]
        else:
            battle = "donor:" + mesh
        map_entry = by_map.get(map_mesh)
        if map_entry is None:
            map_route = "donor:" + map_mesh
        elif sid in (map_entry.get("gameUnitSids") or []):
            map_route = "own"
        else:
            map_route = "borrowed:" + map_entry["gameUnitSids"][0]

        issues: list[str] = []
        if battle != "own":
            issues.append("battle=" + battle)
        if map_route != "own":
            issues.append("map=" + map_route)
        if own is not None and bundles is not None:
            clips = _clips(bundles, own["bundleName"])
            if clips is None:
                issues.append("bundle_missing:" + own["bundleName"])
            else:
                missing = [c for c in REQUIRED_CLIPS if c not in clips]
                if not any(c in clips for c in ATTACK_CLIPS):
                    missing.append("|".join(ATTACK_CLIPS))
                if missing:
                    issues.append("clips_missing:" + ",".join(missing))
        if f"ui_portrait_{sid}" not in portraits:
            issues.append("portrait_missing")
        logic = logics.get(sid, (None, {}))[1]
        if folder == "neutral":
            for key in ("upgradeSid", "baseSid"):
                if logic.get(key):
                    issues.append(f"inherited_donor_line:{key}={logic[key]}")
        if issues:
            census[sid] = {"folder": folder, "issues": issues}
    return census


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--core", type=Path, default=DEFAULT_CORE)
    ap.add_argument("--bundles-dir", type=Path, default=DEFAULT_BUNDLES)
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--emit", type=Path, help="write the computed census JSON here and exit 0")
    args = ap.parse_args(argv)

    errors: list[str] = []
    if not args.core.is_file():
        print(f"FAIL: Core.zip not found: {args.core}", file=sys.stderr)
        return 1
    if not args.bundles_dir.is_dir():
        print(f"FAIL: bundles dir not found: {args.bundles_dir}", file=sys.stderr)
        return 1
    census = compute(args.core, args.bundles_dir)
    if args.emit:
        args.emit.write_text(json.dumps(census, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {len(census)} stopgap rows to {args.emit}")
        return 0

    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    listed: dict[str, dict] = ledger.get("stopgaps") or {}
    for sid, row in census.items():
        if sid not in listed:
            errors.append(f"{sid}: unlisted stopgap (silent fallback) {row['issues']}")
            continue
        want = sorted(listed[sid].get("issues") or [])
        if want != sorted(row["issues"]):
            errors.append(f"{sid}: stopgap signature changed; ledger={want} computed={sorted(row['issues'])}")
        if not str(listed[sid].get("fix") or "").strip():
            errors.append(f"{sid}: ledger row has no fix plan")
    for sid in listed:
        if sid not in census:
            errors.append(f"{sid}: listed as stopgap but is no longer one; remove the ledger row")

    with zipfile.ZipFile(args.core) as zf:
        view_sids = set(_rows(zf, VIEWS_PREFIX))
    for sid, row in (ledger.get("declaredMeshIdentity") or {}).items():
        if sid not in view_sids:
            errors.append(f"declaredMeshIdentity {sid}: no unit view in Core.zip")
        if not str(row.get("evidence") or "").strip():
            errors.append(f"declaredMeshIdentity {sid}: missing evidence")

    if errors:
        print("FAIL: HoMM3 unit presentation stopgap contract", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        return 1
    print(
        f"OK: HoMM3 unit presentation stopgap contract ({len(census)} listed stopgaps, "
        f"{len(ledger.get('declaredMeshIdentity') or {})} declared mesh-identity rows)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
