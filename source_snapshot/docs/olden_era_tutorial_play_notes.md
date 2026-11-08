# Olden Era Tutorial Play Notes

These notes are live-observed from the vanilla Steam build on June 16, 2026, while playing `Tutorial Map` -> `Gameplay Basics`. They are intended for future agents who need to operate the game UI, not as design speculation.

## Agent Operating Principles

- In tutorial play, making discoveries quickly is more valuable than perfect play. Act, observe, and record the repeatable rule that explains what happened.
- Hovering is free and usually informative. Before committing to a click, hover over objects, route endpoints, enemies, unit stacks, buttons, and cards to learn the game's tooltip language.
- Prefer quick repeatable decision patterns over one-off optimization. For example: hover target, check highlight/path color, click once for preview, confirm only if the preview is executable.
- Learn the visual language from the game instead of guessing. Route color, hex outlines, cursor changes, stack highlights, tooltip text, scrollbar presence, and task checkmarks are stronger evidence than visual resemblance.
- A failed or non-executing click is still useful data. Record whether it produced a tooltip, preview path, target outline, blocked cursor, no state change, or a tutorial card.

## Main Menu

- The main menu is a left-column stack: `New Game`, `Load`, `Campaign`, `Tutorial`, `Challenges`, `Multiplayer`, `Extras`, `Settings`, and `Exit to Desktop`.
- `Tutorial` expands in place. The observed submenu entries were `Continue Tutorial` and `Tutorial Map`.
- Bottom-right main-menu buttons include `Bug Report` and social/community buttons. These can open external browser windows; avoid clicking them during gameplay automation unless that is the explicit task.

## Tutorial Selection

- `Tutorial Map` opens a parchment-style world map with a right-side details panel.
- `Gameplay Basics` is the first/main beginner mission. The right panel labels it `Main Mission` and says it teaches the basics of playing Heroes of Might and Magic.
- The mission panel has a `Select Difficulty` control above a green `Start Mission` button.

## Tutorial Dialogs

- Initial tutorial dialogs are modal overlays. They can be advanced or dismissed by left-clicking the dialog/window.
- Tutorial card sequences use `Continue` and `Close` buttons at the bottom of the card.
- Some tutorial cards have a vertical scrollbar on the right side of the text panel. If a scrollbar is visible, scroll to the bottom before recording the card as complete; otherwise later rules can be missed.
- The first intro says Olden Era is a tactical turn-based game about map exploration, recruiting and leveling heroes, developing cities, and battle.
- The second intro says the first mission is `Gameplay Basics`; completing it unlocks short challenges. It also says the tutorial is started from the menu on the right side of the tutorial map screen.

## Adventure Map Basics

- Active tasks are shown in the upper-left corner. In the first mission, the first task was `Move to the marked area`.
- The top bar shows resources. In the observed initial tutorial state all resource counts were `0`.
- The right sidebar shows hero/army slots and the large bottom-right hourglass used to advance the day.
- The bottom UI shows the selected hero portrait, hero name (`John Johnson` in the observed run), army slots, and visible stack counts.
- User-verified UI read: the green bar to the right of the selected hero portrait shows how much Movement the hero has left.
- The bottom-left mini-map shows discovered land and objective markers.

## Global Map Tutorial Cards

- `Global Map` page 1/5: the global map is the game world where objects, locations, and enemy forces are scattered.
- Page 2/5: most of the map starts covered by fog of war. Moving heroes and interacting with special reveal objects uncovers more of the world.
- Page 3/5: movement is a two-step left-click flow. First click marks/previews the route; second click confirms and sends the selected hero on the march. Movement consumes the hero's Movement points. Cursor shape indicates available actions or impossible movement.
- Page 4/5: camera movement options are right-drag, `WASD`, clicking the mini-map, or moving the cursor to an edge of the screen.
- Page 5/5: routes can only be placed through visible, passable areas. Fog of war, obstacles, and enemy squads block route planning. Route colors mean:
  - Green: regular route the hero can fully travel this turn.
  - Grey: not enough Movement points to reach this part of the path this turn.
  - Red: route ends in battle with an enemy squad or garrison.

## Movement Observations

- Do not identify the map hero by the horse-shaped cursor. The cursor itself changes into a horse over valid movement targets.
- The actual selected hero is the map unit with a selection ring and flag; in the observed first map step it was near the top of the revealed area.
- Do not identify roads, paths, trees, or passable terrain from low-resolution screenshots alone. Early observations were made from a 1280x720 Computer Use capture, which made tree canopy and terrain edges easy to misread. After changing Windows scaling, Computer Use captured the game at 1920x1080 and terrain/object separation was materially clearer, but route lines, tooltips, tutorial text, and selected-unit rings are still better evidence than visual guesses.
- Movement confirmation was only reliable after a visible green route appeared. The successful sequence was:
  1. Click a visible/passable destination tile to draw a green route.
  2. Click the same route endpoint again to execute movement.
- A red "blocked/no" cursor appeared over invalid terrain such as water or impassable tiles.
- The camera follows the hero after confirmed movement.
- It is possible to consume all Movement points before reaching the marked checkpoint. The tutorial then reports that the hero can no longer move because all Movement points have been used.
- If a route turns grey, check the green Movement bar beside the hero portrait before assuming the click failed. It may simply mean the hero cannot reach that endpoint this day.

## New Day / Movement Refresh

- When Movement points are depleted, the tutorial adds `Start a new game day` to the active task list.
- The large hourglass button at the bottom-right starts a new day.
- Starting a new day showed `Your turn begins`, checked off `Start a new game day`, displayed `Successfully saved!`, and restored the hero's Movement points.

## Follow The Road / Redwood Observatory

- After movement refresh, the next task was `Follow the road`. It completed only after the same movement pattern from the tutorial cards: click the target/route endpoint to preview, then click it again to execute.
- The next tutorial object was `Redwood Observatory`. Its tutorial text says interactive objects can remove fog of war in a large or huge radius, and that hovering an interactive object shows what it does.
- Observed Redwood Observatory tooltip: `Removes the fog of war in a huge radius around it. It's better than climbing a random tree!`
- Interacting with the Redwood Observatory used the same object interaction expectation from the tutorial text: double-click with left mouse on the object's actual base/hotspot. After interaction, a large surrounding area became visible.
- After the Observatory interaction, the main quest appeared as `Capture the city in the northeast of the map`.

## Gold Collection

- After the Observatory, the tutorial asked the player to collect nearby Gold before attacking the enemy. The active task became `Collect 5,000 Gold`.
- The top resource bar is the reliable source for current Gold total. In this observed run the count advanced to `5000` and the task checked off after the last pickup.
- Gold piles use normal route/object interaction rules: hover can show a tooltip, and movement to the pickup still depends on the hero having enough Movement points.
- Observed Gold tooltip: `Gives 400-800 Gold.`
- Do not assume a highlighted pickup failed just because the cursor/tooltip appears. In one observed case the hero was adjacent to a valid Gold pickup but did not collect until a new day restored Movement; after clicking the same object with Movement available, the Gold counter advanced from `4000` to `5000`.

## Battle Initiation

- After collecting `5,000 Gold`, the next task is `Attack the enemy further down the road`.
- Tutorial dialog text for this step: `Keep going and plot a route to the squad blocking your path. Your hero will start a battle as soon as he steps onto the square adjacent to that squad.`
- Enemy squad route previews use the same two-step movement pattern. First click creates a route ending in battle; the preview can show an enemy panel with skull difficulty, stack estimate, and `Right-click for more info`.
- Observed first enemy preview: `Easy Battle`, one visible enemy stack estimated `10-19`, and a red battle endpoint/route segment.
- Because the tutorial builds on movement, treat this preview as the route confirmation state rather than inventing a separate battle-start control.
- Proven correction: if clicking the enemy sprite or adjacent battle endpoint keeps the preview open, check route color and the hero Movement bar. In the observed run, the route line was grey/white because the hero did not have enough Movement left. Starting a new day restored movement and changed the route to green/yellow/red; clicking the red endpoint then transitioned to battle.

## Battle Basics

- Battle transition starts a `TACTICS PHASE`.
- First battle tutorial card title: `Battle Basics`.
- Tutorial text says battles take place on separate battlefields divided into hexes. Creatures move across hexes and engage in combat with enemies.
- Tutorial text says battles proceed in rounds. Once all stacks, both yours and the enemy's, have taken their turns, the next round begins.
- The large crossed-swords control at the bottom center ended the observed `TACTICS PHASE` and began the battle turn sequence.
- The top combat timeline shows upcoming stack turns grouped by round markers.
- During battle, a left hero panel shows hero stats/Focus-style resource and the bottom action bar exposes tactical buttons.
- Observed Focus tutorial panel text: Focus is a special resource used to activate creature and hero abilities. Using an ability spends Focus Charges. `1 Focus Charge = 6 Focus points.` The army generates Focus when creatures attack or take damage; all creatures generate Focus on attack except melee creatures, which generate more, and all creatures generate Focus when taking damage.

## Enemy Movement And Attack Tutorial

- Battle goal: defeat every unit in the enemy army. The player's creatures must attack enemy troops.
- Tutorial page 1/3 says there are three types of attacks. The first shown type is `Melee attack`, where the creature deals damage only when close to the target, on an adjacent hex.
- Page 2/3 says if a stack cannot currently attack, it can move closer to the enemy. Maximum movement distance depends on the creature's `Speed`.
- Page 2/3 also says a creature making a `Melee` or `Long Reach` attack can both approach and attack in the same turn.
- Page 3/3 says melee attacks may receive a counterattack in response. Counterattacks are limited; usually, creatures can counterattack only once per round.
- Page 3/3 introduces tactical options for situations where the player does not want a stack to attack or move.
- Scrolled page 3/3 details:
  - `Wait` delays the stack's action until the end of the current round, allowing others to act first. It can only be used once per round per stack.
  - `Skip Turn` makes the stack forfeit its action for the round; it cannot act again until the next round.
  - The tutorial advises planning battlefield positioning and strike timing to minimize losses from enemy counterattacks.

## June 18 Restart Continuation (Computer Use)

- The tutorial was resumed after a reload at the pre-combat stage and then fast-stepped through the remaining tutorial card flow with the verified 1280x720-style interaction points.
- Repeated clicks on the card footer (`~640,560`) were used to dismiss/advance the `Battle Basics` and `Enemy Movement and Attack` dialogs. The final card page was scrolled via `x:~804`, `y:~500`, `scrollY:550` before attempting close.
- Battle start was re-triggered from the lower-center tactics button (`~639,674`) and several quick movement/attack attempts were run on nearby battle hexes and enemy-adjacent targets using the repeatable discovery pattern (single click, observe, adjust/alternate).
- Notes status from this pass: the control input sequence executed successfully from the automation side, but this run could not capture readable accessibility/visual confirmation inside the current tool response path. Treat the exact final card/battle-state progression as unconfirmed in this pass until a visual capture with visible game feed is available.
