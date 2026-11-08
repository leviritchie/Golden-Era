# Surface: Separate hero battle actions (Warcry / Gating / Avenger / …)

## Intent

Add or adjust **extra** hero battle buttons that are not the stock warrior/mage commander attack: Stronghold Warcries, Inferno Gating summons, Rampart Avenger, Tower Arcane Battery, Castle Elite Strategem mode toggles, etc.

## Ownership preference

1. **Data grant:** `heroBattleAbility` rows on skills / specializations / subskills (overlay-owned ability SIDs).
2. **UI icons / binds:** release-safe Warcry surfaces via `Homm3WarcriesHeroAbilityHook` + `GameSymbols.WarcryHeroAbility` (and analogous icon caches for custom abilities).
3. **Runtime behavior:** prefer native ability envelopes; use packet-gated law/runtime only when required.
4. **Do not** use the quarantined legacy Warcry availability-normalization path as product.

## Touch points

| Family | Notes |
| --- | --- |
| Warcry | `Homm3WarcriesHeroAbilityHook`, buffs like `homm3_stronghold_warcry_*` in ability buffs table; validators under `tools/release_port/validate_warcry_*` |
| Gating | Inferno `heroBattleAbility` ability SIDs in overlay; gating sacrifice predicates in law profiles |
| Avenger | Rampart `heroBattleAbility` level overrides; marker runtime separate from stock Heroic Strike |
| Arcane Battery | Tower ability SID + native `refresh_spell_book` only (no per-spell CD wipe); `validate_homm3_tower_arcane_battery_contract.py` |
| Elite Strategem | Castle spellbook placement toggles — not a custom-law row. A pending mode is stored per casting `DataHero.id`, applied to that hero's next battle, and consumed after the first successful application. Casting-hero identity is read handler -> WorldHero -> LogicHero through `GameSymbols.CastleEliteStrategem` properties resolved with exact types at registration; a drifted pin there made every cast a no-op from Aug 8 to 2026-09-27 (log: `casting hero identity unresolved (world-magic WorldHero member missing)`). Source/build-validated; runtime unproven. |

## Can / cannot

**Can:** add ability rows + grants + icons through overlay and required UI hooks.

**Cannot:** assume legacy `TryRegister` Warcry normalization still runs (it logs quarantine and returns). Cannot treat Focus UI bind probing as safe in broad law pilots.

## Pitfalls

- Extra actions are **additive** slots; overwriting `skill_warrior_ability` is a different design.
- Icon cache zero-row success was a real failure mode — verify cache load counts.
- Elite Strategem must not use a process-global active mode; key by casting hero identity and consume the pending mode after successful application or every later Castle combat inherits the last toggle.

## Open unknowns

Per-ability combat proof. Quarantine of legacy Warcry path: `source/static` in hook. Product combat proof remains per feature.

Hub: [../agent_surface_guide.md](../agent_surface_guide.md).
