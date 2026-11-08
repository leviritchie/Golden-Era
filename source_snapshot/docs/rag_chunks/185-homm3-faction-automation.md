# RAG_CHUNK: olden-era-playtest/homm3-faction-automation

## HoMM3 Faction Automation Investigation

Stable note: full investigation is in `docs/homm3_faction_automation_investigation.md`.
First-pass placeholder design principles are in `docs/homm3_ai_first_pass_design_principles.md`.
Per-faction editable plans, including HotA Cove, are in `docs/homm3_faction_plans/`.

Stronghold is close enough to use as the template for other HoMM3 factions. Code-path review shows roughly 70-80% of the mechanical work can be automated after adding a faction manifest:

- Core.zip scaffolding: fraction/city/laws/squads/heroes/map registrations/quickgame/localization rows.
- Unit logic/view row cloning and donor remapping.
- HoMM3 creature DEF/audio extraction through `tools/homm3_import/`.
- AssetBundle project scaffolding and `authoring.json` stubs.
- `homm3_units_manifest.json` and `homm3_import.json` generation.
- Release Core overlay rows.
- Basic Custom Game registration and icon/portrait registry entries.

Manual release-quality work remains significant:

- choose OE donor faction/unit mappings for every HoMM3 unit tier/base/upgrade/alternate;
- use HotA balance values over vanilla Complete values when HotA has entries;
- convert probability-based effects into focus-point abilities;
- give every `_upg_alt` at least one passive or active ability differentiator;
- tune stats, growth, costs, projectiles, AI role, and unit abilities;
- statically trace native-heavy mechanics before adding runtime probes;
- map HoMM3 town DEF/building layers to OE building SIDs and hand-tune `positions.json`;
- design faction laws, building graph, Mage Guild caps, hero specialties, skills, starting armies, and localization;
- generalize Stronghold-specific runtime code and revalidate release UI/hook surfaces after Steam hotfixes;
- trace external dwelling/RMG/random-hire behavior beyond visual aliases.

Stronghold-specific code that should not be blindly copied per faction:

- `StrongholdUnitSidMapping.cs` should become a data-driven donor alias registry.
- `ReleaseCustomGameUiProbe.cs` production path should append configured custom factions, not only `homm3_stronghold`.
- `Homm3StrongholdTownLayers.cs` should become a generic layer loader with faction data.
- Stronghold town extraction scripts are templates, but each town needs manual DEF-to-building SID mapping and placement.
- Hero portrait/class hooks need generated hero/class registries.

Expected effort:

- First additional faction: 1-2 days for scaffold plus about 3-7 days for manual faction-quality work, assuming local assets are available and release hooks do not drift again.
- Later factions after manifest/runtime-registry refactor: less than 1 day for scaffold, then about 1-3 days manual polish depending on mechanics and town art.

Risk by faction:

- Lower/moderate: Castle, Rampart.
- Moderate/high: Dungeon, Fortress.
- High: Tower, Inferno, Necropolis, Conflux, Cove.

If HotA/Cove is included, treat it as a separate asset-source lane; HoMM3 Complete `H3sprite.lod` does not cover Cove.
