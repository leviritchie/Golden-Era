# Custom-law runtime hooks on live build 25672315 (2026-10-21)

Static trace (Ghidra, raw disassembly, global-metadata v31, live GE interop, GE Core.zip) of the five hooks the abandoned law
runtimes need. Round 2 closed every "needs runtime proof" item from code and shipped data: **no open runtime unknowns remain**.
Per-hook reports and evidence: `V:\olden_port_work\law_hooks_25672315\<hook>\REPORT.md` (round 1) and `<hook>\r2\REPORT.md`.
Reusable string-literal decryptor: `cooldown\r2\oe_strlit.py` / `morale\r2\strdec.py`.

## Hooks

| Hook | Live hook (native / interop / VA) | Proven facts (round 2) | Laws |
|---|---|---|---|
| Kill | postfix enb `bfmq` `Method_Public_Void_Object_BattleEventArgs_63` (0x1820E7930, ObjectTookDamage, pinned) + enb `bfmu` `..._47` (0x1820E7F10, ObjectDestroyed, new pin tok 100707364) | Once per death (early-out if dead). Kill = bikt-path death, or bikq from `eqi` (assasinate) / `eqv` (destroy_summon); bikq from `equ` destroy_self, `esf` summon_with_buff, `ext` substitute and `bikr` lifetime expiry are not kills (caster may be non-null). Mark real kills with prefixes on eqi.bgty / eqv.bgua/bgvq. bfmu also fires for FieldObject/Obstacle/Sentry: filter Unit. The old map-load overflow was an ordinal-guessed folded stub (golden eda Method_34); bfmq/bfmu are unique bodies and the `_63` postfix already runs in the live GE log. No flag pilot needed. | 12 trigger-side + exact per-kill counts (Necropolis corpse, Soul Contract) |
| Counterattack | postfix `etm.bhdy` CounterAttackStep.Begin `Object1PublicObcmInSicmBoUncmUncmUnique.Method_Public_Virtual_Void_0` (0x1821ECC50), state==2; close on `etm.bhdz` -> 3 | Once per visible counter (ranged >1 hex: none; pre-attack: 1-2, each real; dead counterattacker: none). Damage lands in bhdz frames; attribute by `castSource == etm+0x30 && caster == etm+0x48`. numCounters 1/2/999 (999 = unlimited; negative = none). No native Focus on counters (type 2). Spell power = `HeroStat_2`. Debuffs via `ejz.bejp` need the plugin to raise BuffEventArgs (enb.bfms + enc.bfwg) and check immunity (ext.gpu). | 8 Counterstroke (index 13); Conflux needs a data mech |
| Spell cooldown | postfix `eoy.bgra` `Method_Public_Void_ObjectPublicPrclObPrclInTrPrclInUnique_PDM_0` (0x18217D9F0); write `field_Public_Int32_0` | Once per paid cast (waves/echo skip). All UI/AI readers read the field live. Free-cast flags only set by cheats. Per-round limits from HeroStat (Tower: 1 cast, 1 same-spell, 1 same-school). | conflux/cove/dungeon/inferno/tower 34 |
| Focus | call `side.clyg.bhco(n)` (Void_Int32_0, tok 100710566) / `bhcn` (Void_Int32_1, tok 100710572) | Raises EnergyUpdate on the live bus; BhEnergyView redraws. Pin by token (a _0/_1 swap turns a grant into a spend). | cove 13/15/19 |
| Morale | postfix `eor.bgmj` (Boolean_Unit_Random_0, 0x182151060) good; `eor.bgmi` (Boolean_Unit_Random_Boolean_0, 0x182150E50) bad | Good roll : popup is 1:1. Bad popups also come from forced skips (`UnitData.cncc`) and dead-at-turn-start, so hook enc.bfwm / bgmb prefix for "all bad morale". bigr literal = "skip_turn" (stun/sleep/petrify skip, no popup). Opponent = `TB.sides[w.Int32_0 == 0 ? 1 : 0]`. | 6 of 10 index-25 (needs product decision, below) |
| Resource spend | call wallet `ecc.hhn` `ObjectPublicObchBoObchctchObUnique.Method_Public_Boolean_String_Int32_0` (0x183148010); check `bbqg`, add `bbqe`; costs via postfix `egf.bdhc` (vslot 5) | HUD refreshes only on ResChange from hhn/bbqe. Every UI/logic cost reader goes through bdhc (postfix must clone the array). ConstructBuilding `egz.mab` (patch one alias only) is reached by player and AI; free builds bypass it. Skip clone wallets (`field_Private_Boolean_0`). | 4 row-28 construction laws |

## Simulated battles (all hooks)
Player auto-resolve (Options `Side.simulateBattle`, +0xf1) and AI-vs-AI battles run the real battle logic synchronously
(`djt.ypb` -> `eor.bglm`), so every hook fires there. If the player then chooses "Battle!", the battle replays interactively
and effects would fire twice. Discriminator: `eor.state(+0xb0)+0x60 != 0` (also enb `field_Public_Boolean_0`). Battle logic is
never cloned for AI look-ahead; the `ebg` unit sandbox never runs combat. **Design decision:** whether law effects apply in
simulations at all.

## Defects found in existing plugin code
Each was checked against the live interop; most explain why "implemented" runtimes do nothing today.

| Area | Defect | Fix |
|---|---|---|
| Battle events | `Homm3BattleEventNativeAdapter.TryReadDamageEvent` / `TryReadDestroyedEvent` type-check the BattleEventArgs wrapper with `IsInstanceOfType`, so they always fail (live log: "damage read failed" 3/3). Also breaks `SurfaceIngress.NormalizeObjectDestroyed` and `Homm3RuntimeMechanicHooks.cs:402`. | Native class check, then re-wrap `new ObjectTookDamageEventArgs(ptr)` |
| Owner registry | `Homm3BattleUnitLawOwnerRegistry.cs:288` reads the world-index-keyed `SideIndexToDataSide` with the battle-local index, so owners are wrong whenever world order differs (neutrals can inherit map player 1's laws). The `:298` bridge fallback passes the wrapper instead of `nativeTransferSide`. Preseed runs only with diagnostics on, and the map is cleared after every battle. The `ebg` sandbox registers dummy units. | Separate battle-local map seeded eagerly in `PostfixUnitInit` via the logicHero bridge (skip index < 0); no opposite-side API exists yet |
| Spell cooldown | `Homm3CustomSpellCooldownLawRuntime` patches folded `bgqz` (zero callers; also detours PDM_0/1). `EffectiveCooldown` (`bgqu`) is the spell level. The SetCooldown hint can't be resolved, and spell-pool member hints are native names, so they all fail closed. | Move to the bgra postfix + field write |
| Counterattack | `Homm3CounterattackDoctrineMutationRuntime` hooks the ChangeAbility factory `eib.bdwf` (cooldown/charge setters only). | Move to the etm.bhdy/bhdz window |
| Morale | `NegativeMoraleRoll` pin is the dead PDM `nwv`. `PostfixMoraleRoll` applies to every `__args` entry. There is no simulation filter. The armed one-shot damage consumer (TrainingDamage) is disabled and forbidden. Dungeon/Necropolis have no mutator. | Pin bgmi, use `__args[0]` |
| Construction | `BuildingConstructStateMutation` is pinned to `BuildingData.bjjz` = **SetBanned(level, bool)**: `TrySetConstructedState` would ban levels. None of the row-28 laws is wired to a game method. | Use egz.mab / egf.bdhg / egf.bdhc |
| Resources | `ResHeapOreMembers = {"ore"}`, but live is `field_Public_Resource_0`, so ore lookups fail closed. Swashbuckler gold, Cove plunder and reward-economy add/set/spend bypass ResChange, so the HUD stays stale and quests/statistics miss the change. | Route through ecc.hhn / bbqe |

## Data bugs (no runtime needed)
- **rampart_17 Pegasus Screens, bulwark_34, factory_34**: `heroStatBattle magicCdBonus +1` without `receiverAllegiance`. The decrypted default is `"ally"`, so they lengthen the **owner's** cooldowns. Fix: `"receiverAllegiance":"enemy"`. Audit every custom bonus that omits the field.
- **fortress_34 Bog Hex** can be pure data with the same `magicCdBonus` + `"enemy"` shape. The live row is `inComingBuffDuration +1`, which disagrees with docs.
- **castle_31** promises Focus but grants a dragon-father set-bonus buff. Native fix: an `energyPerRound` unitStat.
- **tower 15/27** do not ship as cooldown laws (mana cost / school space); "tier-1 no cooldown" exists only behind a pilot flag.

## Product decisions before building
1. **Restore the runtime law designs?** Law index 25 (morale) and most runtime designs were deliberately replaced by native-data rows in 2a2aa29be1 (2026-06-25). The shipped text describes native bonuses, and `validate_gameplay_surface_runtime_candidate_coverage.py` forbids re-registering these runtimes.
2. **Simulated battles**: do law effects apply in auto-resolve / AI-vs-AI simulations?
3. **Conflux counterstroke**: the magic damage component needs a data mech on the counter ability, not runtime.

## Build order if approved
1. Fix the shared defects first: battle-event reader, owner registry, simulation filter. Everything depends on them.
2. Kill bus + counter window (trigger sources most laws need).
3. Cooldown postfix, morale re-pin, wallet swap + bdhc cost postfix.
4. Per-law effects; data-bug fixes ship independently and immediately.
