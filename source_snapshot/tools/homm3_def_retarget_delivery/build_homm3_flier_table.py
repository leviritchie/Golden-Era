"""Build the HoMM3 flier table the stride gate uses: which retarget units are fliers, from the creature configs.

    python tools/homm3_def_retarget_delivery/build_homm3_flier_table.py [--out P]

Why: stride_match_glb.py used to call a Move "flown" when its floor rose off the Idle floor or fewer than two legs
reached it. That lets a hop, a grounding bug or a rig whose legs the chain finder does not know skip the stride
check. Whether a unit flies is a HoMM3 fact, so it is read from the creature definitions instead.

Join (no name guessing): tools/homm3_import/units_inventory.json records the exact battle DEF each unit was extracted
from - a core LOD entry (battleLodEntry), a mod zip member (battleZipMember / battleJsonZipMember) or a file
(battleDefPath). Each is normalised to its sprite path (after "sprites/", lower case, no extension; LOD entries to
the basename) and matched to the creature entry whose graphics.animation normalises to the same path, in:
  core             V:/games/VCMI/config/creatures/*.json                (VCMI's SoD creature set)
  third-upgrades   vcmi/Mods/third-upgrades/**/creatures/**/*.json
  hota             vcmi/Mods/hota/** (content.zip members and loose files under config/ whose path names "creature")
  tears-of-ashan   vcmi/Mods/tears-of-ashan/** (same)
A creature flies when its own abilities carry a bonus of type FLYING (a null value removes it). Mod entries that
override a core creature ("core:imp") are ignored: the table records HoMM3's creature, not a mod's rebalance.
A unit whose DEF matches no creature, or matches creatures that disagree, is written as "unresolved" unless
MANUAL below settles it with evidence; stride_match_glb.py refuses an unresolved or missing unit (fail closed).
Proof tier: source/static (creature configs); nothing here touches the game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

import json5

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INVENTORY = ROOT / "tools/homm3_import/units_inventory.json"
CORE = Path("V:/games/VCMI/config/creatures")
MODS = ROOT / "vcmi/Mods"
OUT = HERE / "reference/homm3_fliers.json"
SOURCES = ("third-upgrades", "hota", "tears-of-ashan")

# Units the join cannot settle mechanically: {unitSid: (flier, evidence)}. Retarget unit configs that have no
# units_inventory.json row are added from here too, so every tools/homm3_def_retarget/units/*.json is classified.
MANUAL: dict[str, tuple[bool, str]] = {
    "h3_boar_rider": (False, "retarget lab unit without an inventory row: the Stronghold boar rider (orc on a boar, "
                             "stronghold_quadruped rig), the same creature as inventory row toa_boar_rider, which "
                             "matches core:boar (no FLYING); a boar walks"),
}


def norm(path: str) -> str:
    p = path.replace("\\", "/").lower()
    if "sprites/" in p:
        p = p.rsplit("sprites/", 1)[1]
    return re.sub(r"\.(def|json|png)$", "", p)


def flying(abilities) -> bool:
    items = abilities.values() if isinstance(abilities, dict) else (abilities or [])
    return any(isinstance(b, dict) and b.get("type") == "FLYING" for b in items)


def flying_subtypes(abilities) -> list:
    items = abilities.values() if isinstance(abilities, dict) else (abilities or [])
    return sorted({str(b.get("subtype", "")) for b in items if isinstance(b, dict) and b.get("type") == "FLYING"})


def creatures_from(src: str, name: str, text: str, out: list) -> None:
    try:
        d = json5.loads(text)
    except ValueError as e:
        raise SystemExit(f"{src}: cannot parse {name}: {e}")
    if not isinstance(d, dict):
        return
    for key, v in d.items():
        if not isinstance(v, dict) or ":" in key:          # "core:imp" style overrides are rebalances, not HoMM3
            continue
        g = v.get("graphics")
        anim = g.get("animation") if isinstance(g, dict) else None
        if not anim:
            continue
        out.append({"source": src, "creature": key, "animation": anim, "key": norm(anim),
                    "flying": flying(v.get("abilities")), "subtypes": flying_subtypes(v.get("abilities")),
                    "file": name})


def rel(p) -> str:
    q = Path(str(p).split("!")[0]).resolve()
    tail = str(p)[len(str(p).split("!")[0]):]
    try:
        return q.relative_to(ROOT.resolve()).as_posix() + tail
    except ValueError:
        return q.as_posix() + tail


def load_creatures() -> tuple[list, dict]:
    out, hashes = [], {}
    for f in sorted(CORE.glob("*.json")):
        t = f.read_text(encoding="utf-8-sig")
        hashes[rel(f)] = hashlib.sha256(t.encode("utf-8")).hexdigest()
        creatures_from("core", str(f), t, out)
    for src in SOURCES:
        for r, _, fs in os.walk(MODS / src):
            for f in sorted(fs):
                p = Path(r) / f
                if f.endswith(".zip"):
                    with zipfile.ZipFile(p) as z:
                        members = [n for n in z.namelist() if "creature" in n.lower() and n.endswith(".json")
                                   and "/config/" in "/" + n.lower()]
                        if members:
                            hashes[rel(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
                        for n in members:
                            creatures_from(src, f"{p}!{n}", z.read(n).decode("utf-8-sig"), out)
                elif f.endswith(".json") and "/config/" in str(p).replace("\\", "/").lower() \
                        and "creature" in str(p).replace("\\", "/").lower():
                    t = p.read_text(encoding="utf-8-sig")
                    hashes[rel(p)] = hashlib.sha256(t.encode("utf-8")).hexdigest()
                    creatures_from(src, str(p), t, out)
    return out, hashes


def unit_def(row: dict) -> tuple[str, str, str] | None:
    """(source, key, provenance) of a unit's battle DEF."""
    if row.get("battleLodEntry"):
        return "core", norm(row["battleLodEntry"]).rsplit("/", 1)[-1], f"{row.get('battleLod')}:{row['battleLodEntry']}"
    member = row.get("battleZipMember") or row.get("battleJsonZipMember")
    if member:
        zp = str(row.get("battleZipPath", "")).replace("\\", "/")
        src = next((s for s in SOURCES if f"/{s}/" in f"/{zp}/"), None)
        return src or "unknown", norm(member), f"{zp}!{member}"
    if row.get("battleDefPath"):
        p = str(row["battleDefPath"]).replace("\\", "/")
        src = next((s for s in SOURCES if f"/{s}/" in f"/{p}/"), "file")
        return src, norm(p), p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    creatures, hashes = load_creatures()
    by_key: dict[tuple[str, str], list] = {}
    for c in creatures:
        by_key.setdefault((c["source"], c["key"]), []).append(c)
        if c["source"] == "core":
            by_key.setdefault(("core", c["key"].rsplit("/", 1)[-1]), []).append(c)
    rows = json.loads(INVENTORY.read_text(encoding="utf-8-sig"))["units"]
    units, unresolved = {}, []
    for row in rows:
        sid = row["unitSid"]
        d = unit_def(row)
        rec = {"def": d[2] if d else None}
        if sid in MANUAL:
            rec.update(flier=MANUAL[sid][0], status="manual", evidence=MANUAL[sid][1])
        elif d is None:
            rec.update(flier=None, status="unresolved", evidence="no battle DEF provenance in units_inventory.json")
        else:
            src, key, _ = d
            hits = by_key.get((src, key), [])
            if src != "core" and not hits:                  # a mod unit drawn with a mod-shipped copy of a core DEF
                hits = by_key.get(("core", key.rsplit("/", 1)[-1]), [])
            vals = {h["flying"] for h in hits}
            if len(vals) == 1:
                rec.update(flier=vals.pop(), status="matched",
                           creatures=sorted({f"{h['source']}:{h['creature']}" for h in hits}))
                sub = sorted({x for h in hits for x in h["subtypes"] if x})
                if sub:
                    rec["flyingSubtypes"] = sub                  # e.g. a teleporter: still no ground stride
            else:
                rec.update(flier=None, status="unresolved",
                           evidence="no creature entry animates this DEF" if not hits else "matched creatures disagree",
                           creatures=sorted({f"{h['source']}:{h['creature']}={h['flying']}" for h in hits}))
        if rec["status"] == "unresolved":
            unresolved.append(sid)
        units[sid] = rec
    for sid, (fl, ev) in MANUAL.items():
        if sid not in units:
            units[sid] = {"def": None, "flier": fl, "status": "manual", "evidence": ev}
    table = {"schema": "homm3_flier_table.v1", "tool": "tools/homm3_def_retarget_delivery/build_homm3_flier_table.py",
             "rule": "flier = the creature animating the unit's battle DEF has a FLYING bonus in its own definition",
             "proof": "source/static: VCMI core + mod creature configs joined by DEF path",
             "inputs": {"inventory": hashlib.sha256(INVENTORY.read_bytes()).hexdigest(), "configs": hashes},
             "counts": {"units": len(units), "fliers": sum(1 for u in units.values() if u["flier"] is True),
                        "walkers": sum(1 for u in units.values() if u["flier"] is False), "unresolved": len(unresolved)},
             "unresolved": unresolved, "units": dict(sorted(units.items()))}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"out": rel(args.out), **table["counts"], "unresolved": unresolved}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
