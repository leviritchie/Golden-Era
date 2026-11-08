"""Build the Tower Artificing Schematic catalog from a Core.zip.

A schematic is one displayed unit passive (a view `passives[].name` Lang key) that a Tower hero can
transcribe and graft. The catalog decides, per schematic:

- classification: `copyable`, `generic` (policy `genericRules`; never transcribed) or `excluded`;
- payload: the buff-shaped mechanics (`data` / `actions` / `statOverrides`) a graft buff carries.
  Unit passives and buff rows share those three shapes, so a graft is a native, dispellable battle buff.
  View passives are display labels and are not index-aligned with logic `passives` blocks (positional
  pairing put a curse immunity under "Alert I"), so payloads come only from policy `manualPayloads`.
  Each schematic lists the distinct non-class logic blocks of the units that show it as `candidates`,
  a review hint for whoever maps it. Unmapped schematics are `needs_mapping` and cannot be grafted.
- index: stable across regenerations. Hero saves store indices in ledger bits, so an index is never
  reused; a schematic that disappears from Core is kept as `retired`.

Outputs (all regenerable; the catalog JSON is the source for the overlay and the validator):
- custom_factions/tower_artificing/schematic_catalog.json
- docs/generated/homm3_tower_artificing_schematics.md (review table)
- OfflineUnlockMod/Homm3TowerArtificingCatalog.g.cs (runtime tables)

Runtime: reads one Core.zip once (~3 s, <200 MB RAM measured 2026-10-25). CPU only: zip/JSON I/O.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from description_tokens import TokenResolver, Unresolved  # noqa: E402
from observe_specs import check_override, derive  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO / "custom_factions" / "tower_artificing" / "artificing_policy.json"
CATALOG_PATH = REPO / "custom_factions" / "tower_artificing" / "schematic_catalog.json"
REVIEW_PATH = REPO / "docs" / "generated" / "homm3_tower_artificing_schematics.md"
CS_PATH = REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3TowerArtificingCatalog.g.cs"
TOWER_MANIFEST_PATH = REPO / "custom_factions" / "homm3_tower.json"
DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)

PAYLOAD_KEYS = ("data", "actions", "statOverrides")
# Curated keys beside the buff payload: extra Core rows, runtime hooks, per-unit variant rule, text override.
EXTRA_KEYS = ("helpers", "runtime", "perUnit", "descriptionText")
HELPER_KINDS = {"buff", "side_buff", "side_buff_info", "obstacle", "hero_buff"}
RUNTIME_KEYS = {
    "onHit", "berserkOnHit", "vampirism", "battleStart", "factions", "faction", "buff", "duration", "oncePerBattle",
    # Map grafts: a hero buff held while a carrier is in the army, daily gold per carrier, injected battle abilities.
    "heroBuff", "nativeUnitSet", "dailyGold", "abilities",
}
# The battle HUD shows alternative attacks + abilities in 5 fixed skill slots (BhUnitControlsView.SetSkills).
HUD_SKILL_SLOTS = 5
ON_HIT_TAGS = {"melee_attack", "shoot_attack", "range_attack"}
VAMPIRISM_TARGETS = {"self", "allies_no_self"}
# Live EHealType names (interop 2026-10-26); the runtime parses them by name and fails closed.
HEAL_TYPES = {"WithoutRespawn", "WithRespawn", "WithRealUntilStart", "WithTempStacks", "WithTempUntilStart", "UntilStartThenTemp"}
BATTLE_START_KINDS = {"enemy_faction_buffs", "ally_hive_count", "enemy_flyer_buff"}
PER_UNIT_RULES = {"godslayer_threshold", "duelist_melee", "phoenix_revive"}
GRAFT_PLACEHOLDER = "{graft}"
# Buff rows accept these `data` members (Core survey 2026-10-25: stats, disablers, immunities,
# sequenceEffect, alwaysMinDmg). `sideModifiers` exists only on unit passives.
BUFF_DATA_KEYS = {"stats", "disablers", "immunities", "sequenceEffect", "alwaysMinDmg"}
# Creature-class traits carried as hidden logic blocks (immunity families, bloodless disablers).
CLASS_IMMUNITY_TAG = re.compile(
    r"^(living|undead|construct|demon|embodiment|dragon|magic_creature|elemental|plant|beast)_immunities$"
)
CLASS_DISABLER_MECHS = {"vampirism", "destroy_corpse_and_heal"}


def strip_comments(text: str) -> str:
    return re.sub(r"(?m)^\s*//.*$", "", text)


def load_member(zf: zipfile.ZipFile, name: str) -> Any:
    return json.loads(strip_comments(zf.read(name).decode("utf-8-sig")))


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def is_class_block(block: dict[str, Any]) -> bool:
    """True when a logic passive block only carries creature-class traits."""
    if set(block) - {"data"}:
        return False
    data = block.get("data") or {}
    if set(data) - {"immunities", "disablers"}:
        return False
    for immunity in data.get("immunities") or []:
        tags = immunity.get("tags") or []
        if immunity.get("type") != "cast" or not tags or not all(CLASS_IMMUNITY_TAG.match(t) for t in tags):
            return False
    for disabler in data.get("disablers") or []:
        if disabler.get("mech") not in CLASS_DISABLER_MECHS:
            return False
    return True


def payload_unsupported_reason(payload: dict[str, Any]) -> str | None:
    extra = set(payload) - set(PAYLOAD_KEYS)
    if extra:
        return "payload keys not accepted by buff rows: " + ",".join(sorted(extra))
    bad_data = set(payload.get("data") or {}) - BUFF_DATA_KEYS
    if bad_data:
        return "data members not accepted by buff rows: " + ",".join(sorted(bad_data))
    return None


def expand_graft(value: Any, graft_sid: str) -> Any:
    if isinstance(value, str):
        return value.replace(GRAFT_PLACEHOLDER, graft_sid)
    if isinstance(value, list):
        return [expand_graft(v, graft_sid) for v in value]
    if isinstance(value, dict):
        return {k: expand_graft(v, graft_sid) for k, v in value.items()}
    return value


def check_runtime(key: str, runtime: dict[str, Any]) -> None:
    def fail(why: str) -> None:
        raise SystemExit(f"manualPayloads[{key}].runtime: {why}")

    extra = set(runtime) - RUNTIME_KEYS
    if extra:
        fail("unknown keys " + ",".join(sorted(extra)))
    for hit in runtime.get("onHit") or []:
        if not isinstance(hit.get("buff"), str) or not isinstance(hit.get("duration"), int):
            fail(f"onHit entry needs buff and integer duration: {hit}")
        if hit.get("attackTag") not in (None, *ON_HIT_TAGS):
            fail(f"onHit attackTag must be one of {sorted(ON_HIT_TAGS)}")
    if runtime.get("berserkOnHit") and not runtime.get("onHit"):
        fail("berserkOnHit needs an onHit entry (its attack filter)")
    vamp = runtime.get("vampirism")
    if vamp is not None:
        if not (0 < float(vamp.get("rate", 0)) <= 1) or vamp.get("target") not in VAMPIRISM_TARGETS or vamp.get("healType") not in HEAL_TYPES:
            fail(f"vampirism needs rate in (0,1], target in {sorted(VAMPIRISM_TARGETS)}, healType in {sorted(HEAL_TYPES)}")
    kind = runtime.get("battleStart")
    if kind is not None and kind not in BATTLE_START_KINDS:
        fail(f"battleStart must be one of {sorted(BATTLE_START_KINDS)}")
    if kind == "enemy_faction_buffs" and not runtime.get("factions"):
        fail("enemy_faction_buffs needs factions")
    if kind == "ally_hive_count" and not runtime.get("faction"):
        fail("ally_hive_count needs faction")
    if kind == "enemy_flyer_buff" and not (runtime.get("buff") and isinstance(runtime.get("duration"), int)):
        fail("enemy_flyer_buff needs buff and duration")
    if ("heroBuff" in runtime) != ("nativeUnitSet" in runtime):
        fail("heroBuff and nativeUnitSet go together (the native set marks the non-stacking source)")
    gold = runtime.get("dailyGold")
    if gold is not None and not (isinstance(gold.get("gold"), int) and gold["gold"] > 0 and isinstance(gold.get("sourceUnit"), str)):
        fail("dailyGold needs a positive integer gold and a sourceUnit (its weekly growth scales the rate)")
    abilities = runtime.get("abilities")
    if abilities is not None:
        indices = abilities.get("indices")
        if not isinstance(abilities.get("sourceUnit"), str) or not indices or not all(isinstance(i, int) and i >= 0 for i in indices):
            fail("abilities needs sourceUnit and non-empty non-negative indices")


def weekly_growth(zf: zipfile.ZipFile, names: list[str]) -> dict[str, int]:
    """Unit sid -> weekly growth: town dwelling weeklyIncrement, else the external hire site's (Peasant)."""
    growth: dict[str, int] = {}
    hires: dict[str, set[int]] = {}

    def walk(node: Any, sink: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("sids"), list) and isinstance(node.get("weeklyIncrement"), int):
                for sid in node["sids"]:
                    sink(sid, node["weeklyIncrement"])
            for value in node.values():
                walk(value, sink)
        elif isinstance(node, list):
            for value in node:
                walk(value, sink)

    for name in sorted(names):
        if name.startswith("DB/objects_logic/cities/") and name.endswith(".json"):
            walk(load_member(zf, name), growth.setdefault)
        elif name.startswith("DB/objects_logic/hires/") and name.endswith(".json"):
            walk(load_member(zf, name), lambda sid, inc: hires.setdefault(sid, set()).add(inc))
    for sid, incs in hires.items():
        if sid not in growth and len(incs) == 1:
            growth[sid] = next(iter(incs))
    return growth


def map_graft_fields(row: dict[str, Any], runtime: dict[str, Any], ctx: dict[str, Any]) -> None:
    """Resolve map-graft runtime against Core: native set units, per-line gold, embedded ability configs."""
    key = row["key"]
    if "heroBuff" in runtime:
        unit_set = ctx["unitSets"].get(runtime["nativeUnitSet"])
        if unit_set is None:
            raise SystemExit(f"{key}: unit set {runtime['nativeUnitSet']} not in Core")
        helper = next((h["row"] for h in row.get("helpers") or [] if h["kind"] == "hero_buff" and h["row"]["id"] == runtime["heroBuff"]), None)
        if helper is None:
            raise SystemExit(f"{key}: heroBuff {runtime['heroBuff']} needs a hero_buff helper row")
        if canonical(helper.get("bonuses")) != canonical(unit_set.get("bonuses")):
            raise SystemExit(f"{key}: hero buff bonuses differ from native {runtime['nativeUnitSet']}")
        row["nativeUnitSids"] = sorted(unit_set.get("units") or [])
    gold = runtime.get("dailyGold")
    if gold is not None:
        growth = ctx["growth"]
        src = growth.get(gold["sourceUnit"])
        if not src:
            raise SystemExit(f"{key}: no weekly growth for {gold['sourceUnit']}")
        rates = []
        for line in ctx["lines"]:
            line_growth = growth.get(line["baseSid"])
            if not line_growth:
                raise SystemExit(f"{key}: no weekly growth for Tower line {line['baseSid']}")
            rates.append(max(1, int(gold["gold"] * src / line_growth + 0.5)))
        row["dailyGoldByLine"] = rates
        if "graftDescription" in row:
            row["graftDescription"] = row["graftDescription"].replace(
                "{gold}", ", ".join(f"T{line['tier']} {rate}" for line, rate in zip(ctx["lines"], rates))
            )
    abilities = runtime.get("abilities")
    if abilities is not None:
        source = abilities["sourceUnit"]
        logic = (ctx["logics"].get(source) or {}).get("abilities") or []
        view = (ctx["views"].get(source) or {}).get("abilities") or []
        if len(abilities["indices"]) > HUD_SKILL_SLOTS:
            raise SystemExit(f"{key}: more injected abilities than HUD skill slots")
        injected = []
        for i in abilities["indices"]:
            if i >= len(logic) or i >= len(view):
                raise SystemExit(f"{key}: {source} has no ability {i} in both logic and view")
            injected.append({"sourceUnit": source, "sourceIndex": i, "logic": logic[i], "view": view[i]})
        row["injectedAbilities"] = injected


def per_unit_variants(rule: str, row: dict[str, Any], logics: dict[str, dict[str, Any]], obstacles: dict[str, dict[str, Any]], lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(variants, helpers) for one perUnit rule; a Tower unit with no variant uses the base graft row."""
    graft = row["graftBuffSid"]
    source = next((logics[u["sid"]] for u in row["sourceUnits"] if u["sid"] in logics), None)
    if source is None:
        raise SystemExit(f"{row['key']}: perUnit {rule} has no source logic")
    variants: list[dict[str, Any]] = []
    helpers: list[dict[str, Any]] = []
    for line in lines:
        for unit_sid in line["unitSids"]:
            logic = logics.get(unit_sid)
            if logic is None:
                continue
            tier = int(logic.get("tier") or line["tier"])
            payload: dict[str, Any] | None = None
            if rule == "godslayer_threshold":
                bonus = (source.get("stats") or {}).get("outDamageIfLevelAbove")
                if not bonus:
                    raise SystemExit(f"{row['key']}: source has no outDamageIfLevelAbove")
                if tier < 7:
                    payload = {"data": {"stats": {"outLevelAboveThreshold": tier + 1, "outDamageIfLevelAbove": bonus}}}
            elif rule == "duelist_melee":
                mults = [
                    float((a.get("damageDealer") or {}).get("statDmgMult", 1.0))
                    for a in logic.get("alternativeAttacks") or []
                    if a.get("attackType_") == "melee"
                ]
                mult = min(mults) if mults else 1.0
                if 0 < mult < 1:
                    payload = {"data": {"stats": {"outDmgMods": {"list": [{"t": "melee_attack", "v": round(1 / mult - 1, 4)}]}}}}
            elif rule == "phoenix_revive":
                death = None
                for block in source.get("passives") or []:
                    for action in block.get("actions") or []:
                        mechs = (action.get("damageDealer") or {}).get("targetMechanics") or []
                        if action.get("trigger") == "unit_died" and any(m.get("mech") == "spawn_object" for m in mechs):
                            death = action
                if death is None:
                    raise SystemExit(f"{row['key']}: source has no spawn_object death action")
                mech = next(m for m in death["damageDealer"]["targetMechanics"] if m.get("mech") == "spawn_object")
                donor = obstacles.get(mech["values"][1])
                if donor is None or (donor.get("onTimeoutMechanic") or {}).get("mech") != "spawn_revived_phoenix":
                    raise SystemExit(f"{row['key']}: obstacle {mech['values'][1]} is not a spawn_revived_phoenix ash pile")
                heart = f"{graft}_heart_{unit_sid}"
                obstacle = json.loads(json.dumps(donor))
                obstacle["id"] = heart
                values = list(obstacle["onTimeoutMechanic"]["values"])
                values[1] = unit_sid
                obstacle["onTimeoutMechanic"]["values"] = values
                helpers.append({"kind": "obstacle", "row": obstacle})
                action = json.loads(json.dumps(death))
                for m in action["damageDealer"]["targetMechanics"]:
                    if m.get("mech") == "spawn_object":
                        m["values"] = [m["values"][0], heart, *m["values"][2:]]
                payload = {"actions": list((row["payload"].get("actions") or [])) + [action]}
            if payload is not None:
                variants.append({"unitSid": unit_sid, "buffSid": f"{graft}_{unit_sid}", "payload": payload})
    return variants, helpers


def check_references(rows: list[dict[str, Any]], core_buffs: dict[str, Any]) -> None:
    """Every buff a graft names (runtime, buff actions, global_buff, side_buff) exists in Core or as a helper row."""
    helper_ids = {h["row"]["id"]: h["kind"] for r in rows for h in r.get("helpers") or []}

    def need(key: str, sid: str, kind: str) -> None:
        if helper_ids.get(sid) == kind or (kind == "buff" and sid in core_buffs):
            return
        raise SystemExit(f"{key}: references {kind} {sid}, which is neither in Core nor a helper row")

    for r in rows:
        if not r.get("graftable"):
            continue
        runtime = r.get("runtime") or {}
        for hit in runtime.get("onHit") or []:
            need(r["key"], hit["buff"], "buff")
        if runtime.get("battleStart") == "enemy_flyer_buff":
            need(r["key"], runtime["buff"], "buff")
        if runtime.get("heroBuff"):
            need(r["key"], runtime["heroBuff"], "hero_buff")
        payloads = [r["payload"]] + [v["payload"] for v in r.get("variants") or []]
        for payload in payloads:
            for action in payload.get("actions") or []:
                dealer = action.get("damageDealer") or {}
                if isinstance(dealer.get("buff"), dict):
                    need(r["key"], dealer["buff"]["sid"], "buff")
                for mech in dealer.get("targetMechanics") or []:
                    if mech.get("mech") == "global_buff":
                        for i in range(1, len(mech["values"]), 6):
                            need(r["key"], mech["values"][i], "buff")
                    elif mech.get("mech") == "side_buff" and mech["values"][0].startswith(r["graftBuffSid"]):
                        need(r["key"], mech["values"][0], "side_buff_info")
        for helper in r.get("helpers") or []:
            if helper["kind"] == "side_buff_info":
                need(r["key"], helper["row"]["sid"], "side_buff")


def generic_reason(key: str, display_name: str, rules: list[dict[str, str]]) -> str | None:
    for rule in rules:
        subject = display_name if rule.get("field") == "name" else key
        if re.search(rule["pattern"], subject):
            return rule["reason"]
    return None


def lang_texts(zf: zipfile.ZipFile) -> dict[str, str]:
    texts: dict[str, str] = {}
    for member in ("Lang/english/texts/unitsAbility.json", "Lang/english/texts/units.json"):
        if member not in zf.namelist():
            continue
        doc = load_member(zf, member)
        rows = doc if isinstance(doc, list) else doc.get("tokens") or doc.get("array") or []
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("sid"), str):
                texts.setdefault(row["sid"], str(row.get("text") or ""))
    return texts


def tower_lines() -> list[dict[str, Any]]:
    manifest = json.loads(TOWER_MANIFEST_PATH.read_text(encoding="utf-8"))
    suffixes = manifest.get("unitVariants") or ["", "_upg", "_upg_alt"]
    lines = []
    for line in sorted(manifest["unitLines"], key=lambda row: row["tier"]):
        base = line["baseSid"]
        variants = line.get("variantSids") or [base + s for s in suffixes]
        lines.append({"index": line["tier"] - 1, "baseSid": base, "tier": line["tier"], "unitSids": variants})
    return lines


def observe_rows(rows: list[dict[str, Any]], policy: dict[str, Any], logics: dict[str, dict[str, Any]]) -> None:
    """Observation specs per graftable row (observe_specs.py): policy observeOverrides, else derived. Every
    graftable row must be observable, or it could never enter the schematic book."""
    obs = policy.get("observation") or {}
    chances = obs.get("chanceByRank")
    if not (isinstance(chances, list) and len(chances) == len(policy["graftSlotsByRank"]) and all(isinstance(c, int) and 0 < c <= 100 for c in chances)):
        raise SystemExit("observation.chanceByRank needs one percent (1..100) per rank")
    if not isinstance(obs.get("diagnostics"), bool) or not (isinstance(obs.get("diagnosticLogLines"), int) and obs["diagnosticLogLines"] > 0):
        raise SystemExit("observation needs diagnostics (bool) and a positive diagnosticLogLines")
    overrides = policy.get("observeOverrides") or {}
    by_key = {r["key"]: r for r in rows}
    unknown = sorted(k for k in overrides if not (by_key.get(k) or {}).get("graftable"))
    if unknown:
        raise SystemExit("observeOverrides keys that are not graftable rows: " + ", ".join(unknown))
    missing = []
    for row in rows:
        row.pop("observe", None)
        row.pop("observeSource", None)
        if not row.get("graftable"):
            continue
        if row["key"] in overrides:
            check_override(row["key"], overrides[row["key"]], logics, {u["sid"] for u in row["sourceUnits"]})
            row["observe"], row["observeSource"] = overrides[row["key"]], "override"
            continue
        specs, need = derive(row, logics, canonical)
        if need:
            missing.append(f"{row['key']} ({need})")
            continue
        row["observe"], row["observeSource"] = specs, "derived"
    if missing:
        raise SystemExit("graftable rows need observeOverrides: " + "; ".join(missing))


def round_to(value: float, step: int) -> int:
    return int(step * round(value / step))


def cost_matrix(policy: dict[str, Any]) -> list[list[int]]:
    cost = policy["graftCost"]
    weights = cost["tierWeight"]
    return [[round_to(cost["base"] * ws * wt, cost["roundTo"]) for wt in weights] for ws in weights]


def build(core_path: Path) -> dict[str, Any]:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    rules = policy["genericRules"]
    manual = policy.get("manualPayloads") or {}
    excluded = policy.get("excludedKeys") or {}
    core_sha = hashlib.sha256(core_path.read_bytes()).hexdigest()
    zf = zipfile.ZipFile(core_path)
    names = zf.namelist()
    texts = lang_texts(zf)

    logics: dict[str, dict[str, Any]] = {}
    views: dict[str, dict[str, Any]] = {}
    for name in names:
        if not name.endswith(".json"):
            continue
        if name.startswith("DB/units/units_logics/"):
            for row in load_member(zf, name).get("array", []):
                logics[row["id"]] = row
        elif name.startswith("DB/units/units_views/"):
            for row in load_member(zf, name).get("array", []):
                views[row["id"]] = row
    tokens = TokenResolver(zf, logics, texts)
    lines = tower_lines()
    unit_sets = {r["id"]: r for r in load_member(zf, "DB/unit_sets/unit_sets.json").get("array", [])}
    map_ctx = {"unitSets": unit_sets, "growth": weekly_growth(zf, names), "lines": lines, "logics": logics, "views": views}

    schematics: dict[str, dict[str, Any]] = {}
    candidates: dict[str, dict[str, Any]] = {}
    unit_keys: dict[str, list[str]] = {}
    unit_tiers: dict[str, int] = {}
    for unit_sid in sorted(logics):
        logic = logics[unit_sid]
        tier = int(logic.get("tier") or 0)
        if tier < 1 or tier > 7:
            continue
        unit_tiers[unit_sid] = tier
        view_passives = (views.get(unit_sid) or {}).get("passives") or []
        keys = []
        for passive in view_passives:
            name_sid = passive.get("name") if isinstance(passive, dict) else None
            if not isinstance(name_sid, str) or not name_sid.endswith("_name"):
                continue
            key = name_sid[: -len("_name")]
            if key in keys:
                continue
            keys.append(key)
            entry = schematics.setdefault(
                key,
                {
                    "key": key,
                    "nameSid": name_sid,
                    "descriptionSid": (passive.get("description") if isinstance(passive.get("description"), str) else key + "_description"),
                    "sourceUnits": [],
                },
            )
            entry["sourceUnits"].append({"sid": unit_sid, "tier": tier, "faction": logic.get("fraction") or ""})
        unit_keys[unit_sid] = keys

        blocks = [b for b in (logic.get("passives") or []) if isinstance(b, dict) and not is_class_block(b)]
        for key in keys:
            for block in blocks:
                candidates.setdefault(key, {})[canonical(block)] = block

    previous: dict[str, Any] = {}
    if CATALOG_PATH.exists():
        previous = {row["key"]: row for row in json.loads(CATALOG_PATH.read_text(encoding="utf-8")).get("schematics", [])}
    next_index = max([row["index"] for row in previous.values()] + [-1]) + 1
    max_index = (1 << policy["ledger"]["graftIndexBits"]) - 2  # graft slot stores index + 1; all-ones reserved

    rows: list[dict[str, Any]] = []
    for key in sorted(set(schematics) | set(previous)):
        old = previous.get(key)
        if old is not None:
            index = old["index"]
        else:
            index = next_index
            next_index += 1
        if index > max_index:
            raise SystemExit(f"schematic index {index} exceeds ledger capacity {max_index}; raise ledger.graftIndexBits")
        entry = schematics.get(key)
        if entry is None:
            rows.append({**old, "classification": "retired", "graftable": False})
            continue
        display_name = texts.get(entry["nameSid"], "")
        reason = generic_reason(key, display_name, rules)
        row: dict[str, Any] = {
            "index": index,
            "key": key,
            "nameSid": entry["nameSid"],
            "descriptionSid": entry["descriptionSid"],
            "displayName": display_name,
            "description": texts.get(entry["descriptionSid"], ""),
            "sourceUnits": sorted(entry["sourceUnits"], key=lambda u: (u["tier"], u["sid"])),
            "minSourceTier": min(u["tier"] for u in entry["sourceUnits"]),
            "classification": "generic" if reason else ("excluded" if key in excluded else "copyable"),
            "genericReason": reason,
            "excludedReason": excluded.get(key),
            "graftBuffSid": policy["graftBuff"]["sidPrefix"] + str(index),
        }
        if key in manual:
            curated = expand_graft(manual[key], row["graftBuffSid"])
            payload = {k: v for k, v in curated.items() if k in PAYLOAD_KEYS}
            why = payload_unsupported_reason(payload) or (
                None if payload or curated.get("runtime") or curated.get("helpers") else "manual payload is empty"
            )
            if why:
                raise SystemExit(f"manualPayloads[{key}] cannot be a buff row: {why}")
            row["payload"] = {"status": "manual", **payload}
            for helper in curated.get("helpers") or []:
                if helper.get("kind") not in HELPER_KINDS or not isinstance((helper.get("row") or {}).get("id"), str):
                    raise SystemExit(f"manualPayloads[{key}].helpers: each needs kind in {sorted(HELPER_KINDS)} and row.id")
                if not helper["row"]["id"].startswith(row["graftBuffSid"] + "_"):
                    raise SystemExit(f"manualPayloads[{key}].helpers: id {helper['row']['id']} must start with '{{graft}}_'")
            if curated.get("helpers"):
                row["helpers"] = curated["helpers"]
            if curated.get("runtime"):
                check_runtime(key, curated["runtime"])
                row["runtime"] = curated["runtime"]
            rule = curated.get("perUnit")
            if rule is not None:
                if rule not in PER_UNIT_RULES:
                    raise SystemExit(f"manualPayloads[{key}].perUnit must be one of {sorted(PER_UNIT_RULES)}")
                variants, variant_helpers = per_unit_variants(rule, {**row, "sourceUnits": entry["sourceUnits"]}, logics, tokens.db["obstacle"], lines)
                row["perUnit"] = rule
                row["variants"] = variants
                if variant_helpers:
                    row["helpers"] = (row.get("helpers") or []) + variant_helpers
            if "descriptionText" in curated:
                row["graftDescription"] = curated["descriptionText"]
            elif row["classification"] == "copyable":
                source_sids = [u["sid"] for u in sorted(entry["sourceUnits"], key=lambda u: (u["tier"], u["sid"]))]
                try:
                    row["graftDescription"] = tokens.resolve(entry["descriptionSid"], row["description"], source_sids)
                except Unresolved as exc:
                    raise SystemExit(f"manualPayloads[{key}]: description tokens unresolved ({exc}); give descriptionText") from None
            if row.get("runtime"):
                map_graft_fields(row, row["runtime"], map_ctx)
        else:
            row["payload"] = {"status": "needs_mapping"}
        if row["classification"] == "copyable" and row["payload"]["status"] == "needs_mapping":
            row["candidates"] = list((candidates.get(key) or {}).values())
        row["graftable"] = row["classification"] == "copyable" and row["payload"]["status"] == "manual"
        rows.append(row)
    unknown_manual = sorted(set(manual) - set(schematics))
    if unknown_manual:
        raise SystemExit("manualPayloads keys not shown by any unit: " + ", ".join(unknown_manual))
    unknown_excluded = sorted(set(excluded) - set(schematics))
    if unknown_excluded:
        raise SystemExit("excludedKeys not shown by any unit: " + ", ".join(unknown_excluded))
    rows.sort(key=lambda r: r["index"])
    check_references(rows, tokens.db["buff"])
    observe_rows(rows, policy, logics)

    index_by_key = {r["key"]: r["index"] for r in rows}
    graftable = {r["key"] for r in rows if r["graftable"]}
    units = {
        sid: [index_by_key[k] for k in keys if k in graftable]
        for sid, keys in sorted(unit_keys.items())
    }
    units = {sid: idx for sid, idx in units.items() if idx}
    stats = {
        "schematics": len(rows),
        "copyable": sum(r["classification"] == "copyable" for r in rows),
        "generic": sum(r["classification"] == "generic" for r in rows),
        "excluded": sum(r["classification"] == "excluded" for r in rows),
        "graftable": len(graftable),
        "needsMapping": sum(r["classification"] == "copyable" and r["payload"]["status"] == "needs_mapping" for r in rows),
        "retired": sum(r["classification"] == "retired" for r in rows),
        "unitsWithGraftable": len(units),
    }
    return {
        "schemaVersion": 1,
        "generator": "tools/tower_artificing/build_schematic_catalog.py",
        "policy": "custom_factions/tower_artificing/artificing_policy.json",
        "sourceCore": {"path": str(core_path).replace("\\", "/"), "sha256": core_sha},
        "stats": stats,
        "costMatrix": cost_matrix(policy),
        "towerLines": lines,
        "unitTiers": unit_tiers,
        "unitSchematics": units,
        # Battle-start grafts (Soul Assimilator, Hivemind, Frostbound Skies) read these instead of live configs.
        "unitFactions": {sid: logics[sid]["fraction"] for sid in sorted(logics) if logics[sid].get("fraction")},
        "flyerUnitSids": sorted(sid for sid, logic in logics.items() if (logic.get("stats") or {}).get("moveType") == "fly"),
        "schematics": rows,
    }


def render_review(catalog: dict[str, Any]) -> str:
    out = [
        "# Tower Artificing schematics (generated)",
        "",
        f"Generated by `{catalog['generator']}` from Core sha256 `{catalog['sourceCore']['sha256'][:16]}`. Do not hand-edit;",
        "change `custom_factions/tower_artificing/artificing_policy.json` and regenerate. Design: `docs/homm3_tower_artificing.md`.",
        "",
        "Stats: " + ", ".join(f"{k}={v}" for k, v in catalog["stats"].items()),
        "",
        "## Graft cost (Arcane Essence; rows = source tier, columns = target tier)",
        "",
        "| src\\dst | " + " | ".join(f"T{t}" for t in range(1, 8)) + " |",
        "|---|" + "---|" * 7,
    ]
    for tier, row in enumerate(catalog["costMatrix"], start=1):
        out.append(f"| T{tier} | " + " | ".join(str(v) for v in row) + " |")
    out += ["", "## Schematics", "", "| # | key | name | class | payload | observe | min tier | units |", "|---|---|---|---|---|---|---|---|"]
    for row in catalog["schematics"]:
        units = ", ".join(u["sid"] for u in row.get("sourceUnits", [])[:6])
        more = len(row.get("sourceUnits", [])) - 6
        if more > 0:
            units += f" +{more}"
        cls = row["classification"] + (f" ({row['genericReason']})" if row.get("genericReason") else "")
        status = row["payload"]["status"]
        extras = [name for name in ("helpers", "runtime", "variants") if row.get(name)]
        if extras:
            status += " +" + "+".join(extras)
        observe = ", ".join(spec["kind"] for spec in row.get("observe") or [])
        if row.get("observeSource") == "override":
            observe += " (override)"
        out.append(
            f"| {row['index']} | `{row['key']}` | {row.get('displayName', '')} | {cls} | {status} | {observe} | {row.get('minSourceTier', '')} | {units} |"
        )
    return "\n".join(out) + "\n"


def cs_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_cs(catalog: dict[str, Any], policy: dict[str, Any]) -> str:
    ledger = policy["ledger"]
    lines = [
        "// <auto-generated>",
        "// Generated by tools/tower_artificing/build_schematic_catalog.py from custom_factions/tower_artificing/.",
        "// Do not hand-edit; regenerate. validate_homm3_tower_artificing_contract.py checks this file matches the catalog.",
        "// </auto-generated>",
        "using System.Collections.Generic;",
        "",
        "namespace OfflineUnlockMod;",
        "",
        "internal static class Homm3TowerArtificingCatalog",
        "{",
        f"\tinternal const string CatalogCoreSha256 = {cs_string(catalog['sourceCore']['sha256'])};",
        "\t/// <summary>policy.enabled: false keeps the runtime inert (no essence, no grafts, no Transcribe capture).</summary>",
        f"\tinternal const bool Enabled = {'true' if policy.get('enabled') else 'false'};",
        f"\tinternal const string FactionSkillSid = {cs_string(policy['factionSkillSid'])};",
        f"\tinternal const string TranscribeAbilitySid = {cs_string(policy['transcribe']['abilitySid'])};",
        f"\tinternal const string TranscribeEffectBuffSid = {cs_string(policy['transcribe']['effectBuffSid'])};",
        f"\tinternal const string GraftBuffPrefix = {cs_string(policy['graftBuff']['sidPrefix'])};",
        f"\tinternal const string EssenceBitPrefix = {cs_string(ledger['essenceBitPrefix'])};",
        f"\tinternal const string SchematicBitPrefix = {cs_string(ledger['schematicBitPrefix'])};",
        f"\tinternal const string GraftBitPrefix = {cs_string(ledger['graftBitPrefix'])};",
        f"\tinternal const int EssenceBits = {policy['essence']['bits']};",
        f"\tinternal const int SchematicTierBits = {ledger['schematicTierBits']};",
        f"\tinternal const int GraftIndexBits = {ledger['graftIndexBits']};",
        f"\tinternal const int Lines = {ledger['lines']};",
        f"\tinternal const int MaxSlots = {ledger['maxSlots']};",
        f"\tinternal const int SchematicCount = {max([r['index'] for r in catalog['schematics']] + [-1]) + 1};",
        "\t/// <summary>policy.observation.diagnostics: log the passive attribution scope even while Enabled is false.</summary>",
        f"\tinternal const bool ObservationDiagnostics = {'true' if policy['observation']['diagnostics'] else 'false'};",
        f"\tinternal const int ObservationDiagnosticLogLines = {policy['observation']['diagnosticLogLines']};",
        "",
        "\t/// <summary>Percent chance an observed passive enters the book, at Basic/Advanced/Expert (one roll per passive per battle).</summary>",
        "\tinternal static readonly int[] ObservationChanceByRank = { " + ", ".join(str(v) for v in policy["observation"]["chanceByRank"]) + " };",
        "\t/// <summary>Graft slots per Tower line at Basic/Advanced/Expert.</summary>",
        "\tinternal static readonly int[] GraftSlotsByRank = { " + ", ".join(str(v) for v in policy["graftSlotsByRank"]) + " };",
        "\t/// <summary>Arcane Essence per defeated enemy creature, by creature tier 1..7.</summary>",
        "\tinternal static readonly int[] EssencePerCreatureByTier = { " + ", ".join(str(v) for v in policy["essence"]["perDefeatedCreatureByTier"]) + " };",
        "\t/// <summary>Graft cost [sourceTier - 1, targetTier - 1].</summary>",
        "\tinternal static readonly int[,] GraftCost =",
        "\t{",
    ]
    for row in catalog["costMatrix"]:
        lines.append("\t\t{ " + ", ".join(str(v) for v in row) + " },")
    lines += ["\t};", "", "\t/// <summary>Tower unit sid -> line index (0..6, = tier - 1).</summary>", "\tinternal static readonly Dictionary<string, int> TowerLineByUnitSid = new()", "\t{"]
    for line in catalog["towerLines"]:
        for sid in line["unitSids"]:
            lines.append(f"\t\t[{cs_string(sid)}] = {line['index']},")
    lines += ["\t};", "", "\t/// <summary>Every tiered unit sid -> tier (source tier for transcription).</summary>", "\tinternal static readonly Dictionary<string, int> UnitTierBySid = new()", "\t{"]
    for sid, tier in catalog["unitTiers"].items():
        lines.append(f"\t\t[{cs_string(sid)}] = {tier},")
    lines += ["\t};", "", "\t/// <summary>Unit sid -> graftable schematic indices that unit shows.</summary>", "\tinternal static readonly Dictionary<string, int[]> GraftableSchematicsByUnitSid = new()", "\t{"]
    for sid, indices in catalog["unitSchematics"].items():
        lines.append(f"\t\t[{cs_string(sid)}] = new[] {{ " + ", ".join(str(i) for i in indices) + " },")
    lines += ["\t};", "", "\t/// <summary>Schematic index -> view passive key (diagnostics only).</summary>", "\tinternal static readonly Dictionary<int, string> SchematicKeyByIndex = new()", "\t{"]
    graftable = [row for row in catalog["schematics"] if row.get("graftable")]
    for row in graftable:
        lines.append(f"\t\t[{row['index']}] = {cs_string(row['key'])},")

    def runtime_rows(name: str) -> list[tuple[dict[str, Any], Any]]:
        return [(row, row["runtime"][name]) for row in graftable if (row.get("runtime") or {}).get(name)]

    lines += [
        "\t};",
        "",
        "\t/// <summary>\"{index}|{unitSid}\" -> per-unit variant graft buff sid (perUnit rules); other carriers use the base graft.</summary>",
        "\tinternal static readonly Dictionary<string, string> GraftVariantBuffSid = new()",
        "\t{",
    ]
    for row in graftable:
        for variant in row.get("variants") or []:
            lines.append(f"\t\t[{cs_string(str(row['index']) + '|' + variant['unitSid'])}] = {cs_string(variant['buffSid'])},")
    lines += [
        "\t};",
        "",
        "\t/// <summary>Grafts applied only at battle start: units initialized later (revived or summoned stacks) skip them.</summary>",
        "\tinternal static readonly HashSet<int> OncePerBattleSchematics = new() { "
        + ", ".join(str(row["index"]) for row, _ in runtime_rows("oncePerBattle"))
        + " };",
        "",
        "\t/// <summary>Schematic -> buffs the carrier's damaging basic attacks and counters add to the enemy target. AttackTag null = any.</summary>",
        "\tinternal static readonly Dictionary<int, OnHitGraft[]> OnHitBySchematic = new()",
        "\t{",
    ]
    for row, hits in runtime_rows("onHit"):
        entries = ", ".join(
            f"new OnHitGraft({cs_string(h['buff'])}, {h['duration']}, {cs_string(h['attackTag']) if h.get('attackTag') else 'null'})" for h in hits
        )
        lines.append(f"\t\t[{row['index']}] = new[] {{ {entries} }},")
    lines += [
        "\t};",
        "",
        "\t/// <summary>Schematics whose on-hit also runs native MechBerserk.ApplyBerserk on the target.</summary>",
        "\tinternal static readonly HashSet<int> BerserkOnHitSchematics = new() { "
        + ", ".join(str(row["index"]) for row, _ in runtime_rows("berserkOnHit"))
        + " };",
        "",
        "\t/// <summary>Schematic -> heal from basic-attack damage dealt (Target: self | allies_no_self; HealType: live EHealType name).</summary>",
        "\tinternal static readonly Dictionary<int, VampirismGraft> VampirismBySchematic = new()",
        "\t{",
    ]
    for row, vamp in runtime_rows("vampirism"):
        lines.append(
            f"\t\t[{row['index']}] = new VampirismGraft({float(vamp['rate'])!r}f, {cs_string(vamp['target'])}, {cs_string(vamp['healType'])}),"
        )
    lines += [
        "\t};",
        "",
        "\t/// <summary>Schematic -> first-round synergy. Keys/BuffSids are parallel: enemy_faction_buffs (faction -> buff),",
        "\t/// ally_hive_count (count n -> BuffSids[n - 1]), enemy_flyer_buff (one buff on every enemy flyer).</summary>",
        "\tinternal static readonly Dictionary<int, BattleStartGraft> BattleStartBySchematic = new()",
        "\t{",
    ]
    for row, kind in runtime_rows("battleStart"):
        runtime = row["runtime"]
        helpers = [h["row"]["id"] for h in row.get("helpers") or [] if h["kind"] == "buff"]
        if kind == "enemy_faction_buffs":
            keys = runtime["factions"]
            sids = [f"{row['graftBuffSid']}_faction_{f}" for f in keys]
            duration = -1
        elif kind == "ally_hive_count":
            keys = [runtime["faction"]]
            sids = sorted((h for h in helpers if "_hive_" in h), key=lambda s: int(s.rsplit("_", 1)[1]))
            duration = -1
        else:
            keys = []
            sids = [runtime["buff"]]
            duration = runtime["duration"]
        missing = [s for s in sids if kind != "enemy_flyer_buff" and s not in helpers]
        if missing:
            raise SystemExit(f"{row['key']}: battleStart helper buffs missing: {missing}")
        key_list = "new[] { " + ", ".join(cs_string(k) for k in keys) + " }" if keys else "System.Array.Empty<string>()"
        sid_list = "new[] { " + ", ".join(cs_string(s) for s in sids) + " }"
        lines.append(f"\t\t[{row['index']}] = new BattleStartGraft({cs_string(kind)}, {key_list}, {sid_list}, {duration}),")
    lines += [
        "\t};",
        "",
        "\t/// <summary>Schematic -> hero buff held while a carrier stack is in the hero's army; skipped while a native",
        "\t/// unit of the source unit set (NativeUnitSids) is in the army, so the effect never stacks.</summary>",
        "\tinternal static readonly Dictionary<int, MapHeroBuffGraft> MapHeroBuffBySchematic = new()",
        "\t{",
    ]
    for row, buff in runtime_rows("heroBuff"):
        natives = "new[] { " + ", ".join(cs_string(s) for s in row["nativeUnitSids"]) + " }"
        lines.append(f"\t\t[{row['index']}] = new MapHeroBuffGraft({cs_string(buff)}, {natives}),")
    lines += [
        "\t};",
        "",
        "\t/// <summary>Schematic -> daily gold per carrier creature by Tower line (tier-scaled by weekly growth).</summary>",
        "\tinternal static readonly Dictionary<int, int[]> DailyGoldBySchematic = new()",
        "\t{",
    ]
    for row, _ in runtime_rows("dailyGold"):
        lines.append(f"\t\t[{row['index']}] = new[] {{ " + ", ".join(str(v) for v in row["dailyGoldByLine"]) + " },")
    lines += [
        "\t};",
        "",
        "\t/// <summary>Schematic -> source unit abilities appended to the carrier at Unit.Init (JsonUtility configs).</summary>",
        "\tinternal static readonly Dictionary<int, InjectedAbilityGraft[]> InjectedAbilitiesBySchematic = new()",
        "\t{",
    ]
    for row, _ in runtime_rows("abilities"):
        entries = ", ".join(
            f"new InjectedAbilityGraft({cs_string(a['sourceUnit'])}, {a['sourceIndex']}, "
            f"{cs_string(json.dumps(a['logic'], separators=(',', ':')))}, {cs_string(json.dumps(a['view'], separators=(',', ':')))})"
            for a in row["injectedAbilities"]
        )
        lines.append(f"\t\t[{row['index']}] = new[] {{ {entries} }},")
    lines += [
        "\t};",
        "",
        "\t/// <summary>Schematic -> observe spec kinds (tools/tower_artificing/observe_specs.py).</summary>",
        "\tinternal static readonly Dictionary<int, string[]> ObserveKindsBySchematic = new()",
        "\t{",
    ]
    for row in graftable:
        lines.append(f"\t\t[{row['index']}] = new[] {{ " + ", ".join(cs_string(spec["kind"]) for spec in row["observe"]) + " },")
    passive_actions: dict[str, list[str]] = {}
    tagged: dict[str, dict[str, set[int]]] = {"buff_applied": {}, "aura": {}, "side_modifier": {}}
    for row in graftable:
        for spec in row["observe"]:
            for link in spec.get("links") or []:
                passive_actions.setdefault(link["unit"], []).append(
                    f"new ObservedPassiveAction({link['passive']}, {link['action']}, {row['index']}, {cs_string(link['trigger'] or '')})"
                )
            if spec["kind"] in tagged:
                for tag in spec.get("buffs") or spec.get("tags") or []:
                    tagged[spec["kind"]].setdefault(tag, set()).add(row["index"])
    lines += [
        "\t};",
        "",
        "\t/// <summary>Native unit sid -> its passives[Passive].actions[Action] whose firing observes a schematic (passive_action).</summary>",
        "\tinternal static readonly Dictionary<string, ObservedPassiveAction[]> ObservedPassiveActionsByUnitSid = new()",
        "\t{",
    ]
    for sid in sorted(passive_actions):
        lines.append(f"\t\t[{cs_string(sid)}] = new[] {{ " + ", ".join(passive_actions[sid]) + " },")
    for kind, name, doc in (
        ("buff_applied", "ObservedBuffSchematics", "Native buff sid -> schematics observed when a source unit applies it (buff_applied)."),
        ("aura", "ObservedAuraTagSchematics", "Native aura / global passive tag -> schematics (aura)."),
        ("side_modifier", "ObservedSideModifierSchematics", "Native side modifier / unit-set hero bonus tag -> schematics (side_modifier)."),
    ):
        lines += ["\t};", "", f"\t/// <summary>{doc}</summary>", f"\tinternal static readonly Dictionary<string, int[]> {name} = new()", "\t{"]
        for tag in sorted(tagged[kind]):
            lines.append(f"\t\t[{cs_string(tag)}] = new[] {{ " + ", ".join(str(i) for i in sorted(tagged[kind][tag])) + " },")
    lines += ["\t};", "", "\t/// <summary>Unit sid -> Core fraction (battle-start synergies).</summary>", "\tinternal static readonly Dictionary<string, string> UnitFactionBySid = new()", "\t{"]
    for sid, faction in catalog["unitFactions"].items():
        lines.append(f"\t\t[{cs_string(sid)}] = {cs_string(faction)},")
    lines += ["\t};", "", "\t/// <summary>Unit sids with stats.moveType fly.</summary>", "\tinternal static readonly HashSet<string> FlyerUnitSids = new()", "\t{"]
    for sid in catalog["flyerUnitSids"]:
        lines.append(f"\t\t{cs_string(sid)},")
    lines += [
        "\t};",
        "}",
        "",
    ]
    structs = {
        "OnHitGraft": [("string", "BuffSid"), ("int", "Duration"), ("string", "AttackTag")],
        "VampirismGraft": [("float", "Rate"), ("string", "Target"), ("string", "HealType")],
        "BattleStartGraft": [("string", "Kind"), ("string[]", "Keys"), ("string[]", "BuffSids"), ("int", "Duration")],
        "MapHeroBuffGraft": [("string", "BuffSid"), ("string[]", "NativeUnitSids")],
        "InjectedAbilityGraft": [("string", "SourceUnitSid"), ("int", "SourceIndex"), ("string", "LogicJson"), ("string", "ViewJson")],
        "ObservedPassiveAction": [("int", "Passive"), ("int", "Action"), ("int", "Schematic"), ("string", "Trigger")],
    }
    for name, fields in structs.items():
        params = ", ".join(f"{t} {f[0].lower() + f[1:]}" for t, f in fields)
        lines += [f"internal readonly struct {name}", "{"]
        lines += [f"\tinternal readonly {t} {f};" for t, f in fields]
        lines += ["", f"\tinternal {name}({params})", "\t{"]
        lines += [f"\t\t{f} = {f[0].lower() + f[1:]};" for _, f in fields]
        lines += ["\t}", "}", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--check", action="store_true", help="fail if outputs differ from what is on disk")
    parser.add_argument(
        "--check-derived",
        action="store_true",
        help="Core-free check: the review doc and C# catalog match the on-disk catalog JSON and policy "
        "(the build tier uses this; the installed Core changes sha on every install)",
    )
    args = parser.parse_args()
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if args.check_derived:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        derived = {REVIEW_PATH: render_review(catalog), CS_PATH: render_cs(catalog, policy)}
        stale = [str(p) for p, text in derived.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        if stale:
            print("stale Tower Artificing derived outputs (rerun build_schematic_catalog.py):\n  " + "\n  ".join(stale), file=sys.stderr)
            return 1
        print("Tower Artificing derived outputs current.")
        return 0
    catalog = build(args.core)
    outputs = {
        CATALOG_PATH: json.dumps(catalog, indent=1, ensure_ascii=False) + "\n",
        REVIEW_PATH: render_review(catalog),
        CS_PATH: render_cs(catalog, policy),
    }
    if args.check:
        stale = [str(p) for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        if stale:
            print("stale Tower Artificing outputs:\n  " + "\n  ".join(stale), file=sys.stderr)
            return 1
        print("Tower Artificing outputs current.")
        return 0
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps(catalog["stats"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
