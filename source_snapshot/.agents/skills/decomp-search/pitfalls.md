# Hard-won pitfalls (do not repeat)

## Name drift

- Dump-era factory `egb.bdoh` is **not** live Golden Era. Live factory: **`egd.bdpz`**.
- Live `egb` is a concrete mechanic (AddMagicCd), not the factory.
- `edb.cfkg` is **not** Logic `OnUnitChangedHex` on live GE (≈ View `OnCrit`). Logic ChangedHex ≈ `eda.cfhz` (ordinal-inferred); commit publish ≈ `eda.cfia` via `bdhw`.
- **DiffableCs declaration index ≠ live `Method_N`.** Do not invent event-hub raises by counting DiffableCs `void(object, BattleEventArgs)` and binding `Method_Public_Void_Object_BattleEventArgs_<index>`. Live-negative: DiffableCs `eda.bcja` at index 39 ≠ interop `Method_39` (raises `cfir` / ChangeAbility; `BuffEventArgs`→`ChangeAbilityEventArgs` cast). Correct buff got-buff path: ISIL `bcja` loads `+0x128`/`cfin` → interop `GetIl2CppField(..., "cfin")` = `field_…_35` → `Method_…_35` (`GameSymbols.BuffDebuffLaws.BuffEventDispatch`). Invoke `hub.bcja(nativeSource, args)`, not `hub.bcja(hub, args)`.

## Key / object identity (silent miss class)

Two different failure modes look alike (non-empty map + `TryGetValue` miss). Keep them separate:

### Wrong type / need bridge (Store key ≠ retrieve key)

- `Unit.Init` arg[2] is the battle-side wrapper (`ObjectPublicPrcgObPrcgInTrPrcgInUnique` on live Golden Era; legacy short names `eir`/`ehh` may be absent). Plans keyed from `TransferBattle.sides` must bridge via `BattleSideTransferSideMembers` before lookup. Unbridged `__args[2]` hash → empty `TryGetValue` with plans present = bug, not “no plan.”
- If Split Assembly / Bulwark log `exact Unit.Init shape not found`, re-pin `GameSymbols.BattleUnitInit.SideTypeHints` against live Hex.dll — stale side hints reject the real Init.
- Do not copy a Bulwark/Factory side pattern without checking whether the live object is the current side wrapper, `TransferSide`, or another type.

### Managed proxy identity ≠ native identity (Il2Cpp re-wrap)

- Even after the type/bridge is correct, Il2Cpp field reads and separately marshaled Harmony args often yield a **new managed proxy** for the same native object. Managed `GetHashCode`, `ReferenceEquals`, and `RuntimeHelpers.GetHashCode` on `Il2CppObjectBase` then diverge across store vs retrieve.
- Key live game-object caches (plans, registers, owner maps) by **native pointer** via `Homm3DirectStateIdentity` (or equivalent `Il2CppObjectBase.Pointer`), same as Direct State — not by managed identity.
- Native-pointer keying fixes managed re-wrap only. Matching CapLog / diagnostic `nativeKey=` values mean the same native object; **distinct `nativeKey`s mean different objects / wrong ownership key** — do not treat pointer keying as proof that store and retrieve TransferSide (or other owner) are the same instance.
- Applies to any Il2Cpp Harmony plan/dict keyed by units, sides, heroes, or other game objects — not only TransferSide / Split Assembly / Bulwark.
- Log tell: `planned:` + plan miss + `activePlans≥1` with changing `managedHash` while the **same** native pointer key would match. If store and retrieve already log **different** `nativeKey`s, diagnose ownership/key choice, not re-wrap.
- Distinct from **Producer→consumer window** (map already emptied / cleared too early).

### Shared collection / proof notes

- Prefer `Count` + indexer over `foreach` on Il2Cpp lists when enumeration has previously missed elements or thrown; verify the collection surface before pattern-copy.
- `planned:` log lines prove plan **storage**, not apply.

## Producer→consumer windows (timing / ownership)

- When one Harmony path fills a plan/register and a later hook consumes it, keep that state alive until **every** consumer has run (or own apply on one shared registration surface). Do not clear in an earlier postfix than apply.
- Planned≠applied with **quiet** miss logs often means the map was already emptied — diagnose **timing/ownership**, not key identity. (Optional example class: Init-postfix clear racing Unit.Init apply.)
- `BattleLogic.Init` also runs during adventure-map / session `Loader` paths. Fail-closed throws from optional pilots in an Init prefix can brick map load — soft-skip / log; do not throw out of Init for optional pilots (force-setup lesson).

## Occupancy mistakes

- `Hex.cfqf` / `bcxo` = **`lastCorpse`**, not unit occupant.
- Occupancy on push/walk commit = `fieldObjects` via `bcyn`/`bcyl` inside `edf.bcuo`.
- Helper hex + `cfqf` dual-write can CapLog “success” and still look wrong in battle (**live-negative**).

## Store vs view

- `UnitData.bfdi` is the **store** commit owner (helper + lists + Logic end-move publish).
- Native push still routes through **`emz`** (world tween) before/around `bfdi` for presentation.
- Trusting mid-damage journaled `bfdi` CapLog as Shoulder Check product was wrong.

## Envelope mistakes

- Frog **Leap** (`attackType_=jump`, empty `targetMechanics`) ≠ `push_unit`.
- Frog **Sticky Tongue** = hex-select + `push_unit` `["true","false"]` (pull), not adjacent damage shove.
- Adjacent damage + `push_unit` `["false"]` for Bellwether was **live-negative** for intended shove.
- Prefer Schism **Command: Fear** (`teleport` + ordered hex) when the design is “move enemy to a free hex.”

## Direct State anti-patterns

- Stripping Core mechs then reimplementing with store pokes “because donor failed.”
- Method_N / ordinal invent for event publish (including DiffableCs index → `Method_N` for `eda`/`edb` BattleEventArgs raises — see Name drift `bcja`/`cfin`/`Method_35`).
- `edb` as movement publish hub.
- Shipping MovementPush/Teleport from static dossier alone.
- Empty-listener / plant-incomplete methods promoted as equivalence-proven.

## Recovery limits

- IL2CPP loses original names, comments, and many asset strings.
- Equiv/plant probes need a live battle object graph; many methods stay `plant_incomplete`.
- HotA designer intent is not in Olden binaries — Core donors approximate, not guarantee HotA parity.

## Logging tells

| Log signal | Meaning |
|------------|---------|
| `no active mechanics for caster sid=…` | DS pilot off/absent; native path must carry product |
| `MovementPush committed` + dual-readback agree | Store proof only until view confirmed |
| `PREPARED_MECHANICS=N` | Count of enabled diagnostic pilots at startup |
| `planned:` without `applied unit buffs:` | Plan stored only; apply never hit — often producer→consumer timing (clear before apply), empty registry, **or** Il2Cpp re-wrap keyed by managed GetHashCode (see Managed proxy identity ≠ native identity) |
| `unit init while plans empty:` | Unit.Init fired after plan window closed — fail-closed timing signal |
| `plans active … battle-unit registry empty` | Shared Unit.Init registry missing/late; keep plans open for Unit.Init apply |
| `BuffEventArgs` → `ChangeAbilityEventArgs` cast on buff dispatch | Wrong event-hub raise (`Method_39`/`cfir`). Re-pin via `cfin`/`Method_35` (`BuffEventDispatch`); do not trust DiffableCs index==Method_N |

## Quick Play / DataInc.campaignHeroes

- `DB/data.json` `campaignHeroes` is **campaign-reserved**. Native Quick Play / custom-game hero select omits those SIDs.
- Native OE lists only tutorial/campaign-only rows there (`tutorial_*`, `campaign_*`), never ordinary town-roster heroes.
- Do **not** append shared HoMM3 roster protagonists (Crag Hack `homm3_stronghold_hero_1`, Christian, Yog, …) when installing StoryHubs — that removes them from Quick Play. StoryHub needs the `DB/heroes/…` row, not `campaignHeroes` membership.
- Distinct from `replace_hota` late-slot *name* swaps. Contract: `tools/validate_homm3_campaign_heroes_roster_separation_contract.py`.
