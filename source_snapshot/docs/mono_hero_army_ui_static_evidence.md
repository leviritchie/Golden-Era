# Mono-to-Deobf Hero and Army UI Adapter Evidence

Status: source-prepared/static-only. This document records Mono demo versus current Golden Era static evidence. It is not runtime proof.

## Scope

This slice covers existing-mod UI surfaces where custom hero, unit, or squad data can enter native UI panels:

- `Hex.Session.Hud.BhHeroUIElement`
- `Hex.Session.Hud.BhUnitSlots`
- `Hex.Session.UI.HeroProfile.BhHeroSlotViews`
- `Hex.Session.UI.HeroProfile.BhHeroStatView`
- `Hex.Session.UI.BhHeroStats`
- `Hex.BhHeroSelectButton`

It deliberately excludes battle damage/forecast math and map-squad rendering internals. Those are adjacent systems, but not the same UI adapter problem.

## Evidence artifacts

- Broad map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.json`
- Mono decompile: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_priority_hero_army_ui_decompiled.cs`
- Current method dossiers:
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/hero_army_BhHeroUIElement_Init_dossier.md`
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/hero_army_BhUnitSlots_Init_dossier.md`
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/hero_army_BhHeroSlotViews_Init_dossier.md`
  - `experiments/cpp2il_readable_csharp/samples/latest_refresh/hero_army_BhHeroStats_zbj_dossier.md`

## Type survival

The broad map and current files show exact type-name survival for the UI adapter classes in this slice.

| Mono type | Current deobf type | Static status |
|---|---|---|
| `Hex.Session.Hud.BhHeroUIElement` | `Hex.Session.Hud.BhHeroUIElement` | strong static type match |
| `Hex.Session.Hud.BhUnitSlots` | `Hex.Session.Hud.BhUnitSlots` | strong static type match |
| `Hex.Session.UI.HeroProfile.BhHeroSlotViews` | `Hex.Session.UI.HeroProfile.BhHeroSlotViews` | strong static type match |
| `Hex.Session.UI.HeroProfile.BhHeroStatView` | `Hex.Session.UI.HeroProfile.BhHeroStatView` | strong static type match |
| `Hex.Session.UI.BhHeroStats` | `Hex.Session.UI.BhHeroStats` | strong static type match |
| `Hex.BhHeroSelectButton` | `Hex.BhHeroSelectButton` | strong static type match |

## Mono source shape

### HUD hero button: `BhHeroUIElement`

Mono `Init(WorldHero hero)`:

- Unlistens the prior hero slot event source if present.
- Stores the new hero.
- Listens to hero slot events.
- Toggles city marker based on `EHeroStatus.OnMap` versus `EHeroStatus.InCityGarrison`.
- Releases prior transient state.
- Sets selected state from `hero.isSelected`.
- Loads hero icon.
- Subscribes local hero resource/stat update events.
- Refreshes training state and resource bars.

This is a hero-HUD lifecycle bind point, not just an icon setter.

### HUD unit slots: `BhUnitSlots`

Mono `BhUnitSlots` is the army slot container. The current dossier shows `Init(dta _party)` stores/attaches the party and calls `wgy()`. The heavy work is not in `Init`; current type triage shows `wgy()` is the high-complexity rebuild/populate method with dictionary/list/pool traffic.

### Hero profile slots: `BhHeroSlotViews`

Mono `Init(Hero hero, bool isArena)`:

- Stores arena/fight flags.
- Stores hero.
- Listens to hero slot event manager.
- Assigns hero into each slot view.
- Clears temp item list.
- Calls `FillSlots(fromInit: true, isArena)`.

Mono fill path:

- Clears all slot views.
- Iterates `hero.slots.allItems`.
- Uses `slotsByType` plus `slotId` to choose a slot view.
- Calls `SetItem` on the selected slot view.
- Applies locks from `hero.slots.locksByType`.
- Refreshes hero data stats.

### Hero profile stats: `BhHeroStats` and `BhHeroStatView`

Mono `BhHeroStats.Set(Hero hero)` computes displayed stat values from current hero stats and percentage modifiers, then calls `BhHeroStatView.Set` for attack, defence, spell power, intelligence, luck, and morale.

Mono `BhHeroStatView.Set` stores displayed value plus tooltip SID and icon/stat SID, and hover dispatches `BhTooltips.me.ShowStats(...)`.

### Hero select button: `BhHeroSelectButton`

Mono `Setup(HeroConfig hero, Action onSelect, Action onHover)`:

- Stores select/hover callbacks.
- Toggles hero icon versus random icon.
- If a hero config is present, loads `IconManager.Instance().BySid(hero.icon)` into the icon.

This is a narrow hero-selection icon bind point.

## Current deobf method map

### `BhHeroUIElement`

| Current method | Static claim | Evidence |
|---|---|---|
| `Init(etc _hero)` | Current HUD hero lifecycle bind. | Stores `etc` into `cbfm`, toggles `city`, calls `wdk`, `etc.bhax`, `wdi`, `Hero.bfwx`, sprite lookup `cko.sfo`, and `Image.set_sprite`. |
| `wdk()` | Resource/training/status refresh cluster candidate. | Type triage shows high field use for hero, selector, mana/move/status fields. Generate focused dossier before patching. |
| `wdi(bool)` | Selected-state visual candidate. | Called from `Init`; touches selector image/state fields. |
| `wdj()` | Training marker refresh candidate. | Field usage touches `trainingImage`. |
| `wdq()` | Resource bar refresh candidate. | Field usage touches `manaImage`/move-point fields. |
| `wdr()` | Icon load helper candidate. | Type-level evidence touches `heroIcon`; `Init` already shows icon sprite lookup in the lifecycle route. |

### `BhUnitSlots`

| Current method | Static claim | Evidence |
|---|---|---|
| `Init(dta _party)` | Current party/container bind. | Calls `dta.yii`, `dta.yih`, then `BhUnitSlots.wgy`; stores party field `cbhl`. Good lifecycle hook. |
| `wgy()` | Current unit-slot rebuild/populate candidate. | Highest complexity method in type; type triage shows list/dictionary/pool/slot fields and native UI child traffic. This is the important per-slot rendering boundary, not `Init`. |
| `wha()` / `whb(BhUnitUI)` | Unit UI pool get/return candidates. | Type triage indicates `BhUnitUI` pool access through queue/list fields. |
| `wgp()` / `wgq()` / `wgr()` | Read-only accessors for unit dictionary/list/party. | Current signatures expose dictionary/list/party access. Prefer read-only use unless runtime-proven. |
| `whc(int)` / `whd()` | Slot update/clear candidates. | Type triage shows slot list/dictionary activity. Needs focused dossier if changing slot contents. |

### `BhHeroSlotViews`

| Current method | Static claim | Evidence |
|---|---|---|
| `Init(Hero, bool, bool)` | Current hero profile equipment-slot bind. | Stores hero field `cdxc`, arena/fight flags `cdxe/cdxf`, enumerates views, clears temp list, calls `zyr`. |
| `zyr(bool,bool,bool)` | Current fill/rebuild equipment-slot candidate. | Highest complexity method in type; likely Mono `FillSlots`. Uses `slotsByType`, `views`, hero, temp list. Needs focused dossier before patching. |
| `zys(EType)` / `zyt(EType)` | Highlight/unhighlight slot-type candidates. | Mono has highlight paths by slot type. |
| `zyu(string)` / `zyv()` / `zyw(BhInventoryItemView)` | Set/highlight/right-click/action candidates. | Adjacent profile behavior; not core binding until needed. |

### `BhHeroStats`

| Current method | Static claim | Evidence |
|---|---|---|
| `zbj(etc)` | Current world-hero stats refresh route. | Calls `etc.bhak`, several stat helpers, and `BhHeroStatView.zyz` for all stat views. |
| `zbk(Hero)` | Current logic-hero stats refresh route. | Same shape as `zbj`; generate focused dossier if profile refresh differs from world-HUD refresh. |
| `zbi()` | Hide/clear stats route candidate. | Type triage touches all stat fields. |
| `zbh()` | Read-only stat view list accessor. | Current signature returns `IReadOnlyList<BhHeroStatView>`. |

### `BhHeroStatView`

| Current method | Static claim | Evidence |
|---|---|---|
| `zyz(int,string,string)` | Current integer stat bind; Mono `Set(int, tooltipSid, sid)`. | Called by `BhHeroStats.zbj`; stores value/tooltip/icon identity. |
| `zza(string,string)` | Current string stat bind candidate; Mono `Set(string, sid)`. | Current signature matches string display shape. |
| `zzb(string,int)` | Alternate stat bind candidate. | Needs focused dossier if used. |
| `ShowTooltip()` / `HideTooltip()` | Tooltip dispatch only. | Prefer fixing stat values at bind source, not hover fallback. |

### `BhHeroSelectButton`

| Current method | Static claim | Evidence |
|---|---|---|
| `hqc(HeroConfig, Action, Action)` | Hero selection icon/callback bind candidate. | Current signature matches Mono `Setup(HeroConfig, Action, Action)` exactly by parameter shape. Generate focused dossier before altering icon behavior. |
| `hqb(bool,float,float)` / `hqd(LockMode)` | Appearance/lock state candidates. | Not core custom SID binding. |

## Practical modding conclusions

- Hero HUD icon fixes should attach to `BhHeroUIElement.Init` or its icon helper candidate, not to pointer click/hover methods.
- Hero profile stat corrections should attach to `BhHeroStats.zbj/zbk` or `BhHeroStatView.zyz`, not tooltip hover.
- HUD army slot fixes should not stop at `BhUnitSlots.Init`; `Init` delegates the heavy work to `wgy()`. If a bug appears only after party changes, `wgy()` and the slot update helpers need dossiers.
- Hero profile equipment slot fixes should not stop at `BhHeroSlotViews.Init`; `Init` delegates fill/rebuild to `zyr()`. If item slot rendering is wrong, dossier `zyr()` first.
- Hero selection screen icon fixes likely belong at `BhHeroSelectButton.hqc`, which has the same parameter shape as Mono `Setup`.

## Current mod risk surface

The broad source search shows adjacent custom systems using hero/unit/army concepts:

- battle forecast and damage histogram code reads stack counts and kill caps;
- map squad visual code reads `BhMapSquad` and node data;
- selected-unit and tooltip code previously carried broad defensive probes.

Do not collapse these into one catch-all adapter. They are separate systems with different truth sources:

- HUD/profile UI bind truth: `BhHeroUIElement`, `BhUnitSlots`, `BhHeroSlotViews`, `BhHeroStats`.
- Battle math truth: damage/forecast/target contracts.
- Map visual truth: `BhMapSquad`/map object/component tree.

## Static gaps

- `BhUnitSlots.wgy()` needs a focused dossier before changing army slot rendering.
- `BhHeroSlotViews.zyr()` needs a focused dossier before changing equipment slot rendering.
- `BhHeroStats.zbk(Hero)` needs a focused dossier if profile hero stats differ from world hero stats.
- `BhHeroSelectButton.hqc(...)` needs a focused dossier before changing hero select icons.
- No runtime ordering is proven. This map identifies native-friendly hook targets only.

## Next static work

1. Generate focused dossiers for `BhUnitSlots.wgy()` and `BhHeroSlotViews.zyr()` if custom unit/army slot rendering remains fragile.
2. Generate focused dossier for `BhHeroSelectButton.hqc(...)` if hero portrait selection icons are wrong.
3. Split battle forecast/damage histogram and map squad visuals into separate maps; they should not be handled through the UI adapter layer.
