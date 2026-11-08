# RAG Chunk: olden-era-playtest/090-ability-mechanics

Olden Era supports many mechanics but not arbitrary custom JSON schema. Unsupported invented passive shapes can NRE.

Data-layer Stronghold abilities already use donor patterns: Goblin Long Reach, Roc Wing Gust, Thunderbird Lightning Strike, Cyclops Boulder Throw, Cyclops Petrification, and Behemoth Rampage.

Confirmed mechanics include melee/ranged attacks, alternate attacks, flying, blink, push, AoE, DoT, stun/petrify, buff objects, morale/luck auras, defense piercing, reflection, and some trigger-like patterns.

C# likely required: Wolf Pack, Fear Aura, Bloodlust, Battle Cry, Howl, Blood Rage, Orc Rage, Static Field, low-HP triggers, and unit siege targeting.

Display strings do not implement mechanics.

Hero specialization strings have the same limitation. `generate_homm3_stronghold_heroes.py` currently clones Dungeon `bonuses` arrays and only remaps SIDs, so `homm3_stronghold_hero_*_spec_description` can drift from mechanics. Check `DB/heroes_specializations/specializations_homm3_stronghold.json`; see `docs/homm3_stronghold_hero_ability_mechanics.md`.
