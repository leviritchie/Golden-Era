# RAG Chunk: olden-era-playtest/050-plugin-load

> Archived RAG snapshot. The original `0.1.124` registration list is historical and incomplete.

Plugin identity and version are defined by `Plugin.cs`; do not duplicate a supposedly current version here. `Plugin.Load()` now contains substantially more manual and dynamic registration than the May 2026 summary, including campaign/map, faction, battle, preview, economy, and diagnostic surfaces.

Use current `Plugin.cs`, `LauncherConfig.cs`, and the registration validators for load-order claims. Optional features should remain gated by `Prepare()` or explicit config before patching.
