#!/usr/bin/env python3
"""Validate the Conflux Elemental Fusion data files (no Core build).

custom_factions/conflux_fusion/fusion_config.json is the contract the plugin runtime reads; it must stay
exactly: schema, spellSid, penalty 0.9, minShare 0.3333, tierLines, lines and 105 pairs
{a, b, host, guest, fused, name}. fusion_units.json carries names, squad values, the mesh override field
and the signature spec of each fused unit. Checks:

- 105 unique unordered elemental pairs (self-fusion excluded), unique fused sids and names;
- host priority Earth > Water > Fire > Air > Psychic; inside a family the upgrade hosts the base and
  _upg hosts _upg_alt; fused sid = h3_fusion_<host short>_<guest short>;
- both files agree; squad values are positive; signature specs are well formed and replace like for like;
- no family-wide starting Focus: fusion_units.json has no elementalStartEnergy key and no unit entry sets
  startEnergy (owner 2026-11-16; the Core contract validator pins the candidate rows and the allow-list);
- fused units appear in no neutral pool, reward, dwelling or other custom_factions data file;
- stage-2 recipes (user 2026-11-15): recipeMinRank 1..3; each recipe {a, b, host, guest, fused, name} names two
  different stage-1 fused units, a new h3_fusion_ii_<slug> sid and a unique name; host = the parent whose host
  elemental ranks first (Earth > Water > Fire > Air > Psychic, ties: higher squad value); fusion_units.json stage2
  agrees and gives every unit a squad value, mesh override and at least one buildable signature;
- portraits: homm3_portraits/<fused>.png exists for every unit (local, git-ignored folder; --skip-portraits
  for checkouts without it).
"""

from __future__ import annotations

import argparse
import json
import re
import pathlib
import subprocess
import sys
from itertools import combinations
from typing import Any

FAMILY_PRIORITY = ("earth", "water", "fire", "air", "psychic")
VARIANT_ORDER = ("", "_upg", "_upg_alt")
SHORT_NAMES = {
    "h3_air_elemental": "air", "h3_air_elemental_upg": "storm", "h3_air_elemental_upg_alt": "hurricane",
    "h3_water_elemental": "water", "h3_water_elemental_upg": "ice", "h3_water_elemental_upg_alt": "frost",
    "h3_fire_elemental": "fire", "h3_fire_elemental_upg": "energy", "h3_fire_elemental_upg_alt": "plasma",
    "h3_earth_elemental": "earth", "h3_earth_elemental_upg": "magma", "h3_earth_elemental_upg_alt": "lava",
    "h3_psychic_elemental": "psychic", "h3_psychic_elemental_upg": "magic", "h3_psychic_elemental_upg_alt": "astral",
}
CONFIG_KEYS = ["schema", "spellSid", "penalty", "minShare", "tierLines", "lines", "pairs", "recipeMinRank", "recipes"]
RECIPE_KEYS = ["a", "b", "host", "guest", "fused", "name"]
PAIR_KEYS = ["a", "b", "host", "guest", "fused", "name"]
SIGNATURE_BUILDS = {"active": {"unit_special", "spell_effect"}, "passive": {"passive_graft", "fallback"}}
PORTRAIT_DIR = pathlib.Path("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_portraits")


def family(sid: str) -> str:
    return sid.split("_")[1]


def variant(sid: str) -> str:
    base = f"h3_{family(sid)}_elemental"
    return sid[len(base):]


def expected_host(a: str, b: str) -> str:
    fa, fb = family(a), family(b)
    if fa != fb:
        return a if FAMILY_PRIORITY.index(fa) < FAMILY_PRIORITY.index(fb) else b
    va, vb = VARIANT_ORDER.index(variant(a)), VARIANT_ORDER.index(variant(b))
    # The upgrade hosts the base; _upg hosts _upg_alt.
    if va == 0 or vb == 0:
        return a if va > vb else b
    return a if va < vb else b


def check_signature(sid: str, sig: Any, issues: list[str]) -> None:
    if sig is None:
        return
    if not isinstance(sig, dict):
        issues.append(f"{sid}: signature must be an object or null")
        return
    kind, build = sig.get("kind"), sig.get("build")
    if kind not in SIGNATURE_BUILDS or build not in SIGNATURE_BUILDS[kind]:
        issues.append(f"{sid}: signature kind/build {kind!r}/{build!r} is not like-for-like")
        return
    if not sig.get("effect"):
        issues.append(f"{sid}: signature without effect name")
    if build == "unit_special" and len(str(sig.get("source", "")).split(":")) != 3:
        issues.append(f"{sid}: unit_special source must be <unit>:<slot>:<index>")
    if build == "spell_effect" and not sig.get("spellEffectKey"):
        issues.append(f"{sid}: spell_effect without spellEffectKey")
    if build == "passive_graft" and not (sig.get("cards") and (sig.get("logicPassives") or sig.get("attackBuff") or sig.get("stats") or sig.get("logicFields"))):
        issues.append(f"{sid}: passive_graft needs a card and a logic part")
    if build == "fallback" and not sig.get("reason"):
        issues.append(f"{sid}: fallback signature without reason")
    if not sig.get("useSourceText") and build != "fallback" and not sig.get("nameText"):
        issues.append(f"{sid}: signature card needs nameText or useSourceText")
    for helper in sig.get("helperRows") or []:
        if not (isinstance(helper, dict) and str(helper.get("path", "")).startswith("DB/") and isinstance(helper.get("row"), dict) and helper["row"].get("id")):
            issues.append(f"{sid}: malformed helperRows entry")


def check_stage2(config: dict[str, Any], units: dict[str, Any], stage2: dict[str, Any], names: set[str], issues: list[str]) -> set[str]:
    rank = config.get("recipeMinRank")
    if not isinstance(rank, int) or not 1 <= rank <= 3:
        issues.append("fusion_config.json recipeMinRank must be 1..3")
    recipes = config.get("recipes") or []
    seen_keys, seen = set(), set()
    for row in recipes:
        if list(row) != RECIPE_KEYS:
            issues.append(f"recipe keys {list(row)!r}, expected {RECIPE_KEYS!r}")
            continue
        a, b, host, guest, fused, name = (row[k] for k in RECIPE_KEYS)
        if a == b or a not in units or b not in units:
            issues.append(f"{fused}: recipe parents must be two different stage-1 fused units")
            continue
        key = frozenset((a, b))
        if key in seen_keys:
            issues.append(f"{fused}: recipe {a}+{b} listed twice")
        seen_keys.add(key)
        rank_a = (FAMILY_PRIORITY.index(family(units[a]["host"])), -units[a]["squadValue"])
        rank_b = (FAMILY_PRIORITY.index(family(units[b]["host"])), -units[b]["squadValue"])
        expected = a if rank_a <= rank_b else b
        if host != expected or {host, guest} != {a, b}:
            issues.append(f"{fused}: recipe host {host} breaks the host rule (expected {expected})")
        if not re.fullmatch(r"h3_fusion_ii_[a-z]+(?:_[a-z]+)*", fused) or fused in seen or fused in units:
            issues.append(f"{fused}: stage-2 sid must be a new h3_fusion_ii_<slug>")
        if not name or name in names:
            issues.append(f"{fused}: stage-2 name {name!r} missing or not unique")
        seen.add(fused)
        names.add(name)
        entry = stage2.get(fused)
        if not isinstance(entry, dict):
            issues.append(f"{fused}: missing from fusion_units.json stage2")
            continue
        if any(entry.get(k) != row[k] for k in ("a", "b", "host", "guest", "name")):
            issues.append(f"{fused}: fusion_units.json stage2 disagrees with the recipe")
        if not isinstance(entry.get("squadValue"), int) or entry["squadValue"] <= 0:
            issues.append(f"{fused}: squadValue must be a positive integer")
        if entry.get("mesh") != {"mesh": f"homm3_import/conflux/{fused}", "mapMesh": f"homm3_import/conflux/{fused}_map"}:
            issues.append(f"{fused}: stage-2 mesh override must point at its own crest bundle")
        sigs = entry.get("signatures") or []
        if not [s for s in sigs if isinstance(s, dict) and s.get("build") != "fallback"]:
            issues.append(f"{fused}: stage-2 fusion needs at least one buildable signature")
        kinds = [s.get("kind") for s in sigs if isinstance(s, dict)]
        if len(kinds) != len(set(kinds)):
            issues.append(f"{fused}: at most one active and one passive signature part")
        for sig in sigs:
            check_signature(fused, sig, issues)
    if set(stage2) != seen:
        issues.append(f"fusion_units.json stage2 differs from the config recipes: {sorted(set(stage2) ^ seen)[:5]}")
    return seen


def check_no_foreign_references(repo: pathlib.Path, issues: list[str]) -> None:
    result = subprocess.run(
        ["git", "grep", "--untracked", "-l", "-E", "h3_fusion_[a-z]+_[a-z]+", "--", "custom_factions"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
    )
    # The bundle payload contract lists the fused crest bundles by name (install/payload hashes, not a pool).
    allowed = {"custom_factions/conflux_fusion/fusion_config.json", "custom_factions/conflux_fusion/fusion_units.json",
               "custom_factions/contracts/homm3_bundle_payload_contract.json"}
    for path in (result.stdout or "").splitlines():
        path = path.strip()
        if path and path not in allowed:
            issues.append(f"fused unit sid referenced outside conflux_fusion data (pool/reward/dwelling leak?): {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument("--skip-portraits", action="store_true")
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    data_dir = repo / "custom_factions" / "conflux_fusion"
    config = json.loads((data_dir / "fusion_config.json").read_text(encoding="utf-8"))
    units_doc = json.loads((data_dir / "fusion_units.json").read_text(encoding="utf-8"))
    units = units_doc.get("units") or {}
    issues: list[str] = []

    if list(config) != CONFIG_KEYS:
        issues.append(f"fusion_config.json keys {list(config)!r}, expected {CONFIG_KEYS!r}")
    if config.get("schema") != "homm3_conflux_fusion_config.v1":
        issues.append("fusion_config.json schema must be homm3_conflux_fusion_config.v1")
    if config.get("spellSid") != "homm3_conflux_elemental_fusion":
        issues.append("fusion_config.json spellSid must be homm3_conflux_elemental_fusion")
    if config.get("penalty") != 0.9 or config.get("minShare") != 0.3333:
        issues.append("fusion_config.json penalty/minShare must be 0.9/0.3333")
    if config.get("tierLines") != {
        "1": ["air", "water", "fire"],
        "2": ["air", "water", "fire", "earth"],
        "3": ["air", "water", "fire", "earth", "psychic"],
    }:
        issues.append("fusion_config.json tierLines must be Basic air/water/fire, Advanced +earth, Expert +psychic")
    lines = config.get("lines") or {}
    expected_lines = {f: [f"h3_{f}_elemental{v}" for v in VARIANT_ORDER] for f in ("air", "water", "fire", "earth", "psychic")}
    if lines != expected_lines:
        issues.append("fusion_config.json lines must list base, _upg, _upg_alt for air/water/fire/earth/psychic")
    if "squadValues" in json.dumps(config):
        issues.append("fusion_config.json must not carry squadValues")

    elementals = [sid for line in expected_lines.values() for sid in line]
    expected_pairs = {frozenset(p) for p in combinations(elementals, 2)}
    pairs = config.get("pairs") or []
    seen_pairs, seen_fused, seen_names = set(), set(), set()
    for row in pairs:
        if list(row) != PAIR_KEYS:
            issues.append(f"pair keys {list(row)!r}, expected {PAIR_KEYS!r}")
            continue
        a, b, host, guest, fused, name = (row[k] for k in PAIR_KEYS)
        key = frozenset((a, b))
        if key in seen_pairs or key not in expected_pairs:
            issues.append(f"duplicate or invalid pair {a}+{b}")
        seen_pairs.add(key)
        if elementals.index(a) > elementals.index(b):
            issues.append(f"{fused}: a/b not in line order")
        if {host, guest} != {a, b} or host != expected_host(a, b):
            issues.append(f"{fused}: host {host} breaks the host priority rule (expected {expected_host(a, b)})")
        if fused != f"h3_fusion_{SHORT_NAMES[host]}_{SHORT_NAMES[guest]}":
            issues.append(f"{fused}: sid must be h3_fusion_{SHORT_NAMES[host]}_{SHORT_NAMES[guest]}")
        if fused in seen_fused or name in seen_names or not name:
            issues.append(f"{fused}: duplicate sid or name {name!r}")
        seen_fused.add(fused)
        seen_names.add(name)
        entry = units.get(fused)
        if not isinstance(entry, dict):
            issues.append(f"{fused}: missing from fusion_units.json")
            continue
        if (entry.get("host"), entry.get("guest"), entry.get("name")) != (host, guest, name):
            issues.append(f"{fused}: fusion_units.json host/guest/name disagree with fusion_config.json")
        if not isinstance(entry.get("squadValue"), int) or entry["squadValue"] <= 0:
            issues.append(f"{fused}: squadValue must be a positive integer")
        mesh = entry.get("mesh")
        if mesh is not None and not (isinstance(mesh, dict) and set(mesh) <= {"mesh", "mapMesh"}):
            issues.append(f"{fused}: mesh override must be null or {{mesh, mapMesh}}")
        check_signature(fused, entry.get("signature"), issues)
    if len(pairs) != 105 or seen_pairs != expected_pairs:
        issues.append(f"expected all 105 elemental pairs, found {len(seen_pairs)}")
    if set(units) != seen_fused:
        issues.append(f"fusion_units.json units differ from the config pairs: {sorted(set(units) ^ seen_fused)[:5]}")

    if "elementalStartEnergy" in units_doc:
        issues.append("fusion_units.json elementalStartEnergy is retired (owner 2026-11-16: no elemental starting Focus as a catch-all)")
    for sid, entry in list(units.items()) + list((units_doc.get("stage2") or {}).items()):
        if isinstance(entry, dict) and "startEnergy" in entry:
            issues.append(f"{sid}: fusion_units.json must not set startEnergy")

    stage2_sids = check_stage2(config, units, units_doc.get("stage2") or {}, seen_names, issues)
    check_no_foreign_references(repo, issues)
    if not args.skip_portraits:
        portrait_dir = repo / PORTRAIT_DIR
        missing = [sid for sid in seen_fused | stage2_sids if not (portrait_dir / f"{sid}.png").is_file()]
        if missing:
            issues.append(f"{len(missing)} fused portraits missing in {PORTRAIT_DIR} (e.g. {sorted(missing)[:3]})")

    if issues:
        for issue in issues[:100]:
            print(issue, file=sys.stderr)
        print(f"homm3-conflux-fusion-data: {len(issues)} issue(s)", file=sys.stderr)
        return 1
    signatures = sum(1 for u in units.values() if (u.get("signature") or {}).get("build") not in (None, "fallback"))
    print(f"homm3-conflux-fusion-data: validated 105 fused units ({signatures} signatures), {len(stage2_sids)} stage-2 fusions, contract and portraits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
