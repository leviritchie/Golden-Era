# RAG Chunk: olden-era-playtest/170-agent-workflow

Before edits run `git status --short` and distinguish user/staged changes from your own. Do not revert or unstage user work without explicit request.

Use source files over deployed outputs unless deployment is the task. Gate risky patches with config. Prefer narrow Harmony targets. Use `AgentDebugLog` and stable SIDs. Run build with `-p:DeployPluginToGame=false` for compile validation.

When you learn anything concrete about an obfuscated IL2CPP method, field, pointer chain, native dictionary, or donor/custom divergence, add it to `docs/il2cpp-semantic-map.md` with confidence and evidence. Record weak findings as Tentative and keep rejected interpretations when they would prevent repeated mistakes.

Repeated mistakes to avoid: icon-only hero portrait fixes, re-adding terrain-blend keywords to upright billboards, reviving runtime squad mirror fog loops, using `Sprites/Default` as primary map solution, treating map load as full validation, trusting obfuscated names after updates, broad IL2CPP reflection, and confusing display strings with implemented abilities.
