# Golden Era Codex

A static, searchable site of every custom creature, upgrade branch and town building in the mod,
styled after Olden Era's own unit window and build screen. It is meant for GitHub Pages on the
public repo, and it is rebuilt from the game data on every release, so it does not need hand edits.

## Files

| File | Role |
| --- | --- |
| `export_codex.py` | Reads a Core.zip plus the faction manifests and writes a complete site folder: `data/codex.json`, `img/` and the files in `site/`. |
| `site/` | The page itself: `index.html`, `codex.css`, `codex.js`. Plain HTML/CSS/JS, no build step. |
| `publish_pages.ps1` | Mirrors a built site onto the public repo's `gh-pages` branch. Commits only when something changed; pushes only with `-Push`. |
| `pages.json` | The publish switch. `publish: false` until the owner approves the page. |

## Where the content comes from

Nothing on the page is written by hand. A change to the mod shows up on the next build.

| Page content | Source |
| --- | --- |
| Lines and upgrade branches | Each dwelling's `unitsHire` list in `DB/objects_logic/cities/<city>.json`, in the game's order (base, upgrade, alternate upgrade). Manifest `unitLines` are not used, because several lines were renamed after the manifests were written. |
| Stats, cost, movement, ranged | `DB/units/units_logics/<faction>/*.json` |
| Ability cards, creature type | `DB/units/units_views/<faction>/*.json`, the same cards the in-game unit window shows |
| All text | `Lang/english/texts/*.json`. `{0}`-style arguments are resolved from `Lang/args` and `DB/info/*.script` the way the game does. An argument the script cannot resolve prints `?` and is listed under `unresolvedArgs` in the export report. |
| Building tree layout | `nodePos` and `prevBuildings` per level in the city logic, so the grid matches the in-game build screen |
| Growth | The dwelling's `weeklyIncrement` |
| Conflux fusion parents | `custom_factions/conflux_fusion/fusion_units.json` (host and guest) |
| Neutrals | `DB/units/units_logics/neutral/h3_*` |
| Portraits, ability icons, crests | `OfflineUnlockMod/homm3_portraits`, `homm3_skill_icons`, the manifests' `assets.factionIcon`. Converted to WebP. |

Ability cards that use a stock Olden Era icon (not shipped with the mod) get a drawn gold glyph instead.

## Build and preview

```
python tools/unit_codex/export_codex.py --out V:/olden_port_work/unit_codex/site
python -m http.server 8765 --bind 127.0.0.1 --directory V:/olden_port_work/unit_codex/site
```

- The default `--core` is the installed Golden Era `Core.zip`, which is the Core the release payload is built from.
- `--no-images` gives a data-only rebuild in under a second.
- A full build with images takes about 11 seconds and writes about 8 MB. Rebuilds into the same folder re-encode only images whose source changed, which takes under a second.
- It uses CPU only: JSON reads and WebP encoding. There is no GPU work.
- The page must be served over HTTP, because `fetch` of `data/codex.json` fails from `file://`.

The exporter prints a JSON report. It lists missing portraits, units with no ability cards, and any text arguments it could not resolve.

## Automatic updates

`tools/nightly/nightly_release.ps1` runs a `codex` step right after staging, while the staged plugin folder still exists.

1. It takes `tools/unit_codex` and the manifests from the release commit with `git archive`, so uncommitted edits in the checkout never reach the page.
2. It runs the exporter against the Golden Era `Core.zip` (the same Core the stager reads) and the staged, scrubbed plugin folder.
3. It leak-scans the site with `tools/nightly/payload_leaks.py`, using the same terms as the payload. A site that fails the scan is deleted.

After a successful publish, the nightly reads `pages.json` at the release commit and runs `publish_pages.ps1 -Push` only when `publish` is `true`.

| `follow` | The page is refreshed on |
| --- | --- |
| `release` (default) | versioned releases published with `-Latest`, so the page matches what most players install |
| `nightly` | every published run, nightly prereleases included |

- **Dry runs** keep the site in `<WorkDir>/codex` next to the assets folder. The summary records the path as `codexDir`.
- **A codex failure never fails a release.** The summary records the build as `codex` (counts, size, or the error) and the push as `codexPages`.

## Turning it on (one time)

1. Set `"publish": true` in `pages.json` and commit.
2. Run `publish_pages.ps1 -Site <built site> -Label <version> -Push` once, or wait for the next release. This creates the `gh-pages` branch.
3. On GitHub, open the public repo and go to **Settings > Pages**. Set **Build and deployment** to *Deploy from a branch*, branch `gh-pages`, folder `/ (root)`.
4. The site appears at `https://leviritchie.github.io/Golden-Era/`.

No workflow file is added, so the release pipeline's check that no public workflow fires on push, tag or release stays valid.
