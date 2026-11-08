# RAG Chunk: olden-era-playtest/140-damage-histogram

Damage histogram is implemented by `DamageHistogramOverlay.cs`, `DamageDistribution.cs`, `DamageKillMapping.cs`, `LuckCritMixture.cs`, and `DamageHistogramPanelUgui.cs`.

Hooks: `ejz.bdwu`, `ejz.oez`, `BhHealDamageForecastPanel.Show(ejy)`, and `BhHealDamageForecastPanel.Hide()`.

The engine forecast min/max remains authoritative. The mod uses HoMM3-style PMF shape: independent per-creature rolls up to stack size 10, then the HoMM3 10-roll scaling rule for larger stacks. Luck/crit mixture is applied afterward.

Known issue: retaliation chart can show when the game retaliation indicator does not. Revalidate DTO fields and row visibility after interop/game updates.

