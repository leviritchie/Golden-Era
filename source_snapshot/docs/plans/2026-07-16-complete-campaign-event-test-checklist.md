# HoMM3 Complete Campaign Event Test Checklist

Date: 2026-07-16

Status: source/static inventory from live **HoMM3 Complete** H3C decode via `CampaignEventIR`. Not runtime or installed-payload proof.

Scope: all **20** official Complete Edition campaigns (8 RoE + 6 Armageddon's Blade + 6 Shadow of Death), every global timed event, map EVENT object, and town event.

Source LOD policy:

- RoE + SoD: `V:\Games\Olden Era Playtest Tweak\HoMM 3 Complete\Data\H3bitmap.lod`
- AB: `V:\Games\Olden Era Playtest Tweak\HoMM 3 Complete\Data\H3ab_bmp.lod`
- Excluded: H3HD (incomplete expansion set), HotA Factory

Machine inventory: `artifacts/campaign_port_poc/complete_campaign_event_test_inventory.v1.json`

Regenerate:

```powershell
$env:PYTHONUTF8='1'
python tools/build_roe_campaign_event_test_inventory.py --repo-root .
```

## How to use

- Check off each event after confirming the listed Olden behavior in-game.
- Identity key is `sourceIdentity` (stable for the same H3C).
- Day numbers are H3 trigger days (`firstOccurrence + 1`). Map events fire on visit at `layer:x:y`.
- Events with readiness blockers may still appear in IR while emit is incomplete.

## Summary

| Expansion | Campaign | Mission | Global | Map | Town | Total |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| roe | Long Live the Queen | Homecoming (`homecoming`) | 7 | 1 | 1 | 9 |
| roe | Long Live the Queen | Guardian Angels (`guardian_angels`) | 2 | 0 | 0 | 2 |
| roe | Long Live the Queen | Griffin Cliff (`griffin_cliff`) | 4 | 3 | 0 | 7 |
| roe | Liberation | Steadwick's Liberation (`steadwick_liberation`) | 4 | 0 | 0 | 4 |
| roe | Liberation | Deal With the Devil (`deal_with_the_devil`) | 4 | 2 | 0 | 6 |
| roe | Liberation | Neutral Affairs (`neutral_affairs`) | 4 | 0 | 0 | 4 |
| roe | Liberation | Tunnels and Troglodytes (`tunnels_and_troglodytes`) | 4 | 0 | 0 | 4 |
| roe | Song for the Father | Safe Passage (`safe_passage`) | 1 | 0 | 0 | 1 |
| roe | Song for the Father | United Front (`united_front`) | 2 | 0 | 0 | 2 |
| roe | Song for the Father | For King and Country (`for_king_and_country`) | 1 | 0 | 0 | 1 |
| roe | Dungeons and Devils | A Devilish Plan (`a_devilish_plan`) | 2 | 1 | 0 | 3 |
| roe | Dungeons and Devils | Groundbreaking (`groundbreaking`) | 4 | 1 | 0 | 5 |
| roe | Dungeons and Devils | Steadwick's Fall (`steadwicks_fall`) | 8 | 0 | 0 | 8 |
| roe | Long Live the King | A Gryphon's Heart (`a_gryphons_heart`) | 2 | 0 | 0 | 2 |
| roe | Long Live the King | Season of Harvest (`season_of_harvest`) | 6 | 0 | 0 | 6 |
| roe | Long Live the King | Corporeal Punishment (`corporeal_punishment`) | 3 | 0 | 0 | 3 |
| roe | Long Live the King | From Day to Night (`from_day_to_night`) | 2 | 0 | 0 | 2 |
| roe | Spoils of War | Borderlands (`neutral_1a`) | 3 | 2 | 0 | 5 |
| roe | Spoils of War | Gold Rush (`neutral_1b`) | 4 | 0 | 0 | 4 |
| roe | Spoils of War | Greed (`neutral_1c`) | 6 | 4 | 0 | 10 |
| roe | Seeds of Discontent | The Grail (`the_grail`) | 3 | 15 | 0 | 18 |
| roe | Seeds of Discontent | Independence (`independence`) | 4 | 0 | 0 | 4 |
| roe | Seeds of Discontent | The Road Home (`the_road_home`) | 1 | 10 | 1 | 12 |
| roe | Specter of Power | Poison Fit for a King (`poison_fit_for_a_king`) | 13 | 0 | 1 | 14 |
| roe | Specter of Power | To Build a Tunnel (`to_build_a_tunnel`) | 2 | 0 | 0 | 2 |
| roe | Specter of Power | Kreegan Alliance (`kreegan_alliance`) | 9 | 0 | 0 | 9 |
| roe | Specter of Power | With Blinders On (`with_blinders_on`) | 1 | 3 | 0 | 4 |
| ab | Armageddon's Blade | Catherine's Charge (`catherines_charge`) | 18 | 6 | 1 | 25 |
| ab | Armageddon's Blade | Seeking Armageddon (`seeking_armageddon`) | 9 | 1 | 0 | 10 |
| ab | Armageddon's Blade | Shadows of the Forest (`shadows_of_the_forest`) | 7 | 1 | 1 | 9 |
| ab | Armageddon's Blade | Maker of Sorrows (`maker_of_sorrows`) | 8 | 6 | 0 | 14 |
| ab | Armageddon's Blade | Return of the King (`return_of_the_king`) | 7 | 1 | 0 | 8 |
| ab | Armageddon's Blade | A Blade in the Back (`a_blade_in_the_back`) | 10 | 3 | 0 | 13 |
| ab | Armageddon's Blade | To Kill A Hero (`to_kill_a_hero`) | 9 | 0 | 4 | 13 |
| ab | Armageddon's Blade | Oblivion's Edge (`oblivions_edge`) | 7 | 0 | 1 | 8 |
| ab | Dragon's Blood | Culling the Weak (`culling_the_weak`) | 13 | 0 | 11 | 24 |
| ab | Dragon's Blood | Savaging the Scavengers (`savaging_the_scavengers`) | 12 | 0 | 0 | 12 |
| ab | Dragon's Blood | Blood of the Dragon Father (`blood_of_the_dragon_father`) | 13 | 2 | 0 | 15 |
| ab | Dragon's Blood | Blood Thirsty (`blood_thirsty`) | 12 | 1 | 0 | 13 |
| ab | Dragon Slayer | Rust Dragons (`rust_dragons`) | 5 | 3 | 0 | 8 |
| ab | Dragon Slayer | Faerie Dragons (`faerie_dragons`) | 4 | 13 | 0 | 17 |
| ab | Dragon Slayer | Azure Dragons (`azure_dragons`) | 2 | 7 | 0 | 9 |
| ab | Dragon Slayer | Crystal Dragons (`crystal_dragons`) | 3 | 5 | 0 | 8 |
| ab | Festival of Life | For the Throne (`for_the_throne`) | 6 | 1 | 0 | 7 |
| ab | Festival of Life | Clan War (`clan_war`) | 4 | 0 | 0 | 4 |
| ab | Festival of Life | Taming of the wild (`taming_of_the_wild`) | 3 | 0 | 0 | 3 |
| ab | Festival of Life | Razor Claw (`razor_claw`) | 3 | 9 | 0 | 12 |
| ab | Playing with Fire | Farming Towns (`farming_towns`) | 19 | 7 | 0 | 26 |
| ab | Playing with Fire | March of the Undead (`march_of_the_undead`) | 19 | 25 | 5 | 49 |
| ab | Playing with Fire | Burning of Tatalia (`burning_of_tatalia`) | 10 | 24 | 10 | 44 |
| ab | Foolhardy Waywardness | Lost at Sea (`lost_at_sea`) | 4 | 23 | 0 | 27 |
| ab | Foolhardy Waywardness | Here There Be Pirates (`here_there_be_pirates`) | 6 | 10 | 1 | 17 |
| ab | Foolhardy Waywardness | Hurry Up and Wait (`hurry_up_and_wait`) | 9 | 9 | 0 | 18 |
| ab | Foolhardy Waywardness | Their End of the Bargain (`their_end_of_the_bargain`) | 6 | 13 | 1 | 20 |
| sod | Rise of the Necromancer | Target (`target`) | 8 | 5 | 0 | 13 |
| sod | Rise of the Necromancer | Master (`master`) | 5 | 9 | 0 | 14 |
| sod | Rise of the Necromancer | Finneas Vilmar (`finneas_vilmar`) | 3 | 5 | 0 | 8 |
| sod | Rise of the Necromancer | Duke Alarice (`duke_alarice`) | 1 | 0 | 0 | 1 |
| sod | Hack and Slash | Bashing Skulls (`bashing_skulls`) | 3 | 3 | 0 | 6 |
| sod | Hack and Slash | Black Sheep (`black_sheep`) | 3 | 4 | 0 | 7 |
| sod | Hack and Slash | A Cage in the Hand (`a_cage_in_the_hand`) | 4 | 1 | 2 | 7 |
| sod | Hack and Slash | Grave Robber (`grave_robber`) | 5 | 5 | 1 | 11 |
| sod | Birth of a Barbarian | On the Run (`on_the_run`) | 7 | 5 | 0 | 12 |
| sod | Birth of a Barbarian | The Meeting (`the_meeting`) | 3 | 2 | 0 | 5 |
| sod | Birth of a Barbarian | A Tough Start (`a_tough_start`) | 6 | 0 | 3 | 9 |
| sod | Birth of a Barbarian | Falor and Terwen (`falor_and_terwen`) | 2 | 1 | 0 | 3 |
| sod | Birth of a Barbarian | Returning to Bracada (`returning_to_bracada`) | 5 | 0 | 1 | 6 |
| sod | New Beginning | Clearing the Border (`clearing_the_border`) | 11 | 0 | 4 | 15 |
| sod | New Beginning | After the Amulet (`after_the_amulet`) | 13 | 1 | 10 | 24 |
| sod | New Beginning | Retrieving the Cowl (`retrieving_the_cowl`) | 11 | 0 | 10 | 21 |
| sod | New Beginning | Driving for the Boots (`driving_for_the_boots`) | 15 | 0 | 10 | 25 |
| sod | Elixir of Life | Graduation Exercise (`graduation_exercise`) | 4 | 1 | 0 | 5 |
| sod | Elixir of Life | Cutthroats (`cutthroats`) | 8 | 0 | 0 | 8 |
| sod | Elixir of Life | Valley of the Dragon Lords (`valley_of_the_dragon_lords`) | 5 | 0 | 0 | 5 |
| sod | Elixir of Life | A Thief in the Night (`a_thief_in_the_night`) | 7 | 0 | 0 | 7 |
| sod | Unholy Alliance | Harvest (`harvest`) | 2 | 5 | 0 | 7 |
| sod | Unholy Alliance | Gathering the Legion (`gathering_the_legion`) | 3 | 1 | 5 | 9 |
| sod | Unholy Alliance | Search for a Killer (`search_for_a_killer`) | 13 | 0 | 0 | 13 |
| sod | Unholy Alliance | Final Peace (`final_peace`) | 9 | 0 | 10 | 19 |
| sod | Unholy Alliance | Secrets Revealed (`secrets_revealed`) | 10 | 6 | 2 | 18 |
| sod | Unholy Alliance | Agents of Vengeance (`agents_of_vengeance`) | 7 | 0 | 16 | 23 |
| sod | Unholy Alliance | Wrath of Sandro (`wrath_of_sandro`) | 8 | 1 | 5 | 14 |
| sod | Unholy Alliance | Invasion (`invasion`) | 9 | 9 | 9 | 27 |
| sod | Unholy Alliance | To Strive, To Seek (`to_strive_to_seek`) | 10 | 3 | 0 | 13 |
| sod | Unholy Alliance | Barbarian Brothers (`barbarian_brothers`) | 3 | 0 | 1 | 4 |
| sod | Unholy Alliance | Union (`union`) | 13 | 11 | 0 | 24 |
| sod | Unholy Alliance | Fall of Sandro (`fall_of_sandro`) | 18 | 0 | 0 | 18 |
| | **20 campaigns / 87 missions** | | | | | **985** |

## Long Live the Queen (`roe` / `Good1.h3c`)

### Homecoming (`homecoming`)

Source: `Good1.h3c` block 1 · H3M v21 · 9 events · sha256 `e8ca00cf30e6…` · LOD `H3bitmap.lod`

- [ ] `homecoming:global:0`
  - **Story Background, pt1** · briefing · day 1 · resources: —
  - message: From Catherine Ironfist, Queen of Enroth: "General, our initial landing shows evidence of…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `homecoming:global:1`
  - **Story Background, pt2** · briefing · day 1 · resources: —
  - message: "These people have been under Nighon military rule for the past thirty days. We assume th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `homecoming:global:2`
  - **Story Background, pt3** · briefing · day 1 · resources: —
  - message: "Other generals are fanning through the region to determine the extent of the territorial…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `homecoming:global:3`
  - **Story Background, pt4** · briefing · day 1 · resources: —
  - message: "If you can secure their main base of operations, we will be able to quickly eliminate an…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `homecoming:global:4`
  - **Recon: Mirham** · briefing · day 2 · resources: —
  - message: Returning from Mirham, a scout enters the Caryatid courtyard and reports, "Mirham is unde…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `homecoming:global:5`
  - **Recon: Plinth** · briefing · day 4 · resources: —
  - message: One of your aids approaches and hands you a scroll, mentioning that the scout who just de…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `homecoming:global:6`
  - **Recon: Trailia** · briefing · day 6 · resources: —
  - message: Leading his griffin mount, a scout bearing the cuts of arrows and harpy scratches, approa…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `homecoming:map:0:18:35`
  - **map_event:0:18:35** · unguarded map · visit @ `0:18:35` · resources: —
  - message: Having defeated the Troglodytes, your men free the Guardhouse. Within, the occupying Pike…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `homecoming:town:1:35:35:event:0`
  - **Computer Timber Supplies** · town timed · day 1, every 7d @ `town:1:35:35:event:0` (Terraneus) · resources: +14 wood
  - message: A caravan from the surface arrives with your weekly wood supplies.
  - notes: town=Terraneus | blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Guardian Angels (`guardian_angels`)

Source: `Good1.h3c` block 2 · H3M v21 · 2 events · sha256 `9b3564f27c87…` · LOD `H3bitmap.lod`

- [ ] `guardian_angels:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: We must reach Fair Feather before the Nighon and Eeofol forces. If we can show our suppor…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `guardian_angels:global:1`
  - **News** · briefing · day 3 · resources: —
  - message: Scouts report that there are several cave entrances in the area. It is likely that we wil…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Griffin Cliff (`griffin_cliff`)

Source: `Good1.h3c` block 3 · H3M v21 · 7 events · sha256 `7a711eda91b7…` · LOD `H3bitmap.lod`

- [ ] `griffin_cliff:global:1`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: The region of Griffin Cliff, the annual breeding grounds from which nearly all of Erathia…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `griffin_cliff:global:2`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: Nighon and Kreegan infestation in this area is significant, but we must free the Griffins…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `griffin_cliff:global:3`
  - **Intro part 3** · briefing · day 1 · resources: —
  - message: Seek out the Griffin Towers to the north. We must free them all before we can press on to…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `griffin_cliff:global:0`
  - **Bonus wood.** · timed resource · day 5, every 5d · resources: +10 wood
  - message: Wood for the dungeon overlords war effort
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `griffin_cliff:map:0:25:23`
  - **map_event:0:25:23** · guarded map · visit @ `0:25:23` · resources: +1500 gold
  - message: One of your soldiers suddenly cries out, "Ambush!" You have just enough time to draw your…
  - notes: guards: type43x50, type71x50, type73x30, type45x30, type47x20, type75x20, type81x5 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `griffin_cliff:map:0:29:8`
  - **map_event:0:29:8** · unguarded map · visit @ `0:29:8` · resources: —
  - message: Looks like an avalanche has blocked this pass.
  - notes: removeAfterVisit=false | blockers: audience_encoder_unproven; non_removing_event_lifetime_unproven; persistent_host_rebinding_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `griffin_cliff:map:0:46:23`
  - **map_event:0:46:23** · guarded map · visit @ `0:46:23` · resources: +1500 gold
  - message: One of your soldiers suddenly cries out, "Ambush!" You have just enough time to draw your…
  - notes: guards: type43x50, type71x50, type73x30, type45x30, type47x20, type75x20, type53x5 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)

## Liberation (`roe` / `Good2.h3c`)

### Steadwick's Liberation (`steadwick_liberation`)

Source: `Good2.h3c` block 1 · H3M v21 · 4 events · sha256 `cb027862def7…` · LOD `H3bitmap.lod`

- [ ] `steadwick_liberation:global:0`
  - **Intro 1** · briefing · day 1 · resources: —
  - message: Early intelligence reports indicate that forces from Nighon and Eeofol have barricaded th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `steadwick_liberation:global:1`
  - **Intro 2** · briefing · day 1 · resources: —
  - message: You will either need to find the passage they are using to enter the valley or find a way…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `steadwick_liberation:global:2`
  - **News of General Kendal part 1** · briefing · day 8 · resources: —
  - message: Word from the survivors of the Steadwick seige is that after King Gryphonheart's death, c…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `steadwick_liberation:global:3`
  - **News of General Kendal part 2** · briefing · day 8 · resources: —
  - message: According to witnesses, Gen. Kendal was captured during the fighting, and many believe th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Deal With the Devil (`deal_with_the_devil`)

Source: `Good2.h3c` block 2 · H3M v21 · 6 events · sha256 `8a75caf5dcc9…` · LOD `H3bitmap.lod`

- [ ] `deal_with_the_devil:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: A letter from a leader in Eeofol states clearly that King Roland Ironfist is a captive of…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `deal_with_the_devil:global:1`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: This claim can not be validated, but a thorough interrogation of the messenger has reveal…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `deal_with_the_devil:global:2`
  - **Intro part 3** · briefing · day 1 · resources: —
  - message: Clan Kreelah's main fortress, Kleesive, is located just on the other side of the Erathian…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `deal_with_the_devil:global:3`
  - **Intro part 4** · briefing · day 1 · resources: —
  - message: Forces from AvLee have come to assist us in this task. Good luck, and may the Light of th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `deal_with_the_devil:map:0:14:24`
  - **map_event:0:14:24** · guarded map · visit @ `0:14:24` · resources: +1500 gold
  - message: One of your soldiers cries "Ambush!" You have just enough time to draw your weapons.
  - notes: guards: type88x20, type90x20, type86x20 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `deal_with_the_devil:map:0:17:29`
  - **map_event:0:17:29** · guarded map · visit @ `0:17:29` · resources: +1500 gold
  - message: One of your soldiers cries "Ambush!" You have just enough time to draw your weapons.
  - notes: guards: type91x25 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)

### Neutral Affairs (`neutral_affairs`)

Source: `Good2.h3c` block 3 · H3M v21 · 4 events · sha256 `fe778dab13c0…` · LOD `H3bitmap.lod`

- [ ] `neutral_affairs:global:1`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: For months, Tatalia and Krewlod have fought with Erathia and with each other in a series …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_affairs:global:2`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: The Wizards have set up a modest outpost on the shared Erathian/Tatalian/Krewlod border. …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_affairs:global:3`
  - **Intro part 3** · briefing · day 1 · resources: —
  - message: Strike quickly, and eliminate all opposition in the area. We must teach our neighbors tha…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_affairs:global:0`
  - **Refugees** · briefing · day 3 · resources: —
  - message: A scout reports that there are many refugee camps along the border, populated with creatu…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Tunnels and Troglodytes (`tunnels_and_troglodytes`)

Source: `Good2.h3c` block 4 · H3M v21 · 4 events · sha256 `15bf879301c7…` · LOD `H3bitmap.lod`

- [ ] `tunnels_and_troglodytes:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: The Dungeon Overlords are clever. While the Devils of Eeofol attacked Erathia's borders, …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `tunnels_and_troglodytes:global:1`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: We should credit the Royal Erathian Military Command for holding the invasion to just the…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `tunnels_and_troglodytes:global:2`
  - **Intro part 3** · briefing · day 1 · resources: —
  - message: Forces from AvLee and Bracada will assist us in this final push. No Nighon or Eeofol outp…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `tunnels_and_troglodytes:global:3`
  - **Sailing away** · briefing · day 2 · resources: —
  - message: You might be able to take a large force to Nighon by sea, attacking them from above, but …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

## Song for the Father (`roe` / `Good3.h3c`)

### Safe Passage (`safe_passage`)

Source: `Good3.h3c` block 1 · H3M v21 · 1 events · sha256 `9add49a4b8fa…` · LOD `H3bitmap.lod`

- [ ] `safe_passage:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: The Necromancer, Nimbus, bears proof of who killed King Gryphonheart. He must reach our o…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### United Front (`united_front`)

Source: `Good3.h3c` block 2 · H3M v21 · 2 events · sha256 `e53f3ed8c075…` · LOD `H3bitmap.lod`

- [ ] `united_front:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: Never before has Erathia seen four nations fighting under a single banner. Today, we marc…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `united_front:global:1`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: To be victorious, you must completely control this area. Good luck, we're counting on you.
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### For King and Country (`for_king_and_country`)

Source: `Good3.h3c` block 3 · H3M v21 · 1 events · sha256 `3574d3926026…` · LOD `H3bitmap.lod`

- [ ] `for_king_and_country:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: The city containing the tomb of King Gryphonheart, along with the city where the King cur…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

## Dungeons and Devils (`roe` / `EVIL1.H3C`)

### A Devilish Plan (`a_devilish_plan`)

Source: `EVIL1.H3C` block 1 · H3M v21 · 3 events · sha256 `530775aeb44a…` · LOD `H3bitmap.lod`

- [ ] `a_devilish_plan:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: Our underlings have done well. They have managed to raise a volcano and erect a fort in a…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_devilish_plan:global:1`
  - **Intro Part 2** · briefing · day 1 · resources: —
  - message: The Gold Dragon Queen is a powerful ally of AvLee. You must find her lair and see to her …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_devilish_plan:map:0:61:54`
  - **map_event:0:61:54** · unguarded map · visit @ `0:61:54` · resources: —
  - message: Your scouts report that the immediate area is rich in resources, and that to the south th…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Groundbreaking (`groundbreaking`)

Source: `EVIL1.H3C` block 2 · H3M v21 · 5 events · sha256 `0f29ee4f5eb1…` · LOD `H3bitmap.lod`

- [ ] `groundbreaking:global:0`
  - **Day 1 Intro Part 1** · briefing · day 1 · resources: —
  - message: As we tunneled into the region, we discovered a splinter colony that had long ago been th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `groundbreaking:global:1`
  - **Day 1 Intro Part 2** · briefing · day 1 · resources: —
  - message: We also have an agent who has been spying on the towns in the area from a small, secluded…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `groundbreaking:global:2`
  - **News** · briefing · day 8 · resources: —
  - message: An advisor approaches. "We have received report that warships from Enroth have landed alo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `groundbreaking:global:3`
  - **News** · briefing · day 22 · resources: —
  - message: An advisor approaches. "The news is not good. The Enrothian force to the south is led by …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `groundbreaking:map:0:45:32`
  - **map_event:0:45:32** · unguarded map · visit @ `0:45:32` · resources: —
  - message: A voice booms down from the clouds: "Infidels! You have violated a sacred place, and must…
  - notes: non-resource: mana, morale, luck | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_mana; unsupported_reward_morale; unsupported_reward_luck; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Steadwick's Fall (`steadwicks_fall`)

Source: `EVIL1.H3C` block 3 · H3M v21 · 8 events · sha256 `98c0be881fd3…` · LOD `H3bitmap.lod`

- [ ] `steadwicks_fall:global:0`
  - **Intro 1** · briefing · day 1 · resources: —
  - message: You are to be congratulated on your progress so far. You have laid waste to Eastern Erath…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `steadwicks_fall:global:1`
  - **Intro 2** · briefing · day 1 · resources: —
  - message: Not only have Bracada and AvLee sent reinforcements, but we have received news that Queen…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `steadwicks_fall:global:2`
  - **News** · briefing · day 7 · resources: —
  - message: You have just received a report on the progress of Queen Catherine. Forces from Nighon an…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `steadwicks_fall:global:3`
  - **News** · briefing · day 29 · resources: —
  - message: You receive a report from the south. Queen Catherine's forces have been sufficiently dela…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `steadwicks_fall:global:4`
  - **News** · briefing · day 57 · resources: —
  - message: You receive a report from the south. Our forces continue to throw themselves in the path …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `steadwicks_fall:global:5`
  - **Warning** · briefing · day 71 · resources: —
  - message: Queen Catherine's march continues - her forces are just two weeks away. If you do not hur…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `steadwicks_fall:global:6`
  - **Warning** · briefing · day 78 · resources: —
  - message: Your scouts report sighting Queen Catherine's army seven days to the southwest. If she re…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `steadwicks_fall:global:7`
  - **Ending** · briefing · day 85 · resources: —
  - message: This morning, a massive army lead by Queen Catherine Ironfist arrived at the Erathian cap…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

## Long Live the King (`roe` / `Evil2.h3c`)

### A Gryphon's Heart (`a_gryphons_heart`)

Source: `Evil2.h3c` block 1 · H3M v21 · 2 events · sha256 `e8cdf3b944ee…` · LOD `H3bitmap.lod`

- [ ] `a_gryphons_heart:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: Our spies tell us that the tomb of King Gryphonheart is located in the town of Stonecastl…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_gryphons_heart:global:1`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: You must also seek out the Spirit of Oppression and bring it to Stonecastle, as it is one…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Season of Harvest (`season_of_harvest`)

Source: `Evil2.h3c` block 2 · H3M v21 · 6 events · sha256 `ef75140e0bb8…` · LOD `H3bitmap.lod`

- [ ] `season_of_harvest:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: To truly catch Erathia by surprise, we must attack within three months. However, our forc…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `season_of_harvest:global:1`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: As before, you must move quickly. We must have the element of surprise when we attack Era…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `season_of_harvest:global:5`
  - **News of Sandro** · briefing · day 5 · resources: —
  - message: One of your advisors approaches. "We have just learned that Sandro and his army are being…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `season_of_harvest:global:2`
  - **Warning 3 weeks left** · briefing · day 64 · resources: —
  - message: You receive a letter from your superiors. "Your initial progress is good, but you only ha…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `season_of_harvest:global:3`
  - **Warning 2 weeks left** · briefing · day 71 · resources: —
  - message: You receive a letter from your superiors. "I trust you are making progress. Remember, we …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `season_of_harvest:global:4`
  - **Warning 1 week left** · briefing · day 78 · resources: —
  - message: You receive a letter from your superiors. "One week from today, we launch our attack on E…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Corporeal Punishment (`corporeal_punishment`)

Source: `Evil2.h3c` block 3 · H3M v21 · 3 events · sha256 `ff9aa9196b27…` · LOD `H3bitmap.lod`

- [ ] `corporeal_punishment:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: You receive a letter from the Lich King Gryphonheart. "Commander: It would seem as though…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `corporeal_punishment:global:1`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: "We do, however, need his armies, and I can not allow his disobedience to go unpunished. …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `corporeal_punishment:global:2`
  - **Intro part 3** · briefing · day 1 · resources: —
  - message: Even gazing at the signature of the undead King sends a cold chill through you. You quick…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### From Day to Night (`from_day_to_night`)

Source: `Evil2.h3c` block 4 · H3M v21 · 2 events · sha256 `7905cf838677…` · LOD `H3bitmap.lod`

- [ ] `from_day_to_night:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: You received your orders personally from King Gryphonheart. You will launch your attack f…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `from_day_to_night:global:1`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: It is clear that King Gryphonheart wishes to return to the Throne of Erathia, but this ti…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

## Spoils of War (`roe` / `Neutral1.h3c`)

### Borderlands (`neutral_1a`)

Source: `Neutral1.h3c` block 1 · H3M v21 · 5 events · sha256 `c0d004ad305b…` · LOD `H3bitmap.lod`

- [ ] `neutral_1a:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: Your first orders from King Tralossk are simple enough: seize all mines in the region so …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1a:global:1`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: But there is good news and bad news. The good news is that the three Erathian outposts in…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1a:global:2`
  - **Intro part 3** · briefing · day 1 · resources: —
  - message: Of course, should you eliminate the opposition in the area, then you will be able to comp…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1a:map:0:42:19`
  - **map_event:0:42:19** · unguarded map · visit @ `0:42:19` · resources: —
  - message: A small group of gnolls appears from down the road. As they walk up to you (in a non-thre…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `neutral_1a:map:0:57:71`
  - **map_event:0:57:71** · unguarded map · visit @ `0:57:71` · resources: —
  - message: This road leads deeper into Erathia, but maybe you should secure this region before you m…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Gold Rush (`neutral_1b`)

Source: `Neutral1.h3c` block 2 · H3M v21 · 4 events · sha256 `1f9d27d75d9b…` · LOD `H3bitmap.lod`

- [ ] `neutral_1b:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: Long have we skirmished with the Erathian Military on our eastern border. Many credit us …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1b:global:1`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: Our interrogations of these prisoners confirmed our suspicions. Without their King, Erath…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1b:global:2`
  - **Intro part 3** · briefing · day 1 · resources: —
  - message: Until then, we require your independent participation to raid the Erathian territories to…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1b:global:3`
  - **Intro part 4** · briefing · day 1 · resources: —
  - message: You will be paid well, but you will need to work for your money. The Duke has determined …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Greed (`neutral_1c`)

Source: `Neutral1.h3c` block 3 · H3M v21 · 10 events · sha256 `5146d042769e…` · LOD `H3bitmap.lod`

- [ ] `neutral_1c:global:0`
  - **Tatalia intro part 1** · briefing · day 1 · resources: —
  - message: You receive a message from King Tralossk - "I am pleased that you have chosen to side wit…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1c:global:1`
  - **Tatalia intro part 2** · briefing · day 1 · resources: —
  - message: "This will be a fight to the finish. We wish to extend our borders into the Krewlod hills…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1c:global:2`
  - **Tatalia intro part 3** · briefing · day 1 · resources: —
  - message: "Do well, and you shall be idolized by all of Tatalia. Fail... well, we don't need to dis…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1c:global:3`
  - **Krewlod intro part 1** · briefing · day 1 · resources: —
  - message: You receive your orders from one of Duke Boragus's generals. "I've never liked mercenarie…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1c:global:4`
  - **Krewlod intro part 2** · briefing · day 1 · resources: —
  - message: "Anyway, in case you hadn't noticed, this is a border war. Ol' Tralossk has got it into h…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1c:global:5`
  - **Krewlod intro part 3** · briefing · day 1 · resources: —
  - message: "Now, your orders are clear. Stop the Tatalian advance, then beat those sorry Lizards so …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `neutral_1c:map:0:27:60`
  - **map_event:0:27:60** · guarded map · visit @ `0:27:60` · resources: +1500 gold
  - message: Bandits leap out of the underbrush and attack!
  - notes: guards: type99x100, type101x50 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `neutral_1c:map:0:43:66`
  - **map_event:0:43:66** · guarded map · visit @ `0:43:66` · resources: +1500 gold
  - message: Bandits leap out of the underbrush and attack!
  - notes: guards: type87x80, type89x40 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `neutral_1c:map:0:50:14`
  - **map_event:0:50:14** · guarded map · visit @ `0:50:14` · resources: +1500 gold
  - message: Bandits leap out of the underbrush and attack!
  - notes: guards: type99x100, type101x50 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `neutral_1c:map:0:76:15`
  - **map_event:0:76:15** · guarded map · visit @ `0:76:15` · resources: +1500 gold
  - message: Bandits leap out of the underbrush and attack!
  - notes: guards: type87x80, type89x40 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)

## Seeds of Discontent (`roe` / `Secret1.h3c`)

### The Grail (`the_grail`)

Source: `Secret1.h3c` block 1 · H3M v21 · 18 events · sha256 `dfe5d031d674…` · LOD `H3bitmap.lod`

- [ ] `the_grail:global:1`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: Even as you gather your forces to find the Grail, word reaches you that Erathian and AvLe…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `the_grail:global:2`
  - **Intro part 2** · briefing · day 1 · resources: —
  - message: Some of the locals are declaring for you. Most people are not taking sides. You MUST find…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `the_grail:global:0`
  - **Sister text** · briefing · day 7 · resources: —
  - message: Scouts report your sister is to the north with a large force of War Unicorns from AvLee. …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `the_grail:map:0:16:49`
  - **map_event:0:16:49** · unguarded map · visit @ `0:16:49` · resources: —
  - message: Several Elves, who have heard of your quest to unite the Contested Lands as a separate st…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_grail:map:0:19:34`
  - **map_event:0:19:34** · guarded map · visit @ `0:19:34` · resources: +1000 gold
  - message: Ambush! Erathian militia attack your troops!
  - notes: guards: type3x20, type6x10, type4x10, type1x20, type2x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `the_grail:map:0:23:54`
  - **map_event:0:23:54** · guarded map · visit @ `0:23:54` · resources: —
  - message: Ambush! AvLee Archer militia open fire on your forces!
  - notes: non-resource: artifacts | guards: type18x2, type18x2, type18x2, type19x3, type18x2, type18x2, type18x2 | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `the_grail:map:0:29:25`
  - **map_event:0:29:25** · unguarded map · visit @ `0:29:25` · resources: —
  - message: A group of Pegasi wish to aid you in your quest to find the Grail.
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_grail:map:0:29:49`
  - **map_event:0:29:49** · unguarded map · visit @ `0:29:49` · resources: —
  - message: You encounter a group of Centaurs and Dwarves. After you tell them of the plan to form th…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_grail:map:0:31:42`
  - **map_event:0:31:42** · unguarded map · visit @ `0:31:42` · resources: —
  - message: Hearing about your struggle for independence, a group of Elves joins you.
  - notes: non-resource: morale, luck, creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; unsupported_reward_luck; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_grail:map:0:36:30`
  - **map_event:0:36:30** · unguarded map · visit @ `0:36:30` · resources: —
  - message: A group of Unicorns approach you and wish to join in your quest for independence. They pr…
  - notes: non-resource: artifacts, creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_grail:map:0:38:59`
  - **map_event:0:38:59** · guarded map · visit @ `0:38:59` · resources: —
  - message: Ambush! Erathian Crossbow militia open fire at your forces!
  - notes: non-resource: artifacts | guards: type2x2, type2x2, type2x2, type3x3, type2x2, type2x2, type2x2 | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `the_grail:map:0:39:24`
  - **map_event:0:39:24** · guarded map · visit @ `0:39:24` · resources: —
  - message: A large force of War Unicorns charge out of the forest and attack! As your General rallie…
  - notes: non-resource: experience, morale, artifacts | guards: type19x12, type25x6, type24x4, type25x12, type24x4, type25x6, type19x12 | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_experience; unsupported_reward_morale; unsupported_reward_artifacts; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `the_grail:map:0:42:43`
  - **map_event:0:42:43** · unguarded map · visit @ `0:42:43` · resources: —
  - message: Hearing about your struggle for independence, a group of Elves joins you.
  - notes: non-resource: morale, luck, creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; unsupported_reward_luck; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_grail:map:0:44:25`
  - **map_event:0:44:25** · unguarded map · visit @ `0:44:25` · resources: —
  - message: A group of Pegasi wish to aid you in your quest to find the Grail.
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_grail:map:0:47:48`
  - **map_event:0:47:48** · unguarded map · visit @ `0:47:48` · resources: —
  - message: You come across a group of Dwarves and Centaurs who support your goal of independence for…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_grail:map:0:48:40`
  - **map_event:0:48:40** · guarded map · visit @ `0:48:40` · resources: +1000 gold
  - message: Ambush! Erathian militia attack your troops!
  - notes: guards: type3x20, type6x10, type4x10, type1x20, type2x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `the_grail:map:0:52:50`
  - **map_event:0:52:50** · unguarded map · visit @ `0:52:50` · resources: —
  - message: Several Elves, who have heard of your quest to unite the Contested Lands a separate state…
  - notes: non-resource: morale, creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_grail:map:0:52:54`
  - **map_event:0:52:54** · guarded map · visit @ `0:52:54` · resources: —
  - message: Ambush! AvLee Archer Militia open fire on your forces!
  - notes: non-resource: artifacts | guards: type18x2, type18x2, type18x2, type19x3, type18x2, type18x2, type18x2 | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)

### Independence (`independence`)

Source: `Secret1.h3c` block 2 · H3M v21 · 4 events · sha256 `d6526800e9e4…` · LOD `H3bitmap.lod`

- [ ] `independence:global:2`
  - **Wood shortage** · briefing · day 1 · resources: -20 wood
  - message: We must build Welnin, but the sawmills in the area have been sabotaged, and 'timber poach…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `independence:global:0`
  - **Stolen Wood** · timed resource · day 4 · resources: -1 wood
  - message: With wood in such short supply, the 'timber poachers' are running rampant.
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `independence:global:1`
  - **Stolen Wood and Gold** · briefing · day 5 · resources: -1 wood, -4000 gold
  - message: Overnight your wood stores were raided again, but now they've started taking gold, too!
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `independence:global:3`
  - **Stolen Wood and Gold repeating** · briefing · day 6, every 1d · resources: -1 wood, -3500 gold
  - message: Dispite our best efforts to stop them, the rebels continue to make off with our wood and …
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)

### The Road Home (`the_road_home`)

Source: `Secret1.h3c` block 3 · H3M v21 · 12 events · sha256 `a0039916e39e…` · LOD `H3bitmap.lod`

- [ ] `the_road_home:global:0`
  - **Intro part 1** · briefing · day 1 · resources: —
  - message: The town of Welnin awaits the arrival of the Grail. It is up to the Ranger, Ryland, to ge…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `the_road_home:map:0:10:3`
  - **map_event:0:10:3** · unguarded map · visit @ `0:10:3` · resources: —
  - message: Scouts report that Dendroid Guards in the region might be sympathetic to our cause.
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_road_home:map:0:13:61`
  - **map_event:0:13:61** · unguarded map · visit @ `0:13:61` · resources: —
  - message: Scouts report some of the Monks in this area seem sympathetic to our cause.
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_road_home:map:0:16:54`
  - **map_event:0:16:54** · unguarded map · visit @ `0:16:54` · resources: —
  - message: Scouts report that some of the Wood Elves in the area are sympathetic to our cause.
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_road_home:map:0:28:63`
  - **map_event:0:28:63** · unguarded map · visit @ `0:28:63` · resources: —
  - message: A small order of Monks approaches, and the leader decides your cause is just and they wil…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_road_home:map:0:36:55`
  - **map_event:0:36:55** · unguarded map · visit @ `0:36:55` · resources: +4294966296 gold
  - message: A small mercenary force of Swordsmen walk out of the nearby forest and ask to join your a…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_road_home:map:0:51:6`
  - **map_event:0:51:6** · unguarded map · visit @ `0:51:6` · resources: —
  - message: Scouts report some of the Wood Elves in this region are sympathetic to our cause.
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_road_home:map:0:53:31`
  - **map_event:0:53:31** · unguarded map · visit @ `0:53:31` · resources: —
  - message: A scout reports many of the Dwarves in this area are tired of an Erathian and AvLee prese…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_road_home:map:0:5:7`
  - **map_event:0:5:7** · unguarded map · visit @ `0:5:7` · resources: —
  - message: A scout tells you that some Swordsmen in this part of the woods might be sympathetic to o…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_road_home:map:0:65:11`
  - **map_event:0:65:11** · unguarded map · visit @ `0:65:11` · resources: —
  - message: A small pack of Unicorns approaches, and the leader of the herd steps forward and telepat…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_road_home:map:0:65:23`
  - **map_event:0:65:23** · unguarded map · visit @ `0:65:23` · resources: —
  - message: Scouts report some Unicorns in this area might be sympathetic to our cause.
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_road_home:town:0:38:41:event:0`
  - **Bonus Resources** · town timed · day 5, every 5d @ `town:0:38:41:event:0` (town) · resources: +5 mercury, +5 sulfur, +5 crystal, +5 gems, +1000 gold
  - message: AvLee sending resources for the war effort
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

## Specter of Power (`roe` / `Secret.h3c`)

### Poison Fit for a King (`poison_fit_for_a_king`)

Source: `Secret.h3c` block 1 · H3M v28 · 14 events · sha256 `a01ace8787b8…` · LOD `H3bitmap.lod`

- [ ] `poison_fit_for_a_king:global:0`
  - **Day One** · briefing · day 1 · resources: —
  - message: Sometimes Deyja lords will allow other creatures to move into an area under their control…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:global:1`
  - **Lord Haart** · briefing · day 5 · resources: —
  - message: As per the agreement, Lord Haart has recently left for maneuvers farther into Erathian te…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:global:2`
  - **Jerk** · briefing · day 9 · resources: —
  - message: Lord Haart has decided to play a little nastier than you anticipated. He has left four ca…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:global:3`
  - **Two Weeks** · briefing · day 14 · resources: —
  - message: So far the campaign is going well. Plenty of creatures fight tooth and nail only to becom…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:global:4`
  - **The Plan** · briefing · day 20 · resources: —
  - message: Mulling over the events of the past and looking towards the future, you slowly sip an exq…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:global:5`
  - **Effective Scouts** · briefing · day 27 · resources: -5000 gold
  - message: Your scouting parties "recruited" three messengers carrying pleas for assistance to Lord …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `poison_fit_for_a_king:global:6`
  - **Pay** · briefing · day 36, every 7d · resources: -2000 gold
  - message: To keep these effective troops in your service you must continue to pay them. In return, …
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `poison_fit_for_a_king:global:7`
  - **Trouble** · briefing · day 54 · resources: —
  - message: Once again trouble has come your way. One of those blasted knights made a suicide attack …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:global:8`
  - **Nightmare** · briefing · day 67 · resources: —
  - message: Resting peacefully is never an option for the undead. Each night you are plagued with hor…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:global:9`
  - **Nightmare** · briefing · day 69 · resources: —
  - message: The nightmare began as usual. Ethric was chasing you, waving his sword like the lunatic h…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:global:10`
  - **Nightmare** · briefing · day 71 · resources: —
  - message: As you roll over and raise your weak arm, the stench of seared flesh nearly chokes you. A…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:global:11`
  - **The Genie Barbarian** · briefing · day 89 · resources: —
  - message: Whispers in the darkness hint at things just out of sight and around the corner. You are …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:global:12`
  - **The Ranger** · briefing · day 93 · resources: —
  - message: There is no escaping this nightmare. Once again you are in the shadowy forest, this time …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `poison_fit_for_a_king:town:0:62:33:event:0`
  - **Troops** · town timed · day 37, every 7d @ `town:0:62:33:event:0` (town) · resources: —
  - message: Your money has been going to good use. Troops arrive as promised -- not many, but proof e…
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### To Build a Tunnel (`to_build_a_tunnel`)

Source: `Secret.h3c` block 2 · H3M v28 · 2 events · sha256 `968275959d76…` · LOD `H3bitmap.lod`

- [ ] `to_build_a_tunnel:global:0`
  - **Introduction** · briefing · day 1 · resources: -20 wood
  - message: The Dungeon Overlords have agreed to build you an underground tunnel to Erathia for the s…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `to_build_a_tunnel:global:1`
  - **Wood** · briefing · day 7, every 7d · resources: -5 wood
  - message: A transport cart burrows up from the ground to pick up the weekly supply of wood needed f…
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)

### Kreegan Alliance (`kreegan_alliance`)

Source: `Secret.h3c` block 3 · H3M v28 · 9 events · sha256 `a4651dc6396f…` · LOD `H3bitmap.lod`

- [ ] `kreegan_alliance:global:0`
  - **Day 1** · briefing · day 1 · resources: —
  - message: The Kreegans have demanded that the Necromancers prove their worth by hunting down the Ev…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `kreegan_alliance:global:2`
  - **Computer Resources** · briefing · day 1, every 1d · resources: +4 wood, +2 mercury, +4 ore, +2 sulfur, +2 crystal, +2 gems, +2 gold
  - message: This will give the computer resources every day.
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `kreegan_alliance:global:1`
  - **Day 5** · briefing · day 5 · resources: —
  - message: You have discovered why the Kreegans have not gotten the Ring back. A powerful Druid name…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `kreegan_alliance:global:4`
  - **Scout** · briefing · day 12 · resources: —
  - message: A scouting party returned early in the morning. They were too slow to catch the Silver Pe…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `kreegan_alliance:global:5`
  - **Best Spy** · briefing · day 15 · resources: —
  - message: It is always best to know your enemy, which is why you often use spies to find out what y…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `kreegan_alliance:global:6`
  - **Return** · briefing · day 20 · resources: —
  - message: Your spy returned today. The news was not good. Or at least that's what you gather from t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `kreegan_alliance:global:3`
  - **Speed is of the essence** · briefing · day 28 · resources: —
  - message: You must move quickly or face overwhelming odds. If you do not complete your mission in t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `kreegan_alliance:global:7`
  - **Necromancer** · briefing · day 38 · resources: —
  - message: It is always good to know someone who will retain and sell information. Fortunately you k…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `kreegan_alliance:global:8`
  - **Response** · briefing · day 56 · resources: -4 sulfur, -3000 gold
  - message: Dethmar has obtained some history on the Druid, but his price for revealing it to you is …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)

### With Blinders On (`with_blinders_on`)

Source: `Secret.h3c` block 4 · H3M v28 · 4 events · sha256 `16619e9cc653…` · LOD `H3bitmap.lod`

- [ ] `with_blinders_on:global:0`
  - **Day** · briefing · day 1 · resources: —
  - message: These young upstart lords will be no match for your experience in the field. Once you hav…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `with_blinders_on:map:0:10:15`
  - **map_event:0:10:15** · unguarded map · visit @ `0:10:15` · resources: —
  - message: (no message)
  - notes: non-resource: primarySkill | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_primarySkill; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `with_blinders_on:map:0:13:33`
  - **map_event:0:13:33** · unguarded map · visit @ `0:13:33` · resources: —
  - message: (no message)
  - notes: non-resource: primarySkill | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_primarySkill; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `with_blinders_on:map:0:25:24`
  - **map_event:0:25:24** · unguarded map · visit @ `0:25:24` · resources: —
  - message: (no message)
  - notes: non-resource: primarySkill | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_primarySkill; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

## Armageddon's Blade (`ab` / `ab.h3c`)

### Catherine's Charge (`catherines_charge`)

Source: `ab.h3c` block 1 · H3M v21 · 25 events · sha256 `6d53a43df27f…` · LOD `H3ab_bmp.lod`

- [ ] `catherines_charge:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: Following the initial invasion of Eeofol, you ran into the elite force of Kreegans known …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:1`
  - **An alert** · briefing · day 6 · resources: —
  - message: A scout comes racing to your camp bearing a message. He bows deeply before you and presen…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:14`
  - **A Second Message From Kendal** · briefing · day 10 · resources: —
  - message: A rider enters your camp carrying a message scroll that bears the seal of General Morgan …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:2`
  - **Good News at Last** · briefing · day 15 · resources: —
  - message: A runner leaps off his steed in a hurry to bring urgent news to his Queen. You take the m…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:17`
  - **A Message from Lucifer** · briefing · day 21 · resources: —
  - message: Pacing across the field, you wrack your brain for a way to make sense of this insane war …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:5`
  - **Delays and Despair** · briefing · day 29 · resources: —
  - message: A bedraggled and forlorn looking runner arrived at your tent. He was wounded but waved of…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:3`
  - **Rains Come** · briefing · day 31 · resources: -3 ore, -2000 gold
  - message: A torrential rain begins. The rain bears an odd odor and seems to be eating away at steel…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `catherines_charge:global:4`
  - **Rains Are Useful** · briefing · day 33 · resources: +6 sulfur
  - message: The chief alchemist reports to you that they have found a way to collect the rain and ext…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `catherines_charge:global:6`
  - **A Ray of Hope** · briefing · day 51 · resources: —
  - message: On the First Day of the Festival of Life, the fearsome clouds that brought the hateful ra…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:7`
  - **Terrible News** · briefing · day 60 · resources: —
  - message: A panic stricken man arrives in your camp one day with a message. Tearing it open, you po…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:8`
  - **A Letter from Roland** · briefing · day 62 · resources: —
  - message: As you continue on your quest to exact revenge on the followers of the mad King Lucifer, …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:9`
  - **Assassin** · briefing · day 66 · resources: —
  - message: Last night, during the Hour of the Wolf, a lone assassin armed with demonic magic artifac…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:15`
  - **Catherine Sends For Gelu** · briefing · day 72 · resources: —
  - message: The forces of Eeofol have proven to be mighty indeed. As such, daring plans and cunning t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:16`
  - **Nicolai** · briefing · day 90 · resources: —
  - message: In the long months since you left Enroth, your days have been filled with strife, terror,…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:10`
  - **Catherine's Speech** · briefing · day 112 · resources: —
  - message: You call your troops before you. Their morale is low and all are exhausted from the const…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:11`
  - **The War Drags On** · briefing · day 121 · resources: —
  - message: As the conflict drags on into its fourth month, the men seemed inspired yet weary. Report…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:12`
  - **The Messenger Returns** · briefing · day 135 · resources: —
  - message: A horseman approaches bearing a scroll. The man is the same one sent by you to locate Rol…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:global:13`
  - **Troops Trickle In** · briefing · day 149 · resources: —
  - message: A messenger arrives, snaps a scroll into your hand, salutes, and leaves. Quickly you open…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `catherines_charge:map:0:33:68`
  - **map_event:0:33:68** · unguarded map · visit @ `0:33:68` · resources: —
  - message: Standing before you is a city whose architecture you do not recognize. The rounded roofs,…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `catherines_charge:map:0:36:5`
  - **map_event:0:36:5** · unguarded map · visit @ `0:36:5` · resources: —
  - message: This gleaming citadel stands tall and defiant against the darkening skies that lay overhe…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `catherines_charge:map:0:51:38`
  - **map_event:0:51:38** · unguarded map · visit @ `0:51:38` · resources: —
  - message: Eeofol, land of demons and devilkin. It is said that the Kreegans were a punishment from …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `catherines_charge:map:0:54:57`
  - **map_event:0:54:57** · unguarded map · visit @ `0:54:57` · resources: —
  - message: The blackened walls of the border gate that once protected these lands from the horrors t…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `catherines_charge:map:0:56:7`
  - **map_event:0:56:7** · unguarded map · visit @ `0:56:7` · resources: —
  - message: Beyond these walls lies the dread land of Eeofol, a land of tremendous volcanic rifts and…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `catherines_charge:map:0:64:14`
  - **map_event:0:64:14** · unguarded map · visit @ `0:64:14` · resources: —
  - message: This city is Darqtane, named for a dark god long ago thought forgotten by the people of t…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `catherines_charge:town:0:6:39:event:0`
  - **Troops Trickle In** · town timed · day 149 @ `town:0:6:39:event:0` (Defiance) · resources: —
  - message: The following reinforcements have arrived.
  - notes: town=Defiance | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Seeking Armageddon (`seeking_armageddon`)

Source: `ab.h3c` block 2 · H3M v21 · 10 events · sha256 `fd298d4ff7e3…` · LOD `H3ab_bmp.lod`

- [ ] `seeking_armageddon:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: "You, my faithful Xeron, have been given the glorious task of locating the artifacts need…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `seeking_armageddon:global:1`
  - **A Visit from Sleen** · briefing · day 2 · resources: —
  - message: With a "bamf" sound and a cloud of brimstone teleports in Xex, the messenger you sent to …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `seeking_armageddon:global:6`
  - **Treasure!!!** · briefing · day 5 · resources: —
  - message: One of your spies reports a large cache of gold and resources lies to the north.
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `seeking_armageddon:global:4`
  - **Sleen Returns** · briefing · day 9 · resources: —
  - message: The flap to your tent is flung aside and a human figure thrown to the floor at his feet. …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `seeking_armageddon:global:3`
  - **Guerilla Raid** · briefing · day 15, every 14d · resources: -4 wood, -2 mercury, -4 ore, -2 sulfur, -2 crystal, -2 gems, -2000 gold
  - message: Your minions report that several key supply trains have been ambushed, the contents loote…
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `seeking_armageddon:global:5`
  - **Bad News Guerillas** · briefing · day 16 · resources: —
  - message: Reports start pouring in from all across the land. Someone has been hitting small encampm…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `seeking_armageddon:global:2`
  - **To Catch a Spy** · briefing · day 35 · resources: —
  - message: You were out pacing in the darkness last night, pondering the possibilities, when you sud…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `seeking_armageddon:global:7`
  - **Sit Rep** · briefing · day 40 · resources: —
  - message: "King Lucifer wishes to know what you are doing to acquire the pieces needed to build tha…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `seeking_armageddon:global:8`
  - **A Union is Formed** · briefing · day 66 · resources: —
  - message: A young pit fiend strides into the center of the encampment and makes his way to you. Onc…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `seeking_armageddon:map:0:4:55`
  - **map_event:0:4:55** · unguarded map · visit @ `0:4:55` · resources: —
  - message: (no message)
  - notes: non-resource: primarySkill | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_primarySkill; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Shadows of the Forest (`shadows_of_the_forest`)

Source: `ab.h3c` block 3 · H3M v21 · 9 events · sha256 `0baa6bc9ba83…` · LOD `H3ab_bmp.lod`

- [ ] `shadows_of_the_forest:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: Gelu, early this morning you received word your special skills are needed for a daring pl…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `shadows_of_the_forest:global:1`
  - **Guerilla Raids** · briefing · day 15, every 14d · resources: +4 wood, +2 mercury, +4 ore, +2 sulfur, +2 crystal, +2 gems, +2000 gold
  - message: The men you sent in to raid the enemy supply lines have returned with a healthy take.
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `shadows_of_the_forest:global:3`
  - **Gypsy Fortuneteller** · briefing · day 25 · resources: -1 gems, -7 gold
  - message: A travelling caravan of gypsies passes near your encampment and several of the men decide…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `shadows_of_the_forest:global:2`
  - **A Message From Ciele** · briefing · day 34 · resources: —
  - message: As you pass a small puddle, you hear a voice call out to you, gentle and soft. The voice …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `shadows_of_the_forest:global:5`
  - **A Message From Erdamon** · briefing · day 40 · resources: —
  - message: You are awoken to an odd feeling in the back of your neck, a tingling sensation warning o…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `shadows_of_the_forest:global:6`
  - **A Message From Fiur** · briefing · day 50 · resources: —
  - message: Sitting around the campfire last night, you and several of your most trusted advisors wer…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `shadows_of_the_forest:global:4`
  - **Talon Brigade Member Found** · briefing · day 54 · resources: —
  - message: A pair of warriors dragging a third enters the encampment early in the morning. The dragg…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `shadows_of_the_forest:map:0:33:6`
  - **map_event:0:33:6** · unguarded map · visit @ `0:33:6` · resources: —
  - message: What manner of oddity is this? The architecture matches nothing seen in Erathia, Avlee or…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `shadows_of_the_forest:town:0:67:27:event:0`
  - **Join ups** · town timed · day 2 @ `town:0:67:27:event:0` (Diasamere) · resources: —
  - message: Several new recruits have arrived.
  - notes: town=Diasamere | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Maker of Sorrows (`maker_of_sorrows`)

Source: `ab.h3c` block 4 · H3M v21 · 14 events · sha256 `3aa5e2c8b6ac…` · LOD `H3ab_bmp.lod`

- [ ] `maker_of_sorrows:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: "Sleen has provided us with the name of the man whom you will seek out. Grand Forgesmith …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `maker_of_sorrows:global:1`
  - **Guerilla Attacks News** · briefing · day 6 · resources: -4 wood, -2 mercury, -4 ore, -2 sulfur, -2 crystal, -2 gems, -2000 gold
  - message: Xex teleports into your presence with a message on his lips. Kneeling before his lord and…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `maker_of_sorrows:global:7`
  - **Hamper the computer** · timed resource · day 7, every 7d · resources: -3500 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `maker_of_sorrows:global:2`
  - **Khazandar's Location** · briefing · day 11 · resources: —
  - message: Sleen stumbles into the meeting area, having been pushed there by Xex. You turn and face …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `maker_of_sorrows:global:3`
  - **New about Catherine** · briefing · day 21 · resources: —
  - message: A hurried messenger demon rushes into your planning session early in the pre-dawn hours. …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `maker_of_sorrows:global:5`
  - **Gelu Kills Xeron's Mother** · briefing · day 38 · resources: —
  - message: A forlorn-looking Xex enters your chambers, a long look on his face. He obviously bears g…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `maker_of_sorrows:global:6`
  - **Spirits of the Dead** · briefing · day 48 · resources: —
  - message: In your sleep, you are visited by haunting dreams. In it spirits come to you, with a warn…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `maker_of_sorrows:global:4`
  - **Cat Marches on Kreelah** · briefing · day 66 · resources: —
  - message: Xex "bamfs" in and kneels before you while you are deeply involved in examining tactical …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `maker_of_sorrows:map:0:34:62`
  - **map_event:0:34:62** · unguarded map · visit @ `0:34:62` · resources: —
  - message: Ahead is an entrance to an old Nighon tunnel system. At last Sleen's information is start…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `maker_of_sorrows:map:1:44:72`
  - **map_event:1:44:72** · unguarded map · visit @ `1:44:72` · resources: —
  - message: The musty smell down here is stifling. A feeling of uncertainty is nagging at the backsid…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `maker_of_sorrows:map:1:45:63`
  - **map_event:1:45:63** · unguarded map · visit @ `1:45:63` · resources: —
  - message: The dank, moldy smell of dragon dung hangs thick in the air. Perhaps this way is not a go…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `maker_of_sorrows:map:1:54:53`
  - **map_event:1:54:53** · unguarded map · visit @ `1:54:53` · resources: —
  - message: Echoing off the walls of the caverns comes a sound you've never heard before. It's a sort…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `maker_of_sorrows:map:1:58:67`
  - **map_event:1:58:67** · unguarded map · visit @ `1:58:67` · resources: —
  - message: There is the crackling of electricity up ahead and several of your men have their hair st…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `maker_of_sorrows:map:1:62:68`
  - **map_event:1:62:68** · unguarded map · visit @ `1:62:68` · resources: —
  - message: Washes of heat are coming from down this passageway. Perhaps a nice cozy lava pool is up …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Return of the King (`return_of_the_king`)

Source: `ab.h3c` block 5 · H3M v21 · 8 events · sha256 `acce5b80527f…` · LOD `H3ab_bmp.lod`

- [ ] `return_of_the_king:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: Standing on the edge of the Great Lake, you, the King of Enroth, contemplate the situatio…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `return_of_the_king:global:1`
  - **Letter from Catherine** · briefing · day 5 · resources: —
  - message: A letter arrived in your encampment last night from Catherine. You lit up like a child at…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `return_of_the_king:global:2`
  - **Spies Find Gold** · briefing · day 11 · resources: —
  - message: A message came in late last night that some scouts located an island east of Faler-on-Sea…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `return_of_the_king:global:3`
  - **The Farmer** · briefing · day 13 · resources: —
  - message: As General Kendal prepares to address his troops for the morning, a timid farmer is broug…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `return_of_the_king:global:4`
  - **Centaur Messenger** · briefing · day 22 · resources: —
  - message: A young centaur messenger arrives this morning just after breakfast was being cleared up,…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `return_of_the_king:global:5`
  - **Roland's Nightmare** · briefing · day 33 · resources: —
  - message: Images and sounds swirl through your mind as you sleep; terrible images brought forth fro…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `return_of_the_king:global:6`
  - **Nicolai's Birthday** · briefing · day 40 · resources: —
  - message: You stand atop a small rise and look out over the Great Lake, eyes filled with tears, for…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `return_of_the_king:map:0:17:56`
  - **map_event:0:17:56** · guarded map · visit @ `0:17:56` · resources: —
  - message: This small tidal pool is in fact the resting place of a powerful Aquamancer. Upon disturb…
  - notes: guards: type121x20, type127x50, type123x50 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)

### A Blade in the Back (`a_blade_in_the_back`)

Source: `ab.h3c` block 6 · H3M v21 · 13 events · sha256 `02342c86f111…` · LOD `H3ab_bmp.lod`

- [ ] `a_blade_in_the_back:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: The message sent last night told you the following: "Gelu, you have been doing well thus …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_blade_in_the_back:global:5`
  - **Political Unrest** · briefing · day 2 · resources: —
  - message: A letter arrives from Queen Catherine by griffin rider. The rider, in an obvious hurry, s…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_blade_in_the_back:global:1`
  - **Sleen Captured** · briefing · day 3 · resources: —
  - message: Stemming the tide of escaping refugees when one is looking for the enemy is never an easy…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_blade_in_the_back:global:2`
  - **Guerilla Raid** · briefing · day 5 · resources: —
  - message: A note is delivered to you via a strange messenger, a corpse spiked to a tree. When you g…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_blade_in_the_back:global:3`
  - **Halfling Guerrillas** · briefing · day 12 · resources: —
  - message: Kieran, one of your most trusted scouts, reports that yesterday his team was on a watchdo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_blade_in_the_back:global:4`
  - **Note From Roland** · briefing · day 21 · resources: —
  - message: A letter is delivered by griffin rider this morning bearing the seal of the King of Enrot…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_blade_in_the_back:global:6`
  - **Gelu sends a runner** · briefing · day 22 · resources: —
  - message: All this talk of the Sons of Erebus has you wondering, so you summon a runner to visit wi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_blade_in_the_back:global:8`
  - **Halflings Strike Back** · briefing · day 33 · resources: —
  - message: Your spies report several halfling guerillas have won a minor victory and taken the suppl…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_blade_in_the_back:global:7`
  - **Runner returns** · briefing · day 40 · resources: —
  - message: Early in the morning, the runner you sent to consult with Judge Fairweather returns. He i…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_blade_in_the_back:global:9`
  - **Smith name revealed** · briefing · day 50 · resources: —
  - message: At dusk last night a small boy came running into camp, seeking the pale warrior called De…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_blade_in_the_back:map:0:43:17`
  - **map_event:0:43:17** · unguarded map · visit @ `0:43:17` · resources: —
  - message: You see ahead what appears to be a battlefield with several dozen dead on both sides of t…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `a_blade_in_the_back:map:0:66:65`
  - **map_event:0:66:65** · unguarded map · visit @ `0:66:65` · resources: —
  - message: As your army approaches the city of Jagos, you can see a peculiar thing. There are scores…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `a_blade_in_the_back:map:0:9:29`
  - **map_event:0:9:29** · guarded map · visit @ `0:9:29` · resources: —
  - message: A group of demons appears to be fleeing. Either that or they've been sent on a suicide mi…
  - notes: non-resource: morale | guards: type42x6, type48x3, type44x4 | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)

### To Kill A Hero (`to_kill_a_hero`)

Source: `ab.h3c` block 7 · H3M v21 · 13 events · sha256 `bfa1fd9a98e7…` · LOD `H3ab_bmp.lod`

- [ ] `to_kill_a_hero:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: Support has greatly waned amongst the Erathian nobility, for this war in the past few mon…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_kill_a_hero:global:1`
  - **Opening Part II** · briefing · day 1 · resources: —
  - message: The days ahead will be filled with rough terrain and sleepless nights. Roland and your fo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_kill_a_hero:global:2`
  - **Cat Learns Gelu is here** · briefing · day 2 · resources: —
  - message: A runner from the north approaches your encampment with caution. He wears the markings of…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_kill_a_hero:global:3`
  - **Conflux Warning** · briefing · day 11 · resources: —
  - message: A shadowy figure slips into the meeting chamber where you sit with your advisors. This wi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_kill_a_hero:global:5`
  - **Roland's Semi-Evil Speech** · briefing · day 20 · resources: —
  - message: Roland stood to address his troops, marching back and forth across the makeshift stage he…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_kill_a_hero:global:4`
  - **Kendal Sends Covert Aid** · briefing · day 25 · resources: +3 wood, +1 mercury, +3 ore, +1 sulfur, +1 crystal, +1 gems, +5000 gold
  - message: A small supply wagon shows up with a note proclaiming this wagon is a gift from a friend.…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `to_kill_a_hero:global:6`
  - **Portents of Doom** · briefing · day 31 · resources: —
  - message: "My Queen," reports a page to you, "you have a visitor. He is claiming he represents the …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_kill_a_hero:global:7`
  - **Atrocities** · briefing · day 35 · resources: —
  - message: A report comes in to Roland. The message tells of horrible atrocities committed by the Kr…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_kill_a_hero:global:8`
  - **A Letter to Roland from Catherine** · briefing · day 40 · resources: —
  - message: Roland awoke early this morning to a messenger bringing with him a letter bearing the sce…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_kill_a_hero:town:0:27:12:event:0`
  - **Fresh troops** · town timed · day 1, every 21d @ `town:0:27:12:event:0` (Xent'a) · resources: —
  - message: (no message)
  - notes: town=Xent'a | blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `to_kill_a_hero:town:0:35:35:event:0`
  - **Fresh troops** · town timed · day 1 @ `town:0:35:35:event:0` (Kelvishen) · resources: —
  - message: Here.
  - notes: town=Kelvishen | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `to_kill_a_hero:town:0:35:57:event:0`
  - **Fresh Troops** · town timed · day 1 @ `town:0:35:57:event:0` (Shadowden) · resources: —
  - message: Here
  - notes: town=Shadowden | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `to_kill_a_hero:town:0:63:43:event:0`
  - **Fresh Troops** · town timed · day 1 @ `town:0:63:43:event:0` (Xent'ara) · resources: —
  - message: Her
  - notes: town=Xent'ara | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Oblivion's Edge (`oblivions_edge`)

Source: `ab.h3c` block 8 · H3M v21 · 8 events · sha256 `ee8802bd8cbe…` · LOD `H3ab_bmp.lod`

- [ ] `oblivions_edge:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: Xeron has been defeated, but managed to teleport away before he could be finished off. St…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `oblivions_edge:global:1`
  - **Nighon Emissary Captured** · briefing · day 4 · resources: —
  - message: During the early hours after breakfast, a runner reports to Catherine that some outer pat…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `oblivions_edge:global:2`
  - **Seduced by the Blade** · briefing · day 10 · resources: —
  - message: Last eve as Gelu lay sleeping in his bunk; an odd dream came to him. It was filled with v…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `oblivions_edge:global:3`
  - **Tamar's Return** · briefing · day 14 · resources: —
  - message: In the darkest hours before dawn, Catherine is awoken by a soft wind blowing across her b…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `oblivions_edge:global:4`
  - **Sleen Sentenced** · briefing · day 16 · resources: —
  - message: A message was received by all this morning informing the leaders of Catherine's army abou…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `oblivions_edge:global:5`
  - **Tavin's Guerillas Strike Again** · briefing · day 25 · resources: —
  - message: Early in the morning a legion of halfling slingers from Tavin's Guerillas stopped by to i…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `oblivions_edge:global:6`
  - **Ghosts of Conscience** · briefing · day 33 · resources: —
  - message: Roland lay sleeping in his bed last eve, drenched in sweat, his mind racing and filled wi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `oblivions_edge:town:0:37:36:event:0`
  - **Cash Flow** · town timed · day 7, every 7d @ `town:0:37:36:event:0` (Kreelah) · resources: +10 mercury, +40000 gold
  - message: Here ya go dude. Kick ass!
  - notes: town=Kreelah | blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

## Dragon's Blood (`ab` / `blood.h3c`)

### Culling the Weak (`culling_the_weak`)

Source: `blood.h3c` block 1 · H3M v21 · 24 events · sha256 `bc24dc39bb4f…` · LOD `H3ab_bmp.lod`

- [ ] `culling_the_weak:global:0`
  - **Day 1 Intro** · briefing · day 1 · resources: —
  - message: My spies have brought news; two young and hungry lords have launched near simultaneous at…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:1`
  - **Day 1 Intro (con)** · briefing · day 1 · resources: —
  - message: The time is ripe to kick out the young upstart lords and seize the old warlock's lands. O…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:2`
  - **War Diary Red Dragons** · briefing · day 3 · resources: —
  - message: War Diary: Today my scouts reported a small group of wild Red Dragons have built a nest b…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:3`
  - **War Diary Green Lord** · briefing · day 4 · resources: —
  - message: War Diary: My western scouts report Lord Caomham's green banner is flying over Harpy's Ro…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:4`
  - **War Diary Tan Lord** · briefing · day 5 · resources: —
  - message: War Diary: This evening an out of breath scout reported Lord Preuet's tan troops have sei…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:5`
  - **War Diary Upper Caverns** · briefing · day 9 · resources: —
  - message: War Diary: My scouts say there are at least three castles in the upper caverns. The neare…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:6`
  - **War Diary Sage's Note** · briefing · day 11 · resources: —
  - message: War Diary: Today I receive a note from a sage near Sinkhole Castle asking for a visit. He…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:8`
  - **War Diary Town Revolts** · briefing · day 14 · resources: —
  - message: War Diary: Today, a group of scouts reported that four of Ordwald's towns have revolted a…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:9`
  - **War Diary Missing Garrisons** · briefing · day 20 · resources: —
  - message: War Diary: Ordwald has not yet been spotted. Whatever his flaws, he is a powerful warlock…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:7`
  - **War Diary Troops Need to Guard Homeland** · briefing · day 36 · resources: —
  - message: War Diary: I received a message today from General Maih. The neighboring Lords around my …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:11`
  - **War Diary Miah's extra recruits** · briefing · day 42 · resources: —
  - message: War Diary: I received a message from Miah today. The Lords surrounding my home lands have…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:12`
  - **War Diary Recruits arrived** · briefing · day 47 · resources: —
  - message: War Diary: The extra recruits arrived today. I distributed then evenly over all of my new…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:global:10`
  - **War Diary ?** · briefing · day 56 · resources: —
  - message: War Diary: Strange, still no sign of Ordwald. The Master of Scouts has not located him an…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `culling_the_weak:town:1:21:18:event:0`
  - **Add Townhall** · town timed · day 2 @ `town:1:21:18:event:0` (town) · resources: +4294964796 gold
  - message: Help for Ordwald
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `culling_the_weak:town:1:21:18:event:1`
  - **Add Citadel** · town timed · day 4 @ `town:1:21:18:event:1` (town) · resources: +4294967291 ore, +4294964796 gold
  - message: Help for Ordwald
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `culling_the_weak:town:1:21:18:event:2`
  - **Add Mushroom Rings** · town timed · day 6 @ `town:1:21:18:event:2` (town) · resources: —
  - message: Help for Ordwald
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `culling_the_weak:town:0:18:33:event:0`
  - **Recruits** · town timed · day 47 @ `town:0:18:33:event:0` (town) · resources: —
  - message: Additional recruits arrived here today.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `culling_the_weak:town:0:60:30:event:0`
  - **Recruits** · town timed · day 47 @ `town:0:60:30:event:0` (town) · resources: —
  - message: Additional recruits arrived here today.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `culling_the_weak:town:0:62:57:event:0`
  - **Reinforcements from Home** · town timed · day 47 @ `town:0:62:57:event:0` (Sinkhole) · resources: —
  - message: Additional recruits arrived at Sinkhole Castle today.
  - notes: town=Sinkhole | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `culling_the_weak:town:1:24:57:event:0`
  - **Recruits from home** · town timed · day 47 @ `town:1:24:57:event:0` (Harpy's Rock) · resources: —
  - message: Additional recruits arrived at Harpy's Rock Castle today.
  - notes: town=Harpy's Rock | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `culling_the_weak:town:1:37:57:event:0`
  - **Recruits from home** · town timed · day 47 @ `town:1:37:57:event:0` (town) · resources: —
  - message: Additional recruits arrived here today.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `culling_the_weak:town:1:54:19:event:0`
  - **Recruits from home** · town timed · day 47 @ `town:1:54:19:event:0` (Dead Timber) · resources: —
  - message: Additional recruits arrived at Dead Timber Castle today.
  - notes: town=Dead Timber | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `culling_the_weak:town:1:54:57:event:0`
  - **Reinforcements from Home** · town timed · day 47 @ `town:1:54:57:event:0` (Death Kiss) · resources: —
  - message: Additional recruits arrived at Death Kiss Castle today.
  - notes: town=Death Kiss | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `culling_the_weak:town:1:59:38:event:0`
  - **Recruits from home** · town timed · day 47 @ `town:1:59:38:event:0` (town) · resources: —
  - message: Additional recruits arrived here today.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Savaging the Scavengers (`savaging_the_scavengers`)

Source: `blood.h3c` block 2 · H3M v21 · 12 events · sha256 `2c3a4a124f4a…` · LOD `H3ab_bmp.lod`

- [ ] `savaging_the_scavengers:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: The Vial of Dragon Blood will give me the edge I need to force my way into the ranks of p…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:1`
  - **Intro (con)** · briefing · day 1 · resources: —
  - message: General Miah will mop up the last resistance in Ordwald's old lands and then rebuild the …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:2`
  - **Charm of Mana** · briefing · day 3 · resources: —
  - message: War Diary: I kept the Charm of Mana, a worthless trinket if I've ever seen one, because t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:3`
  - **No Quarter Scouting Report** · briefing · day 6 · resources: —
  - message: War Diary: My scouts found a second Dungeon Castle called No Quarter to the northwest of …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:4`
  - **Tan Lord Scouting Report** · briefing · day 10 · resources: —
  - message: War Diary: Some of my scouts found Lord Preuet's base. His troops are flying a tan banner…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:5`
  - **Green Lord Scouting Report** · briefing · day 14 · resources: —
  - message: War Diary: Several days ago, scouts spotted Lord Caomham's green bannered troops at a cas…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:6`
  - **Questgate Scouting Report** · briefing · day 16 · resources: —
  - message: War Diary: Today, the Master of Scouts reported a strange Border Guard who will only let …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:8`
  - **Tactics** · briefing · day 23 · resources: —
  - message: War Diary: It will be a lot harder to take out Preuet and Caomham if they were smart enou…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:7`
  - **Dead Scout** · briefing · day 27 · resources: —
  - message: War Diary: I had to kill a scout today. He was whining about being outnumbered 2 to 1. I …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:9`
  - **Ordwald's Forces** · briefing · day 39 · resources: —
  - message: War Diary: My scouts have located some of Ordwald's forces in the Deep Caverns. From the …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:10`
  - **The Heat is On** · briefing · day 54 · resources: —
  - message: War Diary: I received word from General Miah today. The word is out along the Nighon bord…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `savaging_the_scavengers:global:11`
  - **Matter of Time** · briefing · day 69 · resources: —
  - message: War Diary: Miah reports the border lords have changed tactics. They are flooding the area…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Blood of the Dragon Father (`blood_of_the_dragon_father`)

Source: `blood.h3c` block 3 · H3M v21 · 15 events · sha256 `e169ffc1f961…` · LOD `H3ab_bmp.lod`

- [ ] `blood_of_the_dragon_father:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: I always thought I would be a powerful noble one day. Taking Rauric's Lands was only the …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:1`
  - **Intro (cont)** · briefing · day 1 · resources: —
  - message: General Miah will take command of the troops in my old staging area (and new castles) nea…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:2`
  - **Scouting Report 1st Castle** · briefing · day 2 · resources: —
  - message: War Diary: Today some of my scouts reported Ordwald's troops hold a castle to the West. T…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:3`
  - **Campaign Journal 1** · briefing · day 5 · resources: —
  - message: War Diary: I imagine Ordwald's troops near here are picket or screening troops. As soon a…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:4`
  - **Scout Report River** · briefing · day 17 · resources: —
  - message: War Diary: Today my scouts reported that further on to the west past the first enemy cast…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:12`
  - **Scout report prison** · briefing · day 24 · resources: —
  - message: War Diary: My scouts found a prison along the river today. A warlock named Alamar is impr…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:5`
  - **Campaign Journal 2** · briefing · day 31 · resources: —
  - message: War Diary: I talked to the castle's Barkeep the other day. After tossing him a few gold a…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:6`
  - **Campaign Journal 2 (cont)** · briefing · day 31 · resources: —
  - message: and the power of a normal dragon. I was fascinated. I love my Red and Black Dragons and e…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:7`
  - **Campaign Journal 3** · briefing · day 38 · resources: —
  - message: War Diary: Certain resources seem scarce in this part of the Deep Caverns. I haven't been…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:8`
  - **Campaign Journal 4** · briefing · day 63 · resources: —
  - message: War Diary: I've been thinking about the magical plain areas containing trees and other Br…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:9`
  - **Campaign Journal 5** · briefing · day 74 · resources: —
  - message: War Diary: I have to wonder if the Father of All Dragons may have once lived in the Deep …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:10`
  - **Campaign Journal 6** · briefing · day 84 · resources: —
  - message: War Diary: Good commanders have to plan for all the things that might happen. That way wh…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:global:11`
  - **Campaign Journal 7** · briefing · day 99 · resources: —
  - message: War Diary: Miah sent a message that three powerful Nighon Lords are heading for the Borde…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_of_the_dragon_father:map:1:5:6`
  - **map_event:1:5:6** · unguarded map · visit @ `1:5:6` · resources: —
  - message: War Diary: Some of my scouts report they have discovered strange types of Dragons. I'll h…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `blood_of_the_dragon_father:map:1:88:50`
  - **map_event:1:88:50** · unguarded map · visit @ `1:88:50` · resources: —
  - message: A group of returning scouts report Ordwald and his armies are near. The scouts report Ord…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Blood Thirsty (`blood_thirsty`)

Source: `blood.h3c` block 4 · H3M v21 · 13 events · sha256 `363c25a902d9…` · LOD `H3ab_bmp.lod`

- [ ] `blood_thirsty:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: Defeating the Lords blocking your access to the surface tunnels and the Nighon borderland…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:global:1`
  - **Campaign Journal 1** · briefing · day 2 · resources: —
  - message: War Diary: Things are going according to plan. I have established a base in the tunnels b…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:global:10`
  - **Scout Report Gold and Leprechaun** · briefing · day 3 · resources: —
  - message: War Diary: My Master of Scouts reported the Subterranean Gate near Castle Bat Fang leads …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:global:2`
  - **Scout Report NW Castle** · briefing · day 4 · resources: —
  - message: War Diary: Today the Master of Scouts reported his scouts found a neutral castle in the c…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:global:3`
  - **Scout report SE Castle** · briefing · day 5 · resources: —
  - message: War Diary: My scouts have located another neutral castle to the southeast from my startin…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:global:4`
  - **Campaign Journal 2** · briefing · day 10 · resources: —
  - message: War Diary: A messager from General Miah, arrived today. He has obtained information, whic…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:global:11`
  - **Scout Reinforcements from Deep Caverns** · briefing · day 17 · resources: —
  - message: War Diary: My Master of Scouts had good news and bad news today. The good news was a grou…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:global:6`
  - **Scout report Dragon Utopias** · briefing · day 23 · resources: —
  - message: War Diary: A while back scouts located a Dragon Utopia to the northwest, near a subterran…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:global:5`
  - **Campaign Journal 3** · briefing · day 33 · resources: —
  - message: War Diary: I'm going to have to counter Ordwald's lies. If people actually believe they c…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:global:8`
  - **Campaign Journal 5** · briefing · day 43 · resources: —
  - message: War Diary: Today I sent a messager to the Sage by Sinkhole Castle. I asked him to do some…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:global:9`
  - **Campaign Journal 6** · briefing · day 50 · resources: -5 mercury, -5 sulfur, -5 crystal, -5 gems
  - message: War Diary: I got a message back from the sage agreeing to do the research. Unfortunately,…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `blood_thirsty:global:7`
  - **Campaign Journal 4** · briefing · day 55 · resources: —
  - message: War Diary: Today I sent a message to General Miah to leak word to the borderlands that dr…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `blood_thirsty:map:1:72:58`
  - **map_event:1:72:58** · unguarded map · visit @ `1:72:58` · resources: —
  - message: Reinforcements arrive from your lands in the Deep Caverns.
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

## Dragon Slayer (`ab` / `slayer.h3c`)

### Rust Dragons (`rust_dragons`)

Source: `slayer.h3c` block 1 · H3M v21 · 8 events · sha256 `d8562f603869…` · LOD `H3ab_bmp.lod`

- [ ] `rust_dragons:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: The people of Bracada have kept the Krewlodians at bay by controlling the mines. Now Rust…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `rust_dragons:global:4`
  - **Stuff for Enemy** · timed resource · day 1, every 1d · resources: +2 wood, +1 mercury, +2 ore, +1 sulfur, +3 crystal, +1 gems, +500 gold
  - message: Here
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `rust_dragons:global:1`
  - **Collar CarryOver** · briefing · day 7 · resources: —
  - message: After a few drinks you and your troops start to exchange war stories. One of the tales th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `rust_dragons:global:2`
  - **Carry over of Crown** · briefing · day 8 · resources: —
  - message: Not wanting to make a habit of getting drunk every night you decide to go to sleep early.…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `rust_dragons:global:3`
  - **carry over of crown 2** · briefing · day 8 · resources: —
  - message: You remember seeing yourself fighting a Blue Dragon, awesome in size. What really caught …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `rust_dragons:map:0:16:46`
  - **map_event:0:16:46** · guarded map · visit @ `0:16:46` · resources: —
  - message: As you walk towards the entrance you notice it is unusually quiet. Then just before you e…
  - notes: guards: type135x1, type135x2, type135x3, type135x4, type135x3, type135x2, type135x1 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `rust_dragons:map:0:16:47`
  - **map_event:0:16:47** · guarded map · visit @ `0:16:47` · resources: —
  - message: As you approach the mine you notice that it is very very quite.
  - notes: guards: empty | removeAfterVisit=true | blockers: audience_encoder_unproven; hasGuards_true_but_empty_guardStacks; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `rust_dragons:map:0:50:69`
  - **map_event:0:50:69** · unguarded map · visit @ `0:50:69` · resources: —
  - message: Hidden behind an unused part of the Water Mill is what looks like a very old book.
  - notes: non-resource: artifacts | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Faerie Dragons (`faerie_dragons`)

Source: `slayer.h3c` block 2 · H3M v21 · 17 events · sha256 `02161a430459…` · LOD `H3ab_bmp.lod`

- [ ] `faerie_dragons:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: It has come to your attention there are Faerie Dragons lurking about somewhere on the Wes…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `faerie_dragons:global:1`
  - **Neclace** · briefing · day 8 · resources: —
  - message: As you are traveling down the road you and your army come across an old lady that says sh…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `faerie_dragons:global:2`
  - **Neclace 2** · briefing · day 8 · resources: -2000 gold
  - message: What the old lady tells you is quite surprising, "The Celestial Necklace of Bliss will be…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `faerie_dragons:global:3`
  - **Get pendant** · briefing · day 20 · resources: —
  - message: Once the Pendant of Life was used to keep evil at bay. Recently it was stolen. Rumor has …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `faerie_dragons:map:0:102:54`
  - **map_event:0:102:54** · guarded map · visit @ `0:102:54` · resources: —
  - message: After long hours of walking down this path you approach a Redwood Observatory. Sitting at…
  - notes: guards: type2x20, type6x15, type2x20, type7x30, type2x20, type6x15, type2x20 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `faerie_dragons:map:0:104:55`
  - **map_event:0:104:55** · unguarded map · visit @ `0:104:55` · resources: +5000 gold
  - message: Reaching the base of the Redwood Observatory you see why these men attacked as they did. …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `faerie_dragons:map:0:10:51`
  - **map_event:0:10:51** · unguarded map · visit @ `0:10:51` · resources: —
  - message: Just as you are about to attack the dragon you think you hear the leprechaun's voice in y…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `faerie_dragons:map:0:11:53`
  - **map_event:0:11:53** · unguarded map · visit @ `0:11:53` · resources: —
  - message: After the disorienting feeling of the teleporter wears off you start down the path. You c…
  - notes: non-resource: morale, luck | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; unsupported_reward_luck; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `faerie_dragons:map:0:14:11`
  - **map_event:0:14:11** · unguarded map · visit @ `0:14:11` · resources: —
  - message: After you beat the Faerie Dragons you look around you only to notice the image around, wa…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `faerie_dragons:map:0:14:12`
  - **map_event:0:14:12** · guarded map · visit @ `0:14:12` · resources: —
  - message: As you walk towards the town you notice it is abandoned. Perhaps you can turn this town i…
  - notes: guards: type134x7, type134x8, type134x9, type134x10, type134x9, type134x8, type134x7 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `faerie_dragons:map:0:53:67`
  - **map_event:0:53:67** · unguarded map · visit @ `0:53:67` · resources: —
  - message: The leprechaun appears before you shaking his head and laughing to himself. Expecting the…
  - notes: non-resource: morale, luck | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; unsupported_reward_luck; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `faerie_dragons:map:0:6:51`
  - **map_event:0:6:51** · unguarded map · visit @ `0:6:51` · resources: —
  - message: HEY! WHAT ARE YOU DOING? THIS ISN'T THE RIGHT ONE.
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `faerie_dragons:map:0:85:10`
  - **map_event:0:85:10** · unguarded map · visit @ `0:85:10` · resources: —
  - message: As you approach the garrison you notice there is no activity whatsoever. Standing in the …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `faerie_dragons:map:0:88:7`
  - **map_event:0:88:7** · guarded map · visit @ `0:88:7` · resources: —
  - message: As you step through the garrison you see a faint shimmer just over the small hill that li…
  - notes: guards: type134x4, type134x4, type134x4 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `faerie_dragons:map:0:8:51`
  - **map_event:0:8:51** · unguarded map · visit @ `0:8:51` · resources: —
  - message: HA,HA,HA..This isn't the right one either!
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `faerie_dragons:map:0:98:58`
  - **map_event:0:98:58** · unguarded map · visit @ `0:98:58` · resources: —
  - message: Just shortly after you leave the castle you see a man lying in the ground, trying his har…
  - notes: non-resource: experience | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_experience; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `faerie_dragons:map:0:98:73`
  - **map_event:0:98:73** · unguarded map · visit @ `0:98:73` · resources: —
  - message: Wanting to get as much space between you and the Faerie Dragons you hurry on down the pat…
  - notes: non-resource: artifacts | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Azure Dragons (`azure_dragons`)

Source: `slayer.h3c` block 3 · H3M v21 · 9 events · sha256 `1d40c3968a99…` · LOD `H3ab_bmp.lod`

- [ ] `azure_dragons:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: "It is now time," you tell yourself as you prepare for the long journey. You have been wa…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `azure_dragons:global:1`
  - **No Magic** · briefing · day 3 · resources: —
  - message: As you walk around you notice that the towns around the base of the mountains are very pr…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `azure_dragons:map:0:23:71`
  - **map_event:0:23:71** · unguarded map · visit @ `0:23:71` · resources: —
  - message: Immediately after the battle you sit down for a rest. "This is gonna be harder than I tho…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `azure_dragons:map:0:26:11`
  - **map_event:0:26:11** · unguarded map · visit @ `0:26:11` · resources: —
  - message: After several days up the mountain your army is getting restless. There have been many ha…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `azure_dragons:map:0:38:0`
  - **map_event:0:38:0** · guarded map · visit @ `0:38:0` · resources: —
  - message: As you pass by the medusa stones you become aware of some medusas that have been sleeping…
  - notes: guards: type76x30, type76x40, type76x50, type77x115, type76x50, type76x40, type76x30 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `azure_dragons:map:0:41:33`
  - **map_event:0:41:33** · unguarded map · visit @ `0:41:33` · resources: —
  - message: You and your army have made it this far. Morale has not been good, but your army has a ne…
  - notes: non-resource: morale, luck | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; unsupported_reward_luck; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `azure_dragons:map:0:84:81`
  - **map_event:0:84:81** · unguarded map · visit @ `0:84:81` · resources: —
  - message: You close your eyes and say a prayer to your god, realizing these might be your last step…
  - notes: non-resource: morale, luck | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; unsupported_reward_luck; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `azure_dragons:map:0:87:32`
  - **map_event:0:87:32** · unguarded map · visit @ `0:87:32` · resources: —
  - message: Your army has broken up the scales and split them between themselves. They now wear the s…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `azure_dragons:map:0:89:2`
  - **map_event:0:89:2** · unguarded map · visit @ `0:89:2` · resources: —
  - message: The journey has been a long one. And now it is almost over. The only thing standing betwe…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Crystal Dragons (`crystal_dragons`)

Source: `slayer.h3c` block 4 · H3M v21 · 8 events · sha256 `4fb1cfb841c3…` · LOD `H3ab_bmp.lod`

- [ ] `crystal_dragons:global:1`
  - **Intro** · briefing · day 1 · resources: —
  - message: Your mother has been training Dragon Slayers for as long as she can remember. It is now t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `crystal_dragons:global:0`
  - **Lost** · briefing · day 8 · resources: —
  - message: As you are sitting down by the morning fire you remember the words of your mother, "If yo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `crystal_dragons:global:2`
  - **Diplomat's Ring** · briefing · day 12 · resources: —
  - message: Something came to you last night. You couldn't sleep and so you decided to take a little …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `crystal_dragons:map:0:25:5`
  - **map_event:0:25:5** · unguarded map · visit @ `0:25:5` · resources: —
  - message: Lying on the ground are small cracked shards of red crystal. Recognizing the shards you f…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `crystal_dragons:map:0:57:11`
  - **map_event:0:57:11** · unguarded map · visit @ `0:57:11` · resources: —
  - message: As you approach the clearing you notice there are several ways to go. Not knowing which w…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `crystal_dragons:map:0:59:61`
  - **map_event:0:59:61** · unguarded map · visit @ `0:59:61` · resources: —
  - message: Straight ahead you see the crystal dragons. Mother will be pleased, you think to yourself…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `crystal_dragons:map:0:65:57`
  - **map_event:0:65:57** · unguarded map · visit @ `0:65:57` · resources: +4294967196 wood, +4294967196 mercury, +4294967196 ore, +4294967196 sulfur, +4294967196 crystal, +4294967196 gems, +4294932296 gold
  - message: On your way to the Black Market you stumble across a camp. As you approach, you notice th…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `crystal_dragons:map:0:6:15`
  - **map_event:0:6:15** · unguarded map · visit @ `0:6:15` · resources: —
  - message: Lying on the ground are small cracked shards of red crystal. Recognizing the shards you f…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

## Festival of Life (`ab` / `festival.h3c`)

### For the Throne (`for_the_throne`)

Source: `festival.h3c` block 1 · H3M v21 · 7 events · sha256 `022fc675e0bf…` · LOD `H3ab_bmp.lod`

- [ ] `for_the_throne:global:0`
  - **Day 1 event.** · briefing · day 1 · resources: —
  - message: All your opponents except Duke Boragus lie at your feet. The final test in the Festival o…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `for_the_throne:global:1`
  - **Day 1 cont** · briefing · day 1 · resources: —
  - message: You only have 3 months to defeat the Duke or he wins by default (He is the leader of Krew…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `for_the_throne:global:2`
  - **Duke sends a message.** · briefing · day 7 · resources: —
  - message: Duke Boragus sends a message "May the mightier warrior win, young one. I will try not to …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `for_the_throne:global:3`
  - **Second message.** · briefing · day 14 · resources: —
  - message: Duke Boragus sends another message "Cowardice is not so bad in one such as you, suicide i…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `for_the_throne:global:4`
  - **Rebuttal.** · briefing · day 15 · resources: —
  - message: You send back a rather scalding message to Duke Boragus telling him what he can do with h…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `for_the_throne:global:5`
  - **no messages.** · briefing · day 25 · resources: —
  - message: No more messages seem forthcoming, good. Now you can concentrate on taking the fool down.
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `for_the_throne:map:0:63:10`
  - **map_event:0:63:10** · unguarded map · visit @ `0:63:10` · resources: —
  - message: This is a special bonus for the King of Krewlod.
  - notes: non-resource: primarySkill | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_primarySkill; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Clan War (`clan_war`)

Source: `festival.h3c` block 2 · H3M v21 · 4 events · sha256 `d2af9bf02559…` · LOD `H3ab_bmp.lod`

- [ ] `clan_war:global:0`
  - **Day one event.** · briefing · day 1 · resources: —
  - message: The third test begins. The three opponents arrayed against you and each other are battle …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clan_war:global:1`
  - **House Telez message** · briefing · day 3 · resources: —
  - message: A message arrives from House Telez: "Give up now, before we step on you like the pile of …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clan_war:global:2`
  - **House Degab taunt** · briefing · day 5 · resources: —
  - message: House Degab sends you a message: "Surrender to us now and we will give you a quick and pa…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clan_war:global:3`
  - **House Vilmit message** · briefing · day 7 · resources: —
  - message: House Vilmit sends a message: "<Ugh>..we crush you like bug you are..<Ugh>"
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Taming of the wild (`taming_of_the_wild`)

Source: `festival.h3c` block 3 · H3M v21 · 3 events · sha256 `28d4510d7ede…` · LOD `H3ab_bmp.lod`

- [ ] `taming_of_the_wild:global:0`
  - **Lieutenants** · briefing · day 1 · resources: —
  - message: To prove your leadership three lieutenants are given for your command. Use them wisely fo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `taming_of_the_wild:global:1`
  - **Scout report1.** · briefing · day 3 · resources: —
  - message: Scouts report there are many areas that have one type of creature: from Griffins to Wolf-…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `taming_of_the_wild:global:2`
  - **Scout report 2.** · briefing · day 7 · resources: —
  - message: Scouts report the three lieutenants seem to be trapped in their area by a border guard wh…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Razor Claw (`razor_claw`)

Source: `festival.h3c` block 4 · H3M v21 · 12 events · sha256 `1046523384bf…` · LOD `H3ab_bmp.lod`

- [ ] `razor_claw:global:1`
  - **Day 1 event.** · briefing · day 1 · resources: —
  - message: The first test begins. Razor Claw has been terrorizing this territory for generations; hi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `razor_claw:global:0`
  - **Scout report 1.** · briefing · day 8 · resources: —
  - message: Advanced scouts report that they found three ways past the mountains, one guarded by Cycl…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `razor_claw:global:2`
  - **Razor-Claws roar.** · briefing · day 14, every 14d · resources: —
  - message: The vicious roar of Razor Claw tears through the countryside like flesh being torn from b…
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `razor_claw:map:0:20:5`
  - **map_event:0:20:5** · unguarded map · visit @ `0:20:5` · resources: —
  - message: There seems to be a family of Ogre Mages here guarding three different artifacts. They da…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `razor_claw:map:0:30:42`
  - **map_event:0:30:42** · unguarded map · visit @ `0:30:42` · resources: —
  - message: A large group of friendly Hobgoblins suddenly boil out of the mountains and join you.
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `razor_claw:map:0:33:6`
  - **map_event:0:33:6** · guarded map · visit @ `0:33:6` · resources: —
  - message: Ambush!
  - notes: guards: type85x60, type87x50, type90x30 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `razor_claw:map:0:43:20`
  - **map_event:0:43:20** · guarded map · visit @ `0:43:20` · resources: —
  - message: Ambush!
  - notes: guards: type85x60, type87x50, type90x30 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `razor_claw:map:0:44:33`
  - **map_event:0:44:33** · unguarded map · visit @ `0:44:33` · resources: —
  - message: A large group of friendly Wolf Raiders suddenly appear out of the trees.
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `razor_claw:map:0:4:5`
  - **map_event:0:4:5** · unguarded map · visit @ `0:4:5` · resources: —
  - message: Scouts report a stronghold not far to the south (just follow the road), which would make …
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `razor_claw:map:0:57:3`
  - **map_event:0:57:3** · unguarded map · visit @ `0:57:3` · resources: —
  - message: Black dragons swoop down and ask if they can join in your crusade to fight their long-tim…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `razor_claw:map:0:68:3`
  - **map_event:0:68:3** · unguarded map · visit @ `0:68:3` · resources: —
  - message: The stench of Razor Claw (worse then your average Behemoth stench) wafts up from the dept…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `razor_claw:map:1:64:4`
  - **map_event:1:64:4** · guarded map · visit @ `1:64:4` · resources: —
  - message: The angry spirits of the Ancient Behemoth's past victims rise up and attack you.
  - notes: guards: type61x60, type60x70 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)

## Playing with Fire (`ab` / `fire.h3c`)

### Farming Towns (`farming_towns`)

Source: `fire.h3c` block 1 · H3M v21 · 26 events · sha256 `f3caaa1a3c2b…` · LOD `H3ab_bmp.lod`

- [ ] `farming_towns:global:0`
  - **Introduction** · briefing · day 1 · resources: —
  - message: You enter into this region, not too far from the Tatalian border, glad to be almost home.…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:1`
  - **Please help us!** · briefing · day 2 · resources: —
  - message: The bushes rustle and you prepare for attack. Even in Erathia there are beasts to be wary…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:2`
  - **Undead** · briefing · day 2 · resources: —
  - message: Someone is slaughtering the peasantry to make an undead army.
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:14`
  - **Warning of War** · briefing · day 3 · resources: —
  - message: Now it is time to speak to the Tatalian leaders for there is a new menace that plagues Er…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:3`
  - **Messengers** · briefing · day 4 · resources: —
  - message: Quickly, messengers are sent out to the Tatalian leaders and to an Erathian lord to the e…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:10`
  - **Advisor** · briefing · day 5 · resources: —
  - message: Your most trusted friend and advisor, Baltron, enters your tent. "Adrienne, there is no w…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:4`
  - **Second Message** · briefing · day 5 · resources: —
  - message: Before you send off the message to the Erathian government you give it one last look thro…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:5`
  - **Messenger returns** · briefing · day 15 · resources: —
  - message: Of the group you sent to Tatalia only one returns. He confirms your worst fears. The infe…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:6`
  - **Reply** · briefing · day 20 · resources: —
  - message: A messenger returns from the knight's castle. He does not carry the official word, but th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:7`
  - **Official Response** · briefing · day 25 · resources: —
  - message: Finally, after several days the messengers return with an official response. "We regretfu…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:11`
  - **Baltron's opinion** · briefing · day 26 · resources: —
  - message: "My dearest young Witch," you know this is going to be an 'I told you' session. "I did wa…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:8`
  - **Burning of the Dead** · briefing · day 30 · resources: —
  - message: Last night you came across lots of piles of rotting flesh. Even though they did not move …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:12`
  - **Troubles** · briefing · day 35 · resources: —
  - message: Baltron rushes into your tent, waking you from a near dead sleep. "Adrienne! There is tro…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:13`
  - **Flowers** · briefing · day 40 · resources: —
  - message: It has been a long and tiring day. Traveling through familiar territory that has been tur…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:9`
  - **Death Knight** · briefing · day 45 · resources: —
  - message: Sighting of the leader occurred some days ago. It is a Death Knight on a great Black Char…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:16`
  - **Death Knight** · briefing · day 50 · resources: —
  - message: This strange Death Knight seems more powerful than the others. Not knowing who he is, and…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:17`
  - **Tatalia** · briefing · day 60 · resources: —
  - message: An answer has come back from Tatalia. They do not know who this Death Knight is. They are…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:global:18`
  - **Money** · briefing · day 65 · resources: -50 wood, -25 mercury, -50 ore, -25 sulfur, -25 crystal, -25 gems, -10000 gold
  - message: A messenger comes in from Erathia. They need money to run a war. Busy with their own prob…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `farming_towns:global:15`
  - **Who is he?** · briefing · day 75 · resources: —
  - message: Scouts have been tracking the Death Knight, and have finally returned with word of who he…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `farming_towns:map:0:14:6`
  - **map_event:0:14:6** · guarded map · visit @ `0:14:6` · resources: —
  - message: Ahead of you lies unguarded treasure. Rushing forward to claim the much-needed supplies t…
  - notes: guards: type47x7, type47x7, type47x7, type47x10, type47x7, type47x7, type47x7 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `farming_towns:map:0:17:71`
  - **map_event:0:17:71** · unguarded map · visit @ `0:17:71` · resources: —
  - message: Ahead is a roaring campfire. There, bandits drink and toy with their loot. The rustle to …
  - notes: non-resource: luck | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_luck; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `farming_towns:map:0:41:41`
  - **map_event:0:41:41** · unguarded map · visit @ `0:41:41` · resources: —
  - message: Stumbling onto your path is a young girl. Her dress is torn and tattered, and she is half…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `farming_towns:map:0:47:24`
  - **map_event:0:47:24** · unguarded map · visit @ `0:47:24` · resources: —
  - message: The stench of death fills your lungs and you can taste the decay in the air. The undead h…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `farming_towns:map:0:55:29`
  - **map_event:0:55:29** · unguarded map · visit @ `0:55:29` · resources: —
  - message: On the rock face written in blood is the message, "Unless you are type A+, B- or AB+ we a…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `farming_towns:map:0:71:4`
  - **map_event:0:71:4** · unguarded map · visit @ `0:71:4` · resources: —
  - message: Passing through the small valley the troops come across the scarred land where a great ba…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `farming_towns:map:0:71:8`
  - **map_event:0:71:8** · unguarded map · visit @ `0:71:8` · resources: —
  - message: Approaching the prison you see a group of Erathians clamoring to be freed. Calling out to…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### March of the Undead (`march_of_the_undead`)

Source: `fire.h3c` block 2 · H3M v21 · 49 events · sha256 `d2cfcf2f00c3…` · LOD `H3ab_bmp.lod`

- [ ] `march_of_the_undead:global:0`
  - **History** · briefing · day 1 · resources: —
  - message: Freeing the Erathian-Tatalian border from the grasp of undead you push further into Tatal…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:1`
  - **Purpose** · briefing · day 2 · resources: —
  - message: You begin to look around, searching for a place to set up home base. Reports tell of such…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:2`
  - **Reports** · briefing · day 5 · resources: —
  - message: Scouts are beginning to return and the news is not good. The first to return did not get …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:18`
  - **Scholars** · briefing · day 7 · resources: —
  - message: It has been rumored that Scholars have knowledge of great spells, but are heavily guarded…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:3`
  - **Scouts** · briefing · day 10 · resources: —
  - message: The last few scouts return with more news. None of it is good. Fleeing Tatalians went dee…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:4`
  - **Intelligence** · briefing · day 15 · resources: —
  - message: It may be that the troops of undead are not all that smart, but it seems one of the Death…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:5`
  - **Rumors** · briefing · day 20 · resources: —
  - message: Rumors of Basilisks trapped on one of the Great Lakes have reached your ears. Seems they …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:7`
  - **Lord Haart** · briefing · day 25 · resources: —
  - message: A scout returns, Lord Haart has definitely moved out of the area, leaving only two of his…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:6`
  - **Trouble** · briefing · day 30 · resources: —
  - message: "My lady, there is trouble. An outside Witch has come to the area in order to aid us. She…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:8`
  - **Information** · briefing · day 35 · resources: —
  - message: In order to see how things are going you send a scout to the Krewlod border. There they c…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:9`
  - **Great Treasure** · briefing · day 40 · resources: —
  - message: Rumors of great treasure far to the northeast have trickled into camp. Much needed suppli…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:10`
  - **Treasure** · briefing · day 50 · resources: —
  - message: The rumors have been confirmed. There is a great treasure far to the north. Of course you…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:11`
  - **Below** · briefing · day 60 · resources: —
  - message: Below the surface the stacks of undead grow as young creatures leave their homes each wee…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:12`
  - **Kilgor** · briefing · day 75 · resources: —
  - message: It has been confirmed. Kilgor is the new King of Krewlod, having successfully passed the …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:13`
  - **Birthday** · briefing · day 90 · resources: —
  - message: Today is a depressing day for you. It is your Birthday. Unlike so many others you cannot …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:14`
  - **Birthday Present** · briefing · day 95 · resources: —
  - message: "Excuse me" One of your lieutenants approaches cautiously, knowing your bad mood the past…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:15`
  - **It worked!** · briefing · day 105 · resources: —
  - message: With the delivering of the message the Leaders had no choice but to investigate such a cl…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:16`
  - **Leaders** · briefing · day 115 · resources: —
  - message: The leaders have responded: Tiva, We have assessed the immediate situation. It is definit…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:global:17`
  - **True to their word** · briefing · day 130 · resources: —
  - message: True to their word the Leaders have sent help. Some troops are now assembling in Scarlum,…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `march_of_the_undead:map:0:104:65`
  - **map_event:0:104:65** · unguarded map · visit @ `0:104:65` · resources: —
  - message: Here you see where some of the citizens of Tatalia went below to escape the undead who ha…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:12:90`
  - **map_event:0:12:90** · unguarded map · visit @ `0:12:90` · resources: —
  - message: A child's broken doll lies in the path. Stopping to pick it up, one of the men stares bla…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:26:25`
  - **map_event:0:26:25** · guarded map · visit @ `0:26:25` · resources: +20 wood, +20 ore, +5000 gold
  - message: As your men stumble along, exhausted from the lengthy battles, you rejoice as you about t…
  - notes: guards: type64x10, type62x10, type60x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `march_of_the_undead:map:0:31:72`
  - **map_event:0:31:72** · unguarded map · visit @ `0:31:72` · resources: —
  - message: Upon approaching the half destroyed town of Basdar, mutterings can be heard within the tr…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:37:105`
  - **map_event:0:37:105** · unguarded map · visit @ `0:37:105` · resources: —
  - message: These battlements usually hold the Tatalian military. Now, they hold the stench of death …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:39:101`
  - **map_event:0:39:101** · unguarded map · visit @ `0:39:101` · resources: —
  - message: A peasant comes forward and says, "Beware the one way monoliths. The Necromancers use the…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:39:25`
  - **map_event:0:39:25** · unguarded map · visit @ `0:39:25` · resources: —
  - message: You see some Tatalians clutching onto driftwood. Hauling them aboard they say, "Thank you…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:41:36`
  - **map_event:0:41:36** · unguarded map · visit @ `0:41:36` · resources: +40 wood, +20 mercury, +40 ore, +20 sulfur, +20 crystal, +20 gems, +10000 gold
  - message: Huddled in the underbrush are hundreds of frightened Gnolls. Not until the horrid creatur…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:41:47`
  - **map_event:0:41:47** · unguarded map · visit @ `0:41:47` · resources: —
  - message: This small fishing village has been destroyed. Only a few of the dwellings still exist an…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:44:0`
  - **map_event:0:44:0** · unguarded map · visit @ `0:44:0` · resources: —
  - message: This area is quiet and peaceful, the undead invasion not quite so prevalent. Even so, ner…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:58:106`
  - **map_event:0:58:106** · unguarded map · visit @ `0:58:106` · resources: —
  - message: With relief your troops push forward to Scarlum. This town has a reputation for being tou…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:5:53`
  - **map_event:0:5:53** · unguarded map · visit @ `0:5:53` · resources: —
  - message: The teacher sees you and says, "Ahh thank you for allowing me to return to my school. Com…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:6:67`
  - **map_event:0:6:67** · unguarded map · visit @ `0:6:67` · resources: —
  - message: The winds are blowing southerly today, bringing with them the stench of decaying bodies a…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:6:7`
  - **map_event:0:6:7** · unguarded map · visit @ `0:6:7` · resources: —
  - message: In order to utilize the Tatalian resources you must first seek the blessing of an elder. …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:71:23`
  - **map_event:0:71:23** · unguarded map · visit @ `0:71:23` · resources: —
  - message: Here is where many of the Tatalians fled below ground. Now you must free them because the…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:74:99`
  - **map_event:0:74:99** · unguarded map · visit @ `0:74:99` · resources: —
  - message: Playing quietly by the fountain are some ragged looking children. Their gay laughter warm…
  - notes: non-resource: artifacts | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:80:77`
  - **map_event:0:80:77** · unguarded map · visit @ `0:80:77` · resources: —
  - message: Peeking at the serene waters of a Great Lake you wish for days of ease and peace. Turning…
  - notes: non-resource: luck, artifacts | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_luck; unsupported_reward_artifacts; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:86:28`
  - **map_event:0:86:28** · unguarded map · visit @ `0:86:28` · resources: —
  - message: This used to be the entrance to one of the largest cities in the area. It boasted all of …
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:8:28`
  - **map_event:0:8:28** · unguarded map · visit @ `0:8:28` · resources: —
  - message: Here is where many of the Tatalians fled below ground. Now you must free them because the…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:93:105`
  - **map_event:0:93:105** · unguarded map · visit @ `0:93:105` · resources: —
  - message: Approaching the school you are glad it's doors never had to close. Here you can sharpen a…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:97:46`
  - **map_event:0:97:46** · unguarded map · visit @ `0:97:46` · resources: —
  - message: In this ravine the stench of undead is gone. All traces of unnatural horrors are wiped aw…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:0:9:101`
  - **map_event:0:9:101** · unguarded map · visit @ `0:9:101` · resources: —
  - message: Once, not too long in the past this was a pretty little town where a traveler could rest …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:1:15:88`
  - **map_event:1:15:88** · unguarded map · visit @ `1:15:88` · resources: —
  - message: It seems the undead are indiscriminate as to who they slaughter to fill their ranks. The …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:1:25:81`
  - **map_event:1:25:81** · unguarded map · visit @ `1:25:81` · resources: —
  - message: Down here the Hydras had fled, temporarily escaping the hordes of undead. Now the most po…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:map:1:29:67`
  - **map_event:1:29:67** · unguarded map · visit @ `1:29:67` · resources: —
  - message: Following the river you come to an area where it has worn down the bedrock and created an…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `march_of_the_undead:town:0:28:7:event:0`
  - **Creatures!** · town timed · day 14, every 7d @ `town:0:28:7:event:0` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `march_of_the_undead:town:0:98:81:event:0`
  - **Creatures!** · town timed · day 14, every 7d @ `town:0:98:81:event:0` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `march_of_the_undead:town:0:63:103:event:0`
  - **Troops!** · town timed · day 130 @ `town:0:63:103:event:0` (Scarlum) · resources: —
  - message: Ready for action Sir!
  - notes: town=Scarlum | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `march_of_the_undead:town:0:63:103:event:1`
  - **More Troops** · town timed · day 140 @ `town:0:63:103:event:1` (Scarlum) · resources: —
  - message: More troops have begun to arrive from the border, at first a trickle and now some more. W…
  - notes: town=Scarlum | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `march_of_the_undead:town:0:63:103:event:2`
  - **Troops** · town timed · day 150 @ `town:0:63:103:event:2` (Scarlum) · resources: —
  - message: This will be the last of the reinforcements.
  - notes: town=Scarlum | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Burning of Tatalia (`burning_of_tatalia`)

Source: `fire.h3c` block 3 · H3M v21 · 44 events · sha256 `0b100fdf6377…` · LOD `H3ab_bmp.lod`

- [ ] `burning_of_tatalia:global:0`
  - **Burning** · briefing · day 1 · resources: —
  - message: For days you have traveled, following the thick plume of smoke. Finally, after days of fi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `burning_of_tatalia:global:1`
  - **Followers** · briefing · day 8 · resources: —
  - message: Lord Haart's followers split up and went three ways. They too burned paths through the on…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `burning_of_tatalia:global:2`
  - **Help!** · briefing · day 12 · resources: —
  - message: A messenger returns with news of a few towns that have been able to hold out. However, th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `burning_of_tatalia:global:4`
  - **Thanel Falls** · briefing · day 20 · resources: -10 wood, -3 mercury, -5 ore, -3 sulfur, -3 crystal, -3 gems, -5000 gold
  - message: A message arrives from the north, from the citizens of Thanel Falls. They are holding out…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `burning_of_tatalia:global:3`
  - **Cry for help** · briefing · day 30 · resources: —
  - message: Hacking your way through the underbrush a small creature skitters just out of view. Drawi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `burning_of_tatalia:global:5`
  - **Message** · briefing · day 35 · resources: —
  - message: You send messengers out to the towns still out of your reach. The messages read, "Please …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `burning_of_tatalia:global:6`
  - **A message** · briefing · day 45 · resources: —
  - message: A messenger, out of breath and exhausted runs into camp, shouting for Adrienne. Taking th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `burning_of_tatalia:global:7`
  - **Cash** · briefing · day 55 · resources: +30 mercury, +30 sulfur, +30 crystal, +30 gems, +10000 gold
  - message: Four riders, moving swiftly through the swamps arrive at camp. Each horse is trailing two…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `burning_of_tatalia:global:8`
  - **Slow carts** · briefing · day 60 · resources: +60 wood, +60 ore
  - message: Lumbering into camp are two covered carts. Each are drawn by four horses, lathered with s…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `burning_of_tatalia:global:9`
  - **Troops!** · briefing · day 70 · resources: —
  - message: Finally! Troops are arriving at your main camps. Now available, you can recruit those you…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `burning_of_tatalia:map:0:107:8`
  - **map_event:0:107:8** · unguarded map · visit @ `0:107:8` · resources: +2 wood, +1 ore, +1 crystal, +200 gold
  - message: Rooting about in the underbrush while others take a quick break from the day's trek, some…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:111:38`
  - **map_event:0:111:38** · unguarded map · visit @ `0:111:38` · resources: —
  - message: The infestation has spread widely here. The cries of dying Tatalians can be heard faintly…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:113:137`
  - **map_event:0:113:137** · unguarded map · visit @ `0:113:137` · resources: —
  - message: Unable to completely break through the fierce Tatalian defenses Lord Haart has penned the…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:114:38`
  - **map_event:0:114:38** · unguarded map · visit @ `0:114:38` · resources: —
  - message: As your troops move around the bend you can see a garrison not too far off. The stench of…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:115:39`
  - **map_event:0:115:39** · guarded map · visit @ `0:115:39` · resources: +20 wood, +10 mercury, +20 ore, +10 sulfur, +10 crystal, +10 gems, +5000 gold
  - message: From out behind trees the rotting corpses crawl. The men freeze in fear as the rotting co…
  - notes: guards: type56x160, type58x80, type60x40, type62x20 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `burning_of_tatalia:map:0:118:92`
  - **map_event:0:118:92** · unguarded map · visit @ `0:118:92` · resources: —
  - message: An old man is sitting on the ground, whittling a small toy from wood. He looks up at you …
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:122:11`
  - **map_event:0:122:11** · unguarded map · visit @ `0:122:11` · resources: —
  - message: Here, among the floating wreckage you see the glint of something metallic just below the …
  - notes: non-resource: artifacts | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:122:57`
  - **map_event:0:122:57** · unguarded map · visit @ `0:122:57` · resources: —
  - message: Here is where the undead beasts must have gone to the underworld, originally. The path to…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:124:70`
  - **map_event:0:124:70** · guarded map · visit @ `0:124:70` · resources: —
  - message: Up ahead are loose resources for gathering. Since you had defeated the undead in the Garr…
  - notes: guards: type115x30, type115x30, type115x30, type115x30, type115x30, type115x30, type115x30 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `burning_of_tatalia:map:0:129:54`
  - **map_event:0:129:54** · guarded map · visit @ `0:129:54` · resources: —
  - message: Stepping into the clearing you are suddenly surrounded by at least a hundred of the horro…
  - notes: guards: type59x59, type59x37, type59x49, type63x34, type59x43, type59x37, type59x38 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `burning_of_tatalia:map:0:129:57`
  - **map_event:0:129:57** · unguarded map · visit @ `0:129:57` · resources: —
  - message: This little clearing is untouched by the undead, clean from their bony grasp. How they mi…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:130:95`
  - **map_event:0:130:95** · unguarded map · visit @ `0:130:95` · resources: —
  - message: What used to be a thriving community is now a smoking pile of ruin. Some people can be se…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:131:22`
  - **map_event:0:131:22** · unguarded map · visit @ `0:131:22` · resources: +4294967294 wood, +4294967295 mercury, +4294967294 ore, +4294967295 sulfur, +4294967295 crystal, +4294967295 gems, +4294966796 gold
  - message: Hiding in the underbrush is a young man. Boldly he approaches the army. Smiling and crack…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:134:80`
  - **map_event:0:134:80** · unguarded map · visit @ `0:134:80` · resources: —
  - message: Follow the trail of destruction left behind by this follower has been an all too easy tas…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:137:141`
  - **map_event:0:137:141** · unguarded map · visit @ `0:137:141` · resources: —
  - message: A recovering path of destruction was left behind by Lord Haart and his undead followers. …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:140:109`
  - **map_event:0:140:109** · unguarded map · visit @ `0:140:109` · resources: —
  - message: In the clearing ahead you can see the cave entrance leading to the lands below the surfac…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:22:51`
  - **map_event:0:22:51** · unguarded map · visit @ `0:22:51` · resources: —
  - message: This small area of Tatalia seems untouched by death and destruction. A beautiful fountain…
  - notes: non-resource: luck | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_luck; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:34:120`
  - **map_event:0:34:120** · unguarded map · visit @ `0:34:120` · resources: —
  - message: Rotting flesh and stinking corpses seem to have become a part of every day life in the fi…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:36:81`
  - **map_event:0:36:81** · guarded map · visit @ `0:36:81` · resources: —
  - message: The air whips suddenly, spinning into several small tornadoes. Fearing an early monsoon y…
  - notes: guards: type112x10, type112x10, type112x10, type127x10, type112x10, type112x10, type112x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `burning_of_tatalia:map:0:45:110`
  - **map_event:0:45:110** · unguarded map · visit @ `0:45:110` · resources: —
  - message: The Tatalians within are fighting to keep Lord Haart and his followers from their lands, …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:45:84`
  - **map_event:0:45:84** · unguarded map · visit @ `0:45:84` · resources: —
  - message: Passing into the Greater Basilisks territory you see dozens of Basilisks come at you. The…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:55:121`
  - **map_event:0:55:121** · unguarded map · visit @ `0:55:121` · resources: —
  - message: You can see the battlements are caked with the dried blood of your people. Bits and piece…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:map:0:99:73`
  - **map_event:0:99:73** · guarded map · visit @ `0:99:73` · resources: —
  - message: From the thin air, and the ground below, rise the ghostly remains of Dragons long since d…
  - notes: non-resource: morale | guards: type68x2, type68x2, type68x2, type69x1, type69x1, type68x2, type68x2 | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `burning_of_tatalia:map:0:9:22`
  - **map_event:0:9:22** · unguarded map · visit @ `0:9:22` · resources: —
  - message: Exploring this small island has been a test of character. Amidst the lush swamp are horro…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `burning_of_tatalia:town:0:142:57:event:0`
  - **Troops** · town timed · day 1, every 7d @ `town:0:142:57:event:0` (town) · resources: —
  - message: This will give the computer player troops.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `burning_of_tatalia:town:0:19:128:event:0`
  - **Troops** · town timed · day 1, every 7d @ `town:0:19:128:event:0` (town) · resources: —
  - message: This will give the computer player troops.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `burning_of_tatalia:town:0:52:15:event:0`
  - **Troops** · town timed · day 1, every 7d @ `town:0:52:15:event:0` (town) · resources: —
  - message: This will give the computer player troops.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `burning_of_tatalia:town:0:53:136:event:0`
  - **Troops** · town timed · day 1, every 7d @ `town:0:53:136:event:0` (town) · resources: —
  - message: This will give the computer player troops.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `burning_of_tatalia:town:0:56:74:event:0`
  - **Troops** · town timed · day 1 @ `town:0:56:74:event:0` (town) · resources: +5000 gold
  - message: This will give the computer player troops.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `burning_of_tatalia:town:0:70:39:event:0`
  - **Troops** · town timed · day 1 @ `town:0:70:39:event:0` (town) · resources: —
  - message: This will give the computer player troops.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `burning_of_tatalia:town:0:89:5:event:0`
  - **Troops** · town timed · day 1, every 7d @ `town:0:89:5:event:0` (town) · resources: —
  - message: This will give the computer player troops.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `burning_of_tatalia:town:0:100:136:event:0`
  - **Troops** · town timed · day 70 @ `town:0:100:136:event:0` (Rakops) · resources: —
  - message: There are troops available in Rakops.
  - notes: town=Rakops | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `burning_of_tatalia:town:0:129:94:event:0`
  - **Troops** · town timed · day 70 @ `town:0:129:94:event:0` (Aseranton) · resources: —
  - message: There are troops available in Aseranton.
  - notes: town=Aseranton | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `burning_of_tatalia:town:0:137:120:event:0`
  - **Troops** · town timed · day 70 @ `town:0:137:120:event:0` (Sehithwa) · resources: —
  - message: The troops are ready for hire in Sehithwa.
  - notes: town=Sehithwa | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

## Foolhardy Waywardness (`ab` / `fool.h3c`)

### Lost at Sea (`lost_at_sea`)

Source: `fool.h3c` block 1 · H3M v21 · 27 events · sha256 `2e0b59cb735c…` · LOD `H3ab_bmp.lod`

- [ ] `lost_at_sea:global:0`
  - **Intro 1** · briefing · day 1 · resources: —
  - message: While on a three-hour sight seeing tour, the mighty Sir Christian's ship was blown off co…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `lost_at_sea:global:1`
  - **Day 2** · briefing · day 2 · resources: —
  - message: The leader of the natives meets with you. The jolly old fellow seems very excited and say…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `lost_at_sea:global:2`
  - **Day 7** · briefing · day 7 · resources: —
  - message: Terrible news has reached you. A messenger from the natives delivers you the news. "Sire,…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `lost_at_sea:global:3`
  - **Day 7b** · briefing · day 7, every 14d · resources: -28 wood
  - message: There is a severe toothpick shortage. Trust no one. We'll be back for more when you least…
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `lost_at_sea:map:0:16:56`
  - **map_event:0:16:56** · guarded map · visit @ `0:16:56` · resources: —
  - message: Another fork in the road! Now very testy, you are getting tired of all the forks in the r…
  - notes: guards: empty | removeAfterVisit=true | blockers: audience_encoder_unproven; hasGuards_true_but_empty_guardStacks; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:21:11`
  - **map_event:0:21:11** · unguarded map · visit @ `0:21:11` · resources: —
  - message: You let out a big sigh, bite your bottom lip, and mindlessly gaze up both paths that lay …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:23:14`
  - **map_event:0:23:14** · unguarded map · visit @ `0:23:14` · resources: —
  - message: For a long time you have followed the straight and narrow path. But now you have no idea …
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:23:17`
  - **map_event:0:23:17** · unguarded map · visit @ `0:23:17` · resources: —
  - message: You come to yet another parting in the road. Low and behold another fork for you to toss …
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:23:20`
  - **map_event:0:23:20** · unguarded map · visit @ `0:23:20` · resources: —
  - message: You begin complaining to your troops. "How are we supposed to follow the cobblestone road…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:23:59`
  - **map_event:0:23:59** · guarded map · visit @ `0:23:59` · resources: —
  - message: Feeling bad about being so short tempered to the poor merchant your conscience gets the b…
  - notes: guards: type79x1 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `lost_at_sea:map:0:24:30`
  - **map_event:0:24:30** · unguarded map · visit @ `0:24:30` · resources: —
  - message: You took the road less traveled, and that has made all the difference.
  - notes: non-resource: artifacts | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:24:59`
  - **map_event:0:24:59** · unguarded map · visit @ `0:24:59` · resources: —
  - message: You come across a lowly merchant who looks as if he has not seen any business all day. Th…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:27:33`
  - **map_event:0:27:33** · unguarded map · visit @ `0:27:33` · resources: —
  - message: You come upon two roads that fork in a yellow wood. Travelers have worn them really about…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:30:55`
  - **map_event:0:30:55** · unguarded map · visit @ `0:30:55` · resources: —
  - message: Gasp! A fork in the road! What will you do? After long hours of heated debate and consult…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:32:55`
  - **map_event:0:32:55** · unguarded map · visit @ `0:32:55` · resources: —
  - message: You are confronted by a bunch of short odorous goblins. They all line up in front of you …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:33:56`
  - **map_event:0:33:56** · unguarded map · visit @ `0:33:56` · resources: —
  - message: Several hobgoblins surround you. Suddenly there is an outburst of song. " We represent th…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:39:30`
  - **map_event:0:39:30** · unguarded map · visit @ `0:39:30` · resources: —
  - message: A drunken fool staggers his way out of the tavern and with slurred words begins hollering…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:44:36`
  - **map_event:0:44:36** · unguarded map · visit @ `0:44:36` · resources: —
  - message: At a fork in the road you stop and ask the nearest creature for directions on how to get …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:45:23`
  - **map_event:0:45:23** · unguarded map · visit @ `0:45:23` · resources: +42 wood, +21 mercury, +42 ore, +21 sulfur, +21 crystal, +21 gems, +21000 gold
  - message: While deep in the woods you stumble onto a hidden, moss-covered, wooden chest that has be…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:48:19`
  - **map_event:0:48:19** · unguarded map · visit @ `0:48:19` · resources: —
  - message: Standing at a divergence in the road was a family of tattered peasants and their decrepit…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:48:27`
  - **map_event:0:48:27** · unguarded map · visit @ `0:48:27` · resources: —
  - message: While traveling, you see a tired peasant woman carrying large, heavy looking bags. Being …
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:49:34`
  - **map_event:0:49:34** · unguarded map · visit @ `0:49:34` · resources: —
  - message: A large boulder obstructs the road. You send one of your troops ahead to see what is on t…
  - notes: non-resource: primarySkill | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_primarySkill; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:53:37`
  - **map_event:0:53:37** · guarded map · visit @ `0:53:37` · resources: +4294967281 gold
  - message: A toll guard abruptly stops you and your troops at the fork in the road. The longhaired t…
  - notes: guards: type2x4, type6x7, type2x8, type3x1, type2x3 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `lost_at_sea:map:0:54:56`
  - **map_event:0:54:56** · unguarded map · visit @ `0:54:56` · resources: —
  - message: Another fork in the road! You yawn and wonder what you are going to do with all these for…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:55:66`
  - **map_event:0:55:66** · unguarded map · visit @ `0:55:66` · resources: —
  - message: You begin to weep. Your troops begin to mock you. There you stand in front of the refuse …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:59:48`
  - **map_event:0:59:48** · unguarded map · visit @ `0:59:48` · resources: —
  - message: Two! Two forks in the road! Slightly annoyed you wonder why this fork in the road reminds…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `lost_at_sea:map:0:61:31`
  - **map_event:0:61:31** · unguarded map · visit @ `0:61:31` · resources: —
  - message: Blessed is the artless dizzy-eyed coxcomb who contrived these roads. You are becoming ver…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Here There Be Pirates (`here_there_be_pirates`)

Source: `fool.h3c` block 2 · H3M v21 · 17 events · sha256 `e378c6f473bb…` · LOD `H3ab_bmp.lod`

- [ ] `here_there_be_pirates:global:0`
  - **Intro 1** · briefing · day 1 · resources: —
  - message: It looks as if Sir Christian would be on his way home when one of his crewmembers discove…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `here_there_be_pirates:global:1`
  - **Day 8** · briefing · day 8 · resources: —
  - message: Beware of the fiery swamps in the underground. The enemy has taken over a fairly large fo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `here_there_be_pirates:global:3`
  - **Day 9** · briefing · day 9 · resources: —
  - message: Your advisor suggests that you send off some spies to the other islands to get inside inf…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `here_there_be_pirates:global:2`
  - **Union Dues** · briefing · day 28, every 28d · resources: -5 crystal, -7 gems, -1063 gold
  - message: Congratulations again on your joining the Regnan Pirates Union. It's great to have you wi…
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `here_there_be_pirates:global:4`
  - **Day 30** · briefing · day 30 · resources: —
  - message: Only half of the spies have returned back from their mission. They were beaten bloody and…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `here_there_be_pirates:global:5`
  - **Day 60** · briefing · day 60 · resources: —
  - message: While traveling you meet with a messenger. He is resting on a rock. You dismount and intr…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `here_there_be_pirates:map:0:105:3`
  - **map_event:0:105:3** · guarded map · visit @ `0:105:3` · resources: —
  - message: (no message)
  - notes: guards: type115x39 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `here_there_be_pirates:map:0:13:12`
  - **map_event:0:13:12** · unguarded map · visit @ `0:13:12` · resources: —
  - message: Just as the goblins had said, there is a guard at the town entrance and he asks to see yo…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `here_there_be_pirates:map:0:19:14`
  - **map_event:0:19:14** · unguarded map · visit @ `0:19:14` · resources: —
  - message: You meet the captain. A foul-smelling, foul-mouthed fat old ogre. In a gravely voice, he …
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `here_there_be_pirates:map:0:23:16`
  - **map_event:0:23:16** · unguarded map · visit @ `0:23:16` · resources: —
  - message: You approach the orcs that guard the stronghold town. Suddenly you are surrounded by gobl…
  - notes: non-resource: creatures | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_creatures; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `here_there_be_pirates:map:0:24:69`
  - **map_event:0:24:69** · guarded map · visit @ `0:24:69` · resources: +4 sulfur, +259 gold
  - message: A pack of hideous, drunken zombies approach you. "You best watch yourself. We're wanted m…
  - notes: guards: type59x11 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `here_there_be_pirates:map:0:26:87`
  - **map_event:0:26:87** · unguarded map · visit @ `0:26:87` · resources: —
  - message: It sure is hot out. You could fry a dozen eggs over-easy on the saddle of your horse. You…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `here_there_be_pirates:map:0:33:28`
  - **map_event:0:33:28** · unguarded map · visit @ `0:33:28` · resources: —
  - message: While relieving yourself, you find a leprechaun. Expecting to get his pot of gold, the le…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `here_there_be_pirates:map:0:35:83`
  - **map_event:0:35:83** · unguarded map · visit @ `0:35:83` · resources: +4294967245 wood, +4294967245 mercury, +4294967245 ore, +4294967245 sulfur, +4294967245 crystal, +4294967245 gems, +4294962196 gold
  - message: From out of nowhere an extremely bright flashing light consumes the surroundings of you a…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `here_there_be_pirates:map:0:88:83`
  - **map_event:0:88:83** · unguarded map · visit @ `0:88:83` · resources: —
  - message: An undead dead drunk approaches you and invites you to the bi-annual undead convention. "…
  - notes: non-resource: artifacts | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `here_there_be_pirates:map:1:94:73`
  - **map_event:1:94:73** · unguarded map · visit @ `1:94:73` · resources: —
  - message: On the way to the tavern, several combat-hardened cyclopses stop you. They began looking …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `here_there_be_pirates:town:0:15:11:event:0`
  - **Build Tavern** · town timed · day 3 @ `town:0:15:11:event:0` (town) · resources: —
  - message: The pirates have fallen off the wagon and have built a tavern in your name. (Of course.) …
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Hurry Up and Wait (`hurry_up_and_wait`)

Source: `fool.h3c` block 3 · H3M v21 · 18 events · sha256 `afdc53a2bf53…` · LOD `H3ab_bmp.lod`

- [ ] `hurry_up_and_wait:global:0`
  - **Intro 1** · briefing · day 1 · resources: —
  - message: If someone were to ask you where your loyalties lie, at this point, you would answer, "To…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `hurry_up_and_wait:global:3`
  - **Whew!** · briefing · day 7 · resources: —
  - message: This week has been pretty easy. Hopefully the Pirates will leave you alone, but your luck…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `hurry_up_and_wait:global:4`
  - **Those stupid teleporters** · briefing · day 14 · resources: +3 ore
  - message: Well it seems those stupid teleporters are making your life miserable. With several unsuc…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `hurry_up_and_wait:global:5`
  - **Loser** · briefing · day 22 · resources: —
  - message: It looks like these pirates are serious. They will stop at nothing. You spot few of the e…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `hurry_up_and_wait:global:6`
  - **You Cry** · briefing · day 30 · resources: —
  - message: Finding about the enemy is of utmost importance. You try to convince the goblins of that.…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `hurry_up_and_wait:global:7`
  - **Grandma** · briefing · day 38 · resources: -50 gold
  - message: You come across an old woman, and you greet her with "Good day Grandmother." She stops, l…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `hurry_up_and_wait:global:8`
  - **A young boy** · briefing · day 49 · resources: —
  - message: A young boy about twelve years old mysteriously joins your camp one night. He says he is …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `hurry_up_and_wait:global:1`
  - **120A You made it!** · briefing · day 120 · resources: —
  - message: Queen Catherine's ships have been spotted on the horizon. The Regnan Pirates have also sp…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `hurry_up_and_wait:global:2`
  - **120B Gilligan's Island Spoof** · briefing · day 120 · resources: —
  - message: Just sit right back and you'll hear a tale, a tale of a sci-fi trip, that started in Agou…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `hurry_up_and_wait:map:0:103:15`
  - **map_event:0:103:15** · unguarded map · visit @ `0:103:15` · resources: —
  - message: (no message)
  - notes: non-resource: experience | removeAfterVisit=false | blockers: audience_encoder_unproven; unsupported_reward_experience; non_removing_event_lifetime_unproven; persistent_host_rebinding_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `hurry_up_and_wait:map:0:13:3`
  - **map_event:0:13:3** · unguarded map · visit @ `0:13:3` · resources: —
  - message: (no message)
  - notes: non-resource: experience | removeAfterVisit=false | blockers: audience_encoder_unproven; unsupported_reward_experience; non_removing_event_lifetime_unproven; persistent_host_rebinding_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `hurry_up_and_wait:map:0:23:89`
  - **map_event:0:23:89** · unguarded map · visit @ `0:23:89` · resources: —
  - message: (no message)
  - notes: non-resource: experience | removeAfterVisit=false | blockers: audience_encoder_unproven; unsupported_reward_experience; non_removing_event_lifetime_unproven; persistent_host_rebinding_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `hurry_up_and_wait:map:0:29:14`
  - **map_event:0:29:14** · guarded map · visit @ `0:29:14` · resources: —
  - message: Thou shall not kill-ist or trade in precious life for treasure.
  - notes: guards: type12x1, type12x1, type12x1, type12x1, type12x1, type12x1, type12x2 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `hurry_up_and_wait:map:0:41:101`
  - **map_event:0:41:101** · unguarded map · visit @ `0:41:101` · resources: —
  - message: Beware the Triangle Bermuda
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `hurry_up_and_wait:map:0:44:106`
  - **map_event:0:44:106** · unguarded map · visit @ `0:44:106` · resources: —
  - message: Beware the Devils Triangle
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `hurry_up_and_wait:map:0:47:101`
  - **map_event:0:47:101** · unguarded map · visit @ `0:47:101` · resources: —
  - message: Beware Limbo of the lost.
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `hurry_up_and_wait:map:0:67:28`
  - **map_event:0:67:28** · unguarded map · visit @ `0:67:28` · resources: —
  - message: As you approach the trading post you notice an outhouse. You walk over to it and it is lo…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `hurry_up_and_wait:map:0:94:97`
  - **map_event:0:94:97** · unguarded map · visit @ `0:94:97` · resources: —
  - message: (no message)
  - notes: non-resource: experience | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_experience; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Their End of the Bargain (`their_end_of_the_bargain`)

Source: `fool.h3c` block 4 · H3M v21 · 20 events · sha256 `fd7e5b7c6f0c…` · LOD `H3ab_bmp.lod`

- [ ] `their_end_of_the_bargain:global:0`
  - **Intro 1** · briefing · day 1 · resources: —
  - message: The natives were so happy at Sir Christian's success that they completely forgot about th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `their_end_of_the_bargain:global:1`
  - **Day 4** · briefing · day 4 · resources: —
  - message: As you are traveling to your new quarters you sort out your thoughts and strategies as to…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `their_end_of_the_bargain:global:4`
  - **Day 15 send out spies** · briefing · day 15 · resources: —
  - message: Your advisor suggests that you send out spies to gather information from behind the enemy…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `their_end_of_the_bargain:global:2`
  - **Spies return** · briefing · day 20 · resources: —
  - message: Your valiant spies have returned! A very noxious stench fills your nostrils. The stench w…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `their_end_of_the_bargain:global:3`
  - **Day 29** · briefing · day 29 · resources: —
  - message: It is another blazing hot day. You and your troops are beyond exhaustion. You stop and si…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `their_end_of_the_bargain:global:5`
  - **Pick up?** · briefing · day 38 · resources: —
  - message: You spot a young female warrior facing away from you. It looks like she is repairing her …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:27:31`
  - **map_event:0:27:31** · unguarded map · visit @ `0:27:31` · resources: —
  - message: A young knight stops you in his tracks. "HALT!" he shouts. "You mustn't go any further. D…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:27:49`
  - **map_event:0:27:49** · unguarded map · visit @ `0:27:49` · resources: —
  - message: You stop suddenly. "Everything well, sir?" asks one of your advisors. "You have no idea w…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:29:10`
  - **map_event:0:29:10** · unguarded map · visit @ `0:29:10` · resources: —
  - message: You can hardly believe your eyes. There stands a dendroid feeding a large bonfire from a …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:29:30`
  - **map_event:0:29:30** · guarded map · visit @ `0:29:30` · resources: —
  - message: (no message)
  - notes: non-resource: experience | guards: type82x1 | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_experience; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:32:27`
  - **map_event:0:32:27** · unguarded map · visit @ `0:32:27` · resources: —
  - message: You hear a sudden rustling in the bushes nearby. Hushed, you and your troops hit the grou…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:32:55`
  - **map_event:0:32:55** · unguarded map · visit @ `0:32:55` · resources: —
  - message: As you approach the town entrance, you overhear two maidens gossiping. "Have you ever see…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:38:16`
  - **map_event:0:38:16** · unguarded map · visit @ `0:38:16` · resources: —
  - message: While traveling through a wood your horse stumbles across a small wooden box. You dismoun…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:40:32`
  - **map_event:0:40:32** · unguarded map · visit @ `0:40:32` · resources: —
  - message: You have found new confidence in yourself after meeting with your new allies. You finish …
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:47:19`
  - **map_event:0:47:19** · guarded map · visit @ `0:47:19` · resources: —
  - message: "Stop!" Groups of lizardmen emerge from the trees and completely surround you. One of the…
  - notes: guards: type100x30 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:48:33`
  - **map_event:0:48:33** · unguarded map · visit @ `0:48:33` · resources: —
  - message: A merchant approaches you in a panic. "Run Sir! Run for your life! The natives from the s…
  - notes: non-resource: luck | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_luck; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:48:63`
  - **map_event:0:48:63** · unguarded map · visit @ `0:48:63` · resources: —
  - message: "Ooohhh scary" you laugh. "It's about time they build up some defense. Of course they cou…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:5:51`
  - **map_event:0:5:51** · guarded map · visit @ `0:5:51` · resources: —
  - message: A decrepit old man with a walking cane approaches you. You stop and greet the old gentlem…
  - notes: non-resource: artifacts | guards: empty | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; hasGuards_true_but_empty_guardStacks; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:map:0:64:16`
  - **map_event:0:64:16** · unguarded map · visit @ `0:64:16` · resources: —
  - message: You look out to sea and daydream about home. Suddenly, something in the rocks catches you…
  - notes: non-resource: artifacts | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `their_end_of_the_bargain:town:0:57:65:event:0`
  - **Day 39** · town timed · day 1 @ `town:0:57:65:event:0` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

## Rise of the Necromancer (`sod` / `Sandro.h3c`)

### Target (`target`)

Source: `Sandro.h3c` block 1 · H3M v28 · 13 events · sha256 `365dd75f5e74…` · LOD `H3bitmap.lod`

- [ ] `target:global:0`
  - **Day 1** · briefing · day 1 · resources: —
  - message: At last! You have the Cloak of the Undead King and the Armor of the Damned! Your plans to…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `target:global:1`
  - **Letter from Jeddite** · briefing · day 2 · resources: —
  - message: You have just received a threatening letter from the Barbarians due west. It reads: "Sand…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `target:global:6`
  - **Message** · briefing · day 6 · resources: —
  - message: Your spies send a message: "My Sovereign, As difficult as our travels may be now, we don'…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `target:global:2`
  - **Reply to Jeddite** · briefing · day 8 · resources: —
  - message: Your advisors remind you it has been almost a week since you received that threatening le…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `target:global:3`
  - **Letters to Enemies.** · briefing · day 13 · resources: —
  - message: Sending a message confidently announcing your intentions to your enemy is not normally yo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `target:global:4`
  - **Everyone knows** · briefing · day 18 · resources: —
  - message: By now, all the fools standing between you and Deyja know about carry the artifacts you c…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `target:global:5`
  - **Rumors** · briefing · day 24 · resources: —
  - message: A spy returns with word has come about internal conflicts among your enemies. Your old fr…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `target:global:7`
  - **Attempt to assassinate** · briefing · day 36 · resources: -10003 gold
  - message: "Dreadful news, sir!" A soldier frantically runs up to you and tells you that someone bro…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `target:map:0:15:27`
  - **map_event:0:15:27** · unguarded map · visit @ `0:15:27` · resources: —
  - message: This place looks familiar. You have a hazy memory of bringing a beautiful maiden here sev…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `target:map:0:17:19`
  - **map_event:0:17:19** · guarded map · visit @ `0:17:19` · resources: —
  - message: A rustle comes from a bush alongside the road. You leap off your horse, sword in hand, to…
  - notes: guards: type50x56 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `target:map:0:40:46`
  - **map_event:0:40:46** · unguarded map · visit @ `0:40:46` · resources: —
  - message: Your spies report overhearing the following conversation between Lord Ufretin and one of …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `target:map:0:49:63`
  - **map_event:0:49:63** · unguarded map · visit @ `0:49:63` · resources: —
  - message: Your neighboring town is coming into view. Jeddite has become quite a powerful lord as we…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `target:map:1:39:49`
  - **map_event:1:39:49** · guarded map · visit @ `1:39:49` · resources: —
  - message: (no message)
  - notes: guards: type88x121 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)

### Master (`master`)

Source: `Sandro.h3c` block 2 · H3M v28 · 14 events · sha256 `b3586e5d9fc3…` · LOD `H3bitmap.lod`

- [ ] `master:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: During your journey to Deyja, you meet a young Wizard named Vidomina who wishes to become…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `master:global:1`
  - **First Lesson.** · briefing · day 2 · resources: —
  - message: Vidomina continues to demonstrate great talent and dedication to becoming a Necromancer. …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `master:global:2`
  - **You're in love** · briefing · day 8 · resources: —
  - message: "He's in love, I tell you," a skeleton warrior whispers to his comrades. "Haven't you see…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `master:global:3`
  - **Vidomina Message** · briefing · day 15 · resources: —
  - message: A message from Vidomina arrives: "Master, there are two Rampart towns in this region. Eth…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `master:global:4`
  - **More info** · briefing · day 23 · resources: —
  - message: One of your spies asks to speak to you: "Sir, after studying our dwarven enemies for a we…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `master:map:0:12:29`
  - **map_event:0:12:29** · guarded map · visit @ `0:12:29` · resources: —
  - message: Long thick branches wrap around your body and pull you to the ground. You are attacked by…
  - notes: guards: type23x5 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `master:map:0:19:19`
  - **map_event:0:19:19** · unguarded map · visit @ `0:19:19` · resources: —
  - message: Your spies report those border guards flying a black standard are guarding all the monoli…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `master:map:0:22:18`
  - **map_event:0:22:18** · guarded map · visit @ `0:22:18` · resources: —
  - message: The trees around come to life. You are attacked!
  - notes: guards: type22x21 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `master:map:0:24:10`
  - **map_event:0:24:10** · guarded map · visit @ `0:24:10` · resources: —
  - message: An operating sawmill stands before you. Lots of Power Liches guard it. You never thought …
  - notes: guards: type65x33 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `master:map:0:29:22`
  - **map_event:0:29:22** · guarded map · visit @ `0:29:22` · resources: —
  - message: This must be sacred sulfur!
  - notes: guards: type26x3 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `master:map:0:2:18`
  - **map_event:0:2:18** · guarded map · visit @ `0:2:18` · resources: —
  - message: (no message)
  - notes: guards: type14x37 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `master:map:0:7:15`
  - **map_event:0:7:15** · guarded map · visit @ `0:7:15` · resources: —
  - message: From out of the lava you see fiery creatures approach you. Quickly, you draw your sword.
  - notes: guards: type114x51 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `master:map:0:9:25`
  - **map_event:0:9:25** · guarded map · visit @ `0:9:25` · resources: —
  - message: The Silver Pegasi don't look too happy to see you. As you begin to approach the ore pit, …
  - notes: guards: type21x11 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `master:map:1:3:22`
  - **map_event:1:3:22** · unguarded map · visit @ `1:3:22` · resources: —
  - message: The dwarven tunnels cover a vast area. As you look down into the mining shaft, you see th…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Finneas Vilmar (`finneas_vilmar`)

Source: `Sandro.h3c` block 3 · H3M v28 · 8 events · sha256 `80f193375905…` · LOD `H3bitmap.lod`

- [ ] `finneas_vilmar:global:0`
  - **Day 1** · briefing · day 1 · resources: —
  - message: Finneas Vilmar is a young lord who desires power. With such a greedy appetite but a poor …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `finneas_vilmar:global:2`
  - **Duke Alarice** · briefing · day 4 · resources: —
  - message: Duke Alarice has a problem with Finneas Vilmar and with you waltzing into Deyja with a fu…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `finneas_vilmar:global:1`
  - **Underground Dwarves** · briefing · day 7 · resources: —
  - message: Reports confirm that two separate groups of AvLee forces have tunneled underground and in…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `finneas_vilmar:map:0:51:37`
  - **map_event:0:51:37** · unguarded map · visit @ `0:51:37` · resources: —
  - message: Your spies inform you there are three tribes of dwarves in this area. None of them are al…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `finneas_vilmar:map:0:56:27`
  - **map_event:0:56:27** · guarded map · visit @ `0:56:27` · resources: —
  - message: A contingent of skeletons blocks your way, refusing to let you pass. Grabbing one by its …
  - notes: guards: type57x11, type57x11, type57x11, type57x11, type57x11 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `finneas_vilmar:map:0:5:28`
  - **map_event:0:5:28** · guarded map · visit @ `0:5:28` · resources: —
  - message: You are greeted with sharpened sticks pointed directly at your face. A stout dwarf passes…
  - notes: guards: type15x101, type17x52, type19x41, type21x32, type23x24, type25x19, type26x8 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `finneas_vilmar:map:1:47:33`
  - **map_event:1:47:33** · guarded map · visit @ `1:47:33` · resources: —
  - message: Out of nowhere, a contingent of Wood Elves attacks!
  - notes: guards: type18x103 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `finneas_vilmar:map:1:61:7`
  - **map_event:1:61:7** · unguarded map · visit @ `1:61:7` · resources: —
  - message: "Stop where you are!" shouts a voice out of nowhere. "Why do you stop us?" you shout back…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Duke Alarice (`duke_alarice`)

Source: `Sandro.h3c` block 4 · H3M v28 · 1 events · sha256 `12ed07acc9a9…` · LOD `H3bitmap.lod`

- [ ] `duke_alarice:global:0`
  - **Day 1** · briefing · day 1 · resources: —
  - message: Soon the Duke Alarice will find himself among the dead. Your plans are going well as you …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

## Hack and Slash (`sod` / `Crag.h3c`)

### Bashing Skulls (`bashing_skulls`)

Source: `Crag.h3c` block 1 · H3M v28 · 6 events · sha256 `fb64aee610e8…` · LOD `H3bitmap.lod`

- [ ] `bashing_skulls:global:0`
  - **Sandro meeting.** · briefing · day 1 · resources: —
  - message: "You appear to be the right man for a series of tasks I need performed, Mister Hack," say…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `bashing_skulls:global:1`
  - **Entering region.** · briefing · day 1 · resources: —
  - message: As you enter the region of Avautnell, you decide to first establish a Stronghold of your …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `bashing_skulls:global:2`
  - **Rogue barbarians.** · briefing · day 7 · resources: —
  - message: Scouts report Barshon has allied with the rogue Barbarians in the area. Also, an Erathian…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `bashing_skulls:map:0:50:66`
  - **map_event:0:50:66** · unguarded map · visit @ `0:50:66` · resources: —
  - message: A young mounted barbarian shouts, "I, Gurnis the Barbarian, demand that you shall go no f…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `bashing_skulls:map:0:54:12`
  - **map_event:0:54:12** · unguarded map · visit @ `0:54:12` · resources: —
  - message: A message arrives from Barshon: "I know you mean to take the Skull Helmet from me, but I …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `bashing_skulls:map:1:27:33`
  - **map_event:1:27:33** · unguarded map · visit @ `1:27:33` · resources: —
  - message: Bones abound in what is obviously a troll's underground lair.
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Black Sheep (`black_sheep`)

Source: `Crag.h3c` block 2 · H3M v28 · 7 events · sha256 `7511f1515f2f…` · LOD `H3bitmap.lod`

- [ ] `black_sheep:global:0`
  - **Sandro take 2** · briefing · day 1 · resources: —
  - message: "Ah, you've brought me the Skull Helmet, Mister Hack," Sandro exclaims back in the Wingta…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `black_sheep:global:1`
  - **Scout report** · briefing · day 7 · resources: —
  - message: Scouts report there are three Castles in the region, and rumor has it Marzeth is under th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `black_sheep:global:2`
  - **Scout report 2** · briefing · day 14 · resources: —
  - message: Scouts have another rumor to report. Supposedly Marzeth was a Knight of the Blade who inh…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `black_sheep:map:0:15:19`
  - **map_event:0:15:19** · guarded map · visit @ `0:15:19` · resources: —
  - message: Fighters appear out of the underbrush and eye you warily. "Do you have permission to be h…
  - notes: guards: type6x60, type7x1 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `black_sheep:map:0:15:68`
  - **map_event:0:15:68** · guarded map · visit @ `0:15:68` · resources: —
  - message: Lizardmen rise up out of the swamp and attack!
  - notes: guards: type100x100, type101x40 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `black_sheep:map:0:46:39`
  - **map_event:0:46:39** · guarded map · visit @ `0:46:39` · resources: —
  - message: Fighters appear out of the underbrush and eye you warily. "Do you have permission to be h…
  - notes: guards: type6x60, type7x1 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `black_sheep:map:0:64:9`
  - **map_event:0:64:9** · unguarded map · visit @ `0:64:9` · resources: —
  - message: The Stronghold leader and his clan ride forward to greet you. As you embrace your fellow …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### A Cage in the Hand (`a_cage_in_the_hand`)

Source: `Crag.h3c` block 3 · H3M v28 · 7 events · sha256 `3678463268f6…` · LOD `H3bitmap.lod`

- [ ] `a_cage_in_the_hand:global:0`
  - **Sandro meeting 3** · briefing · day 1 · resources: —
  - message: "Splendid! I see you have been successful once again, Mister Hack!" Sandro says back at t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_cage_in_the_hand:global:1`
  - **Entering the region.** · briefing · day 1 · resources: —
  - message: As you enter region marked on Sandro's map, your first thought is to set up a Stronghold.…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_cage_in_the_hand:global:2`
  - **Send Message** · briefing · day 21 · resources: —
  - message: You order a scout to send a message to the Necromancers: "Give up the Rib Cage or Crag Ha…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_cage_in_the_hand:global:3`
  - **Reply** · briefing · day 30 · resources: —
  - message: Your messenger returns, bruised, bloody, and maimed, but still alive... barely. Limping u…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_cage_in_the_hand:map:0:53:61`
  - **map_event:0:53:61** · unguarded map · visit @ `0:53:61` · resources: —
  - message: It looks as if the Necromancers of the Ebon Hand are barricaded in their main castle! Per…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `a_cage_in_the_hand:town:0:11:13:event:0`
  - **Goblin tribe tribute.** · town timed · day 7, every 7d @ `town:0:11:13:event:0` (town) · resources: —
  - message: A large nearby Goblin tribe sends its warriors as tribute to their Barbarian brothers for…
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `a_cage_in_the_hand:town:0:55:56:event:0`
  - **Bonus money from followers.** · town timed · day 7, every 5d @ `town:0:55:56:event:0` (town) · resources: +3 wood, +3 mercury, +3 ore, +3 sulfur, +3 crystal, +3 gems, +2000 gold
  - message: This is money donated from fanatic followers.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Grave Robber (`grave_robber`)

Source: `Crag.h3c` block 4 · H3M v28 · 11 events · sha256 `6b0993117b05…` · LOD `H3bitmap.lod`

- [ ] `grave_robber:global:0`
  - **Sandro 4** · briefing · day 1 · resources: —
  - message: "You have the Rib Cage! Excellent work, Mister Hack" Sandro says back in the Wingtail tav…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `grave_robber:global:1`
  - **Captain meeting** · briefing · day 1 · resources: —
  - message: As you approach the castle Sandro indicated on your map, its captain rides out to greet y…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `grave_robber:global:3`
  - **Sandro sends money.** · briefing · day 7, every 7d · resources: +4000 gold
  - message: Sandro sends gold to help in your search.
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `grave_robber:global:2`
  - **Message from Hand of Death.** · briefing · day 15 · resources: —
  - message: A message arrives from the Hand of Death: "We know you have been sent by an acquaintance …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `grave_robber:global:4`
  - **Barricaded Hand of Death.** · briefing · day 28 · resources: —
  - message: Scouts report the Hand of Death has barricaded their castles very effectively. This cowar…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `grave_robber:map:0:19:25`
  - **map_event:0:19:25** · unguarded map · visit @ `0:19:25` · resources: —
  - message: The road to the east disappears into a bunch of litter and bones.
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `grave_robber:map:0:23:25`
  - **map_event:0:23:25** · unguarded map · visit @ `0:23:25` · resources: —
  - message: From the looks of it, this town has been overrun with undead. Scouts advise caution -- an…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `grave_robber:map:0:50:62`
  - **map_event:0:50:62** · unguarded map · visit @ `0:50:62` · resources: +4294967286 gold
  - message: "Beware!" one of the shipwrights tells you, visibly shaken. "I have seen undead suddenly …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `grave_robber:map:0:51:55`
  - **map_event:0:51:55** · guarded map · visit @ `0:51:55` · resources: —
  - message: The souls of the damned who are buried here rise up and attack!
  - notes: guards: type57x120, type61x90, type65x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `grave_robber:map:0:56:62`
  - **map_event:0:56:62** · guarded map · visit @ `0:56:62` · resources: —
  - message: The souls of the damned who are buried here rise up and attack!
  - notes: guards: type57x200, type61x150, type65x20 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `grave_robber:town:0:12:10:event:0`
  - **New recruits.** · town timed · day 12, every 14d @ `town:0:12:10:event:0` (town) · resources: —
  - message: An aggressive recruiting campaign by the captain and his fellow mercenaries at the castle…
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

## Birth of a Barbarian (`sod` / `Yog.h3c`)

### On the Run (`on_the_run`)

Source: `Yog.h3c` block 1 · H3M v28 · 12 events · sha256 `b1a551ab562e…` · LOD `H3bitmap.lod`

- [ ] `on_the_run:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: Born the son of a Barbarian chieftain and a Genie enchantress, you have always found your…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `on_the_run:global:4`
  - **Take this!!!!!** · timed resource · day 1 · resources: -20 wood, -10 mercury, -20 ore, -10 sulfur, -10 crystal, -10 gems, -20000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `on_the_run:global:1`
  - **Journal Entry 1- Day 4** · briefing · day 4 · resources: —
  - message: Journal Entry 1: I have been on the run for four days now, and still there is no sign of …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `on_the_run:global:6`
  - **Take this too!!!!** · timed resource · day 7 · resources: -100 wood, -100 mercury, -100 ore, -100 sulfur, -100 crystal, -100 gems, -50000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `on_the_run:global:2`
  - **Journal Entry 2 - Day 8** · briefing · day 8 · resources: —
  - message: Journal Entry 2: We arrived at Padon not too long ago. So far everything is going well, a…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `on_the_run:global:3`
  - **Journal Entry 3 - Day 14** · briefing · day 14 · resources: —
  - message: Journal Entry 3: Late last night my scout returned with the good news that a city named G…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `on_the_run:global:5`
  - **Good Find** · briefing · day 23 · resources: +10 gems, +7000 gold
  - message: You discover an ancient magical text on the black art of Necromancy. This is not the firs…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `on_the_run:map:0:32:7`
  - **map_event:0:32:7** · unguarded map · visit @ `0:32:7` · resources: —
  - message: Journal Entry 5: My scout has advised me to head south because an army of this size canno…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `on_the_run:map:0:48:20`
  - **map_event:0:48:20** · unguarded map · visit @ `0:48:20` · resources: —
  - message: Journal Entry 6: It is almost over. The scout's map indicates this to be the entrance to …
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `on_the_run:map:0:58:7`
  - **map_event:0:58:7** · unguarded map · visit @ `0:58:7` · resources: —
  - message: Journal Entry 7: This battle could have been avoided. All I wanted was to hold out here u…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `on_the_run:map:0:6:22`
  - **map_event:0:6:22** · unguarded map · visit @ `0:6:22` · resources: —
  - message: Journal Entry 4 (Continued): The battle was indeed fierce. I did not expect to lose as ma…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `on_the_run:map:0:8:24`
  - **map_event:0:8:24** · unguarded map · visit @ `0:8:24` · resources: —
  - message: Journal Entry 4: I am resting my army before we begin the battle to cross the border. Jus…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### The Meeting (`the_meeting`)

Source: `Yog.h3c` block 2 · H3M v28 · 5 events · sha256 `b05982e54331…` · LOD `H3bitmap.lod`

- [ ] `the_meeting:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: Aine gave up pursuit even sooner than you hoped. Not wanting to start a war between Braca…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `the_meeting:global:1`
  - **Journal Entry 8 - Day 2** · briefing · day 2 · resources: —
  - message: Journal Entry 8: My scouts report that there are several routes leading to Ulgak, but lar…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `the_meeting:global:2`
  - **Journal Entry 9 - Day 4** · briefing · day 4 · resources: —
  - message: Journal Entry 9: My scouts reported have returned with very disturbing news. Krewlod is r…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `the_meeting:map:0:18:13`
  - **map_event:0:18:13** · unguarded map · visit @ `0:18:13` · resources: —
  - message: Journal Entry 11: I would think that my being this close to the capital would attract Win…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `the_meeting:map:1:7:25`
  - **map_event:1:7:25** · unguarded map · visit @ `1:7:25` · resources: —
  - message: Journal Entry 10: I tried getting past the garrison, but the Barbarians have packed them …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### A Tough Start (`a_tough_start`)

Source: `Yog.h3c` block 3 · H3M v28 · 9 events · sha256 `7221dfa0be50…` · LOD `H3bitmap.lod`

- [ ] `a_tough_start:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: After a few days travel into Tatalia, you discovered the Tatalians really don't want you …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_tough_start:global:1`
  - **Journal Entry 12** · briefing · day 4 · resources: —
  - message: Journal Entry 12: I sent my scouts out yesterday to search the countryside while I search…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_tough_start:global:5`
  - **Comp Resources** · timed resource · day 7, every 7d · resources: +14 wood, +7 mercury, +14 ore, +25 sulfur, +7 crystal, +7 gems, +10000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `a_tough_start:global:2`
  - **Journal Entry 13** · briefing · day 11 · resources: —
  - message: Journal Entry 13: All but one of my scouts have returned to report they have been unable …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_tough_start:global:3`
  - **Journal Entry 14** · briefing · day 20 · resources: —
  - message: Journal Entry 14: Just when I was beginning to fear that my last scout had been killed, h…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_tough_start:global:4`
  - **Journal Entry 15** · briefing · day 21 · resources: —
  - message: Journal Entry 15: I had the scout who located Alendora brought before me after he had a p…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_tough_start:town:0:67:13:event:2`
  - **Give Comp Creatures** · town timed · day 7, every 7d @ `town:0:67:13:event:2` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `a_tough_start:town:0:67:13:event:0`
  - **Give Comp Hydras** · town timed · day 20 @ `town:0:67:13:event:0` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `a_tough_start:town:0:67:13:event:1`
  - **Give Comp Upg Hydras** · town timed · day 27 @ `town:0:67:13:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Falor and Terwen (`falor_and_terwen`)

Source: `Yog.h3c` block 4 · H3M v28 · 3 events · sha256 `86d1beca5648…` · LOD `H3bitmap.lod`

- [ ] `falor_and_terwen:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: Before leaving Tatalia you sent a messenger off to deliver the Pendant of Courage to Wins…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `falor_and_terwen:global:1`
  - **Journal Entry 16** · briefing · day 4 · resources: —
  - message: Journal Entry 16: Fortifying my position wasn't difficult, for the mountains make an effe…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `falor_and_terwen:map:1:18:8`
  - **map_event:1:18:8** · unguarded map · visit @ `1:18:8` · resources: —
  - message: Journal Entry 17: It has been a while since my last journal entry, but I have been very b…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Returning to Bracada (`returning_to_bracada`)

Source: `Yog.h3c` block 5 · H3M v28 · 6 events · sha256 `0e3ff2f4b0ce…` · LOD `H3bitmap.lod`

- [ ] `returning_to_bracada:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: You dispatched a messenger immediately to Winston Boragus, informing him that you found F…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `returning_to_bracada:global:4`
  - **Comp Stuff** · timed resource · day 1, every 7d · resources: +10 wood, +7 mercury, +10 ore, +7 sulfur, +7 crystal, +25 gems, +15000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `returning_to_bracada:global:1`
  - **Journal Entry 18** · briefing · day 3 · resources: —
  - message: Journal Entry 18: I have sent my scouts out into Bracada hoping to get some good intellig…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `returning_to_bracada:global:2`
  - **Journal Entry 19** · briefing · day 6 · resources: —
  - message: Journal entry 19: My scouts returned a few hours ago without any information on Aine. She…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `returning_to_bracada:global:3`
  - **Journal Entry 20** · briefing · day 13 · resources: —
  - message: Journal Entry 20: My scouts have found Beleg and Orruk: they are due south from my city. …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `returning_to_bracada:town:0:4:34:event:0`
  - **Comp Stuff.** · town timed · day 16 @ `town:0:4:34:event:0` (town) · resources: +4 gems, +20000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

## New Beginning (`sod` / `Gem.h3c`)

### Clearing the Border (`clearing_the_border`)

Source: `Gem.h3c` block 1 · H3M v28 · 15 events · sha256 `2e851bfdec4e…` · LOD `H3bitmap.lod`

- [ ] `clearing_the_border:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: Eight months ago my mentor, Amanda, told me of a device invented in Antagarich that might…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:global:1`
  - **Intro (cont)** · briefing · day 1 · resources: —
  - message: When Delino learned I had been a general in the Enroth's Succession Wars, he summoned me …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:global:3`
  - **Rampart Castle** · briefing · day 5 · resources: —
  - message: Following Delino's advice, I based my armies at a pair of vacant Rampart Castles north of…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:global:4`
  - **Necro Castles** · briefing · day 13 · resources: —
  - message: My Elven scouts have just reported there are two Necromancer castles to the North. The ra…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:global:2`
  - **Black Hair (Deleted Unless Gem gets her horse)** · briefing · day 21 · resources: —
  - message: One of my Centaurs approached me while we were setting up camp. "My Lady Gem," he asked "…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:global:10`
  - **Necro Harvest (cont)** · briefing · day 29 · resources: —
  - message: I buried the children and freed the animals, which were still alive. The real horror is t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:global:5`
  - **Necro Harvest** · briefing · day 29 · resources: —
  - message: I rode through a small hamlet yesterday, and I had a horrible sensation of deja vu. A Nec…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:global:6`
  - **Nightmare** · briefing · day 32 · resources: —
  - message: I was with a small patrol traveling in the forest in the hour before dusk becomes true ni…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:global:7`
  - **Nightmare (cont)** · briefing · day 32 · resources: —
  - message: I rolled from my cot shaking with anguish and rage. This time the Necromancer would pay f…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:global:8`
  - **Meeting with Ranger (Clancy)** · briefing · day 40 · resources: —
  - message: Last night I met Clancy, a ranger hero who has a bond with Unicorns. His Lord is an AvLee…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:global:9`
  - **Manda Dream** · briefing · day 48 · resources: —
  - message: I dreamed of Amanda last night. She asked me how I liked Antagarich. I told her I thought…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `clearing_the_border:town:0:55:10:event:0`
  - **Extra Income** · town timed · day 15, every 1d @ `town:0:55:10:event:0` (town) · resources: +1000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `clearing_the_border:town:0:15:14:event:0`
  - **Extra Income** · town timed · day 21, every 1d @ `town:0:15:14:event:0` (town) · resources: +1000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `clearing_the_border:town:0:39:21:event:0`
  - **Extra Income** · town timed · day 21, every 1d @ `town:0:39:21:event:0` (town) · resources: +500 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `clearing_the_border:town:0:54:41:event:0`
  - **Extra Income** · town timed · day 21, every 1d @ `town:0:54:41:event:0` (town) · resources: +500 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### After the Amulet (`after_the_amulet`)

Source: `Gem.h3c` block 2 · H3M v28 · 24 events · sha256 `a00120b11a3f…` · LOD `H3bitmap.lod`

- [ ] `after_the_amulet:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: I told Clancy of my agreement to help a wizard's apprentice, Sandro, find an Amulet of th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:12`
  - **Intro (cont)** · briefing · day 1 · resources: —
  - message: I replied I would be glad to have his company again as long as he understood this was my …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:1`
  - **Amulet Report** · briefing · day 3 · resources: —
  - message: According to Sandro, the Amulet of the Undertaker is located to the North Northeast of Cl…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:2`
  - **Liking the Rampart** · briefing · day 11 · resources: —
  - message: I am becoming to feel quite at home in the Rampart Castle. I'm even starting to get accus…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:3`
  - **Necro Near By** · briefing · day 17 · resources: —
  - message: My Elven scouts have just reported there is a Necromancer to the North East. It appears h…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:8`
  - **Letter from Sandro** · briefing · day 21 · resources: —
  - message: I received a very interesting letter from Sandro today. Apparently he convinced his maste…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:9`
  - **Letter from Sandro (cont)** · briefing · day 21 · resources: —
  - message: I wrote back to Sandro that Ethric's project was a worthwhile one and promised to search …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:10`
  - **Message to Clancy** · briefing · day 23 · resources: —
  - message: I sent a message to Clancy telling him about Ethric's project and that I had promised to …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:4`
  - **Ghost Dragons** · briefing · day 28 · resources: —
  - message: One of my Elven scouts talked to a local who said he saw a group of Ghost Dragons going t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:5`
  - **Visit from a Druid** · briefing · day 33 · resources: —
  - message: An old Druid appeared just as we were setting up camp last night. He said he had heard mu…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:11`
  - **Message from Clancy** · briefing · day 37 · resources: —
  - message: Clancy sent me a message back saying he would also like to help Ethric but first needed t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:6`
  - **Saved a Hamlet** · briefing · day 41 · resources: —
  - message: This morning, screams brought us to a tiny hamlet. A small roaming band of skeletons and …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:global:7`
  - **Gold** · briefing · day 49 · resources: —
  - message: People are strange about gold. If you don't let them give it to you, they don't know what…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `after_the_amulet:map:0:32:5`
  - **map_event:0:32:5** · guarded map · visit @ `0:32:5` · resources: —
  - message: Suddenly, the smell of death is overwhelming. "Ambush!" screams one of your troops, point…
  - notes: non-resource: morale | guards: type68x20, type69x20, type68x20 | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `after_the_amulet:town:0:10:21:event:2`
  - **Build Townhall** · town timed · day 2 @ `town:0:10:21:event:2` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `after_the_amulet:town:0:57:18:event:2`
  - **Build Townhall** · town timed · day 2 @ `town:0:57:18:event:2` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `after_the_amulet:town:0:57:18:event:0`
  - **Extra Income** · town timed · day 11, every 1d @ `town:0:57:18:event:0` (town) · resources: +2500 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `after_the_amulet:town:0:57:18:event:1`
  - **Extra Troops** · town timed · day 17, every 7d @ `town:0:57:18:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `after_the_amulet:town:0:10:21:event:0`
  - **Extra Income** · town timed · day 18, every 1d @ `town:0:10:21:event:0` (town) · resources: +2500 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `after_the_amulet:town:0:37:28:event:0`
  - **Extra Income** · town timed · day 18, every 1d @ `town:0:37:28:event:0` (town) · resources: +1000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `after_the_amulet:town:0:44:59:event:0`
  - **Extra Income** · town timed · day 18, every 1d @ `town:0:44:59:event:0` (town) · resources: +1000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `after_the_amulet:town:0:62:42:event:0`
  - **Extra Income** · town timed · day 18, every 1d @ `town:0:62:42:event:0` (town) · resources: +1000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `after_the_amulet:town:0:10:21:event:1`
  - **Extra Troops** · town timed · day 24, every 7d @ `town:0:10:21:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `after_the_amulet:town:0:62:42:event:1`
  - **Extra Creatures** · town timed · day 24 @ `town:0:62:42:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Retrieving the Cowl (`retrieving_the_cowl`)

Source: `Gem.h3c` block 3 · H3M v28 · 21 events · sha256 `1949b37da011…` · LOD `H3bitmap.lod`

- [ ] `retrieving_the_cowl:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: A Barbarian named Terek has located the Vampire's Cowl for Sandro. Unfortunately, Bandits…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:global:3`
  - **Intro (cont)** · briefing · day 1 · resources: —
  - message: I also received some good news today. Clancy obtained permission from his Lord to help me…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:global:1`
  - **Scouting Report Rampart Towns** · briefing · day 3 · resources: —
  - message: A scouting party has located a neutral Rampart town to the north east of our starting bas…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:global:10`
  - **Another Harvested Village (cont)** · briefing · day 11 · resources: —
  - message: I must stay focused on my quest. I found out very painfully I couldn't single-handedly ri…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:global:4`
  - **Another Harvested Village** · briefing · day 11 · resources: —
  - message: Today we rode through another small hamlet that had been "harvested" by a Necromancer abo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:global:2`
  - **Scouting Report Border Lord** · briefing · day 19 · resources: —
  - message: Apparently I made an impression on the Deyjan Border Lords. My Elven scouts report the ne…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:global:6`
  - **Dream from Manda** · briefing · day 27 · resources: —
  - message: I had another dream about Amanda last night. I think the dreams are real, and she's commu…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:global:5`
  - **Sorting it out** · briefing · day 30 · resources: —
  - message: I was thinking about... things today. Sometimes I just refuse to think about certain thin…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:global:7`
  - **Visit from Lord** · briefing · day 38 · resources: —
  - message: Clancy's Lord Fayette arrived today! What a pleasant surprise! He claimed he was on a "Hu…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:global:8`
  - **Letter to Lord** · briefing · day 42 · resources: —
  - message: I wanted to write Lord Fayette right after his visit, but I forced myself to let some tim…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:global:9`
  - **Letter from Lord** · briefing · day 50 · resources: —
  - message: I received a letter from Lord Fayette today. I had to open it right away. It formally inv…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `retrieving_the_cowl:town:0:44:62:event:3`
  - **Build Townhall** · town timed · day 2 @ `town:0:44:62:event:3` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `retrieving_the_cowl:town:0:64:47:event:3`
  - **Build Townhall** · town timed · day 2 @ `town:0:64:47:event:3` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `retrieving_the_cowl:town:0:44:62:event:1`
  - **Extra Income** · town timed · day 21, every 1d @ `town:0:44:62:event:1` (town) · resources: +2000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `retrieving_the_cowl:town:0:64:47:event:1`
  - **Extra Income** · town timed · day 21, every 1d @ `town:0:64:47:event:1` (town) · resources: +2000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `retrieving_the_cowl:town:0:44:62:event:0`
  - **Extra Creatures** · town timed · day 24, every 7d @ `town:0:44:62:event:0` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `retrieving_the_cowl:town:0:64:47:event:0`
  - **Extra Creatures** · town timed · day 24, every 7d @ `town:0:64:47:event:0` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `retrieving_the_cowl:town:0:16:61:event:0`
  - **Extra Income** · town timed · day 28, every 1d @ `town:0:16:61:event:0` (town) · resources: +1000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `retrieving_the_cowl:town:0:44:62:event:2`
  - **1 time Bonus Income** · town timed · day 28 @ `town:0:44:62:event:2` (town) · resources: +5000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `retrieving_the_cowl:town:0:64:47:event:2`
  - **1 time Bonus Income** · town timed · day 28 @ `town:0:64:47:event:2` (town) · resources: +5000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `retrieving_the_cowl:town:0:65:26:event:0`
  - **Extra Income** · town timed · day 28, every 1d @ `town:0:65:26:event:0` (town) · resources: +1000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Driving for the Boots (`driving_for_the_boots`)

Source: `Gem.h3c` block 4 · H3M v28 · 25 events · sha256 `6ff10b869fe0…` · LOD `H3bitmap.lod`

- [ ] `driving_for_the_boots:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: Getting the Dead Man's Boots is not going to be easy. From what my Elven scouts tell me, …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:1`
  - **Scrying the Boots** · briefing · day 4 · resources: —
  - message: I tried to scry the location of the Dead Man's Boots but could not divine anything useful…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:4`
  - **Black Grip** · briefing · day 12 · resources: —
  - message: I am in my sixty-first year as a Sorceress. Over time you learn to protect yourself and y…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:5`
  - **Black Grip (cont)** · briefing · day 12 · resources: —
  - message: This morning I discovered half my troops had been afflicted with a spell. It looked like …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:2`
  - **Another old Druid visit** · briefing · day 20 · resources: —
  - message: I had a surprise visitor this morning: the old druid I had spoken to a while ago. Over br…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:6`
  - **Book** · briefing · day 23 · resources: —
  - message: I am not as trusting as I once was. After retrieving the book the old druid gave me, I th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:7`
  - **Book II** · briefing · day 31 · resources: —
  - message: I finished reading the Druid Book last night. I have been reading it slowly and thinking …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:3`
  - **Manda's Reassurance** · briefing · day 34 · resources: —
  - message: I dreamed of Amanda last night and was happy to see her. I told her everything about the …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:8`
  - **Manda's Reassurance (cont)** · briefing · day 34 · resources: —
  - message: "Gem," Amanda replied, "if our two philosophies are as similar as you say, it may be a go…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:9`
  - **Decision** · briefing · day 37 · resources: —
  - message: I've been thinking about the old Druid's offer and what Amanda said. I think I will ask w…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:10`
  - **Druid Meeting** · briefing · day 45 · resources: —
  - message: I met with the old Druid this morning over breakfast. I was honest with him. I told him I…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:11`
  - **Druid Meeting (cont)** · briefing · day 45 · resources: —
  - message: He explained that each Druid wrote their own oaths, and by lunch we had worked out a set …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:12`
  - **Manda Approval** · briefing · day 49 · resources: —
  - message: Amanda was in my dreams last night. After we greeted each other I told her of my meeting …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:13`
  - **Petition Approval/Closure** · briefing · day 51 · resources: —
  - message: Amanda appeared last night and told me my sister Sorcerers had approved my petition to jo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:global:14`
  - **Message to Old Druid** · briefing · day 52 · resources: —
  - message: I sent the revised oath to the Old Druid this morning. I told him there were some nuances…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `driving_for_the_boots:town:0:44:42:event:1`
  - **1 time bonus** · town timed · day 15 @ `town:0:44:42:event:1` (town) · resources: +3000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `driving_for_the_boots:town:0:26:70:event:2`
  - **1 time bonus** · town timed · day 21 @ `town:0:26:70:event:2` (town) · resources: +5000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `driving_for_the_boots:town:0:74:58:event:2`
  - **1 time bonus** · town timed · day 21 @ `town:0:74:58:event:2` (town) · resources: +5000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `driving_for_the_boots:town:0:26:70:event:0`
  - **Extra Income** · town timed · day 28, every 1d @ `town:0:26:70:event:0` (town) · resources: +2000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `driving_for_the_boots:town:0:44:42:event:0`
  - **Extra Income** · town timed · day 28, every 1d @ `town:0:44:42:event:0` (town) · resources: +1000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `driving_for_the_boots:town:0:60:85:event:0`
  - **Extra Income** · town timed · day 28, every 1d @ `town:0:60:85:event:0` (town) · resources: +5000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `driving_for_the_boots:town:0:74:58:event:0`
  - **Extra Income** · town timed · day 28, every 1d @ `town:0:74:58:event:0` (town) · resources: +2000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `driving_for_the_boots:town:0:26:70:event:1`
  - **Extra Critters** · town timed · day 31 @ `town:0:26:70:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `driving_for_the_boots:town:0:60:85:event:1`
  - **Extra Critters** · town timed · day 31, every 7d @ `town:0:60:85:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `driving_for_the_boots:town:0:74:58:event:1`
  - **Extra Critters** · town timed · day 31 @ `town:0:74:58:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

## Elixir of Life (`sod` / `Gelu.h3c`)

### Graduation Exercise (`graduation_exercise`)

Source: `Gelu.h3c` block 1 · H3M v28 · 5 events · sha256 `c40fdea8622f…` · LOD `H3bitmap.lod`

- [ ] `graduation_exercise:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: Congratulations, cadet. You have but one test left to complete your training and join the…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `graduation_exercise:global:3`
  - **A Lesson in Adversity** · briefing · day 11 · resources: -5 wood, -2 mercury, -5 ore, -2 sulfur, -2 crystal, -2 gems, -1000 gold
  - message: Forest Guard rangers must deal with a wide variety of unexpected and troublesome situatio…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `graduation_exercise:global:1`
  - **Words of Encouragement** · briefing · day 31 · resources: —
  - message: It has been 30 days since you began your mission. You are taking too long. As a member of…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `graduation_exercise:global:2`
  - **60 Days Later** · briefing · day 61, every 14d · resources: —
  - message: Cadet, this is getting ridiculous! A region of this size should have been cleared by now.…
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `graduation_exercise:map:0:20:13`
  - **map_event:0:20:13** · unguarded map · visit @ `0:20:13` · resources: —
  - message: This city looks like the perfect place for a base of operations. Take it and build it up …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Cutthroats (`cutthroats`)

Source: `Gelu.h3c` block 2 · H3M v28 · 8 events · sha256 `9d70b8652315…` · LOD `H3bitmap.lod`

- [ ] `cutthroats:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: The Forest Guard has been assigned to recover several artifacts needed to concoct the Eli…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `cutthroats:global:2`
  - **The Lords** · briefing · day 2 · resources: —
  - message: The warlords in this region are cutthroats and madmen. They have been looting caravans, r…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `cutthroats:global:7`
  - **Bandits Attack!** · briefing · day 5, every 21d · resources: -5 wood, -3 mercury, -5 ore, -3 sulfur, -3 crystal, -3 gems, -1500 gold
  - message: Bandits have attacked your supply lines and taken valuable resources.
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `cutthroats:global:1`
  - **Scout Report** · briefing · day 7 · resources: —
  - message: Your spies tell of a seer in the Northeast who knows the location of the Ring of Vitality…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `cutthroats:global:3`
  - **An Arrangement** · briefing · day 13 · resources: —
  - message: Our scouts report that one of the warlords has made contact with the Necromancers and is …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `cutthroats:global:4`
  - **The Seer** · briefing · day 15 · resources: —
  - message: The seer in the Northeast is an old wise man named Feredor. Seek his advice, but be warne…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `cutthroats:global:6`
  - **Terrain** · briefing · day 21 · resources: —
  - message: Be warned, this region was the site of a glorious battle and is now holy ground. Do not d…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `cutthroats:global:5`
  - **The Vision** · briefing · day 26 · resources: —
  - message: Last night your sleep was wracked with terrible dreams, visions of the dark events to com…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Valley of the Dragon Lords (`valley_of_the_dragon_lords`)

Source: `Gelu.h3c` block 3 · H3M v28 · 5 events · sha256 `84a32d2f7fc7…` · LOD `H3bitmap.lod`

- [ ] `valley_of_the_dragon_lords:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: Somewhere in the Valley of Dagrond is the Ring of Life, the second component needed for t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `valley_of_the_dragon_lords:global:1`
  - **More on the Dragon Lords** · briefing · day 3 · resources: —
  - message: We now know for certain that this Dragon Lord is working against AvLee and her people. He…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `valley_of_the_dragon_lords:global:2`
  - **The Ring** · briefing · day 8 · resources: —
  - message: Rumor has it the Ring of Life is to found near a lake made of pure flames.
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `valley_of_the_dragon_lords:global:3`
  - **Lord Falorel** · briefing · day 11 · resources: —
  - message: Your work Lord Falorel has been excellent for honing your skills. Not since the days in e…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `valley_of_the_dragon_lords:global:4`
  - **Smoke on the Horizon** · briefing · day 18 · resources: —
  - message: The smell of smoke in the morning wind leads you to suspect that this lake of fire you se…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### A Thief in the Night (`a_thief_in_the_night`)

Source: `Gelu.h3c` block 4 · H3M v28 · 7 events · sha256 `b082a4c8cc1d…` · LOD `H3bitmap.lod`

- [ ] `a_thief_in_the_night:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: Now the time has come to obtain the Elixir of Life's final component, the Vial of Lifeblo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_thief_in_the_night:global:2`
  - **Vokial** · briefing · day 5 · resources: —
  - message: Vokial is a powerful vampire lord and will be well defended. Take great care when you inv…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_thief_in_the_night:global:5`
  - **Beware the Guild of Cutthroats** · briefing · day 8 · resources: —
  - message: Be wary of the Thieves Guild, for they are treacherous and cunning. Make certain you have…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_thief_in_the_night:global:1`
  - **Words of Encouragement** · briefing · day 11 · resources: +2500 gold
  - message: You have served me well thus far, Gelu. I, Lord Falorel, am pleased with your service and…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `a_thief_in_the_night:global:3`
  - **The Titans Gladius** · briefing · day 15 · resources: —
  - message: Rumor has it the sword of a Titan can be found guarded by Black Dragons living in a valle…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_thief_in_the_night:global:4`
  - **The Sentinel Shield** · briefing · day 18 · resources: —
  - message: A passerby tells tales of a glimmering shield he saw once somewhere in the Southeast. He …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `a_thief_in_the_night:global:6`
  - **Elixir** · briefing · day 24 · resources: —
  - message: Once you have the Vial of Lifeblood, combine it with the Ring of Life and the Ring of Vit…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

## Unholy Alliance (`sod` / `Final.h3c`)

### Harvest (`harvest`)

Source: `Final.h3c` block 1 · H3M v28 · 7 events · sha256 `294b80b4c481…` · LOD `H3bitmap.lod`

- [ ] `harvest:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: A few days ago you heard a rumor about the Necromancers invading Erathia. Since you aren'…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `harvest:global:1`
  - **Enemy stuff** · timed resource · day 1, every 7d · resources: +15 wood, +10 mercury, +15 ore, +10000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `harvest:map:0:11:66`
  - **map_event:0:11:66** · unguarded map · visit @ `0:11:66` · resources: —
  - message: As you approach the town you notice that the people are in rather good spirits. Wondering…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `harvest:map:0:22:17`
  - **map_event:0:22:17** · unguarded map · visit @ `0:22:17` · resources: —
  - message: Standing on a small cliff and looking out, you see that the road splits further up. Beyon…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `harvest:map:0:32:58`
  - **map_event:0:32:58** · unguarded map · visit @ `0:32:58` · resources: —
  - message: You quickly call your army to a stop. As you stand on the edge of the Necromancer's newly…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `harvest:map:0:34:28`
  - **map_event:0:34:28** · unguarded map · visit @ `0:34:28` · resources: —
  - message: Traveling down the road, you stop suddenly as you come across a Necromancer's castle. It …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `harvest:map:0:37:8`
  - **map_event:0:37:8** · unguarded map · visit @ `0:37:8` · resources: —
  - message: Feeling the horses need a rest, you pull over to the edge of the road and call a halt for…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Gathering the Legion (`gathering_the_legion`)

Source: `Final.h3c` block 2 · H3M v28 · 9 events · sha256 `7ff958412cbd…` · LOD `H3bitmap.lod`

- [ ] `gathering_the_legion:global:0`
  - **Hartferd day 1.** · briefing · day 1 · resources: —
  - message: The days and weeks searching for Sandro after his betrayal have proven fruitless. No one …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `gathering_the_legion:global:1`
  - **Warring Knights** · briefing · day 2 · resources: —
  - message: As you start out on your quest to find the Stolen Head and other pieces of Legion, a scou…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `gathering_the_legion:global:2`
  - **Scout report.** · briefing · day 7 · resources: —
  - message: Scouts report rumors that Tyranell (the knight who stole the Head of Legion) is hiding ou…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `gathering_the_legion:map:0:8:60`
  - **map_event:0:8:60** · unguarded map · visit @ `0:8:60` · resources: +4294967266 gold
  - message: You find an old retainer of Tyranell's, discharged from the knight's service and sitting …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `gathering_the_legion:town:0:59:11:event:0`
  - **Hartferd builders** · town timed · day 7 @ `town:0:59:11:event:0` (Hartferd) · resources: —
  - message: The inhabitants of Hartferd are building up their town to help you.
  - notes: town=Hartferd | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `gathering_the_legion:town:0:59:11:event:1`
  - **Build 2.** · town timed · day 14 @ `town:0:59:11:event:1` (Hartferd) · resources: —
  - message: The inhabitants of Hartferd are building up their town to help you.
  - notes: town=Hartferd | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `gathering_the_legion:town:0:59:11:event:2`
  - **Building 3.** · town timed · day 21 @ `town:0:59:11:event:2` (Hartferd) · resources: —
  - message: The inhabitants of Hartferd are building up their town to help you.
  - notes: town=Hartferd | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `gathering_the_legion:town:0:59:11:event:3`
  - **Building 4.** · town timed · day 28 @ `town:0:59:11:event:3` (Hartferd) · resources: —
  - message: The inhabitants of Hartferd are building up their town to help you.
  - notes: town=Hartferd | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `gathering_the_legion:town:0:59:11:event:4`
  - **Building 5.** · town timed · day 35 @ `town:0:59:11:event:4` (Hartferd) · resources: —
  - message: The inhabitants of Hartferd are building up their town to help you.
  - notes: town=Hartferd | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Search for a Killer (`search_for_a_killer`)

Source: `Final.h3c` block 3 · H3M v28 · 13 events · sha256 `5ceabaefe08d…` · LOD `H3bitmap.lod`

- [ ] `search_for_a_killer:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: Upon arriving at Willowglen this morning, you discover that Lord Falorel has been murdere…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:11`
  - **Dark Realizations** · briefing · day 2 · resources: —
  - message: The death of Lord Falorel and discovery that he really was a Vampire calls into question …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:1`
  - **Scout Report** · briefing · day 3 · resources: —
  - message: A runner arrives bringing news that necromancer forces overran the town of Soledare. Skel…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:3`
  - **The Region** · briefing · day 4 · resources: —
  - message: The waters of the Shandar River separate this area of the border between AvLee and Deyja.…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:9`
  - **The Real Lord Falorel** · briefing · day 6 · resources: —
  - message: Your soothsayers discovered that Lord Falorel's real name was Vayarad, and he was a vampi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:4`
  - **Dark Tides** · briefing · day 8 · resources: —
  - message: By herding villagers into pens, the Necromancers can easily slaughter and raise them in m…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:2`
  - **News of the Druidess** · briefing · day 11 · resources: —
  - message: Rumor has it a Druid from a far off land is having troubles with the Necromancers herself…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:5`
  - **News from the Underground** · briefing · day 14 · resources: —
  - message: There is an extensive underground network of tunnels in this region that goes far below t…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:8`
  - **Chaos Reigns Supreme** · briefing · day 18 · resources: —
  - message: A report from your Erathian commanders arrives: "Now that the news of Lord Falorel's demi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:12`
  - **Letter from Gem** · briefing · day 22 · resources: —
  - message: A letter arrived today from a Druid named Gem. She wants to meet with you when you are fi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:6`
  - **A Destiny Forged in Blood** · briefing · day 25 · resources: —
  - message: Your scouts report they have seen these skeleton transformation rituals, and they are gri…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:10`
  - **A Decision** · briefing · day 30 · resources: —
  - message: These killing fields must be shut down. The lords in AvLee and your superiors in Erathia …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `search_for_a_killer:global:7`
  - **The Name of the Enemy** · briefing · day 36 · resources: —
  - message: Your interrogation of some prisoners brought before you leads to a name: Sandro. Apparent…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

### Final Peace (`final_peace`)

Source: `Final.h3c` block 4 · H3M v28 · 19 events · sha256 `5e3391412186…` · LOD `H3bitmap.lod`

- [ ] `final_peace:global:0`
  - **Intro** · briefing · day 1 · resources: —
  - message: Lord Fayette has been turned into a Death Knight while on a secret mission into Deyja. Ap…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `final_peace:global:1`
  - **Plans** · briefing · day 3 · resources: —
  - message: We located two rampart castles. Clancy and I will each base out of one, build our forces …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `final_peace:global:8`
  - **Gem's Eyes** · briefing · day 6 · resources: —
  - message: I over heard some of my troops talking about my eyes. It was amusing. Apparently they thi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `final_peace:global:2`
  - **Lady Fayette Message** · briefing · day 11 · resources: —
  - message: I received a message from Lord Fayette's wife today. She told me she had discovered the p…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `final_peace:global:3`
  - **Dead Border Lord** · briefing · day 19 · resources: —
  - message: Even in Deyja there are a few residents who are not undead. My scouts made contact with s…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `final_peace:global:4`
  - **Plot** · briefing · day 27 · resources: —
  - message: It is becoming increasingly obvious to me that Lord Fayette's death was a result of some …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `final_peace:global:5`
  - **Plot (cont)** · briefing · day 27 · resources: —
  - message: That would make sense except that the Deyjan Border Lord across from them was also killed…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `final_peace:global:6`
  - **Message from Clancy** · briefing · day 35 · resources: —
  - message: I sent a message to Clancy last week asking him what he knew about Gelu. I received his r…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `final_peace:global:7`
  - **Letter to Gelu** · briefing · day 39 · resources: —
  - message: I'm sending a letter to Gelu telling him I think Falorel's and Fayette's deaths are relat…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `final_peace:town:0:28:55:event:2`
  - **Build Townhall** · town timed · day 2 @ `town:0:28:55:event:2` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `final_peace:town:0:53:59:event:2`
  - **Build Townhall** · town timed · day 2 @ `town:0:53:59:event:2` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `final_peace:town:1:5:33:event:2`
  - **Build Townhall** · town timed · day 2 @ `town:1:5:33:event:2` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `final_peace:town:0:17:38:event:0`
  - **Extra income** · town timed · day 21, every 1d @ `town:0:17:38:event:0` (town) · resources: +1500 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `final_peace:town:0:28:55:event:1`
  - **Additional Income** · town timed · day 21, every 1d @ `town:0:28:55:event:1` (town) · resources: +3000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `final_peace:town:0:53:59:event:1`
  - **Additional Income** · town timed · day 21, every 1d @ `town:0:53:59:event:1` (town) · resources: +3000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `final_peace:town:0:28:55:event:0`
  - **Gold** · town timed · day 27 @ `town:0:28:55:event:0` (town) · resources: +5000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `final_peace:town:0:53:59:event:0`
  - **Gold** · town timed · day 27 @ `town:0:53:59:event:0` (town) · resources: +5000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `final_peace:town:1:5:33:event:0`
  - **Gold** · town timed · day 27 @ `town:1:5:33:event:0` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `final_peace:town:1:5:33:event:1`
  - **Additional Income** · town timed · day 28, every 1d @ `town:1:5:33:event:1` (town) · resources: +2000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Secrets Revealed (`secrets_revealed`)

Source: `Final.h3c` block 5 · H3M v28 · 18 events · sha256 `2685994493c4…` · LOD `H3bitmap.lod`

- [ ] `secrets_revealed:global:0`
  - **Computer Stuff for first day** · timed resource · day 1, every 14d · resources: +10 wood, +5 mercury, +10 ore, +5 sulfur, +10 crystal, +5 gems, +10000 gold
  - message: Here
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `secrets_revealed:global:1`
  - **Intro** · briefing · day 1 · resources: —
  - message: It took me a little while to find Crag Hack and convince him to join up with me. Now he i…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `secrets_revealed:global:3`
  - **Shortly after** · briefing · day 7 · resources: —
  - message: Shortly after you and Crag Hack joined up, you came across a section of Erathia completel…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `secrets_revealed:global:5`
  - **Scouts** · briefing · day 12 · resources: —
  - message: The cities are coming along nicely. It's going slower than you would like, but for some r…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `secrets_revealed:global:4`
  - **Strong Forces** · briefing · day 20 · resources: —
  - message: Looking down at the scout's report, you realize the Necromancer forces are a lot stronger…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `secrets_revealed:global:6`
  - **Crag's Reply** · briefing · day 25 · resources: —
  - message: Laughing to yourself, you come to the realization you were crazy to even think about join…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `secrets_revealed:global:7`
  - **Meeting** · briefing · day 29 · resources: —
  - message: Well, I am almost ready. I think it's about time to set up a meeting with Crag Hack to di…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `secrets_revealed:global:8`
  - **History** · briefing · day 33 · resources: —
  - message: Crag Hack showed up today, and he was eager to discuss exactly how we were going to crush…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `secrets_revealed:global:2`
  - **Two Rangers** · briefing · day 39 · resources: —
  - message: Something promising reached your ears last night while you prepared for sleep. It seems y…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `secrets_revealed:global:9`
  - **Gem and Gelu** · briefing · day 46 · resources: —
  - message: A messenger arrived shortly ago informing me that Gem and Gelu want to meet in Bragden, w…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `secrets_revealed:map:0:27:21`
  - **map_event:0:27:21** · unguarded map · visit @ `0:27:21` · resources: —
  - message: Just as the sun hits its peak, you notice a glint in the side of the road. Not knowing wh…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `secrets_revealed:map:0:27:27`
  - **map_event:0:27:27** · unguarded map · visit @ `0:27:27` · resources: +50000 gold
  - message: After several hours of searching you finally found the spot where the map indicated burie…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `secrets_revealed:map:0:27:29`
  - **map_event:0:27:29** · unguarded map · visit @ `0:27:29` · resources: +50000 gold
  - message: Pointing to the spot where your men are to start digging, you begin to wonder why anyone …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `secrets_revealed:map:0:28:31`
  - **map_event:0:28:31** · unguarded map · visit @ `0:28:31` · resources: +50000 gold
  - message: You look at the ground, then at your map. This was definitely the hardest one to find. Ma…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `secrets_revealed:map:0:47:2`
  - **map_event:0:47:2** · unguarded map · visit @ `0:47:2` · resources: —
  - message: As you cross the rugged terrain you come across a man lying on the side of the pass with …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `secrets_revealed:map:0:47:48`
  - **map_event:0:47:48** · unguarded map · visit @ `0:47:48` · resources: —
  - message: You had sent out two scouts to check out the town's fortifications. Only one returned, bu…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `secrets_revealed:town:0:15:5:event:0`
  - **More Creatures** · town timed · day 17 @ `town:0:15:5:event:0` (town) · resources: —
  - message: Some loyal troops have finally arrived to help you whip those Necromancers!
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `secrets_revealed:town:0:56:5:event:0`
  - **Creatures** · town timed · day 17 @ `town:0:56:5:event:0` (town) · resources: —
  - message: Recruits have come in and are willing to fight for you.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Agents of Vengeance (`agents_of_vengeance`)

Source: `Final.h3c` block 6 · H3M v28 · 23 events · sha256 `faf206ab93e5…` · LOD `H3bitmap.lod`

- [ ] `agents_of_vengeance:global:0`
  - **Intro Gelu** · briefing · day 1 · resources: —
  - message: Gelu: After learning that Sandro was behind the plot to kill Lord Falorel, I did some mor…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `agents_of_vengeance:global:1`
  - **Intro Gem** · briefing · day 1 · resources: —
  - message: Gem: The doll got to me. It looked just like the one my sister had right before she died.…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `agents_of_vengeance:global:2`
  - **Letter Ethric to Gem** · briefing · day 9 · resources: —
  - message: Gem: I received a message from Ethric today. Ethric said it had been decades Sandro was h…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `agents_of_vengeance:global:3`
  - **Message Gem to Gelu** · briefing · day 12 · resources: —
  - message: Gelu: I received a message from Gem today. She had found out Sandro is a Necromancer. She…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `agents_of_vengeance:global:4`
  - **Scout Report Barbarians** · briefing · day 21 · resources: —
  - message: Gelu: My scouts encountered some Erathian irregulars today. They were part of a militia u…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `agents_of_vengeance:global:5`
  - **Gem to Yog** · briefing · day 25 · resources: —
  - message: Gem: Today I received word from Gelu about a pair of Barbarians attacking Deyja from the …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `agents_of_vengeance:global:6`
  - **Gem to Yog (cont)** · briefing · day 25 · resources: —
  - message: To express their displeasure with Sandro, the Barbarians decided to invade Deyja, but Yog…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `agents_of_vengeance:town:0:15:37:event:3`
  - **Build Townhall** · town timed · day 2 @ `town:0:15:37:event:3` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:38:67:event:3`
  - **Build Townhall** · town timed · day 2 @ `town:0:38:67:event:3` (Crypthome) · resources: —
  - message: (no message)
  - notes: town=Crypthome | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:63:35:event:3`
  - **Build Townhall** · town timed · day 2 @ `town:0:63:35:event:3` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:38:67:event:4`
  - **Build Citadel** · town timed · day 4 @ `town:0:38:67:event:4` (Crypthome) · resources: —
  - message: (no message)
  - notes: town=Crypthome | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:15:37:event:0`
  - **Extra Income** · town timed · day 17, every 1d @ `town:0:15:37:event:0` (town) · resources: +2000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:15:37:event:1`
  - **Extra Critters** · town timed · day 17, every 7d @ `town:0:15:37:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:63:35:event:0`
  - **Extra Income** · town timed · day 17, every 1d @ `town:0:63:35:event:0` (town) · resources: +1500 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:63:35:event:1`
  - **Extra Critters** · town timed · day 17, every 7d @ `town:0:63:35:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:15:37:event:2`
  - **Bonus Income** · town timed · day 18 @ `town:0:15:37:event:2` (town) · resources: +5000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:63:35:event:2`
  - **Bonus Income** · town timed · day 18 @ `town:0:63:35:event:2` (town) · resources: +5000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:38:67:event:0`
  - **Extra Income** · town timed · day 21, every 1d @ `town:0:38:67:event:0` (Crypthome) · resources: +4000 gold
  - message: (no message)
  - notes: town=Crypthome | blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:38:51:event:0`
  - **Extra Income** · town timed · day 24, every 1d @ `town:0:38:51:event:0` (town) · resources: +4000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:38:51:event:1`
  - **Extra Critters** · town timed · day 24, every 7d @ `town:0:38:51:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:38:67:event:1`
  - **Extra Critters** · town timed · day 24, every 7d @ `town:0:38:67:event:1` (Crypthome) · resources: —
  - message: (no message)
  - notes: town=Crypthome | blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:38:51:event:2`
  - **Bonus Income** · town timed · day 28 @ `town:0:38:51:event:2` (town) · resources: +5000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `agents_of_vengeance:town:0:38:67:event:2`
  - **Bonus Income** · town timed · day 28 @ `town:0:38:67:event:2` (Crypthome) · resources: +5000 gold
  - message: (no message)
  - notes: town=Crypthome | blockers: audience_encoder_unproven; town_event_backend_unproven; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Wrath of Sandro (`wrath_of_sandro`)

Source: `Final.h3c` block 7 · H3M v28 · 14 events · sha256 `4f78bcb83024…` · LOD `H3bitmap.lod`

- [ ] `wrath_of_sandro:global:0`
  - **Day One** · briefing · day 1 · resources: —
  - message: Heroic deeds from some AvLee Rangers and a few Barbarians working out of Erathia wiped ou…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `wrath_of_sandro:global:1`
  - **Day 4** · briefing · day 4 · resources: —
  - message: Your spies have sent messages back, and the news is not good. The two groups are allied, …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `wrath_of_sandro:global:2`
  - **Day 9** · briefing · day 9 · resources: —
  - message: More information has been smuggled out, and you almost laugh when you hear the news. Crag…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `wrath_of_sandro:global:3`
  - **Day 12** · briefing · day 12 · resources: —
  - message: Another old 'friend' of yours is now opposing you. Gem, the lady Druid, has taken up arms…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `wrath_of_sandro:global:4`
  - **Day 16** · briefing · day 16 · resources: —
  - message: A new individual is directing the brute force of Crag Hack. His name is Yog. Either your …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `wrath_of_sandro:global:5`
  - **Day 19** · briefing · day 19 · resources: —
  - message: Your source in the Ranger's camp has reported back with information about the fourth of y…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `wrath_of_sandro:global:6`
  - **Day 23** · briefing · day 23 · resources: —
  - message: The nights in the library paid off. You discovered what the Angelic Alliance is. It is a …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `wrath_of_sandro:global:7`
  - **Day 26** · briefing · day 26 · resources: —
  - message: It has become clear you will drive these enemies out of Deyja but will be unable to catch…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `wrath_of_sandro:map:0:25:6`
  - **map_event:0:25:6** · guarded map · visit @ `0:25:6` · resources: —
  - message: Something told you this was too good to be true.
  - notes: guards: type65x189 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `wrath_of_sandro:town:0:32:7:event:0`
  - **resources** · town timed · day 1, every 1d @ `town:0:32:7:event:0` (town) · resources: +4 wood, +2 mercury, +4 ore, +2 sulfur, +2 crystal, +2 gems, +3000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `wrath_of_sandro:town:0:4:13:event:0`
  - **resources** · town timed · day 1, every 2d @ `town:0:4:13:event:0` (town) · resources: +4 wood, +2 mercury, +4 ore, +2 sulfur, +2 crystal, +2 gems, +2000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `wrath_of_sandro:town:1:17:16:event:0`
  - **resources** · town timed · day 1, every 1d @ `town:1:17:16:event:0` (town) · resources: +4 wood, +2 mercury, +4 ore, +2 sulfur, +2 crystal, +2 gems, +2000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `wrath_of_sandro:town:0:4:13:event:1`
  - **monsters** · town timed · day 10, every 7d @ `town:0:4:13:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `wrath_of_sandro:town:0:32:7:event:1`
  - **Creatures** · town timed · day 11, every 7d @ `town:0:32:7:event:1` (town) · resources: —
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Invasion (`invasion`)

Source: `Final.h3c` block 8 · H3M v28 · 27 events · sha256 `0a138c1bff80…` · LOD `H3bitmap.lod`

- [ ] `invasion:global:0`
  - **Day 1** · briefing · day 1 · resources: —
  - message: Removing the AvLee, Erathia, and Krewlod troops from Deyja was easier than you thought. Y…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `invasion:global:6`
  - **Day 4** · briefing · day 4 · resources: —
  - message: Bad news has arrived in a package of dust and bones. While checking out the AvLee territo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `invasion:global:1`
  - **Day 10** · briefing · day 10 · resources: —
  - message: Finneas sent you a message; his tone was pushy and bossy as if he was in control of the s…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `invasion:global:2`
  - **Day 17** · briefing · day 17 · resources: —
  - message: It was a pleasure to appear in the midst of court and rattle Finneas' bones. He was quite…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `invasion:global:7`
  - **Day 20** · briefing · day 20 · resources: —
  - message: The Captain of the Forest Guard is Caleb, an elf of surpassing skill. If you were to kill…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `invasion:global:3`
  - **Day 25** · briefing · day 25 · resources: —
  - message: Spies have confirmed your fears. Yog the Barbarian has encouraged his comrades to search …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `invasion:global:8`
  - **Day 30** · briefing · day 30 · resources: —
  - message: You suspect Caleb is located near Forestdale, an AvLee town located to the north and east…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `invasion:global:4`
  - **Day 39** · briefing · day 39 · resources: —
  - message: The troops for AvLee have arrived and are going to create a problem. It would be wise to …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `invasion:global:5`
  - **Day 53** · briefing · day 53 · resources: —
  - message: You may not win if this keeps up. Troops from Erathia have arrived, and they are already …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `invasion:map:0:12:56`
  - **map_event:0:12:56** · guarded map · visit @ `0:12:56` · resources: —
  - message: With hopes of gaining more sulfur, you push aside the foliage, but find only Forest Guard…
  - notes: guards: type18x5, type18x5, type18x5, type19x10, type18x5, type18x5, type18x5 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `invasion:map:0:13:18`
  - **map_event:0:13:18** · guarded map · visit @ `0:13:18` · resources: —
  - message: While moving your troops through the area, the slightest noise catches your attention. It…
  - notes: guards: type18x5, type18x5, type18x5, type19x10, type18x5, type18x5, type18x5 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `invasion:map:0:27:2`
  - **map_event:0:27:2** · guarded map · visit @ `0:27:2` · resources: —
  - message: Rushing for the gold this mill has to offer, you fail to notice the quiet sneaking of Elv…
  - notes: guards: type18x10, type18x10, type18x10, type19x20, type18x10, type18x10, type18x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `invasion:map:0:32:57`
  - **map_event:0:32:57** · guarded map · visit @ `0:32:57` · resources: —
  - message: Protecting Thestlemore are a few elves, and you suspect a trap. Unable to see anyone else…
  - notes: guards: type18x5, type18x5, type18x5, type19x10, type18x5, type18x5, type18x5 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `invasion:map:0:3:8`
  - **map_event:0:3:8** · guarded map · visit @ `0:3:8` · resources: —
  - message: The few Forest Guard located here are no match for your forces. Before engaging you in ba…
  - notes: guards: type18x5, type18x5, type18x5, type19x10, type18x5, type18x5, type18x5 | removeAfterVisit=false | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `invasion:map:0:56:65`
  - **map_event:0:56:65** · guarded map · visit @ `0:56:65` · resources: —
  - message: Seeking the mercury made in the Alchemist's Lab, you ignore the possibility of enemy acti…
  - notes: guards: type18x5, type18x5, type18x5, type19x10, type18x5, type18x5, type18x5 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `invasion:map:0:5:3`
  - **map_event:0:5:3** · guarded map · visit @ `0:5:3` · resources: —
  - message: Wanting to take over production of the Ore Mine, you fail to see the Forest Guard quietly…
  - notes: guards: type18x10, type18x10, type18x10, type19x20, type18x10, type18x10, type18x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `invasion:map:0:62:5`
  - **map_event:0:62:5** · guarded map · visit @ `0:62:5` · resources: —
  - message: After successfully getting through the garrison, you find yourself surrounded by even mor…
  - notes: non-resource: artifacts | guards: type19x15, type19x15, type19x15, type137x25, type19x15, type19x15, type19x15 | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `invasion:map:0:67:21`
  - **map_event:0:67:21** · guarded map · visit @ `0:67:21` · resources: —
  - message: The town of Silver Falls lies ahead, and as you pass through the rocky pass, it becomes q…
  - notes: guards: type18x10, type18x10, type18x10, type19x20, type18x10, type18x10, type18x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `invasion:town:0:12:44:event:0`
  - **Resources** · town timed · day 1, every 1d @ `town:0:12:44:event:0` (Radstone) · resources: +4 wood, +2 mercury, +4 ore, +2 sulfur, +2 crystal, +2 gems, +2000 gold
  - message: (no message)
  - notes: town=Radstone | blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `invasion:town:0:20:66:event:0`
  - **resources** · town timed · day 1, every 2d @ `town:0:20:66:event:0` (Crag's Place) · resources: +2 wood, +1 mercury, +2 ore, +1 sulfur, +1 crystal, +1 gems, +1 gold
  - message: (no message)
  - notes: town=Crag's Place | blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `invasion:town:0:38:4:event:1`
  - **resources** · town timed · day 1, every 1d @ `town:0:38:4:event:1` (Meadow Brook) · resources: +2 wood, +1 mercury, +2 ore, +1 sulfur, +1 crystal, +1 gems, +2000 gold
  - message: have some resources
  - notes: town=Meadow Brook | blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `invasion:town:0:14:5:event:0`
  - **Troops** · town timed · day 39 @ `town:0:14:5:event:0` (Soaring Height) · resources: +14 wood, +7 mercury, +14 ore, +7 sulfur, +7 crystal, +7 gems, +50000 gold
  - message: Here are some troops for the computer.
  - notes: town=Soaring Height | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `invasion:town:0:38:4:event:0`
  - **Troops** · town timed · day 39 @ `town:0:38:4:event:0` (Meadow Brook) · resources: +50000 gold
  - message: Here are some troops for the computer
  - notes: town=Meadow Brook | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `invasion:town:0:67:3:event:0`
  - **Troops** · town timed · day 39 @ `town:0:67:3:event:0` (Forestdale) · resources: +50000 gold
  - message: Here are some creatures for the computer.
  - notes: town=Forestdale | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `invasion:town:0:28:21:event:0`
  - **Troops** · town timed · day 53 @ `town:0:28:21:event:0` (Hudson Falls) · resources: +50000 gold
  - message: Here are some creatures for the computer.
  - notes: town=Hudson Falls | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `invasion:town:0:34:55:event:0`
  - **Troops** · town timed · day 53 @ `town:0:34:55:event:0` (Thestlemore) · resources: +50000 gold
  - message: Here are some creatures for the computer.
  - notes: town=Thestlemore | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)
- [ ] `invasion:town:0:50:60:event:0`
  - **Troops** · town timed · day 53 @ `town:0:50:60:event:0` (Worthington) · resources: +50000 gold
  - message: Here are some creatures for the computer.
  - notes: town=Worthington | blockers: audience_encoder_unproven; town_event_backend_unproven; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### To Strive, To Seek (`to_strive_to_seek`)

Source: `Final.h3c` block 9 · H3M v28 · 13 events · sha256 `a2971cdfef58…` · LOD `H3bitmap.lod`

- [ ] `to_strive_to_seek:global:0`
  - **Opening** · briefing · day 1 · resources: —
  - message: After their recent defeat, Gem and Gelu knew what must be done. They needed a weapon, som…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_strive_to_seek:global:3`
  - **The Area** · briefing · day 2 · resources: —
  - message: Across a small tributary of the Shandar River lies a region of Erathia that was a major h…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_strive_to_seek:global:1`
  - **Sandals Spotted** · briefing · day 5 · resources: —
  - message: Local farmers passing by your army have spotted the Sandals of the Saint. They tell you i…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_strive_to_seek:global:2`
  - **Celestial Necklace Spotted** · briefing · day 13 · resources: —
  - message: A scout returns to Gem and reports he has located the Celestial Necklace of Bliss near th…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_strive_to_seek:global:4`
  - **The tides have turned** · briefing · day 18 · resources: —
  - message: Though the Necromancer forces have us on the run, we will be able to force them from our …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_strive_to_seek:global:5`
  - **Worries** · briefing · day 22 · resources: —
  - message: No word from Crag or Yog has Gelu worried. He paces back and forth, fretting over the lac…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_strive_to_seek:global:7`
  - **Shades of Betrayal** · briefing · day 25 · resources: —
  - message: Scrying in her bowl, Gem often learned for certain the nature of things around her. She o…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_strive_to_seek:global:6`
  - **A runner arrives** · briefing · day 30 · resources: —
  - message: A runner arrives before Gem and presents a message. The message, from the Council of Elde…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_strive_to_seek:global:8`
  - **The Day of Smoke and Shadows** · briefing · day 33 · resources: —
  - message: A cold gray cloud descended across the land today. The fires of war burned bright as the …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_strive_to_seek:global:9`
  - **Days of Redemption** · briefing · day 40 · resources: —
  - message: Gelu sat in his tent that morning and contemplated his life. He's learned the ways of bat…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `to_strive_to_seek:map:0:27:30`
  - **map_event:0:27:30** · guarded map · visit @ `0:27:30` · resources: —
  - message: A band of refugees approaches, looking forlorn and undernourished. As you reach out to of…
  - notes: guards: type143x125 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `to_strive_to_seek:map:0:3:44`
  - **map_event:0:3:44** · unguarded map · visit @ `0:3:44` · resources: —
  - message: Sitting beside the well is an odd little woman muttering to herself. She is dressed in a …
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `to_strive_to_seek:map:0:65:38`
  - **map_event:0:65:38** · unguarded map · visit @ `0:65:38` · resources: —
  - message: A small boy lies in the road, battered and broken. He holds in his hands a small box. He …
  - notes: non-resource: artifacts | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_artifacts; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Barbarian Brothers (`barbarian_brothers`)

Source: `Final.h3c` block 10 · H3M v28 · 4 events · sha256 `d9ae114bc590…` · LOD `H3bitmap.lod`

- [ ] `barbarian_brothers:global:0`
  - **Barbarian brothers.** · briefing · day 1 · resources: —
  - message: Yog and Crag Hack discovered that three of the six artifacts that Yog thought he was rid …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `barbarian_brothers:global:1`
  - **Flood!** · briefing · day 1 · resources: —
  - message: As Yog and Hack enter the region where the Barbarian Brothers live, a flash flood strikes…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `barbarian_brothers:global:2`
  - **Reinforcements.** · briefing · day 21 · resources: —
  - message: Scouts report that the brothers are bringing in reinforcements from other parts of Krewlo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `barbarian_brothers:town:1:54:54:event:0`
  - **Barbarian brother reinforcements.** · town timed · day 21, every 21d @ `town:1:54:54:event:0` (town) · resources: —
  - message: Reinforcements arrive for the BB's.
  - notes: blockers: audience_encoder_unproven; town_event_backend_unproven; repeating_schedule_requires_native_or_direct_state_backend; backend_not_runtime_proven
  - backend: town_ownership_aware_recurrence (selected_unproven)

### Union (`union`)

Source: `Final.h3c` block 11 · H3M v28 · 24 events · sha256 `2e218a7fd893…` · LOD `H3bitmap.lod`

- [ ] `union:global:0`
  - **Day 1** · briefing · day 1 · resources: —
  - message: We are separated from the others by the inlet. Both groups must stabilize their foothold …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `union:global:12`
  - **Computer Stuff** · timed resource · day 1, every 7d · resources: +50 wood, +25 mercury, +50 ore, +25 sulfur, +25 crystal, +25 gems, +50000 gold
  - message: (no message)
  - notes: blockers: audience_encoder_unproven; repeating_schedule_requires_native_or_direct_state_backend; empty_message_must_not_drop_effects; backend_not_runtime_proven
  - backend: repeating_resource_native_or_direct_state (selected_unproven)
- [ ] `union:global:1`
  - **Day 5** · briefing · day 5 · resources: —
  - message: Research on combination artifacts had continued after the four of you left to search for …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `union:global:2`
  - **Day 10** · briefing · day 10 · resources: -10000 gold
  - message: Disaster has struck. Thieves entered the castle late at night, killed the guards and stol…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `union:global:8`
  - **Day 13** · briefing · day 13 · resources: —
  - message: Strange things have been sighted. Near the small town of Gourney the ground seems to be o…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `union:global:3`
  - **Day 17** · briefing · day 17 · resources: —
  - message: Stumbling into camp one night, a poor man collapses onto the ground in front of Gem. She …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `union:global:11`
  - **Day 20** · briefing · day 20 · resources: -50 wood, -10 gems, -20000 gold
  - message: This is just not your week. A messenger who was traveling between all of the castles, try…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `union:global:4`
  - **Day 24** · briefing · day 24 · resources: —
  - message: The Forest Guard scouts return, each of them reporting something of interest. Sandro's mo…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `union:global:5`
  - **Day 31** · briefing · day 31 · resources: -15000 gold
  - message: Crag came out of his tent swearing up a storm. The entire camp was infested with fleas an…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `union:global:6`
  - **Day 38** · briefing · day 38 · resources: -30 ore, -10000 gold
  - message: A raiding party swarmed over the camps and surprised everyone there. Barely able to escap…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `union:global:9`
  - **Day 41** · briefing · day 41 · resources: —
  - message: A Behemoth, one of Yog's scouts, returns looking ragged and filthy yet also very happy an…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `union:global:7`
  - **Day 45** · briefing · day 45 · resources: -5000 gold
  - message: Knowing the bad luck you have been faced with recently, a seer has been brought on board …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `union:global:10`
  - **Day 48** · briefing · day 48 · resources: —
  - message: A message arrived for Gelu. He quickly read it and then flew into a rage, screaming unint…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `union:map:0:103:76`
  - **map_event:0:103:76** · guarded map · visit @ `0:103:76` · resources: —
  - message: You weren't on guard enough and are being attacked by Fire Elementals!
  - notes: guards: type114x20, type114x20, type114x20, type114x20, type114x20 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `union:map:0:105:87`
  - **map_event:0:105:87** · guarded map · visit @ `0:105:87` · resources: —
  - message: This entire land seems to be on fire, as if the elementals of fire have taken a particula…
  - notes: guards: type114x10, type114x10, type114x10, type114x10, type114x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `union:map:0:43:91`
  - **map_event:0:43:91** · guarded map · visit @ `0:43:91` · resources: —
  - message: Out of the clouds streaking towards you are the Air Elementals, and they seem to have bro…
  - notes: guards: type112x10, type112x10, type112x10, type127x20, type112x10, type112x10, type112x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `union:map:0:44:5`
  - **map_event:0:44:5** · unguarded map · visit @ `0:44:5` · resources: —
  - message: Passing through this idle valley you are admiring the scenery. It is beautiful here, with…
  - notes: non-resource: morale | removeAfterVisit=true | blockers: audience_encoder_unproven; unsupported_reward_morale; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `union:map:0:62:99`
  - **map_event:0:62:99** · unguarded map · visit @ `0:62:99` · resources: —
  - message: This area is definitely at a higher elevation than the others. It may be wise to keep an …
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `union:map:0:85:80`
  - **map_event:0:85:80** · guarded map · visit @ `0:85:80` · resources: —
  - message: This entire land seems to be on fire, as if the elementals of fire have taken a particula…
  - notes: guards: type114x10, type114x10, type114x10, type114x10, type114x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `union:map:0:88:77`
  - **map_event:0:88:77** · guarded map · visit @ `0:88:77` · resources: —
  - message: This entire land seems to be on fire, as if the elementals of fire have taken a particula…
  - notes: guards: type114x10, type114x10, type114x10, type114x10, type114x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `union:map:0:89:46`
  - **map_event:0:89:46** · guarded map · visit @ `0:89:46` · resources: —
  - message: While traveling through the barren lands, you realize this would be a place Earth Element…
  - notes: guards: type113x10, type113x10, type113x10, type113x10, type113x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `union:map:0:89:8`
  - **map_event:0:89:8** · guarded map · visit @ `0:89:8` · resources: —
  - message: While traveling through these beautiful pools, you are ambushed by Water Elementals who v…
  - notes: guards: type115x10, type115x10, type115x10, type115x10, type115x10 | removeAfterVisit=true | blockers: audience_encoder_unproven; guarded_exact_squad_host_contract_unproven; guarded_pre_battle_dialog_phase_unproven; backend_not_runtime_proven
  - backend: guarded_map_event_exact_squad (selected_unproven)
- [ ] `union:map:0:91:78`
  - **map_event:0:91:78** · unguarded map · visit @ `0:91:78` · resources: —
  - message: With all of the Fire Elementals in the area, maybe you should be more careful and avoid g…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)
- [ ] `union:map:0:99:83`
  - **map_event:0:99:83** · unguarded map · visit @ `0:99:83` · resources: —
  - message: With all of the Fire Elementals in the area, maybe you should be more careful and avoid g…
  - notes: removeAfterVisit=true | blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: unguarded_map_event (selected_unproven)

### Fall of Sandro (`fall_of_sandro`)

Source: `Final.h3c` block 12 · H3M v28 · 18 events · sha256 `11a7924c4b70…` · LOD `H3bitmap.lod`

- [ ] `fall_of_sandro:global:0`
  - **Day 1** · briefing · day 1 · resources: —
  - message: We are deep within the Necromancer's territory. Most everything is dying here; only a few…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:2`
  - **Teleporters** · briefing · day 6 · resources: —
  - message: Reports of a teleporter to the underground have surfaced. It is rumored there are undergr…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:1`
  - **Mines** · briefing · day 12 · resources: —
  - message: We have quickly returned sawmills and ore mines to production. With four castles, our res…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:3`
  - **Elixir of Life** · briefing · day 20 · resources: —
  - message: One of the artifacts researched was the Elixir of Life. Gelu had gathered its components …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:4`
  - **Ghost Dragons** · briefing · day 26 · resources: —
  - message: A mystic wanders into camp, begging for food. Crag Hack demands that the mystic earn his …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:13`
  - **Plague** · briefing · day 32 · resources: -10000 gold
  - message: Walled safely within your castle, the forces of undead are unable to break through. For q…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `fall_of_sandro:global:11`
  - **Defeat Sandro** · briefing · day 35 · resources: —
  - message: The Forest Guard has reported back with information you need. Sandro is walled in behind …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:10`
  - **Nomads** · briefing · day 38 · resources: —
  - message: Reports of nomads moving quickly across the deserts reach your ears. It is possible to hi…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:12`
  - **Boots of Levitation** · briefing · day 42 · resources: —
  - message: One of your agents holds the Boots of Levitation, but you must bring 50 hobgoblins to kno…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:7`
  - **Necromancers have bribed the elementals** · briefing · day 49 · resources: —
  - message: A large plume of smoke had been seen rising out of the desert like a hideous black snake.…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:8`
  - **Tome of Fire** · briefing · day 56 · resources: -500 gold
  - message: A prophetic woman enters camp and declares she has important information for Gelu. He agr…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `fall_of_sandro:global:9`
  - **Tome of Water** · briefing · day 63 · resources: —
  - message: An old man comes stumbling into town with his entire family in tow. The group of fifty or…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:6`
  - **Raid** · briefing · day 70 · resources: -10 ore, -10 gems, -5000 gold
  - message: Early in the morning, before the sun hit the flagstones, the warning bell sounded. Hoping…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: one_shot_timed_resource (selected_unproven)
- [ ] `fall_of_sandro:global:5`
  - **Trade** · briefing · day 77 · resources: —
  - message: One of the scouts reports that some people in the underground caverns may be looking for …
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:17`
  - **Four weeks** · briefing · day 84 · resources: —
  - message: There is but a month left before Sandro's troops get here. The scouts have spotted them f…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:16`
  - **Three weeks** · briefing · day 91 · resources: —
  - message: Little time is left, and you should not waste it. Sandro's troops were spotted closer and…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:15`
  - **Two weeks** · briefing · day 98 · resources: —
  - message: In just two short weeks Sandro will have all the reinforcements he needs, and you will be…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)
- [ ] `fall_of_sandro:global:14`
  - **One week** · briefing · day 105 · resources: —
  - message: In just a week you will have run out of time. The troops Sandro needs are on their way. I…
  - notes: blockers: audience_encoder_unproven; backend_not_runtime_proven
  - backend: briefing_start_turn_dialog (selected_unproven)

