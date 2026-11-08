# HoMM3 Ownership Check For Release

Date: May 5, 2026.

Scope: local validation that a user has either HoMM3 Complete or HoMM3 HD Edition installed before enabling the HoMM3-themed Stronghold mod content. This is an ownership/friction check, not real DRM. It should avoid extracting, copying, hashing whole asset archives, or reading proprietary art/audio payloads.

## Recommendation

Use a layered install-presence check:

1. Accept an explicit user-configured path first, e.g. `homm3OwnershipPath` in `BepInEx/plugins/OfflineUnlockMod/config.json`.
2. Auto-detect GOG HoMM3 Complete by Windows uninstall registry product id `1207658787_is1`, then validate only stable top-level files.
3. Auto-detect Steam HoMM3 HD Edition by Steam app id `297000`, preferably through the uninstall registry `Steam App 297000` `InstallLocation`, with Steam library manifest parsing as fallback.
4. Validate a candidate directory by checking marker files and minimum sizes, not by opening archives:
   - Complete/GOG: `Heroes3.exe`, `goggame-1207658787.info`, `Data/H3bitmap.lod`, `Data/H3sprite.lod`, `Data/Heroes3.snd`, `Data/VIDEO.VID`.
   - HD/Steam: `HOMM3Launcher.exe`, `HOMM3 2.0.exe`, `steam_api.dll`, `data/bitmap_DXT_com_x2.pak`, `data/sprite_DXT_com_x2.pak`.
5. If no valid install is found, disable only the HoMM3-derived content and show/log a clear message telling the user to set the path or install HoMM3 Complete/HD. Do not crash startup and do not block unrelated mod features.

This is stronger than checking for a folder name but still avoids asset extraction. It also does not prove ownership against copied files, so wording should be "requires a local install" rather than "DRM".

## Local Evidence

- Local GOG Complete install has uninstall key `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\1207658787_is1`, display name `Heroes of Might and Magic 3 Complete`, and `InstallLocation` pointing at a HoMM3 Complete folder.
- The local GOG marker file `goggame-1207658787.info` identifies `gameId`/`rootGameId` `1207658787`, `name` `Heroes of Might and Magic 3 Complete`, and primary play task `Heroes3.exe`.
- Local GOG Complete data markers are present without extraction: `Data/H3bitmap.lod`, `Data/H3sprite.lod`, `Data/Heroes3.snd`, and `Data/VIDEO.VID`.
- Local Steam HD Edition has uninstall key `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 297000`, display name `Heroes of Might & Magic III - HD Edition`, and `InstallLocation` pointing at the Steam common folder.
- Local Steam manifest `appmanifest_297000.acf` has appid `297000`, name `Heroes of Might & Magic III - HD Edition`, installdir `Heroes of Might & Magic III - HD Edition`, state flags `4`, and installed depots `297001`/`297002`.
- Local Steam HD data markers are present without extraction: `HOMM3Launcher.exe`, `HOMM3 2.0.exe`, `steam_api.dll`, `data/bitmap_DXT_com_x2.pak`, and `data/sprite_DXT_com_x2.pak`.

## Public Metadata

- SteamDB lists HoMM3 HD Edition app id `297000`, install dir `Heroes of Might & Magic III - HD Edition`, and launch executable `HOMM3Launcher.exe`.
- SteamDB lists HD Edition Windows content depot `297001` and language depots such as English depot `297002`, matching the local `appmanifest_297000.acf`.
- GOGDB lists HoMM3 Complete product/root product id `1207658787` and install directory `HoMM 3 Complete/`.

Sources checked May 5, 2026:

- https://steamdb.info/app/297000/config/
- https://steamdb.info/app/297000/depots/
- https://www.gogdb.org/product/1207658787/build/1701

## Implementation Notes

- Put detection in a small standalone helper, e.g. `Homm3OwnershipCheck`, invoked early after `LauncherConfigReader.TryLoad()` and before registering HoMM3 import/Stronghold hooks.
- Keep the result cached for the process. Registry and manifest reads should happen once during plugin load.
- Use `Microsoft.Win32.RegistryKey` for registry reads. Check both 64-bit and 32-bit uninstall hives and HKCU uninstall as a fallback.
- For Steam fallback, parse `steamapps/libraryfolders.vdf` and then `steamapps/appmanifest_297000.acf`. Do not require Steam to be running and do not call Steam APIs.
- For GOG fallback, look for `goggame-1207658787.info` only after a plausible path is found; do not scan whole drives.
- Config should support an override path because portable, Heroic, Lutris/Wine, and copied GOG installs may not have Windows registry entries.
- Emit one concise log line with the detected edition and path. Avoid logging file hashes or inventory dumps.
- The release package should not include extracted HoMM3 assets. This check is only a gating signal for content already shipped in the mod package or generated from non-infringing sources.

## Warnings

- Do not use runtime probes that require the user to launch HoMM3. Static local file/registry/manifest detection is enough for the release gate.
- Do not read or extract `*.lod`, `*.snd`, `*.vid`, or `*.pak` contents for this check. Presence and rough size markers are adequate.
- Do not make the check destructive or network-dependent. Offline users with a valid local install should pass.
- Do not market this as cryptographic DRM. It is an install ownership check intended to show good-faith dependence on a legitimate HoMM3 install.
