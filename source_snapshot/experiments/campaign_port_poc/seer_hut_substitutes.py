"""Hand-crafted substitutes for HoMM3 Seer hut quests that OE cannot port natively.

WHY THIS FILE EXISTS
--------------------
Most H3 Seer hut quests port 1:1 into the confirmed four-stage QuestScript FSM
(``seer_hut_quest.py``). A small set of H3 mission/reward types has no proven OE
native equivalent:

- mission type 1  "hero reaches experience level N"   — no ECondition.HeroLevel
- mission type 2  "hero primary skill total >= N"     — ECondition.HeroStat exists
  in the Golden Era pin (value 34) but its event/latch wiring is not statically
  proven enough to ship (see docs/homm3_seer_hut_questscript.md)
- mission type 8  "hero must be a specific hero"      — no identity ECondition
- mission types 3/4 whose H3 target absod id never got bound to an OE entity SID
  during the port walk (no squad/hero entity to subscribe HeroKill/SquadKill to)
- H3 artifacts / spells / creatures with no ported OE SID (fetch missions and
  artifact/spell/creature rewards fail closed in the native path)

Reward types 2 ("+N mana") and 3 ("+N morale") no longer need substitutes:
stock OE evidence pins EAction.ChangeManaHero (full refill) and
EAction.AddBuffHeroDays (campaign_morale_buff) as the native equivalents —
they are emitted by SeerRewardManaRestore / SeerRewardHeroBuffDays in
``seer_hut_quest.py`` (proof tier: stock action+buff config, empty-heroSid
resolution statically plausible, runtime unproven).

Rather than fail those huts closed forever (which deletes content the campaigns
were balanced around), each blocked hut gets ONE hand-written substitute here.
Every entry records:

- the original H3 quest (decoded fields verbatim, for future re-port attempts)
- the substitute quest, expressed as a decode-shaped payload so it flows through
  the same proven ``_mission_from_quest`` / ``_reward_from_quest`` machinery
- a human rationale

SUBSTITUTE DESIGN PRINCIPLES
----------------------------
1. The substitute must be achievable on the map it lives on (no fetch of an item
   that may not exist; no consuming a unique artifact another quest chain needs).
2. It must use only proven single-event QuestScript conditions (ResCounter /
   UnitOwnSide / ItemOwnSide) so the confirmed FSM shape is untouched.
3. Level-gates (type 1) become gold donations scaled to the required level: gold
   is the universal "time investment" currency and cannot soft-lock.
4. Reward substitutes stay as close to the H3 reward as OE allows:
   morale -> ``campaign_morale_buff`` via AddBuffHeroDays (stock buff, moral +3,
   days=999 = stock permanent marker); mana -> full refill via ChangeManaHero.
5. Hand-written dialog replaces H3 texts that described the original mission so
   the story still reads coherently. Maps with empty H3 texts get texts that
   describe the substitute, not the original.

If a future agent implements a *native* port of one of these H3 types (e.g.
HeroStat statically proven end-to-end), DELETE the registry entry here and let
the native path take over. ``plan_from_seer_entity`` fails closed if a registry
entry shadows a quest the native path can already handle — a stale substitute is
a bug, not a fallback.
"""

from __future__ import annotations

from typing import Any

# Registry key: (mission_id, seer sourceKey) from the decoded port manifest.
# Value fields:
#   original   — verbatim description of the H3 quest (for future re-ports)
#   rationale  — why this substitute, why it is achievable, why it is close
#   mission    — decode-shaped mission payload (numeric H3 types only, must be
#                within SUPPORTED_MISSION_TYPES); omit to keep the H3 mission
#   reward     — decode-shaped reward payload; numeric H3 reward types or the
#                substitute-only string kinds "hero_buff_days" / "mana_restore";
#                omit to keep the H3 reward
#   texts      — {first_visit, next_visit, completed} hand-written dialog;
#                omit to keep the H3 texts (used when they stay coherent)
SEER_HUT_SUBSTITUTES: dict[tuple[str, str], dict[str, Any]] = {
    # ------------------------------------------------------------------
    # H3 mission type 1 (reach experience level N) -> gold donations.
    # ------------------------------------------------------------------
    (
        "burning_of_tatalia",
        "0:96:59",
    ): {
        "original": "mission type 1: reach experience level 32 -> reward 10,000 gold",
        "rationale": (
            "No OE hero-level condition. The H3 seer offers war funds; a small "
            "donation that is paid back doubled keeps the reward net positive and "
            "the flavor of a shrewd investor."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 5000]},
        "texts": {
            "first_visit": (
                "If you prove your commitment, I will invest in your war fund. Bring me "
                "5,000 gold pieces and I will return them with 10,000 of my own. Until "
                "then, do not bother me!"
            ),
            "next_visit": "The war fund cannot grow on empty promises. I still await your 5,000 gold.",
            "completed": (
                "I thought you had promise. Come in, come in. Here is the money I have "
                "promised you — your 5,000 returned, and 10,000 more for the war."
            ),
        },
    },
    (
        "faerie_dragons",
        "0:104:4",
    ): {
        "original": "mission type 1: reach experience level 20 -> reward 10 Titans",
        "rationale": (
            "No OE hero-level condition. Gold donation scaled to the level-20 gate "
            "buys the same time investment the level check enforced."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 7500]},
        "texts": {
            "first_visit": (
                "I keep mighty guests in these woods, but they answer only to proven "
                "patrons. Bring me 7,500 gold and I will send ten Titans to your banner."
            ),
            "next_visit": "The Titans grow restless. Have you gathered the 7,500 gold yet?",
            "completed": "A fair price, fairly paid. The Titans are yours — treat them well.",
        },
    },
    (
        "hurry_up_and_wait",
        "0:13:32",
    ): {
        "original": "mission type 1: reach experience level 35 -> reward 5 Archangels",
        "rationale": (
            "No OE hero-level condition. Gold donation scaled to the level-35 gate; "
            "Archangels remain the reward."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 15000]},
        "texts": {
            "first_visit": (
                "The heavens open their gates for champions, not beggars. Bring 15,000 "
                "gold as an offering and five Archangels will descend to your cause."
            ),
            "next_visit": "The offering is not yet complete. 15,000 gold, then we will speak of wings.",
            "completed": "Your offering is accepted. Five Archangels — spend their grace wisely.",
        },
    },
    (
        "hurry_up_and_wait",
        "0:32:66",
    ): {
        "original": "mission type 1: reach experience level 35 -> reward 11 Archangels",
        "rationale": (
            "No OE hero-level condition. This hut grants the larger Archangel host of "
            "the two on this map, so the donation is doubled accordingly."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 30000]},
        "texts": {
            "first_visit": (
                "A host awaits the faithful. Bring 30,000 gold as tribute and eleven "
                "Archangels will take the field beside you."
            ),
            "next_visit": "The host does not descend for empty hands. 30,000 gold is the price.",
            "completed": "Eleven Archangels, as promised. Lead them to victory.",
        },
    },
    (
        "hurry_up_and_wait",
        "0:47:58",
    ): {
        "original": "mission type 1: reach experience level 31 -> reward 123,849 experience",
        "rationale": (
            "No OE hero-level condition. The H3 reward is raw experience, so the "
            "substitute keeps it verbatim and replaces only the gate with a war-chest "
            "donation — veterans sell their stories dearly."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 25000]},
        "texts": {
            "first_visit": (
                "I have fought a hundred wars and remember every one. For 25,000 gold "
                "I will tell you the parts the chronicles leave out."
            ),
            "next_visit": "Wisdom is not free. 25,000 gold, and every lesson I own is yours.",
            "completed": "Listen well. Few live long enough to hear this twice.",
        },
    },
    (
        "hurry_up_and_wait",
        "0:21:82",
    ): {
        "original": "mission type 1: reach experience level 30 -> reward +101 mana",
        "rationale": (
            "No OE hero-level condition and no interacting-hero mana grant. The gate "
            "becomes a donation; the mana reward becomes a full refill of the "
            "visiting hero's spell points (ChangeManaHero 100%)."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 10000]},
        "reward": {"rewardType": "mana_restore"},
        "texts": {
            "first_visit": (
                "Your aura is thin, little mage. For 10,000 gold I will draw a draught "
                "from the deep wells and fill your mind with power."
            ),
            "next_visit": "The wells do not open for free. 10,000 gold first.",
            "completed": "Drink deep. Your spell points are whole again.",
        },
    },
    (
        "hurry_up_and_wait",
        "0:80:34",
    ): {
        "original": "mission type 1: reach experience level 27 -> reward +62 mana",
        "rationale": (
            "No OE hero-level condition and no interacting-hero mana grant. Same "
            "pattern as 0:21:82 with a donation scaled to the lower level gate."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 7500]},
        "reward": {"rewardType": "mana_restore"},
        "texts": {
            "first_visit": (
                "The springs here restore what battle drains. For 7,500 gold I will "
                "let you drink your fill."
            ),
            "next_visit": "No gold, no water. 7,500 gold is the toll.",
            "completed": "Drink. Your spell points are restored.",
        },
    },
    (
        "invasion",
        "0:59:62",
    ): {
        "original": "mission type 1: reach experience level 32 -> reward Sword of Hellfire",
        "rationale": (
            "No OE hero-level condition. The H3 Burning of Tatalia map forges this "
            "exact blade from a stock recipe (20 wood, 10 mercury, 20 ore, 10 sulfur, "
            "10 crystal, 10 gems, 5,000 gold), so the Invasion smith uses the same "
            "recipe — keeps the artifact, keeps the smith flavor."
        ),
        "mission": {
            "missionType": 7,
            "requiredResources": [20, 10, 20, 10, 10, 10, 5000],
        },
        "texts": {
            "first_visit": (
                "I can forge a Sword of Hellfire for your campaign, but my stock is "
                "spent. Bring me 20 Wood, 20 Ore, 10 each of Mercury, Sulfur, Crystal "
                "and Gems, and 5,000 gold for the fires."
            ),
            "next_visit": "The forge stays cold until every ingredient is in my hands.",
            "completed": "The blade is quenched and singing. Take it — and burn a path home.",
        },
    },
    (
        "master",
        "0:3:14",
    ): {
        "original": "mission type 1: reach experience level 10 -> reward +9 knowledge",
        "rationale": (
            "No OE hero-level condition. A modest tuition donation replaces the "
            "level gate; the knowledge reward is unchanged."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 5000]},
        "texts": {
            "first_visit": (
                "Every master was once a paying student. Fund my library with 5,000 "
                "gold and I will open your mind to deeper lore."
            ),
            "next_visit": "The books stay closed until the 5,000 gold tuition is paid.",
            "completed": "Study well. Knowledge is the one treasure no thief can take.",
        },
    },
    (
        "their_end_of_the_bargain",
        "0:15:16",
    ): {
        "original": "mission type 1: reach experience level 12 -> reward +26 mana",
        "rationale": (
            "No OE hero-level condition and no interacting-hero mana grant. Small "
            "donation for the low level gate; mana becomes a full refill."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 3000]},
        "reward": {"rewardType": "mana_restore"},
        "texts": {
            "first_visit": (
                "I sense your reserves run low. For 3,000 gold I will top them off — "
                "a bargain between friends."
            ),
            "next_visit": "3,000 gold, and the font is yours.",
            "completed": "There — your spell points brim again. Our bargain is kept.",
        },
    },
    (
        "valley_of_the_dragon_lords",
        "0:55:49",
    ): {
        "original": "mission type 1: reach experience level 10 -> reward 20 Sharpshooters",
        "rationale": (
            "No OE hero-level condition. The valley's lords respect coin as much as "
            "renown; donation replaces the level gate, Sharpshooters remain."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 10000]},
        "texts": {
            "first_visit": (
                "My Sharpshooters do not march for green recruits. Show 10,000 gold "
                "of war-chest discipline and twenty of them will march for you."
            ),
            "next_visit": "10,000 gold. Discipline is proven, not claimed.",
            "completed": "Twenty Sharpshooters, drilled and ready. Do not waste their aim.",
        },
    },
    (
        "here_there_be_pirates",
        "0:36:22",
    ): {
        "original": "mission type 1: reach experience level 24 -> reward 5 Titans",
        "rationale": (
            "No OE hero-level condition. Gold donation scaled to the level-24 gate "
            "(between the level-20 and level-27 neighbors at 7,500); the 5 Titans "
            "reward ports natively via h3_giant_upg."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 7500]},
        "texts": {
            "first_visit": (
                "Five of my giants crew only for captains with coin enough to pay "
                "their keep. Show me 7,500 gold and they sail with you."
            ),
            "next_visit": "7,500 gold, captain. Giants do not work on credit.",
            "completed": "Paid in full. Five Titans, yours — point them at the horizon and let go.",
        },
    },
    # ------------------------------------------------------------------
    # H3 mission type 2 (primary skill total) -> themed fetches.
    # ------------------------------------------------------------------
    (
        "faerie_dragons",
        "0:31:84",
    ): {
        "original": "mission type 2: spell power 20 -> reward Ogre's Club of Havoc",
        "rationale": (
            "ECondition.HeroStat exists in the Golden Era pin but its event/latch "
            "wiring is not statically proven, so we do not ship it. Raw magical "
            "essence (the four rare resources) is the natural spell-power fetch."
        ),
        "mission": {
            "missionType": 7,
            "requiredResources": [0, 20, 0, 20, 20, 20, 0],
        },
        "texts": {
            "first_visit": (
                "I weave power from raw essence, but my stores are dry. Bring me 20 "
                "each of Mercury, Sulfur, Crystal and Gems and I will trade you a club "
                "swinging with stored might."
            ),
            "next_visit": "20 Mercury, 20 Sulfur, 20 Crystal, 20 Gems. The loom waits.",
            "completed": "Pure essence, every grain. Here — the Ogre's Club of Havoc, as promised.",
        },
    },
    (
        "farming_towns",
        "0:37:70",
    ): {
        "original": "mission type 2: attack skill 10 -> reward expert Tactics",
        "rationale": (
            "ECondition.HeroStat exists in the Golden Era pin but is not statically "
            "proven for QuestScript latches. Funding the seer's training grounds "
            "keeps the martial-tutelage flavor of the original text."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 5000]},
        "texts": {
            "first_visit": (
                "You want to learn the true tactics of a great warrior? Drills cost "
                "gold. Bring me 5,000 gold for the training grounds and I will teach "
                "you formations no farmer-soldier ever dreamed of."
            ),
            "next_visit": "No gold, no drills. 5,000 gold for the training grounds.",
            "completed": "Watch the lines, learn the timing. You fight like a general now.",
        },
    },
    # ------------------------------------------------------------------
    # H3 mission type 8 (be a specific hero) -> signature-unit fetch.
    # ------------------------------------------------------------------
    (
        "cutthroats",
        "0:1:69",
    ): {
        "original": "mission type 8: visiting hero must be Gelu -> reward Ring of Vitality",
        "rationale": (
            "No OE hero-identity condition. In Armageddon's Blade Gelu's signature "
            "troops are Grand Elves; bringing them proves the elven connection the "
            "original identity check enforced, and works for any OE hero. This keeps "
            "the map's Badge-of-Courage -> Angel Wings -> Ring of Vitality chain intact."
        ),
        "mission": {
            "missionType": 6,
            "requiredCreatures": [{"creatureType": 19, "count": 30}],
        },
        "texts": {
            "first_visit": (
                "My friend Phelan told me to expect the pale one's people. Prove the "
                "elves march with you — bring me 30 Grand Elves — and I will give you "
                "the Ring of Vitality I was told to keep safe."
            ),
            "next_visit": (
                "I was told to hold the Ring for the one the elves follow. If you see "
                "30 Grand Elves in your travels, bring them to me."
            ),
            "completed": (
                "Grand Elves at your back — Phelan's word holds. The Ring of Vitality "
                "is yours."
            ),
        },
    },
    # ------------------------------------------------------------------
    # H3 mission types 3/4 with no bound OE target entity.
    # ------------------------------------------------------------------
    (
        "blood_of_the_dragon_father",
        "1:87:70",
    ): {
        "original": "mission type 4: defeat squad absod 903858184 -> reward Dragon Scale Armor",
        "rationale": (
            "The H3 target squad was never bound to an OE entity SID in the port "
            "walk, so SquadKill has nothing to subscribe to. Dragon treasure "
            "(crystal and gems) is the thematic fetch for a dragon-forged armor."
        ),
        "mission": {
            "missionType": 7,
            "requiredResources": [0, 0, 0, 0, 20, 20, 0],
        },
        "texts": {
            "first_visit": (
                "Dragonscale does not bond to common hide. Bring me 20 Crystal and 20 "
                "Gems to line the seams and I will finish a Dragon Scale Armor fit for "
                "a dragonslayer."
            ),
            "next_visit": "20 Crystal and 20 Gems. The scales wait for their setting.",
            "completed": "Hold still while I fasten the last scale. It is yours — wear it into legend.",
        },
    },
    (
        "burning_of_tatalia",
        "0:116:86",
    ): {
        "original": (
            "mission type 4: defeat Wights (absod 1075875716) south-east beyond the "
            "Garrison -> reward 30 Serpent Flies (map custom text)"
        ),
        "rationale": (
            "The H3 Wight squad was never bound to an OE entity SID. The map already "
            "frames undeath mastery through Skeleton Warriors (hut 0:68:113 asks for "
            "200); bringing 50 proves the same fight against the plague the original "
            "Wight hunt did, and the Fortress 'our males join your cause' reward "
            "still fits."
        ),
        "mission": {
            "missionType": 6,
            "requiredCreatures": [{"creatureType": 57, "count": 50}],
        },
        "texts": {
            "first_visit": (
                "The undead have taken our home! Prove you can master them — bring us "
                "50 Skeleton Warriors bound to your will — and our males will join "
                "your cause for the war."
            ),
            "next_visit": "50 Skeleton Warriors, bound and marching. Until then our homes stay lost.",
            "completed": (
                "Excellent! You command the very plague that drove us out. Our wives "
                "and children can go home — we will help you with the war effort."
            ),
        },
    },
    (
        "fall_of_sandro",
        "0:59:50",
    ): {
        "original": (
            "mission type 4: defeat ghost dragons (absod 1450863563) -> reward Elixir "
            "of Life (SoD combo artifact, not ported; originally fed four downstream "
            "Elixir trade huts)"
        ),
        "rationale": (
            "Two blockers: the H3 ghost-dragon squad was never bound to an OE entity "
            "SID, and the Elixir of Life (h3Id 131) is a SoD combo artifact the OE "
            "port catalog deliberately excludes — so the whole Elixir trade chain is "
            "rewired hut by hut (see the four entries below). A ritual of rare "
            "essences to 'put their souls to rest' preserves the flavor; Dragon "
            "Scale Armor keeps a dragon-themed treasure at the chain's head."
        ),
        "mission": {
            "missionType": 7,
            "requiredResources": [0, 20, 0, 20, 20, 20, 0],
        },
        "reward": {"rewardType": 8, "artifactId": 40},
        "texts": {
            "first_visit": (
                "Our brethren were once beautiful dragons, now hideous ghosts under a "
                "mere mortal Necromancer's yoke. We can free their souls with a ritual "
                "of rare essence — bring us 20 each of Mercury, Sulfur, Crystal and "
                "Gems, and we will give you armor forged from what they leave behind."
            ),
            "next_visit": (
                "Until the ritual is complete, we will not part with the armor. "
                "20 Mercury, 20 Sulfur, 20 Crystal, 20 Gems."
            ),
            "completed": (
                "Their souls soar free at last. This Dragon Scale Armor was forged of "
                "their shed scales — wear it, and remember them kindly."
            ),
        },
    },
    (
        "fall_of_sandro",
        "1:13:50",
    ): {
        "original": (
            "mission type 5: bring Elixir of Life (unported h3Id 131) -> reward Bow of "
            "the Sharpshooter (unported h3Id 137)"
        ),
        "rationale": (
            "Both artifacts are SoD combos excluded from the port catalog, so the "
            "trade is re-authored: healers' fees and rare medicine for the dying "
            "mother, and the 'prized possession' becomes twenty living Sharpshooters "
            "instead of a bow named for them."
        ),
        "mission": {
            "missionType": 7,
            "requiredResources": [0, 0, 0, 0, 0, 15, 5000],
        },
        "reward": {"rewardType": 10, "creatureType": 137, "creatureCount": 20},
        "texts": {
            "first_visit": (
                "My mother's health is failing and the healers demand rare medicine I "
                "cannot afford. Bring me 15 Gems and 5,000 gold, and I will give you "
                "my most prized possession — the twenty Sharpshooters who have "
                "guarded my family for years."
            ),
            "next_visit": "Unless you can pay for the medicine, I cannot part with my Sharpshooters.",
            "completed": (
                "You have saved her. Take them — my Sharpshooters. Where did you find "
                "such kindness? No matter. They are yours now."
            ),
        },
    },
    (
        "fall_of_sandro",
        "1:21:23",
    ): {
        "original": (
            "mission type 5: bring Elixir of Life (unported h3Id 131) -> reward "
            "Wizard's Well (unported h3Id 138)"
        ),
        "rationale": (
            "Both artifacts are SoD combos excluded from the port catalog. Arcane "
            "essence replaces the Elixir; a permanent +4 intelligence is the "
            "mechanical echo of the Well's daily spell-point regeneration."
        ),
        "mission": {
            "missionType": 7,
            "requiredResources": [0, 20, 0, 0, 20, 0, 0],
        },
        "reward": {"rewardType": 6, "primarySkill": 3, "primarySkillAmount": 4},
        "texts": {
            "first_visit": (
                "I am in desperate need of raw arcane essence. My well of power has "
                "run dry and only Mercury and Crystal can refill it. Bring me 20 of "
                "each and I will share what the well taught me over a lifetime."
            ),
            "next_visit": "Unless you bring 20 Mercury and 20 Crystal, the well stays dry — for both of us.",
            "completed": "Perfect specimens! Drink deep of what the well knows — your mind will hold more than ever before.",
        },
    },
    (
        "fall_of_sandro",
        "1:51:58",
    ): {
        "original": (
            "mission type 5: bring Elixir of Life (unported h3Id 131) -> reward Ring "
            "of the Magi (unported h3Id 139)"
        ),
        "rationale": (
            "Both artifacts are SoD combos excluded from the port catalog. The "
            "grandfather-mage flavor is kept; the ring's gift becomes a permanent "
            "+4 spell power, the mage-craft echo of the Ring of the Magi."
        ),
        "mission": {
            "missionType": 7,
            "requiredResources": [0, 20, 0, 0, 0, 20, 0],
        },
        "reward": {"rewardType": 6, "primarySkill": 2, "primarySkillAmount": 4},
        "texts": {
            "first_visit": (
                "I seek the raw stuff of enchantment. This craft once belonged to my "
                "grandfather, a powerful mage. Bring me 20 Mercury and 20 Gems and I "
                "will imbue you with what he taught me."
            ),
            "next_visit": "20 Mercury and 20 Gems. Grandfather's lessons are not given away for less.",
            "completed": "I will teach you my grandfather's deepest workings, as promised. Strike harder than ever.",
        },
    },
    (
        "fall_of_sandro",
        "1:46:22",
    ): {
        "original": (
            "mission type 5: bring Elixir of Life (unported h3Id 131) -> reward "
            "Titan's Thunder (unported h3Id 134); H3 texts empty"
        ),
        "rationale": (
            "Both artifacts are SoD combos excluded from the port catalog. Titan's "
            "Thunder was a lightning artifact, so the substitute trades gold for "
            "the mapped Chain Lightning spell — OE primal_12_magic_chain_lightning "
            "is the literal same spell, so the reward stays a spell upgrade of the "
            "same storm family."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 10000]},
        "reward": {"rewardType": 9, "spellId": 19},
        "texts": {
            "first_visit": (
                "Storms answer to gold and to will. Bring me 10,000 gold and I will "
                "teach you to call the lightning itself."
            ),
            "next_visit": "10,000 gold, and the storm is yours to command.",
            "completed": "Feel it crackle at your fingertips. Chain Lightning — spend it well.",
        },
    },
    (
        "march_of_the_undead",
        "0:107:37",
    ): {
        "original": (
            "mission type 4: defeat Water Elementals occupying the gnoll mine (absod "
            "4219271635) -> reward 1,000 Gnoll Marauders"
        ),
        "rationale": (
            "The H3 elemental squad was never bound to an OE entity SID. Reopening "
            "the mine with ore and gold keeps the mining-equipment story beat and "
            "the 'we will join your ranks' payoff."
        ),
        "mission": {
            "missionType": 7,
            "requiredResources": [0, 0, 20, 0, 0, 0, 5000],
        },
        "texts": {
            "first_visit": (
                "You come across a camp of Gnoll Marauders with mining equipment. One "
                "Gnoll pushes forward and asks, \"Our mine is flooded and our tools "
                "are rusted through. Bring us 20 Ore and 5,000 gold to refit the "
                "works, and we will join your ranks.\""
            ),
            "next_visit": "\"20 Ore and 5,000 gold, and the mine — and our spears — are yours.\"",
            "completed": "\"The mine will sing again. We march with you — all of us.\"",
        },
    },
    (
        "returning_to_bracada",
        "0:27:10",
    ): {
        "original": "mission type 4: defeat squad absod 2124940001 -> reward 20 crystal",
        "rationale": (
            "The H3 target squad was never bound to an OE entity SID. A plain "
            "merchant trade — gold for crystal — preserves the resource economy the "
            "quest fed without inventing a target."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 5000]},
        "texts": {
            "first_visit": (
                "A trader's luck ran dry on the Bracada road. Give me 5,000 gold to "
                "restock and I will cut you in for 20 Crystal from my next caravan."
            ),
            "next_visit": "5,000 gold buys you 20 Crystal. That is the whole deal.",
            "completed": "Pleasure doing business. 20 Crystal, as agreed.",
        },
    },
    (
        "secrets_revealed",
        "0:37:1",
    ): {
        "original": "mission type 3: defeat hero absod 1069052162 -> reward 20 Thunderbirds",
        "rationale": (
            "The H3 target hero was never bound to an OE entity SID. Thunderbirds "
            "follow strength; a war-chest donation is the neutral proof the "
            "Stronghold-flavored reward expects."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 10000]},
        "texts": {
            "first_visit": (
                "The Thunderbirds circle only war-chiefs who can keep them fed. Bring "
                "10,000 gold for their keep and twenty of the flock will answer your "
                "war-horn."
            ),
            "next_visit": "10,000 gold for the flock's keep. The sky waits.",
            "completed": "Twenty Thunderbirds, hungry and loud. Point them at your enemies.",
        },
    },
    (
        "burning_of_tatalia",
        "0:84:24",
    ): {
        "original": (
            "mission type 3: defeat hero Qenay (absod 1540049906) -> reward Fly "
            "(h3 spell 6, no mechanics-matched OE magic)"
        ),
        "rationale": (
            "Two blockers: the H3 target hero was never bound to an OE entity SID, "
            "and H3 Fly has no mechanic-matched OE magic in H3_SPELL_TO_OE_MAGIC. "
            "A resting ritual keeps the 'put his soul to rest' story; Boots of "
            "Levitation carry the same 'travel where wings would' fantasy the Fly "
            "scroll promised."
        ),
        "mission": {
            "missionType": 7,
            "requiredResources": [0, 20, 0, 0, 0, 20, 0],
        },
        "reward": {"rewardType": 8, "artifactId": 90},
        "texts": {
            "first_visit": (
                "Qenay is an evil and horrid beastly thing. He used to be my beloved "
                "husband, but was slaughtered and turned into a hideous thing. I "
                "cannot lay him to rest alone. Bring me 20 Mercury and 20 Gems for "
                "the resting ritual and I will give you boots that walk where wings "
                "cannot."
            ),
            "next_visit": "The ritual is not ready. 20 Mercury and 20 Gems, or his soul wanders still.",
            "completed": (
                "Qenay is finally at rest. Thank you for doing this for me. Take "
                "these Boots of Levitation — may they carry you lighter than his "
                "spirit now travels."
            ),
        },
    },
    (
        "burning_of_tatalia",
        "0:114:59",
    ): {
        "original": (
            "mission type 3: defeat hero Photima (absod 1540049908) -> reward "
            "20 mercury (map custom text)"
        ),
        "rationale": (
            "The H3 target hero was never bound to an OE entity SID. Funding the "
            "manhunt keeps the bounty flavor; the mercury reward is native and "
            "unchanged."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 5000]},
        "texts": {
            "first_visit": (
                "Photima has betrayed her people and joined the side of darkness and "
                "evil. My hunters need funding to bring her to justice. Give 5,000 "
                "gold to the hunt and I will pay 20 Mercury from the bounty."
            ),
            "next_visit": "The hunt stalls without coin. 5,000 gold, and the bounty is yours.",
            "completed": (
                "I thought the day would never come! Photima's trail is cornered at "
                "last. You have earned your 20 Mercury."
            ),
        },
    },
    (
        "march_of_the_undead",
        "0:10:74",
    ): {
        "original": (
            "mission type 4: defeat golem guardians (absod 403068131) -> reward "
            "Crest of Valor"
        ),
        "rationale": (
            "The H3 golem squad was never bound to an OE entity SID. Garrisoning "
            "the valley pass with veteran troops proves the same valor the golem "
            "fight did; the Crest of Valor reward is native and unchanged."
        ),
        "mission": {
            "missionType": 6,
            "requiredCreatures": [{"creatureType": 7, "count": 30}],
        },
        "texts": {
            "first_visit": (
                "An evil wizard drove me out and placed guardians at the entrance to "
                "my valley. I dare not return while the pass is unheld. Bring me 30 "
                "Crusaders to garrison it and I will give you a Crest for your Valor."
            ),
            "next_visit": "30 Crusaders at the pass, or the valley stays lost to me.",
            "completed": "The pass is held and my valley is safe. Wear this Crest of Valor proudly.",
        },
    },
    (
        "march_of_the_undead",
        "0:41:103",
    ): {
        "original": (
            "mission type 4: defeat Throng of Fire Elementals (absod 403068132) -> "
            "reward Inferno (h3 spell 22, no mechanics-matched OE magic)"
        ),
        "rationale": (
            "Two blockers: the H3 elemental squad was never bound to an OE entity "
            "SID, and H3 Inferno has no mechanic-matched OE magic. Binding the "
            "menace with raw sulfur (fire's own essence) replaces the fight; the "
            "Tome of Fire Magic literally delivers the 'powerful fire magic' "
            "Adrienne was promised."
        ),
        "mission": {
            "missionType": 7,
            "requiredResources": [0, 0, 0, 30, 0, 0, 0],
        },
        "reward": {"rewardType": 8, "artifactId": 86},
        "texts": {
            "first_visit": (
                "I knew you would be coming here soon, Adrienne. I will give you what "
                "you want to know — powerful fire magic. But first, prove your "
                "capabilities. To the north a Throng of Fire Elementals terrorizes "
                "the locals. Bring me 30 Sulfur to bind them and return to me."
            ),
            "next_visit": "30 Sulfur, Adrienne. The binding circle cannot be drawn without it.",
            "completed": "The elementals are bound. Take this Tome of Fire Magic — you have earned every page.",
        },
    },
    (
        "secrets_revealed",
        "0:33:45",
    ): {
        "original": (
            "mission type 4: defeat Ancient Behemoths (absod 1517295935) -> reward "
            "25 Cyclops Kings (map custom text)"
        ),
        "rationale": (
            "The H3 behemoth squad was never bound to an OE entity SID. Arming the "
            "threatened villages with a defense fund keeps the story beat; the "
            "Cyclops King reward is native and unchanged."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 15000]},
        "texts": {
            "first_visit": (
                "Ancient Behemoths are menacing the villages just north of here. "
                "Bring me 15,000 gold to arm and wall those villages and I would "
                "reward you richly."
            ),
            "next_visit": "The villages still stand open. 15,000 gold buys walls and watchmen.",
            "completed": "The villages are safe behind new walls. Here — 25 Cyclops Kings, as promised.",
        },
    },
    (
        "hurry_up_and_wait",
        "0:83:103",
    ): {
        "original": "mission type 3: defeat hero absod 2220376651 -> reward 5 Angels",
        "rationale": (
            "The H3 target hero was never bound to an OE entity SID. A temple "
            "offering stands in for the duel; the Angel reward is native and "
            "unchanged."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 12000]},
        "texts": {
            "first_visit": (
                "The temple sends its champions only where the faith is proven. "
                "Bring an offering of 12,000 gold and five Angels will answer your "
                "call."
            ),
            "next_visit": "12,000 gold upon the altar. Then we will speak of Angels.",
            "completed": "The offering is accepted. Five Angels descend to your banner.",
        },
    },
    (
        "hurry_up_and_wait",
        "0:67:64",
    ): {
        "original": "mission type 3: defeat hero absod 2220376652 -> reward +9 spell power",
        "rationale": (
            "The H3 target hero was never bound to an OE entity SID. Paying the "
            "duelist-school masters replaces the duel; the +9 spell power reward is "
            "native and unchanged."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 10000]},
        "texts": {
            "first_visit": (
                "Power answers to practice, and practice answers to coin. Bring "
                "10,000 gold for the masters' fees and I will see your spell power "
                "tempered nine-fold."
            ),
            "next_visit": "The masters do not teach for free. 10,000 gold.",
            "completed": "Feel the current strengthen. Your spell power is greater by nine, as agreed.",
        },
    },
    (
        "hurry_up_and_wait",
        "0:83:4",
    ): {
        "original": "mission type 4: defeat squad absod 1251631721 -> reward 277 wood",
        "rationale": (
            "The H3 target squad was never bound to an OE entity SID. A straight "
            "lumber trade keeps the resource economy the quest fed."
        ),
        "mission": {"missionType": 7, "requiredResources": [0, 0, 0, 0, 0, 0, 2500]},
        "texts": {
            "first_visit": (
                "A timber caravan is stuck behind the lines. Bring me 2,500 gold to "
                "hire escorts and I will sell you 277 Wood at cost."
            ),
            "next_visit": "2,500 gold hires the escorts. Then the wood is yours.",
            "completed": "277 Wood, loaded and counted. The caravan rolls at last.",
        },
    },
    # ------------------------------------------------------------------
    # Reward-side substitutes (mission already ports natively).
    # ------------------------------------------------------------------
    # farming_towns 0:28:28 has NO entry: H3 spell 19 (chainLightning) is
    # mechanics-mapped to OE primal_12_magic_chain_lightning (the literal same
    # spell in OE), so the native path ports the whole quest 1:1. A registry
    # entry here would trip the fail-closed stale-substitute guard.
    (
        "march_of_the_undead",
        "0:8:88",
    ): {
        "original": (
            "mission type 5 (bring Crest of Valor) is native; reward h3 spell 58 "
            "counterstrike has no mechanics-matched OE magic (map custom text)"
        ),
        "rationale": (
            "H3_SPELL_TO_OE_MAGIC deliberately fails closed for Counterstrike. A "
            "permanent +3 attack is the martial echo of striking back harder."
        ),
        "reward": {"rewardType": 6, "primarySkill": 0, "primarySkillAmount": 3},
        "texts": {
            "first_visit": (
                "Prove to me you are worthy of learning a powerful art. Return with "
                "the Crest of Valor and I will teach you to answer every blow with "
                "a harder one."
            ),
            "next_visit": "The Crest of Valor first. Then the lesson.",
            "completed": "Watch how the counterblow lands. Your attack is sharper by three — use it.",
        },
    },
    (
        "hurry_up_and_wait",
        "0:26:21",
    ): {
        "original": (
            "mission type 5 (bring artifacts) is native; reward type 2: +57 mana is not"
        ),
        "rationale": (
            "No interacting-hero mana grant action. Full spell-point refill of the "
            "visiting hero is the closest proven surface (ChangeManaHero 100%)."
        ),
        "reward": {"rewardType": "mana_restore"},
    },
    (
        "lost_at_sea",
        "0:50:37",
    ): {
        "original": (
            "mission type 5 (bring artifact) is native; reward type 3: +2 morale is not"
        ),
        "rationale": (
            "No interacting-hero morale grant action. Stock campaign_morale_buff "
            "grants heroStat moral +3 for 999 days via AddBuffHeroDays — the stock "
            "campaign mechanism for quest morale, one point stronger than the H3 +2."
        ),
        "reward": {
            "rewardType": "hero_buff_days",
            "buffSid": "campaign_morale_buff",
            "days": 999,
        },
    },
    (
        "their_end_of_the_bargain",
        "0:52:51",
    ): {
        "original": (
            "mission type 5 (bring artifact) is native; reward type 3: +3 morale is not"
        ),
        "rationale": (
            "No interacting-hero morale grant action. campaign_morale_buff grants "
            "exactly moral +3 — a numerically exact match for this hut."
        ),
        "reward": {
            "rewardType": "hero_buff_days",
            "buffSid": "campaign_morale_buff",
            "days": 999,
        },
    },
}


def seer_hut_substitution(mission_id: str, source_key: str) -> dict[str, Any] | None:
    """Return the hand-crafted substitute for one blocked hut, or None."""

    entry = SEER_HUT_SUBSTITUTES.get((str(mission_id), str(source_key)))
    if entry is None:
        return None
    return dict(entry)
