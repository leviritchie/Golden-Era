# AI Screen Perception → NVDA Consumer

Status: **in progress toward blind-playable**. Focus utterance surface is source-prepared; NVDA speech and full-mode play remain to prove live.

## Rule

NVDA (and any AssistiveSupport hierarchy later) must consume **Component 2 speech surface** only:

- `focus_snapshot` bridge command / MCP tool
- `ai_driver_bridge/focus_latest.json`
- `ai_driver_bridge/events/focus_*.json`

Fallback while migrating: `hover_snapshot` / `hover_latest.json` **only if** it carries a speech-safe `utterance`.

Do **not** pipe `screen_dump` or `visible_snapshot` wholesale into speech. Those are AI catalogs (`srSafe: false`).

## Companion

`tools/olden_a11y_nvda/watch_hover_nvda.py` prefers `focus_latest.json`, speaks `utterance` when `speechSafe=true`, and falls back to non-placeholder hover labels. Opt-in; fails closed if the DLL or NVDA is unavailable.

## Focus snapshot shape

- `schemaVersion`: `ai-driver.v1.focus-snapshot`
- `speechSafe`: whether `utterance` is safe to speak
- `utterance`: human sentence (dialog/quest/UI label/map name)
- `context`: mode, hero, quest, dialogTitle/dialogBody when known
- Nested raw `hover` lane kept for debugging — do not speak paths like `CanvasHeroHUDPanel/...` as content

## Product bar

Not done until a blind player can realistically play menu, adventure map, town, and battle from this surface (keyboard focus + spoken hover). Pilot testing against dump is paused; AI pilot later consumes the same focus stream.

## Proof labels

| Claim | Tier |
| --- | --- |
| Focus JSON + utterance emitter | source-prepared |
| Placeholder labels rejected (`New Text`) | source-prepared |
| NVDA speaks focus utterance | unproven until live companion + NVDA run |
| Keyboard focus browse ring | not implemented |
| Map passability / route speech | not implemented |
| Town / battle speech lanes | not implemented |
| AccessibilityModule Windows UIA | unproven on Unity 6000.0.66f1 |
