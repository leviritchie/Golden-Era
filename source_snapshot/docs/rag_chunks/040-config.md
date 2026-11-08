# RAG Chunk: olden-era-playtest/040-config

> Archived RAG snapshot. The May 2026 live-state paragraph in the source knowledge base is not a current config contract.

Config is owned by `LauncherConfig.cs` and loaded through `LauncherConfigReader.TryLoad()` from the game-root file and mod config layers.

Current source defaults and the checked-in plugin config keep `homm3ImportApplyHarmony=false`; do not restore the old advice to leave it true. Other feature values must be read from the current config and loader rather than copied from this snapshot.

When bisecting, record the merged config snapshot logged by `Plugin.Load()`. Config can mask code bugs.
