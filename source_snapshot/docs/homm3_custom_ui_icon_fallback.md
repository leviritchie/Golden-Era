# HoMM3 Custom UI Icon Fallback Notes

Current hypothesis: the orange swirl placeholder appears wherever a JSON icon or sprite key is not present in the game's serialized sprite registry. This is not limited to hero portraits; it can affect hero icons, law icons, unit portrait SIDs, and recruitment/preview icon binders.

Do not assume `ckj` is the central sprite resolver in this playtest build. Runtime logs showed no useful `ckj` `Sprite(string)` resolver, and `ckj`-based patches can silently miss the visible UI.

`Homm3CustomUiIconHook` is the shared fallback layer. It is intentionally limited to custom key prefixes:

- `h3_*`
- `hero_homm3_stronghold_*`
- `homm3_stronghold_hero_*`
- `fraction_law_homm3_stronghold_*_icon`
- `homm3_stronghold_building_*`
- `homm3_stronghold_city_icon`, `homm3_stronghold_city`, `fraction_homm3_stronghold`
- Dungeon subclass icon keys used by Stronghold hero classes:
  `sub_class_dungeon_might_1_icon`, `sub_class_dungeon_might_2_icon`,
  `sub_class_dungeon_magic_1_icon`, `sub_class_dungeon_magic_2_icon`
- Stronghold custom ability donor icon keys:
  `pet_blood_icon`, `magic_sharp_edge_effect_icon`, `minos_buff_icon`,
  `assassin_buff_icon`, `primal_1_magic_thunderbolt`, `dragon_hunter_blood_icon`,
  `crossbowman_buff_icon`, `sub_skill_units_attackPen_icon`

The hook patches string-to-`Sprite`/`Texture` resolver methods in Hex assemblies, but returns `true` immediately for non-custom keys. It also patches known city recruitment ability surfaces (`BhHireUnitAbilityItemView` and `BhHireUnitAbilityView`) and logs bounded diagnostics with the icon key, view type, image name, current sprite, and override sprite. For battle action-bar unit buttons (`BhUnitAbilityView.bdpz`), it now prefers the native `viewBase.pics` image list for donor sprites; the older `HOMM3_BATTLE_ABILITY_ICON` overlay remains only as a fallback when that native list is unavailable.

For `Hex.UI.City.BhHireUnitItemView`, do not replace the first child image directly. Runtime logs showed that image is often `UNIT HIRE FRAME`; replacing it produced black-looking hire visuals. The hook creates a `HOMM3_HIRE_UNIT_PORTRAIT` overlay instead, using the frame `RectTransform` as a fallback parent if the view component is not directly on a UI transform.
For the full release, `BhHireUnitItemView.UpdateView(string)` is the larger hire-card path and must preserve the custom `h3_*` SID. Do not reintroduce the old donor SID prefix; June 24 runtime proof showed it creates donor ability wrappers and stale hover/tab payloads. Use explicit donor mesh/view data where native visuals need donor-compatible assets. The small main-town recruitment strip is a different surface: `BhCitySpecialView` owns `items`, `itemsLow4`, `itemsLow3`, and current `bzfy`, each containing `BhCityHireIncrementItemView` rows with a `pic` image. Current release `BhCityHireIncrementItemView.tyj(Sprite,string,int,bool)` carries the SID/label key and index; `tyk(Sprite)` is a later compact/rollup sprite refresh, and `tyl(bool)` is not a sprite setter. Store the resolved SID from `tyj` by item view so rollup refreshes can reuse it. `BhTooltipUnitsView.tkx(dvw,int)` owns another `unitViews` list for hover/pop selection art. Do not expect the `HOMM3_HIRE_UNIT_PORTRAIT` overlay to affect these small icons.
User testing confirmed `0.1.203` fixes the full recruitment screen and recruitment card art. The full recruitment screen still shows Dungeon donor models behind the animated HoMM3 sprites; that is a model/preview-layer suppression task, not evidence that the recruitment icon binders are still wrong.

The subclass and ability-donor cases are deliberately narrow: live Stronghold JSON already points at vanilla icon keys, so the hook scans loaded Unity sprites for only those known keys. Do not broaden this into arbitrary vanilla key replacement without a specific failing surface.

Stronghold custom ability art needs both pieces: `generate_homm3_stronghold_city.py` must write explicit donor `AbilityViewConfig.icon` keys, and `Homm3CustomUiIconHook` must allow those exact vanilla keys through `TryFindLoadedSprite`. Runtime logs can show `icon=primal_1_magic_thunderbolt` while the UI still shows the orange placeholder if the donor key is not in this allowlist.

Stronghold building-tree portraits use custom `homm3_stronghold_building_<BuildSid>_level_<N>` keys generated into `DB/objects_logic/cities/homm3_stronghold_city.json`. `Homm3StrongholdBuildingIconSpriteCache` maps those keys to existing Stronghold town layer PNGs under `homm3_runtime_assets/town_scene_refs/homm3_stronghold/layers/`.

The large oval hover art in the town build menu is a separate tooltip surface, `Hex.UI.BhTooltipBuilding`. Do not expect the generic string resolver to cover it. Playtest builds used `BhTooltipBuilding.spi(ezx, duv, int)` and `spj(BhBuildingView, duv, int)`. The current full release uses `BhTooltipBuilding.syn(fbi,dvw,int)` and `syo(BhBuildingView,dvw,int,Action)`. `Homm3CustomUiIconHook` gates on the current city fraction being `homm3_stronghold`, builds the same `homm3_stronghold_building_<BuildSid>_level_<N>` key from release `dvw.cnou` / `zzb()` and `dvw.cnov` / `zzc()` plus the tooltip level argument, falls back through `dvw.cdtb` / `<cdtb>k__BackingField`, and writes the sprite into `buildingBp`. `dvw.cdtc` is the city wrapper in the May 5 release interop, not the building data.

May 2026 Steam hotfix warning: `BhBuildingView.tot(fbj,dvw,int)` is still the specific build-tree bind point, but later no-arg refreshes can overwrite dwelling icons if they re-resolve from the wrong view member. Prefer the live `BhBuildingView.bzar` string SID and remember the resolved `homm3_stronghold_building_<BuildSid>_level_<N>` per `BhBuildingView` instance. Do not use the working hover oval art as proof that the row icon resolver is using the same building model.

Stronghold city/map buttons use `homm3_stronghold_city_icon`, resolved by `Homm3StrongholdCityIconSpriteCache` from `homm3_runtime_assets/map_object_refs/homm3_stronghold_city/avcstrc0.dir/00_00.png`. The cache also accepts `homm3_stronghold_city` and `fraction_homm3_stronghold` in case a HUD surface binds by city/fraction SID instead of the explicit icon key. The world-map city button specifically uses `Hex.Session.Hud.BhCityUIElement`; logs showed the visible orange placeholder is child image `Pic` with sprite `WIP`, so the hook sweeps live `BhCityUIElement` objects after the Stronghold city key is resolved and replaces `Pic`/placeholder children directly.
Do not set the city HUD `Pic` image to `raycastTarget=false`: runtime testing showed `Pic` is also the button's required hit graphic, and disabling raycasts removes the clickable area. Also do not set decorative placeholder/fallback children to `raycastTarget=true`; on the Steam release right-side adventure HUD this makes the visible HoMM3 city/building icon intercept clicks while the original blank hit area behind it remains clickable. Only the actual `Pic`/`cityIcon` hit image should receive raycasts. The HoMM3 city art currently gets a one-time `RectTransform.anchoredPosition += (-3, 3)` nudge because the raw replacement sat slightly down/right in the circular HUD frame.

Expected useful log lines:

- `Homm3CustomUiIcon: supplied Sprite/Texture for key=...`
- `Homm3CustomUiIcon: surface replaced [...] key=...`
- `Homm3CustomUiIcon diag: ability [...] key=...`
- `Homm3CustomUiIcon: loaded vanilla sprite fallback key='sub_class_dungeon_...'`
- `Homm3CustomUiIcon: loaded vanilla sprite fallback key='primal_1_magic_thunderbolt'` or another allowlisted ability donor key
- `Homm3CustomUiIcon: building tooltip replaced source=Hex.UI.BhTooltipBuilding.syn key='homm3_stronghold_building_...'`

If placeholders persist while these replacement lines appear, the visible image is probably being overwritten later or is owned by a different UI surface. If only diagnostic lines appear with vanilla donor keys, the placeholder is not from a missing custom key and the next step is to inspect that surface's later sprite assignment or model/preview texture path.

Hero preview portrait polish is asset-side: `homm3_hero_portraits/*.png` are generated as 64x64 circular-alpha PNGs, and `Homm3HeroPortraitHook` assigns them without adding a runtime `Outline`. Do not reintroduce the border workaround unless the circular-alpha assets regress.
