# Building pass: integration to-do (coordinator)

**Update 2026-11-22: integrated, committed (8fb513c220) and installed (GE Core adf3aefa, DLL 1e9cfa76). Untested in game. Open: scene catalog keys for Build_Grotto and Build_Factory_Loan_Bank (catalogs held another session's edits); the law pass's stale law validators.**

Original state: all of this was uncommitted in the main checkout.
- **Done:** the tree, applier, shared runtime, SFC and CRT agents. Their hand-backs are `build_*.md` in this folder.
- **Still running when this was written:** IND (`build_ind.md`) and CFB (`build_cfb.md`). Check that their hand-backs exist.

## Steps

1. **`Plugin.cs` registrations.** `TryRegister(_harmony, Log)` unless noted otherwise.
   - Runtime: `Homm3TownSiegeDefenseRuntime` and `Homm3StrongholdEscapeTunnelRuntime`, after `Homm3BulwarkRunesRuntime.TryRegister` (about line 1103).
   - SFC: `Homm3TownBuildingWindowKit.TryRegister(Log)`, next to the Captives/Logistics registrations.
   - CRT: `Homm3CastleStablesRuntime`, `Homm3CastleSignalBeaconRuntime`, `Homm3RampartWeeklyIncomeRuntime` and `Homm3TowerLibraryRuntime`. They must come after `Homm3SwashbucklerGoldHook.RegisterRequiredReleaseSafeSlice` (about line 772).
   - IND: `Homm3InfernoCastleGateRuntime`, `Homm3NecropolisCoverOfDarknessRuntime` and `Homm3DungeonManaVortexRuntime`. IND also needs a Core side-buff row `homm3_ind_town_building_store`: a clone of `heros_crypt_debuff_none` with `hidden:true` and `bonuses:[]`, built like `make_homm3_cove_treasure_store_side_buff_row`. Mana Vortex needs it.
   - CFB (done; details in `build_cfb.md`):
     - Registrations:
       - after about line 1079: `Homm3FactoryLoanBankRuntime`, `Homm3FactoryManaGeneratorRuntime`, `Homm3FactoryLightningRodRuntime`;
       - near 1081: `Homm3CoveLodestarRuntime`;
       - after 1083: `Homm3CoveGrottoRuntime`;
       - the Fair and the Altar need none.
     - GameSymbols needs the `CoveLodestar` partial (snippet in the hand-back). Without it the Lodestar won't compile.
     - Re-run the construction category generator once the Bank rows from the other groups land. Cove gunpowder was moved to `Build_Tier_3` by hand.
   - The symbol-literal confinement check fails on the Escape Tunnel, Freelancers Guild and TownSiegeDefense files. Move their obfuscated names into GameSymbols.
   - csproj: add the new files if it doesn't use a wildcard.
2. **Core rows (CRT):**
   - heroes_buffs `homm3_signal_beacon_buff`: a clone of `stable_buff` with `movementPerBonus 0.10`;
   - logic_side_buffs `homm3_rampart_income_store`: hidden, no bonuses, made the way the Cove treasure store row is.

   Do not ship the weekly income without the store row.
3. **Metadata.** In `apply_release_core_overlay.py`, run `stamp_city_building_source_mechanics_metadata` again after the building-overrides call, so new rows carry their `source_mechanics` stamp.
4. **Validators:**
   - The Necropolis converter check (`converter_errors` in `validate_homm3_city_building_descriptions_contract.py`) has to accept the Skeleton Transformer from IND.
   - The mechanics check already skips sids that an override owns (done).
5. **Translations.** Add `nameTextLocales` and `descriptionTextLocales` (15 locales) to every override row. The renamed and new rows are listed in each `build_*.md`. Reuse `V:/olden_port_work/l10n_331/BRIEF.md` and `glossary.json`.
6. **Checks and install:**
   - `python tools/release_port/apply_release_core_overlay.py --check-building-overrides`;
   - compile the plugin once;
   - build the Core overlay;
   - run the validators, including `validate_homm3_city_building_tree_contract.py`;
   - install into GE after backing up the Core and the DLL, and only if the game is closed;
   - add a row to `docs/ingame_check_queue.md`;
   - commit only these paths.
7. **Scene art.** New SIDs need 3D town catalog keys; the keys are listed in the hand-backs. The catalogs have uncommitted edits from another session, so coordinate before editing them.
