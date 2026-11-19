"""Upgrade-pair parity for the HoMM3 faction unit lines (vanilla's bookkeeping rules).

Contract: custom_factions/contracts/homm3_upgrade_pair_parity_20261116.json

Vanilla Olden Era (Steam 26615913, 42 faction lines) keeps four things fixed on every
base -> upgrade / alternate-upgrade line, whatever the two upgrades do differently:
  * upgrade and alternate upgrade cost the same (gold and rare resources);
  * they share squadValue and expBonus;
  * neither has a stat below the base form;
  * expBonus is squadValue times a per-tier ratio.
The custom lines inherited squadValue/expBonus from donor rows and side-branch estimates,
so this pass re-derives them. It runs after the 20260625 balance contract and before the
passes that read final unit rows (Conflux fusion stats, reward-unit containers).

Rule order per line (the contract's rules.order):
  1. lineStatOverrides - the few hand values the rules cannot derive;
  2. statFloor         - upgrade/alternate stat below base is raised to base;
  3. pairParity        - alternate takes the upgrade's squadValue and whole unitCost;
  4. expBonus          - all three variants get round_half_up(squadValue * tier ratio).

The same functions back tools/validate_homm3_upgrade_pair_parity_contract.py, which is
the gate: it re-checks a built Core against these rules.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIR = REPO_ROOT / "custom_factions"
CONTRACT_PATH = MANIFEST_DIR / "contracts" / "homm3_upgrade_pair_parity_20261116.json"
LOGIC_PREFIX = "DB/units/units_logics/"
FLOOR_STATS = ("hp", "offence", "defence", "damageMin", "damageMax", "initiative", "speed")
RULE_ORDER = ["lineStatOverrides", "statFloor", "pairParity", "expBonus"]
TIERS = tuple(range(1, 8))
VARIANT_SUFFIXES = ("", "_upg", "_upg_alt")

# (factionSid, baseSid, upgSid, altSid)
Line = tuple[str, str, str, str]
# (unitSid, field, before, after, rule)
Change = tuple[str, str, Any, Any, str]


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing HoMM3 upgrade pair parity contract: {path}")
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("schemaVersion") != 1:
        raise RuntimeError("HoMM3 upgrade pair parity contract has an unsupported schemaVersion")
    if (doc.get("rules") or {}).get("order") != RULE_ORDER:
        raise RuntimeError(f"HoMM3 upgrade pair parity contract rules.order must be {RULE_ORDER}")
    if tuple(doc.get("floorStats") or ()) != FLOOR_STATS:
        raise RuntimeError(f"HoMM3 upgrade pair parity contract floorStats must be {list(FLOOR_STATS)}")
    ratios = doc.get("expBonusPerSquadValueByTier")
    if not isinstance(ratios, dict) or sorted(ratios) != [str(t) for t in TIERS]:
        raise RuntimeError("HoMM3 upgrade pair parity contract needs expBonusPerSquadValueByTier for tiers 1-7")
    for tier, ratio in ratios.items():
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0.05 <= ratio <= 0.2:
            raise RuntimeError(f"HoMM3 upgrade pair parity contract tier {tier} expBonus ratio is not in 0.05-0.2")
    overrides = doc.get("lineStatOverrides")
    if not isinstance(overrides, list):
        raise RuntimeError("HoMM3 upgrade pair parity contract is missing lineStatOverrides[]")
    seen: set[str] = set()
    for index, entry in enumerate(overrides):
        if not isinstance(entry, dict):
            raise RuntimeError(f"HoMM3 upgrade pair parity lineStatOverrides[{index}] is not an object")
        sid = entry.get("unitSid")
        stats = entry.get("statOverrides")
        reason = entry.get("reason")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise RuntimeError(f"HoMM3 upgrade pair parity lineStatOverrides[{index}] has a missing or duplicate unitSid")
        seen.add(sid)
        if not isinstance(reason, str) or not reason.strip():
            raise RuntimeError(f"{sid}: upgrade pair parity override needs a reason")
        if not isinstance(stats, dict) or not stats:
            raise RuntimeError(f"{sid}: upgrade pair parity override needs statOverrides")
        for key, value in stats.items():
            if key == "cost":
                if not isinstance(value, dict) or not value or any(
                    not isinstance(res, str) or not isinstance(amount, int) or isinstance(amount, bool) or amount < 0
                    for res, amount in value.items()
                ):
                    raise RuntimeError(f"{sid}: upgrade pair parity override cost must map resource -> non-negative int")
            elif key in FLOOR_STATS or key == "squadValue":
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise RuntimeError(f"{sid}: upgrade pair parity override {key} must be a non-negative integer")
            else:
                raise RuntimeError(f"{sid}: upgrade pair parity override has unsupported key {key!r}")
    return doc


def manifest_core_overlay_enabled(manifest: dict[str, Any]) -> bool:
    validation = manifest.get("validation") or {}
    value = validation.get("coreOverlayEnabled")
    if isinstance(value, bool):
        return value
    return validation.get("releasePromotionBlocked") is not True


def load_enabled_manifests(manifest_dir: Path = MANIFEST_DIR) -> tuple[dict[str, Any], ...]:
    manifests = []
    for path in sorted(manifest_dir.glob("homm3_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        identity = data.get("identity") if isinstance(data, dict) else None
        if not isinstance(identity, dict) or not isinstance(identity.get("factionSid"), str):
            continue
        if manifest_core_overlay_enabled(data):
            manifests.append(data)
    return tuple(manifests)


def unit_lines(manifests: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[Line]:
    """Every base/upgrade/alternate line the enabled faction manifests declare."""
    lines: list[Line] = []
    for manifest in manifests:
        faction_sid = manifest["identity"]["factionSid"]
        variants = tuple(manifest.get("unitVariants") or VARIANT_SUFFIXES)
        if variants != VARIANT_SUFFIXES:
            raise RuntimeError(f"{faction_sid}: upgrade pair parity expects unitVariants {list(VARIANT_SUFFIXES)}")
        declared = list(manifest.get("unitLines") or []) + list(manifest.get("additionalRecruitmentLines") or [])
        for line in declared:
            variant_sids = line.get("variantSids") if isinstance(line.get("variantSids"), dict) else {}
            sids = tuple(variant_sids.get(suffix) or line["baseSid"] + suffix for suffix in VARIANT_SUFFIXES)
            lines.append((faction_sid, sids[0], sids[1], sids[2]))
    return lines


def cost_map(item: dict[str, Any], sid: str) -> dict[str, int]:
    unit_cost = item.get("unitCost")
    rows = unit_cost.get("costResArray") if isinstance(unit_cost, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"{sid}: unitCost.costResArray is missing or malformed")
    return {row["name"]: row["cost"] for row in rows}


def expected_exp_bonus(contract: dict[str, Any], tier: Any, squad_value: Any, sid: str) -> int:
    ratio = contract["expBonusPerSquadValueByTier"].get(str(tier))
    if ratio is None:
        raise RuntimeError(f"{sid}: tier {tier!r} has no expBonus ratio in the upgrade pair parity contract")
    if not isinstance(squad_value, int) or isinstance(squad_value, bool) or squad_value <= 0:
        raise RuntimeError(f"{sid}: squadValue {squad_value!r} is not a positive integer")
    return max(1, int(math.floor(squad_value * ratio + 0.5)))


def _stats(item: dict[str, Any], sid: str) -> dict[str, Any]:
    stats = item.get("stats")
    if not isinstance(stats, dict) or any(not isinstance(stats.get(key), (int, float)) for key in FLOOR_STATS):
        raise RuntimeError(f"{sid}: stats block is missing or lacks one of {list(FLOOR_STATS)}")
    return stats


def apply_to_rows(rows: dict[str, dict[str, Any]], lines: list[Line], contract: dict[str, Any]) -> list[Change]:
    """Mutate the line units' logic rows in place; return every field that moved."""
    changes: list[Change] = []
    line_sids = {sid for line in lines for sid in line[1:]}
    for line in lines:
        for sid in line[1:]:
            if sid not in rows:
                raise RuntimeError(f"{line[0]}: unit logic row for line unit {sid} is missing")

    for entry in contract["lineStatOverrides"]:
        sid = entry["unitSid"]
        if sid not in line_sids:
            raise RuntimeError(f"{sid}: upgrade pair parity override does not name a faction line unit")
        item = rows[sid]
        stats = _stats(item, sid)
        for key, value in entry["statOverrides"].items():
            if key == "cost":
                before = cost_map(item, sid)
                if before != value:
                    item["unitCost"]["costResArray"] = [{"name": res, "cost": amount} for res, amount in value.items()]
                    changes.append((sid, "cost", before, dict(value), "lineStatOverrides"))
            elif key == "squadValue":
                if item.get("squadValue") != value:
                    changes.append((sid, "squadValue", item.get("squadValue"), value, "lineStatOverrides"))
                    item["squadValue"] = value
            elif stats[key] != value:
                changes.append((sid, key, stats[key], value, "lineStatOverrides"))
                stats[key] = value

    for _faction, base_sid, upg_sid, alt_sid in lines:
        base, upg, alt = rows[base_sid], rows[upg_sid], rows[alt_sid]
        base_stats = _stats(base, base_sid)
        for sid, item in ((upg_sid, upg), (alt_sid, alt)):
            stats = _stats(item, sid)
            for key in FLOOR_STATS:
                if stats[key] < base_stats[key]:
                    changes.append((sid, key, stats[key], base_stats[key], "statFloor"))
                    stats[key] = base_stats[key]

        if alt.get("squadValue") != upg.get("squadValue"):
            changes.append((alt_sid, "squadValue", alt.get("squadValue"), upg.get("squadValue"), "pairParity"))
            alt["squadValue"] = upg.get("squadValue")
        upg_cost, alt_cost = cost_map(upg, upg_sid), cost_map(alt, alt_sid)
        if alt_cost != upg_cost:
            changes.append((alt_sid, "cost", alt_cost, upg_cost, "pairParity"))
            alt["unitCost"]["costResArray"] = copy.deepcopy(upg["unitCost"]["costResArray"])

        for sid, item in ((base_sid, base), (upg_sid, upg), (alt_sid, alt)):
            expected = expected_exp_bonus(contract, item.get("tier"), item.get("squadValue"), sid)
            if item.get("expBonus") != expected:
                changes.append((sid, "expBonus", item.get("expBonus"), expected, "expBonus"))
                item["expBonus"] = expected
    return changes


def check_rows(rows: dict[str, dict[str, Any]], lines: list[Line], contract: dict[str, Any]) -> list[str]:
    """Readback: every rule holds on already-built rows. Returns error strings."""
    errors: list[str] = []
    line_sids = {sid for line in lines for sid in line[1:]}
    for faction, base_sid, upg_sid, alt_sid in lines:
        missing = [sid for sid in (base_sid, upg_sid, alt_sid) if sid not in rows]
        if missing:
            errors.append(f"{faction}: line {base_sid} is missing unit logic rows {missing}")
            continue
        base, upg, alt = rows[base_sid], rows[upg_sid], rows[alt_sid]
        try:
            base_stats = _stats(base, base_sid)
            for sid, item in ((upg_sid, upg), (alt_sid, alt)):
                stats = _stats(item, sid)
                for key in FLOOR_STATS:
                    if stats[key] < base_stats[key]:
                        errors.append(f"{sid}: {key} {stats[key]} is below base {base_sid} {base_stats[key]}")
            upg_cost, alt_cost = cost_map(upg, upg_sid), cost_map(alt, alt_sid)
            if upg_cost != alt_cost:
                errors.append(f"{alt_sid}: cost {alt_cost} differs from upgrade {upg_sid} {upg_cost}")
            for field in ("squadValue", "expBonus"):
                if upg.get(field) != alt.get(field):
                    errors.append(f"{alt_sid}: {field} {alt.get(field)} differs from upgrade {upg_sid} {upg.get(field)}")
            for sid, item in ((base_sid, base), (upg_sid, upg), (alt_sid, alt)):
                expected = expected_exp_bonus(contract, item.get("tier"), item.get("squadValue"), sid)
                if item.get("expBonus") != expected:
                    errors.append(
                        f"{sid}: expBonus {item.get('expBonus')} is not the tier {item.get('tier')} value "
                        f"{expected} for squadValue {item.get('squadValue')}"
                    )
        except RuntimeError as ex:
            errors.append(str(ex))
    for entry in contract["lineStatOverrides"]:
        sid = entry["unitSid"]
        if sid not in line_sids or sid not in rows:
            errors.append(f"{sid}: upgrade pair parity override does not name a built faction line unit")
            continue
        item = rows[sid]
        for key, value in entry["statOverrides"].items():
            if key == "cost":
                actual = cost_map(item, sid)
            elif key == "squadValue":
                actual = item.get("squadValue")
            else:
                actual = (item.get("stats") or {}).get(key)
            if actual != value:
                errors.append(f"{sid}: contract override {key} {value} reads back as {actual}")
    return errors


def apply_homm3_upgrade_pair_parity(
    release_zip: Any,
    output: dict[str, bytes],
    notes: list[str],
    manifests: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    read_json: Callable[[Any, str], Any],
    write_json: Callable[[Any], bytes],
) -> list[Change]:
    """Generator pass: apply the contract to the line units' rows in the overlay output."""
    contract = load_contract()
    lines = unit_lines(manifests)
    wanted = {sid for line in lines for sid in line[1:]}
    docs: dict[str, tuple[str, Any]] = {}
    rows: dict[str, dict[str, Any]] = {}
    for name in sorted(set(release_zip.namelist()) | set(output)):
        if not name.startswith(LOGIC_PREFIX) or not name.endswith("_l.json"):
            continue
        sid = Path(name).name.removesuffix("_l.json")
        if sid not in wanted:
            continue
        doc = json.loads(output[name].decode("utf-8-sig")) if name in output else read_json(release_zip, name)
        array = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(array, list) or len(array) != 1 or not isinstance(array[0], dict) or array[0].get("id") != sid:
            raise RuntimeError(f"{sid}: malformed unit logic row for upgrade pair parity ({name})")
        if sid in rows:
            raise RuntimeError(f"{sid}: more than one unit logic member for upgrade pair parity")
        docs[sid] = (name, doc)
        rows[sid] = array[0]
    changes = apply_to_rows(rows, lines, contract)
    errors = check_rows(rows, lines, contract)
    if errors:
        raise RuntimeError("upgrade pair parity did not converge: " + "; ".join(errors[:8]))
    for sid in sorted({change[0] for change in changes}):
        name, doc = docs[sid]
        output[name] = write_json(doc)
    by_rule: dict[str, int] = {}
    for change in changes:
        by_rule[change[4]] = by_rule.get(change[4], 0) + 1
    notes.append(
        f"apply HoMM3 upgrade pair parity contract ({len(lines)} lines, "
        f"{len({change[0] for change in changes})} unit rows, "
        + ", ".join(f"{rule} {by_rule.get(rule, 0)}" for rule in RULE_ORDER)
        + ")"
    )
    return changes
