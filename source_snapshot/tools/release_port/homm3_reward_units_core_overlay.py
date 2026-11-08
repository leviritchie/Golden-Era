"""Core overlay: give custom-faction units native reward-unit rows.

Native unit-box rewards (Pandora's box / chest variants ``HeroBoxUnitReward`` and
``HeroBoxOptionalVersionUnitReward``) resolve their unit through
``DB.me.rewardUnitsContainer.GetUnits(tier, fraction, version)``, i.e. only the
rows listed in ``DB/reward_units_container.json``. When the resolved fraction is a
HoMM3 custom faction and none of its units are listed, the reward-parameter
builder returns null, ``CreateDataReward`` drops the reward, and the object's
reward set is created with an empty ``rewards`` list: the hero interacts and
nothing happens (Player.log: ``chest reward set info ... rewards list:`` empty,
no ``OnRewardSetApplied``).

This module owns one rule: every unit logic row of a core-enabled custom faction
with a tier the vanilla container prices (1..7) has exactly one container row. Custom
faction rows are priced from the vanilla rows' own per-tier budget
(median of ``amount * squadValue`` over vanilla faction units of that tier), so
the reward's army value tracks the vanilla faction boxes of the same tier.
"""

from __future__ import annotations

import json
import re
import statistics
import zipfile
from typing import Any, Iterable

REWARD_UNITS_MEMBER = "DB/reward_units_container.json"
UNIT_LOGICS_PREFIX = "DB/units/units_logics/"
NEUTRAL_FRACTION = "neutral"
# Vanilla prices every faction unit of tiers 1..7 (DB/reward_units_container.json).
FACTION_TIERS = frozenset(range(1, 8))


def _loads_lenient(raw: bytes) -> Any:
    text = raw.decode("utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Vanilla Core rows may carry trailing commas / line comments.
        text = re.sub(r"(?m)^\s*//[^\n]*", "", text)
        text = re.sub(r",(\s*[\]}])", r"\1", text)
        return json.loads(text)


def load_unit_logic_rows(members: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    """Return unit logic rows by id from ``{member: bytes}`` (overlay wins)."""
    rows: dict[str, dict[str, Any]] = {}
    for name in sorted(members):
        if not name.startswith(UNIT_LOGICS_PREFIX) or not name.endswith(".json"):
            continue
        doc = _loads_lenient(members[name])
        array = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(array, list):
            continue
        for row in array:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                rows[row["id"]] = row
    return rows


def _positive_int(value: Any) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def vanilla_tier_budgets(
    container_rows: list[dict[str, Any]],
    unit_rows: dict[str, dict[str, Any]],
    custom_faction_sids: set[str],
) -> dict[int, float]:
    samples: dict[int, list[int]] = {}
    for entry in container_rows:
        unit = unit_rows.get(entry.get("sid"))
        if unit is None:
            continue
        fraction = unit.get("fraction")
        if fraction == NEUTRAL_FRACTION or fraction in custom_faction_sids:
            continue
        amount = _positive_int(entry.get("amount"))
        squad_value = _positive_int(unit.get("squadValue"))
        tier = _positive_int(unit.get("tier"))
        if amount is None or squad_value is None or tier is None:
            continue
        samples.setdefault(tier, []).append(amount * squad_value)
    return {tier: float(statistics.median(values)) for tier, values in samples.items()}


def build_reward_unit_rows(
    container_doc: Any,
    unit_rows: dict[str, dict[str, Any]],
    custom_faction_sids: Iterable[str],
) -> tuple[dict[str, Any], list[str]]:
    """Return the rewritten container doc and the custom sids it priced.

    Raises RuntimeError (fail closed) when the vanilla container cannot price a
    custom unit's tier or a custom unit lacks squadValue.
    """
    factions = set(custom_faction_sids)
    if not isinstance(container_doc, dict) or not isinstance(container_doc.get("unitsArr"), list):
        raise RuntimeError(f"{REWARD_UNITS_MEMBER} has no unitsArr list")
    existing = [row for row in container_doc["unitsArr"] if isinstance(row, dict)]
    budgets = vanilla_tier_budgets(existing, unit_rows, factions)

    custom_units = sorted(
        (sid for sid, row in unit_rows.items() if row.get("fraction") in factions),
        key=lambda sid: (unit_rows[sid].get("fraction"), _positive_int(unit_rows[sid].get("tier")) or 0, sid),
    )
    if not custom_units:
        raise RuntimeError(
            "no unit logic rows found for custom factions " + ", ".join(sorted(factions))
        )

    kept = [
        row for row in existing
        if (unit_rows.get(row.get("sid")) or {}).get("fraction") not in factions
    ]
    added: list[dict[str, Any]] = []
    errors: list[str] = []
    for sid in custom_units:
        unit = unit_rows[sid]
        tier = _positive_int(unit.get("tier"))
        squad_value = _positive_int(unit.get("squadValue"))
        if tier is None or tier not in budgets:
            errors.append(f"{sid}: tier {unit.get('tier')!r} has no vanilla reward budget")
            continue
        if squad_value is None:
            errors.append(f"{sid}: squadValue {unit.get('squadValue')!r} is not a positive integer")
            continue
        added.append({"sid": sid, "amount": max(1, int(round(budgets[tier] / squad_value)))})
    if errors:
        raise RuntimeError(
            "custom reward units cannot be priced from the vanilla container: " + "; ".join(errors)
        )

    doc = dict(container_doc)
    doc["unitsArr"] = kept + added
    return doc, [row["sid"] for row in added]


def missing_reward_unit_rows(
    container_doc: Any,
    unit_rows: dict[str, dict[str, Any]],
    custom_faction_sids: Iterable[str],
) -> list[str]:
    """Contract: every custom-faction unit of tiers 1..7 has exactly one positive row.

    Vanilla rows are not judged (vanilla omits e.g. the summoned ``lava_larva``).
    """
    factions = set(custom_faction_sids)
    rows = container_doc.get("unitsArr") if isinstance(container_doc, dict) else None
    if not isinstance(rows, list):
        return [f"{REWARD_UNITS_MEMBER} has no unitsArr list"]
    counts: dict[str, int] = {}
    problems: list[str] = []
    for row in rows:
        sid = row.get("sid") if isinstance(row, dict) else None
        if not isinstance(sid, str):
            problems.append(f"row without sid: {row!r}")
            continue
        counts[sid] = counts.get(sid, 0) + 1
        if _positive_int(row.get("amount")) is None:
            problems.append(f"{sid}: amount {row.get('amount')!r} is not a positive integer")
    for sid, row in sorted(unit_rows.items()):
        fraction = row.get("fraction")
        if fraction not in factions:
            continue
        if _positive_int(row.get("tier")) not in FACTION_TIERS:
            continue
        count = counts.get(sid, 0)
        if count != 1:
            problems.append(f"{sid} (fraction={fraction}, tier={row.get('tier')}): {count} reward rows, expected 1")
    return problems


def add_custom_faction_reward_units(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
    custom_faction_sids: Iterable[str],
    write_json,
) -> None:
    members: dict[str, bytes] = {}
    for name in release_zip.namelist():
        if name.startswith(UNIT_LOGICS_PREFIX) and name.endswith(".json"):
            members[name] = release_zip.read(name)
    for name, raw in output.items():
        if name.startswith(UNIT_LOGICS_PREFIX) and name.endswith(".json"):
            members[name] = raw
    unit_rows = load_unit_logic_rows(members)

    raw_container = output.get(REWARD_UNITS_MEMBER) or release_zip.read(REWARD_UNITS_MEMBER)
    container_doc = _loads_lenient(raw_container)
    doc, priced = build_reward_unit_rows(container_doc, unit_rows, custom_faction_sids)
    problems = missing_reward_unit_rows(doc, unit_rows, custom_faction_sids)
    if problems:
        raise RuntimeError("reward units container contract failed: " + "; ".join(problems[:20]))
    output[REWARD_UNITS_MEMBER] = write_json(doc)
    notes.append(f"price {len(priced)} custom-faction unit(s) into {REWARD_UNITS_MEMBER} for native unit-box rewards")
