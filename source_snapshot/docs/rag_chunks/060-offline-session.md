# RAG Chunk: olden-era-playtest/060-offline-session

Offline unlock re-enables menu buttons, skips early access and demo thank-you screens, hides the demo overlay, and intercepts Quick Start/New Game clicks.

Patched surfaces include `ScMainMenu`, `MainMenuNavigationView`, `ScEarlyAccess`, `ScDemoThankYou`, `BhDemoIconTxtUI`, and `BhNavigationButton.OnPointerClick`.

Launch paths: `TryStartOfflineQuickMatch()` and `TryStartConfiguredNewGame()`, eventually using `Hex.Session.Loader.utt()`.

Map load alone is not enough validation. Confirm HUD binding, city open, recruitment, return to world, and absence of `BhHUDSession.ira` failures for custom factions.

