# RAG Chunk: olden-era-playtest/160-il2cpp-rebase

Use Il2CppDumper and repo tools under `Heroes of Might & Magic Olden Era Playtest/tools/` to regenerate `dump.cs`, `script.json`, and disassembly anchors after game updates.

Known Map.Init research shows failures before `buz..ctor` can come from `bua`, `bwe`, `bvh`, `bva`, or `bvk`. `bwe..ctor` mixes static Unity data with map subsystem init and is a key null-risk area.

Rebase search terms: `bdwu`, `oez`, `DamageUiParams`, `BhHealDamageForecastPanel`, `dzk`, `buv`, `but`, `SoFractions`, `BhHUDSession`, `ResManager`.

`dump.cs` method bodies are stubs. Use RVAs and disassembly for native null/control-flow analysis.

