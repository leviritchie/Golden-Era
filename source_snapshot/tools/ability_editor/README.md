# HoMM3 Unit Ability Editor

This is a local generator-facing GUI for selecting and editing custom unit ability, hero, and law-tree overrides. It reads `custom_factions/*.json`, shows the current generated or shipped unit/hero/law data, and saves reviewable override files under `custom_factions/ability_overrides/`, `custom_factions/hero_overrides/`, and `custom_factions/law_overrides/`.

Run it from the repo root:

```powershell
python tools\ability_editor\server.py --port 8765
```

Then open `http://127.0.0.1:8765`.

Restart the server after pulling or applying editor changes; the browser talks to whichever local Python process is currently bound to the port.

The editor deliberately does not mutate `Core.zip` or generated Core rows directly. Ability templates live in `tools/ability_editor/ability_templates.json`; add new templates there only after the native mechanic shape is known-good or explicitly marked as advanced/static-trace debt.

Current-data lookup prefers `experiments/<faction>/generated_core_overlay/` when it exists, then falls back to the patched Golden Era install `Core.zip` under `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`. Do not point the editor at the stock game `Core.zip`; that archive has no `DB/units/units_logics/homm3_*` rows, so custom units will appear to have no abilities.

The toolbar browsers are repo indexes:

- **Browse Effects** indexes vanilla unit logic/view rows from `Core.zip` plus generated overlays. It includes mechanics, mechanic values, buff SIDs, projectile keys, icon keys, and ability types, with source rows shown on each result.
- **Pick Icon** scans local PNG asset roots, including AssetRipper's `Resources/icons` export and custom law icon folders, and displays donor icon candidates visually. It also includes current law runtime icon keys even when no local preview PNG is available. Click an input field first, then choose an icon to fill that field.

Existing unit specials are shown separately from new override abilities. Editing or unchecking those cards records reviewable `existingSpecials` instructions; the editor still does not rewrite generated Core rows directly. Existing-special cards expose the unit-ability envelope controls that affect cost and presentation, including animation, Focus cost, cooldown, rank, and charges.

For `h3_*` view rows, the editor also infers the sibling `_description` localization key from the `_name` key when the view row's description field is blank or stale. Icon fields have explicit **Pick Icon** buttons, and existing-special cards can record an `iconKey` override candidate.

Icon selections must be runtime sprite keys, not raw AssetRipper filename noise or localization tokens. Avoid keys with scale suffixes such as `Orientation@4x` and text keys such as `*_name` / `*_description`; use concrete donor sprite keys such as `assassin_buff_icon` or spell icon keys such as `space_6_magic_blink`. The icon browser still shows preview-only art for unsafe filenames so agents can inspect the donor art pool, but disabled preview cards cannot be selected. The generator ignores already-saved invalid icon override keys and falls back to the selected effect's native icon where possible.

Some shared custom-faction strings are generator constants rather than emitted overlay files. The editor indexes literal `{"sid": "...", "text": "..."}` rows from `tools/release_port/apply_release_core_overlay.py` so current-special cards resolve those in-progress `h3_*` keys too.

The panel UI keeps typing limited to user-facing names/descriptions and known free-form identifiers. Internal choices such as ability type, native effects, law effect types, projectiles, numeric ranks/costs, and icons are selected from dropdowns, numeric fields, or the effect/icon browsers.

The **Laws** mode edits generated faction-law rows. Each law exposes display name, description, a visual runtime icon preview/selector, point-spend unlock tier from the faction's `fractionLawsLines[].countToUnlock`, tree position, per-level purchase cost, and structured effect cards for the generator-supported law bonus rows. Unit and faction references should be selected from readable dropdowns/chips while saving the underlying SID. Do not replace those effect controls with a raw JSON textarea; if a current law row cannot be represented, extend the structured controls and validator. Saved law overrides are consumed by `tools/release_port/apply_release_core_overlay.py` when regenerating Core law tables and `Lang/english/texts/factionLaws.json`.

Use the **Copied Donor Unit Special** template for whole native unit specials that are not simple buff/debuff templates, including alternate attacks like Assassin Fighting Style: Hit and Run.

Saved overrides currently use this shape:

```json
{
  "schemaVersion": 1,
  "factionSid": "homm3_tower",
  "unitOverrides": {
    "h3_gremlin_upg_alt": {
      "replaceExistingAbilities": false,
      "replaceExistingPassives": false,
      "abilities": []
    }
  }
}
```

Promotion rule: treat these files as review input for `tools/release_port/apply_release_core_overlay.py`. Before wiring a new override into generation, compare the emitted logic row, view row, Lang tokens, icon key support, and battle UI behavior against a copied native template.
