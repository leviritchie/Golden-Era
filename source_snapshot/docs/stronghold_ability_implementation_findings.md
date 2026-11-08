# Stronghold Ability Implementation — Findings & Roadmap

Generated: 2026-05-01

---

> Status: stale. This file records what a previous implementation attempted, but its ToA
> ability names and several claimed completions are not source-grounded. Use
> `docs/stronghold_ability_mapping.md` as the current audit before making further
> Stronghold ability changes.

## Completed

### Data-Layer (JSON/Core.zip — No C# Required)

| Tier | Unit | Feature | Pattern Source |
|------|------|---------|---------------|
| 1 | Goblin/Hobgoblin/Hobgoblin Vet | Long Reach alt attack | trogl armed_ability |
| 5 | Roc / Thunderbird / Stormbird | Wing Gust (walk reposition, cd=1, energy=1) | medusa move ability |
| 5 | Thunderbird / Stormbird | Lightning Strike (melee Magic Damage, cd=2, energy=2) | medusa_upg stone gaze |
| 6 | Cyclops / King / Warlord | Boulder Throw (AoE shoot, attack_rumble_x1_x100) | medusa alt attack |
| 6 | Cyclops Warlord (alt) | Petrification (medusa_stone buff ability) | medusa_upg exact clone |
| 7 | Behemoth / Ancient / Dire | Rampage (Whirlwind, attack_swirl_x1_x100) | hydra/black_dragon alt |

### Display Text (unitsAbility.json)

- 90+ Stronghold-specific token names replaced cloned Dungeon descriptions
- All 7 tiers have narrative descriptions reflecting Stronghold lore
- All passive/ability names are Stronghold-thematic (e.g. "Grand Slam", "Bloodlust", "Wing Gust")
- All abilities list Focus cost, cooldown, and mechanical effects in descriptions

### Harmony Skeleton (StrongholdAbilities.cs)

- File compiles and deploys with the plugin (0 errors)
- Contains logging infrastructure for future ability debugging
- Documents the tag-based approach (`homm3_sa_` prefix) for avoiding collisions
- Scaffolding for Aura, Trigger, and Static Field patches

---

## What Needs Further Work

### Active Abilities Beyond Donor Patterns (C# Required)

For Tiers 2-4 (Wolf Riders, Orcs, Ogres), the Dungeon donors have no abilities, so we can't clone them. These need Harmony patches:

| Concept | Target Unit | Required Hook |
|---------|-------------|--------------|
| Bloodlust (active buff +Damage to ally) | Ogre Mage | Buff application hook |
| Battle Cry (AoE buff +Attack to allies) | Orc Chieftain | Buff application hook |
| Howl (active debuff -Morale to enemy) | Wolf Raider | Buff application hook |

### Auras (C# Required)

| Concept | Target Unit | Required Hook |
|---------|-------------|--------------|
| Wolf Pack (+Attack to adjacent allies) | Wolf Rider variants | Battle start/unit placement hook |
| Fear Aura (-Attack to adjacent enemies) | Ancient Behemoth | Battle start/unit placement hook |

### Triggers (C# Required)

| Concept | Target Unit | Required Hook |
|---------|-------------|--------------|
| Blood Rage (+Attack on ally death) | Ogre base | Unit death event hook |
| Orc Rage (+Attack on damage taken) | Orc Warlord alt | Damage application hook |
| Static Field (reflect Magic Damage on melee hit) | Stormbird | Damage application hook |

### Hook Discovery Process

Follow the existing pattern from DamageHistogramOverlay.cs:
1. Find the relevant obfuscated method in regenerated Hex interop (e.g., `ejz.bdwu()` for damage forecast)
2. Write a Harmony prefix/postfix that checks unit tags
3. Use `AgentDebugLog.Write("I", "SA", ...)` for logging
4. Test via config toggle

---

## Lessons Learned

1. **The engine's passive system is not generic** — it's a fixed set of engine-recognized structures (`immunities` + a few special types). Custom `aura`, `onDamage`, `onAllyDeath` passives cause NRE.

2. **Unit abilities use specific attack types**: `move`, `melee`, `cast`, `jump`, `end_move_attack`. `abilityCast` is NOT recognized.

3. **The `buff` object** (`buffTarget_`, `buff.sid`, `buff.duration`) IS a legitimate mechanism. Medusa's stone gaze uses it. It's the key to implementing Bloodlust, Battle Cry, Howl, etc.

4. **The `targetMechanics` array** supports 56 mechanics including `push_unit`, `kill_stacks`, `dispel`, `damage`, `berserk`, `add_energy` — these are the building blocks for ability effects.

5. **Donor-cloning is a ceiling, not the destination** — Tiers 2-4 need C# Harmony patches to reach full potential.

6. **Animation safety**: Each unit uses the same ability patterns as its Dungeon donor, ensuring compatible animations. No custom animations needed.
