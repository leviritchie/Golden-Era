# IL2CPP Semantic Map

Use `docs/il2cpp-semantic-map.md` as the working translation table for obfuscated native symbols. The goal is to attach inferred names to methods, fields, and pointer chains using static disassembly, runtime logs, data SIDs, and vanilla donor comparisons.

Confidence levels:

- Known: exposed by interop name, enum, JSON field, method signature, or logged SID.
- Strong inference: disassembly and runtime behavior agree across a meaningful scenario.
- Tentative: plausible from call flow, field offset, or one runtime observation.
- Rejected: disproven interpretation or unsafe fix path kept as a warning.

Current battle ability anchors:

- `ecf.baak()` is strongly inferred as the hero ability availability gate.
- `ekn(dyu,bool,bool)` is the ability view wrapper; `ekn.cgci` is strongly inferred as wrapper enabled/available.
- `BhHeroAbilitiesView.ryt/ryu` build hero ability buttons and pass wrappers to `BhHeroAbilitiyView.rzt`.
- `BhHeroAbilitiyView.rzt` is strongly inferred as hero ability button bind.
- `BhHeroAbilitiesView.rzi/ryy/ryw` and `crg.tuq/tun/tur/...` are still tentative controller/refresh/click-path methods.

Warcries principle: if `wrapperEnabled=True` during `rzt` but the button later appears grey, investigate the `BhHeroAbilitiesView` / `crg` refresh/controller path before changing Focus cost or `ecf.baak()` again. Compare against Dungeon/Triumvirate's Strength before promoting semantic names.

Safety warnings:

- Do not call `BhHeroAbilitiyView.rzu(true)` from an `rzt` postfix; that caused recursive `rzt -> rzu -> rzt` crashes.
- Do not patch every apparent `ecf` energy alias; a broad alias patch caused battle-start recursion in `DynamicClass.DMD<ecf::jtq>`.
- Keep probes bounded and SID-filtered.
- Prefer data/registry fixes when a vanilla donor enters a native dictionary that the custom SID misses.

