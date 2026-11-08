# Olden Era Demo — battle unit Animator parameter hashes

This document records **deterministic** `Animator.StringToHash` values for the shipped **battle unit** animator used by Esquire custom work, without relying on in-game verbose logging.

## Environment verified (2026-04-28)

| Source | Unity version |
|--------|----------------|
| **Game** `HeroesOE_Data/globalgamemanagers` (binary search for `6000.0`) | `6000.0.66f1` |
| **Unity Hub Editor** used for the dump | `6000.0.66f2` |
| **Unity project** `ProjectSettings/ProjectVersion.txt` | `6000.0.66f2` |

Patch revision differs by one (`f1` vs `f2`). `Animator.StringToHash` is engine-level and is **not** expected to change between `f1` and `f2` of the same `6000.0.66` line; if you need a bit-identical guarantee to the installed player, install Hub editor **6000.0.66f1** and re-run the batch step below.

## Asset source (parameter *names*)

The parameter list comes from YAML serialization of:

`Assets/CustomUnits/esquire/Reference/StockEsquireBattle.controller`

in the linked Unity project (`oldenera_factions`). The controller asset’s internal name is `_Battle_Unit_Anim_ctrl_v2`. Parameters are **`camelCase`**, e.g. `attack`, `damage`, `move`, not PascalCase `Attack`, `Hit`, `IsMoving`.

That file is produced by the AssetRipper pipeline documented in `tools/AssetRipper/pipeline_esquire_reference_headless.cmd` (default `GAME_DATA` points at the Steam Demo `HeroesOE_Data`).

## Authoritative hash table (Unity 6000.0.66f2)

Machine-readable copy: **`AnimatorStringToHash_report.tsv`** (same directory as this file).

Summary for **custom audio / Animator postfix dispatch** (typical creature SFX):

| Role | Stock parameter | Type (YAML `m_Type`) | `Animator.StringToHash` (int32) | hex32 |
|------|-----------------|----------------------|----------------------------------|-------|
| Melee / strike | `attack` | 9 = Trigger | `1203776827` | `47C02D3B` |
| Hit reaction | `damage` | 9 = Trigger | `298341484` | `11C8546C` |
| Death | `die` | 9 = Trigger | `964231127` | `3978FFD7` |
| Walk / move loop gate | `move` | 4 = Bool | `-281135240` | `EF3E3778` |
| Victory | `victory` | 9 = Trigger | `1891303514` | `70BB005A` |
| Dead state (hold) | `isDead` | 4 = Bool | `1276664872` | `4C185C28` |

Other parameters (`teleport`, `fly`, `stanceIn`, …) are in the TSV for completeness.

### YAML `m_Type` reminder

Common values in exported controllers: `1` = Float, `3` = Int, `4` = Bool, `9` = Trigger.

## OfflineUnlockMod constants vs this table

`EsquireBattleAudioPlayer` and `EsquireBattleAnimatorSetHook.HintForId` use identifiers such as `IdAttack = -529364832`, `IdHit = 1249463`, `IdIsMoving = -1956118232`, mapped to labels `Attack`, `Hit`, `IsMoving`.

Under **Unity 6000.0.66f2**, `Animator.StringToHash("Attack")` is `1080829965`, **not** `-529364832`. None of those legacy int literals match `StringToHash` for the **PascalCase** names in `HintForId`, nor for the **stock** `attack` / `damage` / `move` names.

**Conclusion:** the mod’s current numeric constants are **not** a faithful encoding of the shipped `_Battle_Unit_Anim_ctrl_v2` parameter hashes for Unity 6. Any Animator-driven audio should key off the **stock parameter names** (or the table above), not the old hint literals—unless you prove with a fresh capture that Il2CPP passes different ints (unexpected for `SetTrigger(int)`).

## How to regenerate

1. Copy `AnimatorStringHashReport.cs` from this folder into `<UnityProject>/Assets/Editor/`.
2. Run (adjust paths):

```bat
"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe" -batchmode -quit -nographics ^
  -projectPath "C:\Users\<user>\oldenera_factions" ^
  -executeMethod OldenEra.ReferenceTools.AnimatorStringHashReport.DumpFromCommandLine ^
  -logFile AnimatorStringHash_unity.log
```

3. Read `AnimatorStringToHash_report.tsv` next to the project root (or use menu **Olden Era → Reference → Dump Animator StringToHash (battle params)** and copy from the Console).

If the game updates Unity major/minor, **re-run** this step; Unity’s documentation states that `StringToHash` stability is not guaranteed across all version jumps (in practice same line usually stable).

## State hashes vs parameter hashes

`Animator.Play` / `CrossFade` log **state** name hashes, not controller parameter ids. Do not mix the two when wiring SFX to `SetTrigger`/`SetBool` postfixes.
