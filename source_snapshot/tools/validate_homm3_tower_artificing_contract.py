"""Contract validator for HoMM3 Tower Artificing (docs/homm3_tower_artificing.md).

Core-free, so it runs on every full-tier plugin build:
- the generated review doc and C# catalog match the committed catalog JSON + policy;
- the catalog agrees with the policy (cost matrix, manual payloads after `{graft}` expansion, exclusions, stable
  indices that fit the ledger's graft-index bits, payloads that are valid buff rows; runtime-, helper- or
  variant-only grafts may have an empty buff payload; every graft has a token-free description);
- the Core overlay rows (graft buffs, Transcribe, ledger and map-graft hero buffs) have the shapes the runtime relies on;
- map grafts are complete (hero buff + native unit set, 7 per-line gold rates, injected abilities within the HUD slots);
- the runtime is gated on Enabled and wired into Plugin.cs, the shared battle-result prefix, Logic.Hero
  RecalculateStats and the shared side day-start grant;
- every graftable row is observable (observe specs of known kinds), and the observation probe is diagnostic only:
  gated on ObservationDiagnostics, scoped on the passive action runner's trigger handler, no book writes.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools" / "release_port"))
sys.path.insert(0, str(REPO / "tools" / "tower_artificing"))

import build_schematic_catalog as gen  # noqa: E402
import observe_specs  # noqa: E402
import homm3_tower_artificing_core_overlay as overlay  # noqa: E402

PLUGIN_DIR = REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
PAYLOAD_KEYS = {"data", "actions", "statOverrides"}


def main() -> int:
    errors: list[str] = []
    check = subprocess.run(
        [sys.executable, str(REPO / "tools" / "tower_artificing" / "build_schematic_catalog.py"), "--check-derived"],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        errors.append("derived outputs stale: " + (check.stderr or check.stdout).strip())

    policy = overlay.load_policy()
    catalog = overlay.load_catalog()
    ledger = policy["ledger"]
    slots = policy["graftSlotsByRank"]
    if len(slots) != 3 or any(s < 0 or s > ledger["maxSlots"] for s in slots) or slots != sorted(slots):
        errors.append(f"graftSlotsByRank {slots} must be 3 non-decreasing values within 0..ledger.maxSlots")
    if ledger["lines"] != 7 or len(catalog["towerLines"]) != ledger["lines"]:
        errors.append("ledger.lines must equal the 7 Tower unit lines")
    if len(policy["essence"]["perDefeatedCreatureByTier"]) != 7 or len(policy["graftCost"]["tierWeight"]) != 7:
        errors.append("essence and tierWeight tables must have 7 tiers")
    if (1 << ledger["schematicTierBits"]) - 1 < 7:
        errors.append("schematicTierBits cannot hold tier 7")
    if catalog["costMatrix"] != gen.cost_matrix(policy):
        errors.append("catalog costMatrix differs from policy graftCost (rerun build_schematic_catalog.py)")

    rows = catalog["schematics"]
    indices = [r["index"] for r in rows]
    if len(set(indices)) != len(indices):
        errors.append("duplicate schematic indices")
    if indices and max(indices) > (1 << ledger["graftIndexBits"]) - 2:
        errors.append(f"schematic index {max(indices)} does not fit graftIndexBits={ledger['graftIndexBits']} (value = index + 1)")
    by_key = {r["key"]: r for r in rows}
    for key, manual in policy["manualPayloads"].items():
        row = by_key.get(key)
        expected = None if row is None else gen.expand_graft({k: v for k, v in manual.items() if k in PAYLOAD_KEYS}, row["graftBuffSid"])
        if row is None:
            errors.append(f"manual payload {key} has no schematic")
        elif not row.get("graftable") or {k: v for k, v in row["payload"].items() if k in PAYLOAD_KEYS} != expected:
            errors.append(f"schematic {key} payload/graftable differs from policy manualPayloads")
    for key in policy["excludedKeys"]:
        if key in by_key and by_key[key]["classification"] != "excluded":
            errors.append(f"excluded key {key} is classified {by_key[key]['classification']}")
    for row in rows:
        if not row.get("graftable"):
            continue
        if row["classification"] != "copyable":
            errors.append(f"graftable schematic {row['key']} is {row['classification']}")
        payload = {k: v for k, v in row["payload"].items() if k in PAYLOAD_KEYS}
        if not payload and not (row.get("runtime") or row.get("helpers") or row.get("variants")):
            errors.append(f"graftable schematic {row['key']} has an empty payload and no runtime/helper/variant effect")
        description = row.get("graftDescription")
        if not description or "{" in description:
            errors.append(f"graftable schematic {row['key']} needs a resolved graftDescription")
        for helper in row.get("helpers") or []:
            if not str(helper["row"].get("id", "")).startswith(row["graftBuffSid"] + "_"):
                errors.append(f"graft {row['key']} helper {helper['row'].get('id')} must be named {row['graftBuffSid']}_*")
        bad = set(payload.get("data", {})) - gen.BUFF_DATA_KEYS
        if bad:
            errors.append(f"graftable schematic {row['key']} data keys {sorted(bad)} are not buff data keys")
        if row["graftBuffSid"] != f"{policy['graftBuff']['sidPrefix']}{row['index']}":
            errors.append(f"graftable schematic {row['key']} graftBuffSid {row['graftBuffSid']} breaks the prefix+index rule")
        runtime_spec = row.get("runtime") or {}
        if runtime_spec.get("heroBuff"):
            hero_buffs = [h["row"]["id"] for h in row.get("helpers") or [] if h["kind"] == "hero_buff"]
            if runtime_spec["heroBuff"] not in hero_buffs or not row.get("nativeUnitSids"):
                errors.append(f"map graft {row['key']} needs its hero_buff helper row and the native unit-set sids (non-stacking)")
        if runtime_spec.get("dailyGold"):
            rates = row.get("dailyGoldByLine") or []
            if len(rates) != ledger["lines"] or any(not isinstance(v, int) or v <= 0 for v in rates):
                errors.append(f"gold graft {row['key']} needs {ledger['lines']} positive per-line rates")
        observe = row.get("observe") or []
        if not observe or any(spec.get("kind") not in observe_specs.OBSERVE_KINDS for spec in observe):
            errors.append(f"graftable schematic {row['key']} needs observe specs of known kinds (observeOverrides or derivation)")
        if runtime_spec.get("abilities"):
            injected = row.get("injectedAbilities") or []
            if not injected or len(injected) > gen.HUD_SKILL_SLOTS or any(not (a.get("logic") or {}).get("damageDealer") or not a.get("view") for a in injected):
                errors.append(f"ability graft {row['key']} needs 1..{gen.HUD_SKILL_SLOTS} embedded abilities with logic damageDealer and view")

    graft_rows = overlay.make_graft_buff_rows(policy, catalog)
    for row in graft_rows:
        if row.get("canDispel") is not True or row.get("infinite") is not True or row.get("addition") != "data":
            errors.append(f"graft buff {row['id']} must be canDispel, infinite, addition=data (purge counterplay)")
    ledger_rows = overlay.make_ledger_hero_buff_rows(policy, catalog)
    if len({r["id"] for r in ledger_rows}) != len(ledger_rows):
        errors.append("ledger hero buff ids collide")
    for row in ledger_rows:
        if row.get("hidden") is not True or row.get("isDispellable") is not True or row.get("bonuses"):
            errors.append(f"ledger buff {row['id']} must be hidden, bonus-less and isDispellable (native Remove needs it)")
            break
    if any(r["id"].startswith(policy["graftBuff"]["sidPrefix"]) for r in ledger_rows):
        errors.append("ledger hero buff prefix overlaps the graft buff prefix")
    for row in overlay.make_helper_rows(catalog)["hero_buff"]:
        if row.get("hidden") or row.get("isDispellable") is not True or not row.get("bonuses"):
            errors.append(f"map graft hero buff {row['id']} must be visible, carry bonuses and be isDispellable (the reconcile removes it)")
    ability = overlay.make_transcribe_hero_ability(policy)
    dealer = ability["levels"][0]["damageDealer"]
    if dealer["buff"]["sid"] != policy["transcribe"]["effectBuffSid"] or ability["levels"][0]["aiValue"] != 0:
        errors.append("Transcribe ability must apply the marker buff and keep aiValue 0")
    marker = overlay.make_transcribe_effect_buff_row(policy)
    if marker["canDispel"] or marker["maxDuration"] != 1:
        errors.append("Transcribe marker buff must be a non-dispellable 1-round buff")

    runtime = (PLUGIN_DIR / "Homm3TowerArtificingRuntime.cs").read_text(encoding="utf-8")
    plugin = (PLUGIN_DIR / "Plugin.cs").read_text(encoding="utf-8-sig")
    hooks = (PLUGIN_DIR / "Homm3RuntimeMechanicHooks.cs").read_text(encoding="utf-8-sig")
    observation = (PLUGIN_DIR / "Homm3TowerArtificingObservation.cs").read_text(encoding="utf-8-sig")
    gold_hook = (PLUGIN_DIR / "Homm3SwashbucklerGoldHook.cs").read_text(encoding="utf-8-sig")
    for needle, text, where in (
        ("if (!IsEnabled)", runtime, "runtime registration must stay gated on Homm3TowerArtificingCatalog.Enabled"),
        ("Homm3TowerArtificingRuntime.TryRegister(_harmony, Log);", plugin, "Plugin.cs must register the runtime"),
        ("Homm3TowerArtificingRuntime.ObserveBeforeBattleResult(__0);", hooks, "battle-result prefix must award essence"),
        ("GameSymbols.BattleEventLaws.ObjectTookDamageDispatcher", runtime, "on-hit/vampirism grafts need the ObjectTookDamage dispatcher postfix"),
        ("GameSymbols.BattleEventLaws.RoundStartedDispatcher", runtime, "first-round grafts need the RoundStarted dispatcher postfix"),
        ("GraftVariantBuffSid", runtime, "perUnit grafts must pick the carrier's variant buff"),
        ("OncePerBattleSchematics", runtime, "once-per-battle grafts must skip late unit inits"),
        ("CarrierStillGrafted", runtime, "runtime grafts must stop once the graft buff is purged"),
        ("GameSymbols.TowerArtificing.LogicHeroRecalculateStats", runtime, "map graft buffs must follow army changes (RecalculateStats postfix)"),
        ("MapHeroBuffBySchematic", runtime, "map graft buffs must come from the catalog table"),
        ("NativeUnitSids", runtime, "map graft buffs must not stack with the native unit set"),
        ("TryRegisterDayStartHeroConsumer(\"homm3.tower.artificing\"", runtime, "gold grafts need the shared day-start consumer"),
        ("DailyGoldBySchematic", runtime, "gold grafts must use the catalog per-line rates"),
        ("InjectedAbilitiesBySchematic", runtime, "ability grafts must be injected at Unit.Init"),
        ("HudSkillSlots", runtime, "ability injection must respect the HUD skill slots"),
        ("SumConsumerGold(__instance", gold_hook, "the side day-start grant must add consumer gold"),
        ("Homm3TowerArtificingObservation.TryRegister(_harmony, Log);", plugin, "Plugin.cs must register the observation probe"),
        ("if (!Homm3TowerArtificingCatalog.ObservationDiagnostics)", observation, "the observation probe must stay gated on policy.observation.diagnostics"),
        ("GameSymbols.TowerArtificing.PassiveActionRunnerTrigger", observation, "attribution needs the passive action runner trigger scope"),
        ("ObservedPassiveActionsByUnitSid", observation, "attribution must map config identity through the catalog table"),
    ):
        if needle not in text:
            errors.append(where)

    for forbidden in ("TryAddEssence", "WriteBits", "Transcribe(", "TryGraft("):
        if forbidden in observation:
            errors.append(f"the observation probe is diagnostic only; it must not call {forbidden}")

    if errors:
        print("Tower Artificing contract FAILED:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    print(
        f"Tower Artificing contract ok: enabled={policy['enabled']} graftable={sum(1 for r in rows if r.get('graftable'))} "
        f"graftBuffs={len(graft_rows)} ledgerBuffs={len(ledger_rows)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
