# Law pass build brief (per faction)

You build the approved law trees for your factions: the data, plus the plugin hooks for the unique-skill laws. Read first:
- `REVIEW.md`: section 2 (cross-faction changes to the drafts), section 3 (decisions) and section 4 with the owner answers below.
- Your factions' drafts (`<faction>.md`).
- `BRIEF.md` (toolkit).

The drafts plus REVIEW are the spec.

## Owner answers (2026-11-21), binding

1. **Stronghold Elite Orcs.** Shots do NOT raise the Warcry: the Warcry subskill already does that. The rider becomes +3/+6 Attack, so Stronghold has 4 (S) laws.
2. **Skill-widening laws.** Build Castle Grand Strategem and Necropolis Unearthed Graves.
   - Lords of the Dead (Necropolis) and Crew Ashore (Cove) are rejected: they are irrelevant in **single hero mode, the most popular mode**. Replace each with an (S) law on the same skill that matters to one hero. Every law you build must pass that test.
   - Cove Letters of Marque (hero hiring discount) fails the test too. Replace it with Privateers' Pact: neutral creatures are +25%/+50% more willing to join (`heroStatMap diplomacyEfficiencyPerBonus`, as Rampart's Sylvan Diplomacy).
   - Suggested replacements; pick better ones if you find them:
     - Necropolis r3 (S): Necromancy also raises from your own army's fallen creatures at the Basic share.
     - Cove r1 (S): each treasure map piece your hero collects also pays 250/500 Gold.
3. **Mixed-army Morale exemption.** Dungeon only (Many Races Below). Necropolis Legion Without Banner is replaced by Grave Chill: enemy creatures -1 Initiative, r2 A, native.
4. **Conflux Elemental Balance.** Native, with no composition condition: Conflux creatures deal +5% and take -5% Damage (`outAllDmgMod` / `inAllDmgMod` on Conflux receivers).

## What you write

### 1. `custom_factions/law_overrides/homm3_<f>.json`

You own this file. Rewrite it; keep the top-level shape.
- **`lawOverrides`** covers all 34 indices `fraction_law_homm3_<f>_<n>`.
  - Every law in your tree gets `enabled: true`, `nameText`, `descriptionText`, `parametersPerLevel` (`[{cost, bonuses:[...]}]`, the vanilla bonus shape as in `V:/olden_port_work/law_pass_20261121/core_laws/DB/fractions_laws/*.json`), `notes` ("law pass 2026-11-21: ...") and icon fields.
  - Every index not in the tree gets `{"enabled": false}`.
- **Icons.** The resolver is `custom_law_icon` in `tools/release_port/apply_release_core_overlay.py`. The tree validator `law_tree_problems` in `tools/release_port/custom_law_tree_layout.py` enforces:
  - an Elite or unit-line law uses `portraitIconSid` = a unit of that line;
  - other laws use `effectIconKey` = a vanilla law icon (`fraction_law_<vanilla>_<n>_icon`) whose vanilla law has the same effect role, or keep an existing shipped `homm4IconPath` + `iconKey` pair from the current file when the role still matches;
  - Resource Riches and Mining are resolved automatically.
- **`lawTree`** (new, top level) lists 5 ranks, each `{"kingdom": [indices], "army": [indices]}`.
  - 2-4 per column.
  - Resource Riches must be the FIRST kingdom entry of ranks 0, 2 and 4.
  - Kingdom-type bonuses (economy, hero, map) go in kingdom; creature bonuses go in army.
  - A law on a single unit line must sit inside its tier band (`UNIT_TIER_LINE_BAND` in `custom_law_tree_layout.py`).
  - Two laws with identical effects may not both be placed.
- **`lawRules`** (new, top level) holds the law-switched kit rules (C), one entry per law:
  ```json
  {"law": <index>, "rule": "<kind>", "name": "<law name>", "percent": [lvl1, lvl2], "cap": int or [per level],
   "receivers": "faction" | "all" | ["h3_unit", ...], ...rule params (fact/state/mode/side/attack/buffs/below...)}
  ```
  - Kinds and params are in `docs/unit_ability_pass_20261121/RUNTIME_CONTRACT.md`.
  - The law row itself still needs a `parametersPerLevel` with a cost per level. Give it a zero-strength native anchor bonus, e.g. `unitStat outAllDmgMod 0.0` on the receivers, so the law exists natively.
  - Validate with `python -c "import sys; sys.path.insert(0,'tools/release_port'); import build_unit_kit_runtime_table as b, homm3_unit_design_table as d; print(len(b.collect_law_rules(d.load_designs())))"`.
  - **Do not** run the generator itself (it writes a shared file).
- **`lawBuffs`** (new, top level) holds the law-granted buffs (B):
  ```json
  [{"id": "h3_law_<f>_<slug>", "cloneOf": "<core buff>", "set": {...}, "name": "...", "text": "..."}]
  ```
  - The law bonus is `{"type": "battleSubskillBonus", "parameters": ["unit_buff", "<id>"], "receivers": [...]}`.
  - Donor buffs live in the Core at `V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/HeroesOE_Data/StreamingAssets/Core.zip` under `DB/buffs/`. Read it with Python zipfile and never write to it.
- **Text.** Vanilla register: "Your heroes gain +1/+2/+3 Attack." Every number in the text must equal the data at each level. No implementation words (plugin, runtime, rule, Core).

### 2. Plugin hooks for every (S) law of type D

- Plugin sources: `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`.
- Read the rank with `Homm3CustomFactionLawRuntime.CustomLawRank(owner, lawIndex, "homm3_<f>")`. It returns 0 when the law is not taken, and 1, 2, ... for its level. `owner` is anything the law runtime resolves to the side's fraction laws: a data side, a battle side, or a hero's side object.
  - For a battle unit, get the owner from `Homm3BattleUnitLawOwnerRegistry.TryResolveDataSide(unit, out var dataSide)`.
  - On the map, look at what the skill runtime already uses to find the hero's side.
- Put each lever beside the constant or branch the draft names, with a short comment `// law pass 2026-11-21: <law name> (#<index>)`. Keep everything fail-closed: no law, or a read failure, means current behaviour.
- **Files you may edit:** your factions' skill runtime files (the ones the draft names) plus new files named `Homm3<Faction>LawHooks.cs` if you need them.
- **Shared files you must NOT edit:**
  - `Homm3CustomFactionLawRuntime.cs`
  - `Homm3UnitKit*.cs`
  - `Homm3CustomLawEffectProfiles.cs`
  - `Homm3CounterattackDoctrineMutationRuntime.cs`
  - `tools/release_port/*.py`
  - `Homm3UnitKitRules.g.cs`
  - anything outside your factions

  If you need a change there, describe it exactly in your hand-back note.
- Do NOT run `dotnet build` (other agents build in parallel, and the coordinator compiles once). Write code that matches the surrounding style and the APIs you can see in the files. Double-check signatures by reading them.

### 3. Hand-back note: `docs/faction_law_pass_20261121/build_<f>.md`

Short. Include:
- the final tree, if it differs from the draft;
- the plugin levers you added (file:line);
- the family indices your tree reuses for new effects (2, 6, 13, 15, 18, 19, 21, 22, 25, 27, 28, 33, 34): the coordinator retires those profiles;
- any shared-file changes you need;
- anything not built and why.

## Rules

- Never launch or kill the game. Never write to the GE install. No git commits, stash, reset or checkout: the git index is shared.
- No recursive scans of `V:`, `F:` or iCloud. Use known paths.
- Never shrink a design to fit a donor ("no donor limit"). If a draft lever turns out impossible, build the closest real version and say so.
