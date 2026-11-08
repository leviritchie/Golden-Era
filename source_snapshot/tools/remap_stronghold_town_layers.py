#!/usr/bin/env python3
"""
Edit the HoMM3 Stronghold town building-to-layer map.
This only changes city-screen visuals. It does not rename buildings or change
the building SIDs used by city data, prerequisites, icons, or localization.

Examples:
  python tools/remap_stronghold_town_layers.py
  python tools/remap_stronghold_town_layers.py --gui
  python tools/remap_stronghold_town_layers.py --list
  python tools/remap_stronghold_town_layers.py --tier-order dwellingUp2Lvl3,dwellingUp2Lvl1,dwellingUp2Lvl2,dwellingUp2Lvl4,dwellingUp2Lvl5,dwellingUp2Lvl6,dwellingUp2Lvl7
  python tools/remap_stronghold_town_layers.py --set Build_Tier_1=dwellingUp2Lvl3 --set Build_Tier_3=dwellingUp2Lvl1
  python tools/remap_stronghold_town_layers.py --reset
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_LAYERS_DIR = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "town_scene_refs"
    / "homm3_stronghold"
    / "layers"
)
DEPLOYED_LAYERS_DIR = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "BepInEx"
    / "plugins"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "town_scene_refs"
    / "homm3_stronghold"
    / "layers"
)
ENGLISH_CITIES_TEXT_PATH = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "HeroesOE_Data"
    / "StreamingAssets"
    / "Lang"
    / "english"
    / "texts"
    / "cities.json"
)
MAP_NAME = "building_layer_map.json"
THUMB_MAX_W = 96
THUMB_MAX_H = 72

DEFAULT_MAP = {
    "Build_Tier_1": "dwellingUp2Lvl1",
    "Build_Tier_2": "dwellingUp2Lvl2",
    "Build_Tier_3": "dwellingUp2Lvl3",
    "Build_Tier_4": "dwellingUp2Lvl4",
    "Build_Tier_5": "dwellingUp2Lvl5",
    "Build_Tier_6": "dwellingUp2Lvl6",
    "Build_Tier_7": "dwellingUp2Lvl7",
    "Build_Main": "extraCapitol",
    "Build_Tavern": "tavern",
    "Build_Market": "market",
    "Build_Artifact_Market": "artifactMarket",
    "Build_Magic_Guild": "magicGuild",
    "Build_Bank": "bank",
    "Build_Treasury": "artifactMarket",
    "Build_Resource_Depot": "resourceDepot",
    "Build_Resource_Depot_level_2": "resourceDepot",
    "Build_Wall": "wall",
    "Build_Gymnasium": "spyNetwork",
    "Build_Lyceum": "horde1",
    "Build_Spy_Network": "lyceum",
}

FALLBACK_BUILDING_NAMES = {
    "Build_Tier_1": "Goblin Hut",
    "Build_Tier_2": "Wolf Pen",
    "Build_Tier_3": "Orc Tower",
    "Build_Tier_4": "Ogre Fort",
    "Build_Tier_5": "Cliff Nest",
    "Build_Tier_6": "Cyclops Cave",
    "Build_Tier_7": "Behemoth Crag",
    "Build_Main": "Byzantine Palace",
    "Build_Tavern": "Tavern",
    "Build_Market": "Marketplace",
    "Build_Artifact_Market": "Artifact Merchant",
    "Build_Magic_Guild": "Mage Guild",
    "Build_Bank": "Bank",
    "Build_Treasury": "Treasury",
    "Build_Resource_Depot": "Resource Depot",
    "Build_Resource_Depot_level_2": "Alchemic Depot",
    "Build_Wall": "Fortifications",
    "Build_Gymnasium": "Gymnasium",
    "Build_Lyceum": "Lyceum",
    "Build_Spy_Network": "Spy Network",
}

BUILDING_NAME_TOKEN_ALIASES = {
    "Build_Spy_Network": [
        "Homm3Stronghold_Build_Unic_Graal_name",
    ],
}


def load_english_city_tokens() -> dict[str, str]:
    if not ENGLISH_CITIES_TEXT_PATH.exists():
        return {}
    try:
        data = json.loads(ENGLISH_CITIES_TEXT_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    tokens = data.get("tokens", [])
    if not isinstance(tokens, list):
        return {}
    return {
        str(token["sid"]): str(token.get("text", ""))
        for token in tokens
        if isinstance(token, dict) and "sid" in token
    }


def building_name_token_candidates(building_sid: str) -> list[str]:
    candidates = list(BUILDING_NAME_TOKEN_ALIASES.get(building_sid, []))
    if building_sid == "Build_Resource_Depot_level_2":
        candidates.append("Homm3Stronghold_Build_Resource_Depot_name_level_2")
    else:
        candidates.extend(
            [
                f"Homm3Stronghold_{building_sid}_name_level_1",
                f"Homm3Stronghold_{building_sid}_name",
            ]
        )
    return candidates


def load_building_display_names() -> dict[str, str]:
    tokens = load_english_city_tokens()
    names: dict[str, str] = {}
    for building_sid in DEFAULT_MAP:
        for token_sid in building_name_token_candidates(building_sid):
            text = tokens.get(token_sid)
            if text:
                names[building_sid] = text
                break
        else:
            names[building_sid] = FALLBACK_BUILDING_NAMES.get(building_sid, building_sid)
    return names


def load_positions(layers_dir: Path) -> set[str]:
    positions_path = layers_dir / "positions.json"
    if not positions_path.exists():
        return set()
    data = json.loads(positions_path.read_text(encoding="utf-8"))
    raw = data.get("layers", [])
    if isinstance(raw, list):
        return {str(entry["id"]) for entry in raw if "id" in entry}
    if isinstance(raw, dict):
        return set(raw)
    return set()


def resolve_layer_sprite_path(layer_id: str, layers_dir: Path = SOURCE_LAYERS_DIR) -> Path | None:
    layer_id = (layer_id or "").strip()
    if not layer_id:
        return None
    candidates = [
        layers_dir / f"{layer_id}_1.png",
        layers_dir / f"{layer_id}_2.png",
        layers_dir / f"{layer_id}_3.png",
        layers_dir / f"{layer_id}_4.png",
        layers_dir / f"{layer_id}.png",
        layers_dir / f"layer_{layer_id}.png",
    ]
    return next((path for path in candidates if path.exists()), None)


def load_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return dict(DEFAULT_MAP)
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("buildingLayerIds", data.get("map", {}))
    merged = dict(DEFAULT_MAP)
    merged.update({str(k): str(v) for k, v in raw.items() if v})
    return merged


def write_map(path: Path, mapping: dict[str, str]) -> None:
    blob = {
        "_comment": (
            "Runtime Stronghold town visual mapping. Keys are Olden Era building SIDs; "
            "values are layer IDs from positions.json. Edit and re-enter the city to apply "
            "after the updated plugin DLL is deployed."
        ),
        "buildingLayerIds": {key: mapping[key] for key in DEFAULT_MAP if key in mapping},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")


def parse_set_args(items: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"--set requires BUILDING=layerId, got: {item}")
        building, layer = item.split("=", 1)
        building = building.strip()
        layer = layer.strip()
        if not building or not layer:
            raise SystemExit(f"--set requires BUILDING=layerId, got: {item}")
        parsed[building] = layer
    return parsed


def apply_tier_order(mapping: dict[str, str], value: str) -> None:
    layer_ids = [part.strip() for part in value.split(",") if part.strip()]
    if len(layer_ids) != 7:
        raise SystemExit("--tier-order needs exactly 7 comma-separated layer IDs")
    for index, layer_id in enumerate(layer_ids, start=1):
        mapping[f"Build_Tier_{index}"] = layer_id


def validate(mapping: dict[str, str], valid_layers: set[str]) -> list[str]:
    warnings: list[str] = []
    valid_buildings = set(DEFAULT_MAP)
    for building, layer in mapping.items():
        if building not in valid_buildings:
            warnings.append(f"unknown building SID: {building}")
        if valid_layers and layer not in valid_layers:
            warnings.append(f"{building} maps to unknown layer ID: {layer}")
    return warnings


def backup(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, path.with_suffix(path.suffix + f".bak-{stamp}"))


def target_paths(source_only: bool) -> list[Path]:
    targets = [SOURCE_LAYERS_DIR / MAP_NAME]
    deployed = DEPLOYED_LAYERS_DIR / MAP_NAME
    if not source_only and DEPLOYED_LAYERS_DIR.exists():
        targets.append(deployed)
    return targets


def print_mapping(mapping: dict[str, str]) -> None:
    for key in DEFAULT_MAP:
        if key in mapping:
            print(f"{key:30} -> {mapping[key]}")


def launch_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except Exception as ex:
        raise SystemExit(f"Tkinter is unavailable, cannot launch GUI: {ex}") from ex
    try:
        from PIL import Image, ImageTk
    except Exception:
        Image = None
        ImageTk = None

    source_path = SOURCE_LAYERS_DIR / MAP_NAME
    mapping = load_map(source_path)
    valid_layers = sorted(load_positions(SOURCE_LAYERS_DIR))
    if not valid_layers:
        valid_layers = sorted(set(DEFAULT_MAP.values()))
    building_names = load_building_display_names()

    root = tk.Tk()
    root.title("Stronghold Town Layer Remapper")
    root.geometry("900x720")
    root.minsize(820, 500)

    source_only = tk.BooleanVar(value=False)
    status = tk.StringVar(
        value=(
            f"Editing {source_path}. "
            "This only remaps visuals; fix wrong building SIDs in the city generator/data."
        )
    )
    selected: dict[str, tk.StringVar] = {}
    preview_labels: dict[str, ttk.Label] = {}
    preview_images: dict[str, object] = {}
    thumb_cache: dict[str, object] = {}

    frame = ttk.Frame(root, padding=10)
    frame.pack(fill=tk.BOTH, expand=True)

    top = ttk.Frame(frame)
    top.pack(fill=tk.X)
    ttk.Label(top, text="Building").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
    ttk.Label(top, text="Current data name").grid(row=0, column=1, sticky=tk.W, padx=(0, 10))
    ttk.Label(top, text="Sprite").grid(row=0, column=2, sticky=tk.W, padx=(0, 10))
    ttk.Label(top, text="Visual layer").grid(row=0, column=3, sticky=tk.W)

    rows_outer = ttk.Frame(frame)
    rows_outer.pack(fill=tk.BOTH, expand=True, pady=(6, 8))
    canvas = tk.Canvas(rows_outer, highlightthickness=0)
    scrollbar = ttk.Scrollbar(rows_outer, orient=tk.VERTICAL, command=canvas.yview)
    rows = ttk.Frame(canvas)
    rows.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas_window = canvas.create_window((0, 0), window=rows, anchor=tk.NW)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))

    def make_options(current: str) -> list[str]:
        options = list(valid_layers)
        if current and current not in options:
            options.insert(0, current)
        return options

    def get_thumbnail(layer_id: str):
        layer_id = (layer_id or "").strip()
        if not layer_id:
            return None
        if layer_id in thumb_cache:
            return thumb_cache[layer_id]
        path = resolve_layer_sprite_path(layer_id)
        if path is None:
            thumb_cache[layer_id] = None
            return None
        try:
            if Image is not None and ImageTk is not None:
                image = Image.open(path).convert("RGBA")
                image.thumbnail((THUMB_MAX_W, THUMB_MAX_H), Image.LANCZOS)
                thumb = ImageTk.PhotoImage(image)
            else:
                thumb = tk.PhotoImage(file=str(path))
                step = max(1, int(max(thumb.width() / THUMB_MAX_W, thumb.height() / THUMB_MAX_H)))
                if step > 1:
                    thumb = thumb.subsample(step, step)
            thumb_cache[layer_id] = thumb
            return thumb
        except Exception:
            thumb_cache[layer_id] = None
            return None

    def update_preview(building: str) -> None:
        label = preview_labels.get(building)
        if label is None:
            return
        layer_id = selected[building].get().strip()
        thumb = get_thumbnail(layer_id)
        if thumb is None:
            preview_images.pop(building, None)
            label.configure(image="", text="missing")
            return
        preview_images[building] = thumb
        label.configure(image=thumb, text="")

    for row_index, building in enumerate(DEFAULT_MAP):
        value = mapping.get(building, DEFAULT_MAP[building])
        selected[building] = tk.StringVar(value=value)
        ttk.Label(rows, text=building, width=28).grid(row=row_index, column=0, sticky=tk.W, padx=(0, 10), pady=2)
        ttk.Label(rows, text=building_names.get(building, building), width=24).grid(
            row=row_index,
            column=1,
            sticky=tk.W,
            padx=(0, 10),
            pady=2,
        )
        preview = ttk.Label(rows, width=14, anchor=tk.CENTER)
        preview.grid(row=row_index, column=2, sticky=tk.W, padx=(0, 10), pady=2)
        preview_labels[building] = preview
        combo = ttk.Combobox(
            rows,
            textvariable=selected[building],
            values=make_options(value),
            state="normal",
            width=34,
        )
        combo.grid(row=row_index, column=3, sticky=tk.EW, pady=2)
        combo.bind("<<ComboboxSelected>>", lambda _event, key=building: update_preview(key))
        combo.bind("<FocusOut>", lambda _event, key=building: update_preview(key))
        selected[building].trace_add("write", lambda *_args, key=building: update_preview(key))
        update_preview(building)
    rows.columnconfigure(3, weight=1)

    def current_mapping() -> dict[str, str]:
        return {building: selected[building].get().strip() for building in DEFAULT_MAP}

    def set_mapping(new_mapping: dict[str, str]) -> None:
        for building in DEFAULT_MAP:
            selected[building].set(new_mapping.get(building, DEFAULT_MAP[building]))
            update_preview(building)

    def show_validation_warnings(new_mapping: dict[str, str]) -> bool:
        warnings = validate(new_mapping, set(valid_layers))
        if not warnings:
            return True
        return messagebox.askyesno(
            "Unknown layer IDs",
            "These mappings reference unknown layer IDs:\n\n"
            + "\n".join(warnings)
            + "\n\nSave anyway?",
        )

    def save() -> None:
        new_mapping = current_mapping()
        missing = [building for building, layer in new_mapping.items() if not layer]
        if missing:
            messagebox.showerror("Missing layer IDs", "Every building needs a layer ID.")
            return
        if not show_validation_warnings(new_mapping):
            return
        written: list[str] = []
        for path in target_paths(source_only.get()):
            backup(path)
            write_map(path, new_mapping)
            written.append(str(path))
        status.set("Saved " + ", ".join(written))
        messagebox.showinfo("Saved", "Wrote:\n\n" + "\n".join(written) + "\n\nRe-enter the city to apply.")

    def reload_from_disk() -> None:
        set_mapping(load_map(source_path))
        status.set("Reloaded source mapping.")

    def reset_defaults() -> None:
        if messagebox.askyesno("Reset mapping", "Reset all rows to the default Stronghold mapping?"):
            set_mapping(dict(DEFAULT_MAP))
            status.set("Reset to defaults. Click Save to write changes.")

    controls = ttk.Frame(frame)
    controls.pack(fill=tk.X, pady=(0, 6))
    ttk.Checkbutton(controls, text="Source only", variable=source_only).pack(side=tk.LEFT)
    ttk.Button(controls, text="Reload", command=reload_from_disk).pack(side=tk.RIGHT, padx=(6, 0))
    ttk.Button(controls, text="Reset defaults", command=reset_defaults).pack(side=tk.RIGHT, padx=(6, 0))
    ttk.Button(controls, text="Save", command=save).pack(side=tk.RIGHT)

    ttk.Label(frame, textvariable=status, wraplength=720).pack(fill=tk.X)
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--gui", action="store_true", help="Launch the GUI remapper.")
    parser.add_argument("--list", action="store_true", help="Print the current source mapping.")
    parser.add_argument("--reset", action="store_true", help="Restore the default mapping.")
    parser.add_argument("--set", action="append", default=[], metavar="BUILDING=layerId", help="Set one mapping entry.")
    parser.add_argument("--tier-order", help="Comma-separated layer IDs assigned to Build_Tier_1 through Build_Tier_7.")
    parser.add_argument("--source-only", action="store_true", help="Do not mirror changes into the deployed plugin copy.")
    parser.add_argument("--no-backup", action="store_true", help="Do not create .bak timestamp copies before writing.")
    args = parser.parse_args()

    if args.gui or len(sys.argv) == 1:
        return launch_gui()

    source_path = SOURCE_LAYERS_DIR / MAP_NAME
    mapping = load_map(source_path)
    if args.list and not (args.reset or args.set or args.tier_order):
        print_mapping(mapping)
        return 0

    if args.reset:
        mapping = dict(DEFAULT_MAP)
    if args.tier_order:
        apply_tier_order(mapping, args.tier_order)
    mapping.update(parse_set_args(args.set))

    warnings = validate(mapping, load_positions(SOURCE_LAYERS_DIR))
    if warnings:
        for warning in warnings:
            print(f"WARNING: {warning}")

    for path in target_paths(args.source_only):
        if not args.no_backup:
            backup(path)
        write_map(path, mapping)
        print(f"Wrote {path}")

    print()
    print_mapping(mapping)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
