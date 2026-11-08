================================================================================
  Damage forecast histogram — BepInEx plugin
  (Combat kill-distribution chart next to the game’s damage preview)
================================================================================

REQUIREMENTS
- A PC build of the game with BepInEx 6+ and IL2CPP / Il2CppInterop set up
  the same way you use for any other BepInEx mod for this title. This archive
  contains only the plugin files, not a full BepInEx install.

WHAT IS IN THIS ZIP
- BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll
- BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.deps.json
- BepInEx\plugins\OfflineUnlockMod\config.json.example  (copy to config.json
  to enable and tune the histogram — see below)

FEATURE
- When enabled, the mod shows a small bar chart of the probability of each
  number of units killed, derived from the game’s own min/max damage forecast
  (with an optional model layered on top — see the mod author’s technical notes
  if provided). It does not replace the game’s combat resolution.

INSTALL
1) Close the game.
2) Extract this archive into your game directory (the folder that contains the
   game executable and the BepInEx folder), so you end up with:
   <Game>\BepInEx\plugins\OfflineUnlockMod\OfflineUnlockMod.dll
3) Copy config.json.example to config.json in the same
   BepInEx\plugins\OfflineUnlockMod\ folder. Edit and set
   "damageHistograms": true  (or leave false to load the mod with the chart off).
4) Start the game. Check BepInEx\LogOutput.log if the plugin does not load.

CONFIG (BepInEx\plugins\OfflineUnlockMod\config.json)
- damageHistograms — set true to show the chart (off by default).
- damageHistogramChartWidthPx, damageHistogramChartHeightPx, damageHistogramGapPx
  — layout.
- damageHistogramConvolutionMaxUnits — performance cap for the damage PMF
  (see mod documentation for safe ranges).

TROUBLESHOOTING
- If there is no chart: ensure damageHistograms is true, and you are previewing
  a normal unit weapon attack (not spells/abilities the mod intentionally skips).
- If the game crashes: remove the plugin DLL or set options to minimal values;
  keep a copy of LogOutput.log for the mod author.

DISCLAIMER
- Unofficial add-on, not affiliated with the publisher. Use at your own risk.

================================================================================
