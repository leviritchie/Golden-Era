# HoMM3 Masterful Spell Specialist Notes

Masterful spell variants are the Olden Era equivalent of HoMM3 spell specialists. Do not implement them as unrelated hero abilities or as mana-discount-only spell clones.

The release-overlay generator should make masterful variants cast as one native spell tier stronger, with the final tier extrapolated from the native top tier when the spell data exposes numeric damage, target-count, or buff-stat values. This data-only tier-promotion route is the current substitute for HoMM3's dynamic `hero level / target creature level` specialty formulas.

Keep bespoke improvements on top of tier promotion when they already map to a HoMM3-like specialty effect, such as extra Thunderbolt targets, Sleep immunity removal, extra traps, larger Energy Explosion area, longer Fatal Decay, or cloned defensive buff rows. If exact HoMM3 formulas are later required, add a traced runtime mechanic instead of fallback behavior or broad spell-power hacks.

Creature specialists should use the specialized HoMM3 creature SID as the specialization icon key, for example `sourceSpecialtyKey="creature:h3_archer"` must use `iconKey="h3_archer"`. This routes through the deployed `homm3_portraits/<sid>.png` portrait cache instead of donor skill icons such as `skill_trainer`.
