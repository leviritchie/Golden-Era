# Custom Unit Ability Catalog UI

Browse-first local web UI for every custom HoMM3 unit’s actives, passives, Focus costs, cooldowns, and hire prices.

## Run

From the repo root:

```powershell
$env:PYTHONUTF8 = '1'
python tools\unit_ability_catalog\server.py
```

Then open `http://127.0.0.1:8766` (the server opens a browser tab by default).

Useful flags:

```powershell
python tools\unit_ability_catalog\server.py --port 8766 --skip-regenerate --no-open
```

If the page fails to load or the connection drops immediately, an old dead Python process is usually still bound to the port. Stop those listeners (Task Manager / `taskkill`) or rerun the server — it now walks forward up to 20 ports when `8766` is busy and prints the URL it actually bound.

## Data

- `static/catalog.json` is generated from the active Golden Era `Core.zip`.
- Markdown twin: `docs/homm3_custom_unit_ability_catalog.md`
- Portraits are served from `OfflineUnlockMod/homm3_portraits/`

Regenerate without starting the server:

```powershell
python tools\generate_homm3_custom_unit_ability_catalog.py
```

## Proof boundary

This UI is **installed payload readback**. It shows what Core currently names, describes, and costs. It does not prove runtime battle behavior for every mechanic.
