# Law-Tree Reassessment: 25672315

Status: bounded source/static investigation, including a Current-native follow-up, completed on 2026-10-04. No production law implementation, Core generation, plugin build/deploy, game launch, bridge activation, or gameplay test accompanied this report. The user owns gameplay testing; both optional diagnostic bridges remain disabled.

## Findings

The prior cloud research is useful, but its word "current" refers to the previous Golden executable, not the newly consolidated build. Its five authored law rows absent from the corresponding faction layouts survive in the 25672315 mirror and installed Core, while its aggregate counts have changed. These unreferenced authored rows are separate from the dormant custom-law rework; the layout check does not establish absence of every possible other consumer. Neither finding authorizes reactivating conditional law mutators.

Some original conditional designs remain recorded in historical source-mechanic/profile inputs; preservation of the complete original slate is not established. The active target contract was intentionally rewritten to native-data replacements. Better inspection and transaction tooling makes reassessment more practical; it does not by itself prove that the new engine supports the old conditions or that those conditions work in gameplay.

## Cloud Work Recovered

The private `leviritchie/golden_era` research run produced reports, not an evidenced law implementation branch or commit. It is separate from the public `leviritchie/Golden-Era` bug tracker.

- Cloud coordinator: [Set up golden_era](codex://threads/01a0f471-cebf-7037-99ff-3f42675c10fd).
- Authored-law archaeology and integration: [researcher A](codex://threads/01a0fa19-c6ae-7220-96d6-e894d79050dc), project doc 4 v3 and integrated doc 9 v4.
- Native consumer analysis: [researcher C](codex://threads/01a0fa1a-3579-705b-922d-24fe30d090ce), project doc 7 v3.
- Independent review: [researcher E](codex://threads/01a0fa1a-a76e-7199-a0e6-703f530550c7), project doc 3 v4; accepted the integrated report after corrections, with no material findings remaining.

Cloud artifacts are under `/workspace/olden-era-analysis/swarm-run.4rk3zrvq/reports/`: `researcher_a_stock.md`, its inventory script/JSON, `researcher_c_native_laws.md`, `capability-map.md`, and `reviewer_e.md`. These are cloud artifact locations, not files installed in this checkout. The recovered source snapshot head was `ce365e6571b6e9818ac593542704f4f5f4a27801`.

**Binary provenance:** cloud GameAssembly SHA-256 `d47706eb0ffedbda0ec07ede47abc778e6022ed820ae1a1fd23522d3acdb8416`; metadata `9b157fb01cf617c725e024718454c97fac173769fd162579d664456c26318e00`. This is legacy `GameBuildKind.Golden`. Cloud native names/RVAs, `DataFractionLaws.bfwt`, the five-line consumer constraint, and Frostbite's factory trace are historical leads, not Current-build body proof. The cloud Core was also modded; its reviewers explicitly left pristine stock provenance and runtime behavior unresolved.

## Current Data Comparison

Read-only comparison roots:

- Active install: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`.
- Named Current mirror: `V:\olden_mirrors\Heroes of Might and Magic Olden Era - Current Era 25672315`.

Root `GameAssembly.dll` hashes match: `d9972b0e7f7dd1c17758808e2f1b80e0a728946416d9a41deaa99bad744de53a`, the Current identity recorded in [current consolidation](current_version_consolidation.md). Selected executable, UnityPlayer and baselib hashes also matched. This is selected-file identity, not a whole-mirror pristine-stock certificate. Installed metadata SHA-256 is `f69dfc24ea549c35ec45518383ac8173d45b45f31404bbc25ad988b9e3608db7`; mirror metadata is `99117dc93f4b427967a2fca49378e1b39b3202401b15234a98328faa7d489817`. The port uses patched metadata, so an unequal hash alone is not evidence of corruption.

Core archive SHA-256:

- Mirror: `f11b90c19aae60908a4d503e639f2abf7a02c5d706cdb072879ef9773812d954`.
- Installed overlay: `87d1c9e35598ac41e0a1f031bf81283b7c46bf7285d4f69d1630e4a6bdc4365d`.

The six stock `DB/fractions_laws/fractions_laws_table_<faction>.json` entries and six `DB/fractions/<number>_<faction>.json` layouts are raw-byte identical between these two archives (12/12). Layout membership was joined through `fractionLawsLines[*].groups[*].laws[*]`, not inferred from naming gaps.

| Faction | Authored rows | Distinct layout references | Unreferenced authored IDs |
| --- | ---: | ---: | --- |
| human | 34 | 32 | `fraction_law_human_20`, `fraction_law_human_31` |
| undead | 34 | 32 | `fraction_law_undead_25`, `fraction_law_undead_33` |
| dungeon | 34 | 34 | None |
| nature | 31 | 31 | None |
| demon | 30 | 30 | None |
| unfrozen | 36 | 35 | `fraction_law_unfrozen_21` |
| Total | 199 | 194 | Five; zero missing layout references |

The cloud result was 198 authored / 193 referenced. Do not carry those totals into Current documentation. The five identities absent from the corresponding faction layouts still match, but disconnected rows are not evidence of a complete abandoned tree or its removal date/reason.

A second bounded comparison against `V:\olden_port_work\golden_era_legacy_rollback_20261004` corroborated the generation difference. Its binary/metadata hashes match the cloud D477 pair; its Core hash is `0986a509e801e35fd2b779b55769a9367852d8ed9e7aa5c741ac73c3a19fa110` (not asserted identical to the cloud's modded archive). Current adds exactly one authored ID and layout reference: `fraction_law_dungeon_34`, a cost-2 `heroStat manaBonus=15` row at Dungeon line index 1, first group, fourth SID. No IDs or references were removed in these selected tables/layouts. Also, 66 common table rows differ as parsed definitions (human 17, undead 9, dungeon 12, nature 4, demon 9, unfrozen 15); this is not a claim of 66 distinct new mechanics or a pristine vanilla-to-vanilla developer diff, since the rollback archive is modded. Several groups reorder or move laws: undead 29 moves from the count-30 to count-50 line; unfrozen 8 from count-30 to count-15, and unfrozen 29 from count-50 to count-30. Do not portray the law content as unchanged across generations merely because the five leftover IDs persist.

The retained effects are ranged outgoing/incoming modifiers (human 20), `energyPerRound` (human 31), `finalSummonBonusPercent` (undead 25), `crit` (undead 33), and `battleSubskillBonus` with `side_buff` (unfrozen 21 / Frostbite). The cloud found no locale for undead 33 and a multi-stage Frostbite side-buff chain; that localization/chain follow-through was not re-audited here. In particular, do not equate `crit` with `critChanceModifier` or assume a retained row is reachable in the playable tree.

The selected-entry Python audit read 24 entries across two archives in 0.090 s, sampled peak process working set 41.32 MiB. This was sequential ZIP I/O, JSON parsing and byte comparison; no GPU stage was relevant. No all-Core substring scan, new validator, or whole-tree validation was added.

## Original Custom Rework

Three different inputs must not be conflated:

1. [June 22 creative revision](custom_law_safe_creative_revision_recommendations_20260622.md): 40 accepted revisions with source/candidate-Core proof at that date. It removed unsafe trigger dependencies in favor of concrete native envelopes. Its historical status does not establish Current installation or gameplay.
2. `custom_factions/custom_law_targets.json`: post-June-21 active native-data target list. The generated [readiness backlog](custom_law_remaining_implementation_backlog.md) currently labels all 130 targets `native-exact-ready`; this means the current replacement target, not the original conditional design, and not runtime clearance.
3. `custom_factions/source_mechanics/homm3_*.json`, effect-plan inventory/profiles, and proposal/rethink docs: dormant original conditional intent. A profile name such as first-volley, mixed-elements, or native-formation does not turn the current passive row into that conditional mechanic. Some generated inventory rows are also stale: Castle law 13 still says Shield Wall / counterattack damage there, while the current target and override say Royal Retaliation / extra counterattack charge. Read active targets and overrides first; do not regenerate or change gameplay from that old inventory alone.

The current `custom_factions/custom_law_packet_proofs.json` still has all eight packet families at `gameplayAllowed=false`, but that ledger is **not the effective gate for six families**. The follow-up found `BruteForceSourcePreparedGameplay=true` in source and the installed DLL; committed-damage, counterattack, spell-cooldown, battle-action, reward-result and morale can return allowed before consulting the ledger. The dormant training-damage registrar has no ordinary startup call in the audited source or direct method-reference caller within the installed `OfflineUnlockMod.dll`; arbitrary dynamic/external calls and an already-running process are not ruled out. The bypass is pre-existing and was not changed by this investigation. [The ownership audit](../artifacts/law_tree_current_investigation_25672315/runtime_ownership/fortress_hidebound_ownership.md) separates these facts. [Activation packets](custom_law_surface_activation_packets.md) remain the intended proof contract, not evidence that the present implementation enforces it everywhere.

| Original enhancement | Why the safe revision avoided it | Evidence required before restoration |
| --- | --- | --- |
| Avenger marks | Fixed critical-chance/scouting donors avoid a mark predicate. | Exact mark SID and target identity, active law/rank, and the consuming action/damage path. |
| Corpse economy | Static economy/stat donors do not consume corpses. Visual losses are not a logical corpse ledger. | Eligibility, count, spend transaction, cleanup and visible result. |
| Gating identity | Passive donors avoid treating a visually spawned stack as a gated gameplay entity. | Native owner/SID, temporary lifetime and loss/despawn reason. |
| Plunder/reward | Recurring income avoids capture/result reward dispatch. | Committed reward identity, winner, active rank, and idempotent grant point. |
| Terrain predicates | Custom swamp/road triggers were excluded; native-terrain donors promise only their exact semantics. | Current tile/biome classification in the actual battle/law context. |
| Dynamic elemental composition | Fixed receiver lists avoid dominant/mixed-family counting. | Current unit/spell family classification and the exact composition consumer. |
| Warcry execution / cooldown | Passive cooldown pressure avoids an unproven custom-use trigger. | Real action owner, execution, cooldown owner and sibling sharing. |
| Cannon reload / first volley | Passive gunline bonuses avoid reload events and first-volley/Focus state. | Action classifier, first-volley lifetime, native unit identity and Focus transaction. |
| Friendly cooldown credit | Duration/passive effects avoid weakly proven negative cooldown rows and cast-gate drift. | Exact Current parser plus storage, cast gate, execution and UI synchronization. |
| Kill / debuff / isolation conditions | Passive damage/duration donors avoid event/geometry predicates. | Exact buff/target identity, geometry and damage/death ordering in one ownership path. |

The surviving docs establish these technical risk categories, not a single verified abandonment decision for every idea. Do not rewrite passive targets to conditional promises merely to match dormant profile names.

## Feasibility And Next Boundary

Current-specific `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/GameSymbolsCurrent.g.cs` declares build 25672315 / D997 scope at lines 15/19 and pins the native law API at lines 770-778 and 799-808: SID lookup, `CanApply(string,int)`, `Apply(string,int)`, cost/rank/line access and `DataFractionLaws` collection members. The initial pass established an inspectable API, not its bodies. The follow-up below adds bounded Current-native xrefs. `GameSymbols.cs` lines 5853-5875 and 5976-5981 retain diagnostic/runtime-pending qualifications; `Homm3CustomFactionLawRuntime.cs` lines 208-216 describe the resolver scaffold rather than gameplay law evaluation. Neither API pins nor native xrefs prove runtime ordering or the old conditional mechanics. The historical `bfwt` method is not a Current mapping.

Existing `Homm3CustomFactionLawRuntime` diagnostic parsing accepts custom factions only. General read-only stock-law inspection is a concrete tooling extension opportunity; it must not silently broaden its mutating route. No such extension was implemented or enabled here.

Recommended sequence for a separately authorized implementation lane:

1. Choose one original conditional design and state its exact behavior, rather than restoring a whole slate or silently substituting another passive law.
2. First search Current native donors and trace the exact Current law apply/bonus consumer. Keep native ownership if it expresses the behavior. The legacy five-line result is not Current authority; preserve existing tree shape until the relevant Current body is traced.
3. If the native envelope cannot express the design, prove a complete Direct State transaction and presentation path before promotion. Do not add a second damage/action owner or ungate all packets from metadata alone.
4. Use native bridge, then volatile bridge, then a general-purpose enhancement, then a diagnostic build in that order. Bridges are intentionally disabled after the user's hitch fix; restoring them requires a separate explicit testing decision, not this research report.
5. Two data-only control candidates with aligned active targets, overrides and data-only profiles are Castle Line Doctrine (laws 18/19, paired melee/ranged modifiers) and Chapel Calendar (law 33, daily Astrology points). First re-read their exact Current donor/payload shape. These controls would test the native battle and calendar paths, not restore conditional formation/reward behavior. Any installed pilot requiring the user's eyes belongs in `docs/ingame_check_queue.md`, not a parallel checklist here.

The initial pass prioritized adventure vision for a dynamic investigation because diagnostics and a handler/runtime path already exist in source. Its dormant profile, exact native reveal mutation and active-law ownership still require Current proof. The deeper donor and ownership comparison below now recommends Fortress Hidebound Drill as the first original conditional candidate. Neither is asserted Current-ready.

Highest new proof: source/static Current data/API comparison, bounded native xrefs, installed-byte gate inspection and recovered historical research. Full selected-evaluator dispatch, conditional runtime identity/ordering, costs/UI/save behavior, balance, performance under active diagnostics, and user-visible gameplay remain unproven. No law change is ready to deploy on the strength of this report alone.

Independent report review found two scope-wording issues (layout absence versus global inactivity, and partial versus complete preservation of original designs); both were corrected. The existing documentation contract passed in 1.249 s, and the scoped staged whitespace check passed. These checks are documentation/source hygiene, not law behavior proof.

## Current-Native Follow-Up

Evidence lives under [`artifacts/law_tree_current_investigation_25672315`](../artifacts/law_tree_current_investigation_25672315/). The extractor reads the hash-pinned D997 executable and 99117 clean-index metadata pair, maps PE sections, and records exact tokens/RVAs/bytes; it does not load the game or treat the patched metadata as a different executable.

| Current native identity | RVA | Bounded finding |
| --- | --- | --- |
| `FractionLaws.baom`, token 100698993 | `0x30C42F0` | Preflight/can-apply path. |
| `FractionLaws.baon`, token 100698994 | `0x30C4410` | Apply path calls `DataFractionLaw.LevelUp`, then the selected-rank refresh. |
| `dyy.baof`, token 100698969 | `0x30CF350` | Refresh iterates rank bonuses, calls bonus collection operations and marks applied state. |
| `dyy.baoe`, token 100698980 | `0x30CF080` | Per-rank builder calls the native BonusConfig factory. |
| `dux.zzi`, token 100698039 | `0x30AD140` | Bonus factory; separately pinned installed Hex enum literals identify sampled selectors 6/7/30 as UnitStat/UnitBoolStat/BattleSubskillBonus. This is not full switch or evaluator coverage. |

The selected UnitStat/effect follow-through still contains unresolved indirect dispatch. The enum labels came from the installed `Hex.dll` (SHA-256 `a535d47ef5e8c929ca7c4794d9ec596c8d40ddaad7fbdb1ae7a2b0c2c296d4d7`, MVID `33c88d2b-8215-4e5b-8b0e-2934afd97523`) in the F69-patched metadata install, not from the 99117 clean-index metadata. Only selectors 6/7/30 were separately decoded. Do not infer the actual negative-status law predicate, full switch coverage or BattleSubskillBonus gameplay from this call graph. These are Current-native observations, not a reuse of D477 RVAs and not runtime proof.

The reachable-trace extractor measured 1.255 s elapsed and 163,614,720 bytes peak process working set (Windows `peak_wset`) for 14 selected native methods. CPU-only PE/metadata I/O and sequential Capstone decoding were used; no GPU work, whole-binary regeneration or full interop audit was required. Its traces retain implicit conditional fall-through and are not a strict control-flow-graph partition. The initial linear decoder was rejected in review because it missed branches and decoded padding; it was replaced rather than retained as a fallback.

The best first **original conditional investigation candidate** is Fortress Hidebound Drill, `fraction_law_homm3_fortress_6`: the defending Fortress unit would take 10% less positive damage when the actual attacking unit has a qualifying negative status. [The donor dossier](../artifacts/law_tree_current_investigation_25672315/conditional_donors/feasibility.md) identifies `trogl_debuff` as one exact Current Core status control. Its source taxonomy lists 53 negative SIDs, but one matched control does not validate the whole list. This is more bounded than corpse lifetime/accounting, Gating identity, isolation geometry or Avenger-map inference; no matching conditional law row was found in the six inspected stock tables, not in every possible Core ability.

The active same-SID native row currently grants +10% friendly outgoing damage. Restoring the defensive condition requires an explicit replacement-versus-separate-law decision; silently adding the planner would change the design and could double-apply effects. The old `Homm3TrainingDamageLawRuntime` prefix is dormant research code, not a registrar to revive beside `Homm3RuntimeMechanicHooks`. Future execution must retain one native owner or the designated normalized committed-damage transaction owner when enabled; current live activation is not asserted.

Before any implementation: resolve that design conflict, repair or explicitly approve effective gate behavior without falsifying the proof ledger, define the exact negative-status contract, and prove Current attacker/defender ownership plus final damage, rounding and removal timing. No installed testing request was added because this pass installed nothing.

The follow-up's existing documentation contract passed in 0.997 s. Independent review checked native identity/PE bytes, reachable-instruction coverage, installed enum provenance, damage ownership and report scope. Those checks remain static evidence, not law behavior or release validation.
