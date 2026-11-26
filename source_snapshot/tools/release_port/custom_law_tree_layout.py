#!/usr/bin/env python3
"""Custom faction law trees: slots and icons follow the law's effect, not its index.

Custom law tables are written by index (`fraction_law_homm3_<faction>_<n>`), and the
tree (`fractionLawsLines`) used to be the donor faction's lines with the prefix renamed.
A donor's index n is a different law than the custom faction's index n (nature keeps
Resource Riches at 4/15/26, the generator at 3/16/29), so unit laws landed in the
kingdom column under Resource Riches art and Resource Riches landed in the army column.

* `arrange_law_lines` (run by apply_release_core_overlay.py): a law's column comes from
  its effect (kingdom/hero laws in group 0, army laws in group 1, as in every vanilla
  tree); Resource Riches I/II/III lead lines 0/2/4; a law tied to one unit line sits in
  that tier's vanilla line band. Every other law stays on the line the donor tree gave it
  unless a column is full.
* `law_tree_problems` (validate_custom_law_tree_layout.py): checks a built Core.zip
  against those slots and against the icon rule: a vanilla law icon is art for the
  vanilla law that owns it, so resource, grant and astrology art only goes on a law of
  that kind and the art of a vanilla unit law goes on no custom law.
* `resolve_law_icons` proposes replacements for the validator's `--propose`; icons
  themselves are authored in custom_factions/law_overrides.

Generated-artifact proof only: none of this shows how the law window draws.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable

KINGDOM = "kingdom"
ARMY = "army"
GROUP_BY_ROLE = {KINGDOM: 0, ARMY: 1}

# Vanilla trees on 26615913 (human, undead, dungeon, nature, demon, unfrozen): five lines
# of two groups, two to four laws per group.
LINE_COUNT = 5
GROUP_COUNT = 2
GROUP_MIN_LAWS = 2
GROUP_MAX_LAWS = 4
RICHES_LINES = (0, 2, 4)
RICHES_RESOURCES = frozenset({"gold", "wood", "ore"})

# Line of the vanilla "Elite <unit>" law per unit tier, lowest and highest over human,
# undead, dungeon and nature on 26615913.
UNIT_TIER_LINE_BAND: dict[int, tuple[int, int]] = {
    1: (0, 0),
    2: (0, 1),
    3: (1, 1),
    4: (1, 2),
    5: (2, 3),
    6: (2, 3),
    7: (3, 4),
}

# Vanilla "Mining: <resource>" art per produced resource, by the live vanilla law that
# draws it on 26615913 (human_1, human_14 Mining: Gems, nature_13 Mining: Crystals,
# undead_13 Mining: Mercury). These keys are vanilla law indices and move when vanilla
# redraws a tree; `law_tree_problems` fails when one stops being that resource's art.
DIRECT_RESOURCE_LAW_ICONS: dict[str, str] = {
    "gold": "fraction_law_human_1_icon",
    "gems": "fraction_law_human_14_icon",
    "gemstones": "fraction_law_human_14_icon",
    "crystal": "fraction_law_nature_13_icon",
    "crystals": "fraction_law_nature_13_icon",
    "mercury": "fraction_law_undead_13_icon",
}

VANILLA_LAW_FACTIONS = ("human", "nature", "dungeon", "undead", "demon", "unfrozen")
# Demon and unfrozen art is drawn for the hive and the ice; it replaces an icon only when
# the current one cannot stay.
VANILLA_LAW_FACTIONS_FOR_OPTIONAL_REPLACEMENT = ("human", "nature", "dungeon", "undead")
VANILLA_LAW_ICON_RE = re.compile(r"fraction_law_(%s)_(\d+)_icon" % "|".join(VANILLA_LAW_FACTIONS))

_KINGDOM_BONUS_TYPES = frozenset(
    {
        "sideStat",
        "sideObjectViewRadius",
        "constructionDiscount",
        "constructionDailyLimit",
        "unitHiringDiscount",
        "unitUpgradingDiscount",  # vanilla demon_20 sits in the kingdom column (law pass 2026-11-21)
        "magicGuildIncrement",
        "magicGuildLearnAdditionMagicAllOpenLevel",
        "barrackUnitsIncrementPer",
    }
)
# Placed law pairs with identical bonuses that still wait for a design decision: each pair
# stacks the same effect twice. Any other identical pair fails `law_tree_problems`. Empty
# since 2026-11-17 (Phoenix Omen and Goblin Pressgang got their own effects).
PENDING_DUPLICATE_EFFECT_LAWS: frozenset[frozenset[str]] = frozenset()

_RESOURCE_KIND_PREFIXES = ("riches", "grant", "income", "astrology")


def law_bonuses(row: dict[str, Any]) -> list[dict[str, Any]]:
    bonuses: list[dict[str, Any]] = []
    for level in row.get("parametersPerLevel") or []:
        if isinstance(level, dict):
            bonuses.extend(
                bonus for bonus in level.get("bonuses") or [] if isinstance(bonus, dict) and not is_display_only_bonus(bonus)
            )
    return bonuses


def _parameters(bonus: dict[str, Any]) -> list[Any]:
    parameters = bonus.get("parameters")
    return parameters if isinstance(parameters, list) else []


def bonus_kind(bonus: dict[str, Any]) -> str:
    bonus_type = str(bonus.get("type") or "")
    parameters = _parameters(bonus)
    first = str(parameters[0]) if parameters else ""
    if bonus_type == "sideOneTimeAddRes":
        return "riches" if first in RICHES_RESOURCES else "grant:" + first
    if bonus_type == "sideRes":
        return "income:" + first
    if bonus_type == "astrologyExp":
        return "astrology"
    if bonus_type == "cityUnitsIncrement":
        return "muster"
    if bonus_type.startswith("heroStat"):
        return "hero"
    if bonus_type == "battleSubskillBonus":
        return "hero" if first == "hero_ability" else "army"
    if bonus_type in _KINGDOM_BONUS_TYPES:
        return "kingdom"
    if bonus_type.startswith("unit"):
        return "army"
    return "unknown"


def law_kind(row: dict[str, Any]) -> str:
    """riches | grant:<resource> | income:<resource> | astrology | muster | army | hero | kingdom | mixed | unknown."""
    kinds = {bonus_kind(bonus) for bonus in law_bonuses(row)}
    if not kinds or "unknown" in kinds:
        return "unknown"
    if "muster" in kinds:
        return "muster" if kinds <= {"muster", "army"} else "mixed"
    if len(kinds) == 1:
        return next(iter(kinds))
    if all(kind.startswith(_RESOURCE_KIND_PREFIXES) or kind == "kingdom" for kind in kinds):
        return "kingdom"
    return "mixed"


def is_resource_kind(kind: str) -> bool:
    return kind.startswith(_RESOURCE_KIND_PREFIXES)


def law_role(row: dict[str, Any]) -> str | None:
    """Column the law belongs to; None when its bonuses span both or are not classified."""
    kind = law_kind(row)
    if kind in ("muster", "army"):
        return ARMY
    if kind in ("mixed", "unknown"):
        return None
    return KINGDOM


def riches_gold(row: dict[str, Any]) -> int:
    for bonus in law_bonuses(row):
        parameters = _parameters(bonus)
        if bonus.get("type") == "sideOneTimeAddRes" and len(parameters) >= 2 and parameters[0] == "gold":
            try:
                return int(float(parameters[1]))
            except (TypeError, ValueError):
                return 0
    return 0


def bonus_signature(bonus: dict[str, Any], *, allegiance: bool = True) -> str:
    bonus_type = str(bonus.get("type") or "")
    parameters = [str(item) for item in _parameters(bonus)]
    if bonus_type.startswith("heroStat"):
        family = "hero"
    elif bonus_type.startswith("unit") and bonus_type != "unitHiringDiscount":
        family = "unit"
    else:
        family = bonus_type
    detail = ""
    if family in ("hero", "unit", "sideStat") and parameters:
        detail = parameters[0]
        if detail == "modifierSet" and len(parameters) >= 3:
            detail = parameters[1] + ":" + parameters[2]
        elif detail == "magicSchoolSet" and len(parameters) >= 3:
            detail = "magicSchoolSet:" + ("level" if parameters[2] in ("0", "0.0") else "tier")
        elif detail in ("resPercentIncrementSet", "energyValuesSet") and len(parameters) >= 2:
            detail = detail + ":" + parameters[1]
    elif bonus_type in ("sideRes", "sideOneTimeAddRes", "constructionDiscount") and parameters:
        detail = parameters[0]
    signature = family + (":" + detail if detail else "")
    if allegiance and bonus.get("receiverAllegiance") == "enemy":
        signature = "enemy:" + signature
    return signature


def law_signatures(row: dict[str, Any], *, allegiance: bool = True) -> frozenset[str]:
    return frozenset(bonus_signature(bonus, allegiance=allegiance) for bonus in law_bonuses(row))


DISPLAY_ONLY_ACTIVATION_LEVEL = 99


def is_display_only_bonus(bonus: dict[str, Any]) -> bool:
    """A bonus that only carries a number for the law description ({0} via laws.script); the game never activates it."""
    try:
        return int(bonus.get("activationLevel", 1)) >= DISPLAY_ONLY_ACTIVATION_LEVEL
    except (TypeError, ValueError):
        return False


def law_effect(row: dict[str, Any]) -> tuple[str, ...]:
    """Every bonus of every rank, exactly (receiver order ignored), as one comparable key."""
    effect: list[str] = []
    for rank, level in enumerate(row.get("parametersPerLevel") or []):
        if not isinstance(level, dict):
            continue
        for bonus in level.get("bonuses") or []:
            if isinstance(bonus, dict) and not is_display_only_bonus(bonus):
                normalized = dict(bonus)
                if isinstance(normalized.get("receivers"), list):
                    normalized["receivers"] = sorted(str(item) for item in normalized["receivers"])
                effect.append(f"{rank}:" + json.dumps(normalized, sort_keys=True))
    return tuple(sorted(effect))


def law_unit_sids(row: dict[str, Any]) -> set[str]:
    sids: set[str] = set()
    for bonus in law_bonuses(row):
        for receiver in bonus.get("receivers") or []:
            if isinstance(receiver, str):
                sids.add(receiver)
        if bonus.get("type") == "cityUnitsIncrement":
            parameters = _parameters(bonus)
            if parameters and isinstance(parameters[0], str):
                sids.add(parameters[0])
    return sids


def manifest_unit_lines(manifest: dict[str, Any]) -> dict[str, tuple[int, str]]:
    """Unit sid -> (tier, base sid) for the faction's seven unit lines."""
    variants = manifest.get("unitVariants") or ["", "_upg", "_upg_alt"]
    result: dict[str, tuple[int, str]] = {}
    for line in manifest.get("unitLines") or []:
        if not isinstance(line, dict) or not line.get("baseSid"):
            continue
        tier = int(line.get("tier") or 0)
        base_sid = str(line["baseSid"])
        variant_sids = line.get("variantSids") if isinstance(line.get("variantSids"), dict) else {}
        for suffix in variants:
            sid = variant_sids.get(suffix) or base_sid + suffix
            result[str(sid)] = (tier, base_sid)
    return result


def law_single_unit_line(row: dict[str, Any], unit_lines: dict[str, tuple[int, str]]) -> tuple[int, str] | None:
    """(tier, base sid) when every unit the law names belongs to one unit line."""
    lines = {unit_lines.get(sid) for sid in law_unit_sids(row)}
    if len(lines) != 1 or None in lines:
        return None
    return next(iter(lines))


def placed_laws(lines: Any) -> list[tuple[int, int, int, str]]:
    result: list[tuple[int, int, int, str]] = []
    for line_index, line in enumerate(lines if isinstance(lines, list) else []):
        groups = line.get("groups") if isinstance(line, dict) else None
        for group_index, group in enumerate(groups if isinstance(groups, list) else []):
            laws = group.get("laws") if isinstance(group, dict) else None
            for position, law in enumerate(laws if isinstance(laws, list) else []):
                if isinstance(law, str):
                    result.append((line_index, group_index, position, law))
    return result


def _pinned_riches(
    placed: Iterable[tuple[int, int, int, str]], rows_by_id: dict[str, dict[str, Any]]
) -> dict[str, int]:
    """Law sid -> line for the first Resource Riches law of each amount, smallest first."""
    by_gold: dict[int, str] = {}
    for _line, _group, _position, law in placed:
        row = rows_by_id.get(law)
        if row is not None and law_kind(row) == "riches":
            by_gold.setdefault(riches_gold(row), law)
    if len(by_gold) != len(RICHES_LINES):
        return {}
    return {by_gold[gold]: RICHES_LINES[rank] for rank, gold in enumerate(sorted(by_gold))}


def _assign_lines(costs: list[list[float]], low: list[int], high: list[int]) -> list[int]:
    """Line per law for the least total cost with low[line]..high[line] laws on each line.

    costs[law][line]; the first of equally cheap answers in law order wins, so an
    arrangement that already satisfies the rules is returned unchanged.
    """
    line_count = len(low)
    start = (0,) * line_count
    states: dict[tuple[int, ...], tuple[float, tuple[int, ...]]] = {start: (0.0, ())}
    for law_costs in costs:
        following: dict[tuple[int, ...], tuple[float, tuple[int, ...]]] = {}
        for counts, (cost, path) in states.items():
            for line in range(line_count):
                if counts[line] >= high[line] or law_costs[line] == float("inf"):
                    continue
                key = counts[:line] + (counts[line] + 1,) + counts[line + 1 :]
                candidate = (cost + law_costs[line], path + (line,))
                if key not in following or candidate < following[key]:
                    following[key] = candidate
        states = following
    answers = [
        answer
        for counts, answer in states.items()
        if all(counts[line] >= low[line] for line in range(line_count))
    ]
    if not answers:
        raise RuntimeError(f"cannot place {len(costs)} laws on {line_count} lines of {low}..{high}")
    return list(min(answers)[1])


def arrange_law_lines(
    lines: list[dict[str, Any]],
    rows_by_id: dict[str, dict[str, Any]],
    unit_lines: dict[str, tuple[int, str]],
    label: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Donor-shaped lines with every placed law moved to the slot its effect asks for."""
    if len(lines) != LINE_COUNT or any(
        not isinstance(line, dict) or len(line.get("groups") or []) != GROUP_COUNT for line in lines
    ):
        raise RuntimeError(f"{label}: law tree is not {LINE_COUNT} lines of {GROUP_COUNT} groups; re-derive the layout rules")
    placed = placed_laws(lines)
    sids = [law for _line, _group, _position, law in placed]
    duplicates = sorted({law for law in sids if sids.count(law) > 1})
    if duplicates:
        raise RuntimeError(f"{label}: laws placed more than once: {', '.join(duplicates)}")
    missing = sorted(law for law in sids if law not in rows_by_id)
    if missing:
        raise RuntimeError(f"{label}: laws in the tree without a table row: {', '.join(missing)}")

    pinned = _pinned_riches(placed, rows_by_id)
    by_role: dict[str, list[dict[str, Any]]] = {KINGDOM: [], ARMY: []}
    for line_index, group_index, position, law in placed:
        row = rows_by_id[law]
        role = law_role(row) or (ARMY if group_index == GROUP_BY_ROLE[ARMY] else KINGDOM)
        unit_line = law_single_unit_line(row, unit_lines) if role == ARMY else None
        band = UNIT_TIER_LINE_BAND.get(unit_line[0]) if unit_line is not None else None
        costs: list[float] = []
        for line in range(LINE_COUNT):
            if law in pinned:
                costs.append(0.0 if line == pinned[law] else float("inf"))
            elif band is not None and not band[0] <= line <= band[1]:
                costs.append(float("inf"))
            else:
                costs.append(float(abs(line - line_index)))
        by_role[role].append(
            {
                "law": law,
                "from": (line_index, group_index, position),
                "costs": costs,
                "lead": 0 if law in pinned or law_kind(row) == "muster" else 1,
                "tier": unit_line[0] if unit_line is not None and law_kind(row) == "muster" else 0,
            }
        )

    arranged = [
        {**line, "groups": [{**group, "laws": []} for group in line["groups"]]} for line in lines
    ]
    for role, entries in by_role.items():
        entries.sort(key=lambda entry: entry["from"])
        low = min(GROUP_MIN_LAWS, len(entries) // LINE_COUNT)
        assigned = _assign_lines(
            [entry["costs"] for entry in entries], [low] * LINE_COUNT, [GROUP_MAX_LAWS] * LINE_COUNT
        )
        for entry, line_index in zip(entries, assigned):
            entry["to"] = line_index
        for line_index in range(LINE_COUNT):
            group = [entry for entry in entries if entry["to"] == line_index]
            group.sort(
                key=lambda entry: (entry["lead"], entry["tier"], entry["from"][0] != line_index, entry["from"])
            )
            arranged[line_index]["groups"][GROUP_BY_ROLE[role]]["laws"] = [entry["law"] for entry in group]

    before = {law: (line, group, position) for line, group, position, law in placed}
    moves = [
        f"{law} L{before[law][0]}G{before[law][1]}P{before[law][2]} -> L{line}G{group}P{position}"
        for line, group, position, law in placed_laws(arranged)
        if before[law] != (line, group, position)
    ]
    return arranged, moves


def vanilla_law_tables(core: zipfile.ZipFile) -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {}
    for faction in VANILLA_LAW_FACTIONS:
        try:
            doc = json.loads(core.read(f"DB/fractions_laws/fractions_laws_table_{faction}.json").decode("utf-8-sig"))
        except KeyError:
            continue
        tables[faction] = [row for row in doc.get("array") or [] if isinstance(row, dict)]
    if "human" not in tables:
        raise RuntimeError("Core has no vanilla human law table to read icon owners from")
    return tables


def vanilla_icon_owners(tables: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Icon key -> vanilla law rows drawn with it, in VANILLA_LAW_FACTIONS order."""
    owners: dict[str, list[dict[str, Any]]] = {}
    for faction in VANILLA_LAW_FACTIONS:
        for row in tables.get(faction, []):
            icon = row.get("icon")
            if isinstance(icon, str) and icon:
                owners.setdefault(icon, []).append(row)
    return owners


def is_vanilla_unit_art(owner: dict[str, Any]) -> bool:
    """Vanilla "Elite <unit>" laws: their icon shows that vanilla unit."""
    return law_kind(owner) == "muster" or (law_kind(owner) == "army" and 0 < len(law_unit_sids(owner)) <= 3)


def _shares_effect(row: dict[str, Any], owners: list[dict[str, Any]]) -> bool:
    signatures = law_signatures(row, allegiance=False)
    return any(signatures & law_signatures(owner, allegiance=False) for owner in owners)


def icon_hard_problem(icon: str, row: dict[str, Any], owners_by_icon: dict[str, list[dict[str, Any]]]) -> str | None:
    """Why a vanilla law icon cannot be on this law, or None. Custom keys and portraits pass."""
    kind = law_kind(row)
    owners = owners_by_icon.get(icon)
    if owners is None:
        if VANILLA_LAW_ICON_RE.fullmatch(icon):
            return f"{icon} is not drawn by any live vanilla law"
        return None
    owner_kinds = {law_kind(owner) for owner in owners}
    resource_owner_kinds = {owner_kind for owner_kind in owner_kinds if is_resource_kind(owner_kind)}
    if resource_owner_kinds and kind not in owner_kinds:
        return f"{icon} is {'/'.join(sorted(resource_owner_kinds))} art; the law is {kind}"
    if is_resource_kind(kind) and kind not in owner_kinds:
        return f"{kind} law drawn with {icon}, the art of a {'/'.join(sorted(owner_kinds))} law"
    if any(is_vanilla_unit_art(owner) for owner in owners):
        return f"{icon} is the art of a vanilla unit law"
    return None


def icon_role_mismatch(icon: str, row: dict[str, Any], owners_by_icon: dict[str, list[dict[str, Any]]]) -> str | None:
    """Vanilla icon from the other column whose owner shares no effect with the law."""
    owners = owners_by_icon.get(icon)
    role = law_role(row)
    if owners is None or role is None:
        return None
    if any(law_role(owner) in (role, None) for owner in owners) or _shares_effect(row, owners):
        return None
    return f"{icon} is {law_kind(owners[0])} art; the law is {law_kind(row)}"


def _effect_icon(
    row: dict[str, Any], owners_by_icon: dict[str, list[dict[str, Any]]], used: set[str], exact: bool
) -> str | None:
    """Icon of the vanilla law with the same effect; unless `exact`, else the closest superset or subset."""
    kind = law_kind(row)
    role = law_role(row)
    best: tuple[tuple[int, int, int], str] | None = None
    order = 0
    for icon, owners in owners_by_icon.items():
        for owner in owners:
            order += 1
            owner_kind = law_kind(owner)
            if is_vanilla_unit_art(owner) or (is_resource_kind(owner_kind) or is_resource_kind(kind)) and owner_kind != kind:
                continue
            if exact and not str(owner.get("id")).startswith(
                tuple(f"fraction_law_{faction}_" for faction in VANILLA_LAW_FACTIONS_FOR_OPTIONAL_REPLACEMENT)
            ):
                continue
            if kind == "riches" and riches_gold(owner) != riches_gold(row):
                continue
            if law_role(owner) != role:
                continue
            rank = None
            for step, allegiance in enumerate((True, False)):
                mine = law_signatures(row, allegiance=allegiance)
                theirs = law_signatures(owner, allegiance=allegiance)
                if mine == theirs:
                    rank = step * 3
                elif mine < theirs:
                    rank = step * 3 + 1
                elif theirs < mine:
                    rank = step * 3 + 2
                if rank is not None:
                    break
            if rank is None or (exact and rank not in (0, 3)):
                continue
            key = (1 if icon in used else 0, rank, order)
            if best is None or key < best[0]:
                best = (key, icon)
    return best[1] if best is not None else None


def resolve_law_icons(
    rows: list[dict[str, Any]],
    owners_by_icon: dict[str, list[dict[str, Any]]],
    unit_lines: dict[str, tuple[int, str]],
    declared_portraits: dict[int, str],
    label: str,
) -> tuple[list[str], list[str]]:
    """Replace, in place, every vanilla icon that is art for a different kind of law.

    Art that cannot be on the law (resource art on another kind of law, a vanilla unit,
    a key no live vanilla law draws) is always replaced: declared or unused unit portrait,
    then the vanilla law with the closest effect. Art from the other column is replaced
    only by a declared or unused portrait or by a human, nature, dungeon or undead law
    with exactly the same effect; otherwise it is returned in `kept` for a design decision.
    """
    rejected: list[tuple[dict[str, Any], str, bool]] = []
    for row in rows:
        icon = str(row.get("icon") or "")
        hard = icon_hard_problem(icon, row, owners_by_icon)
        problem = hard or icon_role_mismatch(icon, row, owners_by_icon)
        if problem is not None:
            rejected.append((row, problem, hard is not None))
    rejected_ids = {id(row) for row, _problem, _hard in rejected}
    used = {str(row.get("icon")) for row in rows if id(row) not in rejected_ids}
    changes: list[str] = []
    kept: list[str] = []
    for row, problem, hard in rejected:
        icon = str(row["icon"])
        index = int(str(row["id"]).rsplit("_", 1)[1])
        portrait: str | None = None
        declared = False
        if law_role(row) == ARMY:
            named = {unit_lines[sid][1] for sid in law_unit_sids(row) if sid in unit_lines}
            unit_line = law_single_unit_line(row, unit_lines)
            if declared_portraits.get(index) in named:
                portrait, declared = declared_portraits[index], True
            elif unit_line is not None:
                portrait = unit_line[1]
        effect = _effect_icon(row, owners_by_icon, used, exact=not hard)
        if portrait is not None and (declared or portrait not in used):
            replacement = portrait
        elif effect is not None and effect != icon:
            replacement = effect
        else:
            replacement = portrait if hard else None
        if replacement is None:
            if hard:
                raise RuntimeError(
                    f"{label}: {row['id']} has no icon for its effect ({problem}); "
                    "give its law override a homm4IconPath/iconKey, portraitIconSid or effectIconKey"
                )
            used.add(icon)
            kept.append(f"{row['id']} keeps {icon} ({problem})")
            continue
        row["icon"] = replacement
        used.add(replacement)
        changes.append(f"{row['id']} {icon} -> {replacement} ({problem})")
    return changes, kept


def law_tree_problems(
    faction_sid: str,
    lines: Any,
    rows: list[dict[str, Any]],
    owners_by_icon: dict[str, list[dict[str, Any]]],
    unit_lines: dict[str, tuple[int, str]],
    custom_icon_keys: set[str],
    names: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one custom faction's built law table and tree."""
    errors: list[str] = []
    warnings: list[str] = []
    names = names or {}
    rows_by_id = {str(row.get("id")): row for row in rows}

    def title(law: str) -> str:
        row = rows_by_id.get(law) or {}
        return f"{law} ({names.get(str(row.get('name')), '?')})"

    if not isinstance(lines, list) or len(lines) != LINE_COUNT:
        return [f"{faction_sid}: law tree has {len(lines) if isinstance(lines, list) else 'no'} lines, expected {LINE_COUNT}"], warnings
    placed = placed_laws(lines)
    seen: set[str] = set()
    for line_index, line in enumerate(lines):
        groups = line.get("groups") if isinstance(line, dict) else None
        if not isinstance(groups, list) or len(groups) != GROUP_COUNT:
            errors.append(f"{faction_sid}: line {line_index} does not have {GROUP_COUNT} groups")
            continue
        for group_index, group in enumerate(groups):
            size = len(group.get("laws") or []) if isinstance(group, dict) else 0
            if not GROUP_MIN_LAWS <= size <= GROUP_MAX_LAWS:
                errors.append(f"{faction_sid}: line {line_index} group {group_index} holds {size} laws ({GROUP_MIN_LAWS}..{GROUP_MAX_LAWS})")
    pinned = _pinned_riches(placed, rows_by_id)
    for line_index, group_index, position, law in placed:
        where = f"line {line_index} group {group_index} slot {position}"
        if law in seen:
            errors.append(f"{faction_sid}: {law} is placed twice ({where})")
            continue
        seen.add(law)
        row = rows_by_id.get(law)
        if row is None:
            errors.append(f"{faction_sid}: {law} at {where} has no law table row")
            continue
        role = law_role(row)
        if role is not None and GROUP_BY_ROLE[role] != group_index:
            errors.append(f"{faction_sid}: {title(law)} is a {law_kind(row)} law in the {'army' if group_index else 'kingdom'} group ({where})")
        if law in pinned and (line_index, group_index, position) != (pinned[law], 0, 0):
            errors.append(f"{faction_sid}: {title(law)} must lead line {pinned[law]}, found at {where}")
        unit_line = law_single_unit_line(row, unit_lines) if role == ARMY else None
        if unit_line is not None and unit_line[0] in UNIT_TIER_LINE_BAND:
            low, high = UNIT_TIER_LINE_BAND[unit_line[0]]
            if not low <= line_index <= high:
                errors.append(f"{faction_sid}: {title(law)} is a tier {unit_line[0]} unit law on line {line_index} (lines {low}..{high})")

    effects: dict[tuple[str, ...], list[str]] = {}
    for law in seen:
        if law in rows_by_id:
            effects.setdefault(law_effect(rows_by_id[law]), []).append(law)
    for effect, laws in effects.items():
        if effect and len(laws) > 1:
            pair = ", ".join(title(law) for law in sorted(laws))
            if frozenset(laws) in PENDING_DUPLICATE_EFFECT_LAWS:
                warnings.append(f"{faction_sid}: same effect placed twice, pending decision: {pair}")
            else:
                errors.append(f"{faction_sid}: same effect placed twice, so it stacks: {pair}")

    unit_sids = set(unit_lines)
    icons: dict[str, list[str]] = {}
    titles: dict[str, list[str]] = {}
    for row in rows:
        law = str(row.get("id"))
        icon = row.get("icon")
        if not isinstance(icon, str) or not icon:
            errors.append(f"{faction_sid}: {title(law)} has no icon")
            continue
        if law in seen:
            icons.setdefault(icon, []).append(law)
            titles.setdefault(names.get(str(row.get("name")), law), []).append(law)
        if icon in owners_by_icon:
            problem = icon_hard_problem(icon, row, owners_by_icon)
            if problem is not None:
                errors.append(f"{faction_sid}: {title(law)}: {problem}")
            else:
                soft = icon_role_mismatch(icon, row, owners_by_icon)
                if soft is not None:
                    warnings.append(f"{faction_sid}: {title(law)}: {soft}")
        elif icon.startswith("h3_"):
            if icon not in unit_sids:
                errors.append(f"{faction_sid}: {title(law)} uses portrait {icon}, not a unit of the faction")
            elif unit_lines[icon][1] not in {unit_lines[sid][1] for sid in law_unit_sids(row) if sid in unit_lines}:
                errors.append(f"{faction_sid}: {title(law)} uses portrait {icon} but does not affect that unit line")
        elif icon not in custom_icon_keys:
            errors.append(f"{faction_sid}: {title(law)} icon {icon} is neither a vanilla law icon, a faction unit, nor a shipped custom law icon")
        if law not in seen:
            warnings.append(f"{faction_sid}: {title(law)} is in the table but not in the tree")
    for icon, laws in sorted(icons.items()):
        if len(laws) > 1:
            warnings.append(f"{faction_sid}: icon {icon} is shared by {', '.join(laws)}")
    for name, laws in sorted(titles.items()):
        if len(laws) > 1:
            warnings.append(f"{faction_sid}: name {name!r} is shared by {', '.join(laws)}")
    return errors, warnings


def custom_law_icon_keys(icon_dir: Path) -> set[str]:
    return {path.stem for path in icon_dir.glob("*.png")}
