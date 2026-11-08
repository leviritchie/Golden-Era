# HoMM3 Stronghold Canonical Town Animations

Source of record: original local HoMM3 Complete asset archive `HoMM 3 Complete/Data/H3sprite.lod`, parsed directly from the `TBSt*.def` DEF sequence tables on 2026-05-04.

Rule: a Stronghold town-screen building is canonically animated only when its original DEF has more than one frame in group 0. The current Olden Era Stronghold layer extraction scripts often save only frame 0 as PNG, so those PNG layers are not authoritative for animation support.

## Animated DEFs

| Original DEF | Frames | Canonical building/use |
| --- | ---: | --- |
| `TBStDw_6.def` | 10 | Base level-7 Behemoth Lair |
| `TBStUp_5.def` | 10 | Upgraded level-6 Cyclops Cave |
| `TBStUp_6.def` | 10 | Upgraded level-7 Behemoth Lair |
| `TBStHall.def` | 20 | Village Hall |
| `TBStHal2.def` | 20 | Town Hall |
| `TBStHal3.def` | 20 | City Hall |
| `TBStHal4.def` | 20 | Capitol |
| `TBStHoly.def` | 10 | Grail structure |
| `TBStSpec.def` | 20 | Special building visual used by Stronghold town screen |
| `TBStExt3.def` | 20 | Special/extra Stronghold town-screen building visual |

## Static DEFs

All other original `TBSt*.def` entries in `H3sprite.lod` have one group-0 frame and should be treated as static: `TBStBlak.def`, `TBStCas2.def`, `TBStCas3.def`, `TBStCstl.def`, `TBStDw_0.def` through `TBStDw_5.def`, `TBStExt0.def`, `TBStExt1.def`, `TBStExt2.def`, `TBStHrd1.def`, `TBStHrd2.def`, `TBStMag2.def`, `TBStMag3.def`, `TBStMage.def`, `TBStMark.def`, `TBStSilo.def`, `TBStTvrn.def`, and `TBStUp_0.def` through `TBStUp_4.def`.

Warning: do not infer canonical animation from `homm3_runtime_assets/town_scene_refs/homm3_stronghold/layers/*.png`; those files are cropped still frames. If town animation parity is needed, re-extract full DEF frame sequences from `H3sprite.lod` and preserve per-frame timing/looping in the Olden Era layer renderer.
