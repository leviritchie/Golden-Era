# Cove: unit ability variety pass (draft, 2026-11-21)

Trade axis: Boarding (striker: Speed, Initiative and melee riders that pin a target and rush it) versus Broadside (ward: sturdier bodies that spend Focus on shots, or pure gun lines). The new cards push boarders toward grabbing and repositioning, and gunners toward shaping the line from range.

Cross-check with my other two factions: Cove's push, pull and teleport tricks are not used in Conflux or Factory. The Corsair dive is the only `dive` across the three files, because Factory's Skyfall is removed.

## 1. Duplicates found

| Ability | Units | Why it is a duplicate or generic |
|---|---|---|
| Boarding / Swoop / Tidal Charge / Serpent Rush (+5 or 10% per hex) | Crew Mate, Seaman, Crew alt, Stormbird, Ayssid, Stormbird alt, Nix alt, Haspid | Flat damage per hex (`gallop`) on four lines. |
| Slick Scales / Evasive / Storm Feathers / Sea Legs / Abyssal Hide | Serpent line, Ayssid, Stormbird alt, Corsair, Serpent alt | Generic resists. |
| Calm Seas (adjacent allies -15% Ranged) | Stormbird alt | Generic resist aura; Factory's Sentinel Field is the same card. |
| Brawler, Alert (counterattack twice) | Seaman, Nix Warrior | Generic second counterattack. |
| Duelist (no melee penalty) | Pirate line and Sea Witch line | Functionally identical passive on two lines. It stays as the Pirate line's identity. |
| Undertow, Grappling Hook, Harpoon Throw (-2 Speed) | Oceanid, Seaman, Nix Warrior | Three "hit and slow by 2" cards. |
| Cutlass Rush, Crushing Coils, Abyssal Hook | Corsair, Haspid, Nix | Strike for +x%, no counterattack. |
| Water Jet, Pistol Shot, Thunderbolt, Focused Ray, Venom Spit | Nymph alt, Crew alt, Stormbird alt, Sorceress, Serpent alt | Five "shoot for x%" actives. Pistol Shot stays: a melee crew stack with one shot is its whole identity. |
| Guillotine Shot | Sea Dog | The same pure-damage % max HP execute as Castle's fixed Glaivier Guillotine. |
| Whirlpool (-2 Speed, -2 Initiative) | Serpent alt | A plain stat debuff with a name that promises a pull. |

## 2. Proposed kits

| Unit | Card | P / A | Card text | How it is built | Replaces |
|---|---|---|---|---|---|
| Nymph | Blink, Ice Immunity | P | kept | `card`, `card` | kept |
| Oceanid | Blink, Ice Immunity | P | kept | as now | kept |
| | Riptide | A 1F / CD2, free | Moves a friendly creature to a free hex within 3 hexes of it. Does not end this creature's turn. | NEW keyword `reposition`: clone of `arbitrator` ability 0 "Command: Reposition" (verified: teleport an ally to a hex within N of its position), range 3 | Undertow |
| Nymph alt | Blink, Ice Immunity | P | kept | as now | kept |
| | Healing Water | A 1F | kept | `keep_ability` | kept |
| | (removed) | | | | Water Jet |
| Crew Mate | Scrappers | P | If the target counterattacks, this creature attacks it again after the counterattack. | NEW keyword `scrappers`: unit passive `{"data":{"sequenceEffect":"add_attack_after_counter_melee"}}` (verified on vanilla `locust` and `h3_swordsman_upg`) | Boarding |
| Seaman | Scrappers | P | (as Crew Mate) | `scrappers` | Boarding |
| | Grappling Hook | A 1F / CD2, free | Pulls an enemy creature up to 3 hexes away into the hex next to this creature. Does not end this creature's turn. | NEW keyword `pull`: clone of `giant_frog` ability 1 "Sticky Tongue" (verified: pull, `push_unit` ["true","false"], reach pattern, free). Tower's draft proposes the same keyword, so it can be shared | Grappling Hook (slow strike), Brawler |
| Crew alt (Swashbuckler) | Scrappers | P | (as Crew Mate) | `scrappers` | Boarding |
| | Gold Producer | P | kept | `card` | kept |
| | Pistol Shot | A 1F / CD1 | kept | `cove_focus_shot` mult 1.0 | kept |
| Pirate | Duelist | P | kept | `cove_duelist` | kept (line identity) |
| Corsair | Swashbuckling | P | kept | `cove_duelist` | kept |
| | Plunder | P | Melee attacks steal one positive effect from the target and give it to this creature. | NEW keyword `steal_on_hit`: target mechanic `steal_buffs` on the default melee dealer, limited to one effect (donor `angel_upg`, verified) | Sea Legs |
| | Swing Aboard | A 1F / CD2 | Leaps onto an enemy creature up to 4 hexes away, ignoring obstacles and creatures in between, and performs a Melee attack. | `dive` {range 4, mult 1.0} (lava_larva jump) | Cutlass Rush |
| Sea Dog | Duelist, Sharpshooter | P | kept | as now | kept |
| | Raking Shot | A 2F / CD2 | Performs a Ranged attack that also hits the creature directly behind the target for 50% Damage. | NEW keyword `pierce_shot`: `cove_focus_shot` with `attackPatternSid` `attack_reach_x1_x100_x50` on the shot dealer | Guillotine Shot |
| Stormbird | Gust | P | Basic attacks push the target 1 hex directly away, if that hex is free. | NEW keyword `push_on_hit`: target mechanic `push_unit_from_caster` ["false"] on the default attack (donor `minos` ability 0, verified). Castle's draft names the same keyword | Swoop |
| Ayssid | Gust | P | (as Stormbird) | `push_on_hit` | Swoop |
| | Ferocity | P | kept | `cove_ferocity` | kept |
| | Stormbird Shock | A 2F | kept | `keep_ability` | kept |
| | (removed) | | | | Evasive |
| Stormbird alt | Gust | P | (as Stormbird) | `push_on_hit` | Swoop |
| | Gale Guard | P | Its counterattacks also push the attacker 1 hex directly away, if that hex is free. | `push_on_hit` with the same mechanic on the counterattack dealer | Storm Feathers, Calm Seas |
| | (removed) | | | | Thunderbolt |
| Sea Witch | Weakening Shot | P | kept | `cove_shot_buff` | kept |
| | (removed) | | | | Duelist (now Pirate line only) |
| Sorceress | Weakening Shot, Sharpshooter | P | kept | as now | kept |
| | Becalm | A 2F / CD3 | Every ability of the target enemy creature goes on cooldown for 2 rounds. | NEW keyword `cooldown_cast`: single-enemy ranged cast with mechanic `force_unit_cd` (donors `jaw` and `sentinel` abilities, verified), 2 rounds | Focused Ray, Duelist |
| Tidecaller (Sea Witch alt) | Weakening Shot | P | kept | `cove_shot_buff` | kept |
| | Summon Fangarms | A 2F | kept | `keep_ability` | kept |
| | Rising Tide | A 2F / CD2 | kept | `rally` | kept (Factory's Stampede, the copy, is removed) |
| | (removed) | | | | Duelist |
| Nix | Attack Ignore | P | kept | `cove_attack_ignore` 30 | kept |
| | (removed) | | | | Abyssal Hook |
| Nix Warrior | Attack Ignore | P | kept | `cove_attack_ignore` 60 | kept |
| | Harpoon Watch | P | Remains on Overwatch: strikes every enemy that moves into a hex next to it, any number of times per round. | NEW keyword `overwatch`: battle-long self buff with `maxOverwatchStrikes` 999 (donor `sub_skill_formation_4_overwatch_buff`, verified; qilin and `h3_mammoth_upg_alt` show it on units) | Alert, Harpoon Throw |
| | Harpoon Break | A 2F | kept | `keep_ability` | kept |
| Nix alt | Attack Ignore | P | kept | `cove_attack_ignore` 30 | kept |
| | Run Aground | P | Deals +25% Damage to rooted enemies. | `runtime` {percent 25} (unchanged); the text drops "grappled" | kept (Tidal Charge removed) |
| | Tidebreak | A 3F | kept | `keep_ability` | kept |
| Sea Serpent | Venom | P | kept | `on_hit_buff` | kept |
| | (removed) | | | | Slick Scales |
| Haspid | Venom | P | kept | `on_hit_buff` | kept |
| | Revenge | P | kept | `runtime` {percent 100, cap 50} (unchanged) | kept |
| | Crushing Coils | A 3F / CD2 | Performs a Melee attack and roots the target until the end of the next round. Until then the target cannot counterattack anyone. | `melee_strike` mult 1.0, counter on, + NEW buff `h3_kit_cove_coiled_effect`: clone of the root buff with `disablers` ["counter_attack"] added (the layout the Conflux frozen effect uses) | Crushing Coils (+50%, no counter), Slick Scales, Serpent Rush |
| Serpent alt | Venom | P | kept | `on_hit_buff` | kept |
| | Whirlpool | A 3F / CD3 | Pulls every creature within 2 hexes of the chosen hex 1 hex toward it, then deals Damage to each enemy pulled. | NEW keyword `whirlpool`: clone of `aqualotl_upg` ability 2 (verified: pulls all stacks within 2 toward a hex, `push_unit` ["true"], `attack_rumble_x2_star_x100`) | Whirlpool (stat debuff), Venom Spit, Slick Scales, Abyssal Hide |

Kit sizes after the pass: Nymph 2 / 3 / 3, Crew 1 / 2 / 3, Pirate 1 / 3 / 3, Stormbird 1 / 3 / 2, Sea Witch 1 / 3 / 3, Nix 1 / 3 / 3, Serpent 1 / 3 / 2. Every upgrade is larger than its base.

## 3. New mechanics needed

- **Keyword `reposition`** {range}. Clone `arbitrator` ability 0 "Command: Reposition" (verified) with Focus and cooldown from the entry. The first pick is a friendly creature and the second pick is a free hex within range of it. Free action.
- **Keyword `scrappers`.** A unit passive carrying `sequenceEffect: add_attack_after_counter_melee`, copied from vanilla `locust` (verified in `demons/locust_l.json`). It only triggers when a counterattack actually happens, so it rewards attacking stacks that still have one.
- **Keyword `pull`.** Clone `giant_frog` ability 1 "Sticky Tongue" (verified: `push_unit` ["true","false"], reach pattern, free, 1F CD1). Set Focus and cooldown from the entry. The Tower draft wants the same keyword (Lodestone Pull), so build it once in the shared table.
- **Keyword `steal_on_hit`.** Add target mechanic `steal_buffs` to the default melee dealer, using the value layout of `angel_upg` (verified), with the count limited to 1. If `steal_buffs` cannot be limited, steal all positive effects and cut the Corsair body.
- **Keyword `pierce_shot`.** `cove_focus_shot` with the shot dealer's `attackPatternSid` set to `attack_reach_x1_x100_x50` (Castle's Archangel alt uses this pattern for melee). It needs a check that a reach pattern works on a ranged dealer.
- **Keyword `push_on_hit`** {counter: bool}. Target mechanic `push_unit_from_caster` ["false"] (minos ability 0, verified) on the default attack dealer, and on the counterattack dealer when `counter` is true. The Castle draft defines the same keyword; one implementation serves both.
- **Keyword `cooldown_cast`** {rounds}. A single-enemy ranged cast (envelope from `cove_debuff_cast`) whose mechanic is `force_unit_cd` with the values layout the jaw line uses. The Stronghold draft's `cooldown_strike` is the melee version; mine is ranged, has no damage, and lasts 2 rounds.
- **Keyword `overwatch`.** A `start_battle` self buff (like `kw_start_buff`) with `maxOverwatchStrikes` 999, copied from `sub_skill_formation_4_overwatch_buff` (verified). Qilin's "Always remains in Overwatch" shows the unit-side form.
- **Buff `h3_kit_cove_coiled_effect`.** Clone the root buff Crushing Coils already applies, and add `disablers` ["counter_attack"]. That is the layout the Conflux frozen effect uses.
- **Keyword `whirlpool`.** Clone `aqualotl_upg` ability 2 (verified) unchanged except Focus, cooldown and damage multiplier (0.6).
- No new plugin rule kinds are needed for Cove. Every card above is native data.

## 4. Power notes

These are estimates from the model's formulas, not a scratch run.

- **Crew line:** losing Boarding costs about 10% offence. Scrappers is unseen by the model; give it `offMult` 1.15 (a second hit whenever the target counterattacks). Seaman loses Brawler, gains a pull (util +0.5). Crew Mate and Seaman unchanged. Crew alt +1 Attack.
- **Corsair:** losing Sea Legs is about -15% toughness; give it +3 HP. Swing Aboard at mult 1.0 is weaker than Cutlass Rush at 1.5 with no counterattack. Plunder is `offMult` about 1.05. Net offence about even.
- **Sea Dog:** Raking Shot at 50% splash replaces an execute. The model will value it lower (about -5% offence); give it +1 Attack.
- **Stormbird line:** losing Swoop costs about 12% offence on fast flyers. Gust is unseen by the model (util +0.5). Stormbird +1 Attack. Ayssid also loses Evasive: give it +3 HP. Stormbird alt loses a shot, a resist and an aura: give it +1 Attack, +1 Defence and +3 HP. Check the Ayssid/alt pair gap stays at or under 0.10.
- **Sea Witch line:** losing Duelist costs melee value only (the model counts skirmisher). Sea Witch +2 HP. Sorceress: Becalm replaces a +50% shot (offence down about 10%, util +1). Give it +1 Attack.
- **Nix line:** Nix loses Abyssal Hook (offence down slightly): give it +1 Attack. Nix Warrior swaps Alert and a shot for Overwatch; the model can't see Overwatch, so set `offMult` 1.10. Nix alt loses Tidal Charge: give it +2 Attack.
- **Serpent line:** removing Slick Scales costs about 8% toughness. Sea Serpent +10 HP. Haspid loses Serpent Rush and the +50% on Coils, but Coils now disarms counterattacks (util +0.5): give it +2 Attack. Serpent alt loses two resists and a shot (-20% toughness, -10% offence): give it +3 Defence and +15 HP, then re-check the pair gap.

## 5. Risks

- **`pull` and `whirlpool` on new rows.** Pulls on rows other than the vanilla frog and aqualotl are unproven. Pulling into hazards and AI pathing after a pull are untested.
- **`push_on_hit` on counterattacks (Gale Guard)** is unproven. A push in the middle of an attack sequence may break Scrappers-style follow-ups or double strikes.
- **`maxOverwatchStrikes` as a unit buff.** Natively it is a hero formation buff. With 999 strikes it may trigger on every hex of a long move through its zone, or on fliers passing over.
- **`steal_buffs` limited to one effect** may not be supported. Stealing everything on every melee hit is much stronger.
- **`pierce_shot`:** a reach pattern on a ranged dealer may hit the hex behind the shooter, not behind the target.
- **Cross-faction:** `pull` (Tower), `push_on_hit` (Castle) and `force_unit_cd` (Stronghold) also appear in other drafts. Each Cove card uses a different trigger or range from those, but the owner may still read them as shared.
