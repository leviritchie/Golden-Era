# RAG Chunk: olden-era-playtest/010-runtime-stack

Olden Era is Unity IL2CPP. The mod is a BepInEx 6 IL2CPP Harmony plugin targeting `netstandard2.1`.

Installed loader version, verified from `BepInEx/LogOutput.log` and `BepInEx/core/*.dll` assembly metadata on May 4, 2026: **BepInEx 6.0.0-be.755**, built from commit `3fab71a1914132a1ce3a545caf3192da603f2258`. The log also reports .NET runtime **6.0.7**.

Runtime stack: Unity player + `GameAssembly.dll`, IL2CPP metadata, BepInEx, generated interop under `BepInEx/interop`, `OfflineUnlockMod.dll`, Harmony patches, and JSON game data in `Core.zip`.

Obfuscated names such as `ejz.bdwu`, `ejy`, `dzk.bath`, `buv`, `but`, `fvh`, `fvf`, and `czk.uvl` are build-specific. Re-anchor them after game updates by signature, call site, stack trace, or disassembly.

Normal `[HarmonyPatch]` types are auto-discovered by `Plugin.PatchAnnotatedTypes()`. `[ProbePatch]` types are excluded unless probe Harmony is explicitly enabled. Avoid broad reflection across IL2CPP/Unity object graphs and avoid generic component-scan loops in injected runtime components.
