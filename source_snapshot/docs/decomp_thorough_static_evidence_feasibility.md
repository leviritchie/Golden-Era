# Thorough Static Evidence Feasibility (IL2CPP Golden Era)

Status: durable strategy note (2026-07-24).  
Scope: large-scale IL2CPP decompilation / static recoverable C# evidence for Golden Era.  
Out of scope: town scene replace, asset pipelines, and product feature ungating.

This document answers whether a multi-month / multi-year AI-assisted program can produce **thorough static evidence for modifying the game**, and what that actually requires. Claims are proof-labeled. “Done” is defined without pretending the whole binary becomes a clean C# tree.

## One-sentence verdict

**(A) high-coverage static read aids are possible and already partially real; (B) large compilable recovered C# is only partially possible (easy accessors scale, hard bodies do not); (C) equivalence-proven recovery is island-scale only; (D) recompiling/replacing `GameAssembly` from recovered C# is practically impossible.**

## Terms (light)

| Term | Meaning |
| --- | --- |
| **Static read aid** | Dump, DiffableCs shell, ISIL, native asm, call graph, or index that helps a human/AI *read* the game without claiming the method is recovered correctly. |
| **DiffableCs / ISIL** | Cpp2IL outputs: C#-shaped type shells (fields/signatures) and intermediate instruction listings. Not full original source. |
| **DummyDll** | Cpp2IL attribute-injected assemblies used to export managed method pointer addresses into `GameAssembly`. |
| **Bar C / equivalence-proven** | Repo proof bar: live identity bridge + `live_execution` oracle (inputs → observable outputs) + recovered replay match. Static lift alone never promotes. |
| **CompGen** | Compiler-generated accessors (getters/setters) — usually tiny native bodies; the recovery program’s proven sweet spot. |
| **Plant incomplete** | Oracle/recovery blocked because the live object graph needed to construct/invoke the method cannot be planted safely. |
| **Obfuscation churn** | Short generated names (`ezg`, `egd`, …) are reused across hotfixes for *different* types; stale dumps mislead. |

Evidence sources used here: `.cursor/skills/decomp-search/`, `tools/IL2CPP_DUMP.md`, `experiments/cpp2il_readable_csharp/`, `experiments/olden_cs_recovery/` (README, proof ledger, oracle capture, Direct State write-body lane).

---

## Four targets

### (A) High-coverage static read aids — **possible**

**What it is:** Always-refreshable `dump.cs`, DiffableCs, ISIL (where emit works), DummyDll method-pointer maps (~199k rows already exported in the Cpp2IL experiment), Capstone native disassembly packs, direct-call graphs, semantic/symbol indexes, and agent-navigable maps (decomp-search style).

**Why possible:**

- Il2CppDumper + Cpp2IL (dev/fork for metadata **31.1**) already produce the shells and address maps the repo uses for mod work.
- Attribute-injected DummyDll export produced **199,233** method-pointer rows for the Golden Era experiment — identity coverage at whole-binary scale is a solved *static* problem, not a research fantasy.
- Native disasm + call-graph tooling already covers broad `Hex.*` domains; refresh wrappers and corpus compare exist.
- AI does not need compilable C# to be useful: searchable dumps, xref graphs, and pin tables already change modification speed.

**Limits (still A, not failure):**

- Milestone Cpp2IL releases historically could not parse metadata 31.1; the program depends on a **maintained fork/dev build**.
- Full ISIL dumps have hit Windows path/sanitization and NuGet restore blockers; when ISIL is incomplete, DummyDll pointers + native disasm are the fail-closed substitute — not invented managed bodies.
- Stale dumps are actively harmful: same obfuscated name can mean different types across builds (`tools/IL2CPP_DUMP.md`).
- Static paths prove call edges and layouts; they do **not** prove runtime order, hook safety, or gameplay.

**Proof label today:** *source/static validated* tooling exists; *generated artifact* refresh is operational when run against the live Golden Era install. Whole-corpus “always indexed for every agent session” is an engineering scale-up, not a physics barrier.

### (B) Large compilable recovered C# with real method bodies — **partially possible**

**What it is:** Emitting C# that `dotnet build`s, with bodies that look like real logic (not empty stubs), for large fractions of the ~199k methods.

**Why only partial:**

- **Easy island scales:** CompGen getters/setters, simple EventArgs ctors, and thin wrappers lift cleanly. Phase 4–5 declared sets in `olden_cs_recovery` reached `domain_promoted` on explicit subsets (EventArgs/edb + CompGen battle/city/map/configs) — on the order of **~100 methods**, not ~199k, and intentionally not “full Unit / full Map.”
- **Hard bodies do not auto-scale:** Complex control flow, generic sharing, Unity lifecycle, and battle-graph methods leave `UnresolvedLift` markers or stay skeletons. Direct State write-body work still hits `plant_incomplete` on methods that need a live battle plant (`ehh.bdpe`, grid plants, `Unit.Init`, …).
- Cpp2IL readable pipeline is explicitly **not a full decompiler**; complex methods need manual interpretation, live probes, or stronger body evidence.
- **Compile-check ≠ correctness.** `recovered/` has a compile-check gate that only proves the package builds; bar C still requires equivalence. Bulk “AI wrote a body that compiles” is not recovery.

**Honest ceiling:** Over years, an AI-assisted lifter can grow a large library of **static-lifted / compile-gated** skeletons and a smaller library of **high-confidence bodies** on simple shapes. It will not fill GameAssembly with trustworthy full method implementations.

### (C) Equivalence-proven recovered methods vs live game — **partially possible (island-scale); near-full is practically impossible**

**What it is:** Bar C — identity bridged, `live_execution` oracle captured, EquivTester replay matches engine snapshot.

**Why island-scale works:**

- The recovery package already defines overnight-safe lift/rename vs live-required oracle capture.
- Proven domains exist for declared CompGen/EventArgs sets and for selected Direct State cards (with blocked-with-reason entries kept visible).
- Fail-closed design correctly refuses promotion from `live_surface_metadata` alone.

**Why near-full (~199k proven) is not realistic:**

- Most interesting methods need a **live Golden Era object graph** (battle field, hex grid, MonoBehaviour lifecycle, class `.cctor` ordering). Many stay `plant_incomplete`.
- Oracles cannot be invented overnight; each hard method needs a probe surface, deploy, and capture tied to `game_build_id` / `GameAssembly` hash.
- Obfuscation churn invalidates identity and oracles across patches; proof is per build, then remapped — not a one-time corpus.
- Equivalence for floaty / presentation / async paths needs tolerances and often **user-visible** follow-up; store CapLog agreement is not gameplay proof (decomp-search pitfalls).

**Proof label:** *runtime behavior proven* only per promoted method/card. Domain promotion is always over an **explicit declared set**, never implied whole-type coverage.

### (D) Recompiling / replacing `GameAssembly` from C# — **practically impossible**

**What people often want:** Recover C# → rebuild IL2CPP binary → ship a replaced `GameAssembly.dll` as if original source returned.

**Why this is not a viable north-star:**

- Original C#, comments, and many designer strings are gone; IL2CPP + obfuscation destroy the reconstructible source product.
- A working Unity/IL2CPP rebuild needs the vendor project, matching engine version, assets, native plugins, and link order — none of which recovery supplies.
- Generic sharing, blittable layouts, and interop thunks must match the live binary; “close C#” that compiles in a recovery project will not produce a drop-in `GameAssembly`.
- The successful modification path in this repo is **BepInEx / Harmony / Core overlays / live bridge** against the shipping binary — not binary replacement from decomp.

Treat (D) as a non-goal. Effort spent chasing it displaces (A)+(C islands) that actually accelerate mods.

---

## What a multi-year AI-assisted program actually requires

Concrete pillars (not optional fluff):

1. **Cpp2IL (or successor) fork maintenance**  
   Stay on metadata 31.1+; keep DiffableCs / DummyDll attribute injection / ISIL emit working after Unity and tooling breaks. Budget ongoing porting, not a one-shot dump.

2. **Continuous dump refresh vs Golden Era updates**  
   Dated Il2CppDumper folders; never a stale “live” symlink. Remap `GameSymbols` with signature/semantics checks after hotfixes. Pin `GameAssembly` hash into recovery manifests.

3. **Corpus indexing at decomp-search scale**  
   Always-fresh searchable layers: dump.cs, DiffableCs, address maps, native disasm packs, call graphs, mono↔live pin tables, law-surface dossiers. Agent skill/maps must point at **current** dated artifacts. This is the highest leverage AI investment.

4. **Tiered automated lift**  
   Automate CompGen getters/setters and simple ctors hard. Keep complex control-flow behind explicit Unresolved markers. Separate overnight lift from live oracle. Do not blur static-lifted into equivalence-proven.

5. **Human + live oracle promotion path**  
   Live probe bridge, construct/field-delta/call-trace probes, EquivTester, proof ledger, banned-surface validators. Promotion is a scarce resource aimed at **mod surfaces** (battle commit, occupancy, configs, UI binders), not vanity method counts.

6. **Name stability strategy**  
   Centralize obfuscated names in `GameSymbols` / Direct State cards. Maintain mono↔live pin tables. Treat same-name matches across dumps as non-proof. Prefer RVAs/DummyDll identity for recovery queue keys; prefer semantic cards for product exports.

7. **Storage / compute**  
   Multi-GB DiffableCs/ISIL/disasm trees, ~200k method-pointer rows, per-build corpora, oracle JSON, and agent indexes. Prefer repo-local / `V:` storage; keep multi-MB dumps optional commits; regenerate from install when needed.

8. **Explicit “done” definition that is not 199k proven**  
   Done = (i) refreshable high-coverage static corpus + AI navigation, (ii) expanding equivalence-proven / Direct State islands around active mod surfaces, (iii) remap discipline after every Golden Era update. Method-count dashboards are secondary.

Optional capacity (not the definition of done): broader `Hex.*` CompGen slices, more Direct State write-body cards, deeper semantic alias maps — only when a concrete mod surface needs them.

---

## Recommended north-star

**Always-fresh, AI-navigable static evidence corpus + expanding recovered/proven islands around modification surfaces — not full-game recompile.**

In practice that means:

- Agents open current dump / DiffableCs / asm / call-graph / pin table first (decomp-search discipline).
- Recovery workers keep growing CompGen and simple-body coverage where bar C is cheap.
- Hard combat/UI write paths earn Direct State cards and GameSymbols exports only when equivalence-proven (or explicitly blocked with reason).
- Product remains Harmony/Core/live-bridge modification of the shipping binary.

This maximizes “thorough static evidence for modification” on a multi-year horizon without promising (D) or full (C).

---

## Risks of bulk AI decomp without oracles

Bulk AI “recovery” that skips bar C is worse than sparse honest dumps:

- **Confident wrong C#** — plausible control flow that never matches live stores (classic occupancy mistake: treating `Hex.bcxo` / `cfqf` as occupants instead of `lastCorpse`).
- **Name drift** — teaching models on last month’s dump trains them to hook the wrong `ezg`.
- **Silent TryGetValue misses** — wrong live arg types vs map keys look like “no plan” instead of a failed bridge.
- **Store-vs-view confusion** — CapLog / dual-readback “success” with wrong presentation (`emz` / Logic hub mistakes).
- **Promotion pollution** — once wrong bodies enter a recovered package without ledger status, later agents treat them as law.

Mitigation already encoded in-repo: evidence labels, fail-closed promotion, banned-surface validators, plant_incomplete visibility, and “compile-check is a gate, never promotion.” Keep that culture when scaling AI lift.

---

## Possibility matrix (summary)

| Target | Possibility | Why |
| --- | --- | --- |
| **(A)** Static read aids at high coverage | **Possible** | Dumper + Cpp2IL DummyDll (~199k pointers) + disasm/graphs/indexes; main work is refresh, indexing, and agent UX. |
| **(B)** Large compilable recovered C# with real bodies | **Partially possible** | Easy accessors/ctors scale; complex bodies and generics do not become trustworthy mass C#. |
| **(C)** Equivalence-proven vs live | **Partially possible** | Proven islands work; full/~199k needs live plants the program cannot automate for most methods. |
| **(D)** Recompile/replace `GameAssembly` from C# | **Practically impossible** | Missing original project/toolchain; IL2CPP+obfuscation; modding path is patch-in-place. |

---

## Related repo anchors

| Path | Role |
| --- | --- |
| `.cursor/skills/decomp-search/SKILL.md` | Agent navigation contract and proof labels |
| `tools/IL2CPP_DUMP.md` | Dated dump policy; obfuscation reuse warning |
| `experiments/cpp2il_readable_csharp/README.md` | DiffableCs/ISIL/DummyDll/disasm pipeline; metadata 31.1 note; ~199k pointer export |
| `experiments/olden_cs_recovery/README.md` | Lifter/rename/oracle/equiv/promote; Phase 4–5 declared-set promotion |
| `experiments/olden_cs_recovery/proof_ledger/README.md` | Status vocabulary; bar C |
| `experiments/olden_cs_recovery/oracle_traces/CAPTURE.md` | Live execution surfaces and plant limits |
| `experiments/olden_cs_recovery/DIRECT_STATE_WRITE_BODY.md` | Write-body island + ungating discipline |

---

## Document class

Strategic feasibility / proof-boundary note. It does not prove any new runtime behavior and does not authorize product ungating. When implementation or installed-game evidence disagrees with dated recovery counts above, trust the current ledger and dumps and update this summary.
