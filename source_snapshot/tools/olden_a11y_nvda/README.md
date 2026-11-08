# Olden A11y NVDA Companion

Watches `focus_latest.json` (preferred) or `hover_latest.json` and speaks speech-safe utterances through NVDA Controller Client.

```powershell
python tools\olden_a11y_nvda\watch_hover_nvda.py --bridge-dir "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\ai_driver_bridge"
```

Requires NVDA running and `nvdaControllerClient*.dll`. Does not read `screen_dump`. See `docs/ai_screen_perception_nvda_consumer.md`.
