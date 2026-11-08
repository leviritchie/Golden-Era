# RAG_CHUNK: olden-era-playtest/homm3-faction-planning-docs

## HoMM3 Faction Planning Documents

Editable first-pass plans for the non-Stronghold HoMM3 and HotA factions live in `docs/homm3_faction_plans/`.

Files:

- `castle.md`: Human donor; Knight/Cleric; morale, archery, cavalry, angels. Low-medium risk.
- `rampart.md`: Nature donor; Ranger/Druid; luck, resistance, growth, dragons. Medium risk.
- `tower.md`: Human city plus mixed donors; Alchemist/Wizard; constructs, ranged magic, Titan. High risk.
- `inferno.md`: Demon donor; Demoniac/Heretic; fire, gating, sacrifice, Devils. High risk.
- `necropolis.md`: Undead donor; Death Knight/Necromancer; skeleton economy, drain, liches, dragons. High risk.
- `dungeon.md`: Dungeon donor but custom SID `homm3_dungeon`; Overlord/Warlock; subterranean control and dragons. Medium-high risk.
- `fortress.md`: Nature city plus mixed donors; Beastmaster/Witch; swamp defense, poison, petrify, hydras. Medium-high risk.
- `conflux.md`: Nature plus mixed elemental donors; Planeswalker/Elementalist; elemental immunities, magic access, Phoenix. High risk.
- `cove.md`: HotA-only asset lane; Captain/Navigator; pirate shooters, Cannon flavor, Nix, Haspid. High risk.

Unique faction skill recommendation summary:

- Castle: OE native `Righteousness` / `skill_faction_humans`; reuse the Humans native death/kill-triggered temporary hero attribute stacking. Verify Castle heroes/classes can reference it cleanly.
- Rampart: `Harmony`; first pass should use passive luck/resistance/native-terrain bonuses. Reactive aura UI is static-trace.
- Tower: `Artifice`; constructs gain Attack from hero Spell Power and Defense from hero Knowledge at 20/40/60% effectiveness by rank. Define the construct set before generation.
- Inferno: `Gating`; active summon places Imps on a target hex based on army strength, using the native Hive larvae-egg summon flow as donor. Trace that path before adapting.
- Necropolis: OE native `Necromancy` / `skill_faction_undead`; reuse post-battle undead HP conversion. Native Necromancy currently works on vanilla undead, so HoMM3 undead may need eligibility adjustment.
- Dungeon: OE native `Triumvirate's Strength` / `skill_faction_dungeon`; reuse vanilla Dungeon stance buttons/rank scaling. Verify `homm3_dungeon` faction/unit filters for subskills.
- Fortress: `Swamp Tactics`; enemy units suffer -1 Initiative at rank 1, -1 Initiative/-1 Speed at rank 2, and -2 Initiative/-1 Speed at rank 3.
- Conflux: `Summon Elementals`; active summon creates rank-dependent elemental types, with quantity based on hero Spell Power. Trace/reuse a safe summon path first.
- Cove: `Cannoneering`; Heroic Strike becomes a Cannon blast with adjacent splash at 20/40/60% by rank. Import the HoMM3/HotA Cannon sprite through the Cove asset lane.

Shared rules:

- Use `docs/homm3_ai_first_pass_design_principles.md`.
- Use status values `exact`, `approximation`, `donor_backed`, `visual_placeholder`, `manual_design_required`, and `static_trace_required`.
- Treat `_upg_alt` as an editable Olden Era alternate upgrade proposal.
- Use Horn of the Abyss balance values over vanilla Complete values when HotA has an entry.
- Convert probability-based HoMM3 or Tears of Ashan effects into focus-point abilities.
- Every `_upg_alt` row must have at least one passive or active ability differentiator; pure stat changes are not enough.
- Preserve OE economy conventions, including the Stronghold dust ladder T1..T7 = 10,20,30,40,50,75,100.
- Do not claim unsupported HoMM3 mechanics in text.
- Town layer maps and `positions.json` rows are always manual review.
- Native-heavy mechanics require static donor tracing before runtime hooks.
- Cove requires a local HotA asset-source lane; HoMM3 Complete `H3sprite.lod` is insufficient.
