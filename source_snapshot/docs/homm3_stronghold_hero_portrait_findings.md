# HoMM3 Stronghold Hero Portrait Findings

Date: 2026-05-02

## Current State

- `DB/heroes/homm3_stronghold/homm3_stronghold_hero_1..18.json` now use icon keys `hero_homm3_stronghold_1..18`.
- Hero slots 17 and 18 have no extracted HoMM3 Stronghold portrait PNGs. They intentionally use custom Stronghold icon keys anyway, and `Homm3ImportPortraitSpriteCache` aliases them to existing HoMM3 portraits so Dungeon donor portraits do not leak into Stronghold UI.
- Extracted hero portrait PNGs are now present in the source mod directory:
  `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_hero_portraits/`
- `OfflineUnlockMod.csproj` deploys `homm3_hero_portraits/` to the plugin folder.
- Runtime diagnostics proved that `ckj` is not the central hero icon resolver in the current build. It exposes only inherited Unity component methods for our scan, so `ckj.scf`/`hqu`/`scg` should not be assumed.
- `Homm3HeroPortraitHook.cs` now patches known portrait surfaces directly using the current runtime names: `BhHeroSelectButton.hmy`, `BhTooltipHeroItemView.sre/srf/srg`, `BhHeroPortraitView.zfq/zft`, `BhTavernHeroView.ynz`, plus the older HUD/city fallback hooks.
- The direct surface patches resolve hero config data (`HeroConfig.icon` / `sid`, `Hero.ivd()` / `cmeo`, etc.) and replace private `Image` fields named `heroFace`, `pic`, or `icon` with cached PNG sprites for `hero_homm3_stronghold_N` / `homm3_stronghold_hero_N`.
- Runtime log evidence shows that hook can work after match start for at least Boragus:
  `Homm3HeroPortrait: replaced [BhHeroHUDPanel.ghk] sid='homm3_stronghold_hero_6' sprite='homm3_static_portrait_homm3_stronghold_hero_6'.`
- Later runtime log evidence showed the HUD fallback and nested `BhTooltipHeroItemView` path could identify Yog, load the correct cached sprite, and assign it, while the visible UI still showed the orange placeholder. That points to the game rebinding or overriding the UI image after our first assignment, not to missing PNG files.
- The hook now assigns both `Image.sprite` and `Image.overrideSprite`, forces the image active/enabled/white, remembers only portrait view instances that have already been matched to a Stronghold hero key, and reapplies their sprite from `BhTooltipHeroItemView.LateUpdate` if the game changes it later.
- A later custom-law-icon placeholder report strengthened the same root-cause hypothesis: custom JSON icon keys do not enter the game's serialized sprite registry automatically. The law icon hook also incorrectly depended on `ckj`, so it now has a direct `BhFractionLawView.yoh` surface patch.

## Why Donor Portraits Still Appear

The extracted PNGs are not part of the game's normal sprite registry. The normal UI path resolves `hero.icon` through serialized sprite dictionaries, so a JSON icon like `hero_dungeon_1_Enatee` resolves to a real Dungeon portrait. A JSON icon like `hero_homm3_stronghold_1` is unknown to the game and can show the orange placeholder unless a runtime hook supplies a sprite.

The attempted central resolver hook did not find a real resolver. Runtime diagnostics on 2026-05-02 showed only two global sprite-like string candidates: `Hex.BhUnitPreviews.hqw(String)` returning `Texture`, and `Hex.Session.Hud.BhSideTimers.vhk(String)` returning `Sprite`. Neither is enough to cover all hero portrait art surfaces.

The hook is also fragile because it identifies heroes by visible localized text. It can fail if:

- the text is hidden or not populated yet,
- the UI language changes,
- the current panel uses SID/config data but does not display the hero name,
- duplicate/ambiguous text appears in the same subtree,
- the portrait object is not literally named `PORTRAIT`.

The fallback can also be beaten by UI timing: logs may show `replaced` or `surface replaced` while the visible art remains the placeholder because a later binder writes the placeholder back into the same `Image`. In that case look for `remembered surface` and `refresh replaced` log lines; if those do not appear, the surface being displayed is probably not the remembered `BhTooltipHeroItemView` instance.

## Asset Gaps

- HoMM3 Stronghold provides 16 native Stronghold portraits. The mod currently has 18 Stronghold hero slots; slots 17 and 18 use explicit runtime aliases to existing HoMM3 portraits until they get generated art or are removed from the custom faction hero pool.
- `tools/extract_homm3_hero_portraits.py` now writes to the source mod directory by default; the `.csproj` deploy step copies the portraits into the game plugin directory.

## Better Solution Options

### 1. Central Runtime Sprite Lookup Hook

Patch the game's central icon/sprite resolver and return `Homm3ImportPortraitSpriteCache` sprites for `hero_homm3_stronghold_N` or `homm3_stronghold_hero_N`.

Do not start with `ckj`; runtime logs showed it is the wrong type in this build. If pursuing this path, identify the real resolver from call sites that bind `HeroConfig.icon` into `Image.sprite` or from serialized sprite dictionary owners.

Then update generated hero JSON to set:

```json
"icon": "hero_homm3_stronghold_1"
```

This would still be the cleanest runtime approach because every UI surface that uses normal icon lookup would benefit from one patch.

### 2. Sprite Dictionary Injection

After the game's sprite storage initializes, add generated `Sprite` instances into the relevant `ckj` dictionary under keys like `hero_homm3_stronghold_1`.

This preserves normal game call sites and avoids patching every hero UI panel. The hard part is identifying the correct dictionary among the many `ckj` sprite dictionaries and timing injection after initialization.

### 3. Surface Patches

Keep the current panel-specific strategy but patch hero portrait binders directly and resolve SIDs from model/session objects, not visible text.

Candidate surfaces/classes from the IL2CPP dump include:

- `Hex.Session.Hud.BhHeroHUDPanel`
- `Hex.UI.City.BhHeroWithPartyCityView`
- `Hex.BhHeroSelectButton.hmy(HeroConfig, Action, Action)` - hero select/pick art
- `Hex.Session.UI.HeroProfile.BhHeroPortraitView.zfq/zft`
- `Hex.UI.BhTooltipHeroItemView.sre/srf/srg`
- `Hex.Session.UI.BhTavernHeroView.ynz`
- `Hex.UI.Tooltips.BhTooltipSquad`
- `Hex.Session.Battle.BhHeroView`
- `Hex.Session.UI.BhTavernHeroView`
- `Hex.Session.Hud.BhHeroPortrait`
- hero selection and pick classes such as `BhHeroesSelection`, `ScHeroSelectionPanel`, `ScHeroSelect`, `BhHeroSelectable`, and `BhHeroElementView`

This is the quickest incremental path, but it will remain brittle and high-maintenance.

## Recommended Path

1. Validate in-game that `Homm3HeroPortrait: surface replaced...` appears in `BepInEx/LogOutput.log` when hero select/tavern/profile surfaces load.
2. If a UI surface still shows the orange placeholder, inspect which screen owns it and add a targeted binder patch, or find the real central resolver.
3. Generate or choose explicit art for bonus slots 17-18 if they should stop using aliased HoMM3 portraits.
4. Eventually remove visible-text SID resolution from the fallback hook and resolve from model/session data instead.

## Warning For Future Agents

Do not fix this by only changing `icon` fields in Core.zip. Without the runtime sprite lookup hook, the game will have unknown icon SIDs and affected UI surfaces may show blank portraits or throw lookup errors.
