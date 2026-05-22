> [!IMPORTANT]
> This release is built for the Olden Era Steam build current on May 22, 2026. If Steam updates Olden Era after that, the copy this mod creates will be behind that patch number.
>
> The installer does not patch your Steam install in place. It copies your clean Steam game folder to a separate Golden Era folder and installs the mod into that copy only.

# Golden Era: A mod for Heroes of Might and Magic: Olden Era

The goal of this mod is to integrate HD-2D factions modeled after Heroes of Might and Magic 3 factions. The installer uses your Steam Olden Era folder as a clean source, creates a separate modded copy, and asks for a Heroes of Might and Magic 3 install directory, either HoMM3 Complete from GOG (recommended) or HoMM3: HD from Steam.

This is an experimental early-access mod. Stronghold is still the most complete reference faction, and newer faction ports are included at different maturity levels while balance, mechanics, UI, and asset coverage continue to evolve.

## Features

- Adds multiple HoMM3-inspired custom faction ports to Olden Era.
- Adds custom creature lineups, alternate creature upgrades, town screens, buildings, heroes, portraits, map sprites, unit animations, and music where available.
- Adds faction mechanics such as War Cries and other custom-faction rules as they are ported.
- Bundles the BepInEx IL2CPP loader, Golden Era plugin payload, and release-derived Core.zip overlay in one self-extracting installer EXE.
- Installs into a separate Golden Era game copy so launching Olden Era from Steam still runs the vanilla game.

## Current Faction Status

The current public package includes the expanded custom-faction framework and assets for Castle, Rampart, Tower, Inferno, Necropolis, Dungeon, Stronghold, Fortress, Conflux, and Cove. Stronghold remains the most complete reference implementation. I need your balance suggestions, since I spent the last month making this mod instead of playing Olden Era, so I don't know how to balance it.

## Major Known Bugs

- Some enemies on the map sneakily turn sideways, making them razor thin and hard to see.
- Not all factions have had the same hand tuning. Some are almost entirely placeholder effects.
- Sometimes, maps load with no HUD, requiring you to reload the map.
- The back arrow doesn't work in town menus. You have to click the relevant button, such as build tree, again.
- A million other little things.

## Installation

1. Make sure both Olden Era and Heroes of Might and Magic 3 are installed on your computer.
2. Download the current `GoldenEraModInstaller-*.exe` release asset and the matching `.sha256` file if you want to verify the download.
3. Run the installer. It will ask for your clean Steam Olden Era folder, a separate modded copy folder, and your HoMM3 installation.
4. Do not choose the Steam folder as the modded copy folder. The installer should refuse that, because the modded copy must be separate.
5. Wait for the installer to copy the game and apply the mod. It can take several minutes and needs enough free disk space for a second Olden Era copy.
6. Launch the modded copy with `Launch Golden Era.cmd` in the target folder, or by launching the mod folder's exe. Launching Olden Era from Steam should still run vanilla.

## Screenshots

![Quick play setup](screenshots/quickplay.gif)

![Adventure map](screenshots/adventuremap.gif)

![Town buildings](screenshots/buildings.gif)

![Recruitment screen](screenshots/recruitment.gif)

![Avenger interface](screenshots/avenger.gif)

## FAQ

### Will new updates to Olden Era break this mod?
Absolutely yes, especially in early access. The installer preserves your Steam folder and applies the mod to a separate game copy, but the modded copy still depends on Olden Era's current `Core.zip` layout. If Steam updates Olden Era, wait for a matching Golden Era package and run Repair against the modded copy.

### Can I still play vanilla Olden Era through Steam?
Yes. Steam should keep launching your untouched vanilla install. Use `Launch Golden Era.cmd` from the separate target folder when you want to play the mod.

### How do I submit bug reports, balance feedback, and suggestions?
Use the Issues tab in github and choose the relevant form: Bug report, Balance issue, or Suggestion. This repo is the only place feedback will be monitored.

### Why not make a discord server or subreddit for feedback?
Because I don't want to moderate one.

### Does this support multiplayer?
Multiplayer is entirely untested at this time.

### How do I donate to contribute to this project?
I likely will never accept donations. I have a great job and the goal of this side project was, in large part, to enrich my knowledge of AI coding tools as someone who is software-adjacent and has project management experience, but who is not a senior developer or computer science expert.

### Is this AI slop?
There are no AI-generated visuals or audio in this game. IDEs with coding LLM support were heavily used when building the mod, and that was, in some sense, the real purpose of me building this mod. See the "About Me" section for more details.

### My antivirus says this is malware
It's not, you can inspect the source to prove it. The installer is a large self-extracting EXE because it contains the mod payload, so you may have to click a "Run Anyway" button or something similar.

## About Me
I am a Senior Data Scientist with a long-time passion for video games. I have been working with and training language models since well before ChatGPT became popular, and for the sake of my career and knowledge, I was overdue on learning the ins and outs of various coding tools that have recently become available. This project began as an experiment to see what Cursor was capable of, and the scope of the project expanded as I explored other tools (Claude Code, Codex, Cline with Deepseek v4 Pro). Eventually, I decided to polish this up and open it to feedback, so I could learn a bit more about handling github issues and messy technical projects like this one.

## Credits

Special thanks to Aphra for creating the Tears of Ashan VCMI mod and for granting permission to use that mod's sprite recolors. Thanks to the dedicated HoMM3 modding community for decades of documentation on how to pull apart that game and put it back together.
