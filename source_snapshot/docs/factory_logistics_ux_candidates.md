# Factory Logistics: UX candidate list (2026-11-16)

A Fable 5.2 subagent generated this list by reading the spec, the config, the overlay texts, the viewer and
upgrade-panel code, and DECISIONS.md. It changed no files. Nothing here is approved: it is a menu for the owner to pick
from.

Tags: effort S/M/L, impact low/med/high. "#N" points to entries in
`V:/olden_port_work/factory_logistics/DECISIONS.md`.

## Onboarding & explanation

1. **First-open primer card.** A dismissible 4-step strip in the viewer: visit → build → link by range → manage
   remotely. Today the only explanation is the skill and spell text. [S] [high]
2. **Rewrite skill and spell text around that loop.** Say what a visit unlocks and that range limits links. The
   Upgrade Center sentence is appended to every rank text without saying why it matters. [S] [high]
3. **One glossary, one unit.** The header shows "range 200 MP", cut labels say "+3 range needed" (levels), and the
   legend says "range levels short". The panels mix Upgrade Center / enhancement / effective / Mobile Command Center
   level. Pick one range unit (tiles or hero-days) and consider renaming Upgrade Center (e.g. "Surveyed"). [S] [high]
4. **"?" help in the viewer and the build panel.** A hover glossary for hub, range, Upgrade Center and switch. Level
   lines already have tips; the concepts have none. [S] [med]
5. **Suggested first build.** Mark one recommended enhancement per building (e.g. Byproduct on a first mine). Up to
   8 options are currently shown with equal weight. [S] [med]

## Viewer conveniences

6. **Network totals bar.** Show gold/day, gold/week, extra resources, extra units/week, and what was given up (mines
   that stopped producing). No total exists anywhere. [M] [high]
7. **Concrete numbers, not multipliers.** Show "+250 gold/day, loses 1 crystal/day" instead of "2x your market sell
   value". Do the same for Mercenary HQ, Food, Support Hub and Byproduct. [M] [high]
8. **Before/after preview on hover of Build/Upgrade/Switch.** Show the income change and ghost the routes that would
   appear or vanish. Resources and the weekly switch are currently committed blind. [L] [high]
9. **Range overlay for the selected building.** Shade the reachable tiles, with hub refresh visible. Today range only
   shows as routes and red X marks. [M] [high]
10. **"Why is this cut?" with fixes.** Clicking a red X lists the options: build a hub here, raise a Rail Station,
    kill this stack, explore the fog. [M] [high]
11. **Explain no-path cases.** Show a reason on the card: other map level, water, unexplored, guarded. No-path
    routes draw nothing today (#12, #15, #16). [M] [med]
12. **Filters and a to-do list.** Toggles per effect type, plus a side list: unvisited, unenhanced, switch available,
    under construction, cut. Clicking an entry centres the view on it. [M] [med]
13. **Keyboard shortcuts.** Tab to cycle buildings, a key for the next unvisited one, number keys for tabs. Only Esc,
    wheel and drag exist today. [S] [med]
14. **Tab names and visibility.** Rename the "Active enhancement" tab to say it switches. Show Hire greyed out with
    "needs Rail Network active" instead of hiding it. [S] [med]
15. **Legend additions.** Hub ring, pending/under construction, unvisited marker. [S] [low]
16. **Delivery target up front.** Show the target army and its free slots under "Deliver to". The garrison → visitor
    refusals (#50) are a surprise today. [S] [med]

## Adventure-map & panel feedback

17. **Map badges over owned buildings.** Show "can be enhanced", "active enhancement + level" and "not visited".
    Nothing on the adventure map says a mine is enhanceable. [M] [high]
18. **Day/week start digest.** One banner listing remote builds finished, switches applied, weekly switch reset and
    network income. Pending changes apply silently today (#23). [M] [high]
19. **Capture loss notice.** Capture silently and permanently wipes every enhancement on the building (#22); say what
    was lost and where. [S] [high]
20. **"Open network here" from the build panel, and "go to building" from a viewer card.** [S] [med]
21. **Dedicated HUD button or hotkey for the viewer** instead of only the spellbook. [M] [med]
22. **Hint for heroes without the skill.** On visit, show "a Logistics hero can enhance this building". [S] [med]
23. **Open the panel after a won guard battle.** Today such a visit opens nothing (#24). [S] [low]
24. **Range status in the build panel.** Show "linked to: town X, 2 buildings" or "isolated: N short". [S] [med]

## Rule/design simplifications

25. **Flat hub rule.** Replace "refresh 33/66/100% of spent range, floored" with: a hub restarts range at 50/75/100%
    of full. [M] [high]
26. **Collapse Upgrade Center into "visited".** One visit by any skilled hero unlocks remote builds up to the player's
    best skill rank. This removes the per-building level and the chore of re-visiting with a better hero. [M] [high]
27. **One timing rule.** Today on-site actions are instant, remote ones land next day, a remote build auto-activates
    but an on-site one may not, and Food L3 is instant. Make everything next-day, or everything instant with a visible
    cooldown. [M] [high]
28. **Tag "Replaces output" vs "Adds to output"** on every option. Seven enhancements stop base production, and only
    their L1 text says so. [S] [high]
29. **Flatten Power Station maths, or display the powered value.** Hidden extrapolations reach 7x or 21x today.
    [M] [med]
30. **Count each town once** across overlapping Manufactories or Synthesizers (#55). [S] [low]
31. **Drop or fold in Rail Network's private range bonus.** It is a second range concept. [S] [med]

## Subagent's top 5

1. #6 + #7: totals and concrete numbers
2. #17: adventure-map badges
3. #9 + #10: range overlay, plus "why cut, how to fix"
4. #27: one timing rule
5. #3: one glossary and one range unit
