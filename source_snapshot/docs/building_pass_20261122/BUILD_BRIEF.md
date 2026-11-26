# Building pass build brief (2026-11-22)

The spec is the per-faction drafts (`<faction>.md`) plus `REVIEW.md`. Where they disagree, REVIEW wins, and the owner answers below override both.

## Owner answers (2026-11-22), binding

1. **Escape Tunnel comes with the Stronghold Fort (Wall L1).** It is not a new building.
2. **Build the three window buildings now:**
   - Stronghold Freelancer's Guild (sell creatures);
   - Conflux Magic University (buy one of the 4 school skills);
   - Cove Grotto (trade creatures or artifacts for experience).
3. **Grails keep their current extras and add the HoMM3 special on top.** Examples:
   - Aurora Borealis keeps +1 growth in all cities and adds every spell;
   - the Stronghold grail keeps its fog reveal and adds +20 Attack in sieges;
   - Colossus keeps its resources and adds +2 Morale for all heroes.

   Grail text lists both.

## Work split: one owner per file

| Agent | Owns (only these files) |
|---|---|
| **applier** | A new `tools/release_port/homm3_city_building_overrides.py` and its call site in `tools/release_port/apply_release_core_overlay.py`. The call goes in each `homm3_*_city` normalizer, before `apply_homm3_city_building_tree`. It also owns the description hook in `tools/release_port/homm3_city_building_descriptions.py`, so that an explicit `descriptionText` wins over the computed text. |
| **tree** | `tools/release_port/homm3_city_building_tree.py`, its validator(s) and `docs/homm3_city_building_tree.md`: every tree change in every draft, plus table entries for every new SID. It runs the layout solver for all 12 towns. |
| **runtime** | New `Homm3TownBuildingReader.cs`, `Homm3TownSiegeDefenseRuntime.cs` and `Homm3StrongholdEscapeTunnelRuntime.cs`. The siege runtime implements all ten siege-defender entries in REVIEW §1, each for the town that has the building. |
| **faction groups** (CRT, IND, SFC, CFB) | `custom_factions/building_overrides/homm3_<f>.json` (new), `custom_factions/source_mechanics/homm3_<f>.json`, and new per-building plugin files `Homm3<Faction><Building>Runtime.cs` / `...Window.cs`. |

Shared files nobody edits; put the needed change in your hand-back note instead:
- `Plugin.cs`
- the csproj
- other agents' files
- the town scene catalogs (`homm3_town_scene_meshes/**/catalog.json` have uncommitted edits from another session)
- localization JSONs

## Reader API (runtime agent implements exactly this; everyone codes against it)

```csharp
public static class Homm3TownBuildingReader {
    // city: a native city/town object (BhCity / CityData as the construction adapter sees it)
    public static int CityBuildingLevel(object city, string buildingSid);          // 0 = not built
    public static bool CityHasBuilding(object city, string buildingSid, int level = 1);
    // owner: a data side, a battle side or a hero (anything Homm3CustomFactionLawRuntime resolves)
    public static int SideBuildingCount(object owner, string buildingSid, string citySid = null); // towns owning it
    public static bool SideHasBuilding(object owner, string buildingSid, string citySid = null);
    public static System.Collections.Generic.IEnumerable<object> SideCities(object owner);
    public static bool TryGetBesiegedCity(object battleLogicOrState, out object city);  // null when not a siege
}
```

- Every call runs on the main thread only and fails closed (0, false or empty) on any read error.
- Cache per day where you can.
- Put the city identity (`id`, for example `homm3_castle_city`) behind `citySid`.

## Override JSON schema (`custom_factions/building_overrides/homm3_<f>.json`)

```json
{
  "factionSid": "homm3_castle",
  "rows": [
    {
      "sid": "Build_Stables",
      "section": "heroBonusBanks",
      "template": "human_city:Build_Mother_Nature",
      "replace": false,
      "sceneSlot": "Stables",
      "costs": [{"gold": 2000, "wood": 10}],
      "fields": {},
      "bonuses": [[]],
      "nameText": "Stables",
      "descriptionText": "Visiting heroes gain +20% movement until the end of the week.",
      "narrativeText": "…",
      "iconFrom": "self:Build_Bank",
      "plugin": "Homm3CastleStablesRuntime",
      "notes": "building pass 2026-11-22: castle.stables"
    }
  ],
  "remove": ["Build_Lyceum"]
}
```

Field meanings:
- `template`: a vanilla row (`<vanilla city id>:<sid>`) or one of this town's rows (`self:<sid>`). The row is deep-copied, then given the new `sid`, `section` and fields.
- `replace: true`: edit the existing row in place (same `sid`), keeping its icons, scene slot and names unless given.
- `costs`: one entry per level.
- `fields`: section-specific fields set as-is, for example `resArr`, `levelStep`, `conversionPairs`, `usageLimit`, `viewRadius`, `sideBonuses`, `cityBonuses`.
- `bonuses`: per level, native bonus dicts. They go into the row the way the section's native rows carry them; the applier checks `NATIVE_CITY_BUILDING_BONUS_TYPES`.
- `descriptionText`: omit it to keep the computed vanilla description. Plugin-only effects must give it.
- `iconFrom`: the icon source.
- `plugin`: documentation only.
- `notes`: says which mechanic the row implements.

Prerequisites and `nodePos` belong to the tree agent, not this file. Literal numbers in text must equal the data.

## Applier duties

1. Load every `building_overrides/homm3_*.json`. Validate it fail-closed:
   - the section exists in the IL2CPP city schema;
   - the template exists;
   - bonus types are allowed for the section;
   - a cost exists for every level.
2. Remove the rows listed under `remove`. Add or replace rows. Generate text keys the way `generic_building_text_key` does, and write the English text to the Lang overlay the same way existing custom city text is written.
3. Make sure `source_mechanics` `currentRows` retention keeps the new rows, so the Castle-slot stripping and the Mage Guild caps leave them alone.
4. The description generator uses `descriptionText` when present.
5. Add a dry-run check to the overlay path: `python tools/release_port/apply_release_core_overlay.py --help` shows the flags. Report how you verified.

## Faction group duties

1. Write the override JSON for every changed special in your drafts and in REVIEW §1–2:
   - the restored Bank;
   - new rows;
   - grails, keeping their extras (answer 3);
   - renames.
2. For each plugin building, write its runtime file using the reader API. Hook points are as in your draft. Re-read the current game symbols in the decompile or interop, because the drafts cite a May decompile.
   - Weekly and daily effects must pay exactly once, including across save and load: use the plugin save-state pattern the Factory logistics runtime uses.
   - Window buildings: model them on the War Captives window (`Homm3DungeonCaptives*`) and open them from the building click the way existing custom building UIs do. If the click route is unproven, add a town-screen button.
3. Update `source_mechanics`: `exact`, or `substituted` with an honest reason, and correct `currentRows`.
4. **Scene art:** for each new SID, name the 3D scene catalog key or HoMM3 town building it should map to. Put it in the hand-back; do not edit the catalogs.

## Everyone

- Do not run `dotnet build` (the coordinator compiles once) or the release overlay over the GE install.
- Never launch or kill the game; never write to the GE install. No git commits, stash, reset or checkout: the index is shared.
- No recursive scans of `V:`, `F:` or iCloud.
- "No donor limit": if a lever turns out impossible, build the closest real version and say so.
- Hand-back note: `docs/building_pass_20261122/build_<agent>.md`. Include:
  - files and lines changed;
  - the `Plugin.cs` registrations needed;
  - scene keys for new SIDs;
  - anything not built and why.
