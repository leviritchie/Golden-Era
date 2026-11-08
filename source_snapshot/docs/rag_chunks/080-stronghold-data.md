# RAG Chunk: olden-era-playtest/080-stronghold-data

Stronghold main IDs: `homm3_stronghold` and `homm3_stronghold_city`.

Generators: `generate_homm3_stronghold_city.py`, `generate_homm3_stronghold_heroes.py`. Checker: `verify_homm3_stronghold_core_parity.py`.

Dungeon donor mapping: `trogl` -> `h3_goblin`, `assassin` -> `h3_wolf_rider`, `blade_dancer` -> `h3_orc`, `minos` -> `h3_ogre`, `medusa` -> `h3_roc`, `hydra` -> `h3_cyclops`, `black_dragon` -> `h3_behemoth`, with `_upg` and `_upg_alt` variants.

Do not patch only units. Stronghold depends on squads, heroes, subclasses, barracks, map object registrations, RMG presets, localization, UI aliasing, and presentation hooks.

Stronghold dwelling upgrade costs combine HoMM3 resource/gold costs with Olden Era's standard alchemical dust ladder on level-2 dwelling rows only: T1 10, T2 20, T3 30, T4 40, T5 50, T6 75, T7 100. Keep `generate_homm3_stronghold_city.py` and `verify_homm3_stronghold_core_parity.py` in sync when changing those costs.

Localization placeholders: visible `{0}` / `{1}` in Stronghold text means the matching `Lang/args/*.json` `tokensArgs` row is missing or too short. Use `generate_homm3_stronghold_city.py --lang-only` to repair all locales. May 2026: `h3_ogre_moral_selfbuff_description` needed an explicit `H3_UNIT_BUFF_ARG_OVERRIDES` row because the Dungeon donor `minos_moral_selfbuff_description` has no `unitsBuff` args row. A structural audit found no literal `[0]` placeholder-like tokens in Stronghold `Lang/*/texts`; capture the exact UI surface if square-bracket numbers appear in game.

Hero descriptions: `homm3_stronghold_hero_*_raw_spec_description` and `_raw_raw_spec_description` are cloned Dungeon donor aliases and can show raw `{0}` placeholders even when the main `_spec_description` override is clean. Use `generate_homm3_stronghold_heroes.py --lang-only` to refresh these aliases to the static Stronghold override text without rewriting `Core.zip`.
