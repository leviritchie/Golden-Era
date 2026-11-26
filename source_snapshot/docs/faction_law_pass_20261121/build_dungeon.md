# Dungeon law tree: build notes (2026-11-21)

Spec: `dungeon.md`, REVIEW sections 2-4 and 6, BUILD_BRIEF. Not compiled, not installed, not committed.

## Files

- `custom_factions/law_overrides/homm3_dungeon.json`: 27 laws defined; 3/16/29 are left to the Resource Riches generator.
- New `OfflineUnlockMod/Homm3DungeonLawHooks.cs`.
- `OfflineUnlockMod/Homm3DungeonCaptivesRuntime.cs` and `Homm3DungeonWarCaptivesWindow.cs`: War Captives levers, each marked `// law pass 2026-11-21`.

## Tree (cost per level)

| Rank | Kingdom | Army |
|---|---|---|
| r0 | 3 Resource Riches I; 5 Holding Cells 3/3; 33 Mana Vortex 2/2 | 4 Elite Troglodytes 3/2; 10 Elite Harpies 3/2; 25 Ambush from the Dark 2/2 |
| r1 | 1 Tax Collectors 2/2; 14 Mining: Mercury 2/2; 7 Ransom Brokers 3/3; 2 Deep Scouts 3 | 11 Elite Beholders 3/2; 17 Elite Medusae 3/2 |
| r2 | 16 Resource Riches II; 34 No Escape Below 5; 28 Excavation Crews 3; 6 Warlock's Tutelage 2/2/2 | 20 Elite Minotaurs 3/2; 8 Feast of the Fallen 4; 12 Many Races Below 4 |
| r3 | 9 Taskmasters 5; 15 Night Dominion 3; 21 Slave Labour 4/3/3 | 24 Elite Manticores 3/2; 26 Kill Corridors 3/3; 32 Tunnel Network 5 |
| r4 | 29 Resource Riches III; 30 Overlord's Due 5; 27 Battle Academy 4/4 | 31 Elite Red Dragons 3/2; 23 Dread of the Deep 4 |

Cost per rank: 25 / 27 / 29 / 34 / 25 = 140. The layout validator returns 0 problems. The lawRules snippet returns 2 rules:
- #25 Ambush from the Dark: `turn_state unacted_target` 5/10% on the faction.
- #26 Kill Corridors: `wall_slam` 10/20% on the faction.

Owner decisions applied:
- Many Races Below (`unitBoolStat ignoreFractionsCount`) is Dungeon-only.
- Dread of the Deep (#23, enemy Defence -1 and Morale -1) is the only Morale source.
- Overlord's Due is half strength and never offers Enslave or Recruit.

Other choices:
- Elite Manticores use `modifierSet outDmgMods overTime_effect` .25/.5.
- Elite Medusae use `outComingDebuffDuration`.
- Tunnel Network uses `actionArea allied`.

## Plugin levers (War Captives)

Each (S) law carries a native zero-strength anchor: 5 `viewRadius 0`, 7 `movementBonus 0`, 9 `defence 0`, 30 `offence 0`, 8 `unitStat inAllDmgMod 0.0` (all Dungeon). The levels are read once, when the offer is built, from the winner's logic hero (`Homm3DungeonLawHooks.Rank`, which fails closed to 0).

| # | Law | Lever |
|---|---|---|
| 5 | Holding Cells | `Homm3DungeonCaptivesRuntime.cs:1296`: captives x(1 + 0.1L), multiplied with Dungeon Cells. |
| 7 | Ransom Brokers | `:1307`: Execute XP and Ransom Gold x(1 + 0.25L). Interrogation Mana stays on the base XP. |
| 8 | Feast of the Fallen | `:1325`: Eat share +10 points; `:1339`: restore cap x1.5. |
| 9 | Taskmasters | `:1274`: `HasRecruit = subskill OR law`. BuildRecruit runs after this, so the Recruit list fills at the rank's share. |
| 30 | Overlord's Due | See below. |

How Overlord's Due works:
- **Offer fields.** The Offer gains `SecondFate` and `Excluded` (`:148`).
- **Building the second offer.** `TryBuildSecondFate` (`:423` block) builds it after the first fate is applied:
  - half the captives (at least 1) and half the XP, Mana and Gold;
  - half of each Eat stack;
  - no Enslave or Recruit;
  - the applied fate is excluded.
- **Choice gating.** `IsChoiceAvailable` (`:370`) refuses Enslave, Recruit and the excluded fate on a second offer.
- **Fallback.** `FallbackChoice` is Ransom, or Execute when Ransom is excluded.
- **Human player.** The window's `Finish` (`Homm3DungeonWarCaptivesWindow.cs:240`) queues the second window after an accepted fate (`QueueSecondFate`, `:256`). That window lists only the fates still on offer (`:463`), with its own intro text (`:495`). The open-failure paths use `FallbackChoice` (`:111`).
- **AI, or a window that cannot open.** `ApplySecondFateDirect` takes Ransom after Eat, or Execute after Ransom (`:542`; window-queue failure at `:530`).

## Family indices reused (the coordinator should retire these family rows for Dungeon)

2, 6, 15, 21, 25, 27, 28, 34. Index 13 is dormant (not placed). Index 22 (morale profile) is retired: Dread of the Deep at #23 is the native Morale source.

## Not built / caveats

- If the AI's Eat falls back to Ransom inside `Apply` (winner TransferSide unreadable), the second fate still excludes Eat, so the AI gets Ransom twice (full, then half). This is a rare edge case and was left as is.
- Captives on auto-resolved battles keep today's behaviour (draft question 4).

## Shared-file asks

1. `Homm3CounterattackDoctrineMutationRuntime.cs` / counter doctrine row 13: drop Dungeon.
2. The morale-22 runtime / `Homm3CustomLawEffectProfiles.cs`: drop Dungeon. Dread #23 is the single source of enemy Morale -1.
3. Law families must skip Dungeon indices 2, 6, 15, 21, 25, 27, 28 and 34.
