"""Custom unit Focus generation follows the vanilla rule (docs/custom_unit_focus_generation.md).

Vanilla Olden Era (installed Core readback 2026-11-19): contact-melee units earn 2 Focus per action
(stats.energyPerCast), shooters and reach attackers earn 1, every unit earns 1 when it takes damage
(energyPerTakeDamage) and 0 per round (energyPerRound). Vanilla deviations each carry a card.

Checks:
- static: the overlay generator defines the rule and runs normalize_custom_unit_focus_generation after
  finalize_conflux_fusion_units; the fusion module does not inherit Focus stats from its parents.
- Core: every h3_* logic row matches the rule (or its CUSTOM_UNIT_FOCUS_GENERATION_EXCEPTIONS entry,
  which must name a unit whose view shows a card mentioning Focus); the vanilla melee/ranged split
  still holds, so a game update that changes the philosophy fails here instead of drifting silently.

Runtime: one Core.zip read, about 2 s / <200 MB. Proof tier: installed payload (or the --core given).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "tools" / "release_port" / "apply_release_core_overlay.py"
FUSION = REPO / "tools" / "release_port" / "homm3_conflux_fusion_core_overlay.py"
DEFAULT_CORE = Path(
    "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    "/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
PER_ACTION = {"melee": 2, "ranged": 1}
DEFAULTS = {"energyPerTakeDamage": 1, "energyPerRound": 0}
# Vanilla rows that deviate, each with the card that explains it. A new deviation is a philosophy change.
VANILLA_CARDED_DEVIATIONS = {"inquisitor_upg", "succubus_upg", "qilin_upg_alt", "gnat"}


def literal_assignment(source: str, name: str):
    for node in ast.parse(source).body:
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id == name and node.value is not None:
            return ast.literal_eval(node.value)
    raise KeyError(name)


def attack_class(row: dict) -> str:
    for attack in row.get("defaultAttacks") or []:
        if isinstance(attack, dict) and attack.get("attackType_") in ("shoot", "range"):
            return "ranged"
    return "melee"


def expected(row: dict, exceptions: dict) -> dict:
    out = {"energyPerCast": PER_ACTION[attack_class(row)], **DEFAULTS}
    out.update(exceptions.get(row["id"], {}))
    return out


def static_issues() -> tuple[list[str], dict]:
    issues: list[str] = []
    src = GENERATOR.read_text(encoding="utf-8")
    try:
        if literal_assignment(src, "CUSTOM_UNIT_FOCUS_PER_ACTION") != PER_ACTION:
            issues.append("generator CUSTOM_UNIT_FOCUS_PER_ACTION is not melee 2 / ranged 1")
        if literal_assignment(src, "CUSTOM_UNIT_FOCUS_STAT_DEFAULTS") != DEFAULTS:
            issues.append("generator CUSTOM_UNIT_FOCUS_STAT_DEFAULTS is not take 1 / round 0")
        exceptions = literal_assignment(src, "CUSTOM_UNIT_FOCUS_GENERATION_EXCEPTIONS")
    except KeyError as exc:
        return [f"generator is missing {exc}"], {}
    fusion_call = src.find("conflux_fusion.finalize_conflux_fusion_units(release_zip, output, notes")
    norm_call = src.find("normalize_custom_unit_focus_generation(release_zip, output, notes)")
    if fusion_call < 0 or norm_call < 0 or norm_call < fusion_call:
        issues.append("build_overlay must call normalize_custom_unit_focus_generation after finalize_conflux_fusion_units")
    if re.search(r'stats\["energyPer(Cast|Round|TakeDamage)"\]\s*=', FUSION.read_text(encoding="utf-8")):
        issues.append("fusion overlay sets a Focus generation stat; the generator normalizer owns it")
    return issues, exceptions


def core_issues(core: Path, exceptions: dict) -> tuple[list[str], str]:
    issues: list[str] = []
    with zipfile.ZipFile(core) as zf:
        names = zf.namelist()
        logic: dict[str, dict] = {}
        for name in names:
            if name.startswith("DB/units/units_logics/") and name.endswith(".json"):
                try:
                    doc = json.loads(zf.read(name).decode("utf-8-sig"))
                except ValueError:
                    continue
                for row in doc.get("array") or [] if isinstance(doc, dict) else []:
                    if isinstance(row, dict) and row.get("id"):
                        logic[row["id"]] = row
        lang: dict[str, str] = {}
        for name in names:
            if name.startswith("Lang/english/") and name.endswith(".json"):
                try:
                    for token in json.loads(zf.read(name).decode("utf-8-sig")).get("tokens") or []:
                        lang[token.get("sid")] = token.get("text") or ""
                except (ValueError, AttributeError):
                    continue
        for sid in exceptions:
            view = next((n for n in names if n.startswith("DB/units/units_views/") and n.endswith(f"/{sid}_v.json")), None)
            text = zf.read(view).decode("utf-8-sig") if view else ""
            if not any("Focus" in lang.get(k, "") for k in re.findall(r'"([A-Za-z0-9_]+_description)"', text)):
                issues.append(f"{sid}: Focus generation exception has no card mentioning Focus")
    custom = {sid: row for sid, row in logic.items() if sid.startswith("h3_")}
    vanilla = {sid: row for sid, row in logic.items() if not sid.startswith("h3_")}
    for sid, row in sorted(custom.items()):
        stats = row.get("stats") or {}
        for key, value in expected(row, exceptions).items():
            if stats.get(key) != value:
                issues.append(f"{sid} ({attack_class(row)}): {key}={stats.get(key)!r}, expected {value}")
    split = Counter()
    for sid, row in vanilla.items():
        stats = row.get("stats") or {}
        ok = all(stats.get(k) == v for k, v in expected(row, {}).items())
        split[ok] += 1
        if not ok and sid not in VANILLA_CARDED_DEVIATIONS:
            issues.append(f"vanilla {sid} deviates from melee 2 / ranged 1 (philosophy changed? re-audit)")
    summary = f"{len(custom)} custom rows checked, vanilla {split[True]} on-rule / {split[False]} carded deviations"
    return issues, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--core", type=Path, default=DEFAULT_CORE)
    ap.add_argument("--static-only", action="store_true")
    args = ap.parse_args()
    issues, exceptions = static_issues()
    summary = "static only"
    if not args.static_only:
        if not args.core.exists():
            issues.append(f"Core.zip not found: {args.core}")
        else:
            more, summary = core_issues(args.core, exceptions)
            issues += more
    if issues:
        print(f"custom unit Focus generation contract FAILED ({len(issues)} issue(s)):")
        for issue in issues[:80]:
            print(f"  - {issue}")
        return 1
    print(f"custom unit Focus generation contract OK: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
