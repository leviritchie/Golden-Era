# HoMM3 ↔ Olden object model catalogue

Source/static notes for the raw_translation and approach_cell translators.  
**Why this exists:** The map lens can look “perfect” while gameplay still has wrong pickups, buried markers, or diagonal holes — usually from **misreading ObjectConfig `nodes`**, especially GATE.

---

## 1. ObjectConfig `nodes` (authoritative)

| Value | Meaning |
|-------|---------|
| `nodes == 0` | Open / visual-only cell in the size grid (not occupied) |
| `nodes == 1` | **Occupied body** — blocks pathing; real footprint |
| `nodes == 2` | **GATE — interaction marker only** |

### GATE is a marker, not occupancy

- GATE cells tell the engine **where the object can be interacted from**.
- They are **not** part of the object body for pathing or cell ownership.
- They **do not claim or block** the cells they sit on.
- If another object’s `nodes==1` covers a GATE marker cell, that other object blocks standing there — the GATE did not “lose a fight”; the cell was never owned by the GATE.
- **Shared GATE markers between objects are normal and fine.**
- A footprint that is **GATE-only** (e.g. 1×1 `nodes=[2]` with no occupied body) is wrong for Resource/item/chest pickups: the body is gone → invisible / unpickable terrain.

| Field | Role |
|-------|------|
| `gateInsideObject` | Interact marker is intended on a cell inside the occupied footprint (land-on) |
| `sizeX` / `sizeZ` | Grid for `nodes` |
| `pivotX` / `pivotZ` | Visual / pivot-center placement |
| High `config_z` | Map-south (Olden +Y = north) |
| Rotation 10 | Mirror when `canBeMirrored` |

Anchor: config `(0,0)` at map top-left of the placed grid; south-edge GATE is high `config_z`.

---

## 2. Shape classes and placement

| Class | Pattern | Examples | Correct placement |
|-------|---------|----------|-------------------|
| **Land-on** | 1 GATE marker, rest mostly `1` | `homm3_landon_*` | GATE-align: marker on H3 visit; body north of south GATE |
| **Single-GATE** | Exactly one `2` | `hero-spawner`, portals | GATE-align: marker on H3 visit |
| **GATE-ring + occupied center** | 8×`2` + center `1` | `resource_*`, `chest`, `random-item`, `camp_fire` | **Visit on GATE**: emit `node = H3 visit` (native editor); body sits off the visit |
| **GATE-ring + open center** | 8×`2` + center `0` | `random-squad` | **Pivot**: open center on H3 visit |

### Wrong (retired) ideas

| Mistake | Why it fails |
|---------|----------------|
| 1×1 GATE-only “point pickup” clones | Erases occupied body → pickups vanish / become bare pathable cells |
| Treating shared GATE markers as conflicts | Markers don’t own cells |
| Pivot occupied center onto H3 visit for gold/chest | Visit becomes unwalkable → piles visible but unpickable |
| Reserving `nodes==0` in fer | Open visual cells aren’t functional ownership |

---

## 3. HoMM3 template masks

- `blockMask` bit **0** = blocked (VCMI polarity)
- `visitMask` bit set = visitable destination
- Gold `AVTgold0.def`: **1×1 visitable_blocked** (`block == visit == {(0,0)}`)
- Olden analogue: keep native 3×3 donor; plant like Thirst_for_Power — **`node` on a GATE at the H3 visit**, occupied body offset; `propResParams.value = 0`

---

## 4. Lens honesty

- Pathability paints `nodes==1` as blocked; GATE as tan markers
- Orange = diagonal-squeeze corridors (Olden allows; H3 walls should not)
- Shared GATE markers are **not** a conflict signal

---

## 5. Functional emit reservation (fer)

Reserve for scenery-omit:

- functional **`nodes==1`** (body), and
- functional **`nodes==2`** (markers — scenery occupied there still blocks standing), and
- HoMM3 visit cells

Do **not** reserve `nodes==0`.

---

## 6. Gap-fill

- Seal H3 non-visitable blocks missing Olden occupied
- Never seal GATE marker cells (would bury interact points)
- Cardinal approach skip: **landon / single_gate only** (not every GATE-ring neighbor)
- Diagonal squeeze seal: if **either** knee is an H3-required block, seal both open corridor ends
- Re-run gap-fill after landon_access clears approach scenery

---

## 7. Gold / items / chests

Native donors are always 3×3 with center occupied.  
**Correct:** keep_donor + node on GATE at H3 visit (native map plant) + `propResParams.value = 0`.  
**Incorrect:** pivot occupied body onto visit (forbidden cursor); invent non-zero `value` amounts.

---

## 8. ObjectConfig clones (translator-owned SIDs)

| Clone | Footprint | `gateInsideObject` | Why |
|-------|-----------|--------------------|-----|
| `homm3_random_resource_pickup` / `homm3_flotsam_pickup` | Donor 3×3 GATE-ring + center `1` | **Unset** (match native `resource_*`) | Exterior markers; inventing `True` mislabels ring pickups as land-on |
| `homm3_landon_map_event_marker` | 1×1 `nodes=[2]` FX marker | **Unset** | Deliberate marker-only quest FX — not a Resource body |
| `homm3_landon_*` towns / barracks | Town-style body + south-center marker | **`True`** | Intentional land-on; GATE is the interact cell inside the size grid (not occupied) |
| `exact_homm3_footprint.apply_same_size_clone` | Rewritten `nodes` only | **Preserve donor** | Do not invent `gateInsideObject` just because GATE markers exist |

---

## 9. Localization (`LOC_[sid]`)

Missing LocKit rows render as **`LOC_[token_sid]`**. Homecoming clones and quest names must ship under `Lang/<locale>/texts/{customMaps,mapObjects,dialogues}.json` for every Core locale.

| Surface | Tokens |
|---------|--------|
| Scenario shell / quest log | `homm3_roe_castle_homecoming_*`, `homecoming_intro`, `homecoming_main_goal`, `homecoming_main_goal_desc` in `customMaps.json` |
| Custom objects | `{sid}_name` / `{sid}_description` in `mapObjects.json` |
| Briefings | `dialogue_title_homecoming_*` / `dialogue_text_homecoming_*` in `dialogues.json` |

Owners: `homecoming_localization.py`, `build_homecoming_lang_translations.py`, `tools/install_homecoming_localization.py`.

---

## 10. Code owners

| Concern | Module |
|---------|--------|
| Emit / property bind | `approach_cell/surface_emit.py` |
| Exact footprints / shape class | `exact_homm3_footprint.py` |
| Policy packs | `approach_cell/emit_policy.py` |
| Fer reservation | `functional_emit_reservation.py` |
| Raw orchestrator | `raw_translation/build_raw_translation_map.py` |
| Lens | `tools/map_model_lens_viewer.py` |
| Diagonal squeeze helper | `approach_cell/domains.py` |
| Ground truth | `raw_translation/placement_ground_truth.py` |
| Localization | `homecoming_localization.py` / `tools/install_homecoming_localization.py` |
