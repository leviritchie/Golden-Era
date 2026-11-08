# RAG Chunk: olden-era-playtest/150-retaliation-probes

`RetaliationForecastFix.cs` debounces rapid `BhHealDamageForecastPanel.Hide()` after `Show()`. Config keys: `retaliationForecastFix`, `retaliationForecastDebounceMs`. It is partial, not a full retaliation logic fix.

Probe patches use `[ProbePatch]` and are excluded from normal patching. They are loaded through separate Harmony only when retaliation debug is enabled.

Safe diagnostics are narrow, config-gated, capped, and log primitive fields/SIDs. Unsafe diagnostics include broad reflection across Unity/IL2CPP objects and generic component scans in runtime injected components.

