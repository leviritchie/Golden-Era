# RAG Chunk: olden-era-playtest/070-core-data

`Core.zip` contains game JSON data under `DB/**`. Custom factions need many coordinated rows, not just a fraction file.

For `homm3_stronghold`, required areas include fractions, laws, `DB/data.json`, city config, map interactables, map/city audio, barracks hires, squads under `DB/squads/squads_homm3_stronghold/**`, heroes, subclasses, hero skills, unit info scripts, localization, and M2/M10 building preset rows.

Custom faction UI root cause: `BhHUDSession` resolves serialized `FractionLobbyAsset` data through `SoFractions.pqu(string)`. Runtime JSON faction IDs are not in that Unity asset. The fix is to alias `homm3_stronghold`, `homm3_fortress`, and `dungeon_raw` to `dungeon` for UI asset lookup only. Stronghold now clones the Dungeon result and replaces only `icon`/`bigIcon` with `homm3_runtime_assets/faction_icons/homm3_stronghold/Stronghold_H6_banner.png`; JSON-only faction icon edits do not affect that serialized UI path.

Do not use `Hero by id -1 not found` alone as pass/fail; it appears in vanilla controls.
