# Mono Icon, Portrait, and Sprite Binding Static Evidence

Status: source-prepared/static-only. Runtime-unvalidated.

This dossier maps old Mono demo icon/portrait binding behavior onto the current Golden Era DiffableCs/ISIL output. It covers native UI sprite assignment contracts used by custom law icons, hero portraits, hero specialization icons, unit ability icons, and hero ability icons.

## Bottom line

Most vanilla UI icon surfaces are thin data-to-`Image` binders. The old Mono demo repeatedly resolves a sprite through `IconManager.Instance().BySid(...)` or `IconManager.me.BySid(...)`, then assigns that `Sprite` to an `Image`. Current deobf preserves the same model: the concrete UI views still hold `Image` fields, bind methods still accept config objects, call current icon manager method `cko.sfo`, and then call `Image.set_sprite`.

The most native-friendly custom icon strategy is therefore:

- put custom icon keys into data rows when the row has a real icon field,
- patch narrow UI bind surfaces only where the native icon manager cannot resolve custom keys,
- assign final `Sprite` directly to the already-bound `Image`,
- avoid replacing whole UI panels or broad resource-manager fallbacks.

`Hex.UI.BhIcon.suj(Sprite)` is a particularly stable low-level sprite-assignment surface: current ISIL shows it only null-checks `skillIconImage` and calls `Image.set_sprite`.

## Mono source evidence

Mono decompile artifact: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_priority_icon_portrait_decompiled.cs`.

Relevant Mono contracts:

| Mono type | Evidence |
|---|---|
| `Hex.BhHeroSelectButton` | `Setup(HeroConfig hero, ...)` toggles `icon`/`randomIcon`, then sets `icon.sprite = IconManager.Instance().BySid(hero.icon)`. |
| `Hex.Configs.AbilityViewConfig` | Ability UI data owns `name`, `description`, `abilityType`, and `icon` fields. The old city ability UI actually uses `viewConfig.name` for icon lookup in several surfaces, so current code must not assume every UI surface reads `icon`. |
| `Hex.Configs.HeroAbilityConfig` | Hero ability data owns `levels`; `PostLoad()` exists as data normalization. |
| `Hex.Configs.HeroAbilityLevelConfig` | Hero ability levels own display text, `energyLevel`, cooldowns, charges, effects, and projectile/effect fields. Icons are not level-owned in this Mono artifact. |
| `Hex.Configs.SpriteConfig` | Simple data holder with `sprite` string. |
| `Hex.Session.City.BhHireUnitAbilityItemView` | `Init(string)` sets `pic.sprite = IconManager.Instance().BySid(_sid)`. `Set(...)` and `SetPassive(...)` store `AbilityViewConfig` and set `pic.sprite = IconManager.me.BySid(viewConfig.name)`. |
| `Hex.Session.City.BhHireUnitAbilityView` | Both overloads of `SetView(...)` store `AbilityViewConfig` and set `pic.sprite = IconManager.me.BySid(viewConfig.name)`. |
| `Hex.Session.Hud.BhHeroUIElement` | Holds `heroIcon`; `Init(WorldHero)` calls icon loading after storing the hero. |
| `Hex.Session.Battle.BhUnitAbilityView` | Stores a `BhAbilityViewBase`, `UIAbility`, and `Ability`; this is a battle ability wrapper rather than the low-level sprite binder itself. |

## Current Golden Era evidence

Current deobf artifacts:

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/UI/BhIcon.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Storage/IconData.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Configs/AbilityViewConfig.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Configs/HeroAbilityConfig.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Configs/HeroAbilityLevelConfig.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/City/BhHireUnitAbilityItemView.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/City/BhHireUnitAbilityView.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/BhHeroSelectButton.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/Hud/BhHeroUIElement.cs`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/UI/BhIcon.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Storage/IconData.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Session/City/BhHireUnitAbilityItemView.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Session/City/BhHireUnitAbilityView.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/BhHeroSelectButton.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Session/Hud/BhHeroUIElement.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Session/UI/HeroProfile/BhHeroPortraitView.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Session/UI/HeroProfile/BhHeroSpecializationView.txt`

Current shell and ISIL matches:

| Current surface | Claim | Evidence strength |
|---|---|---|
| `Hex.UI.BhIcon.suj(Sprite)` | Low-level icon setter assigns a supplied sprite to the serialized `skillIconImage`. | Strong static: DiffableCs has `skillIconImage`; ISIL calls `Image.set_sprite`. |
| `Hex.Storage.IconData` | Native icon storage can serialize sprite texture bytes and recreate sprites from bytes. | Strong static: current ISIL constructors call `Sprite.get_texture` and `ImageConversion.EncodeToPNG`; `izt()` calls `ImageConversion.LoadImage` and `Sprite.Create`. |
| `Hex.Configs.SpriteConfig.sprite` | Data rows can carry sprite keys as plain strings. | Strong static: exact current shell field. |
| `Hex.Configs.AbilityViewConfig` | Current ability view configs preserve the old display/icon data shape. | Strong static for type/field shape; exact icon-consumer depends on UI surface. |
| `BhHireUnitAbilityItemView.Init(string)` | Direct string icon bind still resolves through `cko.sfo` and writes `pic`. | Strong static: current ISIL calls `cko.sfo(_sid)` then `Image.set_sprite(pic, sprite)`. |
| `BhHireUnitAbilityItemView.banl/banm` | Active/passive ability item binds store `AbilityViewConfig`, resolve a string from the config, and write `pic`. | Strong static: current ISIL stores `cege`, calls `cko.sfo`, and assigns `pic`; Mono identifies these as `Set` and `SetPassive`. |
| `BhHireUnitAbilityView.bann/bano` | Larger ability view binds store `AbilityViewConfig`, resolve a string from the config, and write `pic`. | Strong static: current ISIL stores `cegh`, calls `cko.sfo`, and assigns `pic`; Mono identifies overloads of `SetView`. |
| `BhHeroSelectButton.hqc(HeroConfig, Action, Action)` | Hero selection card binds `HeroConfig.icon` through icon manager to `icon`. | Strong static: current ISIL calls `cko.sfo(..., HeroConfig.icon)` then `Image.set_sprite(icon, sprite)`. |
| `BhHeroUIElement.Init(etc)` | Adventure HUD hero element resolves current hero config and binds `heroIcon`. | Strong static for bind path: current ISIL calls `Hero.bfwx`, then `cko.sfo(..., HeroConfig.icon)`, then `Image.set_sprite(heroIcon, sprite)`. |
| `BhHeroSpecializationView.zyx/zyy` | Hero profile specialization view obtains specialization config and writes `icon`. | Strong static: current ISIL calls `bzd.pmw`, then `cko.sfo`, then `Image.set_sprite(icon, sprite)`. |
| `BhHeroPortraitView.zxx` | Hero profile portrait bind delegates portrait display through `BhTooltipHeroItemView` and also updates specialization view. | Strong static for call chain; the actual portrait image is inside tooltip hero item view, not directly owned by this class. |

Note: one row label above includes the current obfuscated method pair `banl`/`banm`. If a tool renders the slash oddly, treat it as `BhHireUnitAbilityItemView.banl` and `BhHireUnitAbilityItemView.banm`.

## Symbol implications

Current `GameSymbols` entries are directionally correct for these surfaces:

- `GameSymbols.CustomGame.BhIconSetSprite` maps to `Hex.UI.BhIcon.suj(Sprite)`.
- `GameSymbols.UnitPreviewAbilityIcons` maps to the city ability item/view bind methods where `AbilityViewConfig` and image fields are present.
- `GameSymbols.HeroPortrait` maps to hero select, side hero, tooltip hero item, and hero profile surfaces.
- `GameSymbols.HeroProfile` maps to hero profile portrait/specialization/skill/subskill icon surfaces.

The important correction is conceptual: the native icon source is not always `AbilityViewConfig.icon`. Mono and current ISIL show several ability UI surfaces resolve `viewConfig.name`. For custom abilities, the safest custom icon hook should inspect the actual bound `AbilityViewConfig` and select the project-owned icon key intentionally, rather than assuming the field used by vanilla is semantically named `icon`.

## Implementation guidance

Do:

- Prefer data-owned icon keys for law rows, hero ability rows, ability view rows, and sprite-config rows.
- Use `BhIcon.suj(Sprite)` when the UI already exposes or receives a `Sprite` object.
- Use narrow postfixes on bind methods that already resolve and assign sprites when custom keys are not in vanilla `IconManager`.
- Keep custom key filtering explicit: custom HoMM3 prefixes, custom faction icon keys, custom hero SIDs, and known donor aliases.
- Keep `Image.sprite`, `Image.overrideSprite`, `Image.preserveAspect`, and enabled/color fixes local to the exact image surface being patched.

Do not:

- Add a broad global icon-manager fallback unless a future dossier proves that is safer than the current narrow UI bind patches.
- Assume every ability icon surface reads `AbilityViewConfig.icon`; some read `name`.
- Replace whole UI panels to fix one missing sprite.
- Treat this as runtime proof. Static evidence proves call shape, not that a custom sprite appears at runtime.

## Remaining uncertainty

| Uncertainty | Why it remains | Recommended proof |
|---|---|---|
| Exact global `IconManager` type identity (`cko`) | Current ISIL calls `cko.sfo`, but this pass did not map the full icon manager owner. | Build a focused `cko` dossier if considering an icon-manager-level hook. |
| Hero tooltip portrait inner image | `BhHeroPortraitView` delegates to `BhTooltipHeroItemView`; this dossier did not re-map that inner view because it overlaps `mono_unit_tooltip_preview_static_evidence.md`. | Use existing tooltip dossier or build a narrow hero-tooltip portrait supplement if needed. |
| Runtime custom sprite availability | Static evidence proves assignment routes, not that project sprite caches have loaded every desired key. | Runtime UI screenshot or targeted bridge metadata after core overlay/deploy. |
| Skill/subskill profile exact obfuscated bind names | Current ISIL confirms the type and image fields; this pass only deeply sampled specialization view. | Build method dossiers for `BhHeroSkillView` and `BhHeroSubSkillView` if editing those specific patches. |

