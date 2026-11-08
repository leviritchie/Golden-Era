# Il2CppDumper outputs (Golden Era)

Do **not** keep a permanent `tools/il2cpp_out_live/` folder. Obfuscated type names are **reused** across hotfixes (`ezg` has meant map-squad visual, ambient sound, and other classes in different builds). A month-old dump will mislead symbol work and break Harmony registration.

## Source of truth

Dump **only** from the mod's Golden Era Steam install (the same tree used for `dotnet build -p:GameRoot=...` and BepInEx deploy):

```text
V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\
  GameAssembly.dll
  HeroesOldenEra_Data\il2cpp_data\Metadata\global-metadata.dat
```

Do **not** use a generic Olden Era / playtest / repo junction path unless you have verified it is this exact install and build id.

## Regenerate (dated folder)

1. Run [Il2CppDumper](https://github.com/Perfare/Il2CppDumper) on `GameAssembly.dll` + `global-metadata.dat` from the path above.
2. Write output to a **dated** folder, e.g. `tools/il2cpp_out_20260602_golden_era/`.
3. Record in your commit/notes: Steam build date, `GameAssembly.dll` size/hash if useful, and plugin version tested.
4. Point all scripts at that folder explicitly — never assume a fixed `il2cpp_out_live` path exists.

Example verify pass:

```powershell
python tools/verify_patch_surfaces.py tools/il2cpp_out_20260602_golden_era/dump.cs --source "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod" --no-probes
```

## Remap after hotfix

Keep the **previous** dated Golden Era dump as `OLD` and the **new** dump as `NEW`:

```powershell
python tools/remap_game_symbols.py tools/il2cpp_out_<OLD>_golden_era/dump.cs tools/il2cpp_out_<NEW>_golden_era/dump.cs --json-out tools/game_symbols_remap_<NEW>_report.json
```

Same-name obfuscated matches are **not** proof — confirm parameter types, return types, and owning type semantics before updating `GameSymbols.cs`.

## Repo policy

- Il2CppDumper outputs are **local / optional commit** artifacts; prefer not committing multi‑MB `dump.cs` unless the team explicitly wants a pinned reference dump.
- **Removed:** `tools/il2cpp_out_live/` (May 10, 2026) — stale; caused map-squad hook work to target wrong `ezg` methods.
- **Pinned symbol card (small):** `tools/golden_era_map_squad_visual_symbols.json` — map-squad controller is `ezn`, not `ezg`.
