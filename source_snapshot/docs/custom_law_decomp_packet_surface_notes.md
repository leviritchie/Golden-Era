# Custom Law Decomp Packet Surface Notes

Status: decomp-backed, runtime-unproven.

This document is a handoff for implementing custom faction law packets closer to native Olden Era surfaces. It does not authorize gameplay changes by itself. Anything marked "proven" is present in the current Cpp2IL/DiffableCs/ISIL artifacts. Anything marked "inferred" still needs runtime ordering proof before use as gameplay logic.

Source-prepared generated-name hint expansion: after refreshing `runtime_interop_map.json`, `symbol_map.json`, and `law_surface_dossiers.json`, `GameSymbols` now includes the remaining strong `type_callable_ordinal_and_signature_shape` generated candidates that were missing from centralized method hints: `EconomyLaws.AddResource`, `SpellbookLaws.HeroMagicLookup`, `HeroMagicCopy`, `HeroMagicCount`, `DataMagicLookup`, `DataMagicIndex`, `MagicBookTypeFilter`, `MagicBookSchoolFilters`, and `BattleEventLaws.BattleEventDispatch`. These hints are registration/diagnostic metadata only. They do not prove reward commit order, spellbook UI/cast-gate synchronization, battle event dispatch safety, or any packet gameplay, and shape-only candidates remain excluded.

Live-bridge negative spell cooldown setter evidence: a read-only `resolve_decomp_method` request for `eew.bdmh(System.Int32)` with decomp ordinal `45` returned runtime ordinal `45` as `Method_Private_Single_Int32_PDM_4`, not a `Void(Int32)` setter. The generated `Void(Int32)` candidates were ordinal mismatches. `GameSymbols.SpellCooldownLaws.SetCooldown` therefore intentionally remains decomp-name-only, and cooldown gameplay must not guess `Method_Public_Void_Int32_PDM_0` or any other shape-only setter. This is negative metadata proof only; it does not identify the correct mutation surface.

Source-prepared cooldown reduction without setter: `Homm3SpellCooldownNativeAdapter.TryReduceCooldownBy(...)` now uses the exact native `bdmg()` / `DecrementCooldown` surface repeatedly, capped by the current effective cooldown, instead of calling unproven `bdmh(...)` / `SetCooldown`. Pool-wide cooldown credit now skips exact school/SID-matching spells already at zero rather than aborting or counting a no-op as affected. This prepares cooldown-credit laws without a shape-only setter, but it remains packet-gated and does not prove cast-order, UI synchronization, spell-pool runtime identity, or active-law owner resolution.

Authoritative source-prepared family matrix: `custom_factions/custom_law_source_prepared_matrix.json`. This file maps each tracked law family index to its packet, handler key, adapter, runtime seam, current capability, and proof blockers. It is planning/source-state evidence only, not build, deployment, startup, or gameplay proof.

Static source-prepared matrix validator: `tools/release_port/validate_custom_law_source_prepared_matrix.py` is wired into `tools/release_port/check_custom_law_no_compromise_static.py`. It checks the matrix against target families, packet proof entries, handler registry slots, and named adapter/runtime source files. This validator is source hygiene only and is not yet run, build-proven, startup-proven, or gameplay-proven.

Source-prepared diagnostic candidate gate: `Homm3CustomLawRuntimeGuard` now separates non-mutating active-law candidate resolution from gameplay entry. `TryResolveCandidateActiveLaw(...)` and `Homm3CustomLawHandlerRegistry.TryProbeHandler(...)` can report exact active custom law/rank and packet proof state even when `gameplayAllowed=false`; `TryEnterHandler(...)` still uses the strict allowed path and remains the only gameplay mutation gate. `Homm3CustomLawHandlerTrace` now emits `candidate-denied` when a hook owner resolves law/rank but packet proof still blocks mutation. This is not packet promotion, not gameplay activation, and not runtime proof by itself; it is a safer logging seam for the next pilot.

Source-prepared candidate profile gates: all current profile-backed custom law families now have non-mutating candidate-profile accessors beside their strict allowed accessors. Candidate paths use `TryProbeHandler(...)` and return the active faction/rank intent plus packet proof state while `gameplayAllowed=false`; mutation helpers still use `TryEnterHandler(...)` only. Current candidate-profile entry points cover vision row 2, training row 6, counterstroke row 13, spell school rows 15/27, formation rows 18/19, gold economy row 21, morale package row 22, morale trigger row 25, construction row 28, calendar row 33, and cooldown row 34. This lets diagnostics and future exact hooks log what the law would do without silently activating unproven gameplay. It is not yet built, deployed, startup-proven, runtime-proven, or packet-promoted.

Source-prepared candidate profile logging: `Homm3CustomLawHandlerTrace.Describe(...)` now appends profile intent for owner-only probes where that is safe: vision, training damage, melee/ranged formation, construction, gold economy, calendar, morale package, spell school, and spell cooldown. Counterattack doctrine and morale trigger remain event-specific in the generic trace, and their exact diagnostics now append profile intent only when the native event payload supplies the required `EAbilityType.CounterAttack` or morale roll observation. This is diagnostic output only; it does not change packet proof states, mutate law effects, or authorize gameplay.

Source-prepared static profile catalog: `Homm3CustomLawImplementationCatalog.DescribeSourcePreparedProfiles(factionSid, rank)` and `DescribeSourcePreparedProfileCatalog()` now enumerate the approved profile intent for every tracked non-universal custom law row without needing a live law owner. Counterattack and morale-trigger entries are explicitly labeled with synthetic catalog observations (`syntheticCounterAttack`, `syntheticPositiveTrue`, `syntheticNegativeTrue`) so their output is design/catalog metadata only, not evidence that a runtime event occurred. This gives bridge commands, diagnostics, and future source audits one centralized way to inspect what each faction/rank law is supposed to do before packet gates are promoted. It is not yet built, deployed, startup-proven, runtime-proven, or gameplay-proven.

Source-prepared profile catalog diagnostic flag: `homm3_custom_law_profile_catalog_diag.flag` now asks `Homm3CustomFactionLawRuntime` to log the full source-prepared profile catalog as bounded per-faction/rank lines at startup. This flag is separate from `homm3_custom_faction_law_diag.flag`: by itself it does not register law-view diagnostic patches, mutate gameplay, or promote packets. It is intended for a quick deploy/startup audit of law intent after source changes. This is not yet built, deployed, startup-proven, or runtime-proven.

Source-prepared live bridge catalog command: `Homm3LiveProbeWorkbench` now includes read-only command `source_prepared_law_profiles`. With no filters it returns all profile catalog lines; with `factionSid` it returns ranks 1-3 for that faction; with `factionSid` plus `rank` it returns one faction/rank line. The command reads only source-prepared catalog metadata and repeats the synthetic counterattack/morale boundary in the response. It does not inspect active law owners, read gameplay state, register hooks, mutate state, or promote packet proofs. This is not yet built, deployed, bridge-listed in a running game, or runtime-proven.

Source-prepared DiffableCs-only law dossier evidence: `build_law_surface_dossiers.py` now records exact DiffableCs method-shell evidence when a law surface has a C# declaration and generated runtime metadata but no ISIL body. This is intended for surfaces such as `MapVisionObjectDesc` factories, `Unit.bbgw(...)`, and `dzv` buff manager methods, where absence of ISIL previously appeared as `type_not_found` even though DiffableCs and runtime interop had useful static metadata. These rows remain static metadata only: no call anchors, method bodies, invocation order, Harmony safety, or gameplay mutation are proven by DiffableCs-only evidence.

Source-prepared MapVision generated-name hints: `GameSymbols.AdventureVisionLaws.MapVisionSquadCandidate` and `MapVisionBySid` now include the exact generated runtime names exposed by the refreshed interop map (`Method_Public_Static_MapVisionObjectDesc_Int32_PDM_0` and `Method_Public_Static_MapVisionObjectDesc_String_PDM_0`) alongside the decomp names `okz` and `ola`. This is exact metadata for future bridge resolution only; it does not classify map objects, reveal fog, refresh map UI, or promote the vision packet.

Source-prepared Unit damage generated-name hint: `GameSymbols.BattleEventLaws.BattleUnitApplyDamage` now includes the exact generated runtime method `Method_Public_Virtual_Void_InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique_InterfacePublicAbstractbaBoaObVobabaObInUnique_ObjectPublicCacodaCaObceObceUnique_Int32_EMechType_Boolean_Single_Boolean_0`, which the refreshed interop map places on `Hex.Session.Battle.Unit` with callable ordinal 88 and an `EMechType` parameter. This is a stronger exact registration hint for committed-damage diagnostics only. It does not prove `Unit.bbgw(...)` call ordering, final-damage semantics, death cleanup timing, or safe damage mutation.

Source-prepared construction lookup generated-name hint: `GameSymbols.ConstructionLaws.BuildingsManagerLookupCandidate` now includes the exact generated runtime method `Method_Private_MonoBehaviourPublicStBhbuceBhInceStBhceUnique_String_PDM_0`, which the refreshed interop map places on `Hex.Session.City.BhBuildingsManager` for the `bajt(string)` lookup candidate. This is exact metadata for construction diagnostics/dossier refresh only. It does not prove displayed-cost, charged-cost, eligibility, constructed-state, resource mutation, or active-law agreement.

Source-prepared unit-family law gates: `Homm3UnitLawClassifier` now exposes explicit `FamilyFact` requirements, and the battle-event/counterattack law runtimes can require dealer or receiver facts after their packet and handler gates pass. These helpers consume only exact native unit/config identity plus the generated custom unit family registry. `custom_factions/unit_family_tags.json` covers 210 exact custom unit SIDs. Current authored facts are ontology-level line facts: living, undead, elemental, construct, and Cove pirate-line `gunpowder=yes` for `h3_pirate`, `h3_corsair`, and `h3_sea_dog`. A June 18 bounded search of `custom_factions/*.json` found no exact `sourceMechanicId` or `branchRole` fields, so `shooter` and `melee` remain `unknown` for every unit. `gatedOrSummoned` and `corpseProducing` also remain unknown because they are runtime-state facts, not unit-line facts. Unknown facts still fail closed. This is not yet built, deployed, startup-proven, classifier-runtime-proven, or gameplay-proven.

Live-bridge construction lookup proof: a June 18 read-only `resolve_decomp_method` request for `Hex.Session.City.BhBuildingsManager.bajt(System.String)` with decomp callable ordinal `6` returned `Method_Private_MonoBehaviourPublicStBhbuceBhInceStBhceUnique_String_PDM_0` with `runtime_callable_ordinal_match`, return-type match, and parameter match. `GameSymbols.ConstructionLaws.BuildingsManagerLookupCandidate` already contains that generated name. This tightens construction diagnostics only; it still does not prove displayed-cost, charged-cost, eligibility, constructed-state, resource mutation, active-law agreement, or packet promotion.

Live-bridge reward apply non-proof: a June 18 read-only `resolve_decomp_method` request for `czy.vji(Hex.Session.Logic.Hero, Hex.Session.Data.DataRewardSet)` with decomp callable ordinal `37` found the full-shape generated candidate `Method_Public_Void_Hero_DataRewardSet_PDM_0`, but that candidate reported runtime callable ordinal `36`, while ordinal `37` resolved to a mismatched `Void(Int32)` method. `GameSymbols.RewardCommitLaws.RewardSetApply` therefore remains decomp-name-only. Do not bind the generated full-shape reward applier as strict proof, diagnostics, or gameplay until the ordinal mismatch is resolved by a stronger evidence class.

Source-prepared classifier evidence-label repair: `Homm3UnitLawClassifier.DescribeEvidence(...)` now reports `familySource=custom-unit-registry` when a unit SID matched `Homm3UnitLawFamilyRegistry`, instead of always appending `source=no-proven-family-source`. This is diagnostic clarity only; unknown facts still fail closed, and the change is not yet built, deployed, startup-proven, runtime-proven, or gameplay-proven.

Regenerated law-surface dossier after DiffableCs-only support: `experiments/cpp2il_readable_csharp/samples/latest_refresh/law_surface_dossiers.json` and `.md` were regenerated from the current `GameSymbols.cs`, DiffableCs, ISIL, symbol map, runtime interop map, and semantic index. This refresh is intended to stop the handoff package from reporting `MapVisionObjectDesc` factories, `Hex.Session.Battle.Unit.bbgw(...)`, and `dzv` buff manager methods as `type_not_found` when DiffableCs and generated interop metadata are available. This is static/tooling evidence only; it is not a build, deploy, startup proof, Harmony safety proof, runtime-ordering proof, or packet promotion.

Live-bridge MapVision metadata proof: June 18 read-only `resolve_decomp_method` requests for `Hex.Map.MapVisionObjectDesc.City(Int32)`, `Hero(Int32)`, `okz(Int32)`, `Item(Int32)`, and `ola(String)` all returned the expected runtime method with callable ordinal match. The generated methods are `Method_Public_Static_MapVisionObjectDesc_Int32_PDM_0` for `okz(Int32)` and `Method_Public_Static_MapVisionObjectDesc_String_PDM_0` for `ola(String)`. This proves metadata identity only; it does not classify objects, mutate fog, refresh map UI, or authorize the vision packet.

Live-bridge Unit damage metadata proof: June 18 read-only `resolve_decomp_method` for `Hex.Session.Battle.Unit.bbgw(...)` returned exactly one full-signature generated candidate, `Method_Public_Virtual_Void_InterfacePublicAbstractbaObbbUnInbbUnObbbObUnique_InterfacePublicAbstractbaBoaObVobabaObInUnique_ObjectPublicCacodaCaObceObceUnique_Int32_EMechType_Boolean_Single_Boolean_0`. This is useful for committed-damage diagnostics, but no decomp callable ordinal was supplied in that bridge request, and it does not prove final-damage ordering, death cleanup ordering, or safe mutation.

Buff/debuff metadata boundary: June 18 read-only bridge requests for `dzv.bbgf`, `bbfn`, and `bbfl` confirm that the full-shape generated buff-add candidate exists, but ordinal attempts using a simple DiffableCs callable-order estimate did not align: `bbgf` full-shape candidate reported an ordinal mismatch, while `bbfn` and `bbfl` remained ambiguous among many same-shape methods. Keep `GameSymbols.BuffDebuffLaws` generated names as static metadata hints only; do not treat `BuffAdd`, `BuffHasBySid`, or `BuffListBySid` as strict live-bridge proofs until a stronger type/ordinal mapping is available.

Source-prepared buff/debuff law gate: `Homm3BuffDebuffNativeAdapter` centralizes exact read-only native buff manager SID query surfaces from `GameSymbols.BuffDebuffLaws`, and `Homm3CustomBuffDebuffLawRuntime` exposes packet-gated SID requirements for future exact hooks. Decomp evidence proves battle receivers inherit `ede`, whose `cnyb` / `bbds()` returns exact `dzv` buff manager from `<cfnh>` offset `0x48`; receiver-derived helpers now query that manager directly and can derive law ownership from the same receiver through `FieldObject.basa()`. It has explicit helpers for Rampart Avenger marks using `GameSymbols.RampartAvengerLaws.MarkBuffSids`. It does not add, remove, mutate, infer, scan for, or classify buffs such as poison/slow/disable by name. Future hooks must pass a proven receiver or buff manager plus exact SID list. This is not yet built, deployed, startup-proven, receiver-buff-runtime-proven, or gameplay-proven.

Source-prepared spell identity gate: `Homm3SpellIdentityNativeAdapter` reads exact `eew` battle spell identity from decomp-proven `cnyy`/`bdma` and `cnyz`/`bdmb`, then reads exact `MagicConfig` school from `bxti` / `<bxti>k__BackingField` / `school_`. `Homm3CustomSpellCooldownLawRuntime` now has SID- and school-gated cooldown helpers. This separates spell identity from cooldown mutation and remains packet-gated. It is not yet built, deployed, startup-proven, cast-order-proven, UI-sync-proven, or gameplay-proven.

Source-prepared spell school/access profiles: `Homm3CustomLawEffectProfiles` now centralizes `SpellSchoolProfile` intents for confirmed generator rows 15 (`spell.low`) and 27 (`spell.high`), and `Homm3CustomSpellSchoolLawRuntime` returns those profiles only after the matching handler gate succeeds. Profiles encode Castle Daylight Liturgy and Dungeon Night Dominion as native data-only access, Fortress/Rampart Primal access with status/Avenger runtime add-on requirements, Cove Space/Arcane support requirements pending generated-row verification, Tower generator-profile school plus prepared-spellbook reuse requirements, Conflux dynamic elemental-family access, Inferno Primal/fire-gating verification plus sacrifice/gated identity, Necropolis Night/corpse rite integration, and Stronghold real Warcry replacement instead of traditional school access. This does not mutate spellbooks, fabricate UI entries, change cast gates, grant schools, or promote packet gameplay. Existing native law rows remain the data path for exact school access; runtime profiles only document add-ons and non-data factions.

Source-prepared spell pool gate: decomp evidence shows `eex` owns the battle spell array through `cfxr` / `<cfxr>k__BackingField` / `bdmq`, the current spell through `cfxv`, and the caster through `cfyd`. `eir` then exposes exact transfer side `cgle`, `TransferSide` exposes exact `logicHero`, `Hex.Session.Logic.Hero` exposes data hero `ccez` and logic root `ccfu`, and the logic root `dsu` exposes current `Data` through `cclb` / `yfr`. `Homm3CustomFactionLawRuntime` can now resolve that logic hero to exact `Data.sides.array` by matching `Hero.sideId` to `Side.index`, then enter active custom law/rank state. `Homm3SpellCooldownNativeAdapter` can read those exact spell-pool members and the caster-derived cooldown law owner, and `Homm3CustomSpellCooldownLawRuntime` can apply ranked cooldown credit or ready-cooldown penalties to all spells in a pool matching an exact school or spell SID. These helpers fail closed on unreadable pools, unreadable spell identity, missing owner links, missing exact side index, empty pools, no matches, or packet denial. They are not yet built, deployed, startup-proven, spell-pool-runtime-proven, caster-owner-runtime-proven, cast-order-proven, UI-sync-proven, or gameplay-proven.

Source-prepared construction identity gate: `Homm3ConstructionNativeAdapter` now reads exact `BuildingData` SID, level, and constructed state using the existing `GameSymbols.ReleaseTownUi` member sets, and resolves `BuildingsData` exactly from `BuildingsData`, `ObjCity.buildings`, or `fbs` city logic through decomp-proven `cjgv`/`biso` city access. For `fbs` city logic callers, decomp evidence also supports exact owner resolution through `fbs.cjgv` / `ObjCity` inherited `DataObject.ownerSide` and `fbs.cjhd` / `ctr.caan` or `ctr.uzb` / `Data.sides.array`, matching `Side.index == ownerSide`. `Homm3CustomConstructionLawRuntime` has SID-list-gated daily construction refund helpers for direct `BuildingsData`, caller-supplied law owner city contexts, and `fbs` owner-derived city contexts. Bare `ObjCity` contexts still cannot derive law ownership because they do not expose a session `Data` root. This supports future faction-specific infrastructure laws without broad generic construction bonuses. It is not yet built, deployed, startup-proven, commit-order-proven, UI-cost-proven, city-owner-runtime-proven, or gameplay-proven.

Source-prepared reward/resource identity gate: `Homm3RewardEconomyNativeAdapter` now reads exact `Resource.name/value`, resolves native gold from `Side.res` or `ResHeap.gold`, and reads exact `DataRewardSet` identity (`id`, `heroId`, `objectId`, `label`, apply/show/cancel types, and reward item summaries). `Homm3CustomRewardEconomyLawRuntime` can now resolve native gold from the active law owner data side before calling gold-economy/calendar grant helpers, while still requiring the resolved resource to be native `gold`. Reward-set helpers remain packet-gated; they do not prove commit ordering, source classification, or idempotence. This is not yet built, deployed, startup-proven, active-law-data-side-runtime-proven, reward-order-proven, or gameplay-proven.

Source-prepared gold economy profile gate: `Homm3CustomRewardEconomyLawRuntime.TryGetAllowedGoldEconomyProfile(...)` now returns a row 21 `RewardEconomyProfile` immediately after the `reward.gold-economy` handler gate succeeds, without requiring a `DataRewardSet` context. This lets future exact mine-capture, town-capture, defensive-win, rare-resource, casualty, sacrifice, or Warcry hooks consume the approved faction economy intent without pretending every economy law starts from a reward-set apply call. It still performs no source classification, resource mutation, idempotence, build/deploy, runtime proof, or packet promotion.

Source-prepared calendar/omen profiles: `Homm3CustomLawEffectProfiles` now centralizes `CalendarProfile` intents for confirmed row 33, and `Homm3CustomRewardEconomyLawRuntime.TryGetAllowedCalendarProfile(...)` returns a profile only after the existing `reward.calendar` handler gate succeeds. Native `astrologyExp([250/500/750, 0.0])` remains the data path for guaranteed Astrology income. Runtime profiles represent Castle support/blessing charges, Cove Focus/Storm Omens, Dungeon first Night spell portents, Fortress poison/slow duration signs, Rampart cleanse/regeneration/resistance cycles, Tower cooldown/construct calculus, Conflux deterministic elemental day phases, Inferno fire/gated signs, Necropolis corpse/raise Death Moon, and Stronghold War Festival. These profiles do not mutate Astrology progress, cooldowns, statuses, Focus, buffs, Warcries, or battle state, and they do not promote packet gameplay.

Source-prepared reward idempotence gate: `Homm3CustomLawIdempotenceRuntime` now provides session-local reward grant keys using handler, law index, rank, grant kind, amount, and exact `DataRewardSet` identity. `Homm3CustomRewardEconomyLawRuntime` has one-shot gold grant helpers for `reward.gold-economy` and `reward.calendar`. This prevents future exact reward hooks from double-paying the same committed reward set, but it is still not persistence and does not prove commit ordering or source classification.

Source-prepared vision object identity gate: `GameSymbols.AdventureObjectScoutingLaws` now aliases exact `DataObject` id/config/owner-side members, `Homm3AdventureVisionNativeAdapter` can read and require object config SIDs, and `Homm3CustomVisionLawRuntime` has one-shot config-SID gated scouting helpers. The runtime can now derive the scouting side from the active law owner via exact `Side.index`, rather than accepting only caller-supplied side ids. This still only calls native object-scouted state and does not mutate fog tiles or refresh the map. It is not yet built, deployed, startup-proven, active-law-side-runtime-proven, reveal-order-proven, or gameplay-proven.

Source-prepared vision profiles: `Homm3CustomLawEffectProfiles` now centralizes `VisionProfile` intents for hero sight radius law index 2, and `Homm3CustomVisionLawRuntime.TryGetAllowedVisionProfile(...)` returns one only after the existing `vision.reveal` packet/handler gate succeeds. The profiles encode Castle Road Wardens conditional +4 road vision, Cove Sea Charts structure-based treasure/bank/high-value neutral scouting, Dungeon Deep Scouts neutral intention preview, Fortress Marsh Sense enemy-hero structure reveal, Rampart Avenger's Trail, Tower Observatory Network artifact/regional reveal, Conflux Planar Attunement elemental-site reveal, Inferno Hellgate Omens existing gate-site reveal, Necropolis Gravesight corpse/undead-site reveal, and Stronghold War Scouts weak-neutral scouting. These are profile data only: they do not classify object SIDs, mutate fog tiles, refresh map visibility, inspect localized threat text, create Avenger marks, or enable gameplay. Cove Prize Shares also no longer carries the previously source-prepared but unapproved hard-coded `10%` gold amount; it remains a classification/idempotence profile until a real balance amount is approved.

Source-prepared formation predicate gate: after generating `runtime_interop_map.json` from the Golden Era `Hex.dll` and refreshing the bounded law dossiers, `Homm3BattleEventNativeAdapter.CastAbilityEventInfo` now reads exact `roundNumber` and exposes attacked object/hex/immune counts from caller-supplied `CastAbilityEventArgs`. `Homm3CustomBattleEventLawRuntime` now has melee and ranged formation helpers that require handler ownership, exact caster family, minimum target counts, and first-round status for ranged volleys. This adds no hook registration, no action mutation, and no fallback geometry inference. It is not yet built, deployed, startup-proven, packet-proven, classifier-data-proven, or gameplay-proven.

Source-prepared battle object law-owner gate: decomp evidence shows battle `Unit` inherits `FieldObject`, and `FieldObject.basa()` returns the exact owning `eir` side from `<cfnp>`. The same current-build chain used for spell pools then applies: `eir.cgle` exposes `TransferSide`, `TransferSide.logicHero` exposes `Hex.Session.Logic.Hero`, and `Homm3CustomFactionLawRuntime` resolves that logic hero to active custom law/rank by matching data hero `sideId` to `Data.sides.array[*].index`. `Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(...)` now consumes that chain, and `Homm3CustomBattleEventLawRuntime` has dealer-owned damage training and caster-owned melee/ranged formation entry points. These helpers do not fall back from dealer to caster, do not infer ownership from array position, and do not register hooks or mutate battle state. They are not yet built, deployed, startup-proven, battle-object-owner-runtime-proven, packet-order-proven, or gameplay-proven.

Source-prepared morale unit law-owner gate: morale trigger candidates consume a native battle `Unit`, and `Homm3CustomMoraleLawRuntime` now has unit-owned roll classification entry points that resolve active `morale.trigger` ownership through `Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(...)`. These helpers can optionally require exact generated unit-family facts, but they do not decide trigger-vs-check semantics, mutate morale rolls, or schedule extra actions. They are not yet built, deployed, startup-proven, morale-unit-owner-runtime-proven, morale-phase-proven, action-queue-proven, or gameplay-proven.

Source-prepared flat morale package profiles: `Homm3CustomLawEffectProfiles` now centralizes `MoralePackageProfile` intents for morale law row 22, and `Homm3CustomMoraleLawRuntime.TryGetAllowedMoralePackageProfile(...)` returns a profile only after the existing `morale.package` handler gate succeeds. The profiles keep Castle as native morale/additional-action data; represent Cove momentum from kills/plunder/cannon/surviving ranged fire; Dungeon enemy morale-failure/debuff exploitation; Fortress damage-taken/slow/poison endurance; Rampart protect/preserve/Avenger morale; Tower construct readiness after spells; Conflux mixed-elemental resonance; Inferno friendly death/sacrifice/gated-loss frenzy; Necropolis enemy dread/corpse pressure with no positive undead morale; and Stronghold damage/kill rage. These profiles do not mutate morale stats, action queues, speed, Focus, buffs, or turn order, and they do not promote `morale` packet gameplay.

Source-prepared Focus event-side law-owner gate: `Homm3CustomFactionLawRuntime` now accepts exact battle side `eir` objects by resolving `eir.cgle` to `TransferSide.logicHero`, then reusing the existing data hero side-id chain. `Homm3CustomFocusLawRuntime` now has event-side-owned Focus/Energy entry points for `counterattack.doctrine`, `spell.low`, `spell.high`, and `spell.cooldown`. These helpers only read native Focus/Energy payloads and enter the consuming law handler; they do not grant Focus, spend Focus, normalize ability energy, or promote packet gameplay. They are not yet built, deployed, startup-proven, Focus-event-side-runtime-proven, storage-mutation-proven, UI-sync-proven, or gameplay-proven.

Source-prepared active law side-index gate: `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLawSideIndex(...)` now resolves exact `Side.index` for data sides, logic sides, logic heroes, and battle `eir` sides already supported by the active-law resolver. Vision uses this to mark objects scouted by the law owner side instead of a free integer side id. This helper has no array-position fallback and does not infer side ownership from object owner fields. It is not yet built, deployed, startup-proven, active-law-side-runtime-proven, or gameplay-proven.

Source-prepared active law data-side economy gate: `Homm3CustomFactionLawRuntime.TryResolveActiveKnownCustomLawDataSide(...)` now exposes the exact data `Side` behind an active law owner. `Homm3CustomRewardEconomyLawRuntime` uses it to resolve native gold from `Side.res -> ResHeap.gold` for gold-economy and calendar grants, including reward-set idempotent variants. This does not classify reward sources, prove reward commit order, or promote packet gameplay. It is not yet built, deployed, startup-proven, active-law-data-side-runtime-proven, reward-order-proven, or gameplay-proven.

Source-prepared receiver buff-manager gate: DiffableCs and ISIL show `ede.bbds()` returns `dzv` from `<cfnh>` / offset `0x48`, and battle `Unit` inherits `ede`. `Homm3BuffDebuffNativeAdapter.TryResolveBuffManagerFromReceiver(...)` now consumes exact `cnyb` / `bbds` to find the native buff manager, while `Homm3CustomBuffDebuffLawRuntime` has receiver-derived SID and Rampart Avenger mark gates, including law-owner-derived variants through `Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(...)`. These helpers read buff presence only; they do not add, remove, mutate, or classify buffs by fuzzy names. They are not yet built, deployed, startup-proven, receiver-buff-runtime-proven, or gameplay-proven.

## June 18 source-prepared implementation classification

The current source state supports three distinct readiness levels:

| Packet | Current source state | What is now statically implementable | Blocking proof before gameplay |
| --- | --- | --- | --- |
| `spell-cooldown` | Exact diagnostics, cooldown adapter, cast-gate adapter | Future handlers can read exact cooldown/gate surfaces and call exact native cooldown methods through adapters | Cast event to gate/cooldown/UI ordering; `setCooldown` strict proof remains weaker |
| `construction` | Exact diagnostics, construction adapter | Future handlers can read/write exact build state and daily construction count through one adapter | Build commit ordering tying displayed cost, charged resources, state mutation, and daily count |
| `vision` | Exact diagnostics, vision adapter | Future handlers can mark objects scouted and read fog/map-magic registry through exact methods | Real fog tile reveal mutation, object classification, side context, and map refresh |
| `reward-result` | Exact reward/economy diagnostics, reward/economy adapter | Future handlers can mutate resources through exact native methods after a committed reward source is known | Reward apply/commit identity, idempotence key, and source-to-resource correlation |
| `morale` | Exact morale-roll diagnostics, morale adapter, handler-gate traces | Future handlers can classify exact positive/negative morale roll methods | Runtime semantic ordering: positive trigger vs check, negative trigger vs check, action-queue timing |
| `committed-damage` | Battle-event diagnostics, handler-gate traces, battle-event adapter | Future handlers can observe exact damage/destruction payloads and active law state together | Safe final unit damage point and post-reduction/death ordering |
| `battle-action` | Battle-event diagnostics, formation probes, handler-gate traces, battle-event adapter | Future handlers can observe exact movement/cast payloads and formation law state together | Publisher/dispatch ordering and action classification for move, attack, cast, wait, defend |
| `counterattack` | Exact counterattack correlation diagnostics and handler-gate traces | Future handlers can observe command/resolver/ability listener contexts without broad dispatcher fallbacks | Proof that ability type/correlation identifies actual retaliations and separates follow-up/revenge damage |
| Focus/Energy support | Focus diagnostics, exact event field symbols, Focus adapter | Future handlers can observe native Focus/Energy event payloads and hero ability energy metadata | Native storage mutation, grant/spend ordering, and hero ability UI synchronization |

No packet currently has `gameplayAllowed=true`; adapters are source-prepared tools, not activation.

Additional gated runtime entry points are now source-prepared for future exact hooks:

- `Homm3CustomVisionLawRuntime` can enter `vision.reveal`, derive the active law owner side index through `Homm3CustomFactionLawRuntime`, and then mutate only object scouting through `Homm3AdventureVisionNativeAdapter`. It does not classify objects or mutate fog tiles.
- `Homm3CustomMoraleLawRuntime.TryClassifyAllowedMoraleRoll(...)` classifies an exact native morale roll through `Homm3MoraleTriggerNativeAdapter`, and the unit-owned overloads can derive law ownership through exact `FieldObject.basa()` battle-side ownership before entering `morale.trigger`. It mutates no roll, action queue, or unit state.
- `Homm3CustomBattleEventLawRuntime` reads committed-damage and melee/ranged formation event payloads through `Homm3BattleEventNativeAdapter`, can derive dealer/caster law owners through exact `FieldObject.basa()` battle-side ownership, then enters the matching handler slot. It mutates no damage, formation, movement, turn order, or cast state.
- `Homm3CustomLawEffectProfiles` now centralizes source-prepared training damage profiles and melee/ranged formation profiles for all custom factions. `Homm3CustomBattleEventLawRuntime` exposes profile-returning gates for `damage.training`, `battle.melee-formation`, and `battle.ranged-formation`. Training profiles encode proposal-specified values such as Castle +2% per positive morale, Cove -1/-2 Defense per gunpowder hit, Dungeon +5/10% isolated-target damage, Fortress -10% debuffed-attacker damage, Inferno +15/30% gated-entry damage, Necropolis 2/4/6 temporary mana per corpse, and Stronghold +1/+2 wounded speed; other factions encode proof requirements without invented numbers. Formation profiles encode required predicates such as first volley, gunpowder/Pirate, geometry, debuff, Avenger mark, construct classifier, spellcast, elemental mix, gating/teleport identity, living enemy, and forward movement/kill. These profiles do not mutate gameplay and remain blocked by final damage ordering, action classification, geometry proof, and safe effect mutation surfaces.
- `Homm3CustomCounterattackLawRuntime` requires a native `EAbilityType.CounterAttack` and counterattacking battle object supplied by a future exact hook, derives law ownership through exact `FieldObject.basa()` battle-side ownership, enters `counterattack.doctrine`, and can then read committed damage through `Homm3BattleEventNativeAdapter`. It does not infer counterattacks from timing, animations, or generic damage events.
- `Homm3CustomFocusLawRuntime` provides packet-gated Focus/Energy read entry points through existing consuming handlers (`counterattack.doctrine`, `spell.low`, `spell.high`, and `spell.cooldown`). Event-side overloads can derive law ownership from the exact Focus/Energy side object through the shared custom-law resolver. It reads exact native Focus payloads and hero ability energy metadata through `Homm3FocusNativeAdapter`; it does not grant, spend, normalize, or classify Focus as its own packet.
- `Homm3CustomLawImplementationCatalog` summarizes the source-prepared adapter/runtime seams in custom law diagnostics so startup logs can show what exists while packet gates still deny gameplay. The catalog is descriptive only and does not resolve adapters or prove hooks.

## June 18 decomp-to-runtime refresh note

The refreshed `experiments/cpp2il_readable_csharp/samples/latest_refresh` artifacts add static runtime-candidate evidence for several law surfaces. Current source now consumes those candidates only for diagnostics:

- `custom_factions/custom_law_packet_proofs.json` now records intermediate proof states for packets that have live bridge metadata proof but still lack gameplay mutation/order proof. `Homm3CustomLawPacketGate.cs` was regenerated from that ledger. `gameplayAllowed` remains `false` for every packet; this change is source hygiene for exact hooks, not law activation.
- `Homm3CustomLawHandlerTrace` now gives exact packet diagnostics a shared way to call `Homm3CustomLawHandlerRegistry.TryEnterHandler(...)` and log the active-law/proof-gate result without mutating gameplay. Construction, spell-cooldown, and vision diagnostics use this helper on their exact trace surfaces. This is source-prepared only; it is not startup-proven and should produce `handlerGate=...denied...` until packet proof states are intentionally promoted.
- Live bridge metadata proof on June 18 confirmed runtime ordinal matches for `law.rewardCommit.rewardSetQueued` and `law.rewardCommit.rewardSetRemoved`; proof artifacts live under `experiments/cpp2il_readable_csharp/samples/latest_refresh/live_bridge_proofs`. `RewardCommitLaws.RewardSetQueued` and `RewardCommitLaws.RewardSetRemoved` include generated candidates `Method_Public_Void_DataRewardSet_0` and `Method_Public_Void_DataRewardSet_1`. Diagnostics iterate exact hints only.
- `law.rewardCommit.rewardSetApply` keeps the exact generated signature candidate `Method_Public_Void_Hero_DataRewardSet_PDM_0` for `czy.vji(Hero,DataRewardSet)`. The rejected candidate was the delegate-registration-shaped `Method_Public_Void_Action_1_ObjectPublicObciInLici1SiObBocoUnique_Object1PublicSiObFrObccSiLiObcc1Unique_PDM_0`, not the real apply method. Live bridge metadata on June 18 ranked `Method_Public_Void_Hero_DataRewardSet_PDM_0` first by exact signature but with a one-slot callable ordinal mismatch, so this remains exact diagnostic registration evidence, not reward idempotence or gameplay mutation proof.
- `RewardCommitLawDiagnostics` no longer broad-patches every one-`DataRewardSet` method if exact queue/remove names drift. Exact failure is intentional and should remain visible.
- `Homm3RewardEconomyNativeAdapter` now centralizes exact resource data mutations (`Resource.bggu/bggv/bggw/bggx` and generated names) and reward lifecycle observation (`DataRewardSets.bfus/bfut` and generated queue/remove names). It does not authorize committed reward grants, does not invoke reward apply, and treats `ResHeap.bggt` as descriptive unless stronger proof is added. Economy and reward commit diagnostics now log shared `handlerGate` state for `reward.gold-economy` and `reward.calendar`; expected packet-gate result remains denied until idempotent committed source identity is proven.
- `Homm3CustomRewardEconomyLawRuntime` now provides packet-gated `TryAddGoldEconomyGrant(...)` and `TryAddCalendarGrant(...)` entry points for future exact reward/calendar hooks, including active-law-data-side overloads that resolve native gold through `Side.res -> ResHeap.gold`. These methods do not classify reward sources, enter `Homm3CustomLawHandlerRegistry`, and mutate only through `Homm3RewardEconomyNativeAdapter`. They should remain unreachable until reward-result packet proof is promoted.
- `Homm3CustomLawEffectProfiles` now centralizes source-prepared reward/calendar economy profiles for Castle, Cove, Dungeon, Fortress, Rampart, Tower, Conflux, Inferno, Necropolis, and Stronghold. `Homm3CustomRewardEconomyLawRuntime` exposes profile-returning reward-set gates for `reward.gold-economy` and `reward.calendar`; the profiles describe source identity and proof requirements only. They do not authorize reward grants before committed reward identity, idempotence, and source-to-resource correlation are proven.
- `CounterattackCorrelationLaws.AbilityManagerTypeHints` now points to decomp-backed `dxx` with `barb`/`bgl` ability resolve hints instead of stale `dxr::banq`.
- `CounterattackCorrelationLaws.BattleAttackExecute` and `CounterattackCorrelationLaws.AttackResolver` intentionally have no bindable method names after the June 18 refreshed dossiers and bounded method-dossier attempts found no `cty::hrl` or `een::bdhu` methods. `Homm3CounterattackCorrelationLawDiagnostics` now logs these as known-stale surfaces instead of attempting registration. Do not re-enable them without a new exact dossier or runtime metadata proof.
- Live bridge metadata on June 18 exposed exactly two generated `dxx` methods with the `bool(EAbilityType,int,out ability)` resolver shape: `Method_Public_Boolean_EAbilityType_Int32_byref_ObjectPublicObceInBoInceAbObELInUnique_0` and `Method_Public_Boolean_EAbilityType_Int32_byref_ObjectPublicObceInBoInceAbObELInUnique_PDM_0`. DiffableCs exposes exactly two matching obfuscated resolver methods, `barb` and `bgl`. These generated names are now centralized as exact diagnostic registration names only; runtime counterattack correlation remains unproven.
- Live bridge metadata on June 18 exposed exactly three generated `ebv` methods with the `void(Unit,EAbilityType,int)` listener shape: `Method_Public_Void_Unit_EAbilityType_Int32_PDM_0`, `Method_Public_Void_Unit_EAbilityType_Int32_PDM_1`, and `Method_Public_Void_Unit_EAbilityType_Int32_PDM_2`. DiffableCs exposes exactly three matching obfuscated listener methods, `bbwi`, `jsd`, and `nhw`. `bbwi` individually proved ordinal+shape; `jsd/nhw` are exact-set evidence only because the live resolver's callable ordinal for those names prefers different same-ordinal methods. Treat the three generated names as one diagnostic listener set, not as per-method semantic proof.
- `CounterattackCorrelationLaws` now has exact static `dxy` `ChangeAbilityEventArgs` factory candidates (`bast`, `kda`, `dwf`, `mgi` and their generated names). `Homm3CounterattackCorrelationLawDiagnostics` traces these as `ability-runtime-change-event`. Runtime proof must show whether actual retaliations produce `abilityType=2`; no counterattack law gameplay is authorized yet.
- `Homm3CounterattackCorrelationLawDiagnostics` no longer uses unique-signature fallbacks for battle attack command, ability-manager resolve, battle-logic attack resolver, or `ebv` ability listeners. Missing exact names intentionally leave that diagnostic sub-surface disabled with a warning.
- `Homm3CustomCounterattackLawRuntime` now has counterattacking-battle-object entry points that use `Homm3BattleEventNativeAdapter.TryResolveLawOwnerFromBattleObject(...)` before entering `counterattack.doctrine`. These entry points require a proven hook to supply the actual counterattacker; they do not derive counterattack identity from the damage event dealer/caster and do not promote packet gameplay.
- `AdventureVisionLaws` now includes generated candidates for fog initialize/read/count, map-magic add/lookup, and object-scout-by-side from `law_surface_dossiers`. `Homm3AdventureVisionLawDiagnostics` no longer accepts unique signature-shape matches after exact hints fail. This intentionally makes stale vision symbols obvious instead of binding a plausible-but-unproven method.
- Live bridge metadata proof on June 18 confirmed runtime ordinal matches for `law.vision.fog.initialize`, `law.vision.fog.visibilityRead`, `law.vision.fog.countCandidate`, `law.vision.mapMagic.add`, `law.vision.mapMagic.lookup`, and `law.vision.dataObject.scoutedBySide`; proof artifacts live under `experiments/cpp2il_readable_csharp/samples/latest_refresh/live_bridge_proofs`. This is metadata proof only, not fog mutation or map refresh proof.
- `Homm3AdventureVisionNativeAdapter` now centralizes exact object-scouting, fog read/count, and map-magic add/lookup surfaces for future vision handlers. It exposes `DataObject.bgdo(int)` and map-magic registry helpers by exact symbol only, but deliberately does not mutate fog tiles because the native reveal write/update path remains unproven. Vision diagnostics still log shared `handlerGate` state and should remain denied until object classification, side context, idempotence, and map refresh behavior are proven.
- `law.battleEvents.dispatch` is intentionally not promoted: live bridge metadata did not prove the generated dispatcher candidate by first-candidate ordinal match, so the generated dispatch name was removed from `GameSymbols`. Generic battle-event dispatch remains a known high-risk surface and must not be used as a broad fallback.
- `Homm3BattleEventLawDiagnostics` and `Homm3CounterattackCorrelationLawDiagnostics` now log shared `handlerGate` state for `damage.training`, `battle.melee-formation`, `battle.ranged-formation`, and `counterattack.doctrine` respectively. This is diagnostic-only packet routing evidence; committed-damage, battle-action, and counterattack gameplay remain denied until packet proof is promoted.
- `Homm3BattleEventNativeAdapter` now centralizes exact battle event payload reads for `ObjectTookDamageEventArgs`, `ObjectDestroyedEventArgs`, `UnitPosChangedEventArgs`, `UnitStartedMovementEventArgs`, and `CastAbilityEventArgs`. It does not register hooks, dispatch events, mutate damage, or alter turn/action state; it is source-prepared adapter infrastructure for future committed-damage and battle-action handlers after packet proof is promoted.
- `Homm3CustomConstructionLawDiagnostics` and `Homm3CustomFactionEconomyLawDiagnostics` now refuse signature-only binding after exact names miss. Signature checks remain only to validate centralized `GameSymbols` names. If a construction or economy symbol drifts, add decomp/runtime-proven generated names to `GameSymbols`; do not restore unique-signature binding.
- `Homm3CustomConstructionLawRuntime` now provides a packet-gated `TryRefundConstructionCountByRank(...)` entry point for future exact commit hooks. It requires an explicit law owner and `BuildingsData` object, enters `construction.commit` through `Homm3CustomLawHandlerRegistry`, then uses `Homm3ConstructionNativeAdapter` only. It registers no hooks and should remain unreachable until construction packet proof is promoted.
- `Homm3CustomLawEffectProfiles` now centralizes source-prepared construction profiles for Castle, Cove, Dungeon, Fortress, Rampart, Tower, Conflux, Inferno, Necropolis, and Stronghold. `Homm3CustomConstructionLawRuntime.TryGetAllowedConstructionProfile(...)` exposes the profile only after `construction.commit` handler entry succeeds. Profiles encode proposal-specified values such as Cove 20% gold discount, Fortress 25% wood/ore discount, Tower 50% surcharge, Inferno 25% sacrifice threshold, and Stronghold 20% ore discount, plus proof requirements for allowlists, displayed/charged cost parity, capture tokens, mature dwelling state, elemental mapping, garrison sacrifice, and deathworks credit. They do not authorize construction mutation before commit/charge ordering is proven.
- Live bridge metadata proof on June 18 confirmed runtime ordinal matches for `law.spellCooldown.effectiveCooldown`, `law.spellCooldown.decrementCooldown`, `law.spellCooldown.addCooldownIfReady`, and `law.spellCooldown.poolCooldownShift`; proof artifacts live under `experiments/cpp2il_readable_csharp/samples/latest_refresh/live_bridge_proofs`. `law.spellCooldown.setCooldown` is intentionally not promoted because the live bridge ranked an ordinal-match method with the wrong return type ahead of the static signature candidate.
- `Homm3SpellCooldownNativeAdapter` now centralizes exact native cooldown reads and mutations for future law handlers. It resolves only `GameSymbols.SpellCooldownLaws` exact names, uses native methods rather than raw `eew.cfxk` field writes, and fails closed if `setCooldown` remains unresolved. This is source-prepared infrastructure only: no Harmony hook registers it, no gameplay calls it yet, and spell cooldown packets still have `gameplayAllowed=false`.
- `Homm3SpellCastGateNativeAdapter` now centralizes exact native cast-gate reads for `law.spellCastGate.cooldownReadiness`, `law.spellCastGate.fullCastGate`, `law.spellCastGate.spellCounterGate`, and `law.spellCastGate.indexSelectionGate`. It does not alter readiness, bypass gates, cache spell availability, or synchronize spellbook UI; it is an exact read-only adapter for future spell handlers after packet proof is promoted.
- `Homm3CustomSpellCooldownLawRuntime` now provides packet-gated cooldown entry points that require an explicit law owner and battle spell object, enter `spell.cooldown` through `Homm3CustomLawHandlerRegistry`, and call only `Homm3SpellCooldownNativeAdapter`. It registers no hooks and should remain unreachable until spell-cooldown packet proof is promoted.
- `Homm3CustomLawEffectProfiles` now centralizes source-prepared spell cooldown profiles for Castle, Cove, Dungeon, Fortress, Rampart, Tower, Conflux, Inferno, Necropolis, and Stronghold. `Homm3CustomSpellCooldownLawRuntime.TryGetAllowedSpellCooldownProfile(...)` exposes the profile only after `spell.cooldown` handler entry succeeds. Profiles encode proposal-specified `-1` cooldown reductions where applicable and proof requirements such as exact spell school/SID classification, support/blessing classification, movement/storm/sea spells, Night/curse spells, enemy slow/poison/mire state, Avenger mark, Tower overclock credit and cast-gate override, elemental family mapping, sacrifice/temporary loss, corpse consumption, and real Warcry execution. They do not authorize cooldown mutation, cast-gate override, or spellbook UI synchronization.
- Refreshed static dossier evidence on June 18 maps `law.morale.positiveRoll` to generated `eep.Method_Public_Boolean_Unit_Random_0` and `law.morale.negativeRoll` to generated `eep.Method_Public_Boolean_Unit_Random_Boolean_PDM_0` with type-callable ordinal + signature shape. These names are centralized for exact diagnostic registration only. `Homm3MoraleTriggerLawDiagnostics` still logs shared `handlerGate` state for `morale.package` and `morale.trigger`, and `Homm3MoraleTriggerNativeAdapter` centralizes exact positive/negative morale roll resolution/classification for future handlers without invoking rolls or mutating action scheduling. Morale gameplay remains blocked on runtime semantic ordering evidence.
- `Homm3FocusNativeAdapter` now centralizes exact Focus/Energy payload reads for `EnergyUpdateEventArgs.side/energyDelta/energy/energyDistribution`, `EnergyUpdatedByMechEventArgs.side/type/delta`, and `SideUsedEnergyEventArgs.whoChangedEnergy/delta`, plus exact hero ability energy metadata members already used by Focus diagnostics. It does not grant, spend, or normalize Focus and does not register hooks; Focus-dependent laws remain blocked on native storage mutation and UI synchronization proof.

## Packet summary

| Packet | Static confidence | Decomp-proven anchors | Still missing before gameplay |
| --- | --- | --- | --- |
| `morale` | High for trigger detection | `Hex.eep.bdhu(Unit, Random)` / generated `Method_Public_Boolean_Unit_Random_0`, `Hex.eep.grw(Unit, Random, bool)` / generated `Method_Public_Boolean_Unit_Random_Boolean_PDM_0`, decomp-allowlisted `bdht/bdhu/bxb/bxf/cam/grw/jmj` Unit/Random bool candidates, multiple ISIL call sites | Positive/negative morale semantic ordering and exact trigger phase in user combat |
| `construction` | High for UI/cost observation, medium for commit | `BhUIBuildingSession.tuc(int,int)`, `BhUIBuildingSession.tud(bfh)`, `BhBuildingView.trr(...)`, `BhBuildingView.UpdateView()`, `BhBuildingView.tsi(ResNameAndCost[])`, `BuildingsData.todaysConstructionsCount`, `BuildingData.bgck(int,bool)` | Exact commit/charge order tying displayed cost, charged resources, build count, and `BuildingData.isConstructed` |
| `committed-damage` | High for battle damage event observation, unresolved for final unit-damage mutation | `ObjectTookDamageEventArgs`, `ObjectDestroyedEventArgs`, DiffableCs-only `Unit.bbgw(...)`, `Sentry/Obstacle.bbgw(...)`, `EMechType` damage/source values | Exact final committed point for units with complete ISIL/runtime mapping, not just DiffableCs declaration or sentry/obstacle proof; counterattack classification |
| `counterattack` | Medium for ability classification; old command/resolver path is stale | `EAbilityType.CounterAttack = 2`, `dxx.barb/bgl(EAbilityType,int,out dxy)` generated resolver candidates, ability-change listeners `ebv.bbwi/jsd/nhw(Unit,EAbilityType,int)`, `dxy` change-event factories, same damage/event anchors. `cty.hrl` and `een.bdhu/gsq` are currently disabled as stale. | Runtime packet integration tying exact ability classification to the later committed damage event and active custom law/rank |
| `battle-action` | Medium-high for movement/cast events | `UnitStartedMovementEventArgs`, `UnitPosChangedEventArgs`, `StepEventArgs`, `CastMagicEventArgs`, `CastHeroAbilityEventArgs` | Event publisher/subscriber mapping and turn/action ordering |
| `spell-cooldown` | Medium for spellbook/cast surfaces, low for cooldown storage | `HeroMagics`, `DataMagics`, `MagicCounterSet`, `SideMagic`, `SideMagicData`, `BhMagicItemView.Show(...)`, `BhMagicBookView.UpdateView(...)`, `CastMagicEventArgs` | Actual stored cooldown/gate field or method; whether `MagicCounterSet` only aggregates stats; UI synchronization path |
| `reward-result` | Medium for reward/economy data, medium for resource mutation semantics, medium for exact apply-method observation | `czy.vji(Hero,DataRewardSet)`, `DataReward`, `DataRewardSet`, `DataRewardSets.bfus/bfut`, `Resource.bggu/bggv/bggw/bggx`, `ResHeap.bggt` | Runtime idempotence/source identity tying an apply call and later resource mutation to one reward/capture |
| `vision` | Medium for object scouting, low for fog reveal mutation | `DataFogOfWar.visibilityMap`, `DataFogOfWar.bfrj/bfrk/bfrl`, `DataObject.sideScoutings`, `DataObject.bgdo(int)`, `DataObjects` typed object lists | Exact fog reveal mutation method and ordering versus side scouting/object visibility |

## Morale packet

### Proven

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/eep.cs` declares morale-shaped methods: `bdhu(Unit, Random)`, `grw(Unit, Random, bool)`, `bdht(Unit, Random, bool)`, `jmj(Unit, Random)`, `bxb`, `cam`, and `bxf`.
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/eep.txt` contains exact method entries for `System.Boolean bdhu(Hex.Session.Battle.Unit a, System.Random b)` and `System.Boolean grw(Hex.Session.Battle.Unit a, System.Random b, System.Boolean c)`.
- ISIL contains multiple call sites for `eep.bdhu` and `eep.bdht`.

### Inferred

- `bdhu(Unit, Random)` and `grw(Unit, Random, bool)` are strong native trigger candidates because they directly consume battle `Unit` plus RNG and return a boolean.
- `eep.cs` also declares `bdht`, `bxb`, `bxf`, `cam`, and `jmj` with the same Unit/Random morale-like shape. These remain inventory/correlation candidates only; the diagnostic registration path patches the centralized exact positive/negative roll names and generated ordinal+signature candidates, not a broad Unit/Random allowlist.
- The diagnostic path should patch only centralized exact names, not broad bool-method discovery.
- `Homm3MoraleTriggerNativeAdapter.MoraleRollObservation` and `Homm3CustomMoraleLawRuntime.TryObserveAllowedMoraleRollResultForUnit(...)` now carry the exact roll kind plus raw boolean result behind the existing packet gate. The field names intentionally say `PositiveCandidateReturnedTrue` and `NegativeCandidateReturnedTrue`; they do not assert that `true` means a real morale trigger until runtime semantic ordering is proven.
- `Homm3CustomLawEffectProfiles` now centralizes source-prepared morale profiles for Castle, Cove, Dungeon, Fortress, Rampart, Tower, Conflux, Inferno, Necropolis, and Stronghold. These profiles encode effect intent and required side-channel proofs such as opposing-side owner, kill/loss event, spellcast event, elemental mix, gated/sacrifice identity, and corpse context. They do not mutate gameplay and remain packet-gated through `Homm3CustomMoraleLawRuntime`.

### Still required

- A combat capture that logs one known morale trigger and correlates which candidate method fired.
- Classification of positive morale, negative morale, and check-but-no-trigger paths. Do not enable morale laws from a boolean return until the trigger meaning is proven.

## Construction packet

### June 18 live bridge metadata update

Read-only `resolve_decomp_method` proof artifacts under `experiments/cpp2il_readable_csharp/samples/latest_refresh/live_bridge_proofs` confirmed runtime ordinal matches for:

- `law.construction.buildingsManager.stateCandidate`
- `law.construction.buildingsManager.refreshCandidate`
- `law.construction.buildingSession.costCandidate`
- `law.construction.buildingSession.selectCandidate`
- `law.construction.buildingView.bindCandidate`
- `law.construction.buildingView.updateCandidate`
- `law.construction.buildingView.costCheckCandidate`
- `law.constructionCommit.buildingData.constructStateMutation`

`GameSymbols` now includes the generated names for the non-obvious candidates. `Homm3CustomConstructionLawDiagnostics` consumes full `NameHints` and now refuses signature-only binding after exact names miss, so the next build can register either obfuscated or generated exact names without shape fallback. This is metadata proof only; construction laws still require runtime ordering proof tying displayed cost, charged resources, build count, and constructed-state mutation together.

`Homm3ConstructionNativeAdapter` now centralizes exact native construction state operations for future law handlers. It resolves `BuildingData.bgck(int,bool)` / generated `Method_Public_Void_Int32_Boolean_0` and `BuildingsData.todaysConstructionsCount` by exact symbol only. It deliberately does not invoke UI cost/eligibility observation methods as gameplay and treats those UI surfaces as optional descriptive observations because ordering and one parameter-shape caveat remain unresolved. No hook calls this adapter yet; construction packet gameplay remains gated off.

### Proven

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/UI/City/BhUIBuildingSession.cs` declares `private int tuc(int a, int b)` and `public void tud(bfh a)`.
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/UI/City/BhBuildingView.cs` declares `trr(fbs,dwc,int)`, `UpdateView()`, and `private bool tsi(ResNameAndCost[] a)`.
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/Data/BuildingsData.cs` declares `public int todaysConstructionsCount`.
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/Data/BuildingData.cs` declares `sid`, `level`, `isConstructed`, `citySid`, `bansPerLevel`, `levelOnStart`, and `public void bgck(int a, bool b)`.

### Inferred

- `BhBuildingView.tsi(ResNameAndCost[])` is a native cost/eligibility check candidate.
- `BuildingData.bgck(int,bool)` is a likely construction state mutation candidate.
- `BuildingsData.todaysConstructionsCount` is likely the native daily construction counter.

### Still required

- One user-driven town construction capture that proves displayed cost, eligibility, charged resources, `todaysConstructionsCount`, and constructed-state mutation in one sequence.
- Exact build commit surface. UI cost visibility is not enough to implement cost laws safely.

## Committed-damage packet

### Proven

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/Battle/Unit.cs` declares `public virtual void bbgw(eab a, eac b, dzx c, int d, EMechType e, bool f = false, float g = 0, bool h = true)`.
- `Sentry.cs` and `Obstacle.cs` also declare `bbgw(...)`.
- `ObjectTookDamageEventArgs.cs` exposes `caster`, `castSource`, `damageReceiver`, `dealer`, `damage`, `stacksDestroyed`, `immuneToDamage`, `visualDelay`, `cumulative`, and `fromMech`.
- `ObjectDestroyedEventArgs.cs` exposes `castSource`, `caster`, `destroyedObject`, and `isTimeout`.
- ISIL for `Sentry.txt` and `Obstacle.txt` creates `ObjectTookDamageEventArgs` and `ObjectDestroyedEventArgs` during `bbgw(...)`.
- `EMechType.cs` includes useful source/mechanic values such as `AdditionalDamage`, `AddEnergy`, `ReduceCounters`, `RefreshSpellBook`, `RemoveUnitCd`, `Reveal`, and `RevengeDamage`.

### Inferred

- `ObjectTookDamageEventArgs.damage` is the best native observation point for committed damage.
- `ObjectDestroyedEventArgs.destroyedObject` is the best native observation point for death/corpse follow-up.

### Still required

- ISIL or live confirmation for the `Unit.bbgw(...)` body, not only `Sentry`/`Obstacle`.
- Ordering proof that the event fires after final reductions/immunity and before post-death cleanup for unit targets.

## Counterattack packet

### Safety correction from June 17 crash

Broad `BattleEventArgs` dispatcher probing is not safe for this packet. A map-load crash was traced to `Homm3CounterattackCorrelationLawDiagnostics` accepting hundreds of generated `BattleEventArgs` signature patches, including recursive `ObjectPublicPrcfEvPrcf1BaPrcfEvUnique::Method_Public_Void_Object_BattleEventArgs_PDM_17` calls. Do not revive that approach.

Counterattack work should be decomp-first and exact-surface-first:

- Patch exact attack command/resolver/ability methods only.
- Do not accept signature matches after exact names fail; add decomp/runtime-proven generated names to `GameSymbols` instead.
- Treat generic event-bus dispatchers as off-limits unless a specific method is proven by decomp and runtime evidence.
- Use damage events only after a counterattack context has been established by an exact command/resolver/ability surface.
- Current source direction: `Homm3CounterattackCorrelationLawDiagnostics` no longer registers battle-event dispatch patches. It traces exact command/resolver candidates if found and exact `ebv.bbwi/jsd/nhw(Unit,EAbilityType,int)` ability-listener methods for ability-type context.

### Proven

- The same damage anchors apply: `ObjectTookDamageEventArgs`, `ObjectDestroyedEventArgs`, and `bbgw(...)`.
- `EMechType.ReduceCounters = 39` exists in the current enum.
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/ebv.cs` declares exact ability-event listener shapes `bbwi(Unit,EAbilityType,int)`, `jsd(Unit,EAbilityType,int)`, and `nhw(Unit,EAbilityType,int)`. These are better counterattack diagnostic candidates than generic `BattleEventArgs` dispatchers because the ability type is explicit in the method signature.
- Live bridge metadata on June 18 resolved `bbwi` to generated `Method_Public_Void_Unit_EAbilityType_Int32_PDM_0` with ordinal+shape agreement, and exposed two additional same-shape generated methods `Method_Public_Void_Unit_EAbilityType_Int32_PDM_1` and `Method_Public_Void_Unit_EAbilityType_Int32_PDM_2`. Because `jsd/nhw` individual ordinal resolution is ambiguous, these are centralized only as the exact three-method listener set.
- `Homm3CustomCounterattackLawRuntime.CounterattackAbilityObservation` and `TryObserveCounterattackAbility(...)` now carry the exact ability-listener unit, `EAbilityType`, and ability index for diagnostics. `IsCounterAttackCandidate` means only that the exact ability listener reported `EAbilityType.CounterAttack`; it is not committed-damage correlation proof.
- `Homm3CustomLawEffectProfiles` now centralizes source-prepared counterattack doctrine profiles for Castle, Cove, Dungeon, Fortress, Rampart, Tower, Conflux, Inferno, Necropolis, and Stronghold. These profiles encode data-only rows, Focus deltas, damage percentages, attack debuffs, counter charges, drain percentages, and proof requirements such as Avenger mark, target outnumbering, hero Spell Power, and separate magic damage surfaces. They do not mutate gameplay and remain packet-gated through `Homm3CustomCounterattackLawRuntime`.
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/dxx.cs` declares exact ability resolver shapes `barb(EAbilityType,int,out dxy)` and `bgl(EAbilityType,int,out dxy)`. Live bridge metadata on June 18 exposed the corresponding generated resolver-shaped methods `Method_Public_Boolean_EAbilityType_Int32_byref_ObjectPublicObceInBoInceAbObELInUnique_0` and `Method_Public_Boolean_EAbilityType_Int32_byref_ObjectPublicObceInBoInceAbObELInUnique_PDM_0`; use them only as the exact two-method resolver set, not as signature fallback permission.
- Existing project evidence in `AGENT_REBUILD_AND_MAINTENANCE.md` records the native battle attack command path:
  - `cty : bfh` is the `BattleAttack` command.
  - `cty.hrl()` resolves the attacker battle/session, validates the target, calls `dxr.banq(EAbilityType, int, out dxs)` using command fields `bzxg` and `bzxh`, then calls `cyt.vaz(...)` and `een.bdhr(..., bool=false, bool=false)`.
  - `EAbilityType.CounterAttack` is value `2`.
  - `EAbilityType.DefaultAttack` was observed as value `1` in prior command probe output.
  - `een.bdhu(Unit, Unit, int[], dxs ability, int[], int, bool)` walks affected target units and participates in counter scheduling.
  - `een.gsq(...)` is a duplicate-bodied resolver alias that existing diagnostics patched alongside `een.bdhu`.

### Inferred

- Counterattack laws should be implemented by correlating exact ability classification with committed damage, not by animation state or by broad "damage happened after attack" logic.
- The current safe diagnostic path is generated/obfuscated `dxx.barb/bgl(...)`, exact `ebv.bbwi/jsd/nhw(Unit,EAbilityType,int)` listener names, and `dxy` change-event factories, then a future short-lived classification into exact committed-damage diagnostics. `cty.hrl` and `een.bdhu/gsq` are stale in the refreshed dossier and must not be used until a new exact dossier or runtime metadata proof replaces them.
- `BattleEventArgs` listener classes contain many same-signature methods. Signature-only matching on those classes is a known unsafe fallback and must fail closed.

### Still required

- Runtime proof that `EAbilityType.CounterAttack = 2`, the resolver call context, or `ebv` ability callbacks cleanly identify actual retaliations in the current build.
- A correlation key from command/resolver phase to `ObjectTookDamageEventArgs` so custom law effects apply only to the committed damage caused by that counterattack.
- Proof that normal attacks, counterattacks, special follow-up attacks, and revenge/additional damage are separated.

## Battle-action packet

### Proven

- `UnitStartedMovementEventArgs.cs` exposes `moveTime`, `startTime`, `pathLength`, `id`, `switchSoundToFly`, `moveType`, and `path`.
- `UnitPosChangedEventArgs.cs` exposes `targetHex` and stores the acting `Unit` in the constructor.
- `StepEventArgs.cs` exposes `step` and receives a target `Unit` in the constructor.
- `CastMagicEventArgs.cs` exposes `casterSide`, `castedMagic`, `castTargetHexes`, `filteredCastTargetHexes`, `affectedAoeHexes`, `attackedObjects`, and `immuneObjectsOut`.
- `CastHeroAbilityEventArgs.cs` exposes analogous hero ability fields with `castedAbility`.

### Inferred

- Movement and cast laws can probably be observed through event args without UI scraping.
- Spell/ability cast events are safer than spellbook UI events for battle gameplay.

### Still required

- Publisher/subscriber mapping: where these `BattleEventArgs` are emitted and in which order relative to action resolution.
- Runtime proof for wait/defend/move/attack/cast/hero ability discrimination.

## Spell-cooldown packet

### Proven

- `HeroMagics.cs` declares `list`, `bfxw(string)` lookup, `bfxx(HeroMagics)` copy, and `bfxy()` count.
- `DataMagics.cs` declares `bftu(string)` lookup and `bftw(string)` index lookup.
- `MagicCounterSet.cs` declares `perSchoolStats`, `bgaz(MagicPerSchoolStat)`, `bgba(MagicCounterSet)`, and `bgbb(MagicCounterSet)`.
- `SideMagic.cs` declares `sid`, `isLearned`, `upgradeLevel`, `wasCustomUpgrade`, `MagicConfig chww`, `bgin()`, `bgio(string)`, and `bgip()`.
- `SideMagicData.cs` declares `sidConfig`, `isOpened`, `indexInPool`, and `MagicConfig chwx`.
- `BhMagicItemView.cs` declares `Show(dtl _magic, fda _side, dtm _sideMagics, Action _onCastAction, bool _learnedInCity)`.
- `BhMagicBookView.cs` declares `Init(dva _magicBook)` and `UpdateView(int _targetPage, BhMagicBookPageView _page, int _compare = 0)`.
- `CastMagicEventArgs` provides a native spell-cast observation surface.

### Inferred

- `MagicCounterSet` is likely stat aggregation, not necessarily cooldown storage.
- `BhMagicItemView.Show(...)` and `BhMagicBookView.UpdateView(...)` are useful UI synchronization probes, but should not be treated as gameplay gates.
- Actual cooldown behavior may be represented in the obfuscated `eew`/`edn` runtime magic/ability objects rather than side magic data rows.

### Still required

- Exact stored cooldown field or method for spells.
- Exact cast gate check.
- Proof that spellbook UI, stored cooldown, and cast gate remain synchronized after mutation.

## Reward-result packet

### Proven

- `DataReward.cs` declares reward identity and presentation fields: `stringRewardType`, `rewardType`, `rewardShowType`, `applyRewardFloating`, `rewardIcon`, `rewardName`, `rewardDesc`, `rewardNotificationDesc`, and `parameters`.
- `DataRewardSet.cs` declares `showType`, `applyType`, `cancelType`, `ResNameAndCost[] cost`, `cantCompleteApplying`, `List rewards`, `id`, `heroId`, `objectId`, `label`, and `selectionWindowType`.
- `DataRewardSets.cs` declares `list`, `freeId`, `bfur()`, `bfus(DataRewardSet)`, and `bfut(DataRewardSet)`.
- `Resource.cs` declares `bggu(int)`, `bggv(int)`, `bggw(int)`, and `bggx(int)`.
- `ResHeap.cs` declares resource fields for gold, wood, ore, gemstones, crystals, mercury, dust, graal, and starDust, plus `bggt(ResHeap,bool)`.
- ISIL proves `Resource.bggu(int)` sets `value` exactly to the argument.
- ISIL proves `Resource.bggv(int)` adds the argument to `value`.
- ISIL proves `Resource.bggw(int)` checks `value >= argument`, subtracts the argument only if available, and returns whether subtraction happened.
- ISIL proves `Resource.bggx(int)` is a non-mutating `value >= argument` check.

### Inferred

- `DataRewardSets.bfus/bfut` are reward queue mutation surfaces, not necessarily reward acceptance.
- `Resource` methods are native resource value surfaces with assigned semantics, but observing one resource mutation is still not enough to classify the source as reward, construction, daily income, or another mechanic.
- `ResHeap.bggt(ResHeap,bool)` is likely a heap-level apply/check helper that calls per-resource logic; exact boolean parameter semantics still need runtime/source-order correlation.

### Still required

- Exact reward acceptance/commit method.
- Idempotence key tying one committed reward to one custom law grant.
- Runtime correlation between reward/capture/building events and `Resource`/`ResHeap` calls.

## Vision packet

### Proven

- `DataFogOfWar.cs` declares `visibilityMap`, `sizeX`, `sizeZ`, `bfri(int,int)`, `bfrj(int)`, `bfrk()`, and `bfrl()`.
- ISIL for `Side.txt` constructs `DataFogOfWar` and calls `DataFogOfWar.bfri(sizeX, sizeZ)`.
- `DataObject.cs` declares `sideScoutings`, `released`, `ownerSide`, `isNeutralObj`, `sidConfig`, `idMapObject`, and related object-state fields.
- `DataObject.bgdo(int)` checks `sideScoutings.Contains(side)` and adds the side if absent.
- `DataObjects.cs` declares typed object lists including resources, mines, cities, markets, taverns, portals, chests, prisons, quest guards, shipyards, obelisks, garrisons, monsters, and pocket dimensions.

### Inferred

- `DataObject.bgdo(int)` is a strong object-scouting marker.
- `DataFogOfWar.visibilityMap` is a native data target, but not yet a safe mutation surface because the reveal/update method has not been identified.
- `DataObjects` typed lists can support object classification for vision law predicates.

### Still required

- Exact fog reveal mutation method.
- Runtime proof that object scouting and tile fog visibility are updated in the expected order.
- UI/map refresh method after reveal mutation.

## Next implementation impact

The decomp pass makes these packets plausible enough for diagnostic-first implementation:

- `morale`: exact signature patching is justified.
- `construction`: add/keep diagnostics for `BhBuildingView.tsi(...)`, `BuildingData.bgck(...)`, `BuildingsData.todaysConstructionsCount`, and resource mutation during build.
- `committed-damage`: add event diagnostics around `ObjectTookDamageEventArgs` and `ObjectDestroyedEventArgs`, with unit-target verification.
- `battle-action`: add event diagnostics for movement and cast event args.
- `vision`: add read-only diagnostics for `DataObject.bgdo(int)` and `DataFogOfWar` state, but do not mutate fog yet.

These packets still need more decomp or runtime proof before gameplay work:

- `spell-cooldown`: cooldown storage and gate are unresolved.
- `reward-result`: committed reward acceptance is unresolved.
- `counterattack`: command/resolver discriminators exist, but they still need current-build packet integration and committed-damage correlation.
