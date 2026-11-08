# Surface: Buffs / statuses (DB tables)

## Intent

Find which Core buff tables matter for hero abilities, hero skills, and space magics — and avoid editing the wrong file or promoting config identity to mutation proof.

## Ownership preference

Edit buff JSON through overlay/generators when custom; prefer cloning a live donor buff envelope. Runtime apply/query mutation stays packet-gated (`buffStatus` / committed-damage adjacent surfaces in the evidence matrix).

## Touch points (installed Core)

| Table | Role |
| --- | --- |
| `DB/buffs/sub_skills_battle_hero_ability_buffs.json` | Buffs tied to hero **abilities** / ability subskills (warrior/mage debuffs, Warcry effects, faction ability effects) |
| `DB/buffs/sub_skills_battle_hero_buffs.json` | Broader battle hero buff set (includes class/unit bonus style rows) |
| `DB/buffs/sub_skills_battle_hero_skill_*.json` | Formation / leadership / luck / tactics skill buff packs |
| `DB/buffs/buffs_space_magics.json` | Space-magic (spell) buff definitions |
| Ability info deltas | `DB/heroes_abilities/heroes_abilities_infos/hero_abilities_infos.json` |

Static xref trees under `docs/surface_xref_trees/buff_status_surface_xref_tree.md` are **not** runtime proof.

## Can / cannot

**Can:** add/reshape buff rows that native apply paths already understand.

**Cannot:** claim `buffStatus.buffConfigDefinitions` proven-static means custom apply is safe.

## Pitfalls

- Wrong table → silent missing effect.
- Duration / dispel / hidden flags matter; copy donor flags deliberately.
- Speed-modifying buffs need donor movement tags (`movementPositive` / `movementNegative`, plus haste/slow family tags when cloning haste/web). Live-negative: Split Assembly speed rows verified present in the buff manager without those tags did not change combat Speed.
- **Live-proven (2026-07-26):** even with correct tags and `BuffConfig.data.stats.speed`, `dzv.bbgf` + got-buff dispatch leaves `Unit.get_stats().get_speed` unchanged. Effective speed moves only after folding `config.data.stats` additively via `set_speed(current + delta)` (same for initiative/offence/defence). `Homm3BuffDebuffNativeAdapter` owns that fold after a successful add. Replacing the whole `UnitStat` (`Method_Public_Void_UnitStat_0`) clobbers — do not use it for deltas.
- Battle-long custom army buffs (Split Assembly, Bulwark Runes) need Core `infinite: true` and `addition: "data"` (not `addition: "duration"`). Live-negative: Split Assembly rows with `addition: "duration"` applied (`verified=true`) then decayed immediately in combat.
- Hire / ability-display UI NRE often means null BuffConfig from a bad or missing buff SID (exact leveled Core id), not missing art bundles — run `tools/validate_homm3_unit_buff_sid_contract.py` before blaming assets.
- Config identity ≠ apply/query mutation proven.
- Plugin buff add/event: pin through `GameSymbols.BuffDebuffLaws` only. Got-buff dispatch is `BuffEventDispatch` = live `Method_Public_Void_Object_BattleEventArgs_35` (`cfin`). **Do not** map DiffableCs `bcja` declaration index 39 to `Method_39` — that live raise is `cfir` / ChangeAbility and live-negatives with `BuffEventArgs`→`ChangeAbilityEventArgs`. Invoke `hub.bcja(nativeSource, args)`; never pass the hub as both `this` and Object sender.
- Post-add presence: use `BuffListBySid` (`bbfl`) `get_Count` — not a lone `Boolean_String_*` guess. Live exposes three `Boolean_String` methods (`bbfn` / `dud` / `ink`); IL2CPP `List<T>` is not CLR-`IEnumerable` (`matchCount=-1` from foreach is a bad probe, not proof of empty).
- Exact-id custom buff rows (and law markers) typically apply with level ≥ 1; vanilla leveled rows use base sid + level (`magic_haste_effect` → `magic_haste_effect_1`).

## Open unknowns

Safe custom buff apply/query mutation surfaces remain partial in the evidence matrix. Injected Split Assembly / Bulwark buff presence (`verified=true` / list-by-SID Count) is runtime-proven; **effective combat Speed** after adapter fold is live-probe-proven mid-combat (`get_speed` delta). Full battle-start → UI Speed for industrial Split Assembly still needs a fresh combat after OfflineUnlockMod deploy (Unit.Init apply timing vs mid-combat wipe remains a separate concern).

## Proof labels

Config identity: matrix `proven-static`. Manager presence: runtime-proven. Effective `get_stats` fold after inject: live-probe-proven (additive setters). User-visible battle-start Split Assembly Speed: pending deploy + combat.

Hub: [../agent_surface_guide.md](../agent_surface_guide.md).
