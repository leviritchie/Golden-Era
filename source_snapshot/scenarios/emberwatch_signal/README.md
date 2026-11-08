# The Emberwatch Signal

**Single-player scenario** for Heroes of Might and Magic Olden Era (Golden Era).

## Premise

Castle scout-captain Lysa rides the Emberwatch ridge after three rogue signal fires
burn in a chain the border lords thought abandoned. Stronghold renegades under
Marshal Venn have seized Emberwatch Keep. Light the trail, break the wolf pass,
and take the keep back.

## How to play

1. Build and validate:
   ```bash
   python experiments/campaign_port_poc/build_emberwatch_signal_scenario.py
   python tools/validate_emberwatch_signal_scenario_contract.py --repo-root .
   ```
2. Install (merges map + dialog Core overlay into Golden Era):
   ```bash
   python tools/install_emberwatch_signal_scenario.py --repo-root .
   ```
3. **Restart the game** after install (Core.zip squad/dialog members load at startup).
4. Main menu → **QuickStart** → **The Emberwatch Signal**.

Olden +Y is **north**. Ride the dirt trail north from your outpost.

## Objectives

| Objective | Type |
| --- | --- |
| Investigate the western beacon | Required — +500 gold |
| Recover the crossroads cache | Required — +8 wood, +3 ore |
| Read the eastern warning | Required — lore |
| Clear the wolf pass | Optional — +2 gemstones |
| Capture Emberwatch Keep | **Victory** |

## Events

- **Day 1 briefing** — story dialog, +2500 gold, +5 wood
- **Beacon visits** — three one-shot caches along the ridge (gold ? marks north of each zone)
- **Weekly scout supply** — +10 wood and +5 ore every 7 days from day 7
- **Wolf pass** — guarded `h3_wolf_rider` patrol with pre-battle dialog and gem bounty
- **Marshal Venn** — enemy hero taunt (`BeforeIamVsHero`) before combat
- **Keep capture** — victory dialog + `GameVictory`

## Proof boundary

Source/static and generated-artifact validation only until a Golden Era runtime pass
is recorded. Map SID: `h3_emberwatch_signal`.
