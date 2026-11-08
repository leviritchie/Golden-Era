# Battle State Logic Map (Running)

Status: active research log. Movement static commit-store dossier **finished** (Iteration 11; no Phase 3). Not gameplay proof. Not a ship contract for MovementPush.

Next-agent scope for movement: runtime/`emz`/English-name hypotheses only — see `docs/direct_state_movement_static_trace_handoff.md`. Do not reopen static Phase 3, donor restore, or incomplete dual-write.

Purpose: map how Olden Era battle state actually works — occupancy, movement, actions, events, and view — in one coherent pass. Trace native call chains to discover **ordered stores**; the direct-state manager owns those stores. Do not invent fields/events, and do not treat donor restore as proof.

## Method

Each iteration must:

1. Add or revise **claims** with an evidence label (below).
2. Run a **contradiction pass** against prior claims; record wins/losses.
3. Prefer one reverse chain at a time, but place findings on the **global model** (domains below), not a single-mechanic silo.
4. Forbid shipping or re-enabling hex mutation from this doc until a claim is promoted to at least **runtime behavior proven** for that mutation path.

### Evidence labels (strict)

| Label | Meaning |
|---|---|
| `source/static` | dump / ISIL / Cecil / typed interop presence |
| `xref` | call-graph or surface-xref tree link |
| `live-negative` | combat/runtime proved something does **not** work |
| `live-positive` | combat/runtime proved observable behavior |
| `hypothesis` | useful guess; must not drive writes |
| `contradicted` | withdrawn; keep for history |

### Contradiction rules

- A `live-negative` beats any `source/static` or `hypothesis` about the same API.
- Two `source/static` claims that imply different write owners → mark both `hypothesis` until one chain connects store → event → view.
- Do not resolve contradictions by adding silent fallbacks or a second write path.

## Global model (domains)

Fill these as one system. Empty sections are debt, not permission to invent.

1. **Identity** — Unit, Side, BattleLogic, FieldObject, Hex instance identity (managed wrap vs native ptr).
2. **Occupancy** — who owns “unit is on hex”; occupant field(s); blocked; multi-hex / footprint if any.
3. **Position authority** — which store `get_Hex` / drawer placement actually read; helper vs Unit vs Hex.
4. **Path / walk** — how a move or melee approach chooses hexes; when occupancy updates along the path.
5. **Action lifecycle** — StartAction / damage apply / EndAction / cast; when movement may legally mutate.
6. **Mechanics dispatch** — config `targetMechanics` / `selfMechanics` (e.g. `push_unit`) → native handler.
7. **Events** — `UnitStartedMovement`, `UnitPosChanged`, `OnUnitChangedHex`, damage events; payload vs side effects.
8. **View / ecz** — what listens; transform snap vs event-driven; donor visual overlays.
9. **Transaction / rollback** — whether native has atomic move; what our journal assumed wrongly.

### Domain fill (current)

| Domain | Current state | Key refs |
|---|---|---|
| Identity | Unit/FieldObject are IL2CPP wraps; hex identity compares must use native equality, not `ReferenceEquals` (pilot already CapLogs this). | S3 notes |
| Occupancy | Native push/walk commit updates **`Hex.fieldObjects` (`+0x28`)** via `Hex.bcyn`=`RemoveObject` / `Hex.bcyl`=`AddFieldObject` inside `edf.bcuo`, and refreshes `cfqg` (`+0x3A`). Mono Hex has **no** Unit occupant property. Live `Hex.cfqf` (`+0x30` / `bcxo`) pins to mono **`lastCorpse`**, not occupancy; **not** on the `bfdi` push path. Mod dual-writes of `_cfqf` remain insufficient (S4, S35–S36). | S14*, S27, S31–S32, S35–S36 |
| Position authority | Dump: helper `edf` get/set `bcsx`/`bcsy`. **Live GE DummyDll:** `edf.bcun()` / `edf.bcuo(Hex)` stores `edf+0x10`. Unit `get_Hex` / `ede.bcuh` read that helper. **Helper hex and `fieldObjects` are the connected commit stores; `cfqf` is separate.** | S13, S27, S31, S3, S4 |
| Path / walk | Walk publishes `UnitStartedMovementEventArgs` via `enb.bfcp`. Push uses a different visual/step (`emz` via `enb.bfcr`) and does **not** call `enb.bfcp` from `ejn.bdyi`. Occupancy/position commit for push lands in `UnitData.bfdi` during `emz.bfbe` tick. | S18, S25–S28, Q3 |
| Action lifecycle | DamageApplied-time occupancy mutation remains unsafe (`S10`). Frog Sticky Tongue is cast+hex-select, not mid-damage shove. Leap uses `attackType_=jump` with empty `targetMechanics` (landing push is not the `push_unit` row). | S16, S17 |
| Mechanics dispatch | Config `push_unit` ↔ `EMechType.PushUnit = 37`. **Live GE factory** is `egd.bdpz(eep, MechConfig) → egf` (jump table). **Dump `egb.bdoh` is a different obfuscation epoch — do not use dump `egb` as live factory.** Live PushUnit class = **`ehh`** (apply `ehh.bdpe`). Step: `ejn` (+ queue `ejr`). | S12, S15, S22–S25 |
| Events | **Hubs:** `eda`≈`BattleLogicEvents`, `edb`≈`BattleViewEvents` (S40). Push/walk **commit publish:** `eep.bdhw` → `eda.bcim` → **`eda.cfia` (`+0xC0`)** ≈ Logic **`OnUnitEndedMovement`** (ordinal-inferred — S41; live `eda` has 53 handlers vs mono 49). Logic `OnUnitChangedHex` ≈ `eda.cfhz` (`+0xB8`), **not** on `bfdi`/`bdhw` path. Prior `OnUnitChangedHex`↔`edb.cfkg` **withdrawn for live GE** (W11; `edb.cfkg`≈View `OnCrit`). View `UnitPosChanged` is View-hub, ≠ `bdhw`. Do not ship Method_N invent. | S20, S28, S33, S39–S42, S8, W2, W11 |
| View / ecz | Walk listens on `UnitStartedMovementEventArgs`. Push drives `emz` then `UnitData.bfdi`. View does not follow helper+`cfqf` dual-writes (`S4`). **Store coherence** does not require `emz` (S45); user-visible tween/snap necessity remains **hypothesis**. | S18, S25–S26, S34, S45 |
| Transaction / rollback | Closed commit owner: **`UnitData.bfdi`**. Prefer one invoke. Expanding `bdhv`→`bcuo`→`bdhw` is ordered but not three-way atomic if split. `edf.bcuo` alone is incomplete. Dual-write is not a substitute (W3/S4). | S27, S31–S34, W3 |

## Seed claims (2026-07-19, from Shoulder Check pilot)

| ID | Claim | Label | Notes |
|---|---|---|---|
| S1 | `BattleLogic.Method_Public_Void_Unit_Hex_0` does not publish unit hex / `get_Hex`. | `live-negative` | Retired as commit path. |
| S2 | Interop neighbour slots on Hex are `_cfqh`…`_cfqm` (not dump `<cfnv>` names). | `live-positive` / Cecil | Neighbour *reads* proven; not a write API. |
| S3 | Direct writes to position-helper `field_Private_Hex_0` + Hex occupant can make commit logs pass (`get_Hex` / dest occupant). | `live-positive` | Proves local write shape only. |
| S4 | Those writes do **not** constitute user-visible / coherent battle movement. | `live-negative` | No reliable visible shove; stacking / desync observed. |
| S5 | Enemy hex remaining occupied after a “successful” MovementPush commit contradicts any story that push clears the defender hex then attacker walks in. | `live-negative` (user) | Vacated-hex explanation **contradicted**; do not repeat. |
| S6 | `UnitPosChangedEventArgs(Unit, Hex)` and `UnitStartedMovementEventArgs(...)` exist as typed payloads. | `source/static` | dump.cs / DiffableCs. |
| S7 | Event hub semantics include Logic `OnUnitChangedHex` / movement family. | `xref` / `source/static` (family) | **Live GE field pin revised by W11/S40–S42:** Logic ChangedHex ≈ `eda.cfhz` (not `edb.cfkg`). Field map ≠ write body. |
| S8 | Golden Era hubs expose `Method_Public_Void_Object_BattleEventArgs_N`, not ISIL short names `bcqv`/`bcqt`. | `source/static` / Cecil | Method_N↔field ordinal correlation **unproven** (Skip Method_11 vs ordinal 15). |
| S9 | Config mechanic `push_unit` is a named native effect entry used by donors (e.g. giant_frog). | `source/static` | Stripped for Bellwether shell; best start for mechanics domain. |
| S10 | DamageApplied-time occupancy mutation races melee walk / action playback. | `hypothesis` | Timing domain; do not use to justify mid-damage writes. |
| S11 | Shoulder Check move-into-melee reshape put Bellwether onto/into the enemy hex visually while enemy occupancy remained. | `live-negative` | Ability envelope + unknown native pathing; not proof of our clear. |

### Claims added this research pass (2026-07-19)

| ID | Claim | Label | Notes |
|---|---|---|---|
| S12 | `EMechType.PushUnit = 37` exists; config key `push_unit` is the asset spelling. Dump-era factory type was `egb` with string→enum helpers; **live GE factory is `egd` (see S22)**. | `source/static` | Enum in dump + live DummyDll. String not in IL2CPP stringliteral table (asset/Core-driven). |
| S13 | Position store is helper `edf`: private Hex `cflf`, get `bcsx`, set `bcsy`. `FieldObject.cfkz` holds the helper. `ede.bcsr()` is the Unit `get_Hex` (`cnvr`). | `source/static` | Matches live `field_Private_Hex_0` write shape in S3. |
| S14 | *(superseded by S35–S36)* Earlier pass treated live `_cfqf` as Hex “occupant.” Mono has no Unit occupant; list `fieldObjects` is occupancy. Live `cfqf` pins to `lastCorpse`. | `contradicted` (occupant framing) | Keep only as history of the dual-write mistake. |
| S15 | Mono demo metadata names the movement mechanic family: `MechPushUnit` / `PushUnitStep` / `StepQueueProcessor` (plus Force/Random/Swap). | `source/static` | demo_hex_* interest JSON; live bindings closed in S23–S25 / S37. |
| S16 | Golden Era `giant_frog` abilities: **[0] Leap** = `attackType_=jump`, swirl pattern, **empty** `targetMechanics` (landing push is not a `push_unit` row). **[1] Sticky Tongue** = cast + hex select + `push_unit` values `["true","false"]`. Lang: Tongue **pulls** enemy into target empty hex. | `source/static` | Core.zip `giant_frog_l.json` + english `unitsAbility.json`. |
| S17 | Bellwether donor shell is `giant_frog:abilities:1` (Sticky Tongue), not Leap. **Prior** installed Core stripped that `push_unit` for MovementPush. **Iteration 7** tried restoring native `push_unit` with values `["false"]` under adjacent cast+damage (S30). Modeling as mid-damage dual-write shove remains wrong. | `source/static` / installed readback | Aligns with S11 envelope failure; restore attempt is **live-negative** (W8/S29) — not the ownership path. |
| S18 | `push_unit` MechConfig `values` across Core are almost always a single bool (`true` or `false`); frog Tongue is the rare two-bool form. Other unit donors: black_dragon alt, h3_wyvern alt; also several battle magics. | `source/static` | Core.zip catalog (19 rows). |
| S19 | Shared mechanic runtime has hex-pair entrypoints (dump: `ega.bdoc` / `egd.bdom`; live names drift). Several subclasses override hex-pair apply. **PushUnit does not use hex-pair `bdom` on live GE** — it uses receiver apply `ehh.bdpe` then step queue. | `source/static` | Superseded for PushUnit by S22–S25; hex-pair path still relevant for other mechs (e.g. live `eic`/`eie` `bdqe`). |
| S20 | ISIL field map: `bcqv` dispatches `cflf` / **OnUnitEndTacticsMovement** (and also appears on unknown `cfmw`). Call sites construct `UnitPosChangedEventArgs` then call `edb.bcqv`. Live `edb.bcqt` raises `edb.cfkg` (View ordinal 21 ≈ `OnCrit` per W11 — **not** Logic `OnUnitChangedHex`). | `xref` | Breaks UnitPosChanged ≡ ChangedHex. Do not reuse dump-era `cfkg`↔ChangedHex. Method_45/`bcqv` at best tactics-end — **not** a general hex-publish API. |
| S21 | Same failure mode as movement (symbol≠authoritative write path) is already documented for damage-hook identity (`eab` unwrap) and for Method_N event ordinal guesses. Other direct-state families remain source/static-only for mutation; they are not promoted by this pass. | `live-negative` (damage binding) / `source/static` | Cross-check only; movement stays first. |
| S22 | **Name drift:** June 1 `dump.cs` factory `egb.bdoh` RVAs do **not** match live Golden Era `GameAssembly` DummyDll. Live factory owner is **`egd`** with create API `egd.bdpz(eep, MechConfig) → egf` (plus batch `bdpy`/`bpe`/`dq`/`gez`/`moz`). Live type `egb` is a concrete mechanic (AddMagicCd), not the factory. | `source/static` | DummyDll AddressAttributes + live disasm of `egd.bdpz` (RVA `0x1FB62A0`, len `0x1738`). |
| S23 | Live `egd.bdpz` switches on `EMechType` via jump table (`index = value - 2`, max `0x41`). **Case 37 `PushUnit` → constructs `ehh`.** | `source/static` | Table at RVA `0x1FB79D8`; handler `0x181FB7440` → `ehh::.ctor`. |
| S24 | Live PushUnit apply entry is **`ehh.bdpe(eab,eac,InCastArgs,FieldObject,eaa)`** (mono `MechPushUnit.ApplyForReceiver`). It does **not** call `edf.bcuo` / `Hex.bcxo` inline. It computes destination hexes (`een.bdep`/`bdeo`, `eeu.bdke`, `Hex.bcyf`), constructs **`ejn`(eep, List of Unit, List of Hex)**, and enqueues via **`ejr.bdyq(ejt, Unit)`**. | `source/static` | `ehh.bdpe` RVA `0x1FD4AC0`. |
| S25 | Live mono aliases (**shape-static**): **`ejn` ≈ `PushUnitStep`** (`bdyi` Begin / `bdyj` Process); **`ejr` ≈ `StepQueueProcessor`** (`bdyq` Push, `bdyp` Process, …). `ejn.bdyi` calls `eep.bdhr(Unit)` then **`enb.bfcr(Hex)`** (not walk’s `enb.bfcp`). | `shape-static` / `hypothesis` for exact mono name equality | Field/method shape+callers; not uniform with `bcyl`/`bfdi` store pins; not a runtime rename proof. |
| S26 | `enb.bfcr` constructs **`emz`** and queues it (`enb.bfco`). `emz.bfbe(dt)` calls `UnitData.bfdh` then **`UnitData.bfdi(Hex)`** — this is the push commit into authoritative stores. Walk’s `enb.bfcp` is the path that constructs `UnitStartedMovementEventArgs` and `emw`. | `source/static` | Xrefs: `enb.bfcr` sole scanned caller = `ejn.bdyi`; `UnitStartedMovementEventArgs.ctor` callers = `enb.bfcp`/`kbq`/`kjw` only. |
| S27 | **Ordered position write body** (shared helper used by push commit): `UnitData.bfdi(Hex)` → (1) `eep.bdhv(Unit, Hex)` (2) **`edf.bcuo(Hex)`** (3) `eep.bdhw(Unit, Hex)`. Live position setter is `edf.bcuo` (dump-era `bcsy`). | `source/static` | `UnitData.bfdi` RVA `0x2078360`; also called from `emw.bfbh`/`bfbi`, `eev.bdks`, etc. |
| S28 | **Occupancy / publish (superseded in part by S31–S33):** earlier pass inferred occupancy through `bdhv`/`bdhw` and left `bcxo` open. Iteration 8 closes list occupancy inside `edf.bcuo` (`bcyl`/`bcyn`) and shows `bdhw` publish via `eda.bcim`→`cfia`. `emz` vs walk event parity for *view* remains hypothesis. | `source/static` + `hypothesis` (view only) | Do not invent Method_N publishes. |
| S29 | Bellwether **tried** native `push_unit` restore so `egd.bdpz` instantiates `ehh` under the donor cast envelope. That attempt is **live-negative** for intended shove (W8). Direct invoke of `ehh.bdpe` / `ejn` without context remains unproven; DS ownership target is `UnitData.bfdi` (S34), not donor restore. | `live-negative` (restore) / `hypothesis` (direct `ehh` invoke) | Do not expand restore architecture. |
| S30 | **2026-07-20 redesign:** Shoulder Check uses Schism T6 Arbitrator **Command: Fear** shape (`arbitrator:abilities:1`): ordered enemy+hex cast + native `teleport`, with `distanceFromFirst` tightened to **1**. Replaces failed adjacent `push_unit` away shove. DS MovementPush pilot stays disabled. | `source/static` (donor) | Combat live-positive pending after Core overlay apply. |
| S31 | **`eep.bdhv` / `eep.bdhw` are not occupant writers.** Both iterate `eep+0x98` and virtual-dispatch listeners (bdhv slot +6, bdhw slot +7). `bdhw` then calls `ede.bcuh` (helper hex read), `eep.bdhm`, constructs `BattleEventArgs`, and `eda.bcim`. | `source/static` / `xref` | Disasm RVAs `0x1F463F0` / `0x1F465D0` vs live GameAssembly. |
| S32 | **List occupancy on commit:** `edf.bcuo` calls `Hex.bcyn(FieldObject)` then stores `edf+0x10` then `Hex.bcyl(FieldObject)`. Those update `Hex.fieldObjects` (`+0x28`) and `cfqg` (`+0x3A`). Sole scanned callers of `bcyl`/`bcyn` outside obstacle/sentry init are `edf.bcuo` (+ `eep.bdhk` leave-only). | `source/static` / `xref` | Closes prior “occupant inside bdhv/bdhw” hypothesis. |
| S33 | **`Hex.cfqf` (`+0x30` / `bcxo`) is not on the push `bfdi` path.** Setter has no unique push-path call sites. Mono pin: `lastCorpse` (S35), not occupant. `bcym` ↔ `OnRevive`. | `source/static` / `xref` | Dual-write of `_cfqf` is incomplete (S4/S36). |
| S34 | **DS movement transaction (static):** minimal closed owner = `UnitData.bfdi(dest)` (ordered `bdhv`→`bcuo`→`bdhw`). Presentation (`emz`) remains open for user-visible shove. Donor restore is not the architecture (W8). | `source/static` / `xref` | Dossier § movement. |
| S35 | **Mono Hex has no Unit occupant property.** Occupancy is `fieldObjects` + `AddFieldObject`/`RemoveObject`. Live `cfqf`/`bcxo` ordinal-pin to mono `lastCorpse` get/set; `bcym` ordinal-pins to `OnRevive(Unit)`. | `source/static` | `mono_demo_battle_semantic_index.txt` + GE `dump.cs`. |
| S36 | **DS implication:** do not dual-write helper+`cfqf` as occupancy. Recipe remains `bfdi` → `bcyn`/`bcyl` on `fieldObjects`. Explains S3/S4 without treating `cfqf` as native occupant. | `source/static` + `live-negative` (S4) | Pin table row 6. |
| S37 | **Mono→live type pins (mixed strength):** **source/static+xref** store pins: `FieldObjectData`↔`edf`, `UnitData.set_hex`↔`bfdi`, `AddFieldObject`↔`bcyl`, `RemoveObject`↔`bcyn`. **Factory+field-shape:** `MechPushUnit`↔`ehh`. **shape-static only** (not uniform with store pins): `PushUnitStep`↔`ejn`, `StepQueueProcessor`↔`ejr` (`InsertImmediate`↔`bdyr` remains hypothesis). | `source/static` (stores) / `shape-static` (`ejn`/`ejr`) | Broad semantic map lacks these obfuscated rows; do not promote queue types to store-pin strength. |
| S38 | **`ehh.Init` bool stores closed:** `parameters[0]`→`cgfy`↔`pushInwards`; `parameters[1]`→`cgfz`↔`skipCenter` (disasm RVA `0x1FD4740`). Apply-body uses closed in S43. | `source/static` (stores) | `ehh_Init.asm.txt`. |
| S39 | **Event name pins vs `bdhw` publish (Iteration 9 base; refined S40–S42):** Push commit **required** chain `bdhw`→`eda.bcim`→`cfia` with plain `BattleEventArgs`. `cfia` name upgraded in S41. Prior `OnUnitChangedHex`↔`edb.cfkg` **downgraded then withdrawn** (W11). Walk `UnitStartedMovement` ≠ push Begin. | `required` (chain) | Do not invent Method_N. |
| S40 | **Hub identity:** live `eda` ≈ mono `BattleLogicEvents` (EventHandler prefix + 3 bools; GameSymbols prefix slots 5/6 action, 8/9 round). Live `edb` ≈ mono `BattleViewEvents` (3 `ProfilerMarker`s + EventHandlers including `HotkeyAbilityArgs`). | `source/static` (two shapes) + `xref` (GameSymbols) | Distinct types; not aliases of each other. |
| S41 | **`eda.cfia` mono name:** If declaration-order prefix holds, Logic ordinal 22 = `OnUnitEndedMovement` (`cfhe`=0 … `cfhz`=21 `OnUnitChangedHex`, `cfia`=22). **Solid call:** `bdhw`→`bcim` loads `[this+0xC0]` and invokes. **Solid:** commit publish ≠ `OnUnitChangedHex` / ≠ View `UnitPosChanged`. Residual risk: live `eda` has **53** EventHandlers vs mono Logic **49** (+4; insertion before ordinal 22 would shift names). | `ordinal-inferred` (name) + `source/static`/`xref` (call+offset) | Do not label “ordinal-strong.” Subscribers: mono `BhDrawerHelper`/`BhGatesHelper` — live types **open**. |
| S42 | **`edb.cfkg`:** View instance ordinal 21 ≈ `OnCrit` (not `OnUnitChangedHex`). Logic `OnUnitChangedHex` lives on `eda.cfhz` (`+0xB8`) if raised at all. | `ordinal-inferred` + hub shape (S40) | Withdraws live use of dump-era `cfkg`↔ChangedHex (W11). |
| S43 | **`ehh.bdpe` bool uses:** `pushInwards` selects direction scale **−1.0 vs +1.0** after hex-delta normalize (away vs toward). `skipCenter` is read **only** with `pushInwards` when neighbour-distance metric `== 1`; both true → add unit to `unitsToRemove`, skip dest hex for that unit. No other `cgfz` site. | `source/static` (disasm) + mono field names | Artifacts: `ehh_bdpe.asm.txt`. Shoulder Check `values:[false]` → away (+1). |
| S44 | **Legal dest predicate on push path:** `Hex.bcyf(side, ignoreUnits=false, ETargetAllegiance=2)` ↔ mono **`IsLockedForSide`**. Body ORs `blockedFromAll`/`blockedByMap`/`tempBlocked` and per-`fieldObjects` virtual blockers. `bcyf==true` → reject dest (unit → `unitsToRemove`); false → add hex to `tempHexesToPushTo`. Neighbour pick: `een.bdep`/`bdeo` + `eeu.bdke` distance. | `source/static` (sig+body) + mono signature match | `Hex_bcyf.asm.txt`. |
| S45 | **Store vs view:** `UnitData.bfdi` alone is sufficient for **store coherence** (helper + `fieldObjects` + Logic `OnUnitEndedMovement` via `bdhw`). Native push still routes commit through `emz.bfbe`→`bfdi` for presentation tween. Whether DS may omit `emz` for user-visible shove remains **hypothesis**. | `source/static` (store path) / `hypothesis` (view necessity) | Do not claim view proof. |

### Withdrawn

| ID | Withdrawn claim | Why |
|---|---|---|
| W1 | “Push vacates enemy hex; attacker then paths into the vacated hex.” | Contradicted by S5. |
| W2 | “Dispatch `Method_20` = OnUnitChangedHex via Method_N → field_(N+1).” | Broken by known Skip mapping; unsafe. |
| W3 | “Direct-state MovementPush is a substitute for native push/move.” | Contradicted by S4. |
| W4 | “Bellwether’s stripped native effect is a damage-time one-hex shove of the defender.” | Contradicted by S16/S17 (donor is Sticky Tongue pull via hex target). |
| W5 | “`UnitPosChangedEventArgs` + `bcqv` is the OnUnitChangedHex publish path.” | Contradicted by S20 (bcqv → EndTacticsMovement field). |
| W6 | “Dump `egb` is the live Golden Era mech factory; PushUnit subclass is still unbound.” | Contradicted by S22–S23 (live factory `egd.bdpz`; PushUnit = `ehh`). |
| W7 | “PushUnit is one of the `bdom` hex-pair overrides (`egl`/`egw`/`eia`/`eic`/`eif`).” | Contradicted by S23–S24 (`ehh.bdpe` + `ejn` queue; no `bdom` on `ehh`). |
| W8 | “Prefer Core restore of `push_unit` / donor envelope as the path to own Bellwether shove.” | Contradicted by user **live-negative** (2026-07-19) + handoff rule: DS must own the traced `bfdi` transaction. |
| W9 | “Occupancy clear/set for push is inside `eep.bdhv`/`bdhw` or via `Hex.bcxo`.” | Contradicted by S31–S33 (`bcyl`/`bcyn` inside `edf.bcuo`; `bcxo` not on path). |
| W10 | “Live `Hex.cfqf` is the Unit occupant / occupancy store (mono or live).” | Contradicted by S35–S36 (mono has no occupant; `cfqf`↔`lastCorpse`; push uses `fieldObjects`). |
| W11 | “Live GE `OnUnitChangedHex` = `edb.cfkg` (ISIL/dump-era field map).” | Contradicted by S40–S42 (`edb`≈View; `cfkg`≈`OnCrit`; Logic ChangedHex≈`eda.cfhz`; commit raiser=`eda.cfia`≈EndedMovement). |

## Open questions (queue)

1. What native function(s) assign Hex occupant and clear the previous hex atomically (or in order)? — **answered (static) for commit:** `UnitData.bfdi` → `edf.bcuo` → `Hex.bcyn`/`bcyl` on `fieldObjects`; bracketed by `bdhv`/`bdhw` notify+publish (S31–S34).
2. Does `get_Hex` read the same store as Hex.occupant, or a helper that can diverge? — **answered (static):** helper `edf` vs list `fieldObjects` (occupancy) vs `cfqf`=`lastCorpse` (not occupant); helper+`cfqf` dual-write diverges from native list (S13/S33/S35–S36 + S4).
3. When along StartMovement → per-hex → EndMovement does occupancy flip? — **answered for push:** flip at `emz.bfbe` → `UnitData.bfdi` (`fieldObjects` + helper), not at `UnitStartedMovement` begin.
4. What does `push_unit` pass (distance, direction, ignore blockers)? — **answered (static) for bools:** `pushInwards` flips direction scale ±1; `skipCenter` only with inwards@dist==1 → `unitsToRemove`. Dest legality = `IsLockedForSide`/`bcyf` (S43–S44). Distance is one-hex neighbour pick via `een`/`eeu`, not a config int.
5. Can push run without a movement timeline, or must it go through the same playback as walk? — **answered (static) for native apply:** step queue `ejn`/`ejr` + `emz`, not walk `enb.bfcp`. **Open for DS:** whether invoking `bfdi` without `emz` is enough for user-visible shove (S45).
6. What may legally occupy a hex during an attack step (attacker approach hex vs defender hex)? — **partial for push dest:** `IsLockedForSide` rejects map/all/temp blocked and blocking `fieldObjects`; stacking policy beyond that still open.
7. Which Golden Era class is `MechPushUnit`? — **answered (live GE):** `ehh` (S23).
8. Who constructs `UnitStartedMovementEventArgs` / who calls `edf.bcuo` in the walk and push paths? — **answered (static):** walk start `enb.bfcp`; push/walk commit store via `UnitData.bfdi` → `edf.bcuo`; push start has no `UnitStartedMovement`.

## Iteration log

### Iteration 0 — bootstrap (this file)

- Established domains, labels, contradiction rules.
- Seeded S1–S11 and W1–W3 from the Shoulder Check / direct-state pilot.
- **Contradiction pass:** W1/W2/W3 marked withdrawn; S3 does not promote S4; S8 blocks Method_N event shipping.
- **Next iteration focus:** Mechanics dispatch — locate `push_unit` handler in dump/ISIL/disasm and record callees into Occupancy + Events domains (still no code mutation).

### Iteration 1 — mechanics enum + factory surface

- Findings: `EMechType.PushUnit = 37`; factory `egb` with string dictionary; abstract mechanic base `egd` (`bdnm` apply-to-receiver, `bdom` hex-pair, `bdok` hex cast); runner helpers on `ega` including `bdoc(Hex,Hex,...)`.
- Placed on: Mechanics dispatch; Path/walk (hex-pair APIs).
- **Contradiction pass:** No conflict with seeds. Does not unlock writes.
- Claims: S12, S19 (partial).

### Iteration 2 — position vs occupancy stores

- Findings: `edf` helper is the hex position store (`bcsy`/`bcsx`); `Hex` occupant is separate (`bcvy`); Unit `get_Hex` is `ede.bcsr`. Live dual-write path matches these two stores (S3) and still fails coherent movement (S4).
- Placed on: Position authority; Occupancy; Transaction/rollback.
- **Contradiction pass:** Answers open Q2 statically. Reinforces W3 — matching verify-after-commit stores ≠ native move.
- Claims: S13, S14.

### Iteration 3 — donor config truth (Core.zip)

- Findings: Frog Leap ≠ `push_unit`; Sticky Tongue = `push_unit` pull-to-hex; Bellwether strips that row. Catalog of `push_unit` value shapes (mostly single bool).
- Placed on: Mechanics dispatch; Action lifecycle.
- **Contradiction pass:** Withdraws damage-shove donor story as W4. S10 remains hypothesis; even more reason not to mutate occupancy on DamageApplied for this shell.
- Claims: S16, S17, S18. Withdrawn: W4.

### Iteration 4 — events vs mono step names

- Findings: Mono `MechPushUnit` / `PushUnitStep` / `StepQueueProcessor`. ISIL: `bcqv` → OnUnitEndTacticsMovement while receiving `UnitPosChangedEventArgs`; `OnUnitChangedHex` uses different dispatchers. View listens to `UnitStartedMovementEventArgs` (multiple handlers).
- Placed on: Events; Path/walk; View.
- **Contradiction pass:** Withdraws UnitPosChanged≡OnUnitChangedHex as W5. Further weakens GameSymbols Method_45/`bcqv` as a general movement publish hook (treat as tactics-end / unknown until live-positive).
- Claims: S15, S20, S21. Withdrawn: W5.

### Iteration 5 — verdict gate

- Cross-checked: map is strong enough to judge the direct-state manager for **combat mutation**, especially movement/occupancy. Native entry for push/move is identified at the **config/enum/step-family** layer but not yet as a safe callable Golden Era method chain with live-positive proof.
- **Contradiction pass:** No claim promotes MovementPush. Shipping gate in Working rules still closed.
- Next research (when resumed): disassemble factory switch → pin PushUnit class → walk write body into `edf` + occupant + events.

### Iteration 6 — live GE PushUnit write-body pin (2026-07-19)

- Entry: live `egd.bdpz` jump table case 37 → **`ehh`** (S22–S23). Dump `egb` factory names are stale vs live DummyDll.
- Body: `ehh.bdpe` → `ejn` + `ejr.bdyq` → `ejn.bdyi` → `enb.bfcr`/`emz` → `UnitData.bfdi` → **`eep.bdhv` → `edf.bcuo` → `eep.bdhw`** (S24–S27).
- Order: position helper store is step 2 inside `bfdi`; occupant clear/set bracket it via `bdhv`/`bdhw` (exact `Hex.bcxo` call sites still open — S28).
- Readback map: live `edf.bcuo` ↔ dump `bcsy`; live `Hex+0x30`/`bcxo` ↔ dump `bcvy`/`_cfqf`.
- Closure: class pin + ordered position stores closed at `source/static`. Open: push event publish parity with walk; `ehh.Init` bool semantics; live-positive restore of Core `push_unit`.
- **Contradiction pass:** Withdraws W6/W7; updates S19; does **not** reopen MovementPush (W3/S4 still hold). Prefer Core restore of `push_unit` over dual-writes (S29).
- Claims: S22–S29. Withdrawn: W6, W7.

### Iteration 7 — Bellwether native restore attempt (2026-07-19)

- Changed Shoulder Check shell to `directStateNativeShell.mode=restoreNativeMechanic`: keep `push_unit` with values `["false"]` (dragon shove shape) under adjacent cast+damage reshape; disabled MovementPush pilot.
- Overlay applicator + runtime-mechanics validator updated to match. MovementPush code gate unchanged.
- **Evidence label:** source/static + generated Core when overlay applied. Later **live-negative** for intended shove (user) → W8.
- **Contradiction pass:** Does not reopen W3. Donor restore is not the product.

### Iteration 8 — close `bdhv`/`bdhw` vs occupancy stores (2026-07-19)

- Disasm live GE: `bdhv`/`bdhw` = listener fan-out; list occupancy = `bcyn`/`bcyl` inside `edf.bcuo`; `bfdi` remains ordered commit owner; `bdhw` publishes via `eda.bcim`→`cfia`.
- `Hex.cfqf`/`bcxo` closed as **not** on push path (W9).
- DS dossier written: `docs/direct_state_adapter_dossiers.md` § movement; handoff answers filled.
- **Contradiction pass:** Withdraws W8/W9; revises S28 occupancy hypothesis; does **not** reopen MovementPush (still need runtime proof). No combat write implementation in this slice.
- Claims: S31–S34. Withdrawn: W8, W9.
- Artifacts: `experiments/direct_state_movement_trace/*.asm.txt`.

### Iteration 9 — mono→live pin table (2026-07-19)

- Closed mono aliases for list mutators, `UnitData.set_hex`/`FieldObjectData.set_hex`, `MechPushUnit`/`PushUnitStep`/`StepQueueProcessor`, and `ehh.Init` bool field stores (`pushInwards`/`skipCenter`).
- Mono Hex has **no** Unit occupant; live `cfqf` pins to `lastCorpse` (W10 / S35–S36).
- Event names: `OnUnitChangedHex`↔`edb.cfkg` labeled **ordinal-inferred / hypothesis** (solid ≠ `eda.cfia`); `bdhw`→`cfia` raiser name remains hypothesis (S39).
- `ejn`/`ejr` pins labeled **shape-static** (not uniform with `bcyl`/`bfdi`).
- **Contradiction pass:** Withdraws W10; revises S14 occupant framing; does **not** reopen MovementPush or claim gameplay proof.
- Claims: S35–S39. Package: `experiments/direct_state_movement_trace/mono_live_pin_table.md`.
- Mono lane status: **partially closed** (store/type pins done; `cfia` name + `bdpe` bool gameplay + set_hex mono IL parity still open).
- Grok review must-fix (docs): downgraded S39/`cfkg` and S37 queue pins; handoff softened from “dossier complete” to **commit-store recipe closed**.

### Iteration 10 — Phase 2 hubs / dest predicates (2026-07-20)

- Closed `eda` vs `edb` hub identity (Logic vs View) and upgraded `eda.cfia` → Logic `OnUnitEndedMovement` (ordinal + `bdhw`→`bcim` offset).
- Withdrew live `OnUnitChangedHex`↔`edb.cfkg` (W11); View `cfkg`≈`OnCrit`.
- Closed `ehh.bdpe` bool uses (`pushInwards` direction scale; `skipCenter` only with inwards@dist==1).
- Closed legal dest predicate: `Hex.bcyf`=`IsLockedForSide` (map/all/temp blocked + `fieldObjects`).
- View: store coherence does not require `emz`; user-visible tween necessity still hypothesis (S45).
- **Contradiction pass:** W11; revises S38/S39; does **not** reopen MovementPush or claim gameplay proof.
- Claims: S40–S45. Artifacts: `ehh_bdpe.asm.txt`, `Hex_bcyf.asm.txt`; pin table updated.

### Iteration 11 — Grok Phase 2 accept; static-finished (2026-07-20)

- Grok Phase 2 review (`d6b10201-2794-47b8-ad79-7a8a40993daf`): **accept-with-fixes**, **no Phase 3**.
- Verified fixes already present: S7/S20 no longer teach `cfkg`↔`OnUnitChangedHex` as live truth; `cfia`/`cfhz`/view names stay **ordinal-inferred** (not ordinal-strong).
- Bannered `docs/edb_dxy_mono_xref_surface_mapping.md` as superseded/contradicted for live GE movement publish (points to S40–S45 / W11).
- Handoff + pin table + experiment README marked **static commit-store dossier finished**; remaining = runtime/`emz`/ordinal English names; MovementPush still gated; no readiness.
- **Contradiction pass:** none new (W11 already recorded). Does **not** reopen MovementPush, donor restore, or claim gameplay proof.

---

## Direct-state manager verdict

**Verdict date:** 2026-07-19. Evidence mix: live-negative (movement pilot) + source/static/xref (this map). **Not** user-visible gameplay proof for any custom push.

### Trust for combat mutation

| Area | Trust | Rule |
|---|---|---|
| Movement / occupancy / hex publish | **Do not trust** for mutation until runtime proof of the S34 recipe | Fail-closed. No MovementPush/Teleport production routing, Method_N invent, `cfqf` dual-write, or mid-damage hex writes. Static recipe exists (`UnitData.bfdi`). |
| Movement **reads** (hex, neighbours via fields, blocked, occupant) | **Keep** | Combat-proven neighbour field reads; helper/`get_Hex` reads OK for gates and diagnostics. |
| Journal / transaction scaffolding | **Keep as infrastructure** | Useful for families that already have a real write owner; must not imply occupancy commits are native-equivalent. |
| Damage scalar / Focus / cooldown field paths | **Keep gated** | Same symbol≠path lesson (S21); allow only where a concrete write owner is bound and CapLog rejects are honest. Not re-litigated here. |
| Hooks / ingress / mining | **Keep** | Observation and fail-closed routing only until a native move entry is live-positive. |

### Must stay fail-closed / retired

- **MovementPush** (and any `TryCommitUnitHexMove` / `Homm3DirectStateUnitHexNative` production routing) — retired as a substitute for native push/move (W3, S4). May remain in tree behind flags only if every path CapLogs and cannot claim readiness.
- **BattleLogic `Unit_Hex_0`** — retired (S1).
- **Re-enabling Method_20 / ordinal event publish** — forbidden (W2, S8, S20).
- **Mid-damage hex mutation** — forbidden (S10 + S17 donor mismatch).

### Native / DS write body that should own push/move

1. **Dest computation (native apply, optional invoke):** `egd.bdpz` → **`ehh`** → `ehh.bdpe` → **`ejn`/`ejr`** → `emz` (S22–S26). Use to learn dest rules; not required as the DS product if dest is already known.
2. **Commit owner (required):** `UnitData.bfdi(dest)` = `eep.bdhv` → **`edf.bcuo`** (`bcyn` / helper store / `bcyl`) → `eep.bdhw` (`bdhm` + `eda.bcim`/`cfia`) (S27, S31–S34).
3. **Do not** use Core donor restore or helper+`cfqf` dual-write as ownership (W3, W8, W9, S4).
4. Leap’s landing shove is a **different** path (`attackType_=jump`, empty mechanics) and must not be conflated with `push_unit`.

Until (2) shows **live-positive** end-to-end (stores + coherent unit), the direct-state manager must not ship MovementPush.

### Remaining open questions (runtime / English names — static dossier finished)

Ordered remaining hypotheses after Iteration 11 closeout (not a Phase 3 static agenda):

1. Prove whether `emz` presentation is required for user-visible shove beyond `bfdi` (S45 — store path closed without it).
2. Whether any path still raises Logic `OnUnitChangedHex` (`eda.cfhz`) on push/walk commit (not via `bdhw`).
3. Live type pins for Logic `OnUnitEndedMovement` subscribers (mono: `BhDrawerHelper` / `BhGatesHelper`).
4. Ordinal drift risk on English names (`eda` live 53 handlers vs mono 49).
5. Optional: mono `UnitData.set_hex` IL body parity with live `bfdi`; full `ejr` method-name map beyond `Push`/`bdyq`.

---

## Working rules for agents

- Update this file every investigation slice; do not bury findings only in chat.
- One contradiction pass per slice before starting the next chain.
- Implementation of movement adapters stays blocked until a runtime pass proves the S34 `UnitData.bfdi` recipe (stores + coherent unit). Static dossier alone does not unlock shipping.
- Do not invent new hex-write patches or re-enable MovementPush from static research alone.
- **Code gate (2026-07-19):** `TryMove` rejects `MovementPush`/`MovementTeleport` occupancy mutation. Re-enable only after live-positive proof of the dossier recipe.
- Prefer **journaled `UnitData.bfdi`** (or the full `bdhv`→`bcuo`→`bdhw` expansion) over dual-writes, Method_N invent, or donor restore.
