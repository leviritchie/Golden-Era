# RAG Chunk: olden-era-playtest/030-build-deploy

> Archived RAG snapshot corrected for the current build contract. Exact payload lists still require `.csproj` inspection.

Build from `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`. Golden Era compile claims require `OfficialDeobfBuild=true` and the configured Steam Golden Era `GameRoot`; a plain build is not live-interop proof.

Use `DeployPluginToGame=false` for compile-only validation. Normal deploy copies the plugin and manifest-owned source assets, including `homm3_hero_portraits/`, but intentionally excludes `tools/homm3_import/build_out/custom_units_*` bundles.

`DeployHomm3Bundles=true` is explicit opt-in and must pass the payload-directory validator before copying generated bundles. Never infer bundle deployment from a successful ordinary build.
