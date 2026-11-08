"""Calibrate stock SpawnsCreator budgets to H3 map neutral strength.

Formula matches campaign GE emit (``h3_random_monster_strength_model.json``):

    requestedValue = round_half_up(count_or_nominal * squadValue, 50)

``squadValue`` comes from a baked Golden Era ``h3_`` unit snapshot so stock emit
does not require GE Core at runtime. Stock SpawnsCreator spends that budget on
native units; stock native tier medians are near the GE ``h3_`` scale.

Regenerate the snapshot with::

    python -m experiments.campaign_port_poc.vanilla_stock.stock_neutral_strength
"""

from __future__ import annotations

import json
import math
import re
import statistics
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

STRENGTH_MODEL_PATH = Path(__file__).with_name("h3_neutral_strength_model.json")
CAMPAIGN_STRENGTH_MODEL_PATH = Path(__file__).resolve().parents[1] / "h3_random_monster_strength_model.json"
SURFACE_EMIT_PATH = Path(__file__).resolve().parents[1] / "approach_cell" / "surface_emit.py"
DEFAULT_GE_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/"
    r"HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
DEFAULT_STOCK_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era/"
    r"HeroesOldenEra_Data/StreamingAssets/Core.zip"
)

_MODEL_CACHE: dict[str, Any] | None = None


class StockNeutralStrengthError(ValueError):
    """Fail-closed H3→stock army budget error."""


def load_strength_model(path: Path | None = None) -> dict[str, Any]:
    global _MODEL_CACHE
    model_path = path or STRENGTH_MODEL_PATH
    if path is None and _MODEL_CACHE is not None:
        return _MODEL_CACHE
    if not model_path.is_file():
        raise StockNeutralStrengthError(f"missing H3 neutral strength model: {model_path}")
    doc = json.loads(model_path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise StockNeutralStrengthError(f"strength model must be an object: {model_path}")
    if str(doc.get("schema") or "") != "vanilla_stock.h3_neutral_strength_model.v1":
        raise StockNeutralStrengthError(f"unsupported strength model schema in {model_path}")
    if path is None:
        _MODEL_CACHE = doc
    return doc


def rounded_requested_value(value: float, *, rounding: float) -> float:
    if rounding <= 0:
        raise StockNeutralStrengthError(f"requestedValueRounding must be > 0, got {rounding}")
    return float(math.floor((float(value) / rounding) + 0.5) * rounding)


def _nominal_counts(model: dict[str, Any]) -> dict[int, int]:
    raw = model.get("nominalH3RandomStackCountsByLevel")
    if not isinstance(raw, dict) or not raw:
        raise StockNeutralStrengthError("strength model missing nominalH3RandomStackCountsByLevel")
    out: dict[int, int] = {}
    for key, value in raw.items():
        level = int(key)
        count = int(value)
        if level < 1 or count < 1:
            raise StockNeutralStrengthError(f"invalid nominal count entry {key!r}: {value!r}")
        out[level] = count
    return out


def _tier_median_squad_values(model: dict[str, Any]) -> dict[int, float]:
    raw = model.get("tierMedianSquadValuesFromGeH3")
    if not isinstance(raw, dict) or not raw:
        raise StockNeutralStrengthError("strength model missing tierMedianSquadValuesFromGeH3")
    out: dict[int, float] = {}
    for key, value in raw.items():
        level = int(key)
        if not isinstance(value, (int, float)) or float(value) <= 0:
            raise StockNeutralStrengthError(f"invalid tier median squadValue for {key}: {value!r}")
        out[level] = float(value)
    return out


def _creature_squad_rows(model: dict[str, Any]) -> dict[int, dict[str, Any]]:
    raw = model.get("creatureTypeSquadValuesFromGe")
    if not isinstance(raw, dict) or not raw:
        raise StockNeutralStrengthError("strength model missing creatureTypeSquadValuesFromGe")
    out: dict[int, dict[str, Any]] = {}
    for key, row in raw.items():
        if not isinstance(row, dict):
            raise StockNeutralStrengthError(f"creature squad row must be object for {key}")
        ctype = int(key)
        squad_value = row.get("squadValue")
        tier = row.get("tier")
        if not isinstance(squad_value, (int, float)) or float(squad_value) <= 0:
            raise StockNeutralStrengthError(f"invalid creature squadValue for type {ctype}: {squad_value!r}")
        if not isinstance(tier, int) or tier < 1:
            raise StockNeutralStrengthError(f"invalid creature tier for type {ctype}: {tier!r}")
        out[ctype] = {
            "unitSid": str(row.get("unitSid") or ""),
            "squadValue": float(squad_value),
            "tier": int(tier),
        }
    return out


def h3_random_monster_level(entity: dict[str, Any]) -> int | None:
    """Return AVWmonN level, or None when animation is not a digit-level random template."""

    animation = str(entity.get("templateAnimation") or "")
    prefix = "AVWmon"
    suffix = ".def"
    if not animation.startswith(prefix) or not animation.endswith(suffix):
        return None
    raw = animation[len(prefix) : -len(suffix)]
    if not raw.isdigit():
        return None
    return int(raw)


def creature_type_for_monster_entity(entity: dict[str, Any]) -> int | None:
    """Concrete H3 monster object (id 54): subtype is CRTRAITS creature index."""

    object_id = entity.get("templateObjectId")
    subtype = entity.get("templateSubtype")
    if object_id == 54 and isinstance(subtype, int) and subtype >= 0:
        return subtype
    return None


def stock_random_squad_requested_value(
    entity: dict[str, Any],
    *,
    model: dict[str, Any] | None = None,
) -> float:
    """SpawnsCreator budget for an H3 monster tile → stock ``random-squad``."""

    strength = model or load_strength_model()
    rounding = float(strength["requestedValueRounding"])
    nominal = _nominal_counts(strength)
    tier_medians = _tier_median_squad_values(strength)
    creatures = _creature_squad_rows(strength)
    count = int(entity.get("count") or 0)
    source_key = entity.get("sourceKey") or entity.get("key")

    level = h3_random_monster_level(entity)
    if level is not None:
        if level not in nominal or level not in tier_medians:
            raise StockNeutralStrengthError(
                f"unsupported AVWmon level {level} for {source_key}"
            )
        squad_value = tier_medians[level]
        effective_count = count if count > 0 else nominal[level]
        return rounded_requested_value(squad_value * effective_count, rounding=rounding)

    creature_type = creature_type_for_monster_entity(entity)
    if creature_type is not None:
        row = creatures.get(creature_type)
        if row is None:
            raise StockNeutralStrengthError(
                f"no baked squadValue for concrete creatureType={creature_type} at {source_key}"
            )
        effective_count = count if count > 0 else nominal[int(row["tier"])]
        return rounded_requested_value(float(row["squadValue"]) * effective_count, rounding=rounding)

    if count > 0:
        # Typed animation without object-id 54 (rare stand-ins): budget by T1 median × count.
        # Prefer failing closed once the animation is recognized as a concrete DEF name.
        animation = str(entity.get("templateAnimation") or "")
        raise StockNeutralStrengthError(
            f"cannot calibrate concrete monster strength for {source_key}: "
            f"objectId={entity.get('templateObjectId')!r} subtype={entity.get('templateSubtype')!r} "
            f"animation={animation!r} count={count}"
        )

    # Last resort for untyped empties should not happen on real H3M monsters.
    raise StockNeutralStrengthError(
        f"cannot calibrate monster strength for {source_key}: "
        f"animation={entity.get('templateAnimation')!r} count={count}"
    )


def stock_guard_requested_value(
    stacks: list[dict[str, int]],
    *,
    model: dict[str, Any] | None = None,
) -> float:
    """SpawnsCreator budget for map-event guard stacks (sum of count×creature squadValue)."""

    strength = model or load_strength_model()
    rounding = float(strength["requestedValueRounding"])
    creatures = _creature_squad_rows(strength)
    total = 0.0
    for stack in stacks:
        creature_type = int(stack["creatureType"])
        count = int(stack["count"])
        if count <= 0:
            continue
        row = creatures.get(creature_type)
        if row is None:
            raise StockNeutralStrengthError(
                f"no baked squadValue for guard creatureType={creature_type} stacks={stacks!r}"
            )
        total += float(row["squadValue"]) * count
    if total <= 0:
        raise StockNeutralStrengthError(f"guard requestedValue must be positive; stacks={stacks!r}")
    return rounded_requested_value(total, rounding=rounding)


def _parse_creature_type_unit_map(surface_emit_text: str) -> dict[int, str]:
    match = re.search(
        r"MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE: dict\[int, str\] = \{([\s\S]*?)\n\}",
        surface_emit_text,
    )
    if match is None:
        raise StockNeutralStrengthError("MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE not found in surface_emit.py")
    mapping: dict[int, str] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        row = re.match(r'(\d+)\s*:\s*"([^"]+)"', stripped)
        if row is None:
            continue
        mapping[int(row.group(1))] = row.group(2)
    if not mapping:
        raise StockNeutralStrengthError("parsed empty MAP_EVENT_GUARD_UNIT_BY_CREATURE_TYPE")
    return mapping


def _unit_squad_index(core_zip: Path) -> dict[str, dict[str, float | int]]:
    index: dict[str, dict[str, float | int]] = {}
    with zipfile.ZipFile(core_zip) as core:
        for name in core.namelist():
            if not (name.startswith("DB/units/units_logics/") and name.endswith("_l.json")):
                continue
            doc = json.loads(core.read(name).decode("utf-8-sig"))
            for row in doc.get("array") or []:
                if not isinstance(row, dict):
                    continue
                unit_id = str(row.get("id") or "")
                squad_value = row.get("squadValue")
                tier = row.get("tier")
                if not unit_id or not isinstance(squad_value, (int, float)) or not isinstance(tier, int):
                    continue
                index[unit_id] = {"squadValue": float(squad_value), "tier": int(tier)}
    if not index:
        raise StockNeutralStrengthError(f"no unit squadValue rows in {core_zip}")
    return index


def regenerate_strength_model(
    *,
    ge_core: Path = DEFAULT_GE_CORE,
    stock_core: Path = DEFAULT_STOCK_CORE,
    out_path: Path = STRENGTH_MODEL_PATH,
    surface_emit_path: Path = SURFACE_EMIT_PATH,
    campaign_model_path: Path = CAMPAIGN_STRENGTH_MODEL_PATH,
) -> dict[str, Any]:
    """Rebuild ``h3_neutral_strength_model.json`` from GE Core + campaign nominal counts."""

    if not ge_core.is_file():
        raise StockNeutralStrengthError(f"GE Core.zip not found: {ge_core}")
    if not stock_core.is_file():
        raise StockNeutralStrengthError(f"stock Core.zip not found: {stock_core}")
    if not campaign_model_path.is_file():
        raise StockNeutralStrengthError(f"campaign strength model not found: {campaign_model_path}")
    if not surface_emit_path.is_file():
        raise StockNeutralStrengthError(f"surface_emit.py not found: {surface_emit_path}")

    campaign = json.loads(campaign_model_path.read_text(encoding="utf-8"))
    nominal_raw = campaign.get("nominalH3RandomStackCountsByLevel")
    if not isinstance(nominal_raw, dict):
        raise StockNeutralStrengthError("campaign model missing nominalH3RandomStackCountsByLevel")
    nominal = {int(key): int(value) for key, value in nominal_raw.items()}
    rounding = float(campaign.get("requestedValueRounding") or 50.0)

    ge_index = _unit_squad_index(ge_core)
    stock_index = _unit_squad_index(stock_core)
    creature_map = _parse_creature_type_unit_map(surface_emit_path.read_text(encoding="utf-8"))

    creature_rows: dict[str, dict[str, Any]] = {}
    for creature_type, unit_sid in sorted(creature_map.items()):
        info = ge_index.get(unit_sid)
        if info is None:
            raise StockNeutralStrengthError(
                f"GE Core missing squadValue for mapped unit {unit_sid} (creatureType={creature_type})"
            )
        creature_rows[str(creature_type)] = {
            "unitSid": unit_sid,
            "squadValue": float(info["squadValue"]),
            "tier": int(info["tier"]),
        }

    ge_by_tier: dict[int, list[float]] = defaultdict(list)
    for unit_id, info in ge_index.items():
        if unit_id.startswith("h3_") and int(info["tier"]) in nominal:
            ge_by_tier[int(info["tier"])].append(float(info["squadValue"]))
    stock_by_tier: dict[int, list[float]] = defaultdict(list)
    for unit_id, info in stock_index.items():
        if not unit_id.startswith("h3_") and int(info["tier"]) in nominal:
            stock_by_tier[int(info["tier"])].append(float(info["squadValue"]))

    missing_ge = sorted(set(nominal) - set(ge_by_tier))
    if missing_ge:
        raise StockNeutralStrengthError(f"GE Core missing h3_ tiers for medians: {missing_ge}")

    tier_med_ge = {str(tier): float(statistics.median(values)) for tier, values in sorted(ge_by_tier.items())}
    tier_med_stock = {
        str(tier): float(statistics.median(values)) for tier, values in sorted(stock_by_tier.items())
    }
    budgets = {
        str(tier): float(tier_med_ge[str(tier)]) * nominal[tier]
        for tier in sorted(nominal)
    }

    payload: dict[str, Any] = {
        "schema": "vanilla_stock.h3_neutral_strength_model.v1",
        "model": "h3_count_x_ge_h3_squadValue_v1",
        "sourceStatus": "generated_artifact_validated_against_ge_core_h3_unit_rows",
        "generatedDate": str(date.today()),
        "sourceNote": (
            "Matches campaign GE formula: requestedValue = round_half_up(count_or_nominal * squadValue, 50). "
            "squadValue comes from Golden Era Core.zip h3_ unit rows (ported H3 strength in Olden value space). "
            "Stock SpawnsCreator fills native units into that budget; stock native tier medians are near h3_ medians. "
            "Do not bake NeutralsDifficulty into requestedValue (isIgnoreMultiply / runtime multiply)."
        ),
        "geCoreZip": str(ge_core),
        "stockCoreZip": str(stock_core),
        "nominalH3RandomStackCountsByLevel": {str(key): value for key, value in sorted(nominal.items())},
        "requestedValueRounding": rounding,
        "tierMedianSquadValuesFromGeH3": tier_med_ge,
        "tierMedianSquadValuesFromStockNative": tier_med_stock,
        "randomTierNominalBudgets": budgets,
        "creatureTypeSquadValuesFromGe": creature_rows,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    global _MODEL_CACHE
    _MODEL_CACHE = None
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ge-core", type=Path, default=DEFAULT_GE_CORE)
    parser.add_argument("--stock-core", type=Path, default=DEFAULT_STOCK_CORE)
    parser.add_argument("--out", type=Path, default=STRENGTH_MODEL_PATH)
    args = parser.parse_args(argv)
    payload = regenerate_strength_model(ge_core=args.ge_core, stock_core=args.stock_core, out_path=args.out)
    print(
        json.dumps(
            {
                "out": str(args.out),
                "creatureTypes": len(payload["creatureTypeSquadValuesFromGe"]),
                "randomTierNominalBudgets": payload["randomTierNominalBudgets"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
